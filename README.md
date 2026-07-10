# XHS Review · 小红书智能回复助手

> 仿 Linux.do 刷帖助手 v8.5.0 风格的桌面工具：自动浏览小红书推荐流 / 关键词搜索流，**基于 Anthropic Messages API 动态生成拟人化回复**，支持一键打包为独立 EXE，可在未装 Python 的机器上直接运行。

## ✨ 功能

- 🧠 **AI 智能回复**：调用 Anthropic Messages API，针对每个帖子的标题/正文生成自然口语化的回复
- ⚙️ **API 完全可配**：URL、Key、Model、人设、温度、max_tokens 全部可自定义，支持中转站
- 🌐 **真实抓取**：基于 Playwright 浏览器自动化，模拟真人滚动 / 键入，反检测
- 🔁 **虚拟数据模式**：未安装 Playwright 或无登录态时使用，零依赖可演示
- 🛡 **拟人化 / 防封系统（核心）**：35+ 项可调旋钮，让自动化行为逼近真人，显著降低被平台风控识别的概率（详见下文）
- 📊 **三大运行模式**：无限制 / 帖子数 / 时间限制
- 🐢 **双爬楼模式**：深度爬楼（完整阅读）/ 快速浏览（3~5 层换帖）
- 👍 **行为概率控制**：自动点赞率、自动回复率、随机等待区间
- 🧩 **板块筛选**：内置 15 个板块（开发调优、国产替代、资源荟萃…）
- 📈 **实时统计**：帖子 / 爬楼 / 点赞 / 回复 / 错误 / 升级进度
- 💻 **独立 EXE 打包**：自带浏览器，分发给他人即可用

## 📦 安装（开发模式）

```bash
pip install requests playwright
playwright install chromium
python main.py
```

> 若仅想体验 UI 与虚拟数据模式，不装 Playwright 也能跑（自动降级为虚拟数据）。

## 🚀 启动

```bash
python main.py
```

## ⚙️ 首次使用

1. 点击「⚙ Anthropic 配置」填入：
   - **API URL**：默认 `https://api.anthropic.com`（支持中转站）
   - **API Key**：你的 Key
   - **Model**：`claude-3-5-sonnet-20241022` 或其他支持 Messages API 的模型
   - **人设**：AI 回复风格描述
2. 切换「虚拟数据 / 真实抓取」：
   - 默认 **🔁 虚拟数据：开**（无需登录，开箱即用）
   - 真实抓取需先扫码登录一次（profile 目录保留登录态，勿清空）
3. 调整运行模式、概率、板块
4. 点击「▶ 开始」

## 🛡 拟人化 / 防封系统（v 最新版核心）

工具内置一套**行为拟人化引擎**，目的是让自动化操作难以被平台风控识别。点击主界面「🛡 拟人化设置」可打开调参弹窗，所有旋钮均可单独开关；默认值偏「安全且自然」。

### 旋钮分组一览

| 分组 | 旋钮 | 作用 | 默认 |
|------|------|------|------|
| **打字拟人** | `enabled` | 总开关（关闭则退化为简单随机） | `true` |
| | `type_min/max_delay` | 每个字符基础延迟上下限（秒） | `0.06 / 0.20` |
| | `type_pause_prob` | 输入中偶发「卡顿停顿」概率 | `0.10` |
| | `type_pause_min/max` | 卡顿停顿时长上下限（秒） | `0.30 / 1.00` |
| | `type_typo_rate` | 偶发「打错一字再删」结巴概率 | `0.05` |
| **阅读停留** | `read_enabled` | 评论前先「读完帖子」 | `true` |
| | `read_per_char` | 每字符阅读耗时（秒） | `0.010` |
| | `read_min/max` | 最短 / 最长停留（秒） | `1.5 / 5.0` |
| **滚动拟人** | `scroll_human` | 启用拟人滚动 | `true` |
| | `scroll_pause_prob` | 滚动中偶发停顿「看一眼」概率 | `0.30` |
| | `scroll_back_prob` | 偶发向上回滚（模拟回看）概率 | `0.25` |
| **鼠标拟人** | `mouse_human_move` | 点击前曲线移动鼠标（避免瞬移） | `true` |
| | `mouse_overshoot_prob` | 落点「过冲再修正」概率 | `0.40` |
| | `hesitate_prob` | 偶发「犹豫了没点赞」概率 | `0.04` |
| **内容拟人** | `no_comment_rate` | 「看了但不评论」概率(%) | `12` |
| | `content_typo_rate` | 偶发轻微错别字概率 | `0.15` |
| | `content_emoji_rate` | 偶发追加 1 个 emoji 概率 | `0.50` |
| | `content_truncate_rate` | 偶发只留前半句概率 | `0.12` |
| | `glance_comments` | 评论前先下滑看一眼已有评论 | `true` |
| **行为节奏** | `skip_rate` | 纯浏览跳过率(%) | `20` |
| | `long_break_prob` | 偶发长休息概率 | `0.07` |
| | `long_break_min/max` | 长休息时长上下限（秒） | `30 / 120` |
| **会话安全** | `session_action_cap` | 累计操作达上限强制长休（0=不限） | `35` |
| | `session_break_min/max` | 会话长休时长上下限（秒） | `120 / 300` |
| **其他** | `randomize_order` | 点赞 / 评论顺序随机 | `true` |

### 引擎做了什么（实现要点）

- **逐字拟人输入**：每字随机延迟 + 偶发卡顿 + 偶发结巴（净输出不变，但打乱输入时序）。
- **阅读停留**：评论前按帖子长度估算停留时长（越长越久，带随机抖动）。
- **拟人滚动**：偶发停顿、偶发回滚，避免「匀速下滑」的机器特征。
- **曲线鼠标**：点击前从随机偏移点出发，中途走 waypoint，偶发过冲再修正，绝不停瞬移。
- **AI 内容后处理**（`humanize_reply`）：对生成文本做偶发错别字 / emoji / 截断 / 标点波动，去掉「AI 味」。
- **节奏打乱**：随机纯浏览跳过、随机操作顺序、偶发长休息、会话操作上限后强制长休 —— 规避频次异常风控。

> 使用建议：新号 / 低权重号调保守（降速率、升停留、降会话上限）；老号可适度调激进。所有旋钮都在 GUI 弹窗里实时可调，无需改代码。

## 🗂 目录

```
xhsreview/
├── main.py                  # 启动入口（含自包含浏览器路径处理）
├── scripts/
│   └── build_exe.py         # 一键打包 EXE 脚本（Windows）
├── src/
│   ├── app.py               # Tkinter 主窗口 + 拟人化设置弹窗
│   ├── theme.py             # 主题样式
│   ├── config.py            # 配置管理（含 humanize 默认配置）
│   ├── anthropic_client.py  # API 客户端 + 内容拟人后处理
│   ├── xhs_crawler.py       # 抓取 / 评论 / 拟人化交互引擎
│   └── scheduler.py         # 调度器（节奏 / 会话上限 / 长休息）
├── config.example.json      # 配置模板（humanize 节完整示例）
├── config/config.json       # 用户配置（自动生成，含 API Key，勿提交）
└── logs/                    # 运行日志与诊断导出
```

## 🔌 Anthropic Messages API

请求格式（自动生成）：

```http
POST {base_url}/v1/messages
Content-Type: application/json
x-api-key: {api_key}
anthropic-version: 2023-06-01

{
  "model": "claude-3-5-sonnet-20241022",
  "max_tokens": 256,
  "temperature": 0.85,
  "system": "你是一个{persona}。你会针对小红书上的帖子写一条像真人随手发的短回复……",
  "messages": [
    {"role": "user", "content": "【帖子标题】xxx\n【帖子正文】yyy\n请针对这个帖子写一条回复："}
  ]
}
```

## 💻 打包为独立 EXE（Windows）

工具已支持**自包含打包**：把 Playwright 的 Chromium 浏览器一起打进 exe 目录，分发后无需目标机安装 Python / Playwright / Chrome 即可运行。

### 一键打包

```bash
# 在本机（需已装 playwright + pyinstaller 的 Python 3.12）
python scripts/build_exe.py
```

脚本会自动：
1. 定位本机 `ms-playwright` 浏览器目录；
2. 以 onedir 模式构建 `dist/xhsreview/`（含 `xhsreview.exe` + 依赖 + 内置浏览器）；
3. 附带 `config.example.json` 作模板；
4. **绝不打包真实 `config/config.json`**（含 API Key）。

### 手动打包（等价命令）

```bash
pyinstaller --noconfirm --name xhsreview --onedir --noconsole ^
  --hidden-import playwright --hidden-import greenlet --hidden-import requests ^
  --collect-all playwright ^
  --add-data "%LOCALAPPDATA%\ms-playwright\chromium-1228;ms-playwright/chromium-1228" ^
  --add-data "%LOCALAPPDATA%\ms-playwright\chromium_headless_shell-1228;ms-playwright/chromium_headless_shell-1228" ^
  --add-data "%LOCALAPPDATA%\ms-playwright\ffmpeg-1011;ms-playwright/ffmpeg-1011" ^
  --add-data "config.example.json;config.example.json" ^
  main.py
```

### 运行打包产物

1. 将整个 `dist/xhsreview/` 目录拷到目标机器；
2. 双击 `xhsreview.exe`；
3. 首次运行需在弹出的浏览器里**扫码登录小红书**（登录态保存在临时 profile，勿清空）；
4. 在 GUI 里填入 Anthropic API Key 即可开始。

> 浏览器内核随包携带（`ms-playwright/`），`main.py` 会在 exe 同目录检测到它并优先使用，因此目标机无需预装任何东西。

## ⚠️ 免责声明

本工具仅供学习与研究使用，请遵守小红书用户协议与相关法律法规。自动化操作可能违反平台规则，使用者需自行承担风险。
