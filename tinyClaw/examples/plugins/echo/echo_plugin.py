#!/usr/bin/env python3
"""
TinyClaw 示例插件 — Echo（回显）
================================
这是一个最小化的 tool 类型插件，演示 JSON-RPC 2.0 插件协议。

通信方式：通过 stdin/stdout 使用 JSON-RPC 2.0 协议。
每一行是一个完整的 JSON 对象。

支持的方法：
- initialize: 初始化插件，接收配置
- tool.list: 返回插件提供的工具列表
- tool.execute: 执行指定工具
- shutdown: 优雅关闭插件

运行方式：由 TinyClaw PluginManager 自动启动，不需要手动运行。
测试方式：可手动运行并通过 stdin 输入 JSON-RPC 请求来测试。
"""

import json
import sys


class EchoPlugin:
    """Echo 插件：回显输入文本。"""

    def __init__(self):
        self.config = {}
        self.prefix = "[Echo]"
        self.running = True

    def handle_request(self, request: dict) -> dict | None:
        """
        处理一个 JSON-RPC 2.0 请求。
        返回响应字典，或 None（如果是通知）。
        """
        method = request.get("method", "")
        params = request.get("params", {})
        req_id = request.get("id")  # 如果没有 id，则为通知

        # 路由到对应的处理方法
        if method == "initialize":
            result = self._handle_initialize(params)
        elif method == "tool.list":
            result = self._handle_tool_list(params)
        elif method == "tool.execute":
            result = self._handle_tool_execute(params)
        elif method == "shutdown":
            result = self._handle_shutdown(params)
        else:
            # 未知方法
            if req_id is not None:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {
                        "code": -32601,
                        "message": f"未知方法: {method}",
                    },
                }
            return None

        # 如果是通知（无 id），不返回响应
        if req_id is None:
            return None

        # 构造成功响应
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": result,
        }

    def _handle_initialize(self, params: dict) -> dict:
        """处理初始化请求：接收配置，返回插件能力。"""
        self.config = params.get("config", {})
        self.prefix = self.config.get("prefix", "[Echo]")
        return {
            "status": "ok",
            "name": "Echo Plugin",
            "version": "1.0.0",
            "capabilities": ["tool"],
        }

    def _handle_tool_list(self, params: dict) -> dict:
        """返回插件提供的工具列表。"""
        return {
            "tools": [
                {
                    "name": "echo",
                    "description": "回显输入文本，可添加前缀。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "要回显的文本",
                            },
                            "uppercase": {
                                "type": "boolean",
                                "description": "是否转为大写",
                                "default": False,
                            },
                        },
                        "required": ["text"],
                    },
                }
            ]
        }

    def _handle_tool_execute(self, params: dict) -> dict:
        """执行指定的工具。"""
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "echo":
            return self._execute_echo(arguments)
        else:
            return {"error": f"未知工具: {tool_name}"}

    def _execute_echo(self, arguments: dict) -> dict:
        """执行 echo 工具：回显输入文本。"""
        text = arguments.get("text", "")
        uppercase = arguments.get("uppercase", False)

        if uppercase:
            text = text.upper()

        result = f"{self.prefix} {text}"
        return {"result": result}

    def _handle_shutdown(self, params: dict) -> dict:
        """处理关闭请求：标记停止运行。"""
        self.running = False
        return {"status": "ok", "message": "插件已关闭"}

    def run(self):
        """
        插件主循环：从 stdin 逐行读取 JSON-RPC 请求，处理后写入 stdout。
        """
        while self.running:
            try:
                line = sys.stdin.readline()
                if not line:
                    # stdin 已关闭
                    break
                line = line.strip()
                if not line:
                    continue

                # 解析 JSON-RPC 请求
                try:
                    request = json.loads(line)
                except json.JSONDecodeError:
                    # 无效 JSON，发送解析错误
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {
                            "code": -32700,
                            "message": "JSON 解析错误",
                        },
                    }
                    sys.stdout.write(json.dumps(error_response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                    continue

                # 处理请求
                response = self.handle_request(request)

                # 如果有响应（非通知），写入 stdout
                if response is not None:
                    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()

            except (EOFError, BrokenPipeError):
                break
            except Exception as e:
                # 内部错误
                error_response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32603,
                        "message": f"内部错误: {e}",
                    },
                }
                try:
                    sys.stdout.write(json.dumps(error_response, ensure_ascii=False) + "\n")
                    sys.stdout.flush()
                except Exception:
                    break


if __name__ == "__main__":
    plugin = EchoPlugin()
    plugin.run()
