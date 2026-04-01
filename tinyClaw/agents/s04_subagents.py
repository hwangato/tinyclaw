"""
TinyClaw s04 — 子 Agent
========================
核心概念：隔离的消息历史 —— 子 Agent 拥有独立上下文，
完成任务后将结果返回给父 Agent。

新增：
- spawn_subagent 工具：创建子 Agent，执行独立任务
- 子 Agent 有自己的消息历史，不污染父 Agent 的上下文
- 父 Agent 只收到子 Agent 的最终回复

运行：python agents/s04_subagents.py
"""

import json
import os
import re
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
SKILLS_DIR = Path(os.getenv("TINYCLAW_SKILLS_DIR", "workspace/skills")).resolve()
MAX_SUBAGENT_DEPTH = 3  # 防止无限递归

# ── 工具注册表 ────────────────────────────────────────
_TOOL_REGISTRY: dict[str, dict] = {}


def tool(name: str, description: str, parameters: dict):
    def decorator(func):
        _TOOL_REGISTRY[name] = {
            "schema": {
                "type": "function",
                "function": {"name": name, "description": description, "parameters": parameters},
            },
            "func": func,
        }
        return func
    return decorator


def get_tool_schemas() -> list[dict]:
    return [t["schema"] for t in _TOOL_REGISTRY.values()]


def execute_tool(name: str, arguments: dict, depth: int = 0) -> str:
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return f"未知工具: {name}"
    try:
        # spawn_subagent 需要额外的 depth 参数
        if name == "spawn_subagent":
            return entry["func"](**arguments, _depth=depth)
        return entry["func"](**arguments)
    except Exception as e:
        return f"工具执行出错: {e}"


def safe_path(filepath: str) -> Path:
    resolved = (WORKDIR / filepath).resolve()
    if not str(resolved).startswith(str(WORKDIR)):
        raise PermissionError(f"路径越界: {filepath}")
    return resolved


# ── Skills ────────────────────────────────────────────
def parse_skill_md(content: str) -> dict:
    meta = {"name": "", "description": ""}
    body = content
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if m:
        for line in m.group(1).strip().split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.strip()
        body = m.group(2).strip()
    return {"meta": meta, "body": body}


def load_all_skill_summaries() -> list[dict]:
    summaries = []
    if not SKILLS_DIR.exists():
        return summaries
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        sf = skill_dir / "SKILL.md"
        if sf.exists():
            parsed = parse_skill_md(sf.read_text(encoding="utf-8"))
            summaries.append({
                "id": skill_dir.name,
                "name": parsed["meta"].get("name", skill_dir.name),
                "description": parsed["meta"].get("description", ""),
            })
    return summaries


def build_skills_prompt(summaries: list[dict]) -> str:
    if not summaries:
        return ""
    lines = ["\n可用技能（使用 load_skill 工具获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。", {
    "type": "object",
    "properties": {"command": {"type": "string"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        return output[:4096] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"


@tool("read_file", "读取文件内容。", {
    "type": "object",
    "properties": {"path": {"type": "string"}},
    "required": ["path"],
})
def read_file(path: str) -> str:
    try:
        content = safe_path(path).read_text(encoding="utf-8")
        return content[:8192] if content else "(空文件)"
    except FileNotFoundError:
        return f"文件不存在: {path}"
    except PermissionError as e:
        return str(e)


@tool("write_file", "写入内容到文件。", {
    "type": "object",
    "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
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


@tool("list_dir", "列出目录内容。", {
    "type": "object",
    "properties": {"path": {"type": "string", "default": "."}},
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


@tool("load_skill", "加载指定技能的详细指令。", {
    "type": "object",
    "properties": {"skill_id": {"type": "string"}},
    "required": ["skill_id"],
})
def load_skill(skill_id: str) -> str:
    sf = SKILLS_DIR / skill_id / "SKILL.md"
    if not sf.exists():
        return f"技能不存在: {skill_id}"
    parsed = parse_skill_md(sf.read_text(encoding="utf-8"))
    return f"# 技能: {parsed['meta']['name']}\n\n{parsed['body']}"


@tool("spawn_subagent", "创建子 Agent 执行独立任务，返回结果。", {
    "type": "object",
    "properties": {
        "task": {"type": "string", "description": "要委派给子 Agent 的任务描述"},
    },
    "required": ["task"],
})
def spawn_subagent(task: str, _depth: int = 0) -> str:
    """
    子 Agent 的核心：创建独立的消息历史，
    执行完整的 Agent Loop，只返回最终回复。
    """
    if _depth >= MAX_SUBAGENT_DEPTH:
        return f"已达最大嵌套深度 ({MAX_SUBAGENT_DEPTH})，无法继续派生子 Agent。"

    print(f"  🔀 [深度 {_depth + 1}] 派生子 Agent: {task[:60]}...")

    # 子 Agent 有完全独立的消息历史
    sub_messages = [
        {
            "role": "system",
            "content": (
                "你是 TinyClaw 子 Agent，专注完成一个特定任务。\n"
                f"工作目录: {WORKDIR}\n"
                "完成后直接给出结果，不要多余解释。"
            ),
        },
        {"role": "user", "content": task},
    ]
    tools = get_tool_schemas()

    # 子 Agent 自己的 ReAct 循环
    for _ in range(20):  # 防止无限循环
        response = client.chat.completions.create(
            model=MODEL, messages=sub_messages, tools=tools
        )
        assistant_msg = response.choices[0].message
        sub_messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            result = assistant_msg.content or "(子 Agent 无回复)"
            print(f"  🔀 [深度 {_depth + 1}] 子 Agent 完成")
            return result

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"    ⚙ [{_depth + 1}] {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:80]})")
            result = execute_tool(fn_name, fn_args, depth=_depth + 1)
            print(f"    ← [{_depth + 1}] {result[:150]}")
            sub_messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    return "(子 Agent 达到最大迭代次数)"


# ── Agent Loop ────────────────────────────────────────
def agent_loop(user_message: str):
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)

    system_prompt = (
        "你是 TinyClaw，一个能执行命令、操作文件、加载技能的 AI 助手。\n"
        "你可以使用 spawn_subagent 将复杂任务委派给子 Agent。\n"
        f"工作目录: {WORKDIR}"
        f"{skills_prompt}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]
    tools = get_tool_schemas()

    while True:
        response = client.chat.completions.create(model=MODEL, messages=messages, tools=tools)
        assistant_msg = response.choices[0].message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            print(f"\n🤖 {assistant_msg.content}")
            break

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments)
            print(f"  ⚙ {fn_name}({json.dumps(fn_args, ensure_ascii=False)[:100]})")
            result = execute_tool(fn_name, fn_args, depth=0)
            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    print(f"TinyClaw s04 — 子 Agent  |  最大嵌套深度: {MAX_SUBAGENT_DEPTH}")
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
