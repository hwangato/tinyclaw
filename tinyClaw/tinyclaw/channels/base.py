"""
通道抽象基类
============
定义所有消息通道必须实现的协议接口。
"""

import abc

from tinyclaw.bus import MessageBus


class Channel(abc.ABC):
    """
    通道抽象基类。

    所有消息通道（CLI / Telegram / Discord / 飞书 / 插件通道）
    必须实现此接口。

    生命周期:
        connect() -> 运行中 -> disconnect()
    """

    @abc.abstractmethod
    async def connect(self, bus: MessageBus) -> None:
        """
        连接到消息总线并开始监听。

        参数:
            bus: 消息总线实例
        """
        ...

    @abc.abstractmethod
    async def disconnect(self) -> None:
        """断开连接，释放资源。"""
        ...

    @abc.abstractmethod
    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """
        发送消息到指定会话。

        参数:
            chat_id: 会话 ID
            text: 消息内容
            reply_to: 回复的消息 ID
        """
        ...

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """通道名称标识符。"""
        ...
