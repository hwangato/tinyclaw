"""
消息总线模块
============
定义 InboundMessage / OutboundMessage 消息类型和 MessageBus 双向队列。
所有跨模块通信均通过 MessageBus 进行。
"""

import asyncio
import uuid
from dataclasses import dataclass, field


@dataclass
class InboundMessage:
    """入站消息：从各 Channel 发往 Agent 的消息。"""
    channel: str
    chat_id: str
    user_id: str
    text: str
    sender_name: str = ""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_id: str = ""           # 指定目标 Agent（留空则由 Gateway 路由）
    metadata: dict = field(default_factory=dict)


@dataclass
class OutboundMessage:
    """出站消息：Agent 回复发往 Channel。"""
    channel: str
    chat_id: str
    text: str
    reply_to: str = ""
    agent_id: str = ""
    metadata: dict = field(default_factory=dict)


class MessageBus:
    """
    消息总线：inbound/outbound 双向异步队列。

    所有通道将用户消息放入 inbound 队列，
    Gateway 处理后将回复放入 outbound 队列，
    再路由回对应通道。
    """

    def __init__(self, maxsize: int = 100):
        self.inbound: asyncio.Queue[InboundMessage] = asyncio.Queue(maxsize=maxsize)
        self.outbound: asyncio.Queue[OutboundMessage] = asyncio.Queue(maxsize=maxsize)

    async def publish_inbound(self, msg: InboundMessage) -> None:
        """发布入站消息。"""
        await self.inbound.put(msg)

    async def publish_outbound(self, msg: OutboundMessage) -> None:
        """发布出站消息。"""
        await self.outbound.put(msg)

    def publish_inbound_threadsafe(self, msg: InboundMessage, loop: asyncio.AbstractEventLoop) -> None:
        """从非异步线程安全地发布入站消息。"""
        asyncio.run_coroutine_threadsafe(self.inbound.put(msg), loop)

    def publish_outbound_threadsafe(self, msg: OutboundMessage, loop: asyncio.AbstractEventLoop) -> None:
        """从非异步线程安全地发布出站消息。"""
        asyncio.run_coroutine_threadsafe(self.outbound.put(msg), loop)
