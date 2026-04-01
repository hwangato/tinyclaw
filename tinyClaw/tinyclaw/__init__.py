"""
TinyClaw — 模块化 AI Agent 框架
================================
一个支持多通道、多 Agent、插件扩展的轻量级 AI 助手框架。

主要功能：
- 多 LLM Provider 支持（OpenAI 兼容接口，流式输出）
- 多 Agent 管理（独立人格、SOUL.md / IDENTITY.md）
- 多通道接入（CLI / Telegram / Discord / 飞书）
- ReAct Agent 循环（思考-行动-观察）
- 插件系统（JSON-RPC 2.0 协议，tool / channel / hook 三种类型）
- MCP 客户端（Model Context Protocol）
- 定时任务调度（cron / interval / once）
- Docker 沙盒执行
- 安全策略引擎
- 上下文压缩与长期记忆
"""

__version__ = "0.12.0"
__author__ = "TinyClaw Contributors"

from tinyclaw.bus import MessageBus, InboundMessage, OutboundMessage
from tinyclaw.config import Config, load_config
from tinyclaw.gateway import Gateway

__all__ = [
    "MessageBus",
    "InboundMessage",
    "OutboundMessage",
    "Config",
    "load_config",
    "Gateway",
    "__version__",
]
