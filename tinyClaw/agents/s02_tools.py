"""
TinyClaw s02 — 工具系统
=======================
核心概念：注册表模式 —— 用声明式描述让 LLM 自主选择工具

在 s01 中工具是硬编码的。本课引入工具注册表：
- 用装饰器 @tool 声明工具的 name / description / parameters
- 统一的 dispatch 函数按名称分发
- 新增 read_file / write_file / list_dir 三个文件操作工具
- 路径沙箱：所有文件操作限制在工作目录内

运行：python agents/s02_tools.py
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
MODEL = os.getenv("TINYCLAW_MODEL", "gpt-4o-mini")
WORKDIR = Path(os.getenv("TINYCLAW_WORKDIR", ".")).resolve()

# ── 工具注册表 ────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}  # name -> {schema, func}


def tool(name: str, description: str, parameters: dict):
    """装饰器：将函数注册为 Agent 可调用的工具。"""
    def decorator(func):
        _TOOL_REGISTRY[name] = {
            "schema": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            },
            "func": func,
        }
        return func
    return decorator


def get_tool_schemas() -> list[dict]:
    return [t["schema"] for t in _TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict) -> str:
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return f"未知工具: {name}"
    try:
        return entry["func"](**arguments)
    except Exception as e:
        return f"工具执行出错: {e}"


# ── 路径沙箱 ──────────────────────────────────────────
def safe_path(filepath: str) -> Path:
    """确保路径在 WORKDIR 内，防止路径穿越。"""
    resolved = (WORKDIR / filepath).resolve()
    if not str(resolved).startswith(str(WORKDIR)):
        raise PermissionError(f"路径越界: {filepath}")
    return resolved


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。", {
    "type": "object",
    "properties": {"command": {"type": "string", "description": "shell 命令"}},
    "required": ["command"],
})
def bash(command: str) -> str:
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


@tool("read_file", "读取文件内容。", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径（相对于工作目录）"},
    },
    "required": ["path"],
})
def read_file(path: str) -> str:
    try:
        p = safe_path(path)
        content = p.read_text(encoding="utf-8")
        return content[:8192] if content else "(空文件)"
    except PermissionError as e:
        return str(e)
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except Exception as e:
        return f"读取出错: {e}"


@tool("write_file", "写入内容到文件（覆盖）。", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要写入的内容"},
    },
    "required": ["path", "content"],
})
def write_file(path: str, content: str) -> str:
    try:
        p = safe_path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"已写入 {p.relative_to(WORKDIR)} ({len(content)} 字符)"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"写入出错: {e}"


@tool("list_dir", "列出目录内容。", {
    "type": "object",
    "properties": {
        "path": {"type": "string", "description": "目录路径", "default": "."},
    },
    "required": [],
})
def list_dir(path: str = ".") -> str:
    try:
        p = safe_path(path)
        if not p.is_dir():
            return f"不是目录: {path}"
        entries = []
        for item in sorted(p.iterdir()):
            prefix = "📁 " if item.is_dir() else "📄 "
            entries.append(f"{prefix}{item.name}")
        return "\n".join(entries) if entries else "(空目录)"
    except PermissionError as e:
        return str(e)
    except Exception as e:
        return f"列目录出错: {e}"


# ── Agent Loop ────────────────────────────────────────
def agent_loop(user_message: str):
    messages = [
        {
            "role": "system",
            "content": (
                "你是 TinyClaw，一个能执行命令和操作文件的 AI 助手。\n"
                f"工作目录: {WORKDIR}\n"
                "所有文件路径都相对于工作目录。"
            ),
        },
        {"role": "user", "content": user_message},
    ]
    tools = get_tool_schemas()

    while True:
        response = client.chat.completions.create(
            model=MODEL, messages=messages, tools=tools
        )
        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            print(f"\n🤖 {assistant_msg.content}")
            break

        for tool_call in assistant_msg.tool_calls:
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)
            print(f"  ⚙ {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")

            result = execute_tool(fn_name, fn_args)
            print(f"  ← {result[:200]}")

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": result,
            })


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"TinyClaw s02 — 工具系统  |  工作目录: {WORKDIR}")
    print(f"已注册 {len(_TOOL_REGISTRY)} 个工具: {', '.join(_TOOL_REGISTRY.keys())}")
    print("输入指令（quit 退出）：")
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
