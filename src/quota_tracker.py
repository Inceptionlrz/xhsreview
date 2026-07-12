"""跨日配额 / 运营画像追踪。

为什么需要它：
- 小红书风控除了看单会话行为，还会看「每日总操作量」和「活跃时间分布」。
- 24 小时匀速在线、凌晨仍在点赞评论，是极强 bot 信号。
- QuotaTracker 把当天点赞/评论数持久化到本地文件，跨重启累计，
  并支持「只在指定时段运行」，把运营节奏压到更像真人。
"""

import os
import json
import time
from datetime import datetime, date
from typing import Dict, Any, Tuple


class QuotaTracker:
    def __init__(self, path: str = None):
        self.path = path or self._default_path()
        self._today = date.today().isoformat()
        self._data: Dict[str, Any] = {
            "date": self._today,
            "liked": 0,
            "replied": 0,
            "last_run_start": 0.0,
            "last_run_end": 0.0,
        }
        self._ensure_dir()
        self.load()

    @staticmethod
    def _default_path() -> str:
        # 放在项目根目录 .workbuddy 下，该目录已被 .gitignore 忽略
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base, ".workbuddy", "daily_quota.json")

    def _ensure_dir(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
        except Exception:
            pass

    def load(self):
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                saved = json.load(f)
        except Exception:
            return

        # 日期切换：新的一天自动重置计数
        if saved.get("date") == self._today:
            self._data = saved
        else:
            self._data = {
                "date": self._today,
                "liked": 0,
                "replied": 0,
                "last_run_start": 0.0,
                "last_run_end": 0.0,
            }

    def save(self):
        try:
            self._ensure_dir()
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ---------------- 计数器 ----------------
    def add_like(self, n: int = 1):
        self._data["liked"] = self._data.get("liked", 0) + n
        self.save()

    def add_reply(self, n: int = 1):
        self._data["replied"] = self._data.get("replied", 0) + n
        self.save()

    def counts(self) -> Dict[str, int]:
        return {"liked": self._data.get("liked", 0), "replied": self._data.get("replied", 0)}

    def total_actions(self) -> int:
        return self.counts()["liked"] + self.counts()["replied"]

    # ---------------- 运行时段控制 ----------------
    def record_run_start(self):
        self._data["last_run_start"] = time.time()
        self.save()

    def record_run_end(self):
        self._data["last_run_end"] = time.time()
        self.save()

    def time_since_last_run(self) -> float:
        """距离上次运行结束已过去多少秒（从未运行过则返回无穷大）。"""
        end = self._data.get("last_run_end", 0.0)
        if end <= 0:
            return float("inf")
        return time.time() - end

    # ---------------- 活跃时间窗口 ----------------
    @staticmethod
    def _parse_hhmm(t: str) -> Tuple[int, int]:
        """把 '09:00' 解析成 (9, 0)，非法时返回 (0, 0)。"""
        try:
            h, m = t.split(":")
            return int(h), int(m)
        except Exception:
            return 0, 0

    def within_active_hours(self, start: str, end: str) -> bool:
        """判断当前时间是否在 [start, end] 之间（支持跨午夜）。"""
        now = datetime.now()
        sh, sm = self._parse_hhmm(start)
        eh, em = self._parse_hhmm(end)
        start_min = sh * 60 + sm
        end_min = eh * 60 + em
        cur_min = now.hour * 60 + now.minute

        if start_min <= end_min:
            return start_min <= cur_min <= end_min
        # 跨午夜，例如 23:00-09:00
        return cur_min >= start_min or cur_min <= end_min

    def seconds_until_window(self, start: str) -> int:
        """距离下一个活跃窗口开始还有多少秒。"""
        now = datetime.now()
        sh, sm = self._parse_hhmm(start)
        start_min = sh * 60 + sm
        cur_min = now.hour * 60 + now.minute
        if cur_min < start_min:
            return (start_min - cur_min) * 60 - now.second
        # 窗口在明天
        return (24 * 60 - cur_min + start_min) * 60 - now.second

    # ---------------- 限制检查 ----------------
    def check(self, cfg: Dict[str, Any]) -> Tuple[bool, str]:
        """启动前 / 运行中检查是否还能继续操作。

        返回 (can_run, reason)；can_run=False 时应当停止或长休。
        """
        enabled = bool(cfg.get("daily_quota_enabled", False))
        if not enabled:
            return True, ""

        # 每日总量上限
        liked_lim = int(cfg.get("daily_like_limit", 0))
        replied_lim = int(cfg.get("daily_reply_limit", 0))
        c = self.counts()
        if liked_lim > 0 and c["liked"] >= liked_lim:
            return False, f"本日点赞已达上限 {liked_lim} 次，停止运行"
        if replied_lim > 0 and c["replied"] >= replied_lim:
            return False, f"本日评论已达上限 {replied_lim} 次，停止运行"

        # 活跃时段
        if bool(cfg.get("active_hours_enabled", False)):
            start = cfg.get("active_hours_start", "09:00")
            end = cfg.get("active_hours_end", "23:00")
            if not self.within_active_hours(start, end):
                wait = self.seconds_until_window(start)
                return False, f"当前不在活跃时段 {start}-{end}，{wait // 60} 分钟后恢复"

        # 最小重启间隔（防止反复停止-启动刷量）
        interval_min = int(cfg.get("min_restart_interval_min", 0))
        if interval_min > 0:
            elapsed = self.time_since_last_run() / 60.0
            if elapsed < interval_min:
                wait_sec = int((interval_min - elapsed) * 60)
                return False, f"距离上次运行仅 {elapsed:.0f} 分钟，需间隔 {interval_min} 分钟，剩余 {wait_sec // 60} 分钟"

        return True, ""
