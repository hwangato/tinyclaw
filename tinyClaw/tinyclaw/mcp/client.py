"""
MCP 客户端
==========
通过 stdio 与 MCP 服务器通信，获取工具列表并执行工具。
使用 JSON-RPC 2.0 协议。
"""

import json
import os
import subprocess
import threading
from typing import Optional


class StdioMCPClient:
    """
    MCP Stdio 客户端。

    通过 stdin/stdout 与 MCP 服务器进程通信。
    实现 MCP 协议的 initialize / tools/list / tools/call 等方法。
    """

    def __init__(
        self,
        server_id: str,
        command: str,
        args: list[str],
        env: dict[str, str] | None = None,
    ):
        """
        初始化 MCP 客户端。

        参数:
            server_id: 服务器标识符
            command: 启动命令
            args: 命令参数
            env: 额外环境变量
        """
        self.server_id = server_id
        self.command = command
        self.args = args
        self.env = env or {}
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._lock = threading.Lock()
        self.tools: list[dict] = []
        self._running = False

    def _next_id(self) -> int:
        """线程安全的请求 ID 生成。"""
        with self._lock:
            self._request_id += 1
            return self._request_id

    def start(self) -> bool:
        """启动 MCP 服务器进程并完成握手。"""
        try:
            env = {**os.environ, **self.env}
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                bufsize=1,
            )
            self._running = True

            # initialize 握手
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "TinyClaw", "version": "0.12"},
            })
            if result is None:
                print(f"  [warn] MCP 服务器 {self.server_id} 初始化失败")
                self.stop()
                return False

            # 发送 initialized 通知
            self._send_notification("notifications/initialized", {})
            print(f"  [mcp] 服务器 {self.server_id} 已启动")
            return True
        except Exception as e:
            print(f"  [warn] MCP 服务器 {self.server_id} 启动失败: {e}")
            return False

    def _send_request(self, method: str, params: dict, timeout: float = 10.0) -> dict | None:
        """发送 JSON-RPC 请求并等待响应。"""
        if not self.process or not self.process.stdin or not self.process.stdout:
            return None
        req_id = self._next_id()
        request = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        try:
            line = json.dumps(request) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()
            response_line = self.process.stdout.readline()
            if not response_line:
                return None
            response = json.loads(response_line.strip())
            if "error" in response:
                print(f"  [warn] MCP RPC 错误: {response['error']}")
                return None
            return response.get("result", {})
        except Exception as e:
            print(f"  [warn] MCP 请求失败 ({method}): {e}")
            return None

    def _send_notification(self, method: str, params: dict) -> None:
        """发送 JSON-RPC 通知（无需响应）。"""
        if not self.process or not self.process.stdin:
            return
        notification = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            line = json.dumps(notification) + "\n"
            self.process.stdin.write(line)
            self.process.stdin.flush()
        except Exception:
            pass

    def list_tools(self) -> list[dict]:
        """获取 MCP 服务器提供的工具列表。"""
        result = self._send_request("tools/list", {})
        if result and "tools" in result:
            self.tools = result["tools"]
            return self.tools
        return []

    def call_tool(self, tool_name: str, arguments: dict) -> str:
        """
        调用 MCP 服务器上的工具。

        参数:
            tool_name: 工具名称
            arguments: 工具参数

        返回:
            工具执行结果文本
        """
        result = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        if result is None:
            return f"MCP 工具调用失败: {tool_name}"
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", str(c)) for c in content if isinstance(c, dict)]
            return "\n".join(texts) if texts else json.dumps(result)
        return str(content)

    def stop(self) -> None:
        """停止 MCP 服务器进程。"""
        self._running = False
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.wait(timeout=5)
            except Exception:
                self.process.kill()
            self.process = None

    @property
    def is_running(self) -> bool:
        """检查服务器进程是否仍在运行。"""
        if not self.process:
            return False
        return self.process.poll() is None
