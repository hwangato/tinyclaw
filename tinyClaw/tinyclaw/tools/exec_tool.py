"""
Shell 执行工具
==============
提供 bash 命令执行和沙盒执行工具。
集成策略引擎检查和 Docker 沙盒。
"""

import subprocess
from typing import TYPE_CHECKING

from tinyclaw.agent.compaction import micro_compact
from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from tinyclaw.policy.engine import PolicyEngine
    from tinyclaw.sandbox.docker import DockerSandbox


def register_exec_tools(
    registry: ToolRegistry,
    policy_engine: "PolicyEngine",
    sandbox: "DockerSandbox",
) -> None:
    """
    注册 shell 执行相关工具。

    参数:
        registry: 工具注册表
        policy_engine: 策略引擎
        sandbox: Docker 沙盒
    """

    @registry.tool("bash", "在本地 shell 中执行命令。策略引擎会检查命令安全性。", {
        "type": "object",
        "properties": {"command": {"type": "string", "description": "要执行的 shell 命令"}},
        "required": ["command"],
    })
    def bash(command: str) -> str:
        """执行 shell 命令，受策略引擎管控。"""
        action, reason = policy_engine.check("bash", {"command": command})
        if action == "deny":
            return f"策略拒绝: {reason}"
        if action == "sandbox":
            print(f"  [policy] 沙盒执行: {reason}")
            return sandbox.execute(command, language="bash")
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=30
            )
            output = result.stdout + result.stderr
            return micro_compact(output) if output else "(无输出)"
        except subprocess.TimeoutExpired:
            return "(命令超时)"
        except Exception as e:
            return f"命令执行出错: {e}"

    @registry.tool("sandbox_exec", "在 Docker 沙盒中执行代码。", {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "要执行的代码"},
            "language": {
                "type": "string",
                "enum": ["python", "bash"],
                "default": "python",
                "description": "编程语言",
            },
        },
        "required": ["code"],
    })
    def sandbox_exec(code: str, language: str = "python") -> str:
        """在 Docker 沙盒中执行不可信代码。"""
        return sandbox.execute(code, language)
