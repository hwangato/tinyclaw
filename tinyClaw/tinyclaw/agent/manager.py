"""
多 Agent 管理模块
=================
管理多个 Agent 实例，支持不同人格（SOUL.md）、模型、配置。
根据 agent_id 路由消息到对应的 AgentLoop。
"""

from pathlib import Path
from typing import Optional

from tinyclaw.config import Config, AgentConfig
from tinyclaw.agent.loop import AgentLoop
from tinyclaw.agent.context import ContextBuilder
from tinyclaw.agent.hooks import HookSystem
from tinyclaw.agent.memory import MemoryManager
from tinyclaw.agent.skills import SkillsManager
from tinyclaw.provider.openai_compat import OpenAICompatProvider
from tinyclaw.store.sqlite import Store
from tinyclaw.tools.registry import ToolRegistry
from tinyclaw.policy.engine import PolicyEngine


class AgentManager:
    """
    多 Agent 管理器。

    根据配置创建多个 AgentLoop 实例，每个 Agent 可以有：
    - 独立的人格（SOUL.md / IDENTITY.md）
    - 独立的模型
    - 独立的配置参数

    消息通过 agent_id 路由到对应的 Agent。
    """

    def __init__(
        self,
        config: Config,
        provider: OpenAICompatProvider,
        store: Store,
        tool_registry: ToolRegistry,
        hook_system: HookSystem,
        policy_engine: PolicyEngine,
        plugin_info_fn=None,
    ):
        """
        初始化 Agent 管理器。

        参数:
            config: 全局配置
            provider: LLM Provider
            store: 持久化存储
            tool_registry: 工具注册表
            hook_system: 钩子系统
            policy_engine: 策略引擎
            plugin_info_fn: 获取插件信息的回调
        """
        self.config = config
        self.provider = provider
        self.store = store
        self.tool_registry = tool_registry
        self.hook_system = hook_system
        self.policy_engine = policy_engine
        self._plugin_info_fn = plugin_info_fn
        self._agents: dict[str, AgentLoop] = {}
        self._agent_configs: dict[str, AgentConfig] = {}

        # 初始化所有配置的 Agent
        self._init_agents()

    def _init_agents(self) -> None:
        """根据配置创建所有 Agent 实例。"""
        for agent_cfg in self.config.agents:
            self._create_agent(agent_cfg)

    def _create_agent(self, agent_cfg: AgentConfig) -> AgentLoop:
        """
        创建单个 Agent 实例。

        参数:
            agent_cfg: Agent 配置

        返回:
            AgentLoop 实例
        """
        memory_mgr = MemoryManager(
            self.config.workdir / "workspace" / f"MEMORY_{agent_cfg.id}.md"
            if agent_cfg.id != "default"
            else self.config.workdir / "workspace" / "MEMORY.md"
        )
        skills_mgr = SkillsManager(self.config.skills_dir)

        context_builder = ContextBuilder(
            agent_config=agent_cfg,
            workdir=self.config.workdir,
            memory_mgr=memory_mgr,
            skills_mgr=skills_mgr,
        )

        agent_loop = AgentLoop(
            agent_config=agent_cfg,
            provider=self.provider,
            store=self.store,
            tool_registry=self.tool_registry,
            hook_system=self.hook_system,
            context_builder=context_builder,
            policy_engine=self.policy_engine,
            plugin_info_fn=self._plugin_info_fn,
        )

        self._agents[agent_cfg.id] = agent_loop
        self._agent_configs[agent_cfg.id] = agent_cfg
        return agent_loop

    def get_agent(self, agent_id: str = "default") -> AgentLoop:
        """
        获取指定 Agent 实例。

        参数:
            agent_id: Agent ID（默认 "default"）

        返回:
            AgentLoop 实例
        """
        if agent_id not in self._agents:
            # 回退到默认 Agent
            agent_id = "default"
        if agent_id not in self._agents:
            # 如果连默认 Agent 都没有，创建一个
            default_cfg = AgentConfig(id="default", name="TinyClaw")
            return self._create_agent(default_cfg)
        return self._agents[agent_id]

    def run(self, user_message: str, chat_id: str = "default", agent_id: str = "default") -> str:
        """
        调用指定 Agent 处理消息。

        参数:
            user_message: 用户消息
            chat_id: 会话 ID
            agent_id: Agent ID

        返回:
            Agent 回复文本
        """
        agent = self.get_agent(agent_id)
        return agent.run(user_message, chat_id)

    def list_agents(self) -> str:
        """列出所有 Agent 及其状态。"""
        if not self._agent_configs:
            return "没有已配置的 Agent"
        lines = []
        for aid, cfg in self._agent_configs.items():
            model = cfg.model or self.provider.default_model
            lines.append(
                f"  [{aid}] {cfg.name} | model={model} | "
                f"max_tokens={cfg.max_tokens}"
            )
        return "\n".join(lines)

    @property
    def agent_ids(self) -> list[str]:
        """获取所有 Agent ID 列表。"""
        return list(self._agents.keys())
