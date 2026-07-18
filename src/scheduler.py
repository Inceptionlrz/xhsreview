"""
调度器：协调抓取、AI 生成、回复、统计
"""

import time
import random
import threading
from typing import Optional, Callable, Dict, Any, List

from .anthropic_client import AnthropicClient
from .xhs_crawler import XhsCrawler
from .quota_tracker import QuotaTracker


class Scheduler:
    """
    调度器：单线程顺序执行，避免账号风险

    设计：
    - 主循环在自己线程中跑（与 UI 线程分离）
    - 所有 XhsCrawler 调用现在已线程安全（内部用 worker 隔离 Playwright）
    - 板块 / 关键词 / 搜索筛选从 config 读取后传给 fetch_feed
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
        self._session_actions: int = 0  # 本次会话累计操作数（用于会话安全上限）
        self._quota = QuotaTracker()
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
    def _resolve_config(self) -> Dict[str, Any]:
        """合并「养号模式」覆盖，返回 config dict。

        养号模式关闭时直接返回原 config（零副作用）；开启时返回新 dict，
        仅作用于本次运行的 Scheduler 实例，不回写外部传入的 config。
        用于账号被平台判定为 AI 运营后的「冷启动」：极低频、只看不评、随机长休息。
        """
        if not self.config.get("nurture_mode", False):
            return self.config
        cfg = dict(self.config)
        nz = cfg.get("nurture", {}) or {}
        # 顶层标量覆盖
        for k in ("auto_reply", "auto_like", "like_rate", "wait_min", "wait_max",
                  "daily_like_limit", "daily_reply_limit"):
            if k in nz:
                cfg[k] = nz[k]
        # humanize 嵌套覆盖（skip / 长休息 / 会话上限）
        hz = dict(cfg.get("humanize", {}) or {})
        for k in ("skip_rate", "long_break_prob", "long_break_min",
                  "long_break_max", "session_action_cap"):
            if k in nz:
                hz[k] = nz[k]
        cfg["humanize"] = hz
        # 双保险：养号期间绝不评论
        cfg["auto_reply"] = False
        cfg["daily_reply_limit"] = 0
        return cfg

    def _run(self):
        try:
            # 养号模式：用覆盖后的配置运行（仅影响本实例）
            self.config = self._resolve_config()
            if self.config.get("nurture_mode", False):
                self._log("warn", "🌱 养号模式已启用：极低频 · 只看不评 · 随机长休息")
                self._log("info", "🌱 养号 = 每日≤3次点赞 + 纯浏览跳过(85%) + 帖子间等待8~20秒 "
                                  "+ 频繁长休息；绝不评论。处罚期结束前请勿关闭本模式")
            # 启动前先做配额 / 时段检查
            can_run, reason = self._quota.check(self.config)
            if not can_run:
                self._log("warn", f"⛔ {reason}")
                return
            self._quota.record_run_start()

            mode = self.config.get("mode", "unlimited")
            post_limit = int(self.config.get("post_limit", 50))
            time_limit = int(self.config.get("time_limit", 30)) * 60
            crawl_mode = self.config.get("crawl_mode", "deep")
            scroll_times = 3 if crawl_mode == "deep" else 1

            # 板块 + 关键词 + 筛选
            enabled_cats = self.config.get("enabled_categories") or []
            keyword = (self.config.get("search_keyword") or "").strip()
            search_filters = self.config.get("search_filters") or {}

            # 板块选择：取第一个启用的板块作为抓取目标
            category = enabled_cats[0] if enabled_cats else ""

            self._log("ok", f"开始运行 | 模式={mode} | 板块={category or '全部'}"
                           f" | 关键词={keyword or '(无)'} | 筛选={search_filters}")
            self._log("info", "📊 统计追踪已启动：将记录点赞次数 / 评论次数")
            self._publish_state()

            batch_count = 0
            empty_rounds = 0
            while not self._stop_event.is_set():
                # 运营画像检查：每日上限 / 活跃时段 / 最小重启间隔
                can_run, reason = self._quota.check(self.config)
                if not can_run:
                    self._log("warn", f"⛔ {reason}")
                    break

                if mode == "count" and self._state["posts_seen"] >= post_limit:
                    self._log("ok", f"达到帖子数上限 {post_limit}，自动停止")
                    break
                if mode == "time":
                    elapsed = time.time() - self._state["started_at"]
                    if elapsed >= time_limit:
                        self._log("ok", f"达到时间上限 {time_limit // 60} 分钟，自动停止")
                        break

                # 抓一批（关键词搜索时带上筛选条件）
                feed = self.crawler.fetch_feed(
                    scroll_times=scroll_times,
                    category=category,
                    keyword=keyword,
                    filters=search_filters if keyword else None,
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
                    # 逐帖前检查配额，防止批次内超限
                    can_run, reason = self._quota.check(self.config)
                    if not can_run:
                        self._log("warn", f"⛔ {reason}")
                        self._stop_event.set()
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

                    # ===== 拟人化 / 防封节奏 =====
                    hz = self.config.get("humanize", {}) or {}
                    if not isinstance(hz, dict):
                        hz = {}
                    hz_enabled = bool(hz.get("enabled", True))

                    # 随机「纯浏览跳过」：并非每篇都操作，更像真人刷帖
                    skip_rate = int(hz.get("skip_rate", 20)) if hz_enabled else 0
                    if skip_rate > 0 and random.randint(1, 100) <= skip_rate:
                        self._log("info", f"🙈 随机浏览跳过: {detail.get('title','')[:30]}（本次不操作）")
                        self._maybe_wait()
                        continue

                    # 先按概率决定本帖要做的动作
                    do_like = (self.config.get("auto_like")
                               and self.crawler.is_logged_in
                               and random.randint(1, 100) <= int(self.config.get("like_rate", 0)))
                    do_reply = (self.config.get("auto_reply")
                                and self.crawler.is_logged_in
                                and random.randint(1, 100) <= int(self.config.get("reply_rate", 0)))
                    actions = []
                    if do_like:
                        actions.append("like")
                    if do_reply:
                        actions.append("reply")
                    if not actions:
                        self._maybe_wait()
                        continue

                    # 操作顺序随机（真人不会每次都「先赞后评」）
                    if hz_enabled and hz.get("randomize_order", True):
                        random.shuffle(actions)

                    for act in actions:
                        if self._stop_event.is_set():
                            break
                        if act == "like":
                            if self.crawler.like_note(note_id):
                                self._state["liked"] += 1
                                self._log("ok", f"👍 点赞({self._state['liked']}次): {detail.get('title','')[:30]}")
                                self._publish_state()
                                self._session_actions += 1
                                self._quota.add_like()
                            time.sleep(random.uniform(0.3, 0.8))
                        elif act == "reply":
                            title = detail.get("title", "")
                            content = detail.get("content", "")
                            if not (title or content):
                                continue
                            # 偶发「看了但不评论」（更自然，且省一次 AI 调用）
                            no_comment_rate = int(hz.get("no_comment_rate", 25)) if hz_enabled else 0
                            if no_comment_rate > 0 and random.randint(1, 100) <= no_comment_rate:
                                self._log("info", f"🙊 看了但没评论: {title[:30]}")
                                continue

                            # 人设轮换：从 pool 随机选，打破「单一完美声音」指纹
                            persona = self.config.get("api_persona", "友好、有趣的小红书用户")
                            pool = self.config.get("persona_pool") or []
                            if hz_enabled and hz.get("persona_rotate", True) and isinstance(pool, list) and pool:
                                persona = random.choice(pool)

                            # 通用反应闸门：一定概率直接发真人口语反应（跳过 AI，最抗 AI 检测）
                            # 帖子正文过短也强制走通用反应（没料可评，硬评反而露馅）
                            generic_rate = int(hz.get("generic_reply_rate", 45)) if hz_enabled else 0
                            min_len = int(hz.get("content_min_post_len", 25)) if hz_enabled else 0
                            use_generic = (generic_rate > 0 and random.randint(1, 100) <= generic_rate) \
                                or (min_len > 0 and len(content or "") < min_len)

                            if use_generic:
                                reply = random.choice(AnthropicClient.GENERIC_REACTIONS)
                                if random.random() < 0.30:  # 偶发补一个 emoji，更自然
                                    reply = reply.rstrip("。.!！?？~ ") + random.choice(
                                        ["😂", "✨", "👍", "🔥", "🥺", "💯"])
                                self._log("info", f"💬 通用反应: {reply[:30]}")
                            else:
                                self._log("info", f"🧠 正在生成回复: {title[:30]}")
                                style_hint = random.choice(
                                    ["react", "question", "vague", "empathize", "onpoint"]) \
                                    if (hz_enabled and hz.get("content_vary_voice", True)) else ""
                                reply = self.ai.generate_reply(
                                    post_title=title,
                                    post_content=content,
                                    persona=persona,
                                    max_tokens=int(self.config.get("api_max_tokens", 256)),
                                    temperature=float(self.config.get("api_temperature", 0.85)),
                                    style_hint=style_hint,
                                )
                                if not reply:
                                    self._log("err", f"AI 生成失败: {self.ai.last_error or '未知'}")
                                    self._state["errors"] += 1
                                    continue
                                # 内容层拟人后处理（防 AI 味 / 人工审核）
                                reply = self.ai.humanize_reply(reply, hz if hz_enabled else {})

                            ok, msg = self.crawler.post_comment(
                                note_id, reply, context_text=f"{title}\n{content}")
                            if ok:
                                self._state["replied"] += 1
                                self._log("ok", f"💬 已回复({self._state['replied']}次): {reply[:60]}")
                                self._session_actions += 1
                                self._quota.add_reply()
                            else:
                                self._log("err", f"回复失败: {msg}")
                                self._state["errors"] += 1
                            self._publish_state()

                    # 会话安全上限（累计操作达上限强制长休）& 偶发长休息
                    self._maybe_session_break(hz, hz_enabled)
                    self._maybe_long_break(hz, hz_enabled)
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
            try:
                self._quota.record_run_end()
            except Exception:
                pass
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

    def _sleep_with_stop(self, seconds: float):
        """可被停止事件中断的睡眠（用于长休息，避免停止时卡死）"""
        end = time.time() + seconds
        while time.time() < end and not self._stop_event.is_set():
            time.sleep(0.5)

    def _maybe_long_break(self, hz: Dict[str, Any], enabled: bool):
        """每帖处理后偶发「长休息」，打乱固定节奏。"""
        if not enabled:
            return
        p = float(hz.get("long_break_prob", 0.07))
        if p <= 0 or random.random() >= p:
            return
        dur = random.uniform(float(hz.get("long_break_min", 30)),
                             float(hz.get("long_break_max", 120)))
        self._log("warn", f"☕ 偶发长休息 {dur:.0f} 秒（拟人化节奏，避免规律化）")
        self._sleep_with_stop(dur)

    def _maybe_session_break(self, hz: Dict[str, Any], enabled: bool):
        """累计操作达上限后强制长休并重置计数，规避频次异常风控。"""
        if not enabled:
            return
        cap = int(hz.get("session_action_cap", 35))
        if cap <= 0 or self._session_actions < cap:
            return
        dur = random.uniform(float(hz.get("session_break_min", 120)),
                             float(hz.get("session_break_max", 300)))
        self._log("warn", f"🌙 已达会话操作上限 {cap} 次，长休 {dur:.0f} 秒（防频次异常）")
        self._session_actions = 0
        self._sleep_with_stop(dur)

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
