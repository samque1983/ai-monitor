# src/iv_store.py
import sqlite3
import logging
from datetime import date, timedelta
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)


class IVStore:
    """SQLite store for daily IV snapshots, used to compute IV Rank."""

    MIN_DATA_POINTS = 20

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._create_table()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS iv_history (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                iv REAL NOT NULL,
                PRIMARY KEY (ticker, date)
            )
        """)
        self.conn.commit()

    def save_iv(self, ticker: str, dt: date, iv: float):
        self.conn.execute(
            "INSERT OR REPLACE INTO iv_history (ticker, date, iv) VALUES (?, ?, ?)",
            (ticker, dt.isoformat(), iv),
        )
        self.conn.commit()

    def get_iv_history(self, ticker: str, days: int = 365) -> List[Tuple[str, float]]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        cursor = self.conn.execute(
            "SELECT date, iv FROM iv_history WHERE ticker = ? AND date >= ? ORDER BY date",
            (ticker, cutoff),
        )
        return cursor.fetchall()

    def compute_iv_rank(self, ticker: str, current_iv: float) -> Optional[float]:
        """IV Rank = (current - 52w_low) / (52w_high - 52w_low) * 100"""
        history = self.get_iv_history(ticker, days=365)
        if len(history) < self.MIN_DATA_POINTS:
            return None

        ivs = [row[1] for row in history]
        iv_min = min(ivs)
        iv_max = max(ivs)

        if iv_max == iv_min:
            return 50.0

        rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
        return round(rank, 1)

    def close(self):
        self.conn.close()
