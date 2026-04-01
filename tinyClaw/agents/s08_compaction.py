"""
TinyClaw s08 — 上下文压缩
==========================
核心概念：Token 有限，摘要无限 —— 三层压缩策略

LLM 的上下文窗口有限。当对话变长时，需要压缩旧消息。
三层策略：
1. 微压缩：截断单条过长的工具输出
2. 自动压缩：当 token 数超过阈值，用 LLM 摘要旧消息
3. 手动压缩：Agent 可主动触发压缩

新增：
- token_count(): 估算消息的 token 数
- compact_messages(): LLM 驱动的消息摘要
- compact 工具：Agent 可主动压缩上下文

运行：python agents/s08_compaction.py
"""

import abc
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
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
DATA_DIR = Path(os.getenv("TINYCLAW_DATA_DIR", "data")).resolve()
MAX_SUBAGENT_DEPTH = 3

# 压缩阈值
MAX_TOKENS = int(os.getenv("TINYCLAW_MAX_TOKENS", "50000"))
COMPACT_TARGET_TOKENS = int(os.getenv("TINYCLAW_COMPACT_TARGET", "20000"))
MAX_TOOL_OUTPUT_LEN = 4096  # 微压缩：单条工具输出上限


# ── 消息类型 & 总线 ──────────────────────────────────
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


class MessageBus:
    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)


# ── Token 估算 ───────────────────────────────────────
def estimate_tokens(text: str) -> int:
    """
    粗略估算 token 数。
    英文 ≈ 1 token/4 字符，中文 ≈ 1 token/1.5 字符。
    这里用简单的混合估算。
    """
    if not text:
        return 0
    # 统计中文字符
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def messages_token_count(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if content:
                total += estimate_tokens(content)
            # tool_calls 也占 token
            if "tool_calls" in msg and msg["tool_calls"]:
                total += estimate_tokens(json.dumps(msg["tool_calls"]))
        else:
            # OpenAI message object
            content = getattr(msg, "content", "") or ""
            total += estimate_tokens(content)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    total += estimate_tokens(tc.function.arguments)
    return total


# ── 上下文压缩 ───────────────────────────────────────
def micro_compact(text: str, max_len: int = MAX_TOOL_OUTPUT_LEN) -> str:
    """微压缩：截断过长的单条输出。"""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n...[截断 {len(text) - max_len} 字符]...\n" + text[-half:]


def compact_messages(messages: list[dict], target_tokens: int = COMPACT_TARGET_TOKENS) -> list[dict]:
    """
    LLM 驱动的消息摘要压缩：
    1. 保留 system 消息（第一条）
    2. 将旧消息（除最近 4 轮）摘要为一条
    3. 保留最近 4 轮完整消息
    """
    if len(messages) <= 5:
        return messages  # 太少，不需要压缩

    system_msg = messages[0] if messages[0].get("role") == "system" else None
    non_system = messages[1:] if system_msg else messages

    # 保留最近的 8 条消息（约 4 轮对话）
    keep_recent = 8
    if len(non_system) <= keep_recent:
        return messages

    old_messages = non_system[:-keep_recent]
    recent_messages = non_system[-keep_recent:]

    # 用 LLM 摘要旧消息
    summary_text = _summarize_messages(old_messages)

    result = []
    if system_msg:
        result.append(system_msg)
    result.append({
        "role": "user",
        "content": f"[以下是之前对话的摘要]\n{summary_text}\n[摘要结束，以下是最近的对话]",
    })
    result.extend(recent_messages)

    print(f"  📦 压缩: {messages_token_count(messages)} → {messages_token_count(result)} tokens")
    return result


def _summarize_messages(messages: list[dict]) -> str:
    """调用 LLM 将一组消息压缩为摘要。"""
    conversation_text = ""
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content:
            conversation_text += f"[{role}]: {content[:500]}\n"

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "请将以下对话摘要为简洁的要点，保留关键信息（做了什么、结果如何）。用中文回复，200字以内。",
                },
                {"role": "user", "content": conversation_text[:3000]},
            ],
            max_tokens=300,
        )
        return response.choices[0].message.content or "(摘要失败)"
    except Exception as e:
        return f"(摘要出错: {e})"


# ── SQLite 存储层 ─────────────────────────────────────
class Store:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT, tool_calls TEXT, tool_call_id TEXT,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY, last_active REAL NOT NULL, metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, timestamp);
        """)
        self.conn.commit()

    def save_message(self, chat_id: str, role: str, content: str | None = None,
                     tool_calls: str | None = None, tool_call_id: str | None = None):
        self.conn.execute(
            "INSERT INTO messages (chat_id, role, content, tool_calls, tool_call_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, tool_calls, tool_call_id, time.time()),
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions (chat_id, last_active) VALUES (?, ?)",
            (chat_id, time.time()),
        )
        self.conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role, content, tool_calls, tool_call_id FROM messages "
            "WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        messages = []
        for row in reversed(rows):
            msg: dict = {"role": row["role"]}
            if row["content"]:
                msg["content"] = row["content"]
            if row["tool_calls"]:
                msg["tool_calls"] = json.loads(row["tool_calls"])
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            messages.append(msg)
        return messages

    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT chat_id, role, content, timestamp FROM messages "
            "WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        self.conn.close()


# ── MEMORY.md ─────────────────────────────────────────
class MemoryManager:
    def __init__(self, memory_path: Path):
        self.path = memory_path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("# TinyClaw 记忆\n\n", encoding="utf-8")

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def append(self, entry: str) -> str:
        content = self.read()
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        content += f"\n## [{timestamp}]\n{entry}\n"
        self.path.write_text(content, encoding="utf-8")
        return f"已保存记忆 ({len(entry)} 字符)"

    def search(self, query: str) -> str:
        content = self.read()
        lines = content.split("\n")
        matches = [l for l in lines if query.lower() in l.lower()]
        return "\n".join(matches[:20]) if matches else f"未找到与 '{query}' 相关的记忆"


# ── Channel ───────────────────────────────────────────
class Channel(abc.ABC):
    @abc.abstractmethod
    async def connect(self, bus: MessageBus) -> None: ...
    @abc.abstractmethod
    async def disconnect(self) -> None: ...
    @abc.abstractmethod
    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None: ...
    @property
    @abc.abstractmethod
    def name(self) -> str: ...


class CLIChannel(Channel):
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
                user_input = await loop.run_in_executor(None, lambda: input("\n> ").strip())
                if user_input.lower() in ("quit", "exit", "q"):
                    self._running = False
                    if self._bus:
                        await self._bus.inbound.put(InboundMessage(
                            channel="cli", chat_id="cli-main",
                            user_id="system", text="__QUIT__",
                        ))
                    return
                if user_input and self._bus:
                    await self._bus.inbound.put(InboundMessage(
                        channel="cli", chat_id="cli-main",
                        user_id="user", text=user_input, sender_name="用户",
                    ))
            except (EOFError, KeyboardInterrupt):
                self._running = False
                return


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
    lines = ["\n可用技能（使用 load_skill 获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)


# ── 初始化 ────────────────────────────────────────────
store = Store(DATA_DIR / "tinyclaw.db")
memory_mgr = MemoryManager(WORKDIR / "workspace" / "MEMORY.md")


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
        return micro_compact(output) if output else "(无输出)"
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
        return micro_compact(content, 8192) if content else "(空文件)"
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


@tool("save_memory", "保存重要信息到长期记忆。", {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
})
def save_memory(content: str) -> str:
    return memory_mgr.append(content)


@tool("search_memory", "搜索长期记忆和对话历史。", {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
})
def search_memory(query: str) -> str:
    file_results = memory_mgr.search(query)
    db_results = store.search_messages(query, limit=10)
    db_text = ""
    if db_results:
        db_text = "\n\n--- 对话历史 ---\n"
        for r in db_results:
            content_str = r['content'] or ''
            db_text += f"[{r['role']}] {content_str[:100]}\n"
    return file_results + db_text


@tool("compact", "手动压缩当前对话的上下文。", {
    "type": "object",
    "properties": {},
    "required": [],
})
def compact() -> str:
    return "__COMPACT__"  # 特殊标记，由 Agent Loop 处理


# ── Agent 处理器（带压缩）────────────────────────────
def run_agent(user_message: str, chat_id: str = "default") -> str:
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)
    memory_content = memory_mgr.read()
    memory_prompt = ""
    if memory_content.strip() and memory_content.strip() != "# TinyClaw 记忆":
        memory_prompt = f"\n\n你的长期记忆：\n{memory_content[:2000]}"

    system_prompt = (
        "你是 TinyClaw，一个有记忆的 AI 助手，支持上下文压缩。\n"
        "你可以执行命令、操作文件、加载技能、委派子 Agent。\n"
        "当对话过长时，可用 compact 工具压缩上下文。\n"
        f"工作目录: {WORKDIR}"
        f"{skills_prompt}{memory_prompt}"
    )

    history = store.get_recent_messages(chat_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    store.save_message(chat_id, "user", user_message)

    tools = get_tool_schemas()

    while True:
        # ── 自动压缩检查 ──
        token_count = messages_token_count(messages)
        if token_count > MAX_TOKENS:
            print(f"  📦 自动压缩触发 ({token_count} tokens > {MAX_TOKENS})")
            messages = compact_messages(messages, COMPACT_TARGET_TOKENS)

        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            reply = assistant_msg.content or ""
            store.save_message(chat_id, "assistant", reply)
            return reply

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"  ⚙ {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")
            result = execute_tool(fn_name, fn_args, depth=0)

            # 处理手动压缩
            if result == "__COMPACT__":
                messages = compact_messages(messages, COMPACT_TARGET_TOKENS)
                result = "上下文已压缩。"

            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            store.save_message(chat_id, "tool", result, tool_call_id=tc.id)


# ── Gateway ───────────────────────────────────────────
class Gateway:
    def __init__(self, bus: MessageBus, channels: list[Channel]):
        self.bus = bus
        self.channels = {ch.name: ch for ch in channels}
        self._running = False

    async def start(self):
        for ch in self.channels.values():
            await ch.connect(self.bus)
        self._running = True
        await asyncio.gather(self._process_inbound(), self._route_outbound())

    async def _process_inbound(self):
        while self._running:
            msg = await self.bus.inbound.get()
            if msg.text == "__QUIT__":
                self._running = False
                return
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(None, run_agent, msg.text, msg.chat_id)
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
        store.close()


# ── 主函数 ────────────────────────────────────────────
async def main():
    print("TinyClaw s08 — 上下文压缩")
    print(f"压缩阈值: {MAX_TOKENS} tokens  |  目标: {COMPACT_TARGET_TOKENS} tokens")
    print(f"已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")
    print("输入指令（quit 退出）：")

    bus = MessageBus()
    channels: list[Channel] = [CLIChannel()]
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
