"""
MCP（Model Context Protocol）模块
==================================
MCP 客户端接口和多服务器管理。
"""

from tinyclaw.mcp.client import StdioMCPClient
from tinyclaw.mcp.manager import MCPManager

__all__ = ["StdioMCPClient", "MCPManager"]
