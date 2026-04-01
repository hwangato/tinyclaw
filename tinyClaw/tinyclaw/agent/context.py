"""
系统提示词组装模块
==================
负责组装 Agent 的系统提示词，整合 SOUL.md、IDENTITY.md、技能列表、
记忆、插件信息等内容。
"""

from pathlib import Path
from typing import Optional

from tinyclaw.config import AgentConfig
from tinyclaw.agent.memory import MemoryManager
from tinyclaw.agent.skills import SkillsManager


class ContextBuilder:
    """
    系统提示词构建器。

    从多个来源组装完整的系统提示词：
    - SOUL.md：Agent 的核心人格定义
    - IDENTITY.md：Agent 的身份信息
    - 技能列表
    - 长期记忆
    - 插件状态
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        workdir: Path,
        memory_mgr: MemoryManager,
        skills_mgr: SkillsManager,
    ):
        """
        初始化上下文构建器。

        参数:
            agent_config: Agent 配置
            workdir: 工作目录
            memory_mgr: 记忆管理器
            skills_mgr: 技能管理器
        """
        self.agent_config = agent_config
        self.workdir = workdir
        self.memory_mgr = memory_mgr
        self.skills_mgr = skills_mgr

    def build_system_prompt(self, plugin_info: str = "") -> str:
        """
        构建完整的系统提示词。

        参数:
            plugin_info: 插件状态信息

        返回:
            完整的系统提示词字符串
        """
        parts = []

        # 1. SOUL.md（核心人格）
        soul = self._load_soul()
        if soul:
            parts.append(soul)
        else:
            parts.append(self._default_soul())

        # 2. IDENTITY.md（身份信息）
        identity = self._load_identity()
        if identity:
            parts.append(f"\n{identity}")

        # 3. 工作目录
        parts.append(f"\n工作目录: {self.workdir}")

        # 4. 技能列表
        skills_prompt = self.skills_mgr.build_skills_prompt()
        if skills_prompt:
            parts.append(skills_prompt)

        # 5. 长期记忆
        memory_prompt = self._build_memory_prompt()
        if memory_prompt:
            parts.append(memory_prompt)

        # 6. 插件信息
        if plugin_info and plugin_info != "没有已加载的插件":
            parts.append(f"\n\n已加载的插件：\n{plugin_info}")

        return "\n".join(parts)

    def _load_soul(self) -> str:
        """加载 SOUL.md 文件。"""
        if self.agent_config.soul_path:
            soul_path = Path(self.agent_config.soul_path)
            if not soul_path.is_absolute():
                soul_path = self.workdir / soul_path
            if soul_path.exists():
                return soul_path.read_text(encoding="utf-8").strip()

        # 默认位置
        default_soul = self.workdir / "workspace" / "SOUL.md"
        if default_soul.exists():
            return default_soul.read_text(encoding="utf-8").strip()
        return ""

    def _load_identity(self) -> str:
        """加载 IDENTITY.md 文件。"""
        if self.agent_config.identity_path:
            id_path = Path(self.agent_config.identity_path)
            if not id_path.is_absolute():
                id_path = self.workdir / id_path
            if id_path.exists():
                return id_path.read_text(encoding="utf-8").strip()

        # 默认位置
        default_id = self.workdir / "workspace" / "IDENTITY.md"
        if default_id.exists():
            return default_id.read_text(encoding="utf-8").strip()
        return ""

    def _default_soul(self) -> str:
        """默认系统人格描述。"""
        name = self.agent_config.name
        return (
            f"你是 {name}，一个支持插件扩展的 AI 助手。\n"
            "你可以执行命令、操作文件、加载技能、委派子 Agent、管理定时任务、"
            "在沙盒中执行代码、查看安全策略、管理插件、搜索网页。"
        )

    def _build_memory_prompt(self) -> str:
        """构建记忆提示段落。"""
        if self.memory_mgr.is_empty:
            return ""
        content = self.memory_mgr.read()
        return f"\n\n你的长期记忆：\n{content[:2000]}"
