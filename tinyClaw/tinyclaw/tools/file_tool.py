"""
文件操作工具
============
提供 read_file / write_file / list_dir 三个文件操作工具。
所有路径操作经过安全检查，防止目录遍历。
"""

from tinyclaw.agent.compaction import micro_compact
from tinyclaw.tools.registry import ToolRegistry


def register_file_tools(registry: ToolRegistry) -> None:
    """
    注册文件操作工具。

    参数:
        registry: 工具注册表
    """

    @registry.tool("read_file", "读取文件内容。", {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件相对路径"}},
        "required": ["path"],
    })
    def read_file(path: str) -> str:
        """读取指定文件的内容。"""
        try:
            content = registry.safe_path(path).read_text(encoding="utf-8")
            return micro_compact(content, 8192) if content else "(空文件)"
        except FileNotFoundError:
            return f"文件不存在: {path}"
        except PermissionError as e:
            return str(e)
        except UnicodeDecodeError:
            return f"文件不是文本格式或编码不兼容: {path}"

    @registry.tool("write_file", "写入内容到文件。", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件相对路径"},
            "content": {"type": "string", "description": "要写入的内容"},
        },
        "required": ["path", "content"],
    })
    def write_file(path: str, content: str) -> str:
        """写入内容到指定文件。"""
        try:
            p = registry.safe_path(path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            rel = p.relative_to(registry.workdir)
            return f"已写入 {rel} ({len(content)} 字符)"
        except PermissionError as e:
            return str(e)

    @registry.tool("list_dir", "列出目录内容。", {
        "type": "object",
        "properties": {
            "path": {"type": "string", "default": ".", "description": "目录相对路径"},
        },
        "required": [],
    })
    def list_dir(path: str = ".") -> str:
        """列出指定目录的文件和子目录。"""
        try:
            p = registry.safe_path(path)
            if not p.is_dir():
                return f"不是目录: {path}"
            entries = []
            for item in sorted(p.iterdir()):
                prefix = "[dir]  " if item.is_dir() else "[file] "
                entries.append(f"{prefix}{item.name}")
            return "\n".join(entries) if entries else "(空目录)"
        except PermissionError as e:
            return str(e)
