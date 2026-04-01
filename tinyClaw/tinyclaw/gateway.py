"""
网关模块
========
主编排器：连接所有通道、Agent、调度器、插件管理器。
处理消息路由和生命周期管理。
"""

import asyncio
from typing import Optional

from tinyclaw.bus import MessageBus, InboundMessage, OutboundMessage
from tinyclaw.channels.base import Channel
from tinyclaw.config import Config, ChannelConfig
from tinyclaw.agent.manager import AgentManager
from tinyclaw.agent.hooks import HookSystem
from tinyclaw.agent.heartbeat import HeartbeatManager
from tinyclaw.cron.scheduler import CronScheduler
from tinyclaw.store.sqlite import Store
from tinyclaw.provider.openai_compat import OpenAICompatProvider
from tinyclaw.tools.registry import ToolRegistry
from tinyclaw.policy.engine import PolicyEngine
from tinyclaw.sandbox.docker import DockerSandbox
from tinyclaw.mcp.manager import MCPManager
from tinyclaw.plugin.manager import PluginManager


class Gateway:
    """
    网关：TinyClaw 的核心编排器。

    职责:
    - 初始化所有组件（Provider、Store、Agent、Channel 等）
    - 连接所有通道到 MessageBus
    - 路由入站消息到 Agent
    - 路由出站消息到对应通道
    - 管理组件生命周期
    """

    def __init__(self, config: Config):
        """
        初始化网关。

        参数:
            config: 全局配置
        """
        self.config = config
        self.bus = MessageBus()
        self._running = False

        # 初始化核心组件
        self.provider = OpenAICompatProvider(config.provider)
        self.store = Store(config.data_dir / "tinyclaw.db")
        self.hook_system = HookSystem()
        self.policy_engine = PolicyEngine(
            rules_path=config.policy.rules_path if config.policy.rules_path else None
        )
        self.sandbox = DockerSandbox(config.sandbox)
        self.tool_registry = ToolRegistry(workdir=config.workdir)

        # MCP 管理器
        self.mcp_manager = MCPManager(config.mcp.config_path)

        # 插件管理器
        self.plugin_manager = PluginManager(
            plugins_dir=config.plugins.plugins_dir,
            hook_system=self.hook_system,
            tool_registry=self.tool_registry,
        )

        # 注册内置工具（需要在 plugin_manager 初始化之后）
        self._register_tools()

        # Agent 管理器
        self.agent_manager = AgentManager(
            config=config,
            provider=self.provider,
            store=self.store,
            tool_registry=self.tool_registry,
            hook_system=self.hook_system,
            policy_engine=self.policy_engine,
            plugin_info_fn=self.plugin_manager.get_plugin_info,
        )

        # 定时调度器
        self.scheduler = CronScheduler(
            self.store, self.bus,
            poll_interval=config.cron.poll_interval,
        )

        # 心跳管理器
        self.heartbeat_manager = HeartbeatManager(self.bus)

        # 通道列表
        self.channels: dict[str, Channel] = {}

    def _register_tools(self) -> None:
        """注册所有内置工具。"""
        from tinyclaw.tools.exec_tool import register_exec_tools
        from tinyclaw.tools.file_tool import register_file_tools
        from tinyclaw.tools.web_tool import register_web_tools
        from tinyclaw.tools.memory_tool import register_memory_tools
        from tinyclaw.tools.message_tool import register_message_tools
        from tinyclaw.tools.subagent_tool import register_subagent_tools
        from tinyclaw.tools.cron_tool import register_cron_tools
        from tinyclaw.agent.memory import MemoryManager
        from tinyclaw.agent.skills import SkillsManager

        # Shell 执行
        register_exec_tools(self.tool_registry, self.policy_engine, self.sandbox)

        # 文件操作
        register_file_tools(self.tool_registry)

        # Web 工具
        register_web_tools(self.tool_registry, self.config.web)

        # 记忆工具
        memory_mgr = MemoryManager(self.config.workdir / "workspace" / "MEMORY.md")
        register_memory_tools(self.tool_registry, memory_mgr, self.store)

        # 跨通道消息
        register_message_tools(self.tool_registry, self.bus)

        # 子 Agent
        default_agent_cfg = self.config.agents[0] if self.config.agents else None
        if default_agent_cfg:
            register_subagent_tools(self.tool_registry, self.provider, default_agent_cfg)

        # 定时任务
        register_cron_tools(self.tool_registry, lambda: self.scheduler)

        # 技能加载
        skills_mgr = SkillsManager(self.config.skills_dir)
        self.tool_registry.register(
            "load_skill",
            "加载指定技能的详细指令。",
            {
                "type": "object",
                "properties": {"skill_id": {"type": "string", "description": "技能 ID"}},
                "required": ["skill_id"],
            },
            skills_mgr.load_skill,
        )

        # 上下文压缩
        self.tool_registry.register(
            "compact",
            "手动压缩当前对话上下文。",
            {"type": "object", "properties": {}, "required": []},
            lambda: "__COMPACT__",
        )

        # 策略列表
        self.tool_registry.register(
            "list_policies",
            "列出当前安全策略规则。",
            {"type": "object", "properties": {}, "required": []},
            self.policy_engine.list_rules,
        )

        # 插件列表
        self.tool_registry.register(
            "list_plugins",
            "列出所有已加载的插件及其状态。",
            {"type": "object", "properties": {}, "required": []},
            self.plugin_manager.get_plugin_info,
        )

        # 钩子列表
        self.tool_registry.register(
            "list_hooks",
            "列出所有已注册的钩子处理器。",
            {"type": "object", "properties": {}, "required": []},
            self.hook_system.list_hooks,
        )

    def _create_channels(self) -> list[Channel]:
        """根据配置创建所有通道实例。"""
        from tinyclaw.channels.cli import CLIChannel

        channels: list[Channel] = []
        for ch_cfg in self.config.channels:
            if not ch_cfg.enabled:
                continue
            ch = self._create_channel(ch_cfg)
            if ch:
                channels.append(ch)

        # 确保至少有一个 CLI 通道
        if not any(isinstance(ch, CLIChannel) for ch in channels):
            if not any(ch_cfg.type == "cli" for ch_cfg in self.config.channels):
                channels.insert(0, CLIChannel())

        # 添加插件通道
        for plugin_ch in self.plugin_manager.get_channels():
            channels.append(plugin_ch)

        return channels

    def _create_channel(self, config: ChannelConfig) -> Channel | None:
        """根据配置创建单个通道实例。"""
        ch_type = config.type.lower()

        if ch_type == "cli":
            from tinyclaw.channels.cli import CLIChannel
            return CLIChannel()
        elif ch_type == "telegram":
            if not config.token:
                print("  [warn] Telegram 通道缺少 token 配置")
                return None
            from tinyclaw.channels.telegram import TelegramChannel
            return TelegramChannel(config)
        elif ch_type == "discord":
            if not config.token:
                print("  [warn] Discord 通道缺少 token 配置")
                return None
            from tinyclaw.channels.discord import DiscordChannel
            return DiscordChannel(config)
        elif ch_type == "feishu":
            if not config.app_id or not config.app_secret:
                print("  [warn] 飞书通道缺少 app_id / app_secret 配置")
                return None
            from tinyclaw.channels.feishu import FeishuChannel
            return FeishuChannel(config)
        else:
            print(f"  [warn] 未知通道类型: {ch_type}")
            return None

    async def start(self) -> None:
        """启动网关：初始化所有组件，连接通道，开始消息循环。"""
        print("=" * 60)
        print(f"TinyClaw v{self._get_version()} — 模块化 AI Agent 框架")
        print("=" * 60)
        print()

        # 初始化 MCP
        print("  [init] 扫描 MCP 服务器...")
        self.mcp_manager.start_all(tool_registry=self.tool_registry)

        # 初始化插件
        if self.config.plugins.enabled:
            print(f"  [init] 扫描插件目录: {self.plugin_manager.plugins_dir}")
            manifests = self.plugin_manager.discover()
            if manifests:
                started = self.plugin_manager.start_all()
                print(f"  [init] 已启动 {len(started)} 个插件")
            else:
                print("  [init] 未发现任何插件")

        # 创建并连接通道
        channel_list = self._create_channels()
        for ch in channel_list:
            await ch.connect(self.bus)
            self.channels[ch.name] = ch

        # 输出状态信息
        print(f"\n  已注册 {self.tool_registry.tool_count} 个工具: "
              f"{', '.join(self.tool_registry.tool_names)}")
        print(f"  已注册 {len(self.channels)} 个通道: "
              f"{', '.join(self.channels.keys())}")
        print(f"  已配置 {len(self.agent_manager.agent_ids)} 个 Agent: "
              f"{', '.join(self.agent_manager.agent_ids)}")
        print(f"  已加载 {len(self.scheduler.jobs)} 个定时任务")
        print(f"\n  钩子状态:")
        print(self.hook_system.list_hooks())
        print()
        print("-" * 60)
        print("使用说明：")
        print("  直接输入自然语言，Agent 会理解并执行你的请求。")
        print()
        print("  示例指令：")
        print("    > 列出当前目录下的所有文件")
        print("    > 帮我写一个 hello.py 文件")
        print("    > 搜索项目中包含 TODO 的文件")
        print("    > 创建一个每 5 分钟执行的定时任务，检查磁盘空间")
        print("    > 把这段代码的功能记到长期记忆里")
        print()
        print("  内置命令：")
        print("    quit / exit / q    退出 TinyClaw")
        print()
        print("  CLI 管理命令（另开终端执行）：")
        print("    tinyclaw agent list    列出所有 Agent")
        print("    tinyclaw tool list     列出所有工具")
        print("    tinyclaw cron list     列出定时任务")
        print("    tinyclaw plugin list   列出插件")
        print("    tinyclaw channel list  列出通道")
        print("-" * 60)

        self._running = True

        # 启动心跳
        await self.heartbeat_manager.start(self.config.agents)

        # 启动消息处理循环（任意一个退出则取消其余）
        tasks = [
            asyncio.create_task(self._process_inbound()),
            asyncio.create_task(self._route_outbound()),
            asyncio.create_task(self.scheduler.start()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass

    async def _process_inbound(self) -> None:
        """处理入站消息：路由到对应 Agent。"""
        while self._running:
            msg = await self.bus.inbound.get()

            if msg.text == "__QUIT__":
                self._running = False
                self.scheduler.stop()
                self.heartbeat_manager.stop()
                # 放入哨兵消息解除 _route_outbound 的阻塞
                await self.bus.publish_outbound(OutboundMessage(
                    channel="__quit__", chat_id="", text="",
                ))
                return

            # 确定目标 Agent
            agent_id = msg.agent_id or "default"

            # 在线程池中执行 Agent 循环（避免阻塞事件循环）
            loop = asyncio.get_event_loop()
            reply_text = await loop.run_in_executor(
                None,
                self.agent_manager.run,
                msg.text,
                msg.chat_id,
                agent_id,
            )

            await self.bus.publish_outbound(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                text=reply_text,
                reply_to=msg.message_id,
                agent_id=agent_id,
            ))

    async def _route_outbound(self) -> None:
        """路由出站消息到对应通道。"""
        while self._running:
            msg = await self.bus.outbound.get()
            if msg.channel == "__quit__":
                return
            ch = self.channels.get(msg.channel)
            if ch:
                await ch.send_message(msg.chat_id, msg.text, msg.reply_to)
            elif msg.channel == "cron":
                print(f"\n  [cron-reply] {msg.text[:200]}")
            elif msg.channel == "heartbeat":
                print(f"\n  [heartbeat-reply] {msg.text[:200]}")
            else:
                print(f"\n  [{msg.channel}] {msg.text[:200]}")

    async def stop(self) -> None:
        """停止网关和所有组件。"""
        self._running = False
        self.scheduler.stop()
        self.heartbeat_manager.stop()
        self.plugin_manager.stop_all()
        self.mcp_manager.stop_all()
        for ch in self.channels.values():
            await ch.disconnect()
        self.store.close()

    @staticmethod
    def _get_version() -> str:
        """获取版本号。"""
        try:
            from tinyclaw import __version__
            return __version__
        except ImportError:
            return "0.12.0"
