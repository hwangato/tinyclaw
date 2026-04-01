"""
SQLite 存储层
=============
持久化存储：消息记录、会话管理、定时任务。
"""

import json
import sqlite3
import time
from pathlib import Path


class Store:
    """
    SQLite 持久化存储。

    管理三张表：
    - messages: 消息记录
    - sessions: 会话元信息
    - cron_jobs: 定时任务
    """

    def __init__(self, db_path: Path):
        """
        初始化存储。

        参数:
            db_path: 数据库文件路径
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        """初始化数据库表结构。"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT,
                tool_calls TEXT,
                tool_call_id TEXT,
                timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                chat_id TEXT PRIMARY KEY,
                last_active REAL NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                schedule_type TEXT NOT NULL,
                schedule_value TEXT NOT NULL,
                prompt TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                script TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                next_run REAL DEFAULT 0,
                last_run REAL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chat_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_cron_status
                ON cron_jobs(status, next_run);
        """)
        self.conn.commit()

    def save_message(
        self,
        chat_id: str,
        role: str,
        content: str | None = None,
        tool_calls: str | None = None,
        tool_call_id: str | None = None,
    ) -> None:
        """
        保存一条消息到数据库。

        参数:
            chat_id: 会话 ID
            role: 角色（system / user / assistant / tool）
            content: 消息内容
            tool_calls: 工具调用 JSON
            tool_call_id: 工具调用 ID
        """
        self.conn.execute(
            "INSERT INTO messages (chat_id, role, content, tool_calls, tool_call_id, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, role, content, tool_calls, tool_call_id, time.time()),
        )
        self.conn.commit()

        # 更新会话最后活跃时间
        self.conn.execute(
            "INSERT OR REPLACE INTO sessions (chat_id, last_active) VALUES (?, ?)",
            (chat_id, time.time()),
        )
        self.conn.commit()

    def get_recent_messages(self, chat_id: str, limit: int = 50) -> list[dict]:
        """
        获取指定会话的最近 N 条消息。

        参数:
            chat_id: 会话 ID
            limit: 最大条数

        返回:
            消息字典列表（按时间正序）
        """
        rows = self.conn.execute(
            "SELECT role, content, tool_calls, tool_call_id FROM messages "
            "WHERE chat_id = ? ORDER BY timestamp DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
        messages = []
        for row in reversed(rows):
            msg: dict = {"role": row["role"]}
            if row["content"]:
                msg["content"] = row["content"]
            if row["tool_calls"]:
                msg["tool_calls"] = json.loads(row["tool_calls"])
            if row["tool_call_id"]:
                msg["tool_call_id"] = row["tool_call_id"]
            messages.append(msg)
        return messages

    def search_messages(self, query: str, limit: int = 20) -> list[dict]:
        """
        搜索包含关键词的消息。

        参数:
            query: 搜索关键词
            limit: 最大条数

        返回:
            匹配的消息字典列表
        """
        rows = self.conn.execute(
            "SELECT chat_id, role, content, timestamp FROM messages "
            "WHERE content LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_sessions(self, limit: int = 50) -> list[dict]:
        """获取最近活跃的会话列表。"""
        rows = self.conn.execute(
            "SELECT chat_id, last_active, metadata FROM sessions "
            "ORDER BY last_active DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def delete_session_messages(self, chat_id: str) -> int:
        """删除指定会话的所有消息。返回删除的条数。"""
        cursor = self.conn.execute(
            "DELETE FROM messages WHERE chat_id = ?", (chat_id,)
        )
        self.conn.commit()
        return cursor.rowcount

    def close(self) -> None:
        """关闭数据库连接。"""
        self.conn.close()
