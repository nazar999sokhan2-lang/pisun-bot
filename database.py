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
                    display_name TEXT,
                    username TEXT,
                    length INTEGER DEFAULT 0,
                    last_grow INTEGER DEFAULT 0,
                    last_casino INTEGER DEFAULT 0,
                    last_duel INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            # Автоматична міграція для старих баз (якщо стовпців ще не було)
            for col, col_type in [
                ("last_casino", "INTEGER DEFAULT 0"),
                ("last_duel", "INTEGER DEFAULT 0"),
                ("last_grow", "INTEGER DEFAULT 0"),
                ("length", "INTEGER DEFAULT 0")
            ]:
                try:
                    cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass

            conn.commit()
        finally:
            conn.close()

    def get_user(self, user_id: int, display_name: str, username: str) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d.setdefault("last_casino", 0)
                d.setdefault("last_duel", 0)
                d.setdefault("last_grow", 0)
                d.setdefault("length", 0)
                cursor.execute("""
                    UPDATE users SET display_name = ?, username = ? WHERE user_id = ?
                """, (display_name or "Анонім", username or "", user_id))
                conn.commit()
                return d
            
            cursor.execute("""
                INSERT INTO users (user_id, display_name, username, length, last_grow, last_casino, last_duel)
                VALUES (?, ?, ?, 0, 0, 0, 0)
            """, (user_id, display_name or "Анонім", username or ""))
            conn.commit()
            return {
                "user_id": user_id,
                "display_name": display_name or "Анонім",
                "username": username or "",
                "length": 0,
                "last_grow": 0,
                "last_casino": 0,
                "last_duel": 0
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

    def update_grow(self, user_id: int, new_length: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET length = ?, last_grow = ? WHERE user_id = ?
            """, (max(0, new_length), now, user_id))
            conn.commit()
        finally:
            conn.close()

    def update_casino(self, user_id: int, new_length: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET length = ?, last_casino = ? WHERE user_id = ?
            """, (max(0, new_length), now, user_id))
            conn.commit()
        finally:
            conn.close()

    def transfer_duel(self, winner_id: int, loser_id: int, amount: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users SET length = length + ?, last_duel = ? WHERE user_id = ?
            """, (amount, now, winner_id))
            cursor.execute("""
                UPDATE users SET length = MAX(0, length - ?), last_duel = ? WHERE user_id = ?
            """, (amount, now, loser_id))
            conn.commit()
        finally:
            conn.close()

    def get_top_in_chat(self, chat_id: Optional[int], limit: int = 10) -> List[Dict[str, Any]]:
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
