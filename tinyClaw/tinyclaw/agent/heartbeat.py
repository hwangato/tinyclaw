"""
心跳模块
========
为 Agent 提供定期心跳唤醒功能。
可配置间隔，定期向 MessageBus 发送心跳消息以唤醒 Agent。
"""

import asyncio
import re
import time

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.config import AgentConfig


def parse_interval(s: str) -> int:
    """
    解析间隔字符串为秒数。

    支持格式: 30s, 5m, 1h, 1d

    参数:
        s: 间隔字符串

    返回:
        秒数
    """
    m = re.match(r"^(\d+)([smhd])$", s.strip())
    if not m:
        raise ValueError(f"无效间隔格式: {s}（示例: 30s, 5m, 1h, 1d）")
    value, unit = int(m.group(1)), m.group(2)
    multiplier = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multiplier[unit]


class HeartbeatManager:
    """
    心跳管理器。

    为配置了心跳间隔的 Agent 创建定期唤醒任务。
    心跳消息会发送到 MessageBus 的 inbound 队列，
    由 Gateway 路由到对应的 Agent 处理。
    """

    def __init__(self, bus: MessageBus):
        """
        初始化心跳管理器。

        参数:
            bus: 消息总线
        """
        self.bus = bus
        self._tasks: dict[str, asyncio.Task] = {}
        self._running = False

    def register_agent(self, agent_config: AgentConfig) -> bool:
        """
        为 Agent 注册心跳。

        参数:
            agent_config: Agent 配置

        返回:
            是否成功注册
        """
        if not agent_config.heartbeat_interval:
            return False
        try:
            interval_secs = parse_interval(agent_config.heartbeat_interval)
        except ValueError as e:
            print(f"  [warn] Agent {agent_config.id} 心跳配置错误: {e}")
            return False

        if agent_config.id in self._tasks:
            self._tasks[agent_config.id].cancel()

        task = asyncio.create_task(
            self._heartbeat_loop(agent_config.id, agent_config.name, interval_secs)
        )
        self._tasks[agent_config.id] = task
        print(f"  [heartbeat] Agent {agent_config.id} 心跳已注册: 每 {agent_config.heartbeat_interval}")
        return True

    async def _heartbeat_loop(self, agent_id: str, agent_name: str, interval: int) -> None:
        """
        心跳循环。

        参数:
            agent_id: Agent ID
            agent_name: Agent 名称
            interval: 间隔秒数
        """
        self._running = True
        while self._running:
            await asyncio.sleep(interval)
            if not self._running:
                break
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            msg = InboundMessage(
                channel="heartbeat",
                chat_id=f"heartbeat-{agent_id}",
                user_id="system",
                text=f"[心跳唤醒 {timestamp}] 你是 {agent_name}，请检查是否有待处理的任务或需要主动执行的事项。",
                sender_name="心跳系统",
                agent_id=agent_id,
            )
            await self.bus.publish_inbound(msg)
            print(f"  [heartbeat] 已唤醒 Agent {agent_id}")

    def unregister_agent(self, agent_id: str) -> None:
        """取消 Agent 心跳注册。"""
        if agent_id in self._tasks:
            self._tasks[agent_id].cancel()
            del self._tasks[agent_id]

    async def start(self, agent_configs: list[AgentConfig]) -> None:
        """
        启动心跳管理器，为所有配置了心跳的 Agent 注册。

        参数:
            agent_configs: Agent 配置列表
        """
        self._running = True
        for cfg in agent_configs:
            self.register_agent(cfg)

    def stop(self) -> None:
        """停止所有心跳任务。"""
        self._running = False
        for task in self._tasks.values():
            task.cancel()
        self._tasks.clear()

    def list_heartbeats(self) -> str:
        """列出所有活跃的心跳任务。"""
        if not self._tasks:
            return "没有活跃的心跳任务"
        lines = []
        for agent_id, task in self._tasks.items():
            status = "运行中" if not task.done() else "已停止"
            lines.append(f"  [{agent_id}] 状态={status}")
        return "\n".join(lines)
