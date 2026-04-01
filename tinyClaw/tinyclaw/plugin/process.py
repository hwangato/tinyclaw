"""
插件子进程管理
==============
管理单个插件子进程的生命周期。
通过 stdin/stdout 使用 JSON-RPC 2.0 协议通信。
支持异步通知处理。
"""

import os
import subprocess
import threading
from typing import Callable, Optional

from tinyclaw.plugin.protocol import (
    make_jsonrpc_request,
    make_jsonrpc_notification,
    parse_jsonrpc_response,
)


class PluginProcess:
    """
    插件子进程管理器。

    功能：
    - 启动插件进程
    - 发送 JSON-RPC 请求并等待响应
    - 发送通知（fire and forget）
    - 处理插件发来的异步通知
    - 优雅关闭
    """

    def __init__(
        self,
        plugin_id: str,
        command: str,
        args: list[str],
        working_dir: str | None = None,
        env: dict[str, str] | None = None,
    ):
        """
        初始化插件进程。

        参数:
            plugin_id: 插件 ID
            command: 启动命令
            args: 命令参数
            working_dir: 工作目录
            env: 额外环境变量
        """
        self.plugin_id = plugin_id
        self.command = command
        self.args = args
        self.working_dir = working_dir
        self.env = env or {}
        self.process: subprocess.Popen | None = None
        self._request_id = 0
        self._id_lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._running = False
        self._notification_handlers: dict[str, Callable] = {}
        self._reader_thread: threading.Thread | None = None
        self._pending_responses: dict[int, threading.Event] = {}
        self._response_data: dict[int, dict] = {}
        self._pending_lock = threading.Lock()

    def _next_id(self) -> int:
        """线程安全的自增请求 ID。"""
        with self._id_lock:
            self._request_id += 1
            return self._request_id

    def start(self) -> bool:
        """启动插件子进程。"""
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
                cwd=self.working_dir,
            )
            self._running = True
            # 启动后台读取线程
            self._reader_thread = threading.Thread(
                target=self._read_loop,
                daemon=True,
                name=f"plugin-{self.plugin_id}-reader",
            )
            self._reader_thread.start()
            return True
        except Exception as e:
            print(f"  [warn] 插件 {self.plugin_id} 启动失败: {e}")
            return False

    def _read_loop(self) -> None:
        """后台线程：从 stdout 读取数据，分发响应和通知。"""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                data = parse_jsonrpc_response(line)
                if data is None:
                    continue

                if "id" in data and data["id"] is not None:
                    # 响应
                    req_id = data["id"]
                    with self._pending_lock:
                        if req_id in self._pending_responses:
                            self._response_data[req_id] = data
                            self._pending_responses[req_id].set()
                elif "method" in data:
                    # 通知
                    method = data["method"]
                    params = data.get("params", {})
                    handler = self._notification_handlers.get(method)
                    if handler:
                        try:
                            handler(method, params)
                        except Exception as e:
                            print(f"  [warn] 插件 {self.plugin_id} 通知处理出错 ({method}): {e}")
            except Exception:
                if self._running:
                    break

    def on_notification(self, method: str, handler: Callable) -> None:
        """注册通知处理器。"""
        self._notification_handlers[method] = handler

    def call(self, method: str, params: dict, timeout: float = 10.0) -> dict | None:
        """
        发送 JSON-RPC 请求并阻塞等待响应。

        参数:
            method: 方法名
            params: 参数字典
            timeout: 超时秒数

        返回:
            result 字典，或 None（出错/超时）
        """
        if not self.process or not self.process.stdin:
            return None

        req_id = self._next_id()
        event = threading.Event()
        with self._pending_lock:
            self._pending_responses[req_id] = event

        request_str = make_jsonrpc_request(method, params, req_id) + "\n"
        try:
            with self._io_lock:
                self.process.stdin.write(request_str)
                self.process.stdin.flush()
        except Exception as e:
            with self._pending_lock:
                self._pending_responses.pop(req_id, None)
            print(f"  [warn] 插件 {self.plugin_id} 发送请求失败: {e}")
            return None

        if not event.wait(timeout=timeout):
            with self._pending_lock:
                self._pending_responses.pop(req_id, None)
            print(f"  [warn] 插件 {self.plugin_id} 请求超时 ({method})")
            return None

        with self._pending_lock:
            self._pending_responses.pop(req_id, None)
            data = self._response_data.pop(req_id, None)

        if data is None:
            return None
        if "error" in data:
            print(f"  [warn] 插件 {self.plugin_id} RPC 错误: {data['error']}")
            return None
        return data.get("result", {})

    def send_notification(self, method: str, params: dict) -> None:
        """发送通知（fire and forget）。"""
        if not self.process or not self.process.stdin:
            return
        notification_str = make_jsonrpc_notification(method, params) + "\n"
        try:
            with self._io_lock:
                self.process.stdin.write(notification_str)
                self.process.stdin.flush()
        except Exception:
            pass

    def shutdown(self, timeout: float = 5.0) -> None:
        """
        优雅关闭插件进程。

        步骤:
        1. 发送 shutdown RPC 请求
        2. 关闭 stdin
        3. 等待进程退出
        4. 超时则强制 kill
        """
        self._running = False
        if not self.process:
            return

        # 发送 shutdown 请求
        try:
            req_id = self._next_id()
            request_str = make_jsonrpc_request("shutdown", {}, req_id) + "\n"
            if self.process.stdin:
                self.process.stdin.write(request_str)
                self.process.stdin.flush()
        except Exception:
            pass

        # 关闭 stdin
        try:
            if self.process.stdin:
                self.process.stdin.close()
        except Exception:
            pass

        # 等待退出
        try:
            self.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"  [warn] 插件 {self.plugin_id} 未及时退出，强制终止")
            self.process.kill()
            try:
                self.process.wait(timeout=2)
            except Exception:
                pass

        self.process = None

    @property
    def is_running(self) -> bool:
        """检查插件进程是否仍在运行。"""
        if not self.process:
            return False
        return self.process.poll() is None
