"""
TinyClaw s06 — 接入 Telegram
==============================
核心概念：Channel 抽象 —— 一套接口对接多平台

新增：
- Channel 协议（抽象基类）：connect / disconnect / send_message
- TelegramChannel：基于 aiogram 3 的 Telegram Bot 实现
- CLIChannel：将之前的 CLI 输入/输出封装为标准 Channel
- Gateway 现在通过 Channel 列表管理多渠道

依赖：pip install aiogram openai
环境变量：TELEGRAM_BOT_TOKEN

运行：python agents/s06_channel_telegram.py
"""

import abc
import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
MODEL = os.getenv("TINYCLAW_MODEL", "gpt-4o-mini")
WORKDIR = Path(os.getenv("TINYCLAW_WORKDIR", ".")).resolve()
SKILLS_DIR = Path(os.getenv("TINYCLAW_SKILLS_DIR", "workspace/skills")).resolve()
MAX_SUBAGENT_DEPTH = 3
TRIGGER_WORD = os.getenv("TINYCLAW_TRIGGER", "@claw")


# ── 消息类型 ──────────────────────────────────────────
@dataclass
class InboundMessage:
    channel: str
    chat_id: str
    user_id: str
    text: str
    sender_name: str = ""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class OutboundMessage:
    channel: str
    chat_id: str
    text: str
    reply_to: str = ""


# ── 消息总线 ──────────────────────────────────────────
class MessageBus:
    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

    async def publish_inbound(self, msg: InboundMessage):
        await self.inbound.put(msg)

    async def publish_outbound(self, msg: OutboundMessage):
        await self.outbound.put(msg)


# ── Channel 抽象协议 ──────────────────────────────────
class Channel(abc.ABC):
    """
    渠道抽象：每个消息平台实现这个接口。
    - connect(): 建立连接，开始监听消息
    - disconnect(): 断开连接
    - send_message(): 发送消息到指定会话
    """

    @abc.abstractmethod
    async def connect(self, bus: MessageBus) -> None:
        """建立连接，将收到的消息发布到 bus.inbound。"""

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """断开连接。"""

    @abc.abstractmethod
    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """发送消息到指定会话。"""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """渠道名称标识。"""


# ── CLI Channel ───────────────────────────────────────
class CLIChannel(Channel):
    """命令行渠道：从 stdin 读取，输出到 stdout。"""

    def __init__(self):
        self._bus: MessageBus | None = None
        self._running = False

    @property
    def name(self) -> str:
        return "cli"

    async def connect(self, bus: MessageBus) -> None:
        self._bus = bus
        self._running = True
        asyncio.create_task(self._input_loop())

    async def disconnect(self) -> None:
        self._running = False

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        print(f"\n🤖 {text}")

    async def _input_loop(self):
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                user_input = await loop.run_in_executor(
                    None, lambda: input("\n> ").strip()
                )
                if user_input.lower() in ("quit", "exit", "q"):
                    self._running = False
                    # 发送一个特殊消息通知 Gateway 停止
                    if self._bus:
                        await self._bus.publish_inbound(InboundMessage(
                            channel="cli", chat_id="cli-main",
                            user_id="system", text="__QUIT__",
                        ))
                    return
                if user_input and self._bus:
                    await self._bus.publish_inbound(InboundMessage(
                        channel="cli", chat_id="cli-main",
                        user_id="user", text=user_input, sender_name="用户",
                    ))
            except (EOFError, KeyboardInterrupt):
                self._running = False
                return


# ── Telegram Channel ──────────────────────────────────
class TelegramChannel(Channel):
    """
    Telegram 渠道：基于 aiogram 3。
    - 群聊中需要触发词才响应
    - 私聊直接响应所有消息
    """

    def __init__(self, token: str, trigger_word: str = "@claw"):
        self._token = token
        self._trigger = trigger_word.lower()
        self._bus: MessageBus | None = None
        self._bot = None
        self._dp = None

    @property
    def name(self) -> str:
        return "telegram"

    async def connect(self, bus: MessageBus) -> None:
        try:
            from aiogram import Bot, Dispatcher
            from aiogram.types import Message as TgMessage
        except ImportError:
            print("  [Telegram] aiogram 未安装，跳过。运行: pip install aiogram")
            return

        self._bus = bus
        self._bot = Bot(token=self._token)
        self._dp = Dispatcher()

        @self._dp.message()
        async def on_message(message: TgMessage):
            if not message.text or not self._bus:
                return

            text = message.text.strip()
            chat_id = str(message.chat.id)
            is_group = message.chat.type in ("group", "supergroup")

            # 群聊需要触发词
            if is_group:
                if self._trigger not in text.lower():
                    return
                text = text.replace(self._trigger, "").replace(
                    self._trigger.upper(), ""
                ).strip()

            if not text:
                return

            sender_name = message.from_user.full_name if message.from_user else "Unknown"
            await self._bus.publish_inbound(InboundMessage(
                channel="telegram",
                chat_id=chat_id,
                user_id=str(message.from_user.id) if message.from_user else "unknown",
                text=text,
                sender_name=sender_name,
                message_id=str(message.message_id),
            ))

        # 在后台启动轮询
        asyncio.create_task(self._start_polling())
        print(f"  [Telegram] 已连接，触发词: {self._trigger}")

    async def _start_polling(self):
        if self._dp and self._bot:
            try:
                await self._dp.start_polling(self._bot)
            except Exception as e:
                print(f"  [Telegram] 轮询出错: {e}")

    async def disconnect(self) -> None:
        if self._dp:
            self._dp.shutdown()
        if self._bot:
            await self._bot.session.close()

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        if not self._bot:
            return
        try:
            # Telegram 消息长度限制 4096
            for i in range(0, len(text), 4000):
                chunk = text[i:i + 4000]
                kwargs = {"chat_id": int(chat_id), "text": chunk}
                if reply_to and i == 0:
                    kwargs["reply_to_message_id"] = int(reply_to)
                await self._bot.send_message(**kwargs)
        except Exception as e:
            print(f"  [Telegram] 发送失败: {e}")


# ── 工具注册表 ────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str, parameters: dict):
    def decorator(func):
        _TOOL_REGISTRY[name] = {
            "schema": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            "func": func,
        }
        return func
    return decorator


def get_tool_schemas() -> list[dict]:
    return [t["schema"] for t in _TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict, depth: int = 0) -> str:
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return f"未知工具: {name}"
    try:
        if name == "spawn_subagent":
            return entry["func"](**arguments, _depth=depth)
        return entry["func"](**arguments)
    except Exception as e:
        return f"工具执行出错: {e}"


def safe_path(filepath: str) -> Path:
    resolved = (WORKDIR / filepath).resolve()
    if not str(resolved).startswith(str(WORKDIR)):
        raise PermissionError(f"路径越界: {filepath}")
    return resolved


# ── Skills ────────────────────────────────────────────
def parse_skill_md(content: str) -> dict:
    meta = {"name": "", "description": ""}
    body = content
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2).strip()
    return {"meta": meta, "body": body}


def load_all_skill_summaries() -> list[dict]:
    summaries = []
    if not SKILLS_DIR.exists():
        return summaries
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        sf = skill_dir / "SKILL.md"
        if sf.exists():
            parsed = parse_skill_md(sf.read_text(encoding="utf-8"))
            summaries.append({
                "id": skill_dir.name,
                "name": parsed["meta"].get("name", skill_dir.name),
                "description": parsed["meta"].get("description", ""),
            })
    return summaries


def build_skills_prompt(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    lines = ["\n可用技能（使用 load_skill 工具获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。", {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        return output[:4096] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"


@tool("read_file", "读取文件内容。", {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
})
def read_file(path: str) -> str:
    try:
        content = safe_path(path).read_text(encoding="utf-8")
        return content[:8192] if content else "(空文件)"
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except PermissionError as e:
        return str(e)


@tool("write_file", "写入内容到文件。", {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
    "required": ["path", "content"],
})
def write_file(path: str, content: str) -> str:
    try:
        p = safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p.relative_to(WORKDIR)} ({len(content)} 字符)"
    except PermissionError as e:
        return str(e)


@tool("list_dir", "列出目录内容。", {
    "type": "object",
    "properties": {"path": {"type": "string", "default": "."}},
    "required": [],
})
def list_dir(path: str = ".") -> str:
    try:
        p = safe_path(path)
        if not p.is_dir():
            return f"不是目录: {path}"
        entries = []
        for item in sorted(p.iterdir()):
            prefix = "📁 " if item.is_dir() else "📄 "
            entries.append(f"{prefix}{item.name}")
        return "\n".join(entries) if entries else "(空目录)"
    except PermissionError as e:
        return str(e)


@tool("load_skill", "加载指定技能的详细指令。", {
    "type": "object",
    "properties": {"skill_id": {"type": "string"}},
    "required": ["skill_id"],
})
def load_skill(skill_id: str) -> str:
    sf = SKILLS_DIR / skill_id / "SKILL.md"
    if not sf.exists():
        return f"技能不存在: {skill_id}"
    parsed = parse_skill_md(sf.read_text(encoding="utf-8"))
    return f"# 技能: {parsed['meta']['name']}\n\n{parsed['body']}"


@tool("spawn_subagent", "创建子 Agent 执行独立任务。", {
    "type": "object",
    "properties": {"task": {"type": "string"}},
    "required": ["task"],
})
def spawn_subagent(task: str, _depth: int = 0) -> str:
    if _depth >= MAX_SUBAGENT_DEPTH:
        return f"已达最大嵌套深度 ({MAX_SUBAGENT_DEPTH})"
    sub_messages = [
        {"role": "system", "content": f"你是 TinyClaw 子 Agent。工作目录: {WORKDIR}\n完成后直接给出结果。"},
        {"role": "user", "content": task},
    ]
    tools = get_tool_schemas()
    for _ in range(20):
        response = client.chat.completions.create(model=MODEL, messages=sub_messages, tools=tools)
        msg = response.choices[0].message
        sub_messages.append(msg)
        if not msg.tool_calls:
            return msg.content or "(子 Agent 无回复)"
        for tc in msg.tool_calls:
            fn_args = json.loads(tc.function.arguments)
            result = execute_tool(tc.function.name, fn_args, depth=_depth + 1)
            sub_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
    return "(子 Agent 达到最大迭代次数)"


# ── Agent 处理器 ──────────────────────────────────────
def run_agent(user_message: str) -> str:
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)
    system_prompt = (
        "你是 TinyClaw，一个能执行命令、操作文件、加载技能的 AI 助手。\n"
        "你可以使用 spawn_subagent 将复杂任务委派给子 Agent。\n"
        f"工作目录: {WORKDIR}"
        f"{skills_prompt}"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tools = get_tool_schemas()

    while True:
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)
        if not assistant_msg.tool_calls:
            return assistant_msg.content or ""
        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"  ⚙ {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")
            result = execute_tool(fn_name, fn_args, depth=0)
            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


# ── Gateway ───────────────────────────────────────────
class Gateway:
    def __init__(self, bus: MessageBus, channels: list[Channel]):
        self.bus = bus
        self.channels = {ch.name: ch for ch in channels}
        self._running = False

    async def start(self):
        # 连接所有渠道
        for ch in self.channels.values():
            await ch.connect(self.bus)

        self._running = True

        # 并发：处理 inbound + 路由 outbound
        await asyncio.gather(
            self._process_inbound(),
            self._route_outbound(),
        )

    async def _process_inbound(self):
        while self._running:
            msg = await self.bus.inbound.get()
            if msg.text == "__QUIT__":
                self._running = False
                return
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(None, run_agent, msg.text)
            await self.bus.outbound.put(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                text=reply_text, reply_to=msg.message_id,
            ))

    async def _route_outbound(self):
        while self._running:
            msg = await self.bus.outbound.get()
            ch = self.channels.get(msg.channel)
            if ch:
                await ch.send_message(msg.chat_id, msg.text, msg.reply_to)

    async def stop(self):
        self._running = False
        for ch in self.channels.values():
            await ch.disconnect()


# ── 主函数 ────────────────────────────────────────────
async def main():
    print("TinyClaw s06 — 接入 Telegram")
    print(f"已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")

    # 构建渠道列表
    channels: list[Channel] = [CLIChannel()]

    tg_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if tg_token:
        channels.append(TelegramChannel(tg_token, trigger_word=TRIGGER_WORD))
        print(f"  [Telegram] Token 已配置，触发词: {TRIGGER_WORD}")
    else:
        print("  [Telegram] 未配置 TELEGRAM_BOT_TOKEN，仅使用 CLI")

    print(f"活跃渠道: {', '.join(ch.name for ch in channels)}")
    print("输入指令（quit 退出）：")

    bus = MessageBus()
    gateway = Gateway(bus, channels)

    try:
        await gateway.start()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await gateway.stop()
    print("\n再见！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
