"""
Discord 通道
============
基于 discord.py 的 Discord Bot 通道。
接收 Discord 消息并转发到 MessageBus，
将 Agent 回复发送回 Discord 频道。
"""

import asyncio
from typing import Optional

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.channels.base import Channel
from tinyclaw.config import ChannelConfig


class DiscordChannel(Channel):
    """
    Discord Bot 通道。

    使用 discord.py 库实现，支持：
    - 文本消息收发
    - 服务器频道和私信
    - 长消息自动分片（2000 字符限制）
    - 通过 @ 提及或特定前缀触发
    """

    def __init__(self, config: ChannelConfig):
        """
        初始化 Discord 通道。

        参数:
            config: 通道配置（需要 token 字段）
        """
        self._config = config
        self._bus: MessageBus | None = None
        self._running = False
        self._client = None
        self._prefix = config.extra.get("prefix", "!")  # 命令前缀

    @property
    def name(self) -> str:
        return "discord"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线并启动 Discord Bot。"""
        try:
            import discord
        except ImportError:
            print("  [warn] Discord 通道需要安装 discord.py: pip install discord.py")
            return

        self._bus = bus
        self._running = True

        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        bus_ref = self._bus
        prefix = self._prefix

        @self._client.event
        async def on_ready():
            print(f"  [discord] Bot 已登录: {self._client.user}")

        @self._client.event
        async def on_message(message: discord.Message):
            # 忽略自身消息
            if message.author == self._client.user:
                return
            if not message.content:
                return

            # 检查是否被提及或使用前缀
            text = message.content
            should_respond = False

            if self._client.user and self._client.user.mentioned_in(message):
                # 移除提及文本
                text = text.replace(f"<@{self._client.user.id}>", "").strip()
                should_respond = True
            elif text.startswith(prefix):
                text = text[len(prefix):].strip()
                should_respond = True
            elif isinstance(message.channel, discord.DMChannel):
                # 私信总是响应
                should_respond = True

            if should_respond and text and bus_ref:
                chat_id = str(message.channel.id)
                user_id = str(message.author.id)
                sender_name = message.author.display_name
                await bus_ref.publish_inbound(InboundMessage(
                    channel="discord",
                    chat_id=chat_id,
                    user_id=user_id,
                    text=text,
                    sender_name=sender_name,
                    metadata={"guild_id": str(message.guild.id) if message.guild else ""},
                ))

        # 启动 Bot（非阻塞）
        asyncio.create_task(self._start_bot())

    async def _start_bot(self) -> None:
        """启动 Discord Bot。"""
        try:
            if self._client:
                print("  [discord] Bot 正在启动...")
                await self._client.start(self._config.token)
        except Exception as e:
            print(f"  [warn] Discord Bot 启动出错: {e}")

    async def disconnect(self) -> None:
        """停止 Discord Bot。"""
        self._running = False
        if self._client:
            await self._client.close()

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """
        发送消息到 Discord 频道。

        长消息（> 2000 字符）自动分片发送。
        """
        if not self._client:
            return
        try:
            channel = self._client.get_channel(int(chat_id))
            if channel is None:
                channel = await self._client.fetch_channel(int(chat_id))

            # Discord 消息长度限制 2000 字符
            max_len = 2000
            if len(text) <= max_len:
                await channel.send(text)
            else:
                # 分片发送
                for i in range(0, len(text), max_len):
                    chunk = text[i:i + max_len]
                    await channel.send(chunk)
        except Exception as e:
            print(f"  [warn] Discord 发送消息失败: {e}")
