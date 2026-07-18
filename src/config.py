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
    # 人设池：运营时从中随机轮换，打破「单一完美声音」指纹（留空则只用上面的 api_persona）
    "persona_pool":  [
        "一个爱逛小红书的普通女生，说话随意、爱用表情",
        "有点社恐但热心的大学生，评论常常很简短",
        "刚工作不久的打工人，偶尔吐槽偶尔种草",
        "爱蹲好物的懒人党，看到有用的就马住",
        "话不多但会认真看完帖子的路人",
    ],
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

    # === 搜索筛选（对应网页端「筛选」面板） ===
    "search_filters": {
        "sort_by":      "综合",
        "note_type":    "不限",
        "publish_time": "不限",
        "search_scope": "不限",
        "location":     "不限",
    },

    # === 行为概率 ===
    "auto_like":     False,
    "like_rate":     10,      # 默认极低：警告后已确认高频点赞是强风控信号
    "auto_reply":    True,
    "reply_rate":    25,      # 默认极低：多数帖子只浏览，少量帖子回复
    "enable_wait":   True,
    "wait_min":      3,       # 帖子间最短等待
    "wait_max":      8,       # 帖子间最长等待

    # === 运营画像 / 跨日风控（P1：警告后补上的关键层） ===
    # 平台会看「每日总操作量」和「活跃时间分布」。24 小时匀速在线、凌晨仍在操作是极强 bot 信号。
    "daily_quota_enabled":   True,
    "daily_like_limit":        15,       # 每日点赞上限（跨重启累计）
    "daily_reply_limit":       12,       # 每日评论上限（跨重启累计）
    "active_hours_enabled":    True,
    "active_hours_start":      "09:00",  # 真人活跃开始时间
    "active_hours_end":        "23:00",  # 真人活跃结束时间
    "min_restart_interval_min": 30,       # 两次运行最小间隔（分钟）

    # === 拟人化 / 防封（核心：让自动化行为难以被平台风控识别） ===
    # 所有旋钮均可单独关闭；默认值偏「安全且自然」，可根据账号权重自行调激进/保守。
    "humanize": {
        # 总开关：关闭后所有拟人化逻辑退化为原有的简单随机行为
        "enabled":                 True,

        # —— 打字拟人 ——
        "type_min_delay":          0.08,   # 每个字符基础延迟下限（秒）
        "type_max_delay":          0.35,   # 每个字符基础延迟上限（秒）
        "type_pause_prob":         0.15,   # 输入过程中偶发「卡顿停顿」的概率
        "type_pause_min":          0.50,   # 卡顿停顿时长下限（秒）
        "type_pause_max":          1.50,   # 卡顿停顿时长上限（秒）
        "type_typo_rate":          0.08,   # 偶发「打错一个字再删掉」的结巴概率（净输出不变）

        # —— 阅读停留（评论前先「读完帖子」） ——
        "read_enabled":            True,
        "read_per_char":           0.015,  # 每字符阅读耗时（秒），帖子越长停留越久
        "read_min":                2.5,    # 最短阅读停留（秒）
        "read_max":                8.0,    # 最长阅读停留上限（秒，避免过长）

        # —— 滚动拟人 ——
        "scroll_human":            True,
        "scroll_pause_prob":       0.40,   # 滚动过程中偶发停顿「看一眼」的概率
        "scroll_back_prob":        0.30,   # 偶发向上回滚（模拟回看）的概率

        # —— 鼠标拟人移动（点击前先曲线靠近，避免瞬移） ——
        "mouse_human_move":        True,
        "mouse_overshoot_prob":    0.50,   # 落点前偶发「过冲再修正」，比直线更拟真
        "hesitate_prob":           0.06,   # 偶发「犹豫了没点赞」（只靠近不点，模拟真人）

        # —— AI 回复内容拟人（防「AI 味」与人工审核） ——
        "no_comment_rate":         25,     # % 概率「看了但不评论」（连 AI 调用都省，更自然）
        # 通用反应：一定概率直接发一条真人常用口语反应（前排/蹲一个/收藏了/单个 emoji…），
        # 跳过 AI 生成。这是抗「AI 运营」检测最有效的一招——此类低信息评论几乎不可能被判为 AI。
        "generic_reply_rate":      45,     # % 概率发通用反应而非调用 AI（在「决定要评论」之后）
        "content_min_post_len":    25,     # 帖子正文不足该字数时，强制走通用反应（内容太少无料可评）
        "content_vary_voice":      True,   # 让 AI 每次随机切换语气（纯情绪/反问/含糊/共情/切题）
        "persona_rotate":          True,   # 每帖从 persona_pool 随机选人设（打破单一声音指纹）
        "content_typo_rate":       0.20,   # 偶发轻微错别字（同音/形近，不影响理解）
        "content_emoji_rate":      0.40,   # 偶发追加 1 个随机 emoji（自然口语化）
        "content_truncate_rate":   0.18,   # 偶发只保留前半句（短评更真实）
        "glance_comments":         True,   # 评论前先下滑「看一眼」已有评论再回来

        # —— 行为节奏 ——
        "skip_rate":               45,     # % 概率完全跳过某帖（只浏览，不点赞不评论）
        "long_break_prob":         0.15,   # 每帖处理后偶发「长休息」的概率
        "long_break_min":          45,     # 长休息时长下限（秒）
        "long_break_max":          180,    # 长休息时长上限（秒）

        # —— 会话安全上限（防频次异常） ——
        "session_action_cap":      20,     # 累计点赞+评论达到该值后强制长休
        "session_break_min":        180,    # 会话长休下限（秒）
        "session_break_max":        600,   # 会话长休上限（秒）

        # —— 操作顺序随机 ——
        "randomize_order":         True,   # 每帖随机决定「先赞后评 / 先评后赞 / 只做其一」
    },

    # === 养号模式（极低频 / 只看不评 / 随机长休息） ===
    # 账号被平台判定为 AI 运营后的「冷启动」用：几乎只浏览、极少量点赞、绝不评论、
    # 帖子间等待与长休息大幅拉长。开启后 scheduler 会用下面 nurture 覆盖关键参数。
    "nurture_mode":  False,
    "nurture": {
        "auto_reply":          False,   # 只看不评
        "auto_like":           True,    # 极低频点赞（配合下方 like_rate，每日仅约 3 次）
        "like_rate":            3,      # 极低频点赞（每日仅约 3 次）
        "skip_rate":           85,      # 绝大多数帖子纯浏览跳过
        "wait_min":             8,      # 帖子间等待大幅拉长
        "wait_max":            20,
        "long_break_prob":     0.35,    # 更频繁地长休息（打乱节奏）
        "long_break_min":     120,      # 长休息 2~7 分钟
        "long_break_max":     420,
        "session_action_cap":   4,      # 会话累计操作上限极低
        "daily_like_limit":     3,      # 每日点赞上限（跨重启累计）
        "daily_reply_limit":    0,      # 每日评论上限（养号期间为 0）
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
