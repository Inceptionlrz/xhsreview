# XHS Review · 小红书智能回复助手

> 仿 Linux.do 刷帖助手 v8.5.0 风格的桌面工具：自动浏览小红书首页推荐流，**基于 Anthropic Messages API 动态生成回复**，可自定义 URL 与 Key。

## ✨ 功能

- 🧠 **AI 智能回复**：调用 Anthropic Messages API，针对每个帖子的标题/正文生成自然口语化的回复
- ⚙️ **API 完全可配**：URL、Key、Model、人设、温度、max_tokens 全部可自定义，支持中转站
- 🌐 **真实抓取**：基于 Playwright 浏览器自动化，模拟真人滚动/键入，反检测
- 🔁 **虚拟数据模式**：未安装 Playwright 或无登录态时使用，零依赖可演示
- 📊 **三大运行模式**：无限制 / 帖子数 / 时间限制
- 🐢 **双爬楼模式**：深度爬楼（完整阅读）/ 快速浏览（3~5 层换帖）
- 👍 **行为概率控制**：自动点赞率、自动回复率、随机等待区间
- 🧩 **板块筛选**：内置 15 个板块（开发调优、国产替代、资源荟萃…）
- 📈 **实时统计**：帖子 / 爬楼 / 点赞 / 回复 / 错误 / 升级进度

## 📦 安装

```bash
pip install requests playwright
playwright install chromium
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
3. 调整运行模式、概率、板块
4. 点击「▶ 开始」

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
│   └── scheduler.py     # 调度器
├── config/config.json   # 用户配置（自动生成）
└── logs/                # 预留日志目录
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

## ⚠️ 免责声明

本工具仅供学习与研究使用，请遵守小红书用户协议与相关法律法规。自动化操作可能违反平台规则，使用者需自行承担风险。
