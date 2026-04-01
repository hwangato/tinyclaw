"""
工具注册表模块
==============
全局工具注册表，支持装饰器注册、动态注册、工具执行调度。
"""

import json
from pathlib import Path
from typing import Any, Callable

from tinyclaw.agent.compaction import micro_compact


class ToolRegistry:
    """
    工具注册表。

    集中管理所有工具的 schema 定义和执行函数。
    支持装饰器注册、动态注册（MCP / 插件）、安全路径检查。
    """

    def __init__(self, workdir: Path | None = None):
        """
        初始化工具注册表。

        参数:
            workdir: 工作目录（用于安全路径检查）
        """
        self._registry: dict[str, dict] = {}
        self.workdir = workdir or Path(".").resolve()

    def register(self, name: str, description: str, parameters: dict, func: Callable) -> None:
        """
        注册一个工具。

        参数:
            name: 工具名称
            description: 工具描述
            parameters: JSON Schema 参数定义
            func: 工具执行函数
        """
        self._registry[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "func": func,
        }

    def tool(self, name: str, description: str, parameters: dict) -> Callable:
        """
        工具注册装饰器。

        用法:
            @registry.tool("bash", "执行命令", {...})
            def bash(command: str) -> str:
                ...
        """
        def decorator(func: Callable) -> Callable:
            self.register(name, description, parameters, func)
            return func
        return decorator

    def unregister(self, name: str) -> bool:
        """注销一个工具。"""
        if name in self._registry:
            del self._registry[name]
            return True
        return False

    def get_schemas(self) -> list[dict]:
        """获取所有工具的 JSON Schema 列表。"""
        return [t["schema"] for t in self._registry.values()]

    def execute(self, name: str, arguments: dict, depth: int = 0) -> str:
        """
        执行指定工具。

        参数:
            name: 工具名称
            arguments: 工具参数
            depth: 当前嵌套深度（用于子 Agent）

        返回:
            工具执行结果字符串
        """
        entry = self._registry.get(name)
        if not entry:
            return f"未知工具: {name}"
        try:
            func = entry["func"]
            # 子 Agent 工具需要传递 depth
            if name == "spawn_subagent":
                return func(**arguments, _depth=depth)
            return func(**arguments)
        except Exception as e:
            return f"工具执行出错: {e}"

    def safe_path(self, filepath: str) -> Path:
        """
        安全路径检查：防止目录遍历。

        参数:
            filepath: 相对路径

        返回:
            解析后的绝对路径

        异常:
            PermissionError: 路径越界
        """
        resolved = (self.workdir / filepath).resolve()
        if not str(resolved).startswith(str(self.workdir)):
            raise PermissionError(f"路径越界: {filepath}")
        return resolved

    @property
    def tool_names(self) -> list[str]:
        """获取所有已注册的工具名称。"""
        return list(self._registry.keys())

    @property
    def tool_count(self) -> int:
        """获取已注册的工具数量。"""
        return len(self._registry)

    def list_tools(self) -> str:
        """列出所有已注册工具的概要信息。"""
        if not self._registry:
            return "没有已注册的工具"
        lines = []
        for name, entry in self._registry.items():
            desc = entry["schema"]["function"].get("description", "")
            lines.append(f"  [{name}] {desc[:60]}")
        return "\n".join(lines)
