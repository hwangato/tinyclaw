"""
TinyClaw s10 — 容器隔离与安全策略
====================================
核心概念：Docker Sandbox + Policy Engine —— 沙箱执行与权限管控

Agent 功能越强大，安全风险越大。两道防线：
1. DockerSandbox：将命令执行隔离在 Docker 容器中
   - 容器自动清理（--rm）
   - 工作目录只读挂载
   - 可配置镜像和超时时间
2. PolicyEngine：YAML 驱动的安全策略引擎
   - 文件系统策略（FSPolicy）：读写白名单 / 黑名单
   - 网络策略（NetPolicy）：none / allowlist / permissive
   - 工具策略（ToolsPolicy）：工具白名单 / 黑名单
   - deny-first 语义：拒绝规则总是优先

策略 YAML 格式：
```yaml
filesystem:
  allow_read: ["workspace/**"]
  deny_write: [".env", "*.key", "*.pem"]
network:
  mode: permissive
tools:
  deny: []
sandbox:
  enabled: false
  image: "python:3.12-slim"
```

环境变量：
- TINYCLAW_SANDBOX_ENABLED: 是否启用沙箱（true/false）
- TINYCLAW_SANDBOX_IMAGE: 默认 Docker 镜像
- TINYCLAW_POLICY_FILE: 策略 YAML 文件路径

运行：python agents/s10_sandbox.py
"""

import abc
import asyncio
import fnmatch
import json
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

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

# s10 新增配置
SANDBOX_ENABLED = os.getenv("TINYCLAW_SANDBOX_ENABLED", "false").lower() == "true"
SANDBOX_IMAGE = os.getenv("TINYCLAW_SANDBOX_IMAGE", "python:3.12-slim")
POLICY_FILE = os.getenv("TINYCLAW_POLICY_FILE", "")


# ── YAML 简易解析器（不依赖 PyYAML）──────────────────
def _parse_simple_yaml(text: str) -> dict:
    """
    极简 YAML 解析器，仅支持本项目策略文件格式：
    - 顶层键（无缩进）
    - 二级键（2空格缩进）
    - 值为标量或列表（列表项以 '- ' 开头，或内联 ["a", "b"]）
    """
    result: dict[str, Any] = {}
    current_section: str | None = None
    current_key: str | None = None

    for raw_line in text.split("\n"):
        # 去掉注释
        line = raw_line.split("#")[0].rstrip()
        if not line.strip():
            continue

        indent = len(line) - len(line.lstrip())

        if indent == 0 and line.strip().endswith(":"):
            # 顶层 section
            current_section = line.strip()[:-1]
            result[current_section] = {}
            current_key = None
        elif indent >= 2 and current_section is not None:
            stripped = line.strip()
            if stripped.startswith("- "):
                # 列表项
                if current_key and current_section in result:
                    val = stripped[2:].strip().strip('"').strip("'")
                    if isinstance(result[current_section].get(current_key), list):
                        result[current_section][current_key].append(val)
            elif ":" in stripped:
                k, v = stripped.split(":", 1)
                k = k.strip()
                v = v.strip()
                current_key = k
                if v.startswith("[") and v.endswith("]"):
                    # 内联列表 ["a", "b"]
                    items = []
                    inner = v[1:-1].strip()
                    if inner:
                        for item in inner.split(","):
                            items.append(item.strip().strip('"').strip("'"))
                    result[current_section][k] = items
                elif v == "":
                    result[current_section][k] = []
                elif v.lower() in ("true", "false"):
                    result[current_section][k] = v.lower() == "true"
                else:
                    # 去掉引号
                    result[current_section][k] = v.strip('"').strip("'")
    return result


# ── 安全策略引擎 ─────────────────────────────────────
# 默认策略
DEFAULT_POLICY: dict[str, Any] = {
    "filesystem": {
        "allow_read": ["workspace/**"],
        "allow_write": ["workspace/**"],
        "deny_read": [],
        "deny_write": [".env", "*.key", "*.pem", "*.secret"],
    },
    "network": {
        "mode": "permissive",  # none / allowlist / permissive
        "outbound": [],
    },
    "tools": {
        "allow": [],  # 空 = 全部允许
        "deny": [],
    },
    "sandbox": {
        "enabled": False,
        "image": "python:3.12-slim",
    },
}


class PolicyEngine:
    """
    YAML 驱动的安全策略引擎。
    deny-first 语义：拒绝规则总是优先于允许规则。
    """

    def __init__(self, policy_path: str = ""):
        self.policy = self._deep_copy_policy(DEFAULT_POLICY)
        if policy_path and Path(policy_path).exists():
            self._load_from_file(policy_path)
        # 环境变量覆盖
        if SANDBOX_ENABLED:
            self.policy["sandbox"]["enabled"] = True
        if SANDBOX_IMAGE != "python:3.12-slim":
            self.policy["sandbox"]["image"] = SANDBOX_IMAGE

    def _deep_copy_policy(self, src: dict) -> dict:
        """深拷贝策略字典。"""
        result = {}
        for k, v in src.items():
            if isinstance(v, dict):
                result[k] = self._deep_copy_policy(v)
            elif isinstance(v, list):
                result[k] = list(v)
            else:
                result[k] = v
        return result

    def _load_from_file(self, path: str):
        """从 YAML 文件加载策略。"""
        try:
            content = Path(path).read_text(encoding="utf-8")
            loaded = _parse_simple_yaml(content)
            # 合并到默认策略
            for section, values in loaded.items():
                if section in self.policy and isinstance(values, dict):
                    for k, v in values.items():
                        self.policy[section][k] = v
            print(f"  [策略] 已加载策略文件: {path}")
        except Exception as e:
            print(f"  [策略] 加载策略文件失败: {e}，使用默认策略")

    @property
    def sandbox_enabled(self) -> bool:
        return bool(self.policy.get("sandbox", {}).get("enabled", False))

    @property
    def sandbox_image(self) -> str:
        return self.policy.get("sandbox", {}).get("image", "python:3.12-slim")

    @property
    def network_mode(self) -> str:
        return self.policy.get("network", {}).get("mode", "permissive")

    def check_filesystem(self, filepath: str, is_write: bool = False) -> bool:
        """
        检查文件路径是否允许访问。
        deny-first：如果命中 deny 规则，直接拒绝。
        然后检查 allow 规则，如果 allow 列表非空且未命中，拒绝。
        """
        fs = self.policy.get("filesystem", {})
        normalized = filepath.replace("\\", "/")

        # 1. 检查 deny 规则（deny 总是优先）
        if is_write:
            deny_patterns = fs.get("deny_write", [])
        else:
            deny_patterns = fs.get("deny_read", [])

        for pattern in deny_patterns:
            if fnmatch.fnmatch(normalized, pattern):
                return False
            # 也检查文件名部分
            basename = Path(normalized).name
            if fnmatch.fnmatch(basename, pattern):
                return False

        # 2. 检查 allow 规则
        if is_write:
            allow_patterns = fs.get("allow_write", [])
        else:
            allow_patterns = fs.get("allow_read", [])

        # 如果 allow 列表为空，允许所有（宽松模式）
        if not allow_patterns:
            return True

        for pattern in allow_patterns:
            if fnmatch.fnmatch(normalized, pattern):
                return True
            basename = Path(normalized).name
            if fnmatch.fnmatch(basename, pattern):
                return True

        return False

    def check_tool(self, tool_name: str) -> bool:
        """
        检查工具是否允许执行。
        deny-first：deny 列表优先。
        如果 allow 列表非空，则只允许列表中的工具。
        """
        tools_policy = self.policy.get("tools", {})

        # 1. deny 列表优先
        deny_list = tools_policy.get("deny", [])
        if tool_name in deny_list:
            return False

        # 2. 如果 allow 列表非空，只允许列表中的工具
        allow_list = tools_policy.get("allow", [])
        if allow_list and tool_name not in allow_list:
            return False

        return True

    def check_network(self, host: str = "") -> bool:
        """检查网络访问是否允许。"""
        mode = self.network_mode
        if mode == "none":
            return False
        if mode == "permissive":
            return True
        if mode == "allowlist":
            outbound = self.policy.get("network", {}).get("outbound", [])
            for allowed_host in outbound:
                if fnmatch.fnmatch(host, allowed_host):
                    return True
            return False
        return True

    def summary(self) -> str:
        """返回策略摘要。"""
        lines = ["当前安全策略:"]
        fs = self.policy.get("filesystem", {})
        lines.append(f"  文件系统:")
        lines.append(f"    允许读取: {fs.get('allow_read', [])}")
        lines.append(f"    允许写入: {fs.get('allow_write', [])}")
        lines.append(f"    拒绝读取: {fs.get('deny_read', [])}")
        lines.append(f"    拒绝写入: {fs.get('deny_write', [])}")
        net = self.policy.get("network", {})
        lines.append(f"  网络: mode={net.get('mode', 'permissive')}")
        tools = self.policy.get("tools", {})
        lines.append(f"  工具: allow={tools.get('allow', [])}, deny={tools.get('deny', [])}")
        sb = self.policy.get("sandbox", {})
        lines.append(f"  沙箱: enabled={sb.get('enabled', False)}, image={sb.get('image', 'N/A')}")
        return "\n".join(lines)


# ── Docker 沙箱 ──────────────────────────────────────
class DockerSandbox:
    """
    Docker 容器沙箱。
    将命令在隔离容器中执行，工作目录以只读方式挂载。
    使用 subprocess 调用 docker run（无需 docker SDK）。
    """

    def __init__(self, policy: PolicyEngine, workspace: Path | None = None):
        self.policy = policy
        self.workspace = workspace or WORKDIR
        self._docker_available: bool | None = None

    def is_available(self) -> bool:
        """检查 Docker 是否可用。"""
        if self._docker_available is not None:
            return self._docker_available
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, text=True, timeout=10,
            )
            self._docker_available = result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            self._docker_available = False
        return self._docker_available

    def run(self, command: str, image: str = "", timeout: int = 30,
            writable: bool = False) -> str:
        """
        在 Docker 容器中执行命令。

        参数:
            command: 要执行的 shell 命令
            image: Docker 镜像名称（默认使用策略中的镜像）
            timeout: 超时秒数
            writable: 是否以读写方式挂载工作目录
        """
        if not self.is_available():
            return "[沙箱错误] Docker 不可用，请确认 Docker 已安装并运行"

        if not image:
            image = self.policy.sandbox_image

        # 构建 docker run 命令
        docker_cmd = [
            "docker", "run",
            "--rm",                         # 自动清理容器
            "--name", f"tinyclaw-{uuid.uuid4().hex[:8]}",
        ]

        # 网络策略
        net_mode = self.policy.network_mode
        if net_mode == "none":
            docker_cmd.extend(["--network", "none"])

        # 资源限制
        docker_cmd.extend([
            "--memory", "512m",             # 内存上限
            "--cpus", "1.0",                # CPU 上限
            "--pids-limit", "100",          # 进程数上限
        ])

        # 安全选项：禁止提权
        docker_cmd.extend([
            "--security-opt", "no-new-privileges",
        ])

        # 挂载工作目录
        mount_mode = "rw" if writable else "ro"
        docker_cmd.extend([
            "-v", f"{self.workspace}:/workspace:{mount_mode}",
            "-w", "/workspace",
        ])

        # 镜像和命令
        docker_cmd.extend([
            image,
            "sh", "-c", command,
        ])

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,  # 额外留 10 秒给容器启动
            )
            output = result.stdout + result.stderr
            if result.returncode != 0 and not output:
                output = f"[容器退出码: {result.returncode}]"
            return output if output.strip() else "(容器无输出)"
        except subprocess.TimeoutExpired:
            # 尝试清理超时的容器
            return f"[沙箱超时] 命令执行超过 {timeout} 秒"
        except FileNotFoundError:
            return "[沙箱错误] 找不到 docker 命令"
        except Exception as e:
            return f"[沙箱错误] {e}"

    def run_with_script(self, script_content: str, image: str = "",
                        timeout: int = 60) -> str:
        """
        在容器中执行多行脚本。
        将脚本内容通过 stdin 传入容器。
        """
        if not self.is_available():
            return "[沙箱错误] Docker 不可用"

        if not image:
            image = self.policy.sandbox_image

        docker_cmd = [
            "docker", "run",
            "--rm", "-i",
            "--network", "none" if self.policy.network_mode == "none" else "bridge",
            "--memory", "512m",
            "--cpus", "1.0",
            "--pids-limit", "100",
            "--security-opt", "no-new-privileges",
            "-v", f"{self.workspace}:/workspace:ro",
            "-w", "/workspace",
            image,
            "sh",
        ]

        try:
            result = subprocess.run(
                docker_cmd,
                input=script_content,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
            )
            output = result.stdout + result.stderr
            return output if output.strip() else "(容器无输出)"
        except subprocess.TimeoutExpired:
            return f"[沙箱超时] 脚本执行超过 {timeout} 秒"
        except Exception as e:
            return f"[沙箱错误] {e}"


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


# ── Token & 压缩 ─────────────────────────────────────
def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 4)


def messages_token_count(messages: list[dict]) -> int:
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
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n...[截断 {len(text) - max_len} 字符]...\n" + text[-half:]


def compact_messages(messages: list[dict], target_tokens: int = COMPACT_TARGET_TOKENS) -> list[dict]:
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
    id: str
    schedule_type: str  # cron / interval / once
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
            interval_secs = parse_interval(self.schedule_value)
            # 基于 last_run 而非 now，防止漂移
            base = self.last_run if self.last_run > 0 else now
            return base + interval_secs
        elif self.schedule_type == "once":
            dt = datetime.fromisoformat(self.schedule_value)
            return dt.timestamp()
        elif self.schedule_type == "cron":
            # 下一分钟开始检查
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
        """从数据库加载任务。"""
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
        if job_id not in self.jobs:
            return f"任务不存在: {job_id}"
        del self.jobs[job_id]
        self.store.conn.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
        self.store.conn.commit()
        return f"任务 {job_id} 已删除"

    def list_jobs(self) -> str:
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
        self._running = True
        while self._running:
            await asyncio.sleep(60)  # 每分钟检查一次
            now = time.time()
            for job in list(self.jobs.values()):
                if job.status != "active" or job.next_run > now:
                    continue
                await self._execute_job(job)

    async def _execute_job(self, job: CronJob):
        """执行一个到期的定时任务。"""
        print(f"  [cron] 执行定时任务 [{job.id}]: {job.prompt[:50]}")

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
                            print(f"  [cron] [{job.id}] 脚本门控: 不唤醒 Agent")
                            self._update_job_after_run(job)
                            return
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                print(f"  [cron] [{job.id}] 脚本执行出错: {e}")

        # 将任务作为消息发送给 Agent
        await self.bus.inbound.put(InboundMessage(
            channel="cron",
            chat_id=job.chat_id,
            user_id="cron",
            text=f"[定时任务 {job.id}] {job.prompt}",
            sender_name="定时调度器",
        ))

        self._update_job_after_run(job)

    def _update_job_after_run(self, job: CronJob):
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
        self._running = False


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
        self.conn.execute(
            "INSERT INTO messages (chat_id, role, content, tool_calls, tool_call_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, tool_calls, tool_call_id, time.time()),
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
        print(f"\n[TinyClaw] {text}")

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
    """
    执行工具，先检查策略。
    """
    # 策略检查：工具是否被允许
    if not policy_engine.check_tool(name):
        return f"[策略拒绝] 工具 '{name}' 被安全策略禁止执行"

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
        lines.append(f"  - {s['id']}: {s['name']} -- {s['description']}")
    return "\n".join(lines)


# ── 初始化全局对象 ────────────────────────────────────
store = Store(DATA_DIR / "tinyclaw.db")
memory_mgr = MemoryManager(WORKDIR / "workspace" / "MEMORY.md")
policy_engine = PolicyEngine(POLICY_FILE)
docker_sandbox = DockerSandbox(policy_engine)
# scheduler 需要在 main() 中创建（需要 bus）
_scheduler: CronScheduler | None = None


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在 shell 中执行命令（沙箱模式下在 Docker 容器中执行）。", {
    "type": "object",
    "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    # 如果启用了沙箱，通过 Docker 执行
    if policy_engine.sandbox_enabled:
        print(f"    [沙箱] 在容器中执行命令...")
        return micro_compact(docker_sandbox.run(command))

    # 否则在本地执行
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        return micro_compact(output) if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"


@tool("read_file", "读取文件内容（受文件系统策略管控）。", {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "文件路径"}},
    "required": ["path"],
})
def read_file(path: str) -> str:
    # 策略检查：文件读取权限
    if not policy_engine.check_filesystem(path, is_write=False):
        return f"[策略拒绝] 不允许读取文件: {path}"
    try:
        content = safe_path(path).read_text(encoding="utf-8")
        return micro_compact(content, 8192) if content else "(空文件)"
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except PermissionError as e:
        return str(e)


@tool("write_file", "写入内容到文件（受文件系统策略管控）。", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "文件内容"},
    },
    "required": ["path", "content"],
})
def write_file(path: str, content: str) -> str:
    # 策略检查：文件写入权限
    if not policy_engine.check_filesystem(path, is_write=True):
        return f"[策略拒绝] 不允许写入文件: {path}"
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
            prefix = "[DIR] " if item.is_dir() else "[FILE] "
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
    "properties": {"task": {"type": "string", "description": "子任务描述"}},
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
    "properties": {"content": {"type": "string", "description": "要保存的内容"}},
    "required": ["content"],
})
def save_memory(content: str) -> str:
    return memory_mgr.append(content)


@tool("search_memory", "搜索长期记忆和对话历史。", {
    "type": "object",
    "properties": {"query": {"type": "string", "description": "搜索关键词"}},
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
        chat_id="cli-main",  # 默认关联 CLI 会话
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


# ── s10 新增工具 ──────────────────────────────────────
@tool("sandbox_exec", "在 Docker 沙箱中执行命令（可指定镜像）。", {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "要执行的 shell 命令"},
        "image": {
            "type": "string",
            "description": "Docker 镜像名称（默认 python:3.12-slim）",
            "default": "",
        },
        "timeout": {
            "type": "integer",
            "description": "超时秒数（默认 30）",
            "default": 30,
        },
        "writable": {
            "type": "boolean",
            "description": "是否以读写方式挂载工作目录（默认 false）",
            "default": False,
        },
    },
    "required": ["command"],
})
def sandbox_exec(command: str, image: str = "", timeout: int = 30,
                 writable: bool = False) -> str:
    if not docker_sandbox.is_available():
        return "[沙箱错误] Docker 不可用，请确认 Docker 已安装并运行"
    print(f"    [沙箱] 镜像={image or policy_engine.sandbox_image}, 超时={timeout}s")
    result = docker_sandbox.run(
        command, image=image, timeout=timeout, writable=writable,
    )
    return micro_compact(result)


@tool("show_policy", "显示当前安全策略配置。", {
    "type": "object", "properties": {}, "required": [],
})
def show_policy() -> str:
    sandbox_status = "可用" if docker_sandbox.is_available() else "不可用"
    return (
        policy_engine.summary()
        + f"\n  Docker 状态: {sandbox_status}"
    )


@tool("check_path_policy", "检查指定路径的读写权限。", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "要检查的文件路径"},
        "is_write": {
            "type": "boolean",
            "description": "是否检查写权限（默认 false 检查读权限）",
            "default": False,
        },
    },
    "required": ["path"],
})
def check_path_policy(path: str, is_write: bool = False) -> str:
    action = "写入" if is_write else "读取"
    allowed = policy_engine.check_filesystem(path, is_write=is_write)
    if allowed:
        return f"[策略允许] {action} '{path}'"
    else:
        return f"[策略拒绝] {action} '{path}'"


# ── Agent 处理器 ──────────────────────────────────────
def run_agent(user_message: str, chat_id: str = "default") -> str:
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)
    memory_content = memory_mgr.read()
    memory_prompt = ""
    if memory_content.strip() and memory_content.strip() != "# TinyClaw 记忆":
        memory_prompt = f"\n\n你的长期记忆：\n{memory_content[:2000]}"

    # 沙箱状态提示
    sandbox_hint = ""
    if policy_engine.sandbox_enabled:
        sandbox_hint = (
            "\n\n[安全模式] 沙箱已启用，bash 命令将在 Docker 容器中执行。"
            f"\n  默认镜像: {policy_engine.sandbox_image}"
            "\n  使用 sandbox_exec 可指定不同镜像。"
            "\n  使用 show_policy 查看完整安全策略。"
        )
    else:
        sandbox_hint = (
            "\n\n[安全模式] 沙箱未启用，bash 命令在本地执行。"
            "\n  可通过 sandbox_exec 工具手动在容器中执行命令。"
            "\n  使用 show_policy 查看当前安全策略。"
        )

    system_prompt = (
        "你是 TinyClaw，一个具备安全沙箱的 AI 助手。\n"
        "你可以执行命令、操作文件、加载技能、委派子 Agent、管理定时任务。\n"
        "安全工具: sandbox_exec（沙箱执行）、show_policy（查看策略）、check_path_policy（检查路径权限）。\n"
        "定时任务工具: create_cron（创建）、list_crons（列出）、delete_cron（删除）。\n"
        f"工作目录: {WORKDIR}"
        f"{sandbox_hint}{skills_prompt}{memory_prompt}"
    )

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
            print(f"  [tool] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")
            result = execute_tool(fn_name, fn_args, depth=0)
            if result == "__COMPACT__":
                messages = compact_messages(messages, COMPACT_TARGET_TOKENS)
                result = "上下文已压缩。"
            print(f"  [result] {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
            store.save_message(chat_id, "tool", result, tool_call_id=tc.id)


# ── Gateway ───────────────────────────────────────────
class Gateway:
    def __init__(self, bus: MessageBus, channels: list[Channel], scheduler: CronScheduler):
        self.bus = bus
        self.channels = {ch.name: ch for ch in channels}
        self.scheduler = scheduler
        self._running = False

    async def start(self):
        for ch in self.channels.values():
            await ch.connect(self.bus)
        self._running = True
        await asyncio.gather(
            self._process_inbound(),
            self._route_outbound(),
            self.scheduler.start(),  # 调度器并行运行
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
                text=reply_text, reply_to=msg.message_id,
            ))

    async def _route_outbound(self):
        while self._running:
            msg = await self.bus.outbound.get()
            ch = self.channels.get(msg.channel)
            if ch:
                await ch.send_message(msg.chat_id, msg.text, msg.reply_to)
            elif msg.channel == "cron":
                # Cron 任务的回复输出到终端
                print(f"\n[cron] [定时任务回复] {msg.text[:200]}")

    async def stop(self):
        self._running = False
        self.scheduler.stop()
        for ch in self.channels.values():
            await ch.disconnect()
        store.close()


# ── 主函数 ────────────────────────────────────────────
async def main():
    global _scheduler
    print("=" * 60)
    print("TinyClaw s10 -- 容器隔离与安全策略")
    print("=" * 60)
    print(f"  已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")
    print(f"  模型: {MODEL}")
    print(f"  工作目录: {WORKDIR}")

    # 显示沙箱状态
    if policy_engine.sandbox_enabled:
        docker_ok = docker_sandbox.is_available()
        status = "可用" if docker_ok else "不可用（Docker 未安装或未运行）"
        print(f"  沙箱: 已启用 (镜像: {policy_engine.sandbox_image}) - Docker {status}")
    else:
        print(f"  沙箱: 未启用（bash 在本地执行）")

    # 显示策略来源
    if POLICY_FILE and Path(POLICY_FILE).exists():
        print(f"  策略文件: {POLICY_FILE}")
    else:
        print(f"  策略文件: 使用默认策略")

    # 显示策略要点
    net_mode = policy_engine.network_mode
    deny_tools = policy_engine.policy.get("tools", {}).get("deny", [])
    deny_write = policy_engine.policy.get("filesystem", {}).get("deny_write", [])
    print(f"  网络策略: {net_mode}")
    if deny_tools:
        print(f"  禁止工具: {deny_tools}")
    if deny_write:
        print(f"  禁止写入: {deny_write}")

    print("-" * 60)
    print("输入指令（quit 退出）：")

    bus = MessageBus()
    _scheduler = CronScheduler(store, bus)
    channels: list[Channel] = [CLIChannel()]
    gateway = Gateway(bus, channels, _scheduler)

    print(f"  已加载 {len(_scheduler.jobs)} 个定时任务")

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
