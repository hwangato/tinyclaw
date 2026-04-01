"""
CLI 入口模块
============
基于 click 的命令行接口。

命令:
- tinyclaw run          启动 TinyClaw
- tinyclaw agent list   列出所有 Agent
- tinyclaw cron list    列出定时任务
- tinyclaw plugin list  列出插件
- tinyclaw tool list    列出工具
"""

import asyncio
import sys

import click

from tinyclaw import __version__
from tinyclaw.config import load_config


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="TinyClaw")
@click.option("--config", "-c", default=None, help="配置文件路径（默认 config.yaml）")
@click.pass_context
def cli(ctx, config):
    """TinyClaw — 模块化 AI Agent 框架。"""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@cli.command()
@click.option("--config", "-c", default=None, help="配置文件路径")
def run(config):
    """启动 TinyClaw Agent 服务。"""
    cfg = load_config(config)

    from tinyclaw.gateway import Gateway

    gateway = Gateway(cfg)

    async def _run():
        try:
            await gateway.start()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            await gateway.stop()
        print("\n再见！")

    try:
        asyncio.run(_run())
    except (KeyboardInterrupt, EOFError):
        print("\n再见！")


# ── Agent 子命令组 ──

@cli.group("agent")
def agent_group():
    """Agent 管理命令。"""
    pass


@agent_group.command("list")
@click.option("--config", "-c", default=None, help="配置文件路径")
def agent_list(config):
    """列出所有配置的 Agent。"""
    cfg = load_config(config)
    if not cfg.agents:
        click.echo("没有配置任何 Agent")
        return
    click.echo("已配置的 Agent:")
    for agent_cfg in cfg.agents:
        model = agent_cfg.model or cfg.provider.model
        heartbeat = agent_cfg.heartbeat_interval or "无"
        click.echo(
            f"  [{agent_cfg.id}] {agent_cfg.name} | model={model} | "
            f"max_tokens={agent_cfg.max_tokens} | heartbeat={heartbeat}"
        )


# ── Cron 子命令组 ──

@cli.group("cron")
def cron_group():
    """定时任务管理命令。"""
    pass


@cron_group.command("list")
@click.option("--config", "-c", default=None, help="配置文件路径")
def cron_list(config):
    """列出所有定时任务。"""
    cfg = load_config(config)

    from tinyclaw.store.sqlite import Store
    from tinyclaw.bus import MessageBus
    from tinyclaw.cron.scheduler import CronScheduler

    store = Store(cfg.data_dir / "tinyclaw.db")
    bus = MessageBus()
    scheduler = CronScheduler(store, bus)
    result = scheduler.list_jobs()
    click.echo(result)
    store.close()


# ── Plugin 子命令组 ──

@cli.group("plugin")
def plugin_group():
    """插件管理命令。"""
    pass


@plugin_group.command("list")
@click.option("--config", "-c", default=None, help="配置文件路径")
def plugin_list(config):
    """列出所有可用插件。"""
    cfg = load_config(config)

    from tinyclaw.plugin.manager import PluginManager

    mgr = PluginManager(plugins_dir=cfg.plugins.plugins_dir)
    manifests = mgr.discover()
    if not manifests:
        click.echo("未发现任何插件")
        return
    click.echo("可用插件:")
    for m in manifests:
        status = "已启用" if m.enabled else "已禁用"
        click.echo(
            f"  [{m.id}] {m.name} v{m.version} | 类型={m.type} | "
            f"状态={status} | {m.description}"
        )


# ── Tool 子命令组 ──

@cli.group("tool")
def tool_group():
    """工具管理命令。"""
    pass


@tool_group.command("list")
@click.option("--config", "-c", default=None, help="配置文件路径")
def tool_list(config):
    """列出所有已注册工具。"""
    cfg = load_config(config)

    from tinyclaw.gateway import Gateway

    gateway = Gateway(cfg)
    click.echo(f"已注册 {gateway.tool_registry.tool_count} 个工具:")
    click.echo(gateway.tool_registry.list_tools())


# ── Channel 子命令组 ──

@cli.group("channel")
def channel_group():
    """通道管理命令。"""
    pass


@channel_group.command("list")
@click.option("--config", "-c", default=None, help="配置文件路径")
def channel_list(config):
    """列出所有配置的通道。"""
    cfg = load_config(config)
    if not cfg.channels:
        click.echo("没有配置任何通道")
        return
    click.echo("已配置的通道:")
    for ch_cfg in cfg.channels:
        status = "已启用" if ch_cfg.enabled else "已禁用"
        click.echo(f"  [{ch_cfg.type}] 状态={status}")


def main():
    """主入口函数。"""
    cli()


if __name__ == "__main__":
    main()
