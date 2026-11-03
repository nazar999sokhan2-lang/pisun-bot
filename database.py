import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    length INTEGER DEFAULT 10,
                    last_grow INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)
            conn.commit()
        finally:
            conn.close()

    def get_user(self, user_id: int, first_name: str, username: str) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE users SET first_name = ?, username = ? WHERE user_id = ?
                """, (first_name or "Гравець", username or "", user_id))
                conn.commit()
                return dict(row)
            
            cursor.execute("""
                INSERT INTO users (user_id, first_name, username, length, last_grow)
                VALUES (?, ?, ?, 10, 0)
            """, (user_id, first_name or "Гравець", username or ""))
            conn.commit()
            return {
                "user_id": user_id,
                "first_name": first_name or "Гравець",
                "username": username or "",
                "length": 10,
                "last_grow": 0
            }
        finally:
            conn.close()

    def register_chat(self, chat_id: int, user_id: int):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
            conn.commit()
        finally:
            conn.close()

    def set_length(self, user_id: int, length: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET length = ?, last_grow = ? WHERE user_id = ?
            """, (max(0, length), now, user_id))
            conn.commit()
        finally:
            conn.close()

    def get_top(self, chat_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if chat_id and chat_id < 0:
                cursor.execute("""
                    SELECT u.* FROM users u
                    JOIN chat_members cm ON u.user_id = cm.user_id
                    WHERE cm.chat_id = ?
                    ORDER BY u.length DESC
                    LIMIT ?
                """, (chat_id, limit))
            else:
                cursor.execute("""
                    SELECT * FROM users ORDER BY length DESC LIMIT ?
                """, (limit,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_rank(self, user_id: int, chat_id: Optional[int] = None) -> int:
        top = self.get_top(chat_id=chat_id, limit=100)
        for i, u in enumerate(top, 1):
            if u["user_id"] == user_id:
                return i
        return len(top) + 1
