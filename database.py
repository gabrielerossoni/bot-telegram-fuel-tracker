import sqlite3
import os
import logging

log = logging.getLogger("db")

class Database:
    def __init__(self, db_path="bot_data.db"):
        self.db_path = db_path
        self._create_tables()

    def _execute(self, query, params=(), fetchone=False, fetchall=False):
        """Helper per gestire connessione, esecuzione e chiusura automatica."""
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                res = conn.execute(query, params)
                if fetchone: return res.fetchone()
                if fetchall: return res.fetchall()
                return res
        finally:
            conn.close()

    def _create_tables(self):
        self._execute("""
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
        self._execute("""
            CREATE TABLE IF NOT EXISTS poi (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER,
                label TEXT,
                lat REAL,
                lon REAL,
                FOREIGN KEY(chat_id) REFERENCES users(chat_id)
            )
        """)

    def get_user(self, chat_id):
        res = self._execute("SELECT * FROM users WHERE chat_id = ?", (chat_id,), fetchone=True)
        return dict(res) if res else None

    def create_or_update_user(self, chat_id, **kwargs):
        user = self.get_user(chat_id)
        if not user:
            cols = ["chat_id", "lat", "lon", "raggio_km", "carburante", "self_service", "soglia_alert", "orario_invio"]
            vals = [chat_id, 0.0, 0.0, 10, 'Benzina', 1, 1.5, '08:00']
            for k, v in kwargs.items():
                if k in cols: vals[cols.index(k)] = v
            placeholders = ",".join(["?"] * len(cols))
            self._execute(f"INSERT INTO users ({','.join(cols)}) VALUES ({placeholders})", vals)
        else:
            if not kwargs: return
            set_clause = ", ".join([f"{k} = ?" for k in kwargs.keys()])
            vals = list(kwargs.values()) + [chat_id]
            self._execute(f"UPDATE users SET {set_clause}, last_update = CURRENT_TIMESTAMP WHERE chat_id = ?", vals)

    def get_all_users(self):
        res = self._execute("SELECT * FROM users", fetchall=True)
        return [dict(r) for r in res]

db = Database()
