# TinyClaw

Python 学习版 OpenClaw — 用于理解 AI Agent 架构的轻量实现（<10,000 行代码）。

## 快速开始

```bash
pip install -e .
export OPENAI_API_KEY="your-key"
tinyclaw run
```

## 交互使用

启动后直接输入自然语言，Agent 会理解并执行你的请求：

```
> 列出当前目录下的所有文件
> 帮我写一个 hello.py 文件
> 搜索项目中包含 TODO 的文件
> 创建一个每 5 分钟执行的定时任务，检查磁盘空间
> 把这段代码的功能记到长期记忆里
> quit
```

Agent 拥有 19 个内置工具，包括：
- `bash` — 执行 shell 命令
- `read_file` / `write_file` / `list_dir` — 文件操作
- `save_memory` / `search_memory` — 长期记忆读写
- `spawn_subagent` — 委派子 Agent 执行子任务
- `create_cron` / `list_crons` / `delete_cron` — 定时任务管理
- `load_skill` — 按需加载技能指令
- `sandbox_exec` — 在 Docker 沙箱中执行命令
- `compact` — 手动压缩对话上下文

## CLI 管理命令

```bash
tinyclaw run              # 启动 Agent 服务
tinyclaw agent list       # 列出所有 Agent
tinyclaw tool list        # 列出所有工具
tinyclaw cron list        # 列出定时任务
tinyclaw plugin list      # 列出插件
tinyclaw channel list     # 列出通道
tinyclaw --version        # 查看版本
tinyclaw --help           # 查看帮助
```

## 配置

复制配置模板并修改：

```bash
cp config.example.yaml config.yaml
```

支持的环境变量：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OPENAI_API_KEY` | API 密钥 | (必填) |
| `OPENAI_BASE_URL` | API 地址 | `https://api.openai.com/v1` |
| `TINYCLAW_MODEL` | 模型名称 | `gpt-4o-mini` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot Token | (可选) |
| `DISCORD_BOT_TOKEN` | Discord Bot Token | (可选) |
| `FEISHU_APP_ID` | 飞书 App ID | (可选) |
| `FEISHU_APP_SECRET` | 飞书 App Secret | (可选) |

## 消息渠道

支持 3 个渠道，在 `config.yaml` 中启用：
- **CLI** — 命令行交互（默认启用）
- **Telegram** — 需配置 `TELEGRAM_BOT_TOKEN`
- **Discord** — 需配置 `DISCORD_BOT_TOKEN`
- **飞书** — 需配置 `FEISHU_APP_ID` + `FEISHU_APP_SECRET`

## 渐进式教程

12 个独立可运行的 Python 文件，从 84 行的最简 Agent Loop 逐步构建到 1500 行的完整插件系统：

```bash
python agents/s01_agent_loop.py    # Agent Loop (84 行)
python agents/s02_tools.py         # 工具系统 (160 行)
python agents/s03_skills.py        # Skills 系统 (230 行)
python agents/s04_subagents.py     # 子 Agent (300 行)
python agents/s05_message_bus.py   # 消息总线 (400 行)
python agents/s06_channel_telegram.py  # Telegram 渠道 (520 行)
python agents/s07_memory.py        # 持久化记忆 (650 行)
python agents/s08_compaction.py    # 上下文压缩 (750 行)
python agents/s09_cron.py          # 定时任务 (880 行)
python agents/s10_sandbox.py       # 容器隔离 (1050 行)
python agents/s11_mcp.py           # MCP 协议 (1250 行)
python agents/s12_plugins.py       # 插件系统 (1500 行)
```

## 教程网站

Next.js 构建的交互式教程，包含原理分析和代码实现：

```bash
cd tutorial && npm install && npm run dev
```

访问 http://localhost:3000 查看。
