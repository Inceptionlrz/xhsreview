"""
配置管理：持久化运行参数、API 设置、板块筛选等
"""

import os
import json
from typing import Dict, Any


DEFAULT_CONFIG: Dict[str, Any] = {
    # === API 配置 ===
    "api_base_url":  "https://api.anthropic.com",
    "api_key":       "",
    "api_model":     "claude-3-5-sonnet-20241022",
    "api_persona":   "友好、有趣、真实的小红书用户",
    "api_max_tokens": 256,
    "api_temperature": 0.85,
    "proxy":         "",

    # === 浏览器 ===
    "headless":      False,
    "use_mock":      True,
    "user_data_dir": "",

    # === 运行模式 ===
    "mode":          "unlimited",
    "post_limit":    50,
    "time_limit":    30,
    "crawl_mode":    "deep",

    # === 搜索关键词（覆盖板块，留空则用板块推荐流） ===
    "search_keyword": "",

    # === 行为概率 ===
    "auto_like":     False,
    "like_rate":     30,
    "auto_reply":    True,
    "reply_rate":    80,
    "enable_wait":   True,
    "wait_min":      1,
    "wait_max":      3,

    # === 拟人化 / 防封（核心：让自动化行为难以被平台风控识别） ===
    # 所有旋钮均可单独关闭；默认值偏「安全且自然」，可根据账号权重自行调激进/保守。
    "humanize": {
        # 总开关：关闭后所有拟人化逻辑退化为原有的简单随机行为
        "enabled":                 True,

        # —— 打字拟人 ——
        "type_min_delay":          0.06,   # 每个字符基础延迟下限（秒）
        "type_max_delay":          0.20,   # 每个字符基础延迟上限（秒）
        "type_pause_prob":         0.10,   # 输入过程中偶发「卡顿停顿」的概率
        "type_pause_min":          0.30,   # 卡顿停顿时长下限（秒）
        "type_pause_max":          1.00,   # 卡顿停顿时长上限（秒）
        "type_typo_rate":          0.05,   # 偶发「打错一个字再删掉」的结巴概率（净输出不变）

        # —— 阅读停留（评论前先「读完帖子」） ——
        "read_enabled":            True,
        "read_per_char":           0.010,  # 每字符阅读耗时（秒），帖子越长停留越久
        "read_min":                1.5,    # 最短阅读停留（秒）
        "read_max":                5.0,    # 最长阅读停留上限（秒，避免过长）

        # —— 滚动拟人 ——
        "scroll_human":            True,
        "scroll_pause_prob":       0.30,   # 滚动过程中偶发停顿「看一眼」的概率
        "scroll_back_prob":        0.25,   # 偶发向上回滚（模拟回看）的概率

        # —— 鼠标拟人移动（点击前先曲线靠近，避免瞬移） ——
        "mouse_human_move":        True,
        "mouse_overshoot_prob":    0.40,   # 落点前偶发「过冲再修正」，比直线更拟真
        "hesitate_prob":           0.04,   # 偶发「犹豫了没点赞」（只靠近不点，模拟真人）

        # —— AI 回复内容拟人（防「AI 味」与人工审核） ——
        "no_comment_rate":         12,     # % 概率「看了但不评论」（连 AI 调用都省，更自然）
        "content_typo_rate":       0.15,   # 偶发轻微错别字（同音/形近，不影响理解）
        "content_emoji_rate":      0.50,   # 偶发追加 1 个随机 emoji（自然口语化）
        "content_truncate_rate":   0.12,   # 偶发只保留前半句（短评更真实）
        "glance_comments":         True,   # 评论前先下滑「看一眼」已有评论再回来

        # —— 行为节奏 ——
        "skip_rate":               20,     # % 概率完全跳过某帖（只浏览，不点赞不评论）
        "long_break_prob":         0.07,   # 每帖处理后偶发「长休息」的概率
        "long_break_min":          30,     # 长休息时长下限（秒）
        "long_break_max":          120,    # 长休息时长上限（秒）

        # —— 会话安全上限（防频次异常） ——
        "session_action_cap":      35,     # 累计点赞+评论达到该值后强制长休
        "session_break_min":        120,    # 会话长休下限（秒）
        "session_break_max":        300,   # 会话长休上限（秒）

        # —— 操作顺序随机 ——
        "randomize_order":         True,   # 每帖随机决定「先赞后评 / 先评后赞 / 只做其一」
    },

    # === 板块（小红书真实板块） ===
    "categories": {
        "推荐":      True,
        "世界杯":    False,
        "穿搭":      True,
        "美食":      True,
        "彩妆":      True,
        "影视":      False,
        "职场":      False,
        "情感":      False,
        "家居":      False,
        "游戏":      False,
        "旅行":      False,
        "健身":      False,
        "视频":      False,
    },
}


class Config:
    def __init__(self, path: str = None):
        self.path = path or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config", "config.json",
        )
        self.data: Dict[str, Any] = {}
        self.load()

    def load(self) -> Dict[str, Any]:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                merged = dict(DEFAULT_CONFIG)
                for k, v in saved.items():
                    if isinstance(v, dict) and isinstance(merged.get(k), dict):
                        merged[k].update(v)
                    else:
                        merged[k] = v
                self.data = merged
            except Exception:
                self.data = dict(DEFAULT_CONFIG)
        else:
            self.data = dict(DEFAULT_CONFIG)
        return self.data

    def save(self) -> bool:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value

    def category_enabled(self, name: str) -> bool:
        return bool(self.data.get("categories", {}).get(name, False))

    def enabled_categories(self) -> list:
        return [k for k, v in self.data.get("categories", {}).items() if v]
