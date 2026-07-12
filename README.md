# XHS Review · 小红书智能回复助手

> 仿 Linux.do 刷帖助手 v8.5.0 风格的桌面工具：自动浏览小红书首页推荐流，**基于 Anthropic Messages API 动态生成回复**，可自定义 URL 与 Key。

**⚠️ 重要风险提醒（必读）**

本工具本质是浏览器自动化脚本，**小红书官方明确禁止**使用任何第三方工具、脚本或 AI 自动浏览、查看、点赞、评论。已有用户收到「账号违规预警」：

- 提示「请求次数过多」后收到系统消息；
- 被平台判定为「疑似使用三方工具或脚本（如 AI）自动运营账号」；
- 首次多为警告，多次可能限制账号功能。

**请把本工具仅用于学习研究，并自行承担全部风险。** 真实账号运行前，建议先用小号/弃号验证，且必须开启「🕐 运营画像」中的每日上限与活跃时段。

## ✨ 功能

- 🧠 **AI 智能回复**：调用 Anthropic Messages API，针对每个帖子的标题/正文生成自然口语化的回复
- ⚙️ **API 完全可配**：URL、Key、Model、人设、温度、max_tokens 全部可自定义，支持中转站
- 🌐 **真实抓取**：基于 Playwright 浏览器自动化，模拟真人滚动/键入，反检测
- 🔁 **虚拟数据模式**：未安装 Playwright 或无登录态时使用，零依赖可演示
- 📊 **三大运行模式**：无限制 / 帖子数 / 时间限制
- 🐢 **双爬楼模式**：深度爬楼（完整阅读）/ 快速浏览（3~5 层换帖）
- 👍 **行为概率控制**：自动点赞率、自动回复率、随机等待区间
- 🛡️ **拟人化 / 防封（核心）**：
  - 逐字随机打字 + 偶发卡顿 + 偶发「打错重打」
  - 鼠标曲线靠近 + 过冲修正 + 犹豫不点
  - 评论前阅读停留 + 先下滑看已有评论
  - 纯浏览跳过、随机长休息、会话操作上限、顺序随机
  - 环境指纹伪装（WebGL 渲染器、navigator.plugins、languages 等）
  - AI 回复内容后处理（偶发错别字 / emoji / 截断 / 标点波动）
- 🕐 **运营画像 / 风控**：
  - 每日点赞 / 评论上限（跨重启累计）
  - 只在指定活跃时段运行（默认 09:00-23:00）
  - 两次运行最小间隔
- 🧩 **板块筛选**：内置多个板块（推荐、穿搭、美食、彩妆等）
- 📈 **实时统计**：帖子 / 爬楼 / 点赞 / 回复 / 错误 / 升级进度

## 📦 安装

```bash
pip install requests playwright
playwright install chromium
```

Windows 上若后续需要打包成 EXE，建议同时安装：

```bash
pip install pyinstaller
```

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
   - 真实抓取需先扫码登录一次（profile 目录保留登录态）
3. 打开「🛡 拟人化设置」和「🕐 运营画像」，按下列推荐保守值调整（尤其是收到警告后）。
4. 点击「▶ 开始」

## 🛡 收到警告后的推荐保守配置

如果你已经收到「请求次数过多」或「账号违规预警」，请先把参数压到保守档，观察 1-2 天再决定是否缓慢上调：

| 设置项 | 推荐值 | 说明 |
|---|---|---|
| 自动点赞 | 关闭 / 开启 | 警告后建议关闭，或点赞率 ≤ 10% |
| 点赞率 | 10% | 多数帖子只浏览 |
| 自动回复 | 开启 | 但回复率 ≤ 25% |
| 回复率 | 25% | 大量帖子只看不评 |
| 帖子间等待 | 3~8 秒 | 不要低于 3 秒 |
| 纯浏览跳过率 | 45% | 近一半帖子完全不操作 |
| 看了但不评论率 | 25% | 连 AI 调用都省，更自然 |
| 会话操作上限 | 20 次 | 达到后强制长休 3~10 分钟 |
| 每日点赞上限 | 15 次 | 跨重启累计 |
| 每日评论上限 | 12 次 | 跨重启累计 |
| 活跃时段 | 09:00-23:00 | 避免深夜/凌晨运行 |
| 两次运行最小间隔 | 30 分钟 | 防止反复停止-启动刷量 |
| 长休息概率 | 15% | 每帖处理后有机会长休 45~180 秒 |

> 这些默认值已在 `config.example.json` 和 GUI「恢复默认」中生效。如果你之前保存过旧配置，建议手动把 `config/config.json` 里的 `like_rate`、`reply_rate`、`skip_rate` 等改到上表范围，或在对应弹窗点「恢复默认」。

## 🗂 目录

```
xhsreview/
├── main.py              # 启动入口
├── src/
│   ├── app.py           # Tkinter 主窗口
│   ├── theme.py         # 主题样式
│   ├── config.py        # 配置管理
│   ├── anthropic_client.py  # API 客户端
│   ├── xhs_crawler.py   # 抓取与回复
│   ├── scheduler.py     # 调度器
│   └── quota_tracker.py # 跨日配额/运营画像追踪
├── config/config.json   # 用户配置（自动生成，git 忽略）
├── config.example.json  # 配置模板（不含真实 Key）
├── logs/                # 运行日志
└── dist/xhsreview/      # PyInstaller 打包产物
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
  "system": "你是一个友好、有趣的小红书用户……",
  "messages": [
    {"role": "user", "content": "【帖子标题】xxx\n【帖子正文】yyy\n请针对这个帖子写一条回复："}
  ]
}
```

## 📦 打包成 EXE

本项目已配置 `xhsreview.spec`，使用 PyInstaller 的 `onedir` 模式，打包时会把 Playwright 浏览器随包携带，目标机无需再安装 Python 或 Playwright。

推荐用一键脚本：

```bash
python scripts/build_exe.py
```

或直接：

```bash
python -m PyInstaller xhsreview.spec --noconfirm
```

打包产物在 `dist/xhsreview/xhsreview.exe`。**打包时务必确保 `config/config.json` 不被包含**，因为它包含真实 API Key。`xhsreview.spec` 只包含 `config.example.json`。

## ⚠️ 免责声明

本工具仅供学习与研究使用，请遵守小红书用户协议与相关法律法规。自动化操作可能违反平台规则，使用者需自行承担风险。作者不对账号受限、封禁、数据丢失或其他损失负责。

---

**最后提醒**：没有任何技术手段能 100% 避免被平台检测。一旦收到平台警告，最安全的做法是停止使用自动化工具，回到手动操作，或者大幅降频、降低操作量、限定活跃时段。
