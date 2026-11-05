import os
import sqlite3
import time
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    import psycopg2
    import psycopg2.extras
    HAS_PSYCOPG2 = True
except ImportError:
    HAS_PSYCOPG2 = False


class Database:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_url = os.getenv("DATABASE_URL", "").strip()
        self.is_postgres = bool(self.db_url and HAS_PSYCOPG2)
        self._init_db()

    def _get_conn(self):
        if self.is_postgres:
            return psycopg2.connect(self.db_url, cursor_factory=psycopg2.extras.RealDictCursor)
        else:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            return conn

    def _exec(self, cursor, sql: str, params: tuple = ()):
        if self.is_postgres:
            sql = sql.replace("?", "%s")
            sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "chat_members" in sql and "ON CONFLICT" not in sql:
                sql += " ON CONFLICT DO NOTHING"
            cursor.execute(sql, params)
        else:
            cursor.execute(sql, params)

    def _init_db(self):
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            id_type = "BIGINT" if self.is_postgres else "INTEGER"

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS users (
                    user_id {id_type} PRIMARY KEY,
                    display_name TEXT,
                    username TEXT,
                    length INTEGER DEFAULT 0,
                    last_grow INTEGER DEFAULT 0,
                    last_casino INTEGER DEFAULT 0,
                    last_duel INTEGER DEFAULT 0
                )
            """)

            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS chat_members (
                    chat_id {id_type},
                    user_id {id_type},
                    PRIMARY KEY (chat_id, user_id)
                )
            """)

            # Міграція для старих баз (якщо стовпець називався first_name)
            if not self.is_postgres:
                cursor.execute("PRAGMA table_info(users)")
                cols = [c[1] for c in cursor.fetchall()]
                if "display_name" not in cols:
                    try:
                        cursor.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
                        if "first_name" in cols:
                            cursor.execute("UPDATE users SET display_name = first_name WHERE display_name IS NULL")
                    except Exception:
                        pass

            conn.commit()
        finally:
            conn.close()

    def get_user(self, user_id: int, display_name: str, username: str) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            self._exec(cursor, "SELECT * FROM users WHERE user_id = ?", (user_id,))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                d.setdefault("length", 0)
                d.setdefault("last_grow", 0)
                d.setdefault("last_casino", 0)
                d.setdefault("last_duel", 0)
                # handle if display_name was null
                disp = d.get("display_name") or d.get("first_name") or display_name or "Гравець"
                d["display_name"] = disp
                self._exec(cursor, "UPDATE users SET display_name = ?, username = ? WHERE user_id = ?",
                           (disp, username or "", user_id))
                conn.commit()
                return d

            self._exec(cursor, """
                INSERT INTO users (user_id, display_name, username, length, last_grow, last_casino, last_duel)
                VALUES (?, ?, ?, 0, 0, 0, 0)
            """, (user_id, display_name or "Гравець", username or ""))
            conn.commit()
            return {
                "user_id": user_id,
                "display_name": display_name or "Гравець",
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
            if self.is_postgres:
                cursor.execute("""
                    INSERT INTO chat_members (chat_id, user_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (chat_id, user_id))
            else:
                cursor.execute("INSERT OR IGNORE INTO chat_members (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
            conn.commit()
        finally:
            conn.close()

    def update_grow(self, user_id: int, new_length: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            self._exec(cursor, "UPDATE users SET length = ?, last_grow = ? WHERE user_id = ?",
                       (max(0, new_length), now, user_id))
            conn.commit()
        finally:
            conn.close()

    def update_casino(self, user_id: int, new_length: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            self._exec(cursor, "UPDATE users SET length = ?, last_casino = ? WHERE user_id = ?",
                       (max(0, new_length), now, user_id))
            conn.commit()
        finally:
            conn.close()

    def transfer_duel(self, winner_id: int, loser_id: int, amount: int):
        now = int(time.time())
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            self._exec(cursor, "UPDATE users SET length = length + ?, last_duel = ? WHERE user_id = ?",
                       (amount, now, winner_id))
            self._exec(cursor, "UPDATE users SET length = CASE WHEN (length - ?) < 0 THEN 0 ELSE (length - ?) END, last_duel = ? WHERE user_id = ?",
                       (amount, amount, now, loser_id))
            conn.commit()
        finally:
            conn.close()

    def get_top_in_chat(self, chat_id: Optional[int], limit: int = 10) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            if chat_id and chat_id < 0:
                self._exec(cursor, """
                    SELECT u.* FROM users u
                    JOIN chat_members cm ON u.user_id = cm.user_id
                    WHERE cm.chat_id = ?
                    ORDER BY u.length DESC
                    LIMIT ?
                """, (chat_id, limit))
            else:
                self._exec(cursor, "SELECT * FROM users ORDER BY length DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()

    def get_all_users(self) -> List[Dict[str, Any]]:
        conn = self._get_conn()
        try:
            cursor = conn.cursor()
            self._exec(cursor, "SELECT user_id, display_name, username, length FROM users WHERE length > 0 ORDER BY length DESC")
            return [dict(r) for r in cursor.fetchall()]
        finally:
            conn.close()
