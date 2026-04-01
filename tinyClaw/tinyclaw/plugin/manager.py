"""
插件管理器
==========
发现、加载、管理插件生命周期。
支持三种插件类型：tool / channel / hook。

插件目录结构:
    plugins/
        my-plugin/
            plugin.json     # 插件清单
            main.py         # 插件入口
"""

import asyncio
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tinyclaw.bus import MessageBus, InboundMessage
from tinyclaw.channels.base import Channel
from tinyclaw.plugin.process import PluginProcess
from tinyclaw.agent.hooks import HookSystem, HOOK_POINTS

if TYPE_CHECKING:
    from tinyclaw.tools.registry import ToolRegistry


@dataclass
class PluginManifest:
    """插件清单数据结构（对应 plugin.json）。"""
    id: str
    name: str
    version: str
    type: str                    # tool / channel / hook
    command: str
    args: list[str] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    enabled: bool = True
    description: str = ""


class PluginChannel(Channel):
    """
    将 channel 类型插件适配为 Channel 接口。

    接收插件发来的 message.inbound 通知，转发到 MessageBus。
    """

    def __init__(self, plugin_id: str, plugin_process: PluginProcess):
        self._plugin_id = plugin_id
        self._plugin = plugin_process
        self._bus: MessageBus | None = None
        self._running = False

    @property
    def name(self) -> str:
        return f"plugin_{self._plugin_id}"

    async def connect(self, bus: MessageBus) -> None:
        """连接到消息总线，注册通知处理器。"""
        self._bus = bus
        self._running = True
        self._plugin.on_notification("message.inbound", self._handle_inbound)
        self._plugin.send_notification("channel.start", {})

    def _handle_inbound(self, method: str, params: dict) -> None:
        """处理插件发来的入站消息通知。"""
        if not self._bus or not self._running:
            return
        msg = InboundMessage(
            channel=self.name,
            chat_id=params.get("chat_id", "default"),
            user_id=params.get("user_id", "unknown"),
            text=params.get("text", ""),
            sender_name=params.get("sender_name", ""),
        )
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(self._bus.publish_inbound(msg), loop)
            else:
                self._bus.inbound.put_nowait(msg)
        except Exception as e:
            print(f"  [warn] 插件 Channel {self._plugin_id} 入站消息处理失败: {e}")

    async def disconnect(self) -> None:
        """断开连接。"""
        self._running = False
        self._plugin.send_notification("channel.stop", {})

    async def send_message(self, chat_id: str, text: str, reply_to: str = "") -> None:
        """通过插件发送出站消息。"""
        self._plugin.call("channel.send", {
            "chat_id": chat_id,
            "text": text,
            "reply_to": reply_to,
        })


class PluginManager:
    """
    插件管理器。

    功能：
    - 扫描插件目录发现 plugin.json 清单
    - 启动已启用的插件子进程
    - 根据类型注册工具 / 通道 / 钩子
    - 管理插件生命周期
    """

    def __init__(
        self,
        plugins_dir: str | Path = "plugins",
        hook_system: HookSystem | None = None,
        tool_registry: "ToolRegistry | None" = None,
    ):
        """
        初始化插件管理器。

        参数:
            plugins_dir: 插件目录路径
            hook_system: 钩子系统
            tool_registry: 工具注册表
        """
        self.plugins_dir = Path(plugins_dir).resolve()
        self.hook_system = hook_system or HookSystem()
        self.tool_registry = tool_registry
        self._manifests: dict[str, PluginManifest] = {}
        self._processes: dict[str, PluginProcess] = {}
        self._channels: dict[str, PluginChannel] = {}
        self._lock = threading.Lock()

    def discover(self) -> list[PluginManifest]:
        """扫描插件目录，发现所有插件清单。"""
        manifests = []
        if not self.plugins_dir.exists():
            print(f"  [plugin] 插件目录不存在: {self.plugins_dir}")
            return manifests

        for plugin_dir in sorted(self.plugins_dir.iterdir()):
            manifest_file = plugin_dir / "plugin.json"
            if not manifest_file.exists():
                continue
            try:
                data = json.loads(manifest_file.read_text(encoding="utf-8"))
                manifest = PluginManifest(
                    id=data.get("id", plugin_dir.name),
                    name=data.get("name", plugin_dir.name),
                    version=data.get("version", "0.0.0"),
                    type=data.get("type", "tool"),
                    command=data.get("command", ""),
                    args=data.get("args", []),
                    config=data.get("config", {}),
                    enabled=data.get("enabled", True),
                    description=data.get("description", ""),
                )
                manifests.append(manifest)
                self._manifests[manifest.id] = manifest
                print(f"  [plugin] 发现: {manifest.name} v{manifest.version} ({manifest.type})")
            except Exception as e:
                print(f"  [warn] 加载插件清单失败 ({plugin_dir.name}): {e}")

        return manifests

    def start_all(self) -> list[str]:
        """启动所有已发现且已启用的插件。"""
        started = []
        for pid, manifest in self._manifests.items():
            if not manifest.enabled:
                print(f"  [plugin] {manifest.name} 已禁用，跳过")
                continue
            if not manifest.command:
                print(f"  [warn] 插件 {manifest.name} 缺少 command 配置")
                continue
            if self._start_plugin(manifest):
                started.append(pid)
        return started

    def _start_plugin(self, manifest: PluginManifest) -> bool:
        """启动单个插件。"""
        plugin_dir = self.plugins_dir / manifest.id
        process = PluginProcess(
            plugin_id=manifest.id,
            command=manifest.command,
            args=manifest.args,
            working_dir=str(plugin_dir),
        )

        if not process.start():
            return False

        result = process.call("initialize", {
            "plugin_id": manifest.id,
            "config": manifest.config,
        })
        if result is None:
            print(f"  [warn] 插件 {manifest.name} 初始化失败")
            process.shutdown()
            return False

        with self._lock:
            self._processes[manifest.id] = process

        print(f"  [plugin] {manifest.name} 已启动")

        if manifest.type == "tool":
            self._register_tool_plugin(manifest, process)
        elif manifest.type == "channel":
            self._register_channel_plugin(manifest, process)
        elif manifest.type == "hook":
            self._register_hook_plugin(manifest, process)
        else:
            print(f"  [warn] 未知插件类型: {manifest.type}")

        return True

    def _register_tool_plugin(self, manifest: PluginManifest, process: PluginProcess) -> None:
        """注册 tool 类型插件。"""
        if not self.tool_registry:
            print(f"  [warn] 工具注册表未设置，无法注册插件工具")
            return

        result = process.call("tool.list", {})
        if result is None:
            print(f"  [warn] 插件 {manifest.name} 获取工具列表失败")
            return

        tools = result.get("tools", [])
        for tool_def in tools:
            original_name = tool_def.get("name", "")
            if not original_name:
                continue
            tool_name = f"plugin_{manifest.id}_{original_name}"
            description = tool_def.get("description", f"插件工具: {original_name}")
            parameters = tool_def.get("parameters", {
                "type": "object", "properties": {}, "required": [],
            })

            def make_plugin_tool_caller(proc: PluginProcess, tname: str):
                def caller(**kwargs) -> str:
                    res = proc.call("tool.execute", {
                        "name": tname,
                        "arguments": kwargs,
                    })
                    if res is None:
                        return f"插件工具执行失败: {tname}"
                    return res.get("result", str(res))
                return caller

            self.tool_registry.register(
                name=tool_name,
                description=f"[插件:{manifest.id}] {description}",
                parameters=parameters,
                func=make_plugin_tool_caller(process, original_name),
            )
            print(f"    [plugin] 注册工具: {tool_name}")

        print(f"  [plugin] {manifest.name}: 注册了 {len(tools)} 个工具")

    def _register_channel_plugin(self, manifest: PluginManifest, process: PluginProcess) -> None:
        """注册 channel 类型插件。"""
        channel = PluginChannel(manifest.id, process)
        with self._lock:
            self._channels[manifest.id] = channel
        print(f"  [plugin] {manifest.name}: 已注册为 Channel")

    def _register_hook_plugin(self, manifest: PluginManifest, process: PluginProcess) -> None:
        """注册 hook 类型插件。"""
        result = process.call("hook.list", {})
        if result is None:
            hook_points = HOOK_POINTS
        else:
            hook_points = result.get("hooks", HOOK_POINTS)

        def make_hook_handler(proc: PluginProcess, plugin_name: str):
            def handler(hook_point: str, data: dict) -> dict:
                res = proc.call("hook.fire", {
                    "hook_point": hook_point,
                    "data": data,
                }, timeout=5.0)
                if res is not None and isinstance(res, dict):
                    return res.get("data", data)
                return data
            return handler

        handler = make_hook_handler(process, manifest.name)
        for hp in hook_points:
            if hp in HOOK_POINTS:
                self.hook_system.register(hp, handler)
        print(f"  [plugin] {manifest.name}: 注册了 {len(hook_points)} 个钩子")

    def get_channels(self) -> list[PluginChannel]:
        """获取所有已注册的 Channel 插件。"""
        with self._lock:
            return list(self._channels.values())

    def get_plugin_info(self) -> str:
        """获取所有插件的状态信息。"""
        if not self._manifests:
            return "没有已加载的插件"
        lines = []
        for pid, manifest in self._manifests.items():
            status = "运行中" if pid in self._processes and self._processes[pid].is_running else "已停止"
            lines.append(
                f"  [{pid}] {manifest.name} v{manifest.version} "
                f"| 类型={manifest.type} | 状态={status}"
            )
        return "\n".join(lines)

    def stop_all(self) -> None:
        """停止所有插件进程。"""
        with self._lock:
            for pid, process in self._processes.items():
                print(f"  [plugin] 正在停止: {pid}")
                process.shutdown()
            self._processes.clear()
            self._channels.clear()
        print("  [plugin] 所有插件已停止")
