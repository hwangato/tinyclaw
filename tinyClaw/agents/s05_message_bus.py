"""
TinyClaw s05 — 消息总线
========================
核心概念：发布-订阅解耦 —— 消息的生产者和消费者互不知晓，
通过总线松散连接。

在 s04 中，Agent 直接处理用户输入。当我们要接入多个消息渠道时，
需要一个中间层来解耦「消息来源」和「Agent 处理」。

新增：
- MessageBus：asyncio.Queue 双向消息总线（inbound + outbound）
- InboundMessage / OutboundMessage 统一消息格式
- Gateway：编排器，连接消息源和 Agent
- CLI 作为第一个 "Channel"

运行：python agents/s05_message_bus.py
"""

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


# ── 消息类型 ──────────────────────────────────────────
@dataclass
class InboundMessage:
    """从渠道进入 Agent 的消息。"""
    channel: str          # 来源渠道：cli / telegram / discord / feishu
    chat_id: str          # 会话 ID
    user_id: str          # 发送者 ID
    text: str             # 消息文本
    sender_name: str = "" # 发送者名称
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class OutboundMessage:
    """从 Agent 发出到渠道的消息。"""
    channel: str          # 目标渠道
    chat_id: str          # 目标会话
    text: str             # 回复文本
    reply_to: str = ""    # 回复的消息 ID


# ── 消息总线 ──────────────────────────────────────────
class MessageBus:
    """
    双向异步消息总线。
    - inbound: 渠道 → Agent 的消息队列
    - outbound: Agent → 渠道 的消息队列
    """

    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

    async def publish_inbound(self, msg: InboundMessage):
        await self.inbound.put(msg)

    async def publish_outbound(self, msg: OutboundMessage):
        await self.outbound.put(msg)

    async def consume_inbound(self) -> InboundMessage:
        return await self.inbound.get()

    async def consume_outbound(self) -> OutboundMessage:
        return await self.outbound.get()


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
    "properties": {"task": {"type": "string", "description": "委派的任务描述"}},
    "required": ["task"],
})
def spawn_subagent(task: str, _depth: int = 0) -> str:
    if _depth >= MAX_SUBAGENT_DEPTH:
        return f"已达最大嵌套深度 ({MAX_SUBAGENT_DEPTH})"
    print(f"  🔀 [深度 {_depth + 1}] 派生子 Agent: {task[:60]}...")
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
    """同步执行 Agent Loop，返回最终回复文本。"""
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


# ── Gateway：连接总线与 Agent ─────────────────────────
class Gateway:
    """
    编排器：从 inbound 队列消费消息 → 交给 Agent → 将回复放入 outbound 队列。
    """

    def __init__(self, bus: MessageBus):
        self.bus = bus
        self._running = False

    async def start(self):
        self._running = True
        while self._running:
            msg = await self.bus.consume_inbound()
            # 在线程池中运行同步的 Agent（因为 openai SDK 是同步的）
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(None, run_agent, msg.text)

            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                text=reply_text,
                reply_to=msg.message_id,
            ))

    def stop(self):
        self._running = False


# ── CLI Channel ───────────────────────────────────────
async def cli_input_loop(bus: MessageBus):
    """CLI 渠道：从标准输入读取，发送到消息总线。"""
    loop = asyncio.get_event_loop()
    while True:
        user_input = await loop.run_in_executor(None, lambda: input("\n> ").strip())
        if user_input.lower() in ("quit", "exit", "q"):
            return
        if user_input:
            await bus.publish_inbound(InboundMessage(
                channel="cli",
                chat_id="cli-main",
                user_id="user",
                text=user_input,
                sender_name="用户",
            ))


async def cli_output_loop(bus: MessageBus):
    """CLI 渠道：从消息总线读取回复，输出到终端。"""
    while True:
        msg = await bus.consume_outbound()
        print(f"\n🤖 {msg.text}")


# ── 主函数 ────────────────────────────────────────────
async def main():
    print(f"TinyClaw s05 — 消息总线")
    print(f"已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")
    print("输入指令（quit 退出）：")

    bus = MessageBus()
    gateway = Gateway(bus)

    # 并发运行：CLI 输入、CLI 输出、Gateway 处理
    tasks = [
        asyncio.create_task(cli_input_loop(bus)),
        asyncio.create_task(cli_output_loop(bus)),
        asyncio.create_task(gateway.start()),
    ]

    # 等待 CLI 输入结束（用户输入 quit）
    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    for t in pending:
        t.cancel()
    gateway.stop()
    print("\n再见！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
