"""
主窗口 UI - 仿 Linux.do 刷帖助手 v8.5.0 布局
"""

import os
import time
import subprocess
import queue
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
from typing import Dict, Any, Optional

# 使脚本与包都能 import
if __package__ in (None, ""):
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src.theme import COLORS, FONTS, SIZE, DEFAULT_CATEGORIES
    from src.config import Config
    from src.anthropic_client import AnthropicClient
    from src.xhs_crawler import XhsCrawler
    from src.scheduler import Scheduler
else:
    from .theme import COLORS, FONTS, SIZE, DEFAULT_CATEGORIES
    from .config import Config
    from .anthropic_client import AnthropicClient
    from .xhs_crawler import XhsCrawler
    from .scheduler import Scheduler


# ============== 颜色标记 ==============
LOG_COLOR = {
    "info": COLORS["fg_text"],
    "ok":   COLORS["fg_ok"],
    "warn": COLORS["fg_warn"],
    "err":  COLORS["fg_err"],
    "debug": COLORS["fg_sub"],
}


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.config = Config()
        self.ai = AnthropicClient(
            base_url=self.config.get("api_base_url"),
            api_key=self.config.get("api_key"),
            model=self.config.get("api_model"),
            proxy=self.config.get("proxy", ""),
        )
        self.crawler = XhsCrawler(
            use_mock=self.config.get("use_mock", True),
            headless=self.config.get("headless", False),
            user_data_dir=self.config.get("user_data_dir") or None,
            log_fn=self._on_crawler_log,
            humanize=self.config.data.get("humanize", {}),
        )
        self.scheduler = Scheduler(
            crawler=self.crawler, ai=self.ai,
            config=self.config.data,
            log_fn=self._on_crawler_log,
            state_fn=self._on_state,
        )
        self._log_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
        self._seen_note_ids: set = set()
        self._stats = {"posts_seen": 0, "posts_read": 0, "liked": 0, "replied": 0}
        self._build_window()
        self._build_styles()
        self._build_ui()
        self._refresh_from_config()
        self._poll_log_queue()
        # 关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ============== 窗口骨架 ==============
    def _build_window(self):
        self.root.title("XHS Review · 小红书智能回复助手 v1.0")
        self.root.configure(bg=COLORS["bg_root"])
        self.root.geometry(f"{SIZE['win_w']}x{SIZE['win_h']}")
        self.root.minsize(820, 800)

    def _get_version(self) -> str:
        """读取当前 git 短哈希作为运行版本号（脏工作区追加 *）。"""
        try:
            base = os.path.dirname(os.path.abspath(__file__))
            head = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"], cwd=base,
                stderr=subprocess.DEVNULL,
            ).decode("utf-8").strip()
            dirty = subprocess.call(["git", "diff", "--quiet"], cwd=base) != 0
            return f"{head}{'*' if dirty else ''}"
        except Exception:
            return "unknown"

    def _build_version_badge(self, parent):
        """左上角红色版本框：实时显示 git commit，排查时可与 git log 对齐。"""
        try:
            box = tk.Frame(parent, bg=COLORS["bg_panel"],
                           highlightbackground="#E74C3C", highlightthickness=1, bd=0)
            box.pack(side="left", padx=(0, 14))
            ver = self._get_version()
            self.lbl_version = tk.Label(box, text=f"版本 {ver}", bg=COLORS["bg_panel"],
                                        fg="#E74C3C", font=FONTS["small"])
            self.lbl_version.pack(padx=5, pady=1)
        except Exception:
            pass

    def _build_styles(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except Exception:
            pass
        s.configure(".", background=COLORS["bg_root"], foreground=COLORS["fg_text"],
                    fieldbackground=COLORS["bg_input"], font=FONTS["normal"])
        s.configure("TFrame", background=COLORS["bg_root"])
        s.configure("Panel.TFrame", background=COLORS["bg_panel"], relief="flat", borderwidth=1)
        s.configure("Section.TFrame", background=COLORS["bg_section"], relief="flat", borderwidth=1)
        s.configure("TLabel", background=COLORS["bg_root"], foreground=COLORS["fg_text"], font=FONTS["normal"])
        s.configure("Panel.TLabel", background=COLORS["bg_panel"], foreground=COLORS["fg_text"], font=FONTS["normal"])
        s.configure("Title.TLabel", background=COLORS["bg_panel"], foreground=COLORS["fg_title"], font=FONTS["title"])
        s.configure("Section.TLabel", background=COLORS["bg_section"], foreground=COLORS["fg_section"], font=FONTS["section"])
        s.configure("Value.TLabel", background=COLORS["bg_panel"], foreground=COLORS["fg_value"], font=FONTS["value"])
        s.configure("Sub.TLabel", background=COLORS["bg_panel"], foreground=COLORS["fg_sub"], font=FONTS["small"])
        s.configure("Ok.TLabel", background=COLORS["bg_panel"], foreground=COLORS["fg_ok"], font=FONTS["value"])

        s.configure("TCheckbutton", background=COLORS["bg_panel"], foreground=COLORS["fg_text"], font=FONTS["normal"])
        s.map("TCheckbutton", background=[("active", COLORS["bg_panel"])])

        s.configure("TRadiobutton", background=COLORS["bg_panel"], foreground=COLORS["fg_text"], font=FONTS["normal"])
        s.map("TRadiobutton", background=[("active", COLORS["bg_panel"])])

        s.configure("TEntry", fieldbackground=COLORS["bg_input"], foreground=COLORS["fg_text"],
                    insertcolor=COLORS["fg_text"], bordercolor=COLORS["border"], lightcolor=COLORS["border"],
                    darkcolor=COLORS["border"], padding=4)

        s.configure("TButton", background=COLORS["btn_bg"], foreground=COLORS["btn_fg"],
                    font=FONTS["label"], padding=(12, 6), borderwidth=0)
        s.map("TButton",
              background=[("active", COLORS["btn_hover"]), ("disabled", "#555")],
              foreground=[("disabled", "#888")])

        s.configure("Start.TButton", background=COLORS["btn_start"], foreground="#fff",
                    font=FONTS["label"], padding=(18, 6))
        s.map("Start.TButton", background=[("active", "#3D7EE6")])

        s.configure("Stop.TButton", background=COLORS["btn_stop"], foreground="#fff",
                    font=FONTS["label"], padding=(18, 6))
        s.map("Stop.TButton", background=[("active", "#F07070")])

        s.configure("TLabelframe", background=COLORS["bg_panel"], foreground=COLORS["fg_section"],
                    bordercolor=COLORS["border"], relief="flat")
        s.configure("TLabelframe.Label", background=COLORS["bg_panel"], foreground=COLORS["fg_section"],
                    font=FONTS["section"])

    # ============== UI 布局 ==============
    def _build_ui(self):
        # ============== 顶部：用户信息 ==============
        user_frame = tk.LabelFrame(self.root, text="  用户信息  ", bg=COLORS["bg_panel"],
                                   fg=COLORS["fg_section"], font=FONTS["section"],
                                   bd=1, relief="flat", highlightbackground=COLORS["border"],
                                   highlightthickness=1)
        user_frame.pack(fill="x", padx=SIZE["pad"], pady=(SIZE["pad"], 4))
        user_inner = tk.Frame(user_frame, bg=COLORS["bg_panel"])
        user_inner.pack(fill="x", padx=8, pady=6)
        # 左上角：版本红框（实时读取 git commit，便于排查运行版本）
        self._build_version_badge(user_inner)
        tk.Label(user_inner, text="用户：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")
        self.lbl_username = tk.Label(user_inner, text="未登录", bg=COLORS["bg_panel"],
                                     fg=COLORS["fg_value"], font=FONTS["value"])
        self.lbl_username.pack(side="left", padx=(2, 18))
        tk.Label(user_inner, text="等级：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")
        self.lbl_level = tk.Label(user_inner, text="-", bg=COLORS["bg_panel"],
                                  fg=COLORS["fg_value"], font=FONTS["value"])
        self.lbl_level.pack(side="left", padx=(2, 18))
        tk.Label(user_inner, text="下一级：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")
        self.lbl_next = tk.Label(user_inner, text="-", bg=COLORS["bg_panel"],
                                 fg=COLORS["fg_value"], font=FONTS["value"])
        self.lbl_next.pack(side="left", padx=(2, 18))
        self.lbl_user_state = tk.Label(user_inner, text="● 离线", bg=COLORS["bg_panel"],
                                       fg=COLORS["fg_warn"], font=FONTS["normal"])
        self.lbl_user_state.pack(side="right")

        # ============== 运行模式 ==============
        mode_frame = tk.LabelFrame(self.root, text="  运行模式  ", bg=COLORS["bg_panel"],
                                   fg=COLORS["fg_section"], font=FONTS["section"],
                                   bd=1, relief="flat", highlightbackground=COLORS["border"],
                                   highlightthickness=1)
        mode_frame.pack(fill="x", padx=SIZE["pad"], pady=4)
        mode_inner = tk.Frame(mode_frame, bg=COLORS["bg_panel"])
        mode_inner.pack(fill="x", padx=8, pady=8)

        # 模式选择
        self.var_mode = tk.StringVar(value="unlimited")
        tk.Label(mode_inner, text="模式：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=0, sticky="w", pady=2)
        ttk.Radiobutton(mode_inner, text="无限制模式", variable=self.var_mode, value="unlimited",
                       command=self._on_mode_change).grid(row=0, column=1, sticky="w", padx=(0, 14))
        f_count = tk.Frame(mode_inner, bg=COLORS["bg_panel"])
        f_count.grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(f_count, text="帖子数量", variable=self.var_mode, value="count",
                        command=self._on_mode_change).pack(side="left")
        self.spin_count = tk.Spinbox(f_count, from_=1, to=9999, width=6,
                                     bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                     buttonbackground=COLORS["btn_bg"],
                                     insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_count.pack(side="left", padx=4)
        tk.Label(f_count, text="个", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")

        f_time = tk.Frame(mode_inner, bg=COLORS["bg_panel"])
        f_time.grid(row=0, column=3, sticky="w", padx=(20, 0))
        ttk.Radiobutton(f_time, text="时间限制", variable=self.var_mode, value="time",
                        command=self._on_mode_change).pack(side="left")
        self.spin_time = tk.Spinbox(f_time, from_=1, to=9999, width=6,
                                    bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                    buttonbackground=COLORS["btn_bg"],
                                    insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_time.pack(side="left", padx=4)
        tk.Label(f_time, text="分钟", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")

        # 爬楼模式
        self.var_crawl = tk.StringVar(value="deep")
        tk.Label(mode_inner, text="爬楼模式：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Radiobutton(mode_inner, text="深度爬楼（完整阅读）", variable=self.var_crawl,
                       value="deep").grid(row=1, column=1, sticky="w", pady=(6, 0), padx=(0, 14))
        ttk.Radiobutton(mode_inner, text="快速浏览（3~5层换帖）", variable=self.var_crawl,
                       value="fast").grid(row=1, column=2, sticky="w", pady=(6, 0), columnspan=2)
        tk.Label(mode_inner, text="（快速模式增加浏览话题数）",
                 bg=COLORS["bg_panel"], fg=COLORS["fg_sub"], font=FONTS["small"]).grid(
            row=1, column=3, sticky="w", pady=(6, 0))

        # 代理 + 启停按钮
        ctrl_row = tk.Frame(mode_inner, bg=COLORS["bg_panel"])
        ctrl_row.grid(row=2, column=0, columnspan=4, sticky="we", pady=(10, 0))
        tk.Label(ctrl_row, text="代理：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")
        self.entry_proxy = ttk.Entry(ctrl_row, width=24)
        self.entry_proxy.pack(side="left", padx=(2, 14))
        tk.Label(ctrl_row, text="（代理留空则直连）", bg=COLORS["bg_panel"],
                 fg=COLORS["fg_sub"], font=FONTS["small"]).pack(side="left")

        self.btn_start = ttk.Button(ctrl_row, text="▶  开始", style="Start.TButton",
                                    command=self._on_start)
        self.btn_start.pack(side="left", padx=(20, 6))
        self.btn_stop = ttk.Button(ctrl_row, text="■  停止", style="Stop.TButton",
                                   command=self._on_stop, state="disabled")
        self.btn_stop.pack(side="left")

        # 右侧：API 配置
        api_box = tk.Frame(ctrl_row, bg=COLORS["bg_panel"])
        api_box.pack(side="right")
        tk.Label(api_box, text="API：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).pack(side="left")
        self.btn_api = ttk.Button(api_box, text="⚙  Anthropic 配置",
                                  command=self._open_api_dialog)
        self.btn_api.pack(side="left", padx=4)
        self.btn_mode = ttk.Button(api_box, text="🔁 虚拟数据：开",
                                   command=self._toggle_mock)
        self.btn_mode.pack(side="left", padx=4)

        # ============== 中部：左板块 / 右日志 ==============
        middle = tk.Frame(self.root, bg=COLORS["bg_root"])
        middle.pack(fill="both", expand=True, padx=SIZE["pad"], pady=4)

        # 左侧：板块 + 关键词
        left = tk.LabelFrame(middle, text="  板块 / 关键词  ", bg=COLORS["bg_panel"],
                             fg=COLORS["fg_section"], font=FONTS["section"],
                             bd=1, relief="flat", highlightbackground=COLORS["border"],
                             highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 4))
        left_inner = tk.Frame(left, bg=COLORS["bg_panel"])
        left_inner.pack(fill="both", expand=True, padx=8, pady=6)

        # 搜索关键词（置顶）
        kw_row = tk.Frame(left_inner, bg=COLORS["bg_panel"])
        kw_row.pack(fill="x", pady=(0, 6))
        tk.Label(kw_row, text="🔍 关键词", bg=COLORS["bg_panel"],
                 fg=COLORS["fg_section"], font=FONTS["label"]).pack(anchor="w")
        self.entry_keyword = ttk.Entry(kw_row, font=FONTS["normal"])
        self.entry_keyword.pack(fill="x", pady=(2, 0))
        tk.Label(kw_row, text="（留空则按板块浏览；填了则按关键词搜索）",
                 bg=COLORS["bg_panel"], fg=COLORS["fg_sub"],
                 font=FONTS["small"]).pack(anchor="w", pady=(2, 0))

        # 分隔
        tk.Frame(left_inner, height=1, bg=COLORS["border"]).pack(fill="x", pady=6)

        # 板块标题 + 全选/全不选
        cat_hdr = tk.Frame(left_inner, bg=COLORS["bg_panel"])
        cat_hdr.pack(fill="x", pady=(0, 4))
        tk.Label(cat_hdr, text="📂 板块", bg=COLORS["bg_panel"],
                 fg=COLORS["fg_section"], font=FONTS["label"]).pack(side="left")
        ttk.Button(cat_hdr, text="全选", width=4,
                   command=lambda: self._set_all_cats(True)).pack(side="right", padx=2)
        ttk.Button(cat_hdr, text="全清", width=4,
                   command=lambda: self._set_all_cats(False)).pack(side="right")

        # 板块复选框：两列网格
        cat_grid = tk.Frame(left_inner, bg=COLORS["bg_panel"])
        cat_grid.pack(fill="x")
        self.cat_vars: Dict[str, tk.BooleanVar] = {}
        cats = list(DEFAULT_CATEGORIES)
        for i, (cat, default) in enumerate(cats):
            row, col = divmod(i, 2)
            v = tk.BooleanVar(value=default)
            cb = ttk.Checkbutton(cat_grid, text=cat, variable=v,
                                 command=self._on_cats_change)
            cb.grid(row=row, column=col, sticky="w", padx=(0, 8), pady=1)
            self.cat_vars[cat] = v

        # 提示
        tk.Label(left_inner, text="（单选生效；多选时取首个）",
                 bg=COLORS["bg_panel"], fg=COLORS["fg_sub"],
                 font=FONTS["small"]).pack(anchor="w", pady=(6, 0))

        # 右侧：日志
        right = tk.LabelFrame(middle, text="  运行日志  ", bg=COLORS["bg_panel"],
                              fg=COLORS["fg_section"], font=FONTS["section"],
                              bd=1, relief="flat", highlightbackground=COLORS["border"],
                              highlightthickness=1)
        right.pack(side="left", fill="both", expand=True)
        right_inner = tk.Frame(right, bg=COLORS["bg_panel"])
        right_inner.pack(fill="both", expand=True, padx=8, pady=6)
        self.log_text = scrolledtext.ScrolledText(
            right_inner, height=SIZE["log_h"], width=SIZE["log_w"],
            bg=COLORS["bg_log"], fg=COLORS["fg_text"],
            insertbackground=COLORS["fg_text"],
            font=FONTS["log"], relief="flat", borderwidth=0,
            wrap="word", state="disabled",
        )
        self.log_text.pack(fill="both", expand=True)
        for level, color in LOG_COLOR.items():
            self.log_text.tag_configure(level, foreground=color)

        # 日志工具栏
        log_tools = tk.Frame(right_inner, bg=COLORS["bg_panel"])
        log_tools.pack(fill="x", pady=(4, 0))
        ttk.Button(log_tools, text="清空日志", command=self._clear_log).pack(side="left")
        ttk.Button(log_tools, text="导出日志", command=self._export_log).pack(side="left", padx=4)
        ttk.Button(log_tools, text="测试 AI", command=self._test_ai).pack(side="left", padx=4)
        self.lbl_ai_state = tk.Label(log_tools, text="AI: 未配置", bg=COLORS["bg_panel"],
                                    fg=COLORS["fg_warn"], font=FONTS["small"])
        self.lbl_ai_state.pack(side="right")

        # ============== 行为概率区 ==============
        action_frame = tk.LabelFrame(self.root, text="  行为概率  ", bg=COLORS["bg_panel"],
                                     fg=COLORS["fg_section"], font=FONTS["section"],
                                     bd=1, relief="flat", highlightbackground=COLORS["border"],
                                     highlightthickness=1)
        action_frame.pack(fill="x", padx=SIZE["pad"], pady=4)
        ai = tk.Frame(action_frame, bg=COLORS["bg_panel"])
        ai.pack(fill="x", padx=8, pady=6)

        self.var_like = tk.BooleanVar(value=False)
        ttk.Checkbutton(ai, text="自动点赞", variable=self.var_like,
                        command=self._on_action_change).grid(row=0, column=0, sticky="w")
        tk.Label(ai, text="点赞率：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=1, sticky="w", padx=(20, 2))
        self.spin_like = tk.Spinbox(ai, from_=0, to=100, width=5,
                                    bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                    buttonbackground=COLORS["btn_bg"],
                                    insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_like.grid(row=0, column=2, sticky="w")
        tk.Label(ai, text="%", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=3, sticky="w")

        self.var_reply = tk.BooleanVar(value=True)
        ttk.Checkbutton(ai, text="自动回复", variable=self.var_reply,
                        command=self._on_action_change).grid(row=0, column=4, sticky="w", padx=(20, 0))
        tk.Label(ai, text="回复率：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=5, sticky="w", padx=(20, 2))
        self.spin_reply = tk.Spinbox(ai, from_=0, to=100, width=5,
                                     bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                     buttonbackground=COLORS["btn_bg"],
                                     insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_reply.grid(row=0, column=6, sticky="w")
        tk.Label(ai, text="%", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=7, sticky="w")

        # 等待
        self.var_wait = tk.BooleanVar(value=True)
        ttk.Checkbutton(ai, text="启用等待", variable=self.var_wait,
                        command=self._on_action_change).grid(row=0, column=8, sticky="w", padx=(20, 0))
        tk.Label(ai, text="等待：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=9, sticky="w", padx=(4, 2))
        self.spin_wmin = tk.Spinbox(ai, from_=0, to=120, width=4,
                                    bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                    buttonbackground=COLORS["btn_bg"],
                                    insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_wmin.grid(row=0, column=10, sticky="w")
        tk.Label(ai, text="~", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=11, sticky="w")
        self.spin_wmax = tk.Spinbox(ai, from_=0, to=600, width=4,
                                    bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                    buttonbackground=COLORS["btn_bg"],
                                    insertbackground=COLORS["fg_text"], font=FONTS["normal"])
        self.spin_wmax.grid(row=0, column=12, sticky="w")
        tk.Label(ai, text="秒", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=13, sticky="w")
        tk.Label(ai, text="（已有滚动延迟，可关闭）", bg=COLORS["bg_panel"],
                 fg=COLORS["fg_sub"], font=FONTS["small"]).grid(row=0, column=14, sticky="w", padx=(10, 0))

        # 拟人化 / 防封设置入口
        hz_btn = ttk.Button(ai, text="🛡 拟人化设置", command=self._open_humanize_dialog)
        hz_btn.grid(row=1, column=0, columnspan=4, sticky="w", pady=(8, 0))
        tk.Label(ai, text="（打字/阅读/滚动/鼠标/节奏/会话上限，全部可调，默认已开启防封）",
                 bg=COLORS["bg_panel"], fg=COLORS["fg_sub"],
                 font=FONTS["small"]).grid(row=1, column=4, columnspan=11, sticky="w", padx=(10, 0), pady=(8, 0))

        # ============== 统计 ==============
        stat_frame = tk.LabelFrame(self.root, text="  本次统计  ", bg=COLORS["bg_panel"],
                                   fg=COLORS["fg_section"], font=FONTS["section"],
                                   bd=1, relief="flat", highlightbackground=COLORS["border"],
                                   highlightthickness=1)
        stat_frame.pack(fill="x", padx=SIZE["pad"], pady=(4, SIZE["pad"]))
        si = tk.Frame(stat_frame, bg=COLORS["bg_panel"])
        si.pack(fill="x", padx=8, pady=6)
        self.stat_labels = {}
        items = [
            ("帖子", "posts_seen", COLORS["fg_value"]),
            ("爬楼", "posts_read", COLORS["fg_value"]),
            ("已读", "posts_seen_disp", COLORS["fg_value"]),
            ("点赞", "liked",       COLORS["fg_ok"]),
            ("回复", "replied",     COLORS["fg_ok"]),
            ("错误", "errors",      COLORS["fg_err"]),
        ]
        for i, (k, key, color) in enumerate(items):
            cell = tk.Frame(si, bg=COLORS["bg_panel"])
            cell.grid(row=0, column=i, padx=12, sticky="w")
            tk.Label(cell, text=k, bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                     font=FONTS["normal"]).pack(side="left")
            v = tk.Label(cell, text="0", bg=COLORS["bg_panel"], fg=color, font=FONTS["value"])
            v.pack(side="left", padx=2)
            self.stat_labels[key] = v

    # ============== 行为回调 ==============
    def _on_crawler_log(self, level: str, msg: str):
        self._log_queue.put((level, msg))

    def _poll_log_queue(self):
        try:
            while True:
                level, msg = self._log_queue.get_nowait()
                self._append_log(level, msg)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    def _append_log(self, level: str, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"[{ts}] ", "info")
        prefix = {"info": "· ", "ok": "✓ ", "warn": "! ", "err": "✗ ", "debug": "… "}.get(level, "· ")
        self.log_text.insert("end", prefix + msg + "\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self):
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _export_log(self):
        try:
            content = self.log_text.get("1.0", "end")
            path = filedialog.asksaveasfilename(
                defaultextension=".log",
                filetypes=[("日志文件", "*.log"), ("文本", "*.txt"), ("All", "*.*")],
                initialfile=f"xhsreview_{time.strftime('%Y%m%d_%H%M%S')}.log",
            )
            if path:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(content)
                messagebox.showinfo("导出成功", f"日志已保存到\n{path}")
        except Exception as e:
            messagebox.showerror("导出失败", str(e))

    def _test_ai(self):
        def worker():
            self._append_log("info", "🧪 正在测试 AI 连接...")
            ok, msg = self.ai.test_connection()
            if ok:
                self._append_log("ok", f"AI 连接测试通过：{msg}")
            else:
                self._append_log("err", f"AI 连接失败：{msg}")
        threading.Thread(target=worker, daemon=True).start()

    def _on_state(self, state: Dict[str, Any]):
        # 跨线程更新 UI
        def apply():
            self.stat_labels["posts_seen"].config(text=str(state.get("posts_seen", 0)))
            self.stat_labels["posts_read"].config(text=str(state.get("posts_read", 0)))
            self.stat_labels["posts_seen_disp"].config(text=str(state.get("posts_seen", 0)))
            self.stat_labels["liked"].config(text=str(state.get("liked", 0)))
            self.stat_labels["replied"].config(text=str(state.get("replied", 0)))
            self.stat_labels["errors"].config(text=str(state.get("errors", 0)))
        self.root.after(0, apply)

    def _on_mode_change(self):
        m = self.var_mode.get()
        self.spin_count.configure(state="normal" if m == "count" else "disabled")
        self.spin_time.configure(state="normal" if m == "time" else "disabled")

    def _on_cats_change(self):
        """板块变更：单选模式（多选时取首个），并保存"""
        enabled = [k for k, v in self.cat_vars.items() if v.get()]
        # 单选：取消其他，只保留最后一个被勾选的
        # 实现：如果当前有多个，只保留最后一个
        if len(enabled) > 1:
            # 找到最后一个为 True 的（注意：用户刚点的无法直接知道，但通过 widgets 顺序近似）
            # 更稳妥：取 DEFAULT_CATEGORIES 中靠后被勾选的那个
            last = None
            for cat, _ in DEFAULT_CATEGORIES:
                if self.cat_vars[cat].get():
                    last = cat
            for cat, v in self.cat_vars.items():
                if cat != last:
                    v.set(False)
            enabled = [last] if last else []
        cats_dict = {k: bool(v.get()) for k, v in self.cat_vars.items()}
        self.config.set("categories", cats_dict)
        self.config.save()

    def _set_all_cats(self, on: bool):
        for v in self.cat_vars.values():
            v.set(on)
        # 全选也按单选处理：只留最后一个
        if on:
            last = DEFAULT_CATEGORIES[-1][0] if DEFAULT_CATEGORIES else None
            for cat, v in self.cat_vars.items():
                v.set(cat == last)
        self._on_cats_change()

    def _on_action_change(self):
        self.config.set("auto_like", bool(self.var_like.get()))
        self.config.set("like_rate", int(self.spin_like.get()))
        self.config.set("auto_reply", bool(self.var_reply.get()))
        self.config.set("reply_rate", int(self.spin_reply.get()))
        self.config.set("enable_wait", bool(self.var_wait.get()))
        self.config.set("wait_min", int(self.spin_wmin.get()))
        self.config.set("wait_max", int(self.spin_wmax.get()))
        self.config.save()

    def _refresh_from_config(self):
        c = self.config.data
        self.var_mode.set(c.get("mode", "unlimited"))
        self.spin_count.delete(0, "end"); self.spin_count.insert(0, c.get("post_limit", 50))
        self.spin_time.delete(0, "end"); self.spin_time.insert(0, c.get("time_limit", 30))
        self.var_crawl.set(c.get("crawl_mode", "deep"))
        self.var_like.set(c.get("auto_like", False))
        self.spin_like.delete(0, "end"); self.spin_like.insert(0, c.get("like_rate", 30))
        self.var_reply.set(c.get("auto_reply", True))
        self.spin_reply.delete(0, "end"); self.spin_reply.insert(0, c.get("reply_rate", 80))
        self.var_wait.set(c.get("enable_wait", True))
        self.spin_wmin.delete(0, "end"); self.spin_wmin.insert(0, c.get("wait_min", 1))
        self.spin_wmax.delete(0, "end"); self.spin_wmax.insert(0, c.get("wait_max", 3))

        cats = c.get("categories", {})
        for k, v in self.cat_vars.items():
            v.set(cats.get(k, False))

        # 关键词
        kw = c.get("search_keyword", "")
        if hasattr(self, "entry_keyword"):
            self.entry_keyword.delete(0, "end")
            self.entry_keyword.insert(0, kw)

        # 代理
        proxy_val = c.get("proxy", "")
        self.entry_proxy.delete(0, "end")
        self.entry_proxy.insert(0, proxy_val)

        # AI 状态
        if c.get("api_key"):
            self.lbl_ai_state.config(text=f"AI: {c.get('api_model','?')}", fg=COLORS["fg_ok"])
        else:
            self.lbl_ai_state.config(text="AI: 未配置 Key", fg=COLORS["fg_warn"])

        # 模式按钮
        if c.get("use_mock", True):
            self.btn_mode.config(text="🔁 虚拟数据：开")
        else:
            self.btn_mode.config(text="🌐 真实抓取：开")

        self._on_mode_change()

    def _on_start(self):
        # 收集参数
        self.config.set("mode", self.var_mode.get())
        self.config.set("post_limit", int(self.spin_count.get()))
        self.config.set("time_limit", int(self.spin_time.get()))
        self.config.set("crawl_mode", self.var_crawl.get())
        self.config.set("auto_like", bool(self.var_like.get()))
        self.config.set("like_rate", int(self.spin_like.get()))
        self.config.set("auto_reply", bool(self.var_reply.get()))
        self.config.set("reply_rate", int(self.spin_reply.get()))
        self.config.set("enable_wait", bool(self.var_wait.get()))
        self.config.set("wait_min", int(self.spin_wmin.get()))
        self.config.set("wait_max", int(self.spin_wmax.get()))
        self._on_cats_change()
        # 关键词
        self.config.set("search_keyword", self.entry_keyword.get().strip())
        self.config.save()

        # 代理（同步到 config 和 AI 客户端）
        proxy = self.entry_proxy.get().strip()
        self.config.set("proxy", proxy)
        self.config.save()
        self.ai.update(proxy=proxy)

        if not self.config.get("api_key") and self.config.get("auto_reply", True):
            if not messagebox.askyesno("未配置 API", "尚未配置 Anthropic API Key，是否先打开配置？"):
                return
            self._open_api_dialog()
            return

        # 重新构建爬虫
        self.crawler = XhsCrawler(
            use_mock=self.config.get("use_mock", True),
            headless=self.config.get("headless", False),
            user_data_dir=self.config.get("user_data_dir") or None,
            log_fn=self._on_crawler_log,
            humanize=self.config.data.get("humanize", {}),
        )
        self.scheduler = Scheduler(
            crawler=self.crawler, ai=self.ai,
            config=self.config.data,
            log_fn=self._on_crawler_log,
            state_fn=self._on_state,
        )

        ok, msg = self.scheduler.start()
        if ok:
            self.btn_start.config(state="disabled")
            self.btn_stop.config(state="normal")
            self.lbl_user_state.config(text="● 在线", fg=COLORS["fg_ok"])

            # 启动后检测登录状态，未登录则提示扫码
            if not self.config.get("use_mock", True) and not self.crawler.is_logged_in:
                self._on_crawler_log("warn", "未检测到登录状态，请在浏览器中扫码登录小红书")
                self._on_crawler_log("info", "扫码登录后，点击「已登录」按钮继续")
                self._show_login_prompt()
        else:
            messagebox.showerror("启动失败", msg)

    def _show_login_prompt(self):
        """弹出登录提示对话框，用户扫码后可重新检测"""
        dlg = tk.Toplevel(self.root)
        dlg.title("请登录小红书")
        dlg.geometry("380x180")
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.transient(self.root)
        dlg.grab_set()

        tk.Label(dlg, text="🔑 请在小红书浏览器中扫码登录",
                 font=("", 13, "bold"), bg=COLORS["bg_panel"],
                 fg=COLORS["fg_text"]).pack(pady=(20, 8))
        tk.Label(dlg, text="登录后点击下方按钮重新检测登录状态",
                 font=("", 10), bg=COLORS["bg_panel"],
                 fg=COLORS["fg_dim"]).pack(pady=(0, 16))

        def on_recheck():
            if self.crawler and not self.crawler.use_mock:
                logged_in = self.crawler.recheck_login()
                if logged_in:
                    self._on_crawler_log("ok", "检测到已登录状态")
                    dlg.destroy()
                else:
                    messagebox.showinfo("仍未登录", "未检测到登录状态，请确认已在浏览器中扫码登录", parent=dlg)

        def on_skip():
            self._on_crawler_log("warn", "跳过登录检测，将仅浏览公开内容（无法回复/点赞）")
            dlg.destroy()

        btn_frame = tk.Frame(dlg, bg=COLORS["bg_panel"])
        btn_frame.pack(pady=8)
        ttk.Button(btn_frame, text="已登录，重新检测", command=on_recheck).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="跳过", command=on_skip).pack(side="left", padx=8)

        dlg.update_idletasks()
        dlg.geometry("")
        dlg.geometry(f"+{(dlg.winfo_screenwidth() - dlg.winfo_width()) // 2}+{(dlg.winfo_screenheight() - dlg.winfo_height()) // 2}")

    def _on_stop(self):
        self.scheduler.stop("用户点击停止")
        self.btn_start.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.lbl_user_state.config(text="● 离线", fg=COLORS["fg_warn"])

    def _on_close(self):
        if self.scheduler.is_running():
            if not messagebox.askyesno("确认退出", "任务正在运行中，确定要退出吗？"):
                return
            self.scheduler.stop("窗口关闭")
        self.config.save()
        try:
            self.crawler.stop()
        except Exception:
            pass
        self.root.destroy()

    def _toggle_mock(self):
        cur = self.config.get("use_mock", True)
        self.config.set("use_mock", not cur)
        self.config.save()
        if not cur:
            self.btn_mode.config(text="🔁 虚拟数据：开")
        else:
            self.btn_mode.config(text="🌐 真实抓取：开")
        self._append_log("info", f"已切换到 {'虚拟数据' if not cur else '真实抓取'} 模式（重启任务后生效）")

    # ============== 拟人化 / 防封设置弹窗 ==============
    def _open_humanize_dialog(self):
        HZ_DEFAULTS = {
            "enabled": True, "type_min_delay": 0.06, "type_max_delay": 0.20,
            "type_pause_prob": 0.10, "type_pause_min": 0.30, "type_pause_max": 1.00,
            "type_typo_rate": 0.05, "read_enabled": True, "read_per_char": 0.010,
            "read_min": 1.5, "read_max": 5.0, "scroll_human": True,
            "scroll_pause_prob": 0.30, "scroll_back_prob": 0.25,
            "mouse_human_move": True, "mouse_overshoot_prob": 0.40, "hesitate_prob": 0.04,
            "no_comment_rate": 12, "content_typo_rate": 0.15, "content_emoji_rate": 0.50,
            "content_truncate_rate": 0.12, "glance_comments": True,
            "skip_rate": 20, "long_break_prob": 0.07,
            "long_break_min": 30, "long_break_max": 120, "session_action_cap": 35,
            "session_break_min": 120, "session_break_max": 300, "randomize_order": True,
        }
        # 字段定义：(类型, key, 标签, min, max, step) 或 (分组标题, 标题)
        fields = [
            ("group", "打字拟人"),
            ("bool", "enabled", "总开关（关闭则退化为简单随机）"),
            ("num", "type_min_delay", "每字延迟下限(秒)", 0.01, 0.5, 0.01),
            ("num", "type_max_delay", "每字延迟上限(秒)", 0.01, 1.0, 0.01),
            ("num", "type_pause_prob", "输入中卡顿概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "type_pause_min", "卡顿停顿下限(秒)", 0.0, 5.0, 0.1),
            ("num", "type_pause_max", "卡顿停顿上限(秒)", 0.0, 10.0, 0.1),
            ("num", "type_typo_rate", "打错一个字再删概率(0~1)", 0.0, 1.0, 0.01),
            ("group", "阅读停留（评论前先读完帖子）"),
            ("bool", "read_enabled", "启用阅读停留"),
            ("num", "read_per_char", "每字符阅读耗时(秒)", 0.0, 0.1, 0.001),
            ("num", "read_min", "最短停留(秒)", 0.0, 30.0, 0.5),
            ("num", "read_max", "最长停留(秒)", 0.0, 60.0, 0.5),
            ("group", "滚动拟人"),
            ("bool", "scroll_human", "启用拟人滚动"),
            ("num", "scroll_pause_prob", "滚动中停顿概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "scroll_back_prob", "向上回滚概率(0~1)", 0.0, 1.0, 0.01),
            ("group", "鼠标拟人"),
            ("bool", "mouse_human_move", "点击前曲线移动鼠标（避免瞬移）"),
            ("num", "mouse_overshoot_prob", "落点过冲再修正概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "hesitate_prob", "犹豫了没点赞概率(0~1)", 0.0, 1.0, 0.01),
            ("group", "AI 回复内容拟人（防 AI 味 / 人工审核）"),
            ("num", "no_comment_rate", "看了但不评论率(%)", 0, 100, 1),
            ("num", "content_typo_rate", "偶发错别字概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "content_emoji_rate", "追加 emoji 概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "content_truncate_rate", "只保留前半句概率(0~1)", 0.0, 1.0, 0.01),
            ("group", "行为节奏"),
            ("num", "skip_rate", "纯浏览跳过率(%)", 0, 100, 1),
            ("num", "long_break_prob", "偶发长休息概率(0~1)", 0.0, 1.0, 0.01),
            ("num", "long_break_min", "长休息下限(秒)", 0, 600, 1),
            ("num", "long_break_max", "长休息上限(秒)", 0, 1800, 1),
            ("group", "会话安全上限（防频次异常）"),
            ("num", "session_action_cap", "操作上限(次,0=不限)", 0, 500, 1),
            ("num", "session_break_min", "会话长休下限(秒)", 0, 1800, 10),
            ("num", "session_break_max", "会话长休上限(秒)", 0, 3600, 10),
            ("group", "其他"),
            ("bool", "glance_comments", "评论前先下滑看一眼已有评论再回来"),
            ("bool", "randomize_order", "点赞/评论顺序随机"),
        ]

        dlg = tk.Toplevel(self.root)
        dlg.title("拟人化 / 防封设置")
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.geometry("620x560")

        # 顶部说明
        tk.Label(dlg, text="这些设置让自动化行为更接近真人，降低被小红书风控识别的概率。",
                 bg=COLORS["bg_panel"], fg=COLORS["fg_sub"], font=FONTS["small"]).pack(
            anchor="w", padx=14, pady=(10, 4))

        # 可滚动容器
        canvas = tk.Canvas(dlg, bg=COLORS["bg_panel"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(14, 0), pady=(0, 6))
        scrollbar.pack(side="right", fill="y", pady=(0, 6))

        inner = tk.Frame(canvas, bg=COLORS["bg_panel"])
        canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_canvas_configure(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        inner.bind("<Configure>", _on_canvas_configure)

        # 当前值（用户在 config 里已有的覆盖默认）
        cur = dict(HZ_DEFAULTS)
        saved = self.config.data.get("humanize", {}) or {}
        if isinstance(saved, dict):
            cur.update(saved)

        vars_dict: dict = {}
        row = 0
        for spec in fields:
            if spec[0] == "group":
                tk.Label(inner, text=spec[1], bg=COLORS["bg_panel"],
                         fg=COLORS["fg_section"], font=FONTS["section"]).grid(
                    row=row, column=0, columnspan=3, sticky="w", pady=(10, 2))
            elif spec[0] == "bool":
                key, label = spec[1], spec[2]
                v = tk.BooleanVar(value=bool(cur.get(key, True)))
                cb = ttk.Checkbutton(inner, text=label, variable=v)
                cb.grid(row=row, column=0, columnspan=3, sticky="w", padx=(8, 0))
                vars_dict[key] = v
            elif spec[0] == "num":
                key, label, lo, hi, step = spec[1], spec[2], spec[3], spec[4], spec[5]
                tk.Label(inner, text=label, bg=COLORS["bg_panel"],
                         fg=COLORS["fg_text"], font=FONTS["normal"]).grid(
                    row=row, column=0, sticky="w", padx=(8, 0))
                val = cur.get(key, 0)
                v = tk.StringVar(value=str(val))
                sp = tk.Spinbox(inner, from_=lo, to=hi, increment=step, width=10,
                                textvariable=v, bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                                buttonbackground=COLORS["btn_bg"], font=FONTS["normal"])
                sp.grid(row=row, column=1, sticky="w", padx=(10, 0))
                vars_dict[key] = v
            row += 1

        # 鼠标滚轮滚动
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 底部按钮
        btn_row = tk.Frame(dlg, bg=COLORS["bg_panel"])
        btn_row.pack(fill="x", padx=14, pady=(0, 10))

        def _coerce(key, raw):
            try:
                # 保留整数形态（skip_rate / 各种上限）
                f = float(raw)
                if f == int(f) and key in (
                    "skip_rate", "no_comment_rate", "long_break_min", "long_break_max",
                    "session_action_cap", "session_break_min", "session_break_max"):
                    return int(f)
                return f
            except Exception:
                return HZ_DEFAULTS.get(key, 0)

        def save():
            canvas.unbind_all("<MouseWheel>")
            new_hz = {}
            for key, var in vars_dict.items():
                if isinstance(var, tk.BooleanVar):
                    new_hz[key] = bool(var.get())
                else:
                    new_hz[key] = _coerce(key, var.get())
            self.config.set("humanize", new_hz)
            self.config.save()
            self._append_log("ok", "🛡 拟人化设置已保存（重启任务后生效）")
            dlg.destroy()

        def reset_defaults():
            canvas.unbind_all("<MouseWheel>")
            self.config.set("humanize", dict(HZ_DEFAULTS))
            self.config.save()
            self._append_log("ok", "🛡 已恢复拟人化默认设置")
            dlg.destroy()

        ttk.Button(btn_row, text="恢复默认", command=reset_defaults).pack(side="left")
        ttk.Button(btn_row, text="取消", command=lambda: (canvas.unbind_all("<MouseWheel>"), dlg.destroy())).pack(side="right", padx=4)
        ttk.Button(btn_row, text="保存", command=save).pack(side="right", padx=4)

    # ============== API 配置弹窗 ==============
    def _open_api_dialog(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Anthropic API 配置")
        dlg.configure(bg=COLORS["bg_panel"])
        dlg.geometry("560x460")
        dlg.transient(self.root)
        dlg.grab_set()

        body = tk.Frame(dlg, bg=COLORS["bg_panel"])
        body.pack(fill="both", expand=True, padx=16, pady=14)

        def row(label, default="", show=None, row_idx=0):
            tk.Label(body, text=label, bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                     font=FONTS["normal"]).grid(row=row_idx, column=0, sticky="w", pady=6)
            e = ttk.Entry(body, width=52, show=show)
            e.grid(row=row_idx, column=1, sticky="we", padx=(10, 0), pady=6)
            if default:
                e.insert(0, default)
            body.grid_columnconfigure(1, weight=1)
            return e

        e_url = row("API URL：", self.config.get("api_base_url", "https://api.anthropic.com"), row_idx=0)
        e_key = row("API Key：", self.config.get("api_key", ""), show="*", row_idx=1)
        e_model = row("Model：", self.config.get("api_model", "claude-3-5-sonnet-20241022"), row_idx=2)
        e_persona = row("人设：", self.config.get("api_persona", "友好、有趣的小红书用户"), row_idx=3)
        e_proxy = row("代理：", self.config.get("proxy", ""), row_idx=4)
        tk.Label(body, text="（留空直连，格式 127.0.0.1:7897）", bg=COLORS["bg_panel"],
                 fg=COLORS["fg_sub"], font=FONTS["small"]).grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(0, 6))

        # 高级
        adv = tk.LabelFrame(body, text="  高级  ", bg=COLORS["bg_panel"], fg=COLORS["fg_section"],
                            font=FONTS["section"], bd=1, relief="flat",
                            highlightbackground=COLORS["border"], highlightthickness=1)
        adv.grid(row=5, column=0, columnspan=2, sticky="we", pady=(14, 6))
        adv_inner = tk.Frame(adv, bg=COLORS["bg_panel"])
        adv_inner.pack(fill="x", padx=8, pady=6)
        tk.Label(adv_inner, text="max_tokens：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=0, sticky="w")
        e_max = tk.Spinbox(adv_inner, from_=32, to=2048, width=8,
                           bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                           buttonbackground=COLORS["btn_bg"], font=FONTS["normal"])
        e_max.delete(0, "end"); e_max.insert(0, str(self.config.get("api_max_tokens", 256)))
        e_max.grid(row=0, column=1, sticky="w", padx=(4, 18))

        tk.Label(adv_inner, text="temperature：", bg=COLORS["bg_panel"], fg=COLORS["fg_text"],
                 font=FONTS["normal"]).grid(row=0, column=2, sticky="w")
        e_temp = tk.Spinbox(adv_inner, from_=0.0, to=2.0, increment=0.05, width=8,
                            bg=COLORS["bg_input"], fg=COLORS["fg_text"],
                            buttonbackground=COLORS["btn_bg"], font=FONTS["normal"])
        e_temp.delete(0, "end"); e_temp.insert(0, str(self.config.get("api_temperature", 0.85)))
        e_temp.grid(row=0, column=3, sticky="w", padx=4)

        # 浏览器
        adv2 = tk.LabelFrame(body, text="  浏览器  ", bg=COLORS["bg_panel"], fg=COLORS["fg_section"],
                             font=FONTS["section"], bd=1, relief="flat",
                             highlightbackground=COLORS["border"], highlightthickness=1)
        adv2.grid(row=6, column=0, columnspan=2, sticky="we", pady=(8, 6))
        adv2_inner = tk.Frame(adv2, bg=COLORS["bg_panel"])
        adv2_inner.pack(fill="x", padx=8, pady=6)
        var_head = tk.BooleanVar(value=self.config.get("headless", False))
        ttk.Checkbutton(adv2_inner, text="无头模式（headless）", variable=var_head).pack(side="left")
        ttk.Button(adv2_inner, text="打开 Profile 目录",
                   command=lambda: self._open_profile_dir()).pack(side="right")

        def save():
            self.config.set("api_base_url", e_url.get().strip() or "https://api.anthropic.com")
            self.config.set("api_key", e_key.get().strip())
            self.config.set("api_model", e_model.get().strip() or "claude-3-5-sonnet-20241022")
            self.config.set("api_persona", e_persona.get().strip())
            self.config.set("proxy", e_proxy.get().strip())
            self.config.set("api_max_tokens", int(e_max.get()))
            self.config.set("api_temperature", float(e_temp.get()))
            self.config.set("headless", bool(var_head.get()))
            self.config.save()
            self.ai.update(
                base_url=self.config.get("api_base_url"),
                api_key=self.config.get("api_key"),
                model=self.config.get("api_model"),
                proxy=self.config.get("proxy", ""),
            )
            if self.config.get("api_key"):
                self.lbl_ai_state.config(text=f"AI: {self.config.get('api_model')}", fg=COLORS["fg_ok"])
            self._append_log("ok", "API 配置已保存")
            dlg.destroy()

        def test():
            self.ai.update(
                base_url=e_url.get().strip() or "https://api.anthropic.com",
                api_key=e_key.get().strip(),
                model=e_model.get().strip() or "claude-3-5-sonnet-20241022",
                proxy=e_proxy.get().strip(),
            )
            def w():
                ok, msg = self.ai.test_connection()
                if ok:
                    messagebox.showinfo("成功", "连接成功 ✓", parent=dlg)
                else:
                    messagebox.showerror("失败", msg, parent=dlg)
            threading.Thread(target=w, daemon=True).start()

        # 按钮
        btn_row = tk.Frame(body, bg=COLORS["bg_panel"])
        btn_row.grid(row=7, column=0, columnspan=2, sticky="e", pady=(14, 0))
        ttk.Button(btn_row, text="测试连接", command=test).pack(side="right", padx=4)
        ttk.Button(btn_row, text="取消", command=dlg.destroy).pack(side="right", padx=4)
        ttk.Button(btn_row, text="保存", command=save).pack(side="right", padx=4)

    def _open_profile_dir(self):
        import subprocess
        path = self.config.get("user_data_dir") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".browser_profile"
        )
        os.makedirs(path, exist_ok=True)
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore
            elif sys.platform == "darwin":  # type: ignore
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            messagebox.showinfo("路径", path)


def main():
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
