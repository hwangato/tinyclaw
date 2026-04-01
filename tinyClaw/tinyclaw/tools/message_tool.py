"""
跨通道消息工具
==============
提供 send_message 工具，允许 Agent 主动向指定通道/会话发送消息。
"""

import asyncio
from typing import TYPE_CHECKING

from tinyclaw.bus import MessageBus, OutboundMessage
from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    pass


def register_message_tools(registry: ToolRegistry, bus: MessageBus) -> None:
    """
    注册跨通道消息工具。

    参数:
        registry: 工具注册表
        bus: 消息总线
    """

    @registry.tool("send_message", "向指定通道和会话发送消息。", {
        "type": "object",
        "properties": {
            "channel": {"type": "string", "description": "目标通道名称（cli / telegram / discord / feishu）"},
            "chat_id": {"type": "string", "description": "目标会话 ID"},
            "text": {"type": "string", "description": "消息内容"},
        },
        "required": ["channel", "chat_id", "text"],
    })
    def send_message(channel: str, chat_id: str, text: str) -> str:
        """向指定通道和会话主动发送消息。"""
        msg = OutboundMessage(channel=channel, chat_id=chat_id, text=text)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(bus.publish_outbound(msg), loop)
            else:
                bus.outbound.put_nowait(msg)
            return f"消息已发送到 {channel}:{chat_id}"
        except Exception as e:
            return f"消息发送失败: {e}"
