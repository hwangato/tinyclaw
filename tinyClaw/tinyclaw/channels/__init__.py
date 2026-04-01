"""
通道模块
========
包含所有消息通道实现：CLI / Telegram / Discord / 飞书。
"""

from tinyclaw.channels.base import Channel
from tinyclaw.channels.cli import CLIChannel

__all__ = ["Channel", "CLIChannel"]
