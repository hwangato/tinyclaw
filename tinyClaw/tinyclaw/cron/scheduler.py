"""
定时任务调度器
==============
支持三种调度方式：
- cron: 标准 5 字段 cron 表达式
- interval: 固定间隔（如 5m, 1h）
- once: 一次性定时任务

支持脚本门控：预检脚本可决定是否唤醒 Agent。
"""

import asyncio
import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.store.sqlite import Store


def parse_interval(s: str) -> int:
    """
    解析间隔字符串为秒数。

    参数:
        s: 间隔字符串（如 '5m', '1h', '30s', '1d'）

    返回:
        秒数
    """
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
    """
    检查 5 字段 cron 表达式是否匹配指定时间。

    字段顺序: 分 时 日 月 星期
    """
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
    schedule_type: str       # cron / interval / once
    schedule_value: str      # cron 表达式 / 间隔 / ISO 时间
    prompt: str              # 要执行的任务描述
    chat_id: str             # 关联的会话 ID
    script: str = ""         # 可选的预检脚本
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

    功能：
    - 从数据库加载活跃任务
    - 每 N 秒轮询一次（可配置）
    - 执行到期任务（发送到 MessageBus）
    - 支持脚本门控
    """

    def __init__(self, store: Store, bus: MessageBus, poll_interval: int = 60):
        """
        初始化调度器。

        参数:
            store: 持久化存储
            bus: 消息总线
            poll_interval: 轮询间隔（秒）
        """
        self.store = store
        self.bus = bus
        self.poll_interval = poll_interval
        self.jobs: dict[str, CronJob] = {}
        self._running = False
        self._load_jobs()

    def _load_jobs(self) -> None:
        """从数据库加载活跃任务。"""
        rows = self.store.conn.execute(
            "SELECT * FROM cron_jobs WHERE status = 'active'"
        ).fetchall()
        for row in rows:
            job = CronJob(
                id=row["id"],
                schedule_type=row["schedule_type"],
                schedule_value=row["schedule_value"],
                prompt=row["prompt"],
                chat_id=row["chat_id"],
                script=row["script"] or "",
                status=row["status"],
                next_run=row["next_run"],
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

    async def start(self) -> None:
        """启动调度循环。"""
        self._running = True
        while self._running:
            await asyncio.sleep(self.poll_interval)
            now = time.time()
            for job in list(self.jobs.values()):
                if job.status != "active" or job.next_run > now:
                    continue
                await self._execute_job(job)

    async def _execute_job(self, job: CronJob) -> None:
        """执行一个到期的定时任务。"""
        print(f"  [cron] 执行任务 [{job.id}]: {job.prompt[:50]}")

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

        await self.bus.publish_inbound(InboundMessage(
            channel="cron",
            chat_id=job.chat_id,
            user_id="cron",
            text=f"[定时任务 {job.id}] {job.prompt}",
            sender_name="定时调度器",
        ))
        self._update_job_after_run(job)

    def _update_job_after_run(self, job: CronJob) -> None:
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

    def stop(self) -> None:
        """停止调度器。"""
        self._running = False
