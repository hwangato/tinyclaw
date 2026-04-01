"""
子 Agent 工具
=============
提供 spawn_subagent 工具，允许主 Agent 委派独立任务给子 Agent。
支持嵌套深度限制，防止无限递归。
"""

import json
from typing import TYPE_CHECKING

from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from tinyclaw.provider.openai_compat import OpenAICompatProvider
    from tinyclaw.config import AgentConfig


def register_subagent_tools(
    registry: ToolRegistry,
    provider: "OpenAICompatProvider",
    agent_config: "AgentConfig",
) -> None:
    """
    注册子 Agent 工具。

    参数:
        registry: 工具注册表
        provider: LLM Provider
        agent_config: Agent 配置
    """
    max_depth = agent_config.max_subagent_depth

    @registry.tool("spawn_subagent", "创建子 Agent 执行独立任务。", {
        "type": "object",
        "properties": {
            "task": {"type": "string", "description": "子 Agent 要执行的任务描述"},
        },
        "required": ["task"],
    })
    def spawn_subagent(task: str, _depth: int = 0) -> str:
        """创建子 Agent 并执行独立任务。"""
        if _depth >= max_depth:
            return f"已达最大嵌套深度 ({max_depth})"

        sub_messages = [
            {
                "role": "system",
                "content": (
                    f"你是 TinyClaw 子 Agent。工作目录: {registry.workdir}\n"
                    "完成任务后直接给出结果，不要做额外的事情。"
                ),
            },
            {"role": "user", "content": task},
        ]

        tools = registry.get_schemas()
        model = agent_config.model or provider.default_model

        for _ in range(20):
            response = provider.chat(sub_messages, tools=tools, model=model)

            # 构建 assistant 消息
            assistant_msg: dict = {"role": "assistant"}
            if response.content:
                assistant_msg["content"] = response.content
            if response.tool_calls:
                assistant_msg["tool_calls"] = response.tool_calls
            sub_messages.append(assistant_msg)

            if not response.tool_calls:
                return response.content or "(子 Agent 无回复)"

            for tc in response.tool_calls:
                fn_name = tc["function"]["name"]
                try:
                    fn_args = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    fn_args = {}
                result = registry.execute(fn_name, fn_args, depth=_depth + 1)
                sub_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

        return "(子 Agent 达到最大迭代次数)"
