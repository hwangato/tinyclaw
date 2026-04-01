"""
Telegram 通道
=============
基于 aiogram 的 Telegram Bot 通道。
接收 Telegram 消息并转发到 MessageBus，
将 Agent 回复发送回 Telegram 会话。
"""

import asyncio
from typing import Optional

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.channels.base import Channel
from tinyclaw.config import ChannelConfig


class TelegramChannel(Channel):
    """
    Telegram Bot 通道。

    使用 aiogram 库实现，支持：
    - 文本消息收发
    - 群组和私聊
    - 长消息自动分片
    """

    def __init__(self, config: ChannelConfig):
        """
        初始化 Telegram 通道。

        参数:
            config: 通道配置（需要 token 字段）
        """
        self._config = config
        self._bus: MessageBus | None = None
        self._running = False
        self._bot = None
        self._dp = None

    @property
    def name(self) -> str:
        return "telegram"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线并启动 Telegram Bot 轮询。"""
        try:
            from aiogram import Bot, Dispatcher, types
            from aiogram.filters import CommandStart
        except ImportError:
            print("  [warn] Telegram 通道需要安装 aiogram: pip install aiogram")
            return

        self._bus = bus
        self._running = True

        self._bot = Bot(token=self._config.token)
        self._dp = Dispatcher()

        # 注册消息处理器
        @self._dp.message(CommandStart())
        async def handle_start(message: types.Message):
            await message.answer("你好！我是 TinyClaw Bot。发送消息开始对话。")

        @self._dp.message()
        async def handle_message(message: types.Message):
            if not message.text or not self._bus:
                return
            chat_id = str(message.chat.id)
            user_id = str(message.from_user.id) if message.from_user else "unknown"
            sender_name = message.from_user.full_name if message.from_user else ""
            await self._bus.publish_inbound(InboundMessage(
                channel="telegram",
                chat_id=chat_id,
                user_id=user_id,
                text=message.text,
                sender_name=sender_name,
            ))

        # 启动轮询（非阻塞）
        asyncio.create_task(self._start_polling())

    async def _start_polling(self) -> None:
        """启动 Telegram Bot 长轮询。"""
        try:
            if self._dp and self._bot:
                print("  [telegram] Bot 轮询已启动")
                await self._dp.start_polling(self._bot)
        except Exception as e:
            print(f"  [warn] Telegram 轮询出错: {e}")

    async def disconnect(self) -> None:
        """停止 Telegram Bot。"""
        self._running = False
        if self._dp:
            self._dp.shutdown()
        if self._bot:
            await self._bot.session.close()

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """
        发送消息到 Telegram 会话。

        长消息（> 4096 字符）自动分片发送。
        """
        if not self._bot:
            return
        try:
            # Telegram 消息长度限制 4096 字符
            max_len = 4096
            if len(text) <= max_len:
                await self._bot.send_message(
                    chat_id=int(chat_id),
                    text=text,
                    reply_to_message_id=int(reply_to) if reply_to else None,
                )
            else:
                # 分片发送
                for i in range(0, len(text), max_len):
                    chunk = text[i:i + max_len]
                    await self._bot.send_message(chat_id=int(chat_id), text=chunk)
        except Exception as e:
            print(f"  [warn] Telegram 发送消息失败: {e}")
