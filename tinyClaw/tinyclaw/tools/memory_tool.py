"""
记忆工具模块
============
提供 save_memory / search_memory 两个工具，
用于 Agent 的长期记忆持久化和检索。
"""

from typing import TYPE_CHECKING

from tinyclaw.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from tinyclaw.agent.memory import MemoryManager
    from tinyclaw.store.sqlite import Store


def register_memory_tools(
    registry: ToolRegistry,
    memory_mgr: "MemoryManager",
    store: "Store",
) -> None:
    """
    注册记忆相关工具。

    参数:
        registry: 工具注册表
        memory_mgr: 记忆管理器
        store: 持久化存储
    """

    @registry.tool("save_memory", "保存重要信息到长期记忆。", {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "要保存的记忆内容"},
        },
        "required": ["content"],
    })
    def save_memory(content: str) -> str:
        """将重要信息追加到 MEMORY.md。"""
        return memory_mgr.append(content)

    @registry.tool("search_memory", "搜索长期记忆和对话历史。", {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
        },
        "required": ["query"],
    })
    def search_memory(query: str) -> str:
        """搜索 MEMORY.md 和数据库中的对话历史。"""
        file_results = memory_mgr.search(query)
        db_results = store.search_messages(query, limit=10)
        db_text = ""
        if db_results:
            db_text = "\n\n--- 对话历史 ---\n"
            for r in db_results:
                db_text += f"[{r['role']}] {(r['content'] or '')[:100]}\n"
        return file_results + db_text
