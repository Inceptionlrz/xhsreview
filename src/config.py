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
