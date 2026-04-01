"""
沙盒模块
========
Docker 容器沙盒，用于安全执行不可信代码。
"""

from tinyclaw.sandbox.docker import DockerSandbox

__all__ = ["DockerSandbox"]
