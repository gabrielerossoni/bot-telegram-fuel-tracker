import sqlite3
import os
import logging

log = logging.getLogger("db")

class Database:
    def __init__(self, db_path="bot_data.db"):
        self.db_path = db_path
        self._create_tables()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _create_tables(self):
        with self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    chat_id INTEGER PRIMARY KEY,
                    lat REAL,
                    lon REAL,
                    raggio_km INTEGER DEFAULT 10,
                    carburante TEXT DEFAULT 'Benzina',
                    self_service INTEGER DEFAULT 1,
                    soglia_alert REAL DEFAULT 1.5,
                    orario_invio TEXT DEFAULT '08:00',
                    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS poi (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER,
                    label TEXT,
                    lat REAL,
                    lon REAL,
                    FOREIGN KEY(chat_id) REFERENCES users(chat_id)
                )
            """)
            conn.commit()

    def get_user(self, chat_id):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            res = conn.execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,)).fetchone()
            return dict(res) if res else None

    def create_or_update_user(self, chat_id, **kwargs):
        user = self.get_user(chat_id)
        if not user:
            # Default values from env if available as fallback
            cols = ["chat_id", "lat", "lon", "raggio_km", "carburante", "self_service", "soglia_alert", "orario_invio"]
            vals = [chat_id, 0.0, 0.0, 10, 'Benzina', 1, 1.5, '08:00']
            
            # Replace defaults with kwargs
            for k, v in kwargs.items():
                if k in cols:
                    vals[cols.index(k)] = v
            
            placeholders = ",".join(["?"] * len(cols))
            with self._get_connection() as conn:
                conn.execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({placeholders})", vals)
                conn.commit()
        else:
            if not kwargs: return
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            vals = list(kwargs.values()) + [chat_id]
            with self._get_connection() as conn:
                conn.execute(f"UPDATE users SET {set_clause}, last_update = CURRENT_TIMESTAMP WHERE chat_id = ?", vals)
                conn.commit()

    def get_all_users(self):
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM users").fetchall()]

db = Database()
