"""
定时任务工具
============
提供 create_cron / list_crons / delete_cron 三个工具，
允许 Agent 管理定时任务。
"""

import uuid
from typing import TYPE_CHECKING

from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from tinyclaw.cron.scheduler import CronScheduler, CronJob


def register_cron_tools(registry: ToolRegistry, get_scheduler) -> None:
    """
    注册定时任务工具。

    参数:
        registry: 工具注册表
        get_scheduler: 获取 CronScheduler 实例的回调函数
    """

    @registry.tool("create_cron", "创建定时任务。", {
        "type": "object",
        "properties": {
            "schedule_type": {
                "type": "string",
                "enum": ["cron", "interval", "once"],
                "description": "调度类型: cron（cron 表达式）/ interval（固定间隔）/ once（一次性）",
            },
            "schedule_value": {
                "type": "string",
                "description": "cron: '0 9 * * *', interval: '5m', once: '2024-12-25 09:00'",
            },
            "prompt": {"type": "string", "description": "要执行的任务描述"},
            "script": {
                "type": "string",
                "description": "可选的预检 bash 脚本（返回 JSON，wakeAgent=false 可阻止唤醒）",
                "default": "",
            },
        },
        "required": ["schedule_type", "schedule_value", "prompt"],
    })
    def create_cron(
        schedule_type: str,
        schedule_value: str,
        prompt: str,
        script: str = "",
    ) -> str:
        """创建一个新的定时任务。"""
        scheduler = get_scheduler()
        if not scheduler:
            return "调度器未初始化"
        from tinyclaw.cron.scheduler import CronJob
        job = CronJob(
            id=uuid.uuid4().hex[:8],
            schedule_type=schedule_type,
            schedule_value=schedule_value,
            prompt=prompt,
            chat_id="cli-main",
            script=script,
        )
        return scheduler.add_job(job)

    @registry.tool("list_crons", "列出所有定时任务。", {
        "type": "object",
        "properties": {},
        "required": [],
    })
    def list_crons() -> str:
        """列出所有活跃的定时任务。"""
        scheduler = get_scheduler()
        if not scheduler:
            return "调度器未初始化"
        return scheduler.list_jobs()

    @registry.tool("delete_cron", "删除定时任务。", {
        "type": "object",
        "properties": {
            "job_id": {"type": "string", "description": "任务 ID"},
        },
        "required": ["job_id"],
    })
    def delete_cron(job_id: str) -> str:
        """删除指定的定时任务。"""
        scheduler = get_scheduler()
        if not scheduler:
            return "调度器未初始化"
        return scheduler.remove_job(job_id)
