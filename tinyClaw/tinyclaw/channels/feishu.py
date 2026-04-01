"""
飞书（Lark）通道
================
基于 httpx + Lark Open API 的飞书 Bot 通道。
使用 HTTP 回调模式接收消息，通过 API 发送回复。
"""

import asyncio
import hashlib
import json
import time
from typing import Optional

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.channels.base import Channel
from tinyclaw.config import ChannelConfig


class FeishuChannel(Channel):
    """
    飞书 Bot 通道。

    使用 HTTP 回调（Webhook）接收消息事件，
    通过飞书 Open API 发送回复消息。

    需要配置:
    - app_id: 飞书应用 App ID
    - app_secret: 飞书应用 App Secret
    - webhook_host: 回调服务监听地址
    - webhook_port: 回调服务监听端口
    - extra.verification_token: 事件验证 Token
    - extra.encrypt_key: 事件加密密钥（可选）
    """

    def __init__(self, config: ChannelConfig):
        """
        初始化飞书通道。

        参数:
            config: 通道配置
        """
        self._config = config
        self._bus: MessageBus | None = None
        self._running = False
        self._tenant_access_token: str = ""
        self._token_expires_at: float = 0
        self._verification_token = config.extra.get("verification_token", "")
        self._encrypt_key = config.extra.get("encrypt_key", "")
        self._processed_msg_ids: set[str] = set()  # 消息去重

    @property
    def name(self) -> str:
        return "feishu"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线，启动 HTTP 回调服务器。"""
        self._bus = bus
        self._running = True

        # 获取初始 token
        await self._refresh_token()

        # 启动 HTTP 服务器
        asyncio.create_task(self._start_webhook_server())

    async def _refresh_token(self) -> None:
        """刷新飞书 tenant_access_token。"""
        try:
            import httpx
        except ImportError:
            print("  [warn] 飞书通道需要安装 httpx: pip install httpx")
            return

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                    json={
                        "app_id": self._config.app_id,
                        "app_secret": self._config.app_secret,
                    },
                )
                data = resp.json()
                if data.get("code") == 0:
                    self._tenant_access_token = data["tenant_access_token"]
                    expire = data.get("expire", 7200)
                    self._token_expires_at = time.time() + expire - 300  # 提前 5 分钟刷新
                    print("  [feishu] 已获取 tenant_access_token")
                else:
                    print(f"  [warn] 飞书 token 获取失败: {data}")
        except Exception as e:
            print(f"  [warn] 飞书 token 刷新失败: {e}")

    async def _ensure_token(self) -> str:
        """确保 token 有效，必要时刷新。"""
        if time.time() >= self._token_expires_at:
            await self._refresh_token()
        return self._tenant_access_token

    async def _start_webhook_server(self) -> None:
        """启动 HTTP 回调服务器。"""
        try:
            from aiohttp import web
        except ImportError:
            print("  [warn] 飞书通道 HTTP 服务需要安装 aiohttp: pip install aiohttp")
            return

        app = web.Application()
        app.router.add_post("/feishu/event", self._handle_event)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(
            runner,
            self._config.webhook_host,
            self._config.webhook_port,
        )
        await site.start()
        print(
            f"  [feishu] Webhook 服务已启动: "
            f"http://{self._config.webhook_host}:{self._config.webhook_port}/feishu/event"
        )

    async def _handle_event(self, request) -> "web.Response":
        """处理飞书事件回调。"""
        from aiohttp import web

        try:
            body = await request.json()
        except Exception:
            return web.Response(status=400, text="Invalid JSON")

        # URL 验证（首次配置回调时飞书会发送验证请求）
        if "challenge" in body:
            return web.json_response({"challenge": body["challenge"]})

        # 事件 token 验证
        token = body.get("token", "")
        if self._verification_token and token != self._verification_token:
            return web.Response(status=403, text="Token mismatch")

        # 处理消息事件
        header = body.get("header", {})
        event_type = header.get("event_type", "")

        if event_type == "im.message.receive_v1":
            event = body.get("event", {})
            message = event.get("message", {})
            msg_id = message.get("message_id", "")

            # 消息去重
            if msg_id in self._processed_msg_ids:
                return web.json_response({"code": 0})
            self._processed_msg_ids.add(msg_id)
            # 防止集合无限增长
            if len(self._processed_msg_ids) > 10000:
                self._processed_msg_ids = set(list(self._processed_msg_ids)[-5000:])

            msg_type = message.get("message_type", "")
            chat_id = message.get("chat_id", "")
            sender = event.get("sender", {})
            sender_id = sender.get("sender_id", {}).get("user_id", "unknown")

            if msg_type == "text":
                try:
                    content = json.loads(message.get("content", "{}"))
                    text = content.get("text", "")
                except json.JSONDecodeError:
                    text = ""

                if text and self._bus:
                    await self._bus.publish_inbound(InboundMessage(
                        channel="feishu",
                        chat_id=chat_id,
                        user_id=sender_id,
                        text=text,
                        sender_name=sender.get("sender_id", {}).get("name", ""),
                        metadata={"message_id": msg_id},
                    ))

        return web.json_response({"code": 0})

    async def disconnect(self) -> None:
        """断开连接。"""
        self._running = False

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """
        发送消息到飞书会话。

        参数:
            chat_id: 飞书会话 ID
            text: 消息内容
            reply_to: 回复的消息 ID
        """
        try:
            import httpx
        except ImportError:
            return

        token = await self._ensure_token()
        if not token:
            print("  [warn] 飞书 token 未就绪")
            return

        try:
            payload = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": text}),
            }
            if reply_to:
                payload["reply_in_thread"] = True

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    "https://open.feishu.cn/open-apis/im/v1/messages",
                    params={"receive_id_type": "chat_id"},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json=payload,
                )
                data = resp.json()
                if data.get("code") != 0:
                    print(f"  [warn] 飞书消息发送失败: {data.get('msg', '')}")
        except Exception as e:
            print(f"  [warn] 飞书消息发送出错: {e}")
