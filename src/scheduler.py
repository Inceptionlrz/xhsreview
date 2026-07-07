"""
调度器：协调抓取、AI 生成、回复、统计
"""

import time
import random
import threading
from typing import Optional, Callable, Dict, Any, List

from .anthropic_client import AnthropicClient
from .xhs_crawler import XhsCrawler


class Scheduler:
    """
    调度器：单线程顺序执行，避免账号风险

    设计：
    - 主循环在自己线程中跑（与 UI 线程分离）
    - 所有 XhsCrawler 调用现在已线程安全（内部用 worker 隔离 Playwright）
    - 板块 / 关键词从 config 读取后传给 fetch_feed
    """

    def __init__(self, crawler: XhsCrawler, ai: AnthropicClient,
                 config: Dict[str, Any],
                 log_fn: Optional[Callable[[str, str], None]] = None,
                 state_fn: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.crawler = crawler
        self.ai = ai
        self.config = config
        self.log_fn = log_fn or (lambda l, m: None)
        self.state_fn = state_fn or (lambda s: None)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._processed_ids: set = set()
        self._state = {
            "running":    False,
            "started_at": 0.0,
            "posts_seen": 0,
            "posts_read": 0,
            "liked":      0,
            "replied":    0,
            "errors":     0,
        }

    # ---------------- 控制 ----------------
    def start(self) -> tuple[bool, str]:
        if self._thread and self._thread.is_alive():
            return False, "已在运行中"
        self._stop_event.clear()
        self._state.update({
            "running":    True,
            "started_at": time.time(),
            "posts_seen": 0, "posts_read": 0,
            "liked": 0, "replied": 0, "errors": 0,
        })
        ok, msg = self.crawler.start()
        if not ok:
            self._state["running"] = False
            return False, msg
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return True, "已启动"

    def stop(self, reason: str = "用户手动停止"):
        if not self._state["running"]:
            return
        self._stop_event.set()
        self._log("warn", f"正在停止：{reason}")
        if self._thread:
            self._thread.join(timeout=5)
        try:
            self.crawler.stop()
        except Exception:
            pass
        self._state["running"] = False
        self._publish_state()
        self._log("info", "已停止")

    def is_running(self) -> bool:
        return self._state["running"]

    # ---------------- 主循环 ----------------
    def _run(self):
        try:
            mode = self.config.get("mode", "unlimited")
            post_limit = int(self.config.get("post_limit", 50))
            time_limit = int(self.config.get("time_limit", 30)) * 60
            crawl_mode = self.config.get("crawl_mode", "deep")
            scroll_times = 3 if crawl_mode == "deep" else 1

            # 板块 + 关键词
            enabled_cats = self.config.get("enabled_categories") or []
            keyword = (self.config.get("search_keyword") or "").strip()

            # 板块选择：取第一个启用的板块作为抓取目标
            category = enabled_cats[0] if enabled_cats else ""

            self._log("ok", f"开始运行 | 模式={mode} | 板块={category or '全部'}"
                           f" | 关键词={keyword or '(无)'}")
            self._log("info", "📊 统计追踪已启动：将记录点赞次数 / 评论次数")
            self._publish_state()

            batch_count = 0
            empty_rounds = 0
            while not self._stop_event.is_set():
                if mode == "count" and self._state["posts_seen"] >= post_limit:
                    self._log("ok", f"达到帖子数上限 {post_limit}，自动停止")
                    break
                if mode == "time":
                    elapsed = time.time() - self._state["started_at"]
                    if elapsed >= time_limit:
                        self._log("ok", f"达到时间上限 {time_limit // 60} 分钟，自动停止")
                        break

                # 抓一批
                feed = self.crawler.fetch_feed(
                    scroll_times=scroll_times,
                    category=category,
                    keyword=keyword,
                )
                if not feed:
                    empty_rounds += 1
                    if empty_rounds >= 3:
                        self._log("warn", "连续 3 次未抓到内容，停止")
                        break
                    time.sleep(3)
                    continue
                empty_rounds = 0

                batch_count += 1
                self._log("info", f"=== 第 {batch_count} 批：{len(feed)} 条候选 ===")

                for post in feed:
                    if self._stop_event.is_set():
                        break
                    self._state["posts_seen"] += 1
                    note_id = post.get("note_id", "")
                    if not note_id or note_id in self._processed_ids:
                        continue

                    # 进入详情（传入 feed 标题作为降级）
                    detail = self.crawler.open_note(note_id, fallback_title=post.get("title", ""))
                    if not detail:
                        self._state["errors"] += 1
                        continue
                    self._processed_ids.add(note_id)
                    self._state["posts_read"] += 1
                    self._publish_state()

                    # 详情页需要登录 → 跳过 like/reply
                    if detail.get("login_required"):
                        self._log("warn", f"跳过（需登录）: {detail.get('title','')[:30]}")
                        # 更新 crawler 登录状态，避免后续帖子白白尝试
                        with self.crawler._logged_in_lock:
                            self.crawler._logged_in = False
                        self._maybe_wait()
                        continue

                    if crawl_mode == "deep":
                        time.sleep(random.uniform(1.5, 3.5))
                    else:
                        time.sleep(random.uniform(0.6, 1.4))

                    # 点赞（需登录）
                    if (self.config.get("auto_like")
                            and self.crawler.is_logged_in
                            and random.randint(1, 100) <= int(self.config.get("like_rate", 0))):
                        if self.crawler.like_note(note_id):
                            self._state["liked"] += 1
                            self._log("ok", f"👍 点赞({self._state['liked']}次): {detail.get('title','')[:30]}")
                            self._publish_state()
                        time.sleep(random.uniform(0.3, 0.8))

                    # AI 回复（需登录）
                    if (self.config.get("auto_reply")
                            and self.crawler.is_logged_in
                            and random.randint(1, 100) <= int(self.config.get("reply_rate", 0))):
                        title = detail.get("title", "")
                        content = detail.get("content", "")
                        if not (title or content):
                            continue
                        self._log("info", f"🧠 正在生成回复: {title[:30]}")
                        reply = self.ai.generate_reply(
                            post_title=title,
                            post_content=content,
                            persona=self.config.get("api_persona", "友好、有趣的小红书用户"),
                            max_tokens=int(self.config.get("api_max_tokens", 256)),
                            temperature=float(self.config.get("api_temperature", 0.85)),
                        )
                        if not reply:
                            self._log("err", f"AI 生成失败: {self.ai.last_error or '未知'}")
                            self._state["errors"] += 1
                        else:
                            ok, msg = self.crawler.post_comment(note_id, reply)
                            if ok:
                                self._state["replied"] += 1
                                self._log("ok", f"💬 已回复({self._state['replied']}次): {reply[:60]}")
                            else:
                                self._log("err", f"回复失败: {msg}")
                                self._state["errors"] += 1
                            self._publish_state()

                    self._maybe_wait()

                self._publish_state()

            self._log("ok", "本轮运行结束")
            # ── 运行摘要统计 ──
            s = self._state
            self._log("ok",
                f"📊 运行摘要 | 浏览{s['posts_seen']}帖 · 爬楼{s['posts_read']}条"
                f" | 👍点赞{s['liked']}次 | 💬评论{self._state.get('replied', 0)}次"
                f" | ❌错误{s['errors']}次")
        except Exception as e:
            self._log("err", f"调度异常: {e}")
            import traceback
            self._log("err", traceback.format_exc())
        finally:
            self._state["running"] = False
            self._publish_state()

    def _maybe_wait(self):
        if not self.config.get("enable_wait", True):
            return
        wmin = float(self.config.get("wait_min", 1))
        wmax = float(self.config.get("wait_max", 3))
        if wmax <= 0:
            return
        delay = random.uniform(wmin, wmax)
        end = time.time() + delay
        while time.time() < end and not self._stop_event.is_set():
            time.sleep(0.1)

    # ---------------- 辅助 ----------------
    def _log(self, level: str, msg: str):
        try:
            self.log_fn(level, msg)
        except Exception:
            pass

    def _publish_state(self):
        try:
            self.state_fn(dict(self._state))
        except Exception:
            pass
