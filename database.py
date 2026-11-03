import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

class GameDatabase:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    length INTEGER DEFAULT 10,
                    last_grow INTEGER DEFAULT 0,
                    last_duel INTEGER DEFAULT 0,
                    duels_won INTEGER DEFAULT 0,
                    duels_lost INTEGER DEFAULT 0
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

    def get_or_create_user(self, user_id: int, username: str, first_name: str) -> Dict[str, Any]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                # Update username/first_name if changed
                cursor.execute("""
                    UPDATE users SET username = ?, first_name = ? WHERE user_id = ?
                """, (username or "", first_name or "Анонім", user_id))
                conn.commit()
                return dict(row)
            
            # Create user with initial 10 cm
            cursor.execute("""
                INSERT INTO users (user_id, username, first_name, length, last_grow, last_duel, duels_won, duels_lost)
                VALUES (?, ?, ?, 10, 0, 0, 0, 0)
            """, (user_id, username or "", first_name or "Анонім"))
            conn.commit()
            return {
                "user_id": user_id,
                "username": username or "",
                "first_name": first_name or "Анонім",
                "length": 10,
                "last_grow": 0,
                "last_duel": 0,
                "duels_won": 0,
                "duels_lost": 0
            }
        finally:
            conn.close()

    def register_chat_member(self, chat_id: int, user_id: int):
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)
            """, (chat_id, user_id))
            conn.commit()
        finally:
            conn.close()

    def update_length(self, user_id: int, new_length: int, update_grow_time: bool = True):
        now = int(time.time())
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if update_grow_time:
                cursor.execute("""
                    UPDATE users SET length = ?, last_grow = ? WHERE user_id = ?
                """, (max(0, new_length), now, user_id))
            else:
                cursor.execute("""
                    UPDATE users SET length = ? WHERE user_id = ?
                """, (max(0, new_length), user_id))
            conn.commit()
        finally:
            conn.close()

    def record_duel_result(self, winner_id: int, loser_id: int, transfer_cm: int):
        now = int(time.time())
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE users 
                SET length = length + ?, duels_won = duels_won + 1, last_duel = ?
                WHERE user_id = ?
            """, (transfer_cm, now, winner_id))

            cursor.execute("""
                UPDATE users 
                SET length = MAX(0, length - ?), duels_lost = duels_lost + 1, last_duel = ?
                WHERE user_id = ?
            """, (transfer_cm, now, loser_id))
            conn.commit()
        finally:
            conn.close()

    def get_top_in_chat(self, chat_id: Optional[int] = None, limit: int = 10) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        try:
            cursor = conn.cursor()
            if chat_id and chat_id < 0: # Group chat
                cursor.execute("""
                    SELECT u.* FROM users u
                    JOIN chat_members cm ON u.user_id = cm.user_id
                    WHERE cm.chat_id = ?
                    ORDER BY u.length DESC
                    LIMIT ?
                """, (chat_id, limit))
            else: # Global top
                cursor.execute("""
                    SELECT * FROM users
                    ORDER BY length DESC
                    LIMIT ?
                """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()
