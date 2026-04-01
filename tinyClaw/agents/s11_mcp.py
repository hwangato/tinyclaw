"""
TinyClaw s11 — MCP (Model Context Protocol) 集成
=================================================
核心概念：MCP —— 让 Agent 动态连接外部工具服务器

新增：
- MCPClient (抽象基类)：MCP 服务器连接接口
- StdioMCPClient：通过 stdio + JSON-RPC 2.0 与 MCP 服务器通信
- MCPManager：管理多个 MCP 服务器，命名空间化工具
- TINYCLAW_MCP_CONFIG 配置项

保留 s10 全部功能：Agent Loop, Tool Registry, Skills, SubAgents,
MessageBus, Channel, CLIChannel, SQLite Store, MemoryManager,
Context Compaction, CronScheduler, DockerSandbox, PolicyEngine

运行：python agents/s11_mcp.py
"""

import abc
import asyncio
import json
import logging
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
DOCKER_ENABLED = os.getenv("TINYCLAW_DOCKER_ENABLED", "false").lower() == "true"
MCP_CONFIG_PATH = os.getenv("TINYCLAW_MCP_CONFIG", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("tinyclaw")

# ── 消息类型 & 总线 ──────────────────────────────────
@dataclass
class InboundMessage:
    """入站消息：从各 Channel 流入 Agent。"""
    channel: str
    chat_id: str
    user_id: str
    text: str
    sender_name: str = ""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass
class OutboundMessage:
    """出站消息：Agent 回复给用户。"""
    channel: str
    chat_id: str
    text: str
    reply_to: str = ""


class MessageBus:
    """消息总线：连接 Channel 和 Agent 的桥梁。"""
    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

# ── Token & 压缩 ─────────────────────────────────────
def estimate_tokens(text: str) -> int:
    """估算文本 token 数。中文约 1.5 字符/token，英文约 4 字符/token。"""
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def messages_token_count(messages: list[dict]) -> int:
    """估算消息列表的总 token 数。"""
    total = 0
    for msg in messages:
        if isinstance(msg, dict):
            content = msg.get("content", "")
        else:
            content = getattr(msg, "content", "") or ""
        if content:
            total += estimate_tokens(content)
    return total

def micro_compact(text: str, max_len: int = MAX_TOOL_OUTPUT_LEN) -> str:
    """截断过长的工具输出，保留头尾。"""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n...[截断 {len(text) - max_len} 字符]...\n" + text[-half:]


def compact_messages(messages: list[dict], target_tokens: int = COMPACT_TARGET_TOKENS) -> list[dict]:
    """压缩对话历史：保留最近 8 条，旧消息用 LLM 摘要。"""
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

# ── Docker 沙箱 ───────────────────────────────────────
class DockerSandbox:
    """Docker 沙箱：在容器中安全执行命令，支持资源限制和网络隔离。"""
    def __init__(self, image: str = DOCKER_IMAGE, enabled: bool = DOCKER_ENABLED):
        self.image = image
        self.enabled = enabled
        self._docker_available: bool | None = None

    def is_available(self) -> bool:
        """检查 Docker 是否可用。"""
        if self._docker_available is not None:
            return self._docker_available
        if not self.enabled:
            self._docker_available = False
            return False
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, text=True, timeout=10)
            self._docker_available = r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._docker_available = False
        if not self._docker_available:
            logger.warning("Docker 不可用，将回退到本地执行")
        return self._docker_available

    def run(self, command: str, timeout: int = 30, network: bool = False,
            memory: str = "256m", cpu: float = 1.0) -> str:
        """在 Docker 容器中执行命令。"""
        if not self.is_available():
            return self._fallback_run(command, timeout)
        docker_cmd = [
            "docker", "run", "--rm",
            "--memory", memory,
            f"--cpus={cpu}",
            "-v", f"{WORKDIR}:/workspace:ro",
            "-w", "/workspace",
        ]
        if not network:
            docker_cmd.append("--network=none")
        docker_cmd.extend([self.image, "sh", "-c", command])
        try:
            r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=timeout)
            output = r.stdout + r.stderr
            return micro_compact(output) if output else "(无输出)"
        except subprocess.TimeoutExpired:
            return "(Docker 命令超时)"
        except Exception as e:
            return f"(Docker 执行出错: {e})"

    def _fallback_run(self, command: str, timeout: int) -> str:
        """Docker 不可用时的回退执行。"""
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=timeout)
            output = r.stdout + r.stderr
            return micro_compact(output) if output else "(无输出)"
        except subprocess.TimeoutExpired:
            return "(命令超时)"

# ── PolicyEngine 策略引擎 ─────────────────────────────
@dataclass
class PolicyRule:
    """策略规则定义。"""
    id: str
    description: str
    tool_pattern: str      # 工具名匹配模式（支持 * 通配符）
    action: str            # allow / deny / confirm
    conditions: dict = field(default_factory=dict)

class PolicyEngine:
    """策略引擎：工具执行前的访问控制，支持 allow/deny/confirm。"""
    def __init__(self, rules: list[PolicyRule] | None = None):
        self.rules = rules or self._default_rules()

    def _default_rules(self) -> list[PolicyRule]:
        return [
            PolicyRule("deny-rm-rf", "禁止危险删除命令", "bash", "deny",
                       {"command_contains": ["rm -rf /", "rm -rf ~", "mkfs", "dd if="]}),
            PolicyRule("confirm-write", "写文件需记录", "write_file", "allow", {}),
            PolicyRule("allow-all", "默认允许", "*", "allow", {}),
        ]

    def _match_pattern(self, pattern: str, name: str) -> bool:
        """简单通配符匹配。"""
        if pattern == "*":
            return True
        if "*" in pattern:
            regex = pattern.replace("*", ".*")
            return bool(re.match(f"^{regex}$", name))
        return pattern == name

    def check(self, tool_name: str, arguments: dict) -> tuple[str, str]:
        """
        检查工具调用是否被允许。
        返回 (action, reason)，action 为 allow/deny/confirm。
        """
        for rule in self.rules:
            if not self._match_pattern(rule.tool_pattern, tool_name):
                continue
            # 检查附加条件
            if rule.conditions:
                if "command_contains" in rule.conditions:
                    arg_str = json.dumps(arguments, ensure_ascii=False)
                    if not any(p in arg_str for p in rule.conditions["command_contains"]):
                        continue  # 条件不匹配，继续下一条规则
            return rule.action, rule.description
        return "allow", "默认允许"

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
    """定时任务定义。"""
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
        now = time.time()
        if self.schedule_type == "interval":
            base = self.last_run if self.last_run > 0 else now
            return base + parse_interval(self.schedule_value)
        elif self.schedule_type == "once":
            return datetime.fromisoformat(self.schedule_value).timestamp()
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
        rows = self.store.conn.execute("SELECT * FROM cron_jobs WHERE status = 'active'").fetchall()
        for row in rows:
            job = CronJob(id=row["id"], schedule_type=row["schedule_type"],
                schedule_value=row["schedule_value"], prompt=row["prompt"],
                chat_id=row["chat_id"], script=row["script"] or "",
                status=row["status"], next_run=row["next_run"], last_run=row["last_run"] or 0)
            self.jobs[job.id] = job

    def add_job(self, job: CronJob) -> str:
        job.next_run = job.compute_next_run()
        self.jobs[job.id] = job
        self.store.conn.execute(
            "INSERT OR REPLACE INTO cron_jobs "
            "(id,schedule_type,schedule_value,prompt,chat_id,script,status,next_run,last_run) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (job.id, job.schedule_type, job.schedule_value, job.prompt,
             job.chat_id, job.script, job.status, job.next_run, job.last_run))
        self.store.conn.commit()
        return f"任务 {job.id} 已创建，下次执行: {datetime.fromtimestamp(job.next_run).strftime('%Y-%m-%d %H:%M:%S')}"

    def remove_job(self, job_id: str) -> str:
        if job_id not in self.jobs: return f"任务不存在: {job_id}"
        del self.jobs[job_id]
        self.store.conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        self.store.conn.commit()
        return f"任务 {job_id} 已删除"

    def list_jobs(self) -> str:
        if not self.jobs: return "没有定时任务"
        lines = []
        for job in self.jobs.values():
            nt = datetime.fromtimestamp(job.next_run).strftime("%m-%d %H:%M")
            lines.append(f"  [{job.id}] {job.schedule_type}={job.schedule_value} next={nt} | {job.prompt[:40]}")
        return "\n".join(lines)

    async def start(self):
        self._running = True
        while self._running:
            await asyncio.sleep(60)
            now = time.time()
            for job in list(self.jobs.values()):
                if job.status == "active" and job.next_run <= now:
                    await self._execute_job(job)

    async def _execute_job(self, job: CronJob):
        print(f"  ⏰ 执行定时任务 [{job.id}]: {job.prompt[:50]}")
        if job.script:
            try:
                r = subprocess.run(job.script, shell=True, capture_output=True, text=True, timeout=30)
                if r.stdout.strip():
                    try:
                        gate = json.loads(r.stdout.strip())
                        if not gate.get("wakeAgent", True):
                            print(f"  ⏰ [{job.id}] 脚本门控: 不唤醒 Agent")
                            self._update_job_after_run(job); return
                    except json.JSONDecodeError: pass
            except Exception as e:
                print(f"  ⏰ [{job.id}] 脚本执行出错: {e}")
        await self.bus.inbound.put(InboundMessage(
            channel="cron", chat_id=job.chat_id, user_id="cron",
            text=f"[定时任务 {job.id}] {job.prompt}", sender_name="定时调度器"))
        self._update_job_after_run(job)

    def _update_job_after_run(self, job: CronJob):
        job.last_run = time.time()
        if job.schedule_type == "once":
            job.status = "completed"
            self.store.conn.execute("UPDATE cron_jobs SET status='completed',last_run=? WHERE id=?",
                                    (job.last_run, job.id))
            del self.jobs[job.id]
        else:
            job.next_run = job.compute_next_run()
            self.store.conn.execute("UPDATE cron_jobs SET next_run=?,last_run=? WHERE id=?",
                                    (job.next_run, job.last_run, job.id))
        self.store.conn.commit()

    def stop(self):
        self._running = False


# ── SQLite 存储层 ────────────────────────────────────
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
                timestamp REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY, last_active REAL NOT NULL, metadata TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY, schedule_type TEXT NOT NULL,
                schedule_value TEXT NOT NULL, prompt TEXT NOT NULL,
                chat_id TEXT NOT NULL, script TEXT DEFAULT '',
                status TEXT DEFAULT 'active', next_run REAL DEFAULT 0, last_run REAL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS idx_messages_chat ON messages(chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_cron_status ON cron_jobs(status, next_run);
        """)
        self.conn.commit()

    def save_message(self, chat_id: str, role: str, content: str | None = None,
                     tool_calls: str | None = None, tool_call_id: str | None = None):
        self.conn.execute(
            "INSERT INTO messages (chat_id,role,content,tool_calls,tool_call_id,timestamp) VALUES (?,?,?,?,?,?)",
            (chat_id, role, content, tool_calls, tool_call_id, time.time()))
        self.conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        rows = self.conn.execute(
            "SELECT role,content,tool_calls,tool_call_id FROM messages "
            "WHERE chat_id=? ORDER BY timestamp DESC LIMIT ?", (chat_id, limit)).fetchall()
        messages = []
        for row in reversed(rows):
            msg: dict = {"role": row["role"]}
            if row["content"]: msg["content"] = row["content"]
            if row["tool_calls"]: msg["tool_calls"] = json.loads(row["tool_calls"])
            if row["tool_call_id"]: msg["tool_call_id"] = row["tool_call_id"]
            messages.append(msg)
        return messages

    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT chat_id,role,content,timestamp FROM messages WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit)).fetchall()
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
        content += f"\n## [{time.strftime('%Y-%m-%d %H:%M')}]\n{entry}\n"
        self.path.write_text(content, encoding="utf-8")
        return f"已保存记忆 ({len(entry)} 字符)"

    def search(self, query: str) -> str:
        lines = self.read().split("\n")
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
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                user_input = await loop.run_in_executor(None, lambda: input("\n> ").strip())
                if user_input.lower() in ("quit", "exit", "q"):
                    self._running = False
                    if self._bus:
                        await self._bus.inbound.put(InboundMessage(
                            channel="cli", chat_id="cli-main", user_id="system", text="__QUIT__"))
                    return
                if user_input and self._bus:
                    await self._bus.inbound.put(InboundMessage(
                        channel="cli", chat_id="cli-main",
                        user_id="user", text=user_input, sender_name="用户"))
            except (EOFError, KeyboardInterrupt):
                self._running = False
                return

# ── MCP 客户端（抽象基类）─────────────────────────────
class MCPClient(abc.ABC):
    """MCP (Model Context Protocol) 客户端抽象基类。"""
    @abc.abstractmethod
    def connect(self) -> bool:
        """连接到 MCP 服务器，返回是否成功。"""
        ...
    @abc.abstractmethod
    def list_tools(self) -> list[dict]:
        """列出服务器提供的所有工具。"""
        ...
    @abc.abstractmethod
    def call_tool(self, name: str, args: dict) -> str:
        """调用服务器上的工具，返回结果文本。"""
        ...
    @abc.abstractmethod
    def close(self) -> None:
        """关闭连接，清理资源。"""
        ...

class StdioMCPClient(MCPClient):
    """
    通过 stdio 与 MCP 服务器通信的客户端。
    JSON-RPC 2.0 协议，换行分隔。线程安全（threading.Lock）。

    流程：启动子进程 → initialize → tools/list → tools/call → 关闭
    """
    PROTOCOL_VERSION = "2024-11-05"

    def __init__(self, server_name: str, command: str, args: list[str] | None = None,
                 env: dict[str, str] | None = None, timeout: int = 30):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout = timeout
        self._process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self._connected = False
        self._tools: list[dict] = []

    def _next_id(self) -> int:
        """生成自增请求 ID（线程安全）。"""
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict | None = None) -> dict:
        """发送 JSON-RPC 2.0 请求并等待响应。"""
        if not self._process or self._process.poll() is not None:
            raise ConnectionError(f"MCP 服务器 {self.server_name} 未运行")
        request_id = self._next_id()
        request: dict = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            request["params"] = params
        request_line = json.dumps(request, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                self._process.stdin.write(request_line)
                self._process.stdin.flush()
                # 读取响应，跳过通知（无 id 的消息）
                while True:
                    line = self._process.stdout.readline()
                    if not line:
                        raise ConnectionError(f"MCP 服务器 {self.server_name} 连接中断")
                    line = line.strip()
                    if not line: continue
                    try:
                        resp = json.loads(line)
                    except json.JSONDecodeError:
                        logger.warning(f"MCP [{self.server_name}] 无效 JSON: {line[:200]}")
                        continue
                    if "id" not in resp:  # 通知消息，跳过
                        continue
                    if resp.get("id") != request_id:
                        logger.warning(f"MCP [{self.server_name}] ID 不匹配: 期望 {request_id}, 收到 {resp.get('id')}")
                        continue
                    return resp
            except (BrokenPipeError, OSError) as e:
                raise ConnectionError(f"MCP 服务器 {self.server_name} 通信失败: {e}")

    def connect(self) -> bool:
        """启动子进程并发送 initialize 请求。"""
        try:
            full_env = os.environ.copy()
            full_env.update(self.env)
            cmd = [self.command] + self.args
            logger.info(f"MCP [{self.server_name}] 启动: {' '.join(cmd)}")
            self._process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, env=full_env, bufsize=1)
            # 发送 initialize
            resp = self._send_request("initialize", {
                "protocolVersion": self.PROTOCOL_VERSION,
                "clientInfo": {"name": "tinyclaw", "version": "0.11"},
                "capabilities": {},
            })
            if "error" in resp:
                logger.error(f"MCP [{self.server_name}] 初始化失败: {resp['error'].get('message', '?')}")
                self.close(); return False
            info = resp.get("result", {}).get("serverInfo", {})
            logger.info(f"MCP [{self.server_name}] 已连接 — {info.get('name', '?')} v{info.get('version', '?')}")
            # 发送 initialized 通知（无 id）
            notif = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            with self._lock:
                self._process.stdin.write(notif)
                self._process.stdin.flush()
            self._connected = True
            return True
        except FileNotFoundError:
            logger.error(f"MCP [{self.server_name}] 命令未找到: {self.command}"); return False
        except ConnectionError as e:
            logger.error(f"MCP [{self.server_name}] 连接失败: {e}"); self.close(); return False
        except Exception as e:
            logger.error(f"MCP [{self.server_name}] 启动异常: {e}"); self.close(); return False

    def list_tools(self) -> list[dict]:
        """调用 tools/list 获取工具列表。"""
        if not self._connected: return []
        try:
            resp = self._send_request("tools/list", {})
            if "error" in resp:
                logger.error(f"MCP [{self.server_name}] 获取工具失败: {resp['error'].get('message', '?')}")
                return []
            tools = resp.get("result", {}).get("tools", [])
            self._tools = tools
            logger.info(f"MCP [{self.server_name}] 发现 {len(tools)} 个工具")
            for t in tools:
                logger.info(f"  - {t.get('name', '?')}: {t.get('description', '')[:60]}")
            return tools
        except ConnectionError as e:
            logger.error(f"MCP [{self.server_name}] 列出工具失败: {e}"); return []

    def call_tool(self, name: str, args: dict) -> str:
        """调用 tools/call 执行工具。"""
        if not self._connected: return f"MCP 服务器 {self.server_name} 未连接"
        try:
            resp = self._send_request("tools/call", {"name": name, "arguments": args})
            if "error" in resp:
                return f"MCP 工具执行出错: {resp['error'].get('message', '?')}"
            result = resp.get("result", {})
            content_items = result.get("content", [])
            if not content_items: return json.dumps(result, ensure_ascii=False)
            parts = []
            for item in content_items:
                if isinstance(item, dict):
                    if item.get("type") == "text": parts.append(item.get("text", ""))
                    elif item.get("type") == "image": parts.append(f"[图片: {item.get('mimeType', '?')}]")
                    else: parts.append(json.dumps(item, ensure_ascii=False))
                else: parts.append(str(item))
            return "\n".join(parts) if parts else "(空结果)"
        except ConnectionError as e:
            return f"MCP 服务器通信失败: {e}"

    def close(self) -> None:
        """关闭子进程。"""
        self._connected = False
        if self._process:
            try: self._process.stdin.close()
            except Exception: pass
            try: self._process.terminate(); self._process.wait(timeout=5)
            except Exception:
                try: self._process.kill()
                except Exception: pass
            self._process = None
            logger.info(f"MCP [{self.server_name}] 已断开")

# ── MCPManager ────────────────────────────────────────
class MCPManager:
    """
    MCP 管理器：管理多个 MCP 服务器连接。
    - 从 .mcp.json 加载配置
    - 命名空间化工具名: mcp_{server}_{tool}
    - 路由调用到正确服务器
    - 优雅降级（连接失败仅警告）
    """
    def __init__(self):
        self.clients: dict[str, StdioMCPClient] = {}
        self._tool_routing: dict[str, tuple[str, str]] = {}  # namespaced -> (server, original)
        self._tool_schemas: dict[str, dict] = {}

    def load_config(self, config_path: str) -> dict:
        """从 JSON 文件加载 MCP 服务器配置。"""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"MCP 配置文件不存在: {config_path}")
            return {}
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            logger.info(f"MCP 配置已加载: {len(config.get('servers', {}))} 个服务器")
            return config
        except json.JSONDecodeError as e:
            logger.error(f"MCP 配置解析失败: {e}")
            return {}

    def connect_all(self, config: dict) -> int:
        """连接所有配置的服务器，返回成功数。"""
        servers = config.get("servers", {})
        connected = 0
        for name, cfg in servers.items():
            command = cfg.get("command", "")
            if not command:
                logger.warning(f"MCP [{name}] 缺少 command，跳过")
                continue
            mcp_client = StdioMCPClient(
                server_name=name, command=command,
                args=cfg.get("args", []), env=cfg.get("env", {}))
            try:
                if mcp_client.connect():
                    self.clients[name] = mcp_client
                    tools = mcp_client.list_tools()
                    self._register_server_tools(name, tools)
                    connected += 1
                else:
                    logger.warning(f"MCP [{name}] 连接失败，跳过")
            except Exception as e:
                logger.warning(f"MCP [{name}] 连接异常: {e}，跳过")
        logger.info(f"MCP 已连接 {connected}/{len(servers)} 个服务器")
        return connected

    def _register_server_tools(self, server_name: str, tools: list[dict]):
        """将服务器工具注册到命名空间。"""
        for tool_def in tools:
            orig = tool_def.get("name", "")
            if not orig: continue
            ns_name = f"mcp_{server_name}_{orig}"
            self._tool_routing[ns_name] = (server_name, orig)
            desc = tool_def.get("description", f"MCP 工具: {orig}")
            schema = tool_def.get("inputSchema", {"type": "object", "properties": {}, "required": []})
            self._tool_schemas[ns_name] = {
                "type": "function",
                "function": {"name": ns_name, "description": f"[MCP/{server_name}] {desc}", "parameters": schema},
            }

    def get_tool_schemas(self) -> list[dict]:
        return list(self._tool_schemas.values())

    def is_mcp_tool(self, tool_name: str) -> bool:
        return tool_name in self._tool_routing

    def call_tool(self, namespaced_name: str, args: dict) -> str:
        routing = self._tool_routing.get(namespaced_name)
        if not routing: return f"未知 MCP 工具: {namespaced_name}"
        server_name, orig_name = routing
        c = self.clients.get(server_name)
        if not c: return f"MCP 服务器 {server_name} 未连接"
        return micro_compact(c.call_tool(orig_name, args))

    def list_all_tools(self) -> str:
        if not self._tool_routing: return "没有已连接的 MCP 工具"
        lines = []
        for ns, (srv, orig) in self._tool_routing.items():
            desc = self._tool_schemas.get(ns, {}).get("function", {}).get("description", "")
            lines.append(f"  - {ns}: {desc[:60]}")
        return "\n".join(lines)

    def close_all(self) -> None:
        for name, c in self.clients.items():
            try:
                c.close()
            except Exception as e:
                logger.warning(f"MCP [{name}] 关闭异常: {e}")
        self.clients.clear()
        self._tool_routing.clear()
        self._tool_schemas.clear()
        logger.info("所有 MCP 连接已关闭")

# ── 工具注册表 ────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}

def tool(name: str, description: str, parameters: dict):
    def decorator(func):
        _TOOL_REGISTRY[name] = {
            "schema": {"type": "function",
                       "function": {"name": name, "description": description, "parameters": parameters}},
            "func": func,
        }
        return func
    return decorator

def get_tool_schemas() -> list[dict]:
    """获取所有工具 schema（原生 + MCP）。"""
    schemas = [t["schema"] for t in _TOOL_REGISTRY.values()]
    if _mcp_manager: schemas.extend(_mcp_manager.get_tool_schemas())
    return schemas

def execute_tool(name: str, arguments: dict, depth: int = 0) -> str:
    """执行工具（策略检查 → MCP 路由 → 原生执行）。"""
    action, reason = _policy_engine.check(name, arguments)
    if action == "deny":
        return f"策略拒绝: {reason}"
    if action == "confirm":
        logger.info(f"策略需要确认: {reason} (自动允许)")

    # 检查是否为 MCP 工具
    if _mcp_manager and _mcp_manager.is_mcp_tool(name):
        return _mcp_manager.call_tool(name, arguments)

    # 原生工具
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
    """解析 SKILL.md 文件，提取 frontmatter 和正文。"""
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
    """构建技能列表提示词。"""
    if not summaries:
        return ""
    lines = ["\n可用技能（使用 load_skill 获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)

# ── 初始化全局对象 ────────────────────────────────────
store = Store(DATA_DIR / "tinyclaw.db")
memory_mgr = MemoryManager(WORKDIR / "workspace" / "MEMORY.md")
docker_sandbox = DockerSandbox()
_policy_engine = PolicyEngine()
_scheduler: CronScheduler | None = None
_mcp_manager: MCPManager | None = None

# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。", {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = r.stdout + r.stderr
        return micro_compact(output) if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"

@tool("sandbox_exec", "在 Docker 沙箱中执行命令（安全隔离）。", {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的命令"},
        "network": {"type": "boolean", "description": "是否允许网络", "default": False},
    },
    "required": ["command"],
})
def sandbox_exec(command: str, network: bool = False) -> str:
    return docker_sandbox.run(command, network=network)

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
        if not p.is_dir(): return f"不是目录: {path}"
        entries = []
        for item in sorted(p.iterdir()):
            entries.append(f"{'📁 ' if item.is_dir() else '📄 '}{item.name}")
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
        resp = client.chat.completions.create(model=MODEL, messages=sub_messages, tools=tools)
        msg = resp.choices[0].message
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
        "schedule_type": {"type": "string", "enum": ["cron", "interval", "once"], "description": "调度类型"},
        "schedule_value": {"type": "string", "description": "cron: '0 9 * * *', interval: '5m', once: ISO时间"},
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

@tool("list_mcp_tools", "列出所有已连接的 MCP 工具。", {
    "type": "object", "properties": {}, "required": [],
})
def list_mcp_tools() -> str:
    if not _mcp_manager:
        return "MCP 管理器未初始化"
    return _mcp_manager.list_all_tools()

@tool("policy_check", "检查某个工具调用是否被策略允许。", {
    "type": "object",
    "properties": {
        "tool_name": {"type": "string", "description": "工具名"},
        "arguments": {"type": "object", "description": "工具参数"},
    },
    "required": ["tool_name"],
})
def policy_check(tool_name: str, arguments: dict | None = None) -> str:
    action, reason = _policy_engine.check(tool_name, arguments or {})
    return f"策略: {action} — {reason}"

# ── Agent 处理器 ──────────────────────────────────────
def run_agent(user_message: str, chat_id: str = "default") -> str:
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)
    memory_content = memory_mgr.read()
    memory_prompt = ""
    if memory_content.strip() and memory_content.strip() != "# TinyClaw 记忆":
        memory_prompt = f"\n\n你的长期记忆：\n{memory_content[:2000]}"
    mcp_prompt = ""
    if _mcp_manager and _mcp_manager._tool_routing:
        mcp_prompt = (f"\n\n已连接 {len(_mcp_manager.clients)} 个 MCP 服务器，"
                      f"提供 {len(_mcp_manager._tool_routing)} 个外部工具。"
                      "\nMCP 工具以 mcp_ 前缀命名，与本地工具一起使用。")
    docker_status = "已启用" if docker_sandbox.is_available() else "未启用"
    system_prompt = (
        "你是 TinyClaw，一个支持 MCP 协议的 AI 助手。\n"
        "你可以执行命令、操作文件、加载技能、委派子 Agent、管理定时任务。\n"
        "你还可以使用 MCP 服务器提供的外部工具。\n"
        f"Docker 沙箱: {docker_status}（使用 sandbox_exec 在沙箱中执行）\n"
        f"工作目录: {WORKDIR}"
        f"{skills_prompt}{memory_prompt}{mcp_prompt}")
    history = store.get_recent_messages(chat_id, limit=30)
    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    store.save_message(chat_id, "user", user_message)
    tools = get_tool_schemas()
    while True:
        if messages_token_count(messages) > MAX_TOKENS:
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
            if result == "__COMPACT__":
                messages = compact_messages(messages, COMPACT_TARGET_TOKENS)
                result = "上下文已压缩。"
            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            store.save_message(chat_id, "tool", result, tool_call_id=tc.id)

# ── Gateway ───────────────────────────────────────────
class Gateway:
    def __init__(self, bus: MessageBus, channels: list[Channel],
                 scheduler: CronScheduler, mcp_manager: MCPManager | None = None):
        self.bus = bus
        self.channels = {ch.name: ch for ch in channels}
        self.scheduler = scheduler
        self.mcp_manager = mcp_manager
        self._running = False

    async def start(self):
        for ch in self.channels.values():
            await ch.connect(self.bus)
        self._running = True
        await asyncio.gather(
            self._process_inbound(),
            self._route_outbound(),
            self.scheduler.start(),
        )

    async def _process_inbound(self):
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
                text=reply_text, reply_to=msg.message_id))

    async def _route_outbound(self):
        while self._running:
            msg = await self.bus.outbound.get()
            ch = self.channels.get(msg.channel)
            if ch:
                await ch.send_message(msg.chat_id, msg.text, msg.reply_to)
            elif msg.channel == "cron":
                print(f"\n⏰ [定时任务回复] {msg.text[:200]}")

    async def stop(self):
        self._running = False
        self.scheduler.stop()
        for ch in self.channels.values():
            await ch.disconnect()
        if self.mcp_manager:
            self.mcp_manager.close_all()
        store.close()

# ── 初始化 MCP ────────────────────────────────────────
def init_mcp() -> MCPManager | None:
    """初始化 MCP 管理器，加载配置并连接服务器。"""
    config_path = MCP_CONFIG_PATH
    if not config_path:
        # 检查默认配置路径
        default_paths = [
            Path(".mcp.json"),
            WORKDIR / ".mcp.json",
            DATA_DIR / "mcp.json",
        ]
        for dp in default_paths:
            if dp.exists():
                config_path = str(dp)
                break
    if not config_path:
        logger.info("未找到 MCP 配置，跳过 MCP 初始化")
        return None
    manager = MCPManager()
    config = manager.load_config(config_path)
    if not config or not config.get("servers"):
        logger.info("MCP 配置为空或无服务器定义")
        return manager
    connected = manager.connect_all(config)
    logger.info(f"MCP 初始化完成: {connected} 个服务器已连接")
    return manager

# ── 主函数 ────────────────────────────────────────────
async def main():
    global _scheduler, _mcp_manager
    print("=" * 50)
    print("TinyClaw s11 — MCP (Model Context Protocol) 集成")
    print("=" * 50)
    # 初始化 MCP
    _mcp_manager = init_mcp()
    mcp_tool_count = len(_mcp_manager._tool_routing) if _mcp_manager else 0
    native_count = len(_TOOL_REGISTRY)
    print(f"已注册 {native_count + mcp_tool_count} 个工具 (本地: {native_count}, MCP: {mcp_tool_count})")
    print(f"本地工具: {', '.join(_TOOL_REGISTRY.keys())}")
    if _mcp_manager and _mcp_manager._tool_routing:
        print(f"MCP 工具: {', '.join(_mcp_manager._tool_routing.keys())}")
    print(f"Docker 沙箱: {'已启用 (' + DOCKER_IMAGE + ')' if docker_sandbox.is_available() else '未启用'}")
    print(f"策略引擎: {len(_policy_engine.rules)} 条规则")
    print("输入指令（quit 退出）：")
    bus = MessageBus()
    _scheduler = CronScheduler(store, bus)
    channels: list[Channel] = [CLIChannel()]
    gateway = Gateway(bus, channels, _scheduler, _mcp_manager)
    print(f"已加载 {len(_scheduler.jobs)} 个定时任务")
    print("-" * 50)
    try:
        await gateway.start()
    except (KeyboardInterrupt, asyncio.CancelledError): pass
    finally:
        await gateway.stop()
    print("\n再见！")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")
