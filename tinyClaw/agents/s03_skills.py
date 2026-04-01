"""
TinyClaw s03 — Skills 系统
==========================
核心概念：按需知识注入 —— 不把所有知识塞进系统提示词，
而是让 Agent 在需要时主动加载。

Skills 是存放在目录中的 SKILL.md 文件，包含：
- 前置元信息（name / description）写入系统提示词摘要
- 详细内容通过 load_skill 工具按需获取

目录结构：
  workspace/skills/
    example/
      SKILL.md      ← 技能描述和详细指令

运行：python agents/s03_skills.py
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

# ── 工具注册表（复用 s02 模式）────────────────────────
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


def execute_tool(name: str, arguments: dict) -> str:
    entry = _TOOL_REGISTRY.get(name)
    if not entry:
        return f"未知工具: {name}"
    try:
        return entry["func"](**arguments)
    except Exception as e:
        return f"工具执行出错: {e}"


def safe_path(filepath: str) -> Path:
    resolved = (WORKDIR / filepath).resolve()
    if not str(resolved).startswith(str(WORKDIR)):
        raise PermissionError(f"路径越界: {filepath}")
    return resolved


# ── Skills 加载器 ─────────────────────────────────────
def parse_skill_md(content: str) -> dict:
    """
    解析 SKILL.md 的前置元信息（YAML frontmatter）和正文。

    格式：
    ---
    name: 技能名称
    description: 一句话描述
    ---
    详细的技能指令...
    """
    meta = {"name": "", "description": ""}
    body = content

    frontmatter_match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
    if frontmatter_match:
        for line in frontmatter_match.group(1).strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip()
        body = frontmatter_match.group(2).strip()

    return {"meta": meta, "body": body}


def load_all_skill_summaries() -> list[dict]:
    """扫描所有技能目录，返回摘要列表（用于系统提示词）。"""
    summaries = []
    if not SKILLS_DIR.exists():
        return summaries

    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        skill_file = skill_dir / "SKILL.md"
        if skill_file.exists():
            parsed = parse_skill_md(skill_file.read_text(encoding="utf-8"))
            summaries.append({
                "id": skill_dir.name,
                "name": parsed["meta"].get("name", skill_dir.name),
                "description": parsed["meta"].get("description", ""),
            })
    return summaries


def build_skills_prompt(summaries: list[dict]) -> str:
    """生成技能摘要段落，嵌入系统提示词。"""
    if not summaries:
        return ""
    lines = ["\n可用技能（使用 load_skill 工具获取详细指令）："]
    for s in summaries:
        lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
    return "\n".join(lines)


# ── 工具定义 ──────────────────────────────────────────
@tool("bash", "在本地 shell 中执行命令。", {
    "type": "object",
    "properties": {"command": {"type": "string", "description": "shell 命令"}},
    "required": ["command"],
})
def bash(command: str) -> str:
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
        output = result.stdout + result.stderr
        return output[:4096] if output else "(无输出)"
    except subprocess.TimeoutExpired:
        return "(命令超时)"
    except Exception as e:
        return f"(执行出错: {e})"


@tool("read_file", "读取文件内容。", {
    "type": "object",
    "properties": {"path": {"type": "string", "description": "文件路径"}},
    "required": ["path"],
})
def read_file(path: str) -> str:
    try:
        content = safe_path(path).read_text(encoding="utf-8")
        return content[:8192] if content else "(空文件)"
    except PermissionError as e:
        return str(e)
    except FileNotFoundError:
        return f"文件不存在: {path}"


@tool("write_file", "写入内容到文件。", {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "content": {"type": "string"},
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
    "properties": {
        "skill_id": {"type": "string", "description": "技能 ID（目录名）"},
    },
    "required": ["skill_id"],
})
def load_skill(skill_id: str) -> str:
    """按需加载技能的完整内容。"""
    skill_file = SKILLS_DIR / skill_id / "SKILL.md"
    if not skill_file.exists():
        return f"技能不存在: {skill_id}"
    parsed = parse_skill_md(skill_file.read_text(encoding="utf-8"))
    return f"# 技能: {parsed['meta']['name']}\n\n{parsed['body']}"


# ── Agent Loop ────────────────────────────────────────
def agent_loop(user_message: str):
    # 加载技能摘要到系统提示词
    skill_summaries = load_all_skill_summaries()
    skills_prompt = build_skills_prompt(skill_summaries)

    system_prompt = (
        "你是 TinyClaw，一个能执行命令、操作文件、加载技能的 AI 助手。\n"
        f"工作目录: {WORKDIR}\n"
        "所有文件路径都相对于工作目录。"
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
            result = execute_tool(fn_name, fn_args)
            print(f"  ← {result[:200]}")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})


# ── 入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    summaries = load_all_skill_summaries()
    print(f"TinyClaw s03 — Skills 系统  |  已发现 {len(summaries)} 个技能")
    for s in summaries:
        print(f"  📦 {s['id']}: {s['description']}")
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
