import sqlite3
import json
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id          TEXT PRIMARY KEY,
    dingtalk_webhook TEXT DEFAULT '',
    flex_token_enc   TEXT DEFAULT '',
    flex_query_id    TEXT DEFAULT '',
    watchlist_json   TEXT DEFAULT '[]',
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scan_results (
    scan_date    TEXT PRIMARY KEY,
    results_json TEXT NOT NULL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

class AgentDB:
    def __init__(self, db_path: str = "data/agent.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def save_user(self, user_id: str, dingtalk_webhook: str = ""):
        self.conn.execute(
            "INSERT OR IGNORE INTO users (user_id, dingtalk_webhook, created_at) VALUES (?,?,?)",
            (user_id, dingtalk_webhook, datetime.now().isoformat())
        )
        if dingtalk_webhook:
            self.conn.execute(
                "UPDATE users SET dingtalk_webhook=? WHERE user_id=?",
                (dingtalk_webhook, user_id)
            )
        self.conn.commit()

    def get_user(self, user_id: str) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT * FROM users WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def update_watchlist(self, user_id: str, tickers: List[str]):
        self.conn.execute(
            "UPDATE users SET watchlist_json=? WHERE user_id=?",
            (json.dumps(tickers), user_id)
        )
        self.conn.commit()

    def save_scan_results(self, scan_date: str, results: List[Dict]):
        self.conn.execute(
            "INSERT OR REPLACE INTO scan_results VALUES (?,?,?)",
            (scan_date, json.dumps(results, ensure_ascii=False),
             datetime.now().isoformat())
        )
        self.conn.commit()

    def get_latest_scan_results(self) -> Optional[List[Dict]]:
        row = self.conn.execute(
            "SELECT results_json FROM scan_results ORDER BY scan_date DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None

    def add_message(self, user_id: str, role: str, content: str):
        self.conn.execute(
            "INSERT INTO conversations (user_id, role, content, created_at) VALUES (?,?,?,?)",
            (user_id, role, content, datetime.now().isoformat())
        )
        self.conn.commit()

    def get_history(self, user_id: str, limit: int = 20) -> List[Dict]:
        rows = self.conn.execute(
            "SELECT role, content FROM conversations WHERE user_id=? "
            "ORDER BY id DESC LIMIT ?",
            (user_id, limit)
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def close(self):
        self.conn.close()
