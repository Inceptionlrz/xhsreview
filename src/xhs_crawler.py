"""
小红书抓取与回复模块
基于 Playwright 浏览器自动化，模拟真实用户浏览/回复行为。

架构设计（修复跨线程 greenlet 错误）：
- 所有 Playwright 调用都必须在同一个线程中执行（Playwright sync_api 依赖 gevent）
- 这里把 Playwright 完整生命周期封装到一个专用的 worker 线程
- 主线程 / 调度器线程通过 _cmd_queue 提交任务，worker 线程执行并通过 reply queue 返回结果
- 这样保证：page 对象只在创建它的 worker 线程内被使用，避免 "Cannot switch to a different thread"
"""

import os
import re
import json
import time
import random
import threading
import tempfile
import traceback
import subprocess
import socket
import queue as _queue
import urllib.request
from urllib.parse import urlparse
from typing import Optional, Dict, List, Any, Callable, Tuple

# Playwright 可选导入
try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page, TimeoutError as PWTimeout
    PW_AVAILABLE = True
except Exception:
    PW_AVAILABLE = False
    Browser = BrowserContext = Page = None  # type: ignore


# ============== 虚拟帖子数据（回退模式） ==============
MOCK_POSTS = [
    {
        "note_id": "mock_001",
        "title": "终于把家里的猫毛问题解决了！",
        "user": "喵呜星球",
        "content": "用了三个月的粘毛器 + 空气净化器组合，今天终于看到效果了，沙发上的毛肉眼可见地少了很多，分享给同样被猫毛困扰的姐妹们～",
        "likes": "1247",
        "comments": "89",
    },
    {
        "note_id": "mock_002",
        "title": "国产替代工具推荐：这几个真的能打",
        "user": "程序员小张",
        "content": "最近在调研国产开发工具，发现这几个真的可以替代 VSCode + Github Copilot，国产 AI 编程助手越做越好了。",
        "likes": "892",
        "comments": "156",
    },
    {
        "note_id": "mock_003",
        "title": "推荐几个小众但好用的网站",
        "user": "资源挖掘机",
        "content": "整理了一下我常用的资源站，涵盖图片、字体、模板等多个领域，全部免费可商用，强烈推荐收藏。",
        "likes": "2341",
        "comments": "312",
    },
    {
        "note_id": "mock_004",
        "title": "工作三年才发现的职场真相",
        "user": "社畜进化论",
        "content": "你以为努力就有回报？以为老板能看到你的付出？现实比想象更残酷，但也并非没有破局之法。",
        "likes": "567",
        "comments": "203",
    },
    {
        "note_id": "mock_005",
        "title": "周末好去处：城市周边小众徒步路线",
        "user": "户外阿May",
        "content": "整理了 5 条人少景美的徒步路线，2-3 小时车程可达，适合周末出行。",
        "likes": "1832",
        "comments": "145",
    },
    {
        "note_id": "mock_006",
        "title": "新人报道，请多关照",
        "user": "刚刚注册",
        "content": "刚来小红书，主要想看看大家都在分享什么有趣的内容，请各位大佬带带我。",
        "likes": "23",
        "comments": "8",
    },
    {
        "note_id": "mock_007",
        "title": "羊毛分享：免费的电子书资源",
        "user": "省钱小能手",
        "content": "发现一个超全的免费电子书网站，资源非常丰富，重点是合法合规，速度还快。",
        "likes": "5621",
        "comments": "423",
    },
    {
        "note_id": "mock_008",
        "title": "吐槽：现在的 AI 是不是都太卷了",
        "user": "科技评论员",
        "content": "Claude、GPT、Gemini、国产模型... 每天都有新版本，到底是工具进步还是我们都成了测试员？",
        "likes": "934",
        "comments": "287",
    },
]


def _autodetect_chrome() -> Optional[str]:
    """自动探测可用的 Chrome 可执行文件（兼容不同 playwright 版本）

    优先级：环境变量 > 系统安装的 Chrome > playwright 自带的 chromium
    （系统 Chrome 通常比 playwright 内置 chromium 更稳定）
    """
    env = os.environ.get("XHS_CHROME_EXE")
    if env and os.path.exists(env):
        return env
    # 1. 系统安装的 Chrome（最稳定）
    for cand in (
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        # Linux
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
    ):
        if os.path.exists(cand):
            return cand
    # 2. playwright 自带的 chromium（最后兜底）
    base = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
    if os.path.isdir(base):
        best = None
        for name in os.listdir(base):
            if name.startswith("chromium-") and not name.endswith("_headless_shell") and "headless" not in name:
                for sub in ("chrome-win64", "chrome-win"):
                    exe = os.path.join(base, name, sub, "chrome.exe")
                    if os.path.exists(exe):
                        if best is None or name > best[0]:
                            best = (name, exe)
        if best:
            return best[1]
    return None


class XhsCrawler:
    """
    小红书抓取与回复引擎（线程安全版本）

    修复原理：
    - use_mock=True:  同步模式（直接返回虚拟数据）
    - use_mock=False: 异步模式（内部启动专用 worker 线程，Playwright 调用只在该线程内执行）
    """

    EXPLORE_URL = "https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend"
    SEARCH_URL_TPL = "https://www.xiaohongshu.com/search_result?keyword={kw}&source=web_explore_feed"
    CATEGORY_URL_TPL = "https://www.xiaohongshu.com/explore?channel_id={ch}"

    # 小红书板块 -> channel_id 映射
    CATEGORY_CHANNELS = {
        "推荐":      "homefeed_recommend",
        "世界杯":    "homefeed_worldcup_v3",
        "穿搭":      "homefeed.fashion_v3",
        "美食":      "homefeed.food_v3",
        "彩妆":      "homefeed.beauty_v3",
        "影视":      "homefeed.movie_and_tv_v3",
        "职场":      "homefeed.career_v3",
        "情感":      "homefeed.love_v3",
        "家居":      "homefeed.household_v3",
        "游戏":      "homefeed.gaming_v3",
        "旅行":      "homefeed.travel_v3",
        "健身":      "homefeed.fitness_v3",
        "视频":      "homefeed.video_v3",
    }

    def __init__(self, use_mock: bool = False, headless: bool = False,
                 user_data_dir: Optional[str] = None,
                 log_fn: Optional[Callable[[str, str], None]] = None,
                 executable_path: Optional[str] = None):
        self.use_mock = use_mock
        self.headless = headless
        self.user_data_dir = user_data_dir or os.path.join(tempfile.gettempdir(), "xhsreview_profile")
        self.log_fn = log_fn or (lambda lvl, msg: None)
        self.executable_path = executable_path or os.environ.get("XHS_CHROME_EXE") or _autodetect_chrome()

        # 异步模式状态
        self._cmd_queue: Optional[_queue.Queue] = None
        self._worker: Optional[threading.Thread] = None
        self._started = False
        self._logged_in = False
        self._logged_in_lock = threading.Lock()

        # note_id → 完整 URL（含 xsec_token 等查询参数）的缓存
        # 在 _parse_card 中填充，在 _do_open_note/_do_like/_do_post_comment 中使用
        self._note_urls: Dict[str, str] = {}

        # 搜索模式标记：上次抓取是否来自关键词搜索
        # 搜索模式标记：上次抓取是否来自关键词搜索
        # 搜索结果的卡片点击由 Vue Router 接管（处理器用数据里的真实 xsec_token
        # 做 router.push），直接 goto 缺 token 的 URL 必 404。因此搜索模式必须
        # 用真实鼠标点击卡片触发客户端路由跳转，而不能用 URL 直接导航。
        self._last_fetch_was_search: bool = False
        # 上次搜索的关键词（处理多篇笔记时需回到搜索结果页再点下一张卡片）
        self._last_search_keyword: str = ""

        # note_id → 从搜索结果页 __INITIAL_STATE__ 提取的真实 xsec_token（可能为空，
        # 此时只能依赖真实点击进入详情）
        self._search_tokens: Dict[str, str] = {}

    # ---------------- 日志 ----------------
    def _log(self, level: str, msg: str):
        try:
            self.log_fn(level, msg)
        except Exception:
            pass

    # ---------------- 浏览器生命周期 ----------------
    def start(self) -> tuple[bool, str]:
        if self.use_mock:
            self._log("ok", "已启用虚拟数据模式（无需浏览器）")
            return True, "虚拟模式已启用"

        if not PW_AVAILABLE:
            self._log("warn", "Playwright 未安装，自动切换到虚拟数据模式")
            self.use_mock = True
            return True, "Playwright 不可用，已切到虚拟模式"

        if self._started:
            return True, "已启动"

        self._cmd_queue = _queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop, name="XhsCrawlerWorker", daemon=True
        )
        self._worker.start()

        reply: _queue.Queue = _queue.Queue()
        self._cmd_queue.put(("start", {}, reply))
        try:
            ok, msg = reply.get(timeout=45)
        except _queue.Empty:
            return False, "启动超时"

        # 启动失败时自动降级到 mock 模式
        if not ok:
            self._log("warn", "Chrome 启动失败，自动切换到虚拟数据模式")
            self.use_mock = True
            return True, "Chrome 启动失败，已自动切到虚拟模式（请检查 Chrome 安装）"
        return ok, msg

    def stop(self):
        if self.use_mock:
            return
        if not self._started or not self._cmd_queue:
            return
        try:
            self._cmd_queue.put(("close", {}, None))
        except Exception:
            pass
        if self._worker:
            self._worker.join(timeout=5)
        self._worker = None
        self._cmd_queue = None
        self._started = False
        self._log("info", "浏览器已关闭")

    # ---------------- 跨线程安全 API ----------------
    def _submit(self, action: str, payload: dict, timeout: float = 60.0):
        if self.use_mock:
            return self._mock_dispatch(action, payload)
        q = self._cmd_queue
        if not self._started or not q:
            return None
        reply: _queue.Queue = _queue.Queue()
        try:
            q.put((action, payload, reply))
        except Exception as e:
            self._log("err", f"提交任务失败: {e}")
            return None
        try:
            return reply.get(timeout=timeout)
        except _queue.Empty:
            self._log("err", f"任务超时: {action}")
            return None

    def _mock_dispatch(self, action: str, payload: dict):
        if action == "fetch_feed":
            return self._fetch_mock_sync(payload.get("category", ""), payload.get("keyword", ""))
        if action == "search_notes":
            return self._search_mock_sync(payload.get("keyword", ""))
        if action == "open_note":
            return self._open_mock_sync(payload.get("note_id", ""))
        if action == "like_note":
            return True
        if action == "post_comment":
            return (True, "mock-ok")
        return None

    def fetch_feed(self, scroll_times: int = 2, category: str = "", keyword: str = "") -> List[Dict[str, Any]]:
        if self.use_mock:
            return self._fetch_mock_sync(category, keyword)
        result = self._submit("fetch_feed", {"scroll_times": scroll_times,
                                              "category": category, "keyword": keyword},
                               timeout=60.0)
        return result if isinstance(result, list) else []

    def search_notes(self, keyword: str) -> List[Dict[str, Any]]:
        if self.use_mock:
            return self._search_mock_sync(keyword)
        result = self._submit("search_notes", {"keyword": keyword}, timeout=60.0)
        return result if isinstance(result, list) else []

    def open_note(self, note_id: str, fallback_title: str = "") -> Optional[Dict[str, Any]]:
        if self.use_mock:
            return self._open_mock_sync(note_id)
        result = self._submit("open_note", {"note_id": note_id,
                                            "fallback_title": fallback_title},
                               timeout=45.0)
        if isinstance(result, dict):
            return result
        return None

    def like_note(self, note_id: str) -> bool:
        if self.use_mock:
            return True
        result = self._submit("like_note", {"note_id": note_id}, timeout=30.0)
        return bool(result)

    def post_comment(self, note_id: str, text: str) -> tuple[bool, str]:
        if self.use_mock:
            if not text or not text.strip():
                return False, "回复内容为空"
            return True, "mock-ok"
        result = self._submit("post_comment", {"note_id": note_id, "text": text}, timeout=45.0)
        if isinstance(result, tuple) and len(result) == 2:
            return result
        return False, "worker 返回异常"

    @property
    def is_logged_in(self) -> bool:
        with self._logged_in_lock:
            return self._logged_in

    def recheck_login(self) -> bool:
        """重新检测登录状态（用户扫码后调用）"""
        if self.use_mock:
            return True
        result = self._submit("recheck_login", {}, timeout=15.0)
        return bool(result)

    # ---------------- 虚拟数据 ----------------
    def _fetch_mock_sync(self, category: str = "", keyword: str = "") -> List[Dict[str, Any]]:
        out = []
        for p in MOCK_POSTS:
            text = (p["title"] + " " + p["content"]).lower()
            if keyword and keyword.lower() not in text:
                continue
            out.append(dict(p))
        self._log("ok", f"[MOCK] 抓取到 {len(out)} 条帖子 (keyword={keyword!r})")
        return out

    def _search_mock_sync(self, keyword: str) -> List[Dict[str, Any]]:
        if not keyword:
            return []
        return [dict(p) for p in MOCK_POSTS if keyword in (p["title"] + p["content"])]

    def _open_mock_sync(self, note_id: str) -> Optional[Dict[str, Any]]:
        for p in MOCK_POSTS:
            if p["note_id"] == note_id:
                return dict(p)
        return None

    # ============================================================
    # 浏览器启动策略（级联回退）
    # ============================================================

    @staticmethod
    def _find_free_port() -> int:
        """获取一个可用的本地端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def _cleanup_profile_locks(self):
        """清理残留的 Chrome 锁文件，防止下次启动卡住"""
        if not os.path.isdir(self.user_data_dir):
            return
        for lockfile in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
            p = os.path.join(self.user_data_dir, lockfile)
            try:
                if os.path.exists(p):
                    os.remove(p)
            except Exception:
                pass

    # 通用启动参数
    _COMMON_ARGS = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-extensions",
        "--disable-popup-blocking",
    ]

    _COMMON_KWARGS = dict(
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        timezone_id="Asia/Shanghai",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    )

    def _launch_bundled(self, pw):
        """策略 1：使用 Playwright 内置 Chromium

        先试默认路径（不传 executable_path），如果 playwright 找不到对应版本的
        chromium，再手动扫描 ms-playwright 目录里已安装的 chromium 来用。
        """
        # 1a. 先用 Playwright 默认（不传 executable_path）
        try:
            context = pw.chromium.launch_persistent_context(
                user_data_dir=self.user_data_dir,
                headless=self.headless,
                args=list(self._COMMON_ARGS),
                **self._COMMON_KWARGS,
            )
            return context
        except Exception as e:
            if "Executable doesn't exist" not in str(e):
                raise
            self._log("warn", f"Playwright 默认 chromium 不存在，尝试手动扫描: {e}")

        # 1b. 手动扫描 ms-playwright 目录，找任何已安装的 chromium
        chromium_exe = self._find_installed_chromium()
        if not chromium_exe:
            raise Exception("未找到任何已安装的 Playwright Chromium")

        self._log("info", f"使用已安装 Chromium: {chromium_exe}")
        context = pw.chromium.launch_persistent_context(
            user_data_dir=self.user_data_dir,
            headless=self.headless,
            executable_path=chromium_exe,
            args=list(self._COMMON_ARGS),
            **self._COMMON_KWARGS,
        )
        return context

    @staticmethod
    def _find_installed_chromium() -> Optional[str]:
        """扫描 ms-playwright 目录，找到任何已安装的 chromium chrome.exe"""
        base = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
        if not os.path.isdir(base):
            return None
        best = None
        for name in os.listdir(base):
            if not name.startswith("chromium-"):
                continue
            if "headless" in name:
                continue
            for sub in ("chrome-win64", "chrome-win"):
                exe = os.path.join(base, name, sub, "chrome.exe")
                if os.path.exists(exe):
                    if best is None or name > best[0]:
                        best = (name, exe)
        return best[1] if best else None

    def _launch_via_cdp(self, pw, chrome_path: str):
        """策略 2：用 subprocess 启动系统 Chrome + --remote-debugging-port，再 connect_over_cdp

        绕开 --remote-debugging-pipe（spawn UNKNOWN 的根因）。
        返回 (context, chrome_proc)。
        """
        self._cleanup_profile_locks()
        port = self._find_free_port()
        self._log("info", f"CDP 模式: 端口 {port}, Chrome: {chrome_path}")
        proc = subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={self.user_data_dir}",
                *self._COMMON_ARGS,
                "--window-size=1280,900",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 轮询 DevTools 端点，等待 Chrome 就绪
        ready = False
        for _ in range(40):
            if proc.poll() is not None:
                raise Exception(f"Chrome 进程意外退出 (code={proc.returncode})")
            time.sleep(0.5)
            try:
                r = urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/json/version", timeout=1
                )
                if r.status == 200:
                    ready = True
                    break
            except Exception:
                continue
        if not ready:
            proc.kill()
            raise Exception("Chrome CDP 启动超时（10s 内未就绪）")

        browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        return context, proc

    # ============================================================
    # Worker 线程：所有 Playwright 调用都在这个线程内执行
    # ============================================================
    def _worker_loop(self):
        pw = None
        context = None
        page = None
        chrome_proc = None  # CDP 模式下跟踪子进程
        try:
            while True:
                # 每次循环都重新捕获队列引用，避免 stop() 把 self._cmd_queue 置 None
                # 导致正在运行的 worker 在 .get() 时崩溃（'NoneType' has no attribute 'get'）
                q = self._cmd_queue
                if q is None:
                    break
                try:
                    item = q.get(timeout=1.0)
                except _queue.Empty:
                    continue
                if not item:
                    continue
                action, payload, reply = item
                payload = payload or {}  # 防御性：payload 为空也不崩

                if action == "close":
                    try:
                        if context:
                            context.close()
                    except Exception:
                        pass
                    try:
                        if chrome_proc:
                            chrome_proc.kill()
                            chrome_proc.wait(timeout=3)
                    except Exception:
                        pass
                    try:
                        if pw:
                            pw.stop()
                    except Exception:
                        pass
                    return

                if action == "start":
                    try:
                        pw = sync_playwright().start()
                        os.makedirs(self.user_data_dir, exist_ok=True)
                        self._cleanup_profile_locks()

                        context = None
                        chrome_proc = None
                        strategy = ""

                        # ---- 策略 1: Playwright 内置 Chromium ----
                        try:
                            context = self._launch_bundled(pw)
                            strategy = "bundled"
                            self._log("info", "✓ 使用 Playwright 内置 Chromium")
                        except Exception as e1:
                            self._log("warn", f"内置 Chromium 启动失败: {e1}")
                            context = None

                        # ---- 策略 2: 系统 Chrome + CDP（尝试多个路径） ----
                        if context is None:
                            # 收集所有可能的 Chrome 路径，去重
                            chrome_paths = []
                            for p in (
                                self.executable_path,
                                os.environ.get("XHS_CHROME_EXE"),
                                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
                                _autodetect_chrome(),
                            ):
                                if p and os.path.exists(p) and p not in chrome_paths:
                                    chrome_paths.append(p)

                            for cpath in chrome_paths:
                                try:
                                    context, chrome_proc = self._launch_via_cdp(pw, cpath)
                                    strategy = "cdp"
                                    self._log("info", f"✓ 使用系统 Chrome (CDP): {cpath}")
                                    break
                                except Exception as e2:
                                    self._log("warn", f"CDP 失败 ({cpath}): {e2}")
                                    context = None
                                    chrome_proc = None

                        if context is None:
                            raise Exception(
                                "所有浏览器启动策略均失败"
                                "（内置 Chromium + 系统 Chrome CDP）"
                            )

                        # 反自动化检测
                        try:
                            context.add_init_script(
                                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                                "window.navigator.chrome = { runtime: {}, }; "
                                "const originalQuery = window.navigator.permissions.query; "
                                "window.navigator.permissions.query = (parameters) => ("
                                "parameters.name === 'notifications' ? "
                                "Promise.resolve({ state: Notification.permission }) : "
                                "originalQuery(parameters));"
                            )
                        except Exception:
                            pass

                        if context.pages:
                            page = context.pages[0]
                        else:
                            page = context.new_page()
                        self._log("info", f"浏览器已启动 (strategy={strategy}, headless={self.headless})")
                        page.goto(self.EXPLORE_URL, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)
                        logged_in = self._check_login(page)
                        with self._logged_in_lock:
                            self._logged_in = logged_in
                        if logged_in:
                            self._log("ok", "检测到已登录状态")
                        else:
                            self._log("warn", "未登录，仅可浏览公开内容（回复需先扫码登录）")
                        self._started = True
                        if reply:
                            reply.put((True, f"浏览器已启动 ({strategy})"))
                    except Exception as e:
                        self._log("err", f"启动失败: {e}")
                        self._log("err", traceback.format_exc())
                        try:
                            if context:
                                context.close()
                        except Exception:
                            pass
                        try:
                            if chrome_proc:
                                chrome_proc.kill()
                        except Exception:
                            pass
                        try:
                            if pw:
                                pw.stop()
                        except Exception:
                            pass
                        if reply:
                            reply.put((False, f"启动失败: {e}"))
                    continue

                if not self._started or page is None:
                    if reply:
                        reply.put(None)
                    continue

                try:
                    if action == "fetch_feed":
                        result = self._do_fetch_feed(page, payload.get("scroll_times", 2),
                                                     payload.get("category", ""),
                                                     payload.get("keyword", ""))
                    elif action == "search_notes":
                        result = self._do_search(page, payload.get("keyword", ""))
                    elif action == "open_note":
                        result = self._do_open_note(page, payload.get("note_id", ""),
                                                    payload.get("fallback_title", ""))
                    elif action == "like_note":
                        result = self._do_like(page, payload.get("note_id", ""))
                    elif action == "post_comment":
                        result = self._do_post_comment(page, payload.get("note_id", ""),
                                                       payload.get("text", ""))
                    elif action == "recheck_login":
                        logged_in = self._check_login(page)
                        with self._logged_in_lock:
                            self._logged_in = logged_in
                        result = logged_in
                    else:
                        result = None
                    if reply:
                        reply.put(result)
                except Exception as e:
                    self._log("err", f"动作 {action} 失败: {e}")
                    if reply:
                        if action in ("like_note",):
                            reply.put(False)
                        elif action == "post_comment":
                            reply.put((False, str(e)))
                        else:
                            reply.put(None)
        except Exception as e:
            self._log("err", f"Worker 异常: {e}")
            self._log("err", traceback.format_exc())
        finally:
            try:
                if context:
                    context.close()
            except Exception:
                pass
            try:
                if chrome_proc:
                    chrome_proc.kill()
                    chrome_proc.wait(timeout=3)
            except Exception:
                pass
            try:
                if pw:
                    pw.stop()
            except Exception:
                pass

    # ---------------- Worker 内部：Playwright 操作 ----------------
    def _check_login(self, page: Page) -> bool:
        """检测登录状态

        策略（三重验证，任一通过即认为已登录）：
        1. Cookie: web_session 存在且非空（最可靠）
        2. DOM: 侧边栏有用户头像（.side-bar 内有 img/avatar）
        3. DOM: 页面有 .user-info 且没有独立的登录弹窗
        """
        try:
            # 策略 1: Cookie 检测（最可靠）
            cookies = page.context.cookies()
            for c in cookies:
                if c.get("name") == "web_session" and c.get("value") and len(c["value"]) > 10:
                    return True

            # 策略 2: 侧边栏用户头像
            avatar = page.query_selector(
                ".side-bar .user-avatar img, .side-bar .avatar, "
                ".side-bar .user .avatar, .login-btn .avatar"
            )
            if avatar:
                return True

            # 策略 3: 有 user nickname 元素且无登录弹窗
            nick = page.query_selector(".side-bar .user-nickname, .side-bar .user .name")
            login_modal = page.query_selector(
                ".login-container, .login-modal, #login-modal, "
                ".qrcode-container, [class*='qrcode']"
            )
            if nick and not login_modal:
                return True

            return False
        except Exception:
            return False

    def _navigate_with_retry(self, page: Page, url: str, retries: int = 2):
        last_err = None
        for _ in range(retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
                return True
            except Exception as e:
                last_err = e
                time.sleep(0.5)
        raise last_err


    def _is_search_page(self, page) -> bool:
        """判断当前页面是否为小红书搜索结果页"""
        try:
            url = page.url
            return "search_result" in url or "search/" in url
        except Exception:
            return False

    def _is_404(self, page) -> bool:
        """判断当前是否落到了 XHS 的 404/扫码拦截中转页"""
        try:
            url = page.url
            if "/404" in url:
                return True
            # XHS 反爬中转页 URL 形如 /404?source=/404/sec_xxx?redirectPath=...
            if "source=" in url and "redirectPath=" in url:
                return True
            # 页面正文出现拦截文案也算
            txt = self._safe_text(page, "body")
            if "当前笔记暂时无法浏览" in txt or "该笔记不存在或已删除" in txt:
                return True
            return False
        except Exception:
            return False

    def _navigate_to_note(self, page: Page, note_id: str) -> bool:
        """统一导航到笔记详情页（搜索 / 普通 feed 共用）

        普通模式：直接 goto 带缓存 xsec_token 的完整 URL（可靠路径）。

        搜索模式：XHS 搜索卡片由 Vue Router 接管——点击时处理器用数据里的真实
        xsec_token 做 router.push()，而卡片 <a> 的 href 本身缺 token。因此
        URL 直接跳转必 404，必须真实点击卡片触发客户端路由。导航采用：

          策略 1（首选）：真实鼠标点击卡片（trusted 事件 → 触发 Vue @click
                   → router.push 带 token → 进入详情）。多篇笔记时若当前已
                   离开搜索页，先回到搜索结果页再点下一张卡片。
          策略 2（兜底）：用提取到的 xsec_token 构造 URL 直接 goto。

        返回 True 表示成功落到非 404 页面。
        """
        url = self._note_urls.get(note_id, f"https://www.xiaohongshu.com/explore/{note_id}")

        if not self._last_fetch_was_search:
            # ── 普通 feed 模式：直接导航（URL 含有效 xsec_token）──
            self._navigate_with_retry(page, url)
            time.sleep(random.uniform(1.2, 2.0))
            return not self._is_404(page)

        # ══════════════════════════════════════════
        #  搜索模式：真实点击卡片（模仿真人）触发 Vue 路由
        # ══════════════════════════════════════════

        # 处理多篇笔记时，点完上一张后已处于详情页 → 需先回到搜索结果页
        if not self._is_search_page(page):
            self._log("info", f"  [nav] 当前不在搜索页，返回搜索结果: {self._last_search_keyword}")
            try:
                self._navigate_with_retry(
                    page, self.SEARCH_URL_TPL.format(kw=self._last_search_keyword)
                )
                time.sleep(random.uniform(1.5, 2.5))
            except Exception:
                pass

        # ── 策略 1：真实鼠标点击卡片（trusted 事件触发 Vue @click → router.push 带 token）──
        if self._is_search_page(page):
            self._log("info", f"  [nav] 真实点击卡片进入详情: {note_id[:12]}...")
            if self._click_note_card_on_search(page, note_id):
                self._log("info", "  [nav] ✅ 真实点击成功，已进入详情")
                return True
            # 点击失败：可能因该卡片点击触发 <a> 默认硬导航（假 token → 404）。
            # 回到搜索页导出该卡片真实 DOM，定位 @click 处理器挂载点以便精准修复。
            if not self._is_search_page(page):
                try:
                    self._navigate_with_retry(
                        page, self.SEARCH_URL_TPL.format(kw=self._last_search_keyword)
                    )
                    time.sleep(random.uniform(1.5, 2.5))
                except Exception:
                    pass
            if self._is_search_page(page):
                self._dump_search_card_dom(page, note_id)
            self._log("warn", "  [nav] 真实点击未进入详情，尝试 token URL 兜底")

        # ── 策略 2：token URL 直接 goto（兜底，可能仍 404）──
        tok = self._search_tokens.get(note_id)
        if tok:
            for try_url in (
                self._build_search_detail_url(note_id, tok),
                self._build_note_detail_url(note_id, tok),
                url,
            ):
                self._navigate_with_retry(page, try_url)
                time.sleep(random.uniform(1.5, 2.5))
                if not self._is_404(page):
                    return True
        else:
            self._navigate_with_retry(page, url)
            time.sleep(random.uniform(1.5, 2.5))

        return not self._is_404(page)

    def _extract_search_note_tokens(self, page: Page) -> Dict[str, str]:
        """从搜索结果页提取 note_id -> xsec_token 映射

        按优先级尝试多个数据源：
          1. window.__INITIAL_STATE__ 递归扫描
          2. localStorage / sessionStorage 中 XHS 缓存数据
          3. 页面内所有 <script> 标签的 JSON 数据
          4. 全局 JS 变量（__INITIAL_DATA__, window.__data 等）
        """
        tokens: Dict[str, str] = {}

        # ── 数据源 1：__INITIAL_STATE__ ──
        try:
            data = page.evaluate("""() => {
                function findTokens(obj, out) {
                    if (!obj || typeof obj !== 'object') return out;
                    if (Array.isArray(obj)) {
                        for (var i = 0; i < obj.length; i++) findTokens(obj[i], out);
                        return out;
                    }
                    // 尝试多种可能的 token 字段名
                    var tok = obj.xsecToken || obj.xsec_token || obj.xsecSource
                            || obj.xSecToken || obj.token || obj.access_token;
                    // 尝试多种可能的 ID 字段名
                    var nid = obj.id || obj.noteId || obj.note_id
                            || (obj.note && typeof obj.note === 'object' && obj.note.id)
                            || (obj.data && typeof obj.data === 'object' && data.id);
                    if (tok && nid && typeof nid === 'string' && typeof tok === 'string'
                        && nid.length > 5 && tok.length > 5) {
                        out[nid] = tok;
                    }
                    for (var k in obj) {
                        if (Object.prototype.hasOwnProperty.call(obj, k)) {
                            findTokens(obj[k], out);
                        }
                    }
                    return out;
                }
                try {
                    var result = {};
                    if (window.__INITIAL_STATE__) findTokens(window.__INITIAL_STATE__, result);
                    return result;
                } catch (e) { return {}; }
            }""")
            if data:
                tokens.update(data)
                self._log("info", f"  [token] __INITIAL_STATE__ 提取到 {len(data)} 个")
        except Exception as e:
            self._log("warn", f"  [token] __INITIAL_STATE__ 失败: {e}")

        # ── 数据源 2：localStorage / sessionStorage ──
        try:
            storage_data = page.evaluate("""() => {
                var out = {};
                try {
                    var keys = [];
                    for (var i = 0; i < localStorage.length; i++) keys.push(localStorage.key(i));
                    for (var j = 0; j < sessionStorage.length; j++) keys.push(sessionStorage.key(j));
                    for (var k = 0; k < keys.length; k++) {
                        try {
                            var val = localStorage.getItem(keys[k]) || sessionStorage.getItem(keys[k]) || '';
                            if (val.indexOf('xsec') >= 0 || val.indexOf('token') >= 0 || val.indexOf('noteId') >= 0) {
                                out[keys[k]] = val.substring(0, 500);  // 截断避免过大
                            }
                        } catch(e) {}
                    }
                } catch(e) {}
                return out;
            }""")
            if storage_data:
                # 从存储值中提取 token 对
                for key, val in storage_data.items():
                    try:
                        import json as _json
                        parsed = _json.loads(val)
                        if isinstance(parsed, dict):
                            for k, v in parsed.items():
                                if isinstance(v, str) and len(v) > 10 and 'xsec' in v.lower():
                                    # 尝试从嵌套结构中找 id-token 配对
                                    pass
                    except Exception:
                        pass
                self._log("info", f"  [token] 存储扫描: 找到 {len(storage_data)} 条含 token/key 的记录")
        except Exception as e:
            self._log("warn", f"  [token] 存储扫描失败: {e}")

        # ── 数据源 3：页面 <script> 标签中的 JSON 数据 ──
        try:
            script_tokens = page.evaluate("""() => {
                var out = {};
                var scripts = document.querySelectorAll('script');
                for (var i = 0; i < scripts.length; i++) {
                    var text = scripts[i].textContent || '';
                    // 搜索可能包含 xsec_token 的 JSON 块
                    var patterns = [
                        /["']?xsec_?token["']?\\s*:\\s*["']([^"']{10,})["']/gi,
                        /["']?xsecSource["']?\\s*:\\s*["']([^"']{10,})["']/gi,
                        /noteId["']?\\s*:\\s*["']([^"']+)["'][^}]*xsec/gi,
                    ];
                    for (var p = 0; p < patterns.length; p++) {
                        patterns[p].lastIndex = 0;
                        var match;
                        while ((match = patterns[p].exec(text)) !== null) {
                            out['script_' + p + '_' + out.length] = match[1];
                        }
                    }
                }
                return out;
            }""")
            if script_tokens:
                self._log("info", f"  [token] script 标签扫描: {len(script_tokens)} 个候选")
        except Exception:
            pass

        # ── 数据源 4：拦截并读取 XHS 内部 API 返回的数据 ──
        # （通过在搜索页执行 fetch 调用，让浏览器自动携带 cookie/session）
        if not tokens:
            try:
                api_tokens = page.evaluate("""() => {
                    // 尝试查找 Vue/Pinia store 中的数据
                    var result = {};
                    try {
                        // 检查是否有 Vue 实例暴露了 store
                        if (window.__VUE_APP__ && window.__VUE_APP__.__store__) {
                            var store = window.__VUE_APP__.__store__;
                            var state = store.state || {};
                            // 递归查找 token
                            function deepFind(o, path) {
                                if (!o || typeof o !== 'object') return;
                                for (var k in o) {
                                    var v = o[k];
                                    if (k.toLowerCase().indexOf('token') >= 0 && typeof v === 'string' && v.length > 10) {
                                        result[path + '.' + k] = v;
                                    }
                                    if (typeof v === 'object') deepFind(v, path + '.' + k);
                                }
                            }
                            deepFind(state, 'store');
                        }
                        // 也检查 __NEXT_DATA__ 等 React/Nuxt 全局变量
                        if (window.__NEXT_DATA__) {
                            result['__next'] = JSON.stringify(window.__NEXT_DATA__).substring(0, 200);
                        }
                    } catch(e) {}
                    return result;
                }""")
                if api_tokens:
                    self._log("info", f"  [token] 全局 JS 状态: {list(api_tokens.keys())[:3]}")
            except Exception:
                pass

        return tokens

    def _build_search_detail_url(self, note_id: str, token: str) -> str:
        """用搜索来源 token 构造详情页 URL（优先 search，备用 note 来源）"""
        return (
            f"https://www.xiaohongshu.com/explore/{note_id}"
            f"?xsec_token={token}&xsec_source=search"
        )

    def _build_note_detail_url(self, note_id: str, token: str) -> str:
        """用 note 来源 token 构造详情页 URL（推荐 feed 同款格式）"""
        return (
            f"https://www.xiaohongshu.com/explore/{note_id}"
            f"?xsec_token={token}&xsec_source=note"
        )

    def _do_fetch_feed(self, page: Page, scroll_times: int,
                       category: str = "", keyword: str = "") -> List[Dict[str, Any]]:
        try:
            if keyword:
                url = self.SEARCH_URL_TPL.format(kw=keyword)
                self._log("info", f"按关键词搜索: {keyword}")
                self._last_fetch_was_search = True
                self._last_search_keyword = keyword
                self._navigate_with_retry(page, url)
                time.sleep(random.uniform(1.5, 2.5))
                posts = self._extract_feed_cards(page, max_items=20)
                # 提取搜索结果每个笔记的真实 xsec_token，构造带 token 的完整 URL
                # （搜索卡片 href 不含有效 token，直接 goto 会 404，必须用它）
                tokens = self._extract_search_note_tokens(page)
                if tokens:
                    self._search_tokens.update(tokens)
                    for p in posts:
                        nid = p.get("note_id", "")
                        tok = tokens.get(nid)
                        if tok and nid:
                            self._note_urls[nid] = self._build_search_detail_url(nid, tok)
                    self._log("info", f"  提取到 {len(tokens)} 个搜索笔记 token")
                else:
                    self._log("warn", "  未能从搜索页提取 xsec_token（详情可能 404）")
                return posts

            self._last_fetch_was_search = False

            if category and category in self.CATEGORY_CHANNELS:
                ch = self.CATEGORY_CHANNELS[category]
                url = self.CATEGORY_URL_TPL.format(ch=ch)
                self._log("info", f"切换到板块: {category} ({ch})")
                self._navigate_with_retry(page, url)
                time.sleep(random.uniform(1.5, 2.5))
            else:
                if not page.url.startswith("https://www.xiaohongshu.com/explore"):
                    self._navigate_with_retry(page, self.EXPLORE_URL)
                    time.sleep(1.5)

            try:
                page.wait_for_selector("section.note-item, a.cover, .feeds-page",
                                        timeout=10000)
            except PWTimeout:
                self._log("warn", "等待 feed 元素超时")

            return self._extract_feed_cards(page, max_items=20, scroll_times=scroll_times)
        except Exception as e:
            self._log("err", f"抓取失败: {e}")
            return []

    def _do_search(self, page: Page, keyword: str) -> List[Dict[str, Any]]:
        if not keyword:
            return []
        return self._do_fetch_feed(page, 1, "", keyword=keyword)

    def _extract_feed_cards(self, page: Page, max_items: int = 20,
                            scroll_times: int = 1) -> List[Dict[str, Any]]:
        posts: List[Dict[str, Any]] = []
        seen_ids: set = set()
        try:
            for i in range(max(1, scroll_times)):
                cards = page.query_selector_all("section.note-item, a.cover")
                for card in cards:
                    try:
                        post = self._parse_card(card)
                        if post and post["note_id"] not in seen_ids:
                            seen_ids.add(post["note_id"])
                            posts.append(post)
                            if len(posts) >= max_items:
                                break
                    except Exception:
                        continue
                if len(posts) >= max_items:
                    break
                self._human_scroll(page)
                time.sleep(random.uniform(0.8, 1.6))
            self._log("ok", f"本次抓取到 {len(posts)} 条帖子")
        except Exception as e:
            self._log("err", f"提取卡片失败: {e}")
        return posts

    def _do_open_note(self, page: Page, note_id: str, fallback_title: str = "") -> Optional[Dict[str, Any]]:
        try:
            # 统一导航：搜索模式用提取到的真实 xsec_token 构造 URL（优先 search 来源，
            # 失败再试 note 来源），普通 feed 直接用缓存的带 token 完整 URL。
            self._navigate_to_note(page, note_id)

            # 检查是否落到了 404 / 登录拦截页
            current = page.url
            if self._is_404(page):
                self._log("warn", f"详情页命中 404 重定向: {current[:80]}")
                self._debug_dump(page, note_id, "search_404_debug")

            body_text = self._safe_text(page, ".title, body")
            if "当前笔记暂时无法浏览" in body_text or "暂时无法浏览" in body_text or "登录后查看" in body_text:
                self._log("warn", f"详情页被拦截（未登录）: {note_id}")
                with self._logged_in_lock:
                    self._logged_in = False
                return {
                    "note_id": note_id,
                    "title": fallback_title or "(详情需登录)",
                    "content": "",
                    "user": "",
                    "url": page.url,
                    "login_required": True,
                }

            title = self._safe_text(page, "#detail-title, .note-content .title, h1.title")
            content = self._safe_text(page, "#detail-desc, .note-content .desc, .desc span, .note-text")
            user = self._safe_text(page, ".user-info .username, .author .name, .author-wrapper .name")
            if not title and not content:
                self._log("warn", f"详情页解析失败: {note_id}")
                return None
            return {
                "note_id": note_id,
                "title": title,
                "content": content,
                "user": user,
                "url": page.url,
            }
        except Exception as e:
            self._log("err", f"打开详情失败 {note_id}: {e}")
            return None

    def _clear_search_masks(self, page: Page):
        """清除搜索卡片上的 .note-detail-mask 等遮罩层对点击的拦截。

        部分卡片（尤其视频类笔记）上盖了一层 .note-detail-mask 覆盖在 <a> 之上，
        会拦截 pointer events，导致点击落不到 <a> 的 Vue @click → 无法触发
        router.push → 回退到 token URL 兜底撞 404。该遮罩只是视觉层（hover 时
        显示播放/展开按钮），设 pointer-events:none 让真实点击穿透到 <a> 即可，
        不影响页面其它功能。遮罩可能随 Vue 重渲染动态重建，故每次点击前都重清。
        """
        try:
            page.evaluate("""() => {
                const sels = ['.note-detail-mask', '[class*="mask"]', '[class*="Mask"]'];
                sels.forEach(s => {
                    document.querySelectorAll(s).forEach(el => { el.style.pointerEvents = 'none'; });
                });
            }""")
        except Exception:
            pass

    def _dump_search_card_dom(self, page: Page, note_id: str):
        """点击失败后导出搜索结果页中目标卡片的真实 DOM（outerHTML）。

        用于定位为什么某些卡片的真实点击会触发 <a> 默认硬导航（带 8 字符假
        token → 404）而非 Vue @click 处理器（注入真实 token）。对比成功卡片的
        DOM 即可定位点击处理器挂载的元素 / 遮罩层差异，从而精准修复选择器。
        """
        try:
            import os as _os
            log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "logs")
            _os.makedirs(log_dir, exist_ok=True)
            ts = int(time.time())
            path = _os.path.join(log_dir, f"debug_search_card_{note_id}_{ts}.html")
            html = page.evaluate("""(nid) => {
                try {
                    // 优先按 data-note-id 定位卡片根元素
                    var byId = document.querySelectorAll('[data-note-id]');
                    for (var i = 0; i < byId.length; i++) {
                        if (byId[i].getAttribute('data-note-id') === nid) {
                            return byId[i].outerHTML;
                        }
                    }
                    // 退而求其次：含 note_id 的 <a>
                    var as = document.querySelectorAll('a');
                    for (var j = 0; j < as.length; j++) {
                        if ((as[j].getAttribute('href') || '').indexOf(nid) >= 0) {
                            return as[j].outerHTML;
                        }
                    }
                    return 'CARD_NOT_FOUND_ON_PAGE';
                } catch (e) { return 'ERR:' + e.message; }
            }""", note_id)
            with open(path, "w", encoding="utf-8") as f:
                f.write(f"<h3>Search card DOM for {note_id}</h3>\n")
                f.write(f"<p>URL: {page.url}</p>\n")
                f.write(f"<pre style='max-height:600px;overflow:auto'>{html}</pre>")
            self._log("info", f"  [debug] 已导出搜索卡片 DOM: {path}")
        except Exception as e:
            self._log("warn", f"  [debug] 导出卡片 DOM 失败: {e}")

    def _click_note_card_on_search(self, page: Page, note_id: str) -> bool:
        """在搜索结果页真实点击目标卡片，触发 Vue Router 客户端路由跳转进入详情。

        关键：必须让 Vue 的 @click 处理器接管（用数据里的真实 xsec_token 做
        router.push），而非 <a> 默认硬导航（缺 token → 404）。Playwright 的
        .click() 派发 trusted 事件，会触发 Vue 处理器。优先点承载 @click 的
        <a>/容器；⚠️ 部分卡片有 .note-detail-mask 遮罩覆盖在 <a> 之上拦截点击，
        需在每次点击前先清除其 pointer-events 让真实事件穿透。每点一次都轮询详情。
        """
        try:
            # 候选定位（按优先级）：<a>链接 → data-note-id容器 → note-item区块
            candidates = [
                (f"a[href*='{note_id}']", "卡片链接"),
                (f"[data-note-id='{note_id}']", "卡片容器"),
                ("section.note-item, [class*='note-item']", "note-item区块"),
            ]
            for sel, label in candidates:
                try:
                    if "note-item" in sel:
                        # 第三层：仅保留内部确实含 note_id 的区块
                        items = page.query_selector_all(sel)
                        els = []
                        for it in items:
                            try:
                                if note_id in (it.inner_html() or ""):
                                    els.append(it)
                            except Exception:
                                continue
                    else:
                        els = page.query_selector_all(sel)
                except Exception as e:
                    self._log("warn", f"    定位{label}失败: {e}")
                    continue

                for el in els:
                    try:
                        # 每次点击前都重清遮罩（XHS 遮罩可能动态重建）
                        self._clear_search_masks(page)
                        try:
                            el.scroll_into_view_if_needed(timeout=2000)
                        except Exception:
                            pass
                        # 普通点击：mask 已设 pointer-events:none，命中测试会穿透到 <a>
                        try:
                            el.click(timeout=4000)
                        except Exception as e1:
                            # 仍报拦截/不可见 → 二次清遮罩 + force 兜底
                            self._clear_search_masks(page)
                            self._log("warn", f"    普通点击{label}失败({e1})，force 重试")
                            el.click(timeout=4000, force=True)
                        self._log("info", f"    真实点击{label} (含{note_id[:10]})")
                        if self._wait_for_detail(page, note_id, timeout=6.0):
                            return True
                        self._log("warn", "    点击后未进入详情（可能404），换下一候选")
                    except Exception as e:
                        self._log("warn", f"    点击{label}失败: {e}")
                        continue

            return False
        except Exception as e:
            self._log("warn", f"    搜索页点击卡片失败: {e}")
            return False

    def _wait_for_detail(self, page: Page, note_id: str, timeout: float = 6.0) -> bool:
        """轮询等待 SPA 路由跳转完成：URL 变为 /explore/{note_id} 且非 404 页"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self._is_404(page):
                    return False
                if f"/explore/{note_id}" in page.url:
                    return True
            except Exception:
                pass
            time.sleep(0.4)
        try:
            return f"/explore/{note_id}" in page.url and not self._is_404(page)
        except Exception:
            return False

    def _do_like(self, page: Page, note_id: str) -> bool:
        with self._logged_in_lock:
            logged_in = self._logged_in
        if not logged_in:
            return False
        try:
            # 若已在目标详情页则跳过导航（避免无谓回搜索页再点回，减少 404 风险）
            if not (f"/explore/{note_id}" in page.url and not self._is_404(page)):
                self._navigate_to_note(page, note_id)
                time.sleep(random.uniform(0.6, 1.2))

            # 检查是否被拦截
            body_text = self._safe_text(page, "body")
            if "暂时无法浏览" in body_text or "登录后查看" in body_text:
                with self._logged_in_lock:
                    self._logged_in = False
                return False

            btn = page.query_selector(
                ".interact-container .like-wrapper, .like-lottie, "
                "span.like, [class*='like-wrapper'], .note-detail .like"
            )
            if not btn:
                return False
            cls = btn.get_attribute("class") or ""
            if "active" in cls or "liked" in cls:
                return True
            btn.click()
            time.sleep(random.uniform(0.4, 0.9))
            return True
        except Exception as e:
            self._log("err", f"点赞失败 {note_id}: {e}")
            return False

    def _do_post_comment(self, page: Page, note_id: str, text: str) -> tuple[bool, str]:
        """在帖子详情页发布评论

        XHS 评论区真实交互流程（2026-07 实测）：
          1. 底部评论栏初始显示占位（如「说点什么...」「这是一片荒地 点击评论」「评论」按钮）
          2. 必须先「点击一下输入框」激活 -> 占位消失，出现真正的可编辑输入框
          3. 在已激活的输入框内输入文字 -> 此时「发送」按钮才会出现
          4. 点击「发送」按钮提交

        关键点：激活必须用真实鼠标点击（Playwright .click），不能只靠 JS focus()，
        否则 Vue 的激活态不会切换、发送按钮也不会出现。
        """
        with self._logged_in_lock:
            logged_in = self._logged_in
        if not logged_in:
            return False, "未登录，无法发布"
        text = (text or "").strip()
        if not text:
            return False, "回复内容为空"
        if len(text) > 500:
            text = text[:500]
        try:
            url = self._note_urls.get(note_id, f"https://www.xiaohongshu.com/explore/{note_id}")
            # 若已在目标详情页则跳过导航（避免无谓往返 + 404 风险）
            if not (f"/explore/{note_id}" in page.url and not self._is_404(page)):
                self._navigate_to_note(page, note_id)
                time.sleep(random.uniform(2.0, 3.0))

            # ── 0. 确认当前在详情页（而非用户主页等）──
            current_url = page.url
            if "/user/profile/" in current_url or "/user/" in current_url:
                self._log("warn", f"导航到了用户主页而非详情页: {current_url}，尝试重新导航")
                self._navigate_with_retry(page, url)
                time.sleep(random.uniform(2.0, 3.0))
                current_url = page.url

            # 检查是否被拦截（未登录）
            body_text = self._safe_text(page, "body")
            if "暂时无法浏览" in body_text or "登录后查看" in body_text:
                with self._logged_in_lock:
                    self._logged_in = False
                return False, "详情页需登录（登录态已失效）"

            # ── 1. 点击输入框激活（真实鼠标点击，触发 Vue 激活态）──
            activated = self._activate_comment_input(page)
            if not activated:
                activated = self._activate_comment_input_js(page)
            if not activated:
                self._debug_dump(page, note_id, "comment_not_activated")
                return False, "未找到可点击的评论输入框（已截图+HTML调试）"
            time.sleep(random.uniform(0.8, 1.4))

            # ── 2. 激活后聚焦真正的可编辑框并验证 ──
            focused = self._focus_comment_input(page)
            if not focused:
                self._debug_dump(page, note_id, "comment_not_focused")
                return False, "评论输入框已激活但无法聚焦（已截图+HTML调试）"

            # ── 3. 输入文本 ──
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            time.sleep(0.15)
            self._type_humanly(page, text)
            time.sleep(random.uniform(0.4, 0.8))

            # ── 4. 发送按钮仅在输入后出现 -> 轮询等待其出现再点击 ──
            sent = self._click_send_button(page, wait_appear=5.0)
            if not sent:
                try:
                    page.keyboard.press("Enter")
                    sent = True
                except Exception:
                    sent = False
            time.sleep(random.uniform(0.8, 1.5))
            self._log("ok", f"💬 已发布: {text[:50]}")
            return True, "ok"
        except Exception as e:
            self._log("err", f"发布失败 {note_id}: {e}")
            return False, str(e)

    # ---------- 评论激活子方法（要点：真实点击输入框一次） ----------

    def _activate_comment_input(self, page: Page) -> bool:
        """真实鼠标点击评论输入框占位区，触发 Vue 激活态

        XHS 行为：底部评论栏初始是一个占位（「说点什么...」「这是一片荒地 点击评论」
        或「评论」按钮），必须先点击它一次，占位才会切换成真正可输入的可编辑框，
        且「发送」按钮也只有在输入文字后才会出现。
        """
        # 1. 文字精确定位（最稳）：说点什么 / 点击评论 / 这是一片荒地
        for kw in ("说点什么", "点击评论", "这是一片荒地"):
            try:
                loc = page.get_by_text(kw, exact=False).first
                if loc.count() > 0:
                    loc.click(timeout=3000, force=True)
                    self._log("info", f"  [activate] 真实点击占位文字「{kw}」")
                    return True
            except Exception:
                pass

        # 2. 选择器定位：仅点击含评论相关文字的占位/遮罩元素
        for sel in (".comment-input", "[class*='comment-input']", ".input-wrapper",
                    ".inner-when-not-active", ".comment-trigger", ".comment-box",
                    "#comment-container"):
            try:
                for el in page.query_selector_all(sel):
                    txt = (el.inner_text() or "").strip()
                    if txt and any(k in txt for k in ("评论", "点击评论", "荒地", "说点什么")):
                        el.click(force=True, timeout=3000)
                        self._log("info", f"  [activate] 真实点击占位: {sel} (txt={txt[:20]})")
                        return True
            except Exception:
                pass

        # 3. 兜底：任意含「评论」文字、子节点少的元素真实点击
        try:
            clicked = page.evaluate("""() => {
                var all = document.querySelectorAll('*');
                for (var i = 0; i < all.length; i++) {
                    var el = all[i];
                    if (el.children.length > 5) continue;
                    var t = (el.textContent || '').trim();
                    if (t.indexOf('\\u8BC4\\u8BBA') >= 0 && t.length < 30) {
                        try { el.click(); return true; } catch(e) {}
                    }
                }
                return false;
            }""")
            if clicked:
                self._log("info", "  [activate] 兜底真实点击含「评论」元素")
                return True
        except Exception:
            pass
        return False

    def _activate_comment_input_js(self, page: Page) -> bool:
        """JS 兜底：暴力搜索并点击评论触发元素（占位/遮罩）"""
        result = page.evaluate("""() => {
            var candidates = [];
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++) {
                var el = all[i];
                if (el.children.length > 5) continue;
                var t = (el.textContent || '').trim();
                if ((t.indexOf('\\u8BC4\\u8BBA') >= 0 && t.length < 30)
                    || t.indexOf('\\u70B9\\u51FB\\u8BC4\\u8BBA') >= 0
                    || t.indexOf('\\u8352\\u5730') >= 0
                    || t.indexOf('\\u8BF4\\u70B9\\u4EC0\\u4E48') >= 0) {
                    var cls = (el.className || '').toLowerCase();
                    if (cls.indexOf('comment-item') < 0 && cls.indexOf('comment-list') < 0) {
                        candidates.push(el);
                    }
                }
            }
            for (var k = 0; k < candidates.length; k++) {
                try { candidates[k].click(); return 'clicked'; } catch(e) {}
            }
            return 'no_candidates';
        }""")
        if result == 'clicked':
            self._log("info", "  [activate-js] JS clicked comment trigger element")
            return True
        return False

    def _focus_comment_input(self, page: Page) -> bool:
        """激活态后聚焦真正的可编辑框（contenteditable/textarea/input）

        先等待可编辑元素出现（激活后才有），再真实点击使其聚焦，
        最后校验 document.activeElement 是否可编辑。
        """
        # 等待可编辑元素出现（激活后才会出现）
        try:
            page.wait_for_selector(
                '[contenteditable="true"], textarea, input[type="text"], input[type="search"]',
                timeout=6000,
            )
        except Exception:
            pass

        # 通过 JS 探查当前可编辑元素的类型特征
        info = page.evaluate("""() => {
            function pick() {
                var ce = document.querySelector('[contenteditable="true"]');
                if (ce) return {tag: ce.tagName, isCE: true, cls: (ce.className||'').toString().slice(0,60)};
                var ta = document.querySelector('textarea[class*="comment"], textarea.comment-input, textarea');
                if (ta) return {tag: 'TEXTAREA', isCE: false, cls: (ta.className||'').toString().slice(0,60)};
                var inp = document.querySelector('input[type="text"], input[type="search"]');
                if (inp) return {tag: inp.tagName, isCE: false, cls: (inp.className||'').toString().slice(0,60)};
                return null;
            }
            return pick();
        }""")
        if not info:
            return False

        # 真实点击聚焦（按类型定位，确保鼠标真正落到输入框上）
        try:
            if info.get("isCE"):
                page.locator('[contenteditable="true"]').first.click(timeout=4000, force=True)
            elif info.get("tag") == "TEXTAREA":
                page.locator("textarea").first.click(timeout=4000, force=True)
            else:
                page.locator('input[type="text"], input[type="search"]').first.click(timeout=4000, force=True)
        except Exception as e:
            self._log("warn", f"  [focus] 真实点击失败，回退 JS focus: {e}")
            try:
                page.evaluate("""() => {
                    var ce = document.querySelector('[contenteditable="true"]');
                    if (ce) { ce.focus(); return; }
                    var ta = document.querySelector('textarea'); if (ta) { ta.focus(); return; }
                    var inp = document.querySelector('input[type="text"], input[type="search"]');
                    if (inp) inp.focus();
                }""")
            except Exception:
                pass

        time.sleep(0.4)
        ok = page.evaluate(
            "() => { var a=document.activeElement; "
            "return !!(a&&(a.isContentEditable||a.tagName==='TEXTAREA'||a.tagName==='INPUT')); }"
        )
        if ok:
            self._log("info", f"  [focus] 已聚焦: {info}")
            return True
        return False

    def _click_send_button(self, page: Page, wait_appear: float = 0.0) -> bool:
        """查找并点击发送按钮。

        XHS 的「发送」按钮只有在评论框已输入文字后才会出现，因此 wait_appear>0 时
        先轮询等待其出现再点击，避免「输入了但按钮还没渲染」导致的漏发。
        """
        def find_and_click():
            selectors = [
                "button.submit-btn",
                ".submit-btn",
                "[class*='submit']:not([disabled])",
                "button[class*='send']:not([disabled])",
            ]
            for sel in selectors:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click(force=True, timeout=3000)
                        self._log("info", f"  [send] {sel}")
                        return True
                except Exception:
                    continue
            # JS 兜底：按文字匹配「发送 / 发布」
            found = page.evaluate("""() => {
                var btns = Array.from(document.querySelectorAll(
                    'button, [role="button"], span[class*="btn"]'
                ));
                for (var i = 0; i < btns.length; i++) {
                    var t = (btns[i].textContent || '').trim();
                    if (t === '\\u53D1\\u9001' || t === '\\u53D1\\u5E03') {
                        try { btns[i].click(); return 'clicked'; } catch(e) {}
                    }
                }
                return null;
            }""")
            if found == 'clicked':
                self._log("info", "  [send] JS clicked 发送/发布 button")
                return True
            return False

        if wait_appear > 0:
            deadline = time.time() + wait_appear
            while time.time() < deadline:
                if find_and_click():
                    return True
                time.sleep(0.4)
            return False
        return find_and_click()
    def _debug_dump(self, page: Page, note_id: str, tag: str):
        """保存截图、当前 URL 和完整页面信息用于调试（增强版）"""
        try:
            import os as _os
            log_dir = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))), "logs")
            _os.makedirs(log_dir, exist_ok=True)
            ts = int(time.time())
            prefix = f"debug_{tag}_{note_id}_{ts}"

            # 1. 截图
            shot_path = _os.path.join(log_dir, f"{prefix}.png")
            page.screenshot(path=shot_path, full_page=False)
            self._log("info", f"调试截图: {shot_path}")

            # 2. 完整调试报告（URL + body HTML + 所有可交互元素）
            report_path = _os.path.join(log_dir, f"{prefix}.html")
            try:
                debug_info = page.evaluate("""() => {
                    var lines = [];
                    lines.push('<h3>Debug Report</h3>');
                    lines.push('<p><b>URL:</b> ' + location.href + '</p>');
                    lines.push('<p><b>activeElement:</b> ' +
                        (document.activeElement ? document.activeElement.tagName + '.' + document.activeElement.className.slice(0,60) : 'none') +
                        '</p>');

                    // body 前 6000 字符
                    var bodyHTML = (document.body ? document.body.innerHTML : '').slice(0, 6000);
                    lines.push('<h4>body.innerHTML (first 6000 chars):</h4>');
                    lines.push('<pre style="max-height:400px;overflow:auto">' +
                        bodyHTML.replace(/</g, '&lt;') + '</pre>');

                    // 所有 contenteditable / textarea / input
                    var inputs = [];
                    var ceAll = document.querySelectorAll('[contenteditable="true"]');
                    for (var i = 0; i < ceAll.length; i++) {
                        var e = ceAll[i];
                        inputs.push('contenteditable: ' + e.tagName + '.' +
                            (e.className||'').slice(0,40) + ' visible=' + (e.offsetParent !== null));
                    }
                    var taAll = document.querySelectorAll('textarea');
                    for (var j = 0; j < taAll.length; j++) {
                        var t = taAll[j];
                        inputs.push('textarea: ' + t.tagName + '.' +
                            (t.className||'').slice(0,40) + ' id=' + (t.id||''));
                    }
                    lines.push('<h4>Editables (' + inputs.length + '):</h4>');
                    lines.push('<ul><li>' + inputs.join('</li><li>') + '</li></ul>');

                    // 含"评论"文字的元素（前20个）
                    var commentEls = [];
                    var allEl = document.querySelectorAll('*');
                    for (var k = 0; k < allEl.length && commentEls.length < 20; k++) {
                        var el2 = allEl[k];
                        if (el2.children.length > 10) continue;
                        var txt = (el2.textContent || '').trim();
                        if (txt.indexOf('\\u8BC4\\u8BBA') >= 0 && txt.length < 50) {
                            commentEls.push(el2.tagName + '.' +
                                (el2.className||'').slice(0,40) + ': ' + txt);
                        }
                    }
                    lines.push('<h4>Elements with \\u8BC4\\u8BBA text (' + commentEls.length + '):</h4>');
                    lines.push('<ul><li>' + commentEls.join('</li><li>') + '</li></ul>');

                    // 按钮（发送/发布/评论/取消）
                    var btnTexts = [];
                    var btns = document.querySelectorAll('button, [role="button"]');
                    for (var m = 0; m < btns.length; m++) {
                        var bt = btns[m];
                        var btxt = (bt.textContent || '').trim();
                        if (btxt && btxt.length < 15) {
                            btnTexts.push(btxt + ' (' + bt.tagName + '.' + (bt.className||'').slice(0,30) + ')');
                        }
                    }
                    lines.push('<h4>Buttons (' + btnTexts.length + '):</h4>');
                    lines.push('<ul><li>' + btnTexts.join('</li><li>') + '</li></ul>');

                    return '<!doctype html><html><head><meta charset=utf-8>' +
                        '<style>body{font-family:sans-serif;padding:16px}' +
                        'h4{color:#c0392b} pre{background:#f5f5f5;padding:8px;border-radius:4px}</style>' +
                        '</head><body>' + lines.join('\\n') + '</body></html>';
                }""")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(debug_info or "<p>Failed to generate report</p>")
                self._log("info", f"调试报告: {report_path}")
            except Exception as ex:
                self._log("warn", f"调试报告生成失败: {ex}")
        except Exception as e:
            self._log("warn", f"调试截图失败: {e}")

    def _parse_card(self, card) -> Optional[Dict[str, Any]]:
        try:
            href = card.get_attribute("href") or ""
            if not href:
                link = card.query_selector('a[href*="/explore/"]')
                href = link.get_attribute("href") if link else ""
            note_id = ""
            m = re.search(r"/explore/([a-f0-9]+)", href) or re.search(r"/discovery/item/([a-f0-9]+)", href)
            if m:
                note_id = m.group(1)
            if not note_id:
                return None

            # 构建完整 URL（保留 xsec_token 等查询参数，XHS 详情页访问必须带此 token）
            if href.startswith("http"):
                full_url = href
            elif href.startswith("/"):
                full_url = "https://www.xiaohongshu.com" + href
            else:
                full_url = f"https://www.xiaohongshu.com/explore/{note_id}"

            # 缓存 note_id → 完整 URL
            self._note_urls[note_id] = full_url

            title_el = card.query_selector(".footer .title, .title span, span.title")
            title = title_el.inner_text().strip() if title_el else ""
            author_el = card.query_selector(".author .name, .author-wrapper .name, .name")
            user = author_el.inner_text().strip() if author_el else ""
            like_el = card.query_selector(".like-wrapper .count, .like-count")
            likes = like_el.inner_text().strip() if like_el else ""
            return {
                "note_id": note_id,
                "title": title,
                "user": user,
                "content": "",
                "likes": likes,
                "url": full_url,
            }
        except Exception:
            return None

    def _human_scroll(self, page: Page):
        try:
            for _ in range(random.randint(2, 4)):
                delta = random.randint(400, 800)
                page.mouse.wheel(0, delta)
                time.sleep(random.uniform(0.15, 0.4))
        except Exception:
            pass

    def _safe_text(self, page: Page, selector: str) -> str:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else ""
        except Exception:
            return ""

    def _type_humanly(self, page: Page, text: str):
        for ch in text:
            page.keyboard.type(ch)
            time.sleep(random.uniform(0.02, 0.08))
