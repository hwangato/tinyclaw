"""
插件系统模块
============
JSON-RPC 2.0 based 语言无关插件协议。
支持三种插件类型: tool / channel / hook。
"""

from tinyclaw.plugin.protocol import (
    make_jsonrpc_request,
    make_jsonrpc_notification,
    parse_jsonrpc_response,
)
from tinyclaw.plugin.process import PluginProcess
from tinyclaw.plugin.manager import PluginManager, PluginManifest

__all__ = [
    "make_jsonrpc_request",
    "make_jsonrpc_notification",
    "parse_jsonrpc_response",
    "PluginProcess",
    "PluginManager",
    "PluginManifest",
]
