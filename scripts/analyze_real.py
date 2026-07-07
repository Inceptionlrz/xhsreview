"""
真实环境分析脚本：用 Playwright 访问小红书首页推荐流
1. 分析页面 DOM 结构
2. 提取真实帖子卡片
3. 输出结构化数据用于修复选择器
"""

import os
import sys
import time
import json
import tempfile
from playwright.sync_api import sync_playwright

EXPLORE_URL = "https://www.xiaohongshu.com/explore?channel_id=homefeed_recommend"
PROFILE_DIR = os.path.join(tempfile.gettempdir(), "xhsreview_profile_real")

os.makedirs(PROFILE_DIR, exist_ok=True)

def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=PROFILE_DIR,
            headless=False,  # 有头模式便于观察 + 通过验证
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
        # 反检测
        ctx.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            "window.navigator.chrome = { runtime: {}, };"
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("[1/6] 访问小红书首页...")
        page.goto(EXPLORE_URL, wait_until="domcontentloaded", timeout=45000)
        time.sleep(4)

        title = page.title()
        print(f"  页面标题: {title}")
        url_now = page.url
        print(f"  当前 URL: {url_now}")

        # 截图保存
        shot_path = os.path.join(os.path.dirname(__file__), "..", "logs", "xhs_explore_real.png")
        os.makedirs(os.path.dirname(shot_path), exist_ok=True)
        page.screenshot(path=shot_path, full_page=False)
        print(f"  截图已保存: {shot_path}")

        # 分析 DOM 结构
        print("\n[2/6] 分析页面结构...")
        # 尝试多种选择器
        selectors_to_try = [
            "section.note-item",
            "a.cover",
            ".note-item",
            "[data-note-id]",
            ".feeds-page .note-item",
            "div.note-item",
            "a[href*='/explore/']",
            "a[href*='/discovery/item/']",
            ".explore-feed",
            "#exploreFeeds",
        ]
        for sel in selectors_to_try:
            try:
                els = page.query_selector_all(sel)
                print(f"  {sel:40s} -> {len(els)} 个元素")
            except Exception as e:
                print(f"  {sel:40s} -> 错误: {e}")

        # 滚动加载更多
        print("\n[3/6] 滚动加载更多内容...")
        for i in range(3):
            page.mouse.wheel(0, 800)
            time.sleep(1.2)

        # 重新统计
        print("  滚动后重新统计:")
        for sel in ["section.note-item", "a.cover", "a[href*='/explore/']"]:
            els = page.query_selector_all(sel)
            print(f"    {sel:40s} -> {len(els)} 个")

        # 提取第一个卡片的结构
        print("\n[4/6] 提取卡片结构（取第一个匹配）...")
        card = page.query_selector("section.note-item") or page.query_selector("a.cover")
        if card:
            outer_html = card.evaluate("el => el.outerHTML.slice(0, 1500)")
            print("  卡片 outerHTML (前1500字符):")
            print("  " + outer_html[:1500].replace("\n", "\n  "))
        else:
            print("  未找到卡片元素，尝试用 a[href] 兜底")
            links = page.query_selector_all("a[href*='/explore/']")
            if links:
                first = links[0]
                outer_html = first.evaluate("el => el.outerHTML.slice(0, 1500)")
                print("  第一个 a[href*='/explore/'] outerHTML:")
                print("  " + outer_html[:1500].replace("\n", "\n  "))

        # 提取所有帖子
        print("\n[5/6] 批量提取帖子数据...")
        posts_data = page.evaluate("""() => {
            const posts = [];
            // 多种选择器兼容
            const cards = document.querySelectorAll('section.note-item, a.cover, div.note-item');
            cards.forEach((card, i) => {
                if (i >= 20) return;
                const post = {};
                post.html_preview = card.outerHTML.slice(0, 800);
                // 提取链接
                const link = card.querySelector('a[href*="/explore/"]') || card;
                post.href = link ? link.getAttribute('href') : '';
                // 提取 note_id
                const m = (post.href || '').match(/\\/explore\\/([a-f0-9]+)/);
                post.note_id = m ? m[1] : '';
                // 提取标题
                const titleEl = card.querySelector('.title, .footer .title span, span.title, .note-title');
                post.title = titleEl ? titleEl.innerText.trim() : '';
                // 提取作者
                const authorEl = card.querySelector('.author .name, .footer .author, .name');
                post.author = authorEl ? authorEl.innerText.trim() : '';
                // 提取点赞数
                const likeEl = card.querySelector('.like-wrapper .count, .like-count, .count');
                post.likes = likeEl ? likeEl.innerText.trim() : '';
                posts.push(post);
            });
            return posts;
        }""")
        print(f"  提取到 {len(posts_data)} 条帖子")
        for i, p_info in enumerate(posts_data[:8]):
            print(f"  [{i+1}] id={p_info.get('note_id','')[:12]}  title={p_info.get('title','')[:30]}  author={p_info.get('author','')[:15]}")

        # 保存完整数据
        data_path = os.path.join(os.path.dirname(__file__), "..", "logs", "xhs_feed_real.json")
        with open(data_path, "w", encoding="utf-8") as f:
            json.dump(posts_data, f, ensure_ascii=False, indent=2)
        print(f"\n  完整数据已保存: {data_path}")

        # 尝试打开第一个详情页
        print("\n[6/6] 尝试打开第一个帖子详情页...")
        if posts_data and posts_data[0].get("note_id"):
            note_id = posts_data[0]["note_id"]
            detail_url = f"https://www.xiaohongshu.com/explore/{note_id}"
            print(f"  打开: {detail_url}")
            page.goto(detail_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            # 分析详情页结构
            detail_selectors = [
                "#detail-title", ".note-content .title", "h1.title",
                "#detail-desc", ".note-content .desc", ".desc",
                ".user-info .username", ".author .name",
                ".interact-container .like-wrapper", ".like-lottie",
                "div#content-textarea", ".comment-input-box .content",
                "div[contenteditable='true']", "textarea.comment-input",
                ".comment-input", ".input-box",
            ]
            print("  详情页元素检测:")
            for sel in detail_selectors:
                try:
                    el = page.query_selector(sel)
                    status = "✓ 存在" if el else "✗"
                    text = ""
                    if el:
                        try:
                            text = el.inner_text().strip()[:60]
                        except:
                            pass
                    print(f"    {sel:45s} {status} {text}")
                except Exception as e:
                    print(f"    {sel:45s} 错误: {e}")
            # 详情页截图
            detail_shot = os.path.join(os.path.dirname(__file__), "..", "logs", "xhs_detail_real.png")
            page.screenshot(path=detail_shot, full_page=False)
            print(f"  详情页截图: {detail_shot}")

        # 检测登录态
        print("\n[登录态检测]")
        html = page.content()
        login_indicators = [
            ("/user/profile/", "用户主页链接"),
            ("登录", "登录按钮"),
            ("扫码登录", "扫码登录提示"),
            ("发布", "发布按钮"),
            ("qrcode", "二维码"),
        ]
        for keyword, desc in login_indicators:
            found = keyword in html
            print(f"  {desc:15s} {'✓' if found else '✗'}")

        print("\n[完成] 浏览器保持打开 10 秒供观察，然后关闭...")
        time.sleep(10)
        ctx.close()
        print("浏览器已关闭")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\n错误: {e}")
        sys.exit(1)
