"""
配置管理模块
============
从环境变量和 YAML 配置文件加载配置，统一为 Config 数据类。

优先级：环境变量 > config.yaml > 默认值
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ProviderConfig:
    """LLM Provider 配置。"""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    max_retries: int = 3
    timeout: float = 60.0
    streaming: bool = True


@dataclass
class AgentConfig:
    """单个 Agent 的配置。"""
    id: str = "default"
    name: str = "TinyClaw"
    soul_path: str = ""          # SOUL.md 路径
    identity_path: str = ""      # IDENTITY.md 路径
    model: str = ""              # 覆盖全局 model（留空则用全局）
    max_tokens: int = 50000
    compact_target: int = 20000
    max_tool_output_len: int = 4096
    max_subagent_depth: int = 3
    heartbeat_interval: str = ""  # 心跳间隔，如 "5m"，留空则不启用


@dataclass
class SandboxConfig:
    """Docker 沙盒配置。"""
    enabled: bool = True
    image: str = "python:3.12-slim"
    timeout: int = 30
    memory_limit: str = "128m"
    cpu_limit: str = "0.5"


@dataclass
class ChannelConfig:
    """通道配置。"""
    type: str = "cli"            # cli / telegram / discord / feishu
    enabled: bool = True
    token: str = ""              # Bot token
    app_id: str = ""             # 飞书 App ID
    app_secret: str = ""         # 飞书 App Secret
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8080
    extra: dict = field(default_factory=dict)


@dataclass
class CronConfig:
    """定时调度配置。"""
    enabled: bool = True
    poll_interval: int = 60      # 轮询间隔（秒）


@dataclass
class PolicyConfig:
    """安全策略配置。"""
    enabled: bool = True
    rules_path: str = ""         # 自定义规则文件路径


@dataclass
class MCPConfig:
    """MCP 配置。"""
    config_path: str = "mcp_servers.json"


@dataclass
class PluginConfig:
    """插件系统配置。"""
    enabled: bool = True
    plugins_dir: str = "plugins"


@dataclass
class WebConfig:
    """Web 工具配置。"""
    search_api: str = ""         # 搜索 API 类型（google / bing / searxng）
    search_api_key: str = ""
    search_api_url: str = ""     # SearXNG 实例 URL
    fetch_timeout: float = 15.0
    max_content_length: int = 8192


@dataclass
class Config:
    """TinyClaw 全局配置。"""
    workdir: Path = field(default_factory=lambda: Path(".").resolve())
    data_dir: Path = field(default_factory=lambda: Path("data").resolve())
    skills_dir: Path = field(default_factory=lambda: Path("workspace/skills").resolve())
    log_level: str = "INFO"

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    agents: list[AgentConfig] = field(default_factory=lambda: [AgentConfig()])
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    channels: list[ChannelConfig] = field(default_factory=lambda: [ChannelConfig()])
    cron: CronConfig = field(default_factory=CronConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)
    plugins: PluginConfig = field(default_factory=PluginConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _merge_env(cfg: Config) -> Config:
    """用环境变量覆盖配置项。环境变量优先级最高。"""
    # Provider
    if v := os.getenv("OPENAI_API_KEY"):
        cfg.provider.api_key = v
    if v := os.getenv("OPENAI_BASE_URL"):
        cfg.provider.base_url = v
    if v := os.getenv("TINYCLAW_MODEL"):
        cfg.provider.model = v

    # 路径
    if v := os.getenv("TINYCLAW_WORKDIR"):
        cfg.workdir = Path(v).resolve()
    if v := os.getenv("TINYCLAW_DATA_DIR"):
        cfg.data_dir = Path(v).resolve()
    if v := os.getenv("TINYCLAW_SKILLS_DIR"):
        cfg.skills_dir = Path(v).resolve()

    # Agent
    if v := os.getenv("TINYCLAW_MAX_TOKENS"):
        for a in cfg.agents:
            a.max_tokens = int(v)
    if v := os.getenv("TINYCLAW_COMPACT_TARGET"):
        for a in cfg.agents:
            a.compact_target = int(v)

    # 沙盒
    if v := os.getenv("TINYCLAW_DOCKER_IMAGE"):
        cfg.sandbox.image = v
    if v := os.getenv("TINYCLAW_DOCKER_TIMEOUT"):
        cfg.sandbox.timeout = int(v)

    # MCP
    if v := os.getenv("TINYCLAW_MCP_CONFIG"):
        cfg.mcp.config_path = v

    # 插件
    if v := os.getenv("TINYCLAW_PLUGINS_DIR"):
        cfg.plugins.plugins_dir = v

    # 通道 Token
    if v := os.getenv("TELEGRAM_BOT_TOKEN"):
        for ch in cfg.channels:
            if ch.type == "telegram":
                ch.token = v
    if v := os.getenv("DISCORD_BOT_TOKEN"):
        for ch in cfg.channels:
            if ch.type == "discord":
                ch.token = v
    if v := os.getenv("FEISHU_APP_ID"):
        for ch in cfg.channels:
            if ch.type == "feishu":
                ch.app_id = v
    if v := os.getenv("FEISHU_APP_SECRET"):
        for ch in cfg.channels:
            if ch.type == "feishu":
                ch.app_secret = v

    # Web
    if v := os.getenv("TINYCLAW_SEARCH_API"):
        cfg.web.search_api = v
    if v := os.getenv("TINYCLAW_SEARCH_API_KEY"):
        cfg.web.search_api_key = v
    if v := os.getenv("TINYCLAW_SEARCH_API_URL"):
        cfg.web.search_api_url = v

    return cfg


def _parse_channel_config(data: dict) -> ChannelConfig:
    """解析单个通道配置字典。"""
    return ChannelConfig(
        type=data.get("type", "cli"),
        enabled=data.get("enabled", True),
        token=data.get("token", ""),
        app_id=data.get("app_id", ""),
        app_secret=data.get("app_secret", ""),
        webhook_host=data.get("webhook_host", "0.0.0.0"),
        webhook_port=data.get("webhook_port", 8080),
        extra=data.get("extra", {}),
    )


def _parse_agent_config(data: dict) -> AgentConfig:
    """解析单个 Agent 配置字典。"""
    return AgentConfig(
        id=data.get("id", "default"),
        name=data.get("name", "TinyClaw"),
        soul_path=data.get("soul_path", ""),
        identity_path=data.get("identity_path", ""),
        model=data.get("model", ""),
        max_tokens=data.get("max_tokens", 50000),
        compact_target=data.get("compact_target", 20000),
        max_tool_output_len=data.get("max_tool_output_len", 4096),
        max_subagent_depth=data.get("max_subagent_depth", 3),
        heartbeat_interval=data.get("heartbeat_interval", ""),
    )


def load_config(config_path: str | Path | None = None) -> Config:
    """
    加载配置。

    加载顺序：
    1. 默认值
    2. YAML 配置文件（如果存在）
    3. 环境变量覆盖

    参数:
        config_path: 配置文件路径。默认查找 config.yaml

    返回:
        Config 数据类实例
    """
    cfg = Config()

    # 尝试加载 YAML
    yaml_path = Path(config_path) if config_path else Path("config.yaml")
    if yaml_path.exists():
        try:
            raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            _apply_yaml(cfg, raw)
        except Exception as e:
            print(f"  [warn] 加载配置文件失败: {e}")

    # 环境变量覆盖
    cfg = _merge_env(cfg)
    return cfg


def _apply_yaml(cfg: Config, raw: dict[str, Any]) -> None:
    """将 YAML 字典应用到 Config 对象。"""
    if "workdir" in raw:
        cfg.workdir = Path(raw["workdir"]).resolve()
    if "data_dir" in raw:
        cfg.data_dir = Path(raw["data_dir"]).resolve()
    if "skills_dir" in raw:
        cfg.skills_dir = Path(raw["skills_dir"]).resolve()
    if "log_level" in raw:
        cfg.log_level = raw["log_level"]

    # Provider
    if p := raw.get("provider"):
        cfg.provider = ProviderConfig(
            api_key=p.get("api_key", ""),
            base_url=p.get("base_url", "https://api.openai.com/v1"),
            model=p.get("model", "gpt-4o-mini"),
            max_retries=p.get("max_retries", 3),
            timeout=p.get("timeout", 60.0),
            streaming=p.get("streaming", True),
        )

    # Agents
    if agents_raw := raw.get("agents"):
        cfg.agents = [_parse_agent_config(a) for a in agents_raw]

    # Sandbox
    if s := raw.get("sandbox"):
        cfg.sandbox = SandboxConfig(
            enabled=s.get("enabled", True),
            image=s.get("image", "python:3.12-slim"),
            timeout=s.get("timeout", 30),
            memory_limit=s.get("memory_limit", "128m"),
            cpu_limit=s.get("cpu_limit", "0.5"),
        )

    # Channels
    if channels_raw := raw.get("channels"):
        cfg.channels = [_parse_channel_config(c) for c in channels_raw]

    # Cron
    if c := raw.get("cron"):
        cfg.cron = CronConfig(
            enabled=c.get("enabled", True),
            poll_interval=c.get("poll_interval", 60),
        )

    # Policy
    if p := raw.get("policy"):
        cfg.policy = PolicyConfig(
            enabled=p.get("enabled", True),
            rules_path=p.get("rules_path", ""),
        )

    # MCP
    if m := raw.get("mcp"):
        cfg.mcp = MCPConfig(config_path=m.get("config_path", "mcp_servers.json"))

    # Plugins
    if pl := raw.get("plugins"):
        cfg.plugins = PluginConfig(
            enabled=pl.get("enabled", True),
            plugins_dir=pl.get("plugins_dir", "plugins"),
        )

    # Web
    if w := raw.get("web"):
        cfg.web = WebConfig(
            search_api=w.get("search_api", ""),
            search_api_key=w.get("search_api_key", ""),
            search_api_url=w.get("search_api_url", ""),
            fetch_timeout=w.get("fetch_timeout", 15.0),
            max_content_length=w.get("max_content_length", 8192),
        )
