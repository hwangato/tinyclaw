"""
长期记忆模块
============
基于 Markdown 文件的长期记忆管理器（MEMORY.md）。
支持读取、追加、搜索操作。
"""

import time
from pathlib import Path


class MemoryManager:
    """
    基于 Markdown 文件的长期记忆管理器。

    记忆以时间戳标记的条目形式追加到 MEMORY.md 文件中。
    支持关键词搜索。
    """

    def __init__(self, memory_path: Path):
        """
        初始化记忆管理器。

        参数:
            memory_path: MEMORY.md 文件路径
        """
        self.path = memory_path
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("# TinyClaw 记忆\n\n", encoding="utf-8")

    def read(self) -> str:
        """读取全部记忆内容。"""
        return self.path.read_text(encoding="utf-8")

    def append(self, entry: str) -> str:
        """
        追加一条记忆。

        参数:
            entry: 记忆内容

        返回:
            确认信息
        """
        content = self.read()
        timestamp = time.strftime("%Y-%m-%d %H:%M")
        content += f"\n## [{timestamp}]\n{entry}\n"
        self.path.write_text(content, encoding="utf-8")
        return f"已保存记忆 ({len(entry)} 字符)"

    def search(self, query: str) -> str:
        """
        搜索记忆中的关键词。

        参数:
            query: 搜索关键词

        返回:
            匹配的行（最多 20 行）
        """
        content = self.read()
        lines = content.split("\n")
        matches = [line for line in lines if query.lower() in line.lower()]
        return "\n".join(matches[:20]) if matches else f"未找到与 '{query}' 相关的记忆"

    def clear(self) -> str:
        """清空所有记忆（保留标题）。"""
        self.path.write_text("# TinyClaw 记忆\n\n", encoding="utf-8")
        return "记忆已清空"

    @property
    def is_empty(self) -> bool:
        """检查记忆是否为空。"""
        content = self.read().strip()
        return content == "# TinyClaw 记忆" or content == ""
