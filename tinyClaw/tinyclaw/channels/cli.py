"""
CLI 通道
========
命令行交互通道，通过标准输入/输出与用户交互。
"""

import asyncio

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.channels.base import Channel


class CLIChannel(Channel):
    """
    命令行交互通道。

    从 stdin 读取用户输入，通过 stdout 输出回复。
    支持 quit/exit/q 退出指令。
    """

    def __init__(self):
        self._bus: MessageBus | None = None
        self._running = False

    @property
    def name(self) -> str:
        return "cli"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线，启动输入监听循环。"""
        self._bus = bus
        self._running = True
        asyncio.create_task(self._input_loop())

    async def disconnect(self) -> None:
        """断开连接。"""
        self._running = False

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """输出回复到终端。"""
        print(f"\n[bot] {text}")

    async def _input_loop(self) -> None:
        """异步读取用户输入循环。"""
        loop = asyncio.get_event_loop()
        while self._running:
            try:
                user_input = await loop.run_in_executor(
                    None, lambda: input("\n> ").strip()
                )
                if user_input.lower() in ("quit", "exit", "q"):
                    self._running = False
                    if self._bus:
                        await self._bus.publish_inbound(InboundMessage(
                            channel="cli",
                            chat_id="cli-main",
                            user_id="system",
                            text="__QUIT__",
                        ))
                    return
                if user_input and self._bus:
                    await self._bus.publish_inbound(InboundMessage(
                        channel="cli",
                        chat_id="cli-main",
                        user_id="user",
                        text=user_input,
                        sender_name="用户",
                    ))
            except (EOFError, KeyboardInterrupt):
                self._running = False
                return
