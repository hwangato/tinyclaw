"""
TinyClaw s01 — Agent Loop
=========================
核心概念：ReAct 循环 —— 思考 → 行动 → 观察
这是一切 AI Agent 的最小内核：一个 while 循环。

运行：python agents/s01_agent_loop.py
"""

import json
import os
import subprocess
import sys
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
MODEL = os.getenv("TINYCLAW_MODEL", "gpt-4o-mini")

# ── 唯一的工具：bash ──────────────────────────────────
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "在本地 shell 中执行命令，返回 stdout+stderr。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"}
                },
                "required": ["command"],
            },
        },
    }
]


def run_bash(command: str) -> str:
    """执行 shell 命令，返回输出（最多 4096 字符）。"""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=30
        )
        output = result.stdout + result.stderr
        return output[:4096] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"
    except Exception as e:
        return f"(执行出错: {e})"


def execute_tool(name: str, arguments: dict) -> str:
    """工具分发——目前只有 bash。"""
    if name == "bash":
        return run_bash(arguments["command"])
    return f"未知工具: {name}"


# ── Agent Loop ────────────────────────────────────────
def agent_loop(user_message: str):
    """
    ReAct 循环的最简实现：
    1. 把用户消息发给 LLM
    2. 如果 LLM 想调用工具 → 执行工具 → 把结果喂回去 → 重复
    3. 如果 LLM 返回文本 → 输出给用户 → 结束
    """
    messages = [
        {"role": "system", "content": "你是 TinyClaw，一个能执行 shell 命令的 AI 助手。"},
        {"role": "user", "content": user_message},
    ]

    while True:
        # ── 调用 LLM ──
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS
        )
        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        # ── 没有工具调用 → 输出文本，结束循环 ──
        if not assistant_msg.tool_calls:
            print(f"\n🤖 {assistant_msg.content}")
            break

        # ── 执行每个工具调用 ──
        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            print(f"  ⚙ {fn_name}({fn_args})")

            result = execute_tool(fn_name, fn_args)
            print(f"  ← {result[:200]}")

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                }
            )
        # 继续循环，让 LLM 看到工具结果


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    print("TinyClaw s01 — Agent Loop")
    print("输入你的指令（输入 quit 退出）：")
    while True:
        try:
            user_input = input("\n> ").strip()
            if user_input.lower() in ("quit", "exit", "q"):
                break
            if user_input:
                agent_loop(user_input)
        except (KeyboardInterrupt, EOFError):
            break
    print("\n再见！")
