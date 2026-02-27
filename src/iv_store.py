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

    def get_iv_n_days_ago(
        self,
        ticker: str,
        n: int = 5,
        reference_date: Optional[date] = None
    ) -> Optional[float]:
        """
        获取约 n 天前的 IV 值 (容差: n ~ n+3 天)

        Args:
            ticker: 股票代码
            n: 目标天数 (默认 5)
            reference_date: 参考日期 (默认今天)

        Returns:
            IV 值或 None (数据不足时)
        """
        if reference_date is None:
            reference_date = date.today()

        target_date = reference_date - timedelta(days=n)
        window_start = reference_date - timedelta(days=n + 3)

        cursor = self.conn.execute(
            """
            SELECT iv FROM iv_history
            WHERE ticker = ? AND date >= ? AND date <= ?
            ORDER BY date DESC LIMIT 1
            """,
            (ticker, window_start.isoformat(), target_date.isoformat())
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_data_sufficiency(self, ticker: str) -> dict:
        """
        检查 IV 历史数据的充足性

        Returns:
            {
                "total_days": int,
                "sufficient_for_ivp": bool,      # >= 30天
                "sufficient_for_momentum": bool  # >= 5天
            }
        """
        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM iv_history WHERE ticker = ?",
            (ticker,)
        )
        count = cursor.fetchone()[0]

        return {
            "total_days": count,
            "sufficient_for_ivp": count >= 30,
            "sufficient_for_momentum": count >= 5,
        }

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
