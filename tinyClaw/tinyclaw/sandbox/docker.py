"""
Docker 沙盒执行器
=================
在 Docker 容器中安全执行不可信代码。
限制网络、内存、CPU、进程数，使用只读文件系统。
"""

import subprocess

from tinyclaw.agent.compaction import micro_compact
from tinyclaw.config import SandboxConfig


class DockerSandbox:
    """
    Docker 沙盒执行器。

    在隔离容器中执行代码，安全限制包括：
    - 禁用网络（--network=none）
    - 内存限制（默认 128m）
    - CPU 限制（默认 0.5 核）
    - 进程数限制（64）
    - 只读文件系统（仅 /tmp 可写）
    """

    def __init__(self, config: SandboxConfig | None = None):
        """
        初始化沙盒。

        参数:
            config: 沙盒配置
        """
        self.config = config or SandboxConfig()
        self._available: bool | None = None

    def is_available(self) -> bool:
        """检查 Docker 是否可用。"""
        if self._available is None:
            try:
                result = subprocess.run(
                    ["docker", "info"],
                    capture_output=True, text=True, timeout=5,
                )
                self._available = result.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._available = False
        return self._available

    def execute(self, code: str, language: str = "python") -> str:
        """
        在 Docker 容器中执行代码。

        参数:
            code: 要执行的代码
            language: 编程语言（python / bash）

        返回:
            执行结果文本
        """
        if not self.config.enabled:
            return "(沙盒已禁用)"

        if not self.is_available():
            return "(Docker 不可用，无法执行沙盒代码)"

        # 根据语言选择命令
        if language == "python":
            cmd_in_container = ["python3", "-c", code]
        elif language == "bash":
            cmd_in_container = ["bash", "-c", code]
        else:
            return f"不支持的语言: {language}"

        docker_cmd = [
            "docker", "run", "--rm",
            f"--network=none",
            f"--memory={self.config.memory_limit}",
            f"--cpus={self.config.cpu_limit}",
            "--pids-limit=64",
            "--read-only",
            "--tmpfs=/tmp:rw,size=64m",
            self.config.image,
        ] + cmd_in_container

        try:
            result = subprocess.run(
                docker_cmd,
                capture_output=True, text=True,
                timeout=self.config.timeout,
            )
            output = result.stdout + result.stderr
            return micro_compact(output) if output.strip() else "(无输出)"
        except subprocess.TimeoutExpired:
            return f"(沙盒执行超时 {self.config.timeout}s)"
        except Exception as e:
            return f"(沙盒执行出错: {e})"
