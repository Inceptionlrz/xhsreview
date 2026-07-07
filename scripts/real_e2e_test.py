"""
真实环境测试：端到端跑通
1. 真实访问小红书首页
2. 提取真实帖子
3. 打开详情页
4. 调用 Anthropic API 生成回复（如有 Key）
5. 输出测试报告
"""

import os
import sys
import time
import json
import random
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.anthropic_client import AnthropicClient
from src.config import Config

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

EXPLORE_URL = "https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend"
PROFILE_DIR = os.path.join(tempfile.gettempdir(), "xhsreview_profile_real")
os.makedirs(PROFILE_DIR, exist_ok=True)

REPORT_PATH = os.path.join(os.path.dirname(__file__), "..", "logs", "real_test_report.md")


def log(msg):
    print(msg, flush=True)


def main():
    cfg = Config()
    has_key = bool(cfg.get("api_key"))
    ai = AnthropicClient(
        base_url=cfg.get("api_base_url", "https://api.anthropic.com"),
        api_key=cfg.get("api_key", ""),
        model=cfg.get("api_model", "claude-3-5-sonnet-20241022"),
    )

    report = ["# 小红书真实环境测试报告\n"]
    report.append(f"测试时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append(f"API 配置: {cfg.get('api_base_url', 'https://api.anthropic.com')} / {cfg.get('api_model')}\n")
    report.append(f"API Key: {'已配置' if has_key else '未配置（将跳过 AI 生成）'}\n\n")

    with sync_playwright() as p:
        log("[1/7] 启动浏览器（无头模式）...")
        # 自动探测已有 Chrome
        CHROME_EXE = os.environ.get("XHS_CHROME_EXE")
        if not CHROME_EXE:
            base = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ms-playwright")
            if os.path.isdir(base):
                best = None
                for name in os.listdir(base):
                    if name.startswith("chromium-") and "headless" not in name:
                        for sub in ("chrome-win64", "chrome-win"):
                            exe = os.path.join(base, name, sub, "chrome.exe")
                            if os.path.exists(exe) and (best is None or name > best[0]):
                                best = (name, exe)
                if best:
                    CHROME_EXE = best[1]
        if CHROME_EXE:
            log(f"  使用 Chrome: {CHROME_EXE}")
        launch_kwargs = dict(
            user_data_dir=PROFILE_DIR,
            headless=True,
            viewport={"width": 1280, "height": 900},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        if CHROME_EXE:
            launch_kwargs["executable_path"] = CHROME_EXE
        ctx = p.chromium.launch_persistent_context(**launch_kwargs)
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "window.navigator.chrome = { runtime: {}, };"
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        log("[2/7] 访问小红书首页...")
        try:
            page.goto(EXPLORE_URL, wait_until="domcontentloaded", timeout=45000)
        except PWTimeout:
            log("  ⚠ 页面加载超时，继续尝试...")
        time.sleep(5)

        title = page.title()
        url_now = page.url
        log(f"  标题: {title}")
        log(f"  URL: {url_now}")
        report.append(f"## 1. 页面访问\n- 标题: {title}\n- URL: {url_now}\n\n")

        # 截图
        shot = os.path.join(os.path.dirname(__file__), "..", "logs", "real_explore.png")
        page.screenshot(path=shot)
        log(f"  截图: {shot}")
        report.append(f"![首页截图](real_explore.png)\n\n")

        # 登录态检测
        log("[3/7] 检测登录态...")
        html = page.content()
        login_state = {
            "有用户主页链接": "/user/profile/" in html,
            "有发布按钮": "发布" in html and "发布笔记" in html,
            "有登录弹窗": "扫码登录" in html or "qrcode" in html.lower(),
            "有验证码": "captcha" in html.lower() or "验证" in html,
        }
        logged_in = login_state["有用户主页链接"] or login_state["有发布按钮"]
        for k, v in login_state.items():
            log(f"  {k}: {'✓' if v else '✗'}")
        report.append(f"## 2. 登录态\n- 已登录: {'是' if logged_in else '否'}\n")
        for k, v in login_state.items():
            report.append(f"- {k}: {'✓' if v else '✗'}\n")
        report.append("\n")

        # 滚动加载
        log("[4/7] 滚动加载 feed...")
        for i in range(4):
            try:
                page.mouse.wheel(0, random.randint(600, 900))
            except Exception:
                pass
            time.sleep(random.uniform(1.0, 1.6))
        time.sleep(2)

        # 选择器探测
        log("[5/7] 探测 DOM 选择器...")
        selector_results = page.evaluate("""() => {
            const out = {};
            const tests = [
                'section.note-item', 'a.cover', '.note-item', 'div.note-item',
                'a[href*="/explore/"]', 'a[href*="/discovery/item/"]',
                '.feeds-page', '#exploreFeeds', '.explore-feed',
                '.footer .title', '.author .name', '.like-wrapper .count',
            ];
            for (const s of tests) {
                try { out[s] = document.querySelectorAll(s).length; } catch(e) { out[s] = -1; }
            }
            return out;
        }""")
        report.append("## 3. DOM 选择器探测\n")
        report.append("| 选择器 | 数量 |\n|---|---|\n")
        for sel, cnt in selector_results.items():
            log(f"  {sel:40s} -> {cnt}")
            report.append(f"| `{sel}` | {cnt} |\n")
        report.append("\n")

        # 提取帖子
        log("[6/7] 提取帖子数据...")
        posts = page.evaluate("""() => {
            const posts = [];
            // 多策略
            let cards = document.querySelectorAll('section.note-item');
            if (cards.length === 0) cards = document.querySelectorAll('a.cover');
            if (cards.length === 0) {
                // 兜底：所有 explore 链接的父容器
                cards = Array.from(document.querySelectorAll('a[href*="/explore/"]')).map(a => a.closest('section, div.note-item, li') || a);
            }
            cards.forEach((card, i) => {
                if (i >= 15) return;
                const post = {};
                const link = card.matches('a[href*="/explore/"]') ? card : card.querySelector('a[href*="/explore/"]');
                post.href = link ? link.getAttribute('href') : '';
                const m = (post.href || '').match(/\\/explore\\/([a-f0-9]+)/) || (post.href||'').match(/\\/discovery\\/item\\/([a-f0-9]+)/);
                post.note_id = m ? m[1] : '';
                const titleEl = card.querySelector('.title, .footer .title span, span.title, .note-title');
                post.title = titleEl ? titleEl.innerText.trim() : '';
                const authorEl = card.querySelector('.author .name, .footer .author, .name, .author-wrapper .name');
                post.author = authorEl ? authorEl.innerText.trim() : '';
                const likeEl = card.querySelector('.like-wrapper .count, .like-count, .count');
                post.likes = likeEl ? likeEl.innerText.trim() : '';
                posts.push(post);
            });
            // 去重
            const seen = new Set();
            return posts.filter(p => {
                if (!p.note_id || seen.has(p.note_id)) return false;
                seen.add(p.note_id);
                return true;
            });
        }""")
        log(f"  提取到 {len(posts)} 条真实帖子")
        report.append(f"## 4. 提取帖子\n共 {len(posts)} 条\n\n")
        report.append("| # | note_id | 标题 | 作者 | 点赞 |\n|---|---|---|---|---|\n")
        for i, p_info in enumerate(posts[:10]):
            log(f"  [{i+1}] id={p_info['note_id'][:12]}  title={p_info['title'][:30]}  author={p_info['author'][:15]}  likes={p_info['likes']}")
            report.append(f"| {i+1} | {p_info['note_id'][:12]} | {p_info['title'][:30]} | {p_info['author'][:15]} | {p_info['likes']} |\n")
        report.append("\n")

        # 详情页测试
        detail_result = None
        ai_reply = None
        if posts:
            log(f"[7/7] 打开第一个详情页 + 测试 AI...")
            note_id = posts[0]["note_id"]
            detail_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            log(f"  打开: {detail_url}")
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                detail_shot = os.path.join(os.path.dirname(__file__), "..", "logs", "real_detail.png")
                page.screenshot(path=detail_shot)
                log(f"  详情截图: {detail_shot}")

                # 提取详情
                detail = {}
                for sel, key in [
                    ("#detail-title", "title"), (".note-content .title", "title2"),
                    ("h1.title", "title3"), ("#detail-desc", "desc"),
                    (".note-content .desc", "desc2"), (".desc", "desc3"),
                    (".user-info .username", "user"), (".author .name", "user2"),
                ]:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            detail[key] = el.inner_text().strip()
                    except Exception:
                        pass

                d_title = detail.get("title") or detail.get("title2") or detail.get("title3") or posts[0]["title"]
                d_desc = detail.get("desc") or detail.get("desc2") or detail.get("desc3") or ""
                d_user = detail.get("user") or detail.get("user2") or posts[0]["author"]
                log(f"  标题: {d_title[:40]}")
                log(f"  正文: {d_desc[:60]}")
                log(f"  作者: {d_user}")
                report.append(f"## 5. 详情页测试\n- URL: {detail_url}\n- 标题: {d_title}\n- 正文: {d_desc[:100]}\n- 作者: {d_user}\n\n")
                report.append(f"![详情截图](real_detail.png)\n\n")
                detail_result = {"title": d_title, "desc": d_desc, "user": d_user}

                # 测试 AI
                report.append("## 6. AI 回复生成测试\n")
                if has_key:
                    log("  调用 Anthropic API 生成回复...")
                    reply = ai.generate_reply(d_title, d_desc)
                    if reply:
                        log(f"  ✅ AI 回复: {reply}")
                        report.append(f"- **状态**: 成功\n- **回复内容**: {reply}\n\n")
                        ai_reply = reply
                    else:
                        log(f"  ❌ AI 失败: {ai.last_error}")
                        report.append(f"- **状态**: 失败\n- **错误**: {ai.last_error}\n\n")
                else:
                    log("  ⏭ 跳过 AI（未配置 Key）")
                    report.append("- **状态**: 跳过（未配置 API Key）\n\n")

                # 评论框检测
                log("  检测评论框...")
                comment_selectors = [
                    "div#content-textarea", ".comment-input-box .content",
                    "div[contenteditable='true']", "textarea.comment-input",
                    ".comment-input", ".input-box", ".comment-submit",
                ]
                report.append("## 7. 评论框检测\n| 选择器 | 存在 |\n|---|---|\n")
                for sel in comment_selectors:
                    el = page.query_selector(sel)
                    status = "✓" if el else "✗"
                    log(f"    {sel:40s} {status}")
                    report.append(f"| `{sel}` | {status} |\n")
                report.append("\n")

            except Exception as e:
                log(f"  详情页错误: {e}")
                report.append(f"## 5. 详情页测试\n错误: {e}\n\n")

        # 总结
        report.append("## 总结\n")
        report.append(f"- 页面可访问: ✓\n")
        report.append(f"- 登录态: {'已登录' if logged_in else '未登录（可浏览公开内容）'}\n")
        report.append(f"- 提取帖子数: {len(posts)}\n")
        report.append(f"- 详情页解析: {'成功' if detail_result else '失败'}\n")
        report.append(f"- AI 回复: {'成功' if ai_reply else ('跳过' if not has_key else '失败')}\n")

        # 保存报告
        with open(REPORT_PATH, "w", encoding="utf-8") as f:
            f.write("".join(report))
        log(f"\n报告已保存: {REPORT_PATH}")

        log("\n浏览器保持 8 秒...")
        time.sleep(8)
        ctx.close()
        log("完成")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        sys.exit(1)
