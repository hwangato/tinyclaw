"""
Agent 循环模块
==============
实现 ReAct（Reasoning + Acting）Agent 循环。
接收用户消息，调用 LLM，执行工具，返回回复。
"""

import json
from typing import TYPE_CHECKING

from tinyclaw.agent.compaction import (
    compact_messages,
    messages_token_count,
    micro_compact,
)
from tinyclaw.agent.context import ContextBuilder
from tinyclaw.agent.hooks import HookSystem
from tinyclaw.config import AgentConfig

if TYPE_CHECKING:
    from tinyclaw.provider.openai_compat import OpenAICompatProvider
    from tinyclaw.store.sqlite import Store
    from tinyclaw.tools.registry import ToolRegistry
    from tinyclaw.policy.engine import PolicyEngine


class AgentLoop:
    """
    ReAct Agent 循环。

    每次调用 run() 方法：
    1. 组装系统提示词
    2. 加载历史消息
    3. 循环调用 LLM → 执行工具 → 收集结果
    4. 直到 LLM 给出最终回复

    全程触发钩子系统的 6 个钩子点。
    """

    def __init__(
        self,
        agent_config: AgentConfig,
        provider: "OpenAICompatProvider",
        store: "Store",
        tool_registry: "ToolRegistry",
        hook_system: HookSystem,
        context_builder: ContextBuilder,
        policy_engine: "PolicyEngine",
        plugin_info_fn=None,
    ):
        """
        初始化 Agent 循环。

        参数:
            agent_config: Agent 配置
            provider: LLM Provider
            store: 持久化存储
            tool_registry: 工具注册表
            hook_system: 钩子系统
            context_builder: 上下文构建器
            policy_engine: 策略引擎
            plugin_info_fn: 获取插件信息的回调函数
        """
        self.config = agent_config
        self.provider = provider
        self.store = store
        self.tool_registry = tool_registry
        self.hook_system = hook_system
        self.context_builder = context_builder
        self.policy_engine = policy_engine
        self._plugin_info_fn = plugin_info_fn

    def run(self, user_message: str, chat_id: str = "default") -> str:
        """
        执行一次完整的 Agent 循环。

        参数:
            user_message: 用户消息
            chat_id: 会话 ID

        返回:
            Agent 回复文本
        """
        # ── before_system_prompt 钩子 ──
        hook_data = self.hook_system.fire("before_system_prompt", {
            "user_message": user_message,
            "chat_id": chat_id,
            "agent_id": self.config.id,
        })

        # 组装系统提示词
        plugin_info = self._plugin_info_fn() if self._plugin_info_fn else ""
        system_prompt = self.context_builder.build_system_prompt(plugin_info=plugin_info)

        # ── after_system_prompt 钩子 ──
        hook_data = self.hook_system.fire("after_system_prompt", {
            "system_prompt": system_prompt,
            "user_message": user_message,
            "chat_id": chat_id,
        })
        system_prompt = hook_data.get("system_prompt", system_prompt)

        # 加载历史消息
        history = self.store.get_recent_messages(chat_id, limit=30)
        messages = [{"role": "system", "content": system_prompt}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        self.store.save_message(chat_id, "user", user_message)

        # 获取工具 schema
        tools = self.tool_registry.get_schemas()
        model = self.config.model or self.provider.default_model

        # ReAct 循环
        max_iterations = 30
        for _ in range(max_iterations):
            # 检查 token 上限
            token_count = messages_token_count(messages)
            if token_count > self.config.max_tokens:
                messages = compact_messages(
                    messages, self.config.compact_target, self.provider
                )

            # ── before_model_call 钩子 ──
            self.hook_system.fire("before_model_call", {
                "messages": messages,
                "tools": tools,
                "model": model,
            })

            # 调用 LLM
            response = self.provider.chat(messages, tools=tools, model=model)

            # 构建 assistant 消息
            assistant_msg: dict = {"role": "assistant"}
            if response.content:
                assistant_msg["content"] = response.content
            if response.tool_calls:
                assistant_msg["tool_calls"] = response.tool_calls
            messages.append(assistant_msg)

            # ── after_model_call 钩子 ──
            self.hook_system.fire("after_model_call", {
                "response": {
                    "content": response.content,
                    "has_tool_calls": bool(response.tool_calls),
                },
            })

            # 如果没有工具调用，返回最终回复
            if not response.tool_calls:
                reply = response.content or ""
                self.store.save_message(chat_id, "assistant", reply)
                return reply

            # 执行工具调用
            for tc in response.tool_calls:
                fn_name = tc["function"]["name"]
                fn_args_str = tc["function"]["arguments"]
                try:
                    fn_args = json.loads(fn_args_str)
                except json.JSONDecodeError:
                    fn_args = {}

                print(f"  [tool] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")

                # ── before_tool_call 钩子 ──
                hook_data = self.hook_system.fire("before_tool_call", {
                    "tool_name": fn_name,
                    "arguments": fn_args,
                })
                fn_name = hook_data.get("tool_name", fn_name)
                fn_args = hook_data.get("arguments", fn_args)

                # 策略引擎检查
                action, reason = self.policy_engine.check(fn_name, fn_args)
                if action == "deny":
                    result = f"策略拒绝: {reason}"
                else:
                    result = self.tool_registry.execute(fn_name, fn_args, depth=0)

                # 处理特殊返回值
                if result == "__COMPACT__":
                    messages = compact_messages(
                        messages, self.config.compact_target, self.provider
                    )
                    result = "上下文已压缩。"

                # ── after_tool_call 钩子 ──
                hook_data = self.hook_system.fire("after_tool_call", {
                    "tool_name": fn_name,
                    "arguments": fn_args,
                    "result": result,
                })
                result = hook_data.get("result", result)

                print(f"  <- {result[:200]}")

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })
                self.store.save_message(chat_id, "tool", result, tool_call_id=tc["id"])

        return "(Agent 达到最大迭代次数)"
