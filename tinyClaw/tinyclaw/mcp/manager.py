"""
MCP 服务器管理器
================
从配置文件加载 MCP 服务器配置，管理多服务器生命周期，
将 MCP 工具注册到全局工具注册表。
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tinyclaw.mcp.client import StdioMCPClient

if TYPE_CHECKING:
    from tinyclaw.tools.registry import ToolRegistry


class MCPManager:
    """
    MCP 多服务器管理器。

    功能：
    - 从 JSON 配置文件加载服务器列表
    - 启动/停止所有服务器进程
    - 将 MCP 工具注册到 ToolRegistry
    """

    def __init__(self, config_path: str | Path = "mcp_servers.json"):
        """
        初始化 MCP 管理器。

        参数:
            config_path: MCP 服务器配置文件路径
        """
        self.config_path = Path(config_path).resolve()
        self.clients: dict[str, StdioMCPClient] = {}

    def load_config(self) -> dict:
        """加载 MCP 配置文件。"""
        if not self.config_path.exists():
            return {}
        try:
            content = self.config_path.read_text(encoding="utf-8")
            return json.loads(content)
        except Exception as e:
            print(f"  [warn] MCP 配置加载失败: {e}")
            return {}

    def start_all(self, tool_registry: "ToolRegistry | None" = None) -> None:
        """
        启动所有配置的 MCP 服务器。

        参数:
            tool_registry: 工具注册表（用于注册 MCP 工具）
        """
        config = self.load_config()
        servers = config.get("mcpServers", {})
        for server_id, server_conf in servers.items():
            command = server_conf.get("command", "")
            args = server_conf.get("args", [])
            env = server_conf.get("env", {})
            if not command:
                continue

            client = StdioMCPClient(server_id, command, args, env)
            if client.start():
                self.clients[server_id] = client
                tools = client.list_tools()
                if tool_registry:
                    for t in tools:
                        self._register_mcp_tool(server_id, client, t, tool_registry)
                print(f"  [mcp] {server_id}: 注册了 {len(tools)} 个工具")

    def _register_mcp_tool(
        self,
        server_id: str,
        client: StdioMCPClient,
        tool_def: dict,
        tool_registry: "ToolRegistry",
    ) -> None:
        """将 MCP 工具注册到工具注册表。"""
        original_name = tool_def.get("name", "")
        tool_name = f"mcp_{server_id}_{original_name}"
        description = tool_def.get("description", f"MCP 工具: {original_name}")
        input_schema = tool_def.get("inputSchema", {
            "type": "object", "properties": {}, "required": [],
        })

        def make_caller(c: StdioMCPClient, name: str):
            def caller(**kwargs) -> str:
                return c.call_tool(name, kwargs)
            return caller

        tool_registry.register(
            name=tool_name,
            description=f"[MCP:{server_id}] {description}",
            parameters=input_schema,
            func=make_caller(client, original_name),
        )

    def stop_all(self) -> None:
        """停止所有 MCP 服务器。"""
        for client in self.clients.values():
            client.stop()
        self.clients.clear()

    def list_servers(self) -> str:
        """列出所有 MCP 服务器状态。"""
        if not self.clients:
            return "没有活跃的 MCP 服务器"
        lines = []
        for sid, client in self.clients.items():
            status = "运行中" if client.is_running else "已停止"
            tool_count = len(client.tools)
            lines.append(f"  [{sid}] 状态={status} | 工具数={tool_count}")
        return "\n".join(lines)
