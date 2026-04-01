"""
技能系统模块
============
管理 SKILL.md 技能文件的加载、解析和提示构建。
技能存放在 skills_dir 下，每个子目录包含一个 SKILL.md。
"""

import re
from pathlib import Path


class SkillsManager:
    """
    技能管理器。

    扫描技能目录，解析 SKILL.md 文件（YAML 头部 + Markdown 正文），
    提供技能摘要列表和详细指令加载。
    """

    def __init__(self, skills_dir: Path):
        """
        初始化技能管理器。

        参数:
            skills_dir: 技能目录路径
        """
        self.skills_dir = skills_dir

    @staticmethod
    def parse_skill_md(content: str) -> dict:
        """
        解析 SKILL.md 文件内容。

        格式:
            ---
            name: 技能名称
            description: 技能描述
            ---
            正文内容...

        返回:
            {"meta": {"name": ..., "description": ...}, "body": ...}
        """
        meta: dict[str, str] = {"name": "", "description": ""}
        body = content
        m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)", content, re.DOTALL)
        if m:
            for line in m.group(1).strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip()
            body = m.group(2).strip()
        return {"meta": meta, "body": body}

    def load_all_summaries(self) -> list[dict]:
        """
        加载所有技能的摘要信息。

        返回:
            [{"id": ..., "name": ..., "description": ...}, ...]
        """
        summaries = []
        if not self.skills_dir.exists():
            return summaries
        for skill_dir in sorted(self.skills_dir.iterdir()):
            sf = skill_dir / "SKILL.md"
            if sf.exists():
                parsed = self.parse_skill_md(sf.read_text(encoding="utf-8"))
                summaries.append({
                    "id": skill_dir.name,
                    "name": parsed["meta"].get("name", skill_dir.name),
                    "description": parsed["meta"].get("description", ""),
                })
        return summaries

    def load_skill(self, skill_id: str) -> str:
        """
        加载指定技能的详细指令。

        参数:
            skill_id: 技能 ID（目录名）

        返回:
            技能完整内容或错误信息
        """
        sf = self.skills_dir / skill_id / "SKILL.md"
        if not sf.exists():
            return f"技能不存在: {skill_id}"
        parsed = self.parse_skill_md(sf.read_text(encoding="utf-8"))
        return f"# 技能: {parsed['meta']['name']}\n\n{parsed['body']}"

    def build_skills_prompt(self, summaries: list[dict] | None = None) -> str:
        """
        构建技能提示文本，嵌入系统 prompt。

        参数:
            summaries: 技能摘要列表（留空自动加载）

        返回:
            格式化的技能列表文本
        """
        if summaries is None:
            summaries = self.load_all_summaries()
        if not summaries:
            return ""
        lines = ["\n可用技能（使用 load_skill 获取详细指令）："]
        for s in summaries:
            lines.append(f"  - {s['id']}: {s['name']} — {s['description']}")
        return "\n".join(lines)
