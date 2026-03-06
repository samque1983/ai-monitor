# src/card_store.py
import sqlite3, json, logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class CardStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS opportunity_cards (
            card_id      TEXT PRIMARY KEY,
            ticker       TEXT NOT NULL,
            strategy     TEXT NOT NULL,
            card_json    TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            signal_hash  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_cache (
            ticker                TEXT PRIMARY KEY,
            fundamentals_json     TEXT,
            valuation_json        TEXT,
            next_earnings         TEXT,
            cached_at             TEXT,
            fundamentals_expires  TEXT,
            valuation_expires     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_cards_ticker_strategy
            ON opportunity_cards(ticker, strategy);
        """)
        self.conn.commit()

    def save_card(self, card_id: str, ticker: str, strategy: str,
                  card: Dict, signal_hash: str,
                  created_at: Optional[datetime] = None):
        ts = (created_at or datetime.now()).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO opportunity_cards VALUES (?,?,?,?,?,?)",
            (card_id, ticker, strategy, json.dumps(card, ensure_ascii=False), ts, signal_hash)
        )
        self.conn.commit()

    def get_card(self, ticker: str, strategy: str,
                 ttl_hours: int = 24) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT card_json, created_at FROM opportunity_cards "
            "WHERE ticker=? AND strategy=? ORDER BY created_at DESC LIMIT 1",
            (ticker, strategy)
        ).fetchone()
        if not row:
            return None
        created = datetime.fromisoformat(row[1])
        if datetime.now() - created > timedelta(hours=ttl_hours):
            return None
        return json.loads(row[0])

    def save_analysis(self, ticker: str, fundamentals: Dict, valuation: Dict,
                      next_earnings: str, fundamentals_expires: str, valuation_expires: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO analysis_cache VALUES (?,?,?,?,?,?,?)",
            (ticker, json.dumps(fundamentals, ensure_ascii=False),
             json.dumps(valuation, ensure_ascii=False),
             next_earnings, datetime.now().isoformat(),
             fundamentals_expires, valuation_expires)
        )
        self.conn.commit()

    def get_analysis(self, ticker: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        row = self.conn.execute(
            "SELECT fundamentals_json, valuation_json, "
            "fundamentals_expires, valuation_expires "
            "FROM analysis_cache WHERE ticker=?", (ticker,)
        ).fetchone()
        if not row:
            return None, None
        today = datetime.now().date().isoformat()
        try:
            f = json.loads(row[0]) if row[2] and row[2] >= today else None
        except (json.JSONDecodeError, TypeError):
            f = None
        try:
            v = json.loads(row[1]) if row[3] and row[3] >= today else None
        except (json.JSONDecodeError, TypeError):
            v = None
        return f, v

    def close(self):
        try:
            self.conn.close()
        except Exception:
            pass
