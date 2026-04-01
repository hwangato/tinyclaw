"""
TinyClaw s12 — 插件系统
========================
核心概念：JSON-RPC 2.0 based，语言无关的插件协议

这是 TinyClaw 渐进式教程的最终章（第 12 节）。
在 s11 的全部功能基础上，新增插件系统：

1. 插件协议（JSON-RPC 2.0 over stdin/stdout）
   - 请求: {"jsonrpc": "2.0", "id": N, "method": "...", "params": {...}}
   - 响应: {"jsonrpc": "2.0", "id": N, "result": {...}} 或 error
   - 通知: {"jsonrpc": "2.0", "method": "...", "params": {...}}（无 id）

2. 三种插件类型: tool / channel / hook

3. PluginProcess: 管理插件子进程
   - 通过 stdin 发送 JSON-RPC 请求，从 stdout 读取响应
   - 自增请求 ID（线程安全）
   - call / send_notification / shutdown

4. PluginManager: 发现与生命周期管理
   - 扫描插件目录的 plugin.json 清单
   - tool 插件: 注册为 plugin_{id}_{name} 工具
   - channel 插件: 适配为 Channel
   - hook 插件: 在生命周期钩子点触发

5. HookSystem: 6 个钩子点
   - before_system_prompt / after_system_prompt
   - before_model_call / after_model_call
   - before_tool_call / after_tool_call

6. 配置: TINYCLAW_PLUGINS_DIR（默认 "plugins/"）

运行：python agents/s12_plugins.py
"""

import abc
import asyncio
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

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
MAX_TOKENS = int(os.getenv("TINYCLAW_MAX_TOKENS", "50000"))
COMPACT_TARGET_TOKENS = int(os.getenv("TINYCLAW_COMPACT_TARGET", "20000"))
MAX_TOOL_OUTPUT_LEN = 4096
DOCKER_IMAGE = os.getenv("TINYCLAW_DOCKER_IMAGE", "python:3.12-slim")
DOCKER_TIMEOUT = int(os.getenv("TINYCLAW_DOCKER_TIMEOUT", "30"))
MCP_CONFIG_PATH = Path(os.getenv("TINYCLAW_MCP_CONFIG", "mcp_servers.json")).resolve()
PLUGINS_DIR = Path(os.getenv("TINYCLAW_PLUGINS_DIR", "plugins")).resolve()


# ── 消息类型 & 总线 ──────────────────────────────────
@dataclass
class InboundMessage:
    """入站消息：从各 Channel 发往 Agent 的消息。"""
    channel: str
    chat_id: str
    user_id: str
    text: str
    sender_name: str = ""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class OutboundMessage:
    """出站消息：Agent 回复发往 Channel。"""
    channel: str
    chat_id: str
    text: str
    reply_to: str = ""


class MessageBus:
    """消息总线：inbound/outbound 双向队列。"""
    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)


# ── Token 估算 & 压缩 ────────────────────────────────
def estimate_tokens(text: str) -> int:
    """粗略估算 token 数量：中文字符 / 1.5，其他字符 / 4。"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def messages_token_count(messages: list[dict]) -> int:
    """计算消息列表的总 token 数量。"""
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
            if content:
                total += estimate_tokens(content)
        else:
            content = getattr(msg, "content", "") or ""
            total += estimate_tokens(content)
    return total


def micro_compact(text: str, max_len: int = MAX_TOOL_OUTPUT_LEN) -> str:
    """截断过长文本，保留首尾。"""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n...[截断 {len(text) - max_len} 字符]...\n" + text[-half:]


def compact_messages(messages: list[dict], target_tokens: int = COMPACT_TARGET_TOKENS) -> list[dict]:
    """压缩对话上下文：将旧消息摘要化，保留最近消息。"""
    if len(messages) <= 5:
        return messages
    system_msg = messages[0] if messages[0].get("role") == "system" else None
    non_system = messages[1:] if system_msg else messages
    keep_recent = 8
    if len(non_system) <= keep_recent:
        return messages
    old_messages = non_system[:-keep_recent]
    recent_messages = non_system[-keep_recent:]

    conversation_text = ""
    for msg in old_messages:
        content = msg.get("content", "")
        if content:
            conversation_text += f"[{msg.get('role', '?')}]: {content[:500]}\n"
    try:
        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "将以下对话摘要为简洁要点，保留关键信息，200字以内。"},
                {"role": "user", "content": conversation_text[:3000]},
            ],
            max_tokens=300,
        )
        summary = resp.choices[0].message.content or "(摘要失败)"
    except Exception as e:
        summary = f"(摘要出错: {e})"

    result = []
    if system_msg:
        result.append(system_msg)
    result.append({"role": "user", "content": f"[之前对话摘要]\n{summary}\n[摘要结束]"})
    result.extend(recent_messages)
    return result


# ── Cron 调度器 ───────────────────────────────────────
def parse_interval(s: str) -> int:
    """解析间隔字符串为秒数。如 '5m' -> 300, '1h' -> 3600"""
    m = re.match(r"^(\d+)([smhd])$", s.strip())
    if not m:
        raise ValueError(f"无效间隔格式: {s}（示例: 30s, 5m, 1h, 1d）")
    value, unit = int(m.group(1)), m.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multiplier[unit]


def match_cron_field(field_expr: str, current: int) -> bool:
    """匹配单个 cron 字段。支持 *, */N, 具体数字。"""
    if field_expr == "*":
        return True
    if field_expr.startswith("*/"):
        step = int(field_expr[2:])
        return current % step == 0
    return current == int(field_expr)


def cron_matches(expr: str, dt: datetime) -> bool:
    """检查 5 字段 cron 表达式是否匹配当前时间。"""
    fields = expr.strip().split()
    if len(fields) != 5:
        return False
    minute, hour, day, month, weekday = fields
    return (
        match_cron_field(minute, dt.minute)
        and match_cron_field(hour, dt.hour)
        and match_cron_field(day, dt.day)
        and match_cron_field(month, dt.month)
        and match_cron_field(weekday, dt.weekday())
    )


@dataclass
class CronJob:
    """定时任务数据结构。"""
    id: str
    schedule_type: str   # cron / interval / once
    schedule_value: str  # cron 表达式 / 间隔 / ISO 时间
    prompt: str          # 要执行的任务描述
    chat_id: str         # 关联的会话 ID
    script: str = ""     # 可选的预检脚本
    status: str = "active"
    next_run: float = 0.0
    last_run: float = 0.0

    def compute_next_run(self) -> float:
        """计算下次执行时间戳。"""
        now = time.time()
        if self.schedule_type == "interval":
            interval_secs = parse_interval(self.schedule_value)
            base = self.last_run if self.last_run > 0 else now
            return base + interval_secs
        elif self.schedule_type == "once":
            dt = datetime.fromisoformat(self.schedule_value)
            return dt.timestamp()
        elif self.schedule_type == "cron":
            return now + 60
        return now + 60


class CronScheduler:
    """
    定时任务调度器。
    - 每 60 秒轮询一次
    - 执行到期任务
    - 支持脚本门控
    """

    def __init__(self, store: 'Store', bus: MessageBus):
        self.store = store
        self.bus = bus
        self.jobs: dict[str, CronJob] = {}
        self._running = False
        self._load_jobs()

    def _load_jobs(self):
        """从数据库加载活跃任务。"""
        rows = self.store.conn.execute(
            "SELECT * FROM cron_jobs WHERE status = 'active'"
        ).fetchall()
        for row in rows:
            job = CronJob(
                id=row["id"], schedule_type=row["schedule_type"],
                schedule_value=row["schedule_value"], prompt=row["prompt"],
                chat_id=row["chat_id"], script=row["script"] or "",
                status=row["status"], next_run=row["next_run"],
                last_run=row["last_run"] or 0,
            )
            self.jobs[job.id] = job

    def add_job(self, job: CronJob) -> str:
        """添加一个新任务。"""
        job.next_run = job.compute_next_run()
        self.jobs[job.id] = job
        self.store.conn.execute(
            "INSERT OR REPLACE INTO cron_jobs "
            "(id, schedule_type, schedule_value, prompt, chat_id, script, status, next_run, last_run) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job.id, job.schedule_type, job.schedule_value, job.prompt,
             job.chat_id, job.script, job.status, job.next_run, job.last_run),
        )
        self.store.conn.commit()
        next_time = datetime.fromtimestamp(job.next_run).strftime("%Y-%m-%d %H:%M:%S")
        return f"任务 {job.id} 已创建，下次执行: {next_time}"

    def remove_job(self, job_id: str) -> str:
        """删除一个任务。"""
        if job_id not in self.jobs:
            return f"任务不存在: {job_id}"
        del self.jobs[job_id]
        self.store.conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        self.store.conn.commit()
        return f"任务 {job_id} 已删除"

    def list_jobs(self) -> str:
        """列出所有活跃任务。"""
        if not self.jobs:
            return "没有定时任务"
        lines = []
        for job in self.jobs.values():
            next_time = datetime.fromtimestamp(job.next_run).strftime("%m-%d %H:%M")
            lines.append(
                f"  [{job.id}] {job.schedule_type}={job.schedule_value} "
                f"next={next_time} | {job.prompt[:40]}"
            )
        return "\n".join(lines)

    async def start(self):
        """启动调度循环。"""
        self._running = True
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            for job in list(self.jobs.values()):
                if job.status != "active" or job.next_run > now:
                    continue
                await self._execute_job(job)

    async def _execute_job(self, job: CronJob):
        """执行一个到期的定时任务。"""
        print(f"  ⏰ 执行定时任务 [{job.id}]: {job.prompt[:50]}")

        # 脚本门控
        if job.script:
            try:
                result = subprocess.run(
                    job.script, shell=True, capture_output=True, text=True, timeout=30
                )
                output = result.stdout.strip()
                if output:
                    try:
                        gate = json.loads(output)
                        if not gate.get("wakeAgent", True):
                            print(f"  ⏰ [{job.id}] 脚本门控: 不唤醒 Agent")
                            self._update_job_after_run(job)
                            return
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                print(f"  ⏰ [{job.id}] 脚本执行出错: {e}")

        await self.bus.inbound.put(InboundMessage(
            channel="cron",
            chat_id=job.chat_id,
            user_id="cron",
            text=f"[定时任务 {job.id}] {job.prompt}",
            sender_name="定时调度器",
        ))
        self._update_job_after_run(job)

    def _update_job_after_run(self, job: CronJob):
        """更新任务执行状态。"""
        job.last_run = time.time()
        if job.schedule_type == "once":
            job.status = "completed"
            self.store.conn.execute(
                "UPDATE cron_jobs SET status = 'completed', last_run = ? WHERE id = ?",
                (job.last_run, job.id),
            )
            del self.jobs[job.id]
        else:
            job.next_run = job.compute_next_run()
            self.store.conn.execute(
                "UPDATE cron_jobs SET next_run = ?, last_run = ? WHERE id = ?",
                (job.next_run, job.last_run, job.id),
            )
        self.store.conn.commit()

    def stop(self):
        """停止调度器。"""
        self._running = False


# ── SQLite 存储层 ─────────────────────────────────────
class Store:
    """SQLite 持久化存储：消息、会话、定时任务。"""

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
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                schedule_type TEXT NOT NULL,
                schedule_value TEXT NOT NULL,
                prompt TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                script TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                next_run REAL DEFAULT 0,
                last_run REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_cron_status ON cron_jobs(status, next_run);
        """)
        self.conn.commit()

    def save_message(self, chat_id: str, role: str, content: str | None = None,
                     tool_calls: str | None = None, tool_call_id: str | None = None):
        """保存一条消息到数据库。"""
        self.conn.execute(
            "INSERT INTO messages (chat_id, role, content, tool_calls, tool_call_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, tool_calls, tool_call_id, time.time()),
        )
        self.conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        """获取最近的 N 条消息。"""
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
        """搜索包含关键词的消息。"""
        rows = self.conn.execute(
            "SELECT chat_id, role, content, timestamp FROM messages "
            "WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self):
        """关闭数据库连接。"""
        self.conn.close()


# ── MEMORY.md 记忆管理 ────────────────────────────────
class MemoryManager:
    """基于 Markdown 文件的长期记忆管理器。"""

    def __init__(self, memory_path: Path):
        self.path = memory_path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("# TinyClaw 记忆\n\n", encoding="utf-8")

    def read(self) -> str:
        """读取全部记忆。"""
        return self.path.read_text(encoding="utf-8")

    def append(self, entry: str) -> str:
        """追加一条记忆。"""
        content = self.read()
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        content += f"\n## [{timestamp}]\n{entry}\n"
        self.path.write_text(content, encoding="utf-8")
        return f"已保存记忆 ({len(entry)} 字符)"

    def search(self, query: str) -> str:
        """搜索记忆中的关键词。"""
        content = self.read()
        lines = content.split("\n")
        matches = [l for l in lines if query.lower() in l.lower()]
        return "\n".join(matches[:20]) if matches else f"未找到与 '{query}' 相关的记忆"


# ── Channel 抽象 ──────────────────────────────────────
class Channel(abc.ABC):
    """通道抽象基类：定义消息输入/输出接口。"""

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
    """命令行交互通道。"""

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
        """异步读取用户输入。"""
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


# ── Docker 沙盒 ───────────────────────────────────────
class DockerSandbox:
    """
    Docker 沙盒执行器。
    在隔离容器中执行不可信代码，限制网络、内存和时间。
    """

    def __init__(self, image: str = DOCKER_IMAGE, timeout: int = DOCKER_TIMEOUT):
        self.image = image
        self.timeout = timeout
        self._available: bool | None = None

    def is_available(self) -> bool:
        """检查 Docker 是否可用。"""
        if self._available is None:
            try:
                result = subprocess.run(
                    ["docker", "info"], capture_output=True, text=True, timeout=5,
                )
                self._available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._available = False
        return self._available

    def execute(self, code: str, language: str = "python") -> str:
        """在 Docker 容器中执行代码。"""
        if not self.is_available():
            return "(Docker 不可用，无法执行沙盒代码)"

        # 根据语言选择命令
        if language == "python":
            cmd_in_container = ["python3", "-c", code]
        elif language == "bash":
            cmd_in_container = ["bash", "-c", code]
        else:
            return f"不支持的语言: {language}"

        docker_cmd = [
            "docker", "run", "--rm",
            "--network=none",              # 禁用网络
            "--memory=128m",               # 内存限制
            "--cpus=0.5",                  # CPU 限制
            "--pids-limit=64",             # 进程数限制
            "--read-only",                 # 只读文件系统
            "--tmpfs=/tmp:rw,size=64m",    # 可写 /tmp
            self.image,
        ] + cmd_in_container

        try:
            result = subprocess.run(
                docker_cmd, capture_output=True, text=True, timeout=self.timeout,
            )
            output = result.stdout + result.stderr
            return micro_compact(output) if output.strip() else "(无输出)"
        except subprocess.TimeoutExpired:
            return f"(沙盒执行超时 {self.timeout}s)"
        except Exception as e:
            return f"(沙盒执行出错: {e})"


# ── Policy Engine（策略引擎）──────────────────────────
@dataclass
class PolicyRule:
    """策略规则：定义哪些操作被允许或拒绝。"""
    id: str
    action: str       # allow / deny / sandbox
    resource: str     # 匹配的资源模式（工具名 / 路径模式）
    condition: str    # 条件表达式（简单字符串匹配）
    priority: int = 0 # 优先级，数字越大优先级越高
    description: str = ""


class PolicyEngine:
    """
    策略引擎：在工具执行前检查权限。
    规则按优先级排序，第一个匹配的规则生效。
    """

    def __init__(self):
        self.rules: list[PolicyRule] = []
        self._load_default_rules()

    def _load_default_rules(self):
        """加载默认安全策略。"""
        self.rules = [
            # 禁止删除根目录
            PolicyRule(
                id="deny-rm-rf", action="deny", resource="bash",
                condition="rm -rf /", priority=100,
                description="禁止删除根目录",
            ),
            # 危险命令沙盒化
            PolicyRule(
                id="sandbox-curl", action="sandbox", resource="bash",
                condition="curl ", priority=50,
                description="curl 命令在沙盒中执行",
            ),
            PolicyRule(
                id="sandbox-wget", action="sandbox", resource="bash",
                condition="wget ", priority=50,
                description="wget 命令在沙盒中执行",
            ),
            # 默认允许
            PolicyRule(
                id="allow-all", action="allow", resource="*",
                condition="", priority=0,
                description="默认允许所有操作",
            ),
        ]
        # 按优先级降序排序
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def add_rule(self, rule: PolicyRule):
        """添加一条新规则。"""
        self.rules.append(rule)
        self.rules.sort(key=lambda r: r.priority, reverse=True)

    def check(self, tool_name: str, arguments: dict) -> tuple[str, str]:
        """
        检查工具调用是否被允许。
        返回: (action, reason)
        action: "allow" / "deny" / "sandbox"
        """
        # 构建用于匹配的字符串
        args_str = json.dumps(arguments, ensure_ascii=False)

        for rule in self.rules:
            # 检查资源匹配
            if rule.resource != "*" and rule.resource != tool_name:
                continue
            # 检查条件匹配
            if rule.condition and rule.condition not in args_str:
                continue
            # 匹配成功
            return rule.action, rule.description

        return "allow", "无匹配规则，默认允许"

    def list_rules(self) -> str:
        """列出所有策略规则。"""
        if not self.rules:
            return "没有策略规则"
        lines = []
        for r in self.rules:
            lines.append(
                f"  [{r.id}] {r.action} | resource={r.resource} | "
                f"priority={r.priority} | {r.description}"
            )
        return "\n".join(lines)


# ── MCP 客户端 ────────────────────────────────────────
class MCPClient:
    """
    MCP (Model Context Protocol) 客户端。
    通过 stdio 与 MCP 服务器通信，获取工具列表并执行工具。
    使用 JSON-RPC 2.0 协议。
    """

    def __init__(self, server_id: str, command: str, args: list[str],
                 env: dict[str, str] | None = None):
        self.server_id = server_id
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []
        self._running = False

    def _next_id(self) -> int:
        """线程安全的请求 ID 生成。"""
        with self._lock:
            self._request_id += 1
            return self._request_id

    def start(self) -> bool:
        """启动 MCP 服务器进程。"""
        try:
            env = {**os.environ, **self.env}
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )
            self._running = True
            # 发送 initialize 请求
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TinyClaw", "version": "0.12"},
            })
            if result is None:
                print(f"  ⚠ MCP 服务器 {self.server_id} 初始化失败")
                self.stop()
                return False
            # 发送 initialized 通知
            self._send_notification("notifications/initialized", {})
            print(f"  ✓ MCP 服务器 {self.server_id} 已启动")
            return True
        except Exception as e:
            print(f"  ✗ MCP 服务器 {self.server_id} 启动失败: {e}")
            return False

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> dict | None:
        """发送 JSON-RPC 请求并等待响应。"""
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None
        req_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        try:
            line = json.dumps(request) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()
            # 读取响应
            response_line = self.process.stdout.readline()
            if not response_line:
                return None
            response = json.loads(response_line.strip())
            if "error" in response:
                print(f"  ⚠ MCP RPC 错误: {response['error']}")
                return None
            return response.get("result", {})
        except Exception as e:
            print(f"  ⚠ MCP 请求失败 ({method}): {e}")
            return None

    def _send_notification(self, method: str, params: dict):
        """发送 JSON-RPC 通知（无需响应）。"""
        if not self.process or not self.process.stdin:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            line = json.dumps(notification) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()
        except Exception:
            pass

    def list_tools(self) -> list[dict]:
        """获取 MCP 服务器提供的工具列表。"""
        result = self._send_request("tools/list", {})
        if result and "tools" in result:
            self.tools = result["tools"]
            return self.tools
        return []

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """调用 MCP 服务器上的工具。"""
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result is None:
            return f"MCP 工具调用失败: {tool_name}"
        # 提取结果文本
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", str(c)) for c in content if isinstance(c, dict)]
            return "\n".join(texts) if texts else json.dumps(result)
        return str(content)

    def stop(self):
        """停止 MCP 服务器进程。"""
        self._running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None


class MCPManager:
    """
    MCP 服务器管理器。
    从配置文件加载 MCP 服务器，管理生命周期，注册工具。
    """

    def __init__(self, config_path: Path = MCP_CONFIG_PATH):
        self.config_path = config_path
        self.clients: dict[str, MCPClient] = {}

    def load_config(self) -> dict:
        """加载 MCP 配置文件。"""
        if not self.config_path.exists():
            return {}
        try:
            content = self.config_path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"  ⚠ MCP 配置加载失败: {e}")
            return {}

    def start_all(self):
        """启动所有配置的 MCP 服务器。"""
        config = self.load_config()
        servers = config.get("mcpServers", {})
        for server_id, server_conf in servers.items():
            command = server_conf.get("command", "")
            args = server_conf.get("args", [])
            env = server_conf.get("env", {})
            if not command:
                continue
            client = MCPClient(server_id, command, args, env)
            if client.start():
                self.clients[server_id] = client
                # 获取并注册工具
                tools = client.list_tools()
                for t in tools:
                    self._register_mcp_tool(server_id, client, t)
                print(f"  ✓ MCP {server_id}: 注册了 {len(tools)} 个工具")

    def _register_mcp_tool(self, server_id: str, client: MCPClient, tool_def: dict):
        """将 MCP 工具注册到全局工具注册表。"""
        original_name = tool_def.get("name", "")
        tool_name = f"mcp_{server_id}_{original_name}"
        description = tool_def.get("description", f"MCP 工具: {original_name}")
        input_schema = tool_def.get("inputSchema", {
            "type": "object", "properties": {}, "required": [],
        })

        def make_caller(c: MCPClient, name: str):
            def caller(**kwargs) -> str:
                return c.call_tool(name, kwargs)
            return caller

        _TOOL_REGISTRY[tool_name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": f"[MCP:{server_id}] {description}",
                    "parameters": input_schema,
                },
            },
            "func": make_caller(client, original_name),
        }

    def stop_all(self):
        """停止所有 MCP 服务器。"""
        for client in self.clients.values():
            client.stop()
        self.clients.clear()


# ── 钩子系统 ─────────────────────────────────────────
# 定义 6 个钩子点
HOOK_POINTS = [
    "before_system_prompt",   # 构建系统提示词之前
    "after_system_prompt",    # 构建系统提示词之后
    "before_model_call",      # 调用模型之前
    "after_model_call",       # 调用模型之后
    "before_tool_call",       # 执行工具之前
    "after_tool_call",        # 执行工具之后
]


class HookSystem:
    """
    钩子系统：在 Agent 生命周期的关键节点触发钩子。
    钩子处理器可以是本地函数，也可以是插件提供的远程钩子。
    """

    def __init__(self):
        # 每个钩子点对应一个处理器列表
        self._hooks: dict[str, list[callable]] = {hp: [] for hp in HOOK_POINTS}

    def register(self, hook_point: str, handler: callable):
        """注册一个钩子处理器。"""
        if hook_point not in self._hooks:
            print(f"  ⚠ 未知钩子点: {hook_point}，可用: {', '.join(HOOK_POINTS)}")
            return
        self._hooks[hook_point].append(handler)

    def unregister(self, hook_point: str, handler: callable):
        """取消注册一个钩子处理器。"""
        if hook_point in self._hooks and handler in self._hooks[hook_point]:
            self._hooks[hook_point].remove(handler)

    def fire(self, hook_point: str, data: dict) -> dict:
        """
        触发指定钩子点的所有处理器。
        处理器可以修改 data 并返回，链式传递。
        """
        if hook_point not in self._hooks:
            return data
        for handler in self._hooks[hook_point]:
            try:
                result = handler(hook_point, data)
                if isinstance(result, dict):
                    data = result
            except Exception as e:
                print(f"  ⚠ 钩子处理器出错 ({hook_point}): {e}")
        return data

    def list_hooks(self) -> str:
        """列出所有已注册的钩子。"""
        lines = []
        for hp in HOOK_POINTS:
            handlers = self._hooks.get(hp, [])
            count = len(handlers)
            lines.append(f"  {hp}: {count} 个处理器")
        return "\n".join(lines)


# ── JSON-RPC 2.0 辅助函数 ────────────────────────────
def make_jsonrpc_request(method: str, params: dict, req_id: int) -> str:
    """构造 JSON-RPC 2.0 请求字符串。"""
    request = {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": params,
    }
    return json.dumps(request, ensure_ascii=False)


def make_jsonrpc_notification(method: str, params: dict) -> str:
    """构造 JSON-RPC 2.0 通知字符串（无 id）。"""
    notification = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
    }
    return json.dumps(notification, ensure_ascii=False)


def parse_jsonrpc_response(line: str) -> dict | None:
    """解析 JSON-RPC 2.0 响应。返回 result 或 error 字典。"""
    try:
        data = json.loads(line.strip())
    except json.JSONDecodeError:
        return None
    if "jsonrpc" not in data or data["jsonrpc"] != "2.0":
        return None
    return data


# ── PluginProcess（插件子进程管理）────────────────────
class PluginProcess:
    """
    管理一个插件子进程。
    通过 stdin/stdout 使用 JSON-RPC 2.0 协议通信。
    """

    def __init__(self, plugin_id: str, command: str, args: list[str],
                 working_dir: str | None = None, env: dict[str, str] | None = None):
        self.plugin_id = plugin_id
        self.command = command
        self.args = args
        self.working_dir = working_dir
        self.env = env or {}
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._running = False
        self._notification_handlers: dict[str, callable] = {}
        self._reader_thread: threading.Thread | None = None
        self._pending_responses: dict[int, threading.Event] = {}
        self._response_data: dict[int, dict] = {}
        self._pending_lock = threading.Lock()

    def _next_id(self) -> int:
        """线程安全的自增请求 ID。"""
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def start(self) -> bool:
        """启动插件子进程。"""
        try:
            env = {**os.environ, **self.env}
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
                cwd=self.working_dir,
            )
            self._running = True
            # 启动后台读取线程，处理异步通知
            self._reader_thread = threading.Thread(
                target=self._read_loop, daemon=True, name=f"plugin-{self.plugin_id}-reader"
            )
            self._reader_thread.start()
            return True
        except Exception as e:
            print(f"  ✗ 插件 {self.plugin_id} 启动失败: {e}")
            return False

    def _read_loop(self):
        """后台线程：持续从 stdout 读取数据，分发响应和通知。"""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    # 进程已关闭 stdout
                    break
                line = line.strip()
                if not line:
                    continue
                data = parse_jsonrpc_response(line)
                if data is None:
                    continue

                if "id" in data and data["id"] is not None:
                    # 这是对我们请求的响应
                    req_id = data["id"]
                    with self._pending_lock:
                        if req_id in self._pending_responses:
                            self._response_data[req_id] = data
                            self._pending_responses[req_id].set()
                elif "method" in data:
                    # 这是插件发来的通知
                    method = data["method"]
                    params = data.get("params", {})
                    handler = self._notification_handlers.get(method)
                    if handler:
                        try:
                            handler(method, params)
                        except Exception as e:
                            print(f"  ⚠ 插件 {self.plugin_id} 通知处理出错 ({method}): {e}")
            except Exception:
                if self._running:
                    break

    def on_notification(self, method: str, handler: callable):
        """注册通知处理器。"""
        self._notification_handlers[method] = handler

    def call(self, method: str, params: dict, timeout: float = 10.0) -> dict | None:
        """
        发送 JSON-RPC 请求并阻塞等待响应。
        返回 result 字典，或者出错返回 None。
        """
        if not self.process or not self.process.stdin:
            return None

        req_id = self._next_id()
        event = threading.Event()
        with self._pending_lock:
            self._pending_responses[req_id] = event

        # 发送请求
        request_str = make_jsonrpc_request(method, params, req_id) + "\n"
        try:
            with self._io_lock:
                self.process.stdin.write(request_str)
                self.process.stdin.flush()
        except Exception as e:
            with self._pending_lock:
                self._pending_responses.pop(req_id, None)
            print(f"  ⚠ 插件 {self.plugin_id} 发送请求失败: {e}")
            return None

        # 等待响应
        if not event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending_responses.pop(req_id, None)
            print(f"  ⚠ 插件 {self.plugin_id} 请求超时 ({method})")
            return None

        # 获取响应
        with self._pending_lock:
            self._pending_responses.pop(req_id, None)
            data = self._response_data.pop(req_id, None)

        if data is None:
            return None
        if "error" in data:
            error = data["error"]
            print(f"  ⚠ 插件 {self.plugin_id} RPC 错误: {error}")
            return None
        return data.get("result", {})

    def send_notification(self, method: str, params: dict):
        """发送通知（fire and forget，不等待响应）。"""
        if not self.process or not self.process.stdin:
            return
        notification_str = make_jsonrpc_notification(method, params) + "\n"
        try:
            with self._io_lock:
                self.process.stdin.write(notification_str)
                self.process.stdin.flush()
        except Exception:
            pass

    def shutdown(self, timeout: float = 5.0):
        """
        优雅关闭插件进程。
        1. 发送 shutdown RPC 请求
        2. 关闭 stdin
        3. 等待进程退出
        4. 超时则强制 kill
        """
        self._running = False
        if not self.process:
            return

        # 尝试发送 shutdown 请求
        try:
            req_id = self._next_id()
            request_str = make_jsonrpc_request("shutdown", {}, req_id) + "\n"
            if self.process.stdin:
                self.process.stdin.write(request_str)
                self.process.stdin.flush()
        except Exception:
            pass

        # 关闭 stdin
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass

        # 等待进程退出
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"  ⚠ 插件 {self.plugin_id} 未及时退出，强制终止")
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except Exception:
                pass

        self.process = None

    @property
    def is_running(self) -> bool:
        """检查插件进程是否仍在运行。"""
        if not self.process:
            return False
        return self.process.poll() is None


# ── 插件 Channel 适配器 ──────────────────────────────
class PluginChannel(Channel):
    """
    将 channel 类型的插件适配为 Channel 接口。
    接收插件发来的 message.inbound 通知，转发到 MessageBus。
    """

    def __init__(self, plugin_id: str, plugin_process: PluginProcess):
        self._plugin_id = plugin_id
        self._plugin = plugin_process
        self._bus: MessageBus | None = None
        self._running = False

    @property
    def name(self) -> str:
        return f"plugin_{self._plugin_id}"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线，注册通知处理器。"""
        self._bus = bus
        self._running = True
        # 注册通知处理器：当插件发来 message.inbound 通知时
        self._plugin.on_notification("message.inbound", self._handle_inbound)
        # 通知插件开始监听
        self._plugin.send_notification("channel.start", {})

    def _handle_inbound(self, method: str, params: dict):
        """处理插件发来的入站消息通知。"""
        if not self._bus or not self._running:
            return
        msg = InboundMessage(
            channel=self.name,
            chat_id=params.get("chat_id", "default"),
            user_id=params.get("user_id", "unknown"),
            text=params.get("text", ""),
            sender_name=params.get("sender_name", ""),
        )
        # 在事件循环中放入队列（从非异步线程调用）
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._bus.inbound.put(msg), loop)
            else:
                self._bus.inbound.put_nowait(msg)
        except Exception as e:
            print(f"  ⚠ 插件 Channel {self._plugin_id} 入站消息处理失败: {e}")

    async def disconnect(self) -> None:
        """断开连接。"""
        self._running = False
        self._plugin.send_notification("channel.stop", {})

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """通过插件发送出站消息。"""
        self._plugin.call("channel.send", {
            "chat_id": chat_id,
            "text": text,
            "reply_to": reply_to,
        })


# ── PluginManager（插件管理器）────────────────────────
@dataclass
class PluginManifest:
    """插件清单：plugin.json 的数据结构。"""
    id: str
    name: str
    version: str
    type: str          # tool / channel / hook
    command: str
    args: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


class PluginManager:
    """
    插件管理器：发现、加载、管理插件生命周期。
    - 扫描 PLUGINS_DIR 下的 plugin.json 清单
    - 启动已启用的插件
    - 根据插件类型注册工具 / 通道 / 钩子
    """

    def __init__(self, plugins_dir: Path = PLUGINS_DIR, hook_system: HookSystem | None = None):
        self.plugins_dir = plugins_dir
        self.hook_system = hook_system or HookSystem()
        self._manifests: dict[str, PluginManifest] = {}
        self._processes: dict[str, PluginProcess] = {}
        self._channels: dict[str, PluginChannel] = {}
        self._lock = threading.Lock()

    def discover(self) -> list[PluginManifest]:
        """扫描插件目录，发现所有插件清单。"""
        manifests = []
        if not self.plugins_dir.exists():
            print(f"  ℹ 插件目录不存在: {self.plugins_dir}")
            return manifests

        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            manifest_file = plugin_dir / "plugin.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest = PluginManifest(
                    id=data.get("id", plugin_dir.name),
                    name=data.get("name", plugin_dir.name),
                    version=data.get("version", "0.0.0"),
                    type=data.get("type", "tool"),
                    command=data.get("command", ""),
                    args=data.get("args", []),
                    config=data.get("config", {}),
                    enabled=data.get("enabled", True),
                    description=data.get("description", ""),
                )
                manifests.append(manifest)
                self._manifests[manifest.id] = manifest
                print(f"  ✓ 发现插件: {manifest.name} v{manifest.version} ({manifest.type})")
            except Exception as e:
                print(f"  ⚠ 加载插件清单失败 ({plugin_dir.name}): {e}")

        return manifests

    def start_all(self) -> list[str]:
        """启动所有已发现且已启用的插件。"""
        started = []
        for pid, manifest in self._manifests.items():
            if not manifest.enabled:
                print(f"  ℹ 插件 {manifest.name} 已禁用，跳过")
                continue
            if not manifest.command:
                print(f"  ⚠ 插件 {manifest.name} 缺少 command 配置")
                continue
            success = self._start_plugin(manifest)
            if success:
                started.append(pid)
        return started

    def _start_plugin(self, manifest: PluginManifest) -> bool:
        """启动单个插件。"""
        plugin_dir = self.plugins_dir / manifest.id
        process = PluginProcess(
            plugin_id=manifest.id,
            command=manifest.command,
            args=manifest.args,
            working_dir=str(plugin_dir),
        )

        if not process.start():
            return False

        # 发送 initialize 请求
        result = process.call("initialize", {
            "plugin_id": manifest.id,
            "config": manifest.config,
        })
        if result is None:
            print(f"  ⚠ 插件 {manifest.name} 初始化失败")
            process.shutdown()
            return False

        with self._lock:
            self._processes[manifest.id] = process

        print(f"  ✓ 插件 {manifest.name} 已启动并初始化")

        # 根据插件类型进行注册
        if manifest.type == "tool":
            self._register_tool_plugin(manifest, process)
        elif manifest.type == "channel":
            self._register_channel_plugin(manifest, process)
        elif manifest.type == "hook":
            self._register_hook_plugin(manifest, process)
        else:
            print(f"  ⚠ 未知插件类型: {manifest.type}")

        return True

    def _register_tool_plugin(self, manifest: PluginManifest, process: PluginProcess):
        """注册 tool 类型插件：获取工具列表，注册到全局工具注册表。"""
        result = process.call("tool.list", {})
        if result is None:
            print(f"  ⚠ 插件 {manifest.name} 获取工具列表失败")
            return

        tools = result.get("tools", [])
        for tool_def in tools:
            original_name = tool_def.get("name", "")
            if not original_name:
                continue
            # 工具名称加前缀: plugin_{id}_{name}
            tool_name = f"plugin_{manifest.id}_{original_name}"
            description = tool_def.get("description", f"插件工具: {original_name}")
            parameters = tool_def.get("parameters", {
                "type": "object", "properties": {}, "required": [],
            })

            # 创建工具执行闭包
            def make_plugin_tool_caller(proc: PluginProcess, tname: str):
                def caller(**kwargs) -> str:
                    res = proc.call("tool.execute", {
                        "name": tname,
                        "arguments": kwargs,
                    })
                    if res is None:
                        return f"插件工具执行失败: {tname}"
                    return res.get("result", str(res))
                return caller

            _TOOL_REGISTRY[tool_name] = {
                "schema": {
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "description": f"[插件:{manifest.id}] {description}",
                        "parameters": parameters,
                    },
                },
                "func": make_plugin_tool_caller(process, original_name),
            }
            print(f"    ✓ 注册插件工具: {tool_name}")

        print(f"  ✓ 插件 {manifest.name}: 注册了 {len(tools)} 个工具")

    def _register_channel_plugin(self, manifest: PluginManifest, process: PluginProcess):
        """注册 channel 类型插件：适配为 Channel 接口。"""
        channel = PluginChannel(manifest.id, process)
        with self._lock:
            self._channels[manifest.id] = channel
        print(f"  ✓ 插件 {manifest.name}: 已注册为 Channel")

    def _register_hook_plugin(self, manifest: PluginManifest, process: PluginProcess):
        """注册 hook 类型插件：在各钩子点注册处理器。"""
        # 查询插件支持哪些钩子点
        result = process.call("hook.list", {})
        if result is None:
            # 默认注册所有钩子点
            hook_points = HOOK_POINTS
        else:
            hook_points = result.get("hooks", HOOK_POINTS)

        def make_hook_handler(proc: PluginProcess, plugin_name: str):
            def handler(hook_point: str, data: dict) -> dict:
                res = proc.call("hook.fire", {
                    "hook_point": hook_point,
                    "data": data,
                }, timeout=5.0)
                if res is not None and isinstance(res, dict):
                    return res.get("data", data)
                return data
            return handler

        handler = make_hook_handler(process, manifest.name)
        for hp in hook_points:
            if hp in HOOK_POINTS:
                self.hook_system.register(hp, handler)
        print(f"  ✓ 插件 {manifest.name}: 注册了 {len(hook_points)} 个钩子")

    def get_channels(self) -> list[PluginChannel]:
        """获取所有已注册的 Channel 插件。"""
        with self._lock:
            return list(self._channels.values())

    def get_plugin_info(self) -> str:
        """获取所有插件的状态信息。"""
        if not self._manifests:
            return "没有已加载的插件"
        lines = []
        for pid, manifest in self._manifests.items():
            status = "运行中" if pid in self._processes and self._processes[pid].is_running else "已停止"
            lines.append(
                f"  [{pid}] {manifest.name} v{manifest.version} "
                f"| 类型={manifest.type} | 状态={status}"
            )
        return "\n".join(lines)

    def stop_all(self):
        """停止所有插件进程。"""
        with self._lock:
            for pid, process in self._processes.items():
                print(f"  ℹ 正在停止插件: {pid}")
                process.shutdown()
            self._processes.clear()
            self._channels.clear()
        print("  ✓ 所有插件已停止")


# ── 工具注册表 ────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str, parameters: dict):
    """工具注册装饰器。"""
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
    """获取所有工具的 JSON Schema。"""
    return [t["schema"] for t in _TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict, depth: int = 0) -> str:
    """执行指定工具。"""
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
    """安全路径检查：防止目录遍历。"""
    resolved = (WORKDIR / filepath).resolve()
    if not str(resolved).startswith(str(WORKDIR)):
        raise PermissionError(f"路径越界: {filepath}")
    return resolved


# ── Skills ────────────────────────────────────────────
def parse_skill_md(content: str) -> dict:
    """解析 SKILL.md 文件：提取 YAML 头部元数据和正文。"""
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
    """加载所有技能的摘要信息。"""
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
    """构建技能提示文本。"""
    if not summaries:
        return ""
    lines = ["\n可用技能（使用 load_skill 获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)


# ── 初始化全局组件 ────────────────────────────────────
store = Store(DATA_DIR / "tinyclaw.db")
memory_mgr = MemoryManager(WORKDIR / "workspace" / "MEMORY.md")
docker_sandbox = DockerSandbox()
policy_engine = PolicyEngine()
hook_system = HookSystem()
mcp_manager = MCPManager()
plugin_manager = PluginManager(hook_system=hook_system)
_scheduler: CronScheduler | None = None


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。策略引擎会检查命令安全性。", {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    # 策略引擎检查
    action, reason = policy_engine.check("bash", {"command": command})
    if action == "deny":
        return f"策略拒绝: {reason}"
    if action == "sandbox":
        print(f"  🔒 策略引擎: 沙盒执行 — {reason}")
        return docker_sandbox.execute(command, language="bash")
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
            db_text += f"[{r['role']}] {(r['content'] or '')[:100]}\n"
    return file_results + db_text


@tool("compact", "手动压缩当前对话上下文。", {
    "type": "object", "properties": {}, "required": [],
})
def compact() -> str:
    return "__COMPACT__"


@tool("create_cron", "创建定时任务。", {
    "type": "object",
    "properties": {
        "schedule_type": {
            "type": "string",
            "enum": ["cron", "interval", "once"],
            "description": "调度类型",
        },
        "schedule_value": {
            "type": "string",
            "description": "cron: '0 9 * * *', interval: '5m', once: '2024-12-25 09:00'",
        },
        "prompt": {"type": "string", "description": "要执行的任务描述"},
        "script": {"type": "string", "description": "可选的预检 bash 脚本", "default": ""},
    },
    "required": ["schedule_type", "schedule_value", "prompt"],
})
def create_cron(schedule_type: str, schedule_value: str, prompt: str, script: str = "") -> str:
    if not _scheduler:
        return "调度器未初始化"
    job = CronJob(
        id=uuid.uuid4().hex[:8],
        schedule_type=schedule_type,
        schedule_value=schedule_value,
        prompt=prompt,
        chat_id="cli-main",
        script=script,
    )
    return _scheduler.add_job(job)


@tool("list_crons", "列出所有定时任务。", {
    "type": "object", "properties": {}, "required": [],
})
def list_crons() -> str:
    if not _scheduler:
        return "调度器未初始化"
    return _scheduler.list_jobs()


@tool("delete_cron", "删除定时任务。", {
    "type": "object",
    "properties": {"job_id": {"type": "string", "description": "任务 ID"}},
    "required": ["job_id"],
})
def delete_cron(job_id: str) -> str:
    if not _scheduler:
        return "调度器未初始化"
    return _scheduler.remove_job(job_id)


@tool("sandbox_exec", "在 Docker 沙盒中执行代码。", {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "要执行的代码"},
        "language": {"type": "string", "enum": ["python", "bash"], "default": "python"},
    },
    "required": ["code"],
})
def sandbox_exec(code: str, language: str = "python") -> str:
    return docker_sandbox.execute(code, language)


@tool("list_policies", "列出当前安全策略规则。", {
    "type": "object", "properties": {}, "required": [],
})
def list_policies() -> str:
    return policy_engine.list_rules()


@tool("list_plugins", "列出所有已加载的插件及其状态。", {
    "type": "object", "properties": {}, "required": [],
})
def list_plugins() -> str:
    return plugin_manager.get_plugin_info()


@tool("list_hooks", "列出所有已注册的钩子处理器。", {
    "type": "object", "properties": {}, "required": [],
})
def list_hooks() -> str:
    return hook_system.list_hooks()


# ── Agent 处理器 ──────────────────────────────────────
def run_agent(user_message: str, chat_id: str = "default") -> str:
    """
    Agent 主循环：接收用户消息，调用 LLM，执行工具，返回回复。
    现在集成了钩子系统，在关键节点触发钩子。
    """
    # ── before_system_prompt 钩子 ──
    hook_data = hook_system.fire("before_system_prompt", {
        "user_message": user_message,
        "chat_id": chat_id,
    })

    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)
    memory_content = memory_mgr.read()
    memory_prompt = ""
    if memory_content.strip() and memory_content.strip() != "# TinyClaw 记忆":
        memory_prompt = f"\n\n你的长期记忆：\n{memory_content[:2000]}"

    # 插件信息提示
    plugin_info = plugin_manager.get_plugin_info()
    plugin_prompt = ""
    if plugin_info and plugin_info != "没有已加载的插件":
        plugin_prompt = f"\n\n已加载的插件：\n{plugin_info}"

    system_prompt = (
        "你是 TinyClaw，一个支持插件扩展的 AI 助手。\n"
        "你可以执行命令、操作文件、加载技能、委派子 Agent、管理定时任务、"
        "在沙盒中执行代码、查看安全策略、管理插件。\n"
        f"工作目录: {WORKDIR}"
        f"{skills_prompt}{memory_prompt}{plugin_prompt}"
    )

    # ── after_system_prompt 钩子 ──
    hook_data = hook_system.fire("after_system_prompt", {
        "system_prompt": system_prompt,
        "user_message": user_message,
        "chat_id": chat_id,
    })
    system_prompt = hook_data.get("system_prompt", system_prompt)

    history = store.get_recent_messages(chat_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    store.save_message(chat_id, "user", user_message)

    tools = get_tool_schemas()

    while True:
        token_count = messages_token_count(messages)
        if token_count > MAX_TOKENS:
            messages = compact_messages(messages, COMPACT_TARGET_TOKENS)

        # ── before_model_call 钩子 ──
        hook_data = hook_system.fire("before_model_call", {
            "messages": messages,
            "tools": tools,
            "model": MODEL,
        })

        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        # ── after_model_call 钩子 ──
        hook_data = hook_system.fire("after_model_call", {
            "response": {
                "content": assistant_msg.content,
                "has_tool_calls": bool(assistant_msg.tool_calls),
            },
        })

        if not assistant_msg.tool_calls:
            reply = assistant_msg.content or ""
            store.save_message(chat_id, "assistant", reply)
            return reply

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"  ⚙ {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")

            # ── before_tool_call 钩子 ──
            hook_data = hook_system.fire("before_tool_call", {
                "tool_name": fn_name,
                "arguments": fn_args,
            })
            # 钩子可以修改参数
            fn_name = hook_data.get("tool_name", fn_name)
            fn_args = hook_data.get("arguments", fn_args)

            # 策略引擎检查（对非 bash 工具也进行检查）
            action, reason = policy_engine.check(fn_name, fn_args)
            if action == "deny":
                result = f"策略拒绝: {reason}"
            else:
                result = execute_tool(fn_name, fn_args, depth=0)

            if result == "__COMPACT__":
                messages = compact_messages(messages, COMPACT_TARGET_TOKENS)
                result = "上下文已压缩。"

            # ── after_tool_call 钩子 ──
            hook_data = hook_system.fire("after_tool_call", {
                "tool_name": fn_name,
                "arguments": fn_args,
                "result": result,
            })
            result = hook_data.get("result", result)

            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            store.save_message(chat_id, "tool", result, tool_call_id=tc.id)


# ── Gateway ───────────────────────────────────────────
class Gateway:
    """
    网关：连接所有 Channel，处理消息路由。
    整合了 CronScheduler 和 PluginManager。
    """

    def __init__(self, bus: MessageBus, channels: list[Channel],
                 scheduler: CronScheduler, plugin_mgr: PluginManager):
        self.bus = bus
        self.channels = {ch.name: ch for ch in channels}
        self.scheduler = scheduler
        self.plugin_mgr = plugin_mgr
        self._running = False

    async def start(self):
        """启动网关：连接所有通道，启动调度器。"""
        for ch in self.channels.values():
            await ch.connect(self.bus)
        self._running = True
        await asyncio.gather(
            self._process_inbound(),
            self._route_outbound(),
            self.scheduler.start(),
        )

    async def _process_inbound(self):
        """处理入站消息：调用 Agent 并生成回复。"""
        while self._running:
            msg = await self.bus.inbound.get()
            if msg.text == "__QUIT__":
                self._running = False
                self.scheduler.stop()
                return
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(None, run_agent, msg.text, msg.chat_id)
            await self.bus.outbound.put(OutboundMessage(
                channel=msg.channel, chat_id=msg.chat_id,
                text=reply_text, reply_to=msg.message_id,
            ))

    async def _route_outbound(self):
        """路由出站消息到对应 Channel。"""
        while self._running:
            msg = await self.bus.outbound.get()
            ch = self.channels.get(msg.channel)
            if ch:
                await ch.send_message(msg.chat_id, msg.text, msg.reply_to)
            elif msg.channel == "cron":
                print(f"\n⏰ [定时任务回复] {msg.text[:200]}")
            else:
                # 尝试在插件 Channel 中查找
                print(f"\n📨 [{msg.channel}] {msg.text[:200]}")

    async def stop(self):
        """停止网关和所有组件。"""
        self._running = False
        self.scheduler.stop()
        self.plugin_mgr.stop_all()
        mcp_manager.stop_all()
        for ch in self.channels.values():
            await ch.disconnect()
        store.close()


# ── 主函数 ────────────────────────────────────────────
async def main():
    global _scheduler

    print("=" * 60)
    print("TinyClaw s12 — 插件系统（最终版）")
    print("=" * 60)
    print()

    # 初始化消息总线
    bus = MessageBus()

    # 初始化定时调度器
    _scheduler = CronScheduler(store, bus)
    print(f"  ✓ 已加载 {len(_scheduler.jobs)} 个定时任务")

    # 初始化 MCP 管理器
    print("  ℹ 正在扫描 MCP 服务器配置...")
    mcp_manager.start_all()

    # 初始化插件管理器
    print(f"  ℹ 正在扫描插件目录: {PLUGINS_DIR}")
    manifests = plugin_manager.discover()
    if manifests:
        started = plugin_manager.start_all()
        print(f"  ✓ 已启动 {len(started)} 个插件")
    else:
        print("  ℹ 未发现任何插件")

    # 收集所有 Channel（CLI + 插件 Channel）
    channels: list[Channel] = [CLIChannel()]
    for plugin_ch in plugin_manager.get_channels():
        channels.append(plugin_ch)

    print(f"\n  已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")
    print(f"  已注册 {len(channels)} 个通道: {', '.join(ch.name for ch in channels)}")
    print(f"\n  钩子状态:")
    print(hook_system.list_hooks())
    print()
    print("输入指令（quit 退出）：")
    print("-" * 60)

    gateway = Gateway(bus, channels, _scheduler, plugin_manager)

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
