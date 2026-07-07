# xhsreview 项目交接文档（Handoff）

> 本文档供接手工（Claude Code 或其他）完整接手「小红书智能回复桌面工具」使用。
> 最后更新：2026-07-07，代码最新提交 `5b940b6`（已推送到 `github.com/Inceptionlrz/xhsreview` main 分支）。
> 上一任开发者：Senior Developer（高级开发工程师）。

---

## 0. TL;DR —— 必读三句话

1. **这是 Python + Tkinter 桌面工具**，用 Playwright 操控已登录的浏览器，自动给小红书帖子点赞/评论。所有浏览器操作都跑在 **Worker 线程**里（外部通过 `_cmd_queue` 提交指令），别在主线程调 Playwright，否则 greenlet 跨线程报错。
2. **最深的坑是「关键词搜索模式」进详情页 404**。根因：搜索卡片的 token 不在 `<a href>` 里，而是由 Vue 在真实点击（`isTrusted=true`）时注入。任何 `goto(URL)` 或合成事件都 404，**只能 Playwright 真实 `.click()`**。
3. **搜索卡片 DOM 不统一**（致命细节）：有的 `<a>` 可见、有的 `<a>` 是 `display:none` 的 SEO 占位链接（真 `@click` 在父容器）。点错就会触发 `<a>` 默认硬导航 → 404。最新修复 `_resolve_search_click_target` 已处理，但**截至交接时尚未在运行时验证**。

---

## 1. 项目概览

- **功能**：根据「推荐 feed / 关键词搜索 / 板块」三种模式抓取小红书帖子，自动点赞、按 AI 生成文案评论；带统计（点赞数/评论数）、GUI 控制面板。
- **形态**：Windows 桌面应用（Tkinter GUI），非 Web 服务。
- **仓库**：`github.com/Inceptionlrz/xhsreview`（public, main）。提交需推到 main。
- **关键文件地图**：

| 路径 | 作用 |
|------|------|
| `main.py` | 入口，启动 GUI + Worker |
| `src/app.py` | Tkinter GUI（用户信息区、统计、控制按钮；新增左上角 git 版本红框 `_get_version`/`_build_version_badge`） |
| `src/xhs_crawler.py` | **核心爬虫**——所有导航/点击/点赞/评论逻辑都在这里（约 53 个方法，最常改） |
| `src/scheduler.py` | 调度优先级 `keyword > category > default feed`；liked/replied 计数；起止打印统计摘要 |
| `src/config.py` | 配置加载，缺 `config/config.json` 时回退 `DEFAULT_CONFIG` |
| `scripts/` | 2 个辅助脚本 |
| `config/config.json` | **真实 API Key，已被 .gitignore 排除，绝不可提交** |
| `config/config.example.json` | 占位配置模板 |
| `logs/` | 运行日志 + 调试产物（见 §6） |

---

## 2. 环境 / 凭据（接手前必看）

- **Python**：系统 3.12（`C:\Users\samal\AppData\Local\Programs\Python\Python312\python.exe`，已装 Playwright）；workbuddy 管理版 3.13 也可用。
- **浏览器**：Playwright 级联启动 `bundled chromium-1228` → 系统 Chrome CDP → Mock。
  - chromium-1228 路径：`C:\Users\samal\AppData\Local\ms-playwright\chromium-1228\chrome-win64\chrome.exe`
  - ⚠️ 日志偶尔报 `chromium-1208 不存在` —— **无害**，级联已回退到 1228 正常启动，忽略即可。
- **登录态 Profile**：`C:\Users\samal\AppData\Local\Temp\xhsreview_profile`
  - 小红书需**扫码登录**，登录态持久化在此 profile。**清 profile = 丢失登录，需重新扫码**。
- **GitHub 推送**：本机全局 `~/.gitconfig` 含 `insteadOf` 注入 PAT（`ghp_***@github.com`），`git push` **免显式 Token**。
  - 注意：`git credential fill` 取不到（在 insteadOf 配置里，不在凭据管理器）；要提取用 `git config --list | grep ghp_`。
  - 无 `gh` CLI、GitHub connector 断开。建库用 `curl -H "Authorization: Bearer $TOKEN" POST https://api.github.com/user/repos`，body 用最小 `{"name":"xhsreview"}`（`description` 字段曾触发 HTTP 400）。
- **API Key 安全**：真实 Key 在 `config/config.json`（gitignored）。推送前务必 `git ls-files --error-unmatch config/config.json` 确认未被跟踪。曾短暂在工具输出暴露过 PAT，如担心可撤销重置。

---

## 3. 核心难题全记录：搜索模式详情页 404

### 3.1 现象
- 推荐 feed 模式：正常，能点赞能评论。
- 关键词搜索模式：进详情页全部 `未登录` / 404，评论发不出去。

### 3.2 反爬机制（真相）
- **推荐 feed**：卡片 `<a href>` 自带有效 `xsec_token` → 直接 `page.goto()` 可靠。
- **关键词搜索**：卡片 `<a href>` **不含有效 token**。token 由 Vue Router 在 `@click` 时从数据注入，执行 `router.push`。
- **404 特征**：URL 形如 `https://www.xiaohongshu.com/404?source=/404/sec_xxx?redirectPath=...`，`error_code=300031`，文案「当前笔记暂时无法浏览」。
- **失败签名判定**：`redirectPath` 里 token 是 8 字符 `sec_xxx` → 说明触发了 `<a>` **默认硬导航**（假 token）。成功时 token 是 40+ 字符（Vue `router.push` 注入）。

### 3.3 攻关时间线（每轮都是真金白银踩出来的）

| 提交 | 方案 | 结果 |
|------|------|------|
| `10a2c46e` | 初版搜索 404 拦截（URL 方案） | ❌ 基础失败 |
| `d5e1c6c` | 修 `_do_fetch_feed` 等类方法被错误嵌套（模块级 0 缩进导致一批方法变死代码） | ✅ 编译恢复 |
| `174b8ba` | 从 `__INITIAL_STATE__` 提取真实 token 拼 URL | ❌ 搜索页根本无有效 token |
| `c08503d` | JS 合成 `PointerEvent`/`MouseEvent` 派发 | ❌ `isTrusted=false`，Vue 不认 → 仍 404（还顺带修了 `name 'url' is not defined` NameError） |
| `fdbd9a3` | **Playwright 真实 `.click()`** 触发 Vue `@click` | ✅ 可见卡片通了（用户截图确认评论成功） |
| `3ba3975` | 清 `.note-detail-mask` 遮罩 `pointer-events` 穿透 | ✅ 视频笔记遮罩卡点击问题解决 |
| `212a6a7` | 虚拟列表未渲染先滚动定位 `_ensure_card_in_dom` | ✅ 部分修复（靠后卡片） |
| `6faa35b` | 点击失败导出卡片 DOM 诊断 | 🔧 诊断埋点 |
| `bee6ab6` | 点击前导出快照 + 回搜索页先等卡片渲染 | 🔧 定位到隐藏 `<a>` |
| `5b940b6` | **隐藏 `<a>`(display:none) 占位链接修复 + 版本红框** | ✅ 理论修复，**未运行时验证** |

### 3.4 最终修复要点（`5b940b6`，当前 HEAD）
- 新增 `_resolve_search_click_target(page, note_id)`：
  - `<a href*='note_id'>` **可见** → 点 `<a>`；
  - `<a>` **隐藏**（display:none）→ 上溯到可见卡片容器（承载 `@click` 的父级）再点；
  - **点击前把所有 `a[href*=note_id]` 的 `pointer-events` 设 `none`**，即使 XHS 滚动后把隐藏 `<a>` 渲染成可见，点击也穿透到承载 `@click` 的封面/容器，**绝不触发 `<a>` 默认硬导航**。这是死循环 404 的终结键。
- 诊断 dump 升级：快照里直接打印 `<a>` 的 `DISPLAY`/`VISIBILITY`，一眼看出是否占位链接。
- GUI 左上角新增红色版本框，实时读 `git rev-parse --short HEAD`，排查时版本号与我 `git log` 对齐。

### 3.5 其他导航约定
- `_navigate_to_note`：搜索分支=真实点击首选；处理多篇时若已离搜索页，先回搜索结果页再点下一张。
- `_wait_for_detail`：轮询 URL 是否变 `/explore/{note_id}` 且非 404。
- `_do_like`/`_do_post_comment`：守卫「已在目标详情页则跳过重复导航」。
- **评论发布**：必须**先真实点击输入框**激活 Vue 态，再输入，发送按钮才出现（这是早期 `10a2c46e` 修过的基础设施）。
- `_is_404` / `_is_search_page`：类方法，检测 `/404`、`source=...redirectPath=`、正文「当前笔记暂时无法浏览」、`search_result`/`search/` in url。

---

## 4. 关键经验教训（给接手工的避坑清单）

1. **`isTrusted` 是硬门槛**：小红书反爬查的是事件是否来自真实用户交互。合成 JS 事件再怎么模拟参数都 404，必须让浏览器自己派发可信事件（Playwright `.click()`）。
2. **`force=True` 不会自动穿透遮挡**：它只是跳过可见性检查，仍走浏览器坐标命中测试；中心点被遮罩盖住，事件还是落在遮罩上。必须先把遮挡元素 `pointer-events:none`。
3. **XHS 遮罩层会随 Vue 重渲染动态重建**：清一次 `pointer-events` 不够，**每次点击前都要重清**。
4. **虚拟滚动列表**：`query_selector` 找不到元素，先怀疑「未滚动渲染」，不是「选择器错」。
5. **诊断时序**：回搜索页 / dump 前，先轮询 `data-note-id` 数量稳定（`_wait_search_cards_rendered`），否则会拿到「卡片数=0」假阴性，误导判断。
6. **隐藏 `<a>` 占位链接**：搜索卡片 DOM 不统一，SEO 占位 `<a>` 是 `display:none` 且无布局盒子，真 `@click` 在父容器。点它就触发默认硬导航。
7. **token 长度即签名**：8 字符 `sec_xxx` = 失败（硬导航）；40+ 字符 = 成功（Vue 路由）。
8. **Worker 线程隔离**：所有 Playwright 调用只在 Worker 内，外部走 `_cmd_queue`，别跨线程。

---

## 5. 当前验证状态（截至交接）

| 模块 | 状态 | 说明 |
|------|------|------|
| 推荐 feed 模式 | ✅ 已验证 | 点赞+评论正常 |
| 搜索模式·可见 `<a>` 卡片 | ✅ 已验证 | `fdbd9a3` 后用户截图确认评论成功 |
| 搜索模式·视频遮罩卡片 | ✅ 已验证 | `3ba3975` 截图确认详情加载 |
| 搜索模式·靠后虚拟列表卡片 | 🟡 理论修复 | `212a6a7` 已推，但运行进程一直是旧版，未见端到端确认 |
| 搜索模式·隐藏 `<a>` 占位卡片 | 🟡 **未运行时验证** | `5b940b6` 已推，但交接时运行进程仍是旧代码（PID 29864） |
| GUI 版本红框 | 🟡 待确认 | 我加了 git-hash 版本框；用户曾提及自己也加了版本显示，**可能重复**，需查 |

**结论**：搜索模式大方向已通，最后一个已知变种（隐藏 `<a>` 占位链接）已在代码层修复，但**需要重启脚本用 `5b940b6` 跑一轮真实验证**。

---

## 6. 调试产物说明（看 logs/ 别慌）

- `debug_search_404_debug_{note_id}_{ts}.html` / `.png`：命中 404 时的页面快照。看 `redirectPath` 里 token 长度判死因。
- `debug_search_card_{note_id}_{ts}.html`：点击失败后回搜索页导出的卡片 DOM（或 `CARD_NOT_FOUND_ON_PAGE` / 卡片列表）。
- `debug_search_click_target_{note_id}_{ts}.html`：点击**前**的卡片快照（含 `<a>` 的 `DISPLAY`/`VISIBILITY`）——最有用，直接区分「占位链接点错」vs「真被限流」。
- 这些文件会累积，必要时可清理 `logs/debug_*`。

---

## 7. 给接手工（Claude Code）的下一步清单

1. **重启脚本**跑 `5b940b6`，重点验证之前打不开的帖子（视频类 / 带占位 `<a>` 的）能否正常进详情+评论。
2. 若仍有个别帖子进不去：取最新的 `debug_search_click_target_*.html`，看 `<a>` 的 `DISPLAY` 行——`none` 说明占位链接没点对（继续修 `_resolve_search_click_target`）；若 `<a>` 可见且 token 40+ 仍 404，则可能是**服务端真限流**（`error_code=300031`），应改为「优雅跳过」而非反复重试。
3. **查 GUI 版本框是否重复**：打开 `src/app.py` 看 `_build_version_badge` 与用户可能自加的控件是否叠加，重复就删一个。
4. 可选优化：限流帖子优雅跳过；减少 debug 文件堆积；多篇连续处理时回搜索页的等待策略可再稳一点。
5. 长期：推荐 feed 与搜索模式两套导航已收敛到「真实点击」统一策略，后续除非 XHS 改版，否则不必再折腾 URL 构造。

---

## 8. 附：Worker / 调度关键接口（改代码前先读）

- `src/xhs_crawler.py` 方法签名（最新）：`_do_open_note` / `_do_like` / `_do_post_comment` / `_do_fetch_feed` 均通过 `_navigate_to_note(page, note_id)` 导航；`_navigate_to_note` 非搜索模式直接 goto 缓存带 token URL，搜索模式走 `_click_note_card_on_search` 真实点击。
- `__init__` 关键属性：`_last_fetch_was_search`、`_search_tokens`、`_last_search_keyword`、`_note_urls`（搜索关键词分支：`self.SEARCH_URL_TPL.format(kw=keyword)` → 置 `_last_fetch_was_search=True` + 记 `_last_search_keyword`）。
- 编译校验：`python -m py_compile src/xhs_crawler.py src/app.py`；方法完整性用 `ast` 解析 `XhsCrawler` 类核对。

---

## 9. 协作优化空间（开发者与用户合作的复盘）

> 这 10 个提交里，有几次往返本可避免。以下复盘供接手工（Claude Code）与用户建立更高效的协作节奏。

### 9.1 开发者侧可优化
1. **第一轮就该要 DOM 快照，而非瞎猜 token**。最早 404 时连续试了「提取 token 拼 URL」(`174b8ba`) 和「合成事件」(`c08503d`) 两轮才转向真实点击。只要一开始导出一份卡片 `outerHTML`，`display:none` 占位 `<a>` 和「token 不在 href」当场可看穿，省 2-3 个提交。
2. **过早宣布胜利**。`fdbd9a3` 后仅凭一张成功截图就报「搜索模式完全跑通」，结果用户回来「有的能评论有的不行」。修完应先拿**失败用例**（视频卡/占位 `<a>` 卡）验证，而非只用 happy-path 卡片。
3. **没早点借力用户的手动观察**。用户后来一句「URL 直跳被拦截、点卡片能进」才是转折点。这种「人工点击 vs 工具导航」的差异，本该在第一轮就主动问。
4. **诊断工具是增量拼出来的**。无 dump → dump 卡片 → dump 点击前快照，每加一次都要用户重跑一轮。首个 404 就该把「点击前卡片快照 + 回搜索页等渲染」一次性埋好。
5. **缺少快速验证通道**。每次修复都要用户重启整个长时工具看日志，反馈慢。本可提供一个轻量 re-run 脚本或基于已保存页面快照的回放测试，让我自行验证逻辑，不必每次麻烦用户跑全流程。

### 9.2 用户侧可优化
1. **首报 bug 用结构化模板**。早期「显示无登陆」较笼统；后期好转（发 debug HTML/截图/日志片段）。若一开始就说「版本号 X、关键词 Y、哪些帖 fail、附 debug 文件」，能直接定位。
2. **早期就点明行为差异**。你后来才说「点卡片能进、URL 跳被拦」——这个观察是破局关键，越早说省 2-3 轮。
3. **报「还不行」前确认跑的是最新代码**。部分反馈是在旧进程上跑的（改源码不影响已在内存运行的进程）。

### 9.3 建议沿用的工作约定
- 任何 404/导航类问题，**第一轮就自动导出**「点击前卡片 outerHTML + 回搜索页等渲染后再 dump」，附在报告里。
- 修完先自测失败用例再宣告完成。
- 给用户一份《报 bug 模板》：版本 hash、模式、关键词、失败帖 note_id、debug 文件。
- 长时工具旁提供轻量验证脚本，缩短反馈环。
