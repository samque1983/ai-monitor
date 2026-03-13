import sqlite3
import json
import logging
from datetime import datetime, timedelta
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

CREATE TABLE IF NOT EXISTS signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date   DATE NOT NULL,
    scanned_at  TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,
    category    TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    payload     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_scanned_at ON signals(scanned_at);

CREATE TABLE IF NOT EXISTS risk_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id   TEXT NOT NULL,
    report_date  TEXT NOT NULL,
    html_content TEXT NOT NULL,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(account_id, report_date)
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

    def _parse_watchlist(self, user: dict) -> List[Dict]:
        """Parse watchlist_json supporting both old (list of str) and new (list of dict) formats."""
        raw = json.loads(user.get("watchlist_json") or "[]")
        return [{"ticker": t} if isinstance(t, str) else t for t in raw]

    def add_to_watchlist(self, user_id: str, ticker: str, metadata: Optional[Dict] = None) -> List[Dict]:
        """Add ticker with optional metadata to watchlist (dedup, uppercase). Returns updated list of dicts."""
        ticker = ticker.upper().strip()
        user = self.get_user(user_id)
        if not user:
            self.save_user(user_id)
            user = self.get_user(user_id)
        items = self._parse_watchlist(user)
        if not any(i["ticker"] == ticker for i in items):
            entry: Dict = {"ticker": ticker}
            if metadata:
                entry.update(metadata)
            items.append(entry)
            self.conn.execute(
                "UPDATE users SET watchlist_json=? WHERE user_id=?",
                (json.dumps(items, ensure_ascii=False), user_id)
            )
            self.conn.commit()
        return items

    def remove_from_watchlist(self, user_id: str, ticker: str) -> List[Dict]:
        """Remove ticker from watchlist. No-op if not present. Returns updated list of dicts."""
        ticker = ticker.upper().strip()
        user = self.get_user(user_id)
        if not user:
            return []
        items = self._parse_watchlist(user)
        items = [i for i in items if i["ticker"] != ticker]
        self.conn.execute(
            "UPDATE users SET watchlist_json=? WHERE user_id=?",
            (json.dumps(items, ensure_ascii=False), user_id)
        )
        self.conn.commit()
        return items

    def get_strategy_pool(self, signal_type: str) -> List[Dict]:
        """Return all signals of given signal_type from the latest scan_date."""
        row = self.conn.execute(
            "SELECT MAX(scan_date) as latest FROM signals WHERE signal_type=?",
            (signal_type,)
        ).fetchone()
        if not row or not row["latest"]:
            return []
        rows = self.conn.execute(
            "SELECT ticker, payload FROM signals WHERE signal_type=? AND scan_date=?",
            (signal_type, row["latest"])
        ).fetchall()
        result = []
        for r in rows:
            entry = {"ticker": r["ticker"]}
            entry.update(json.loads(r["payload"]))
            result.append(entry)
        return result

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

    _CATEGORY_MAP = {
        "sell_put": "opportunity",
        "iv_low": "opportunity",
        "leaps": "opportunity",
        "dividend": "opportunity",
        "ma200_bullish": "opportunity",
        "iv_high": "risk",
        "ma200_bearish": "risk",
        "earnings_gap": "risk",
        "sell_put_earnings_risk": "risk",
        "iv_momentum": "risk",
    }

    def save_signals(self, scan_date: str, signals: List[Dict]) -> int:
        """Write signals for a scan_date. Idempotent: deletes existing rows first."""
        self.conn.execute("DELETE FROM signals WHERE scan_date=?", (scan_date,))
        # Use noon of scan_date so range filters work correctly for historical dates.
        # For today's date this will be earlier today; for past dates it will be in the past.
        try:
            scanned_at = datetime.fromisoformat(scan_date).replace(hour=12).isoformat()
        except ValueError:
            logger.warning("Invalid scan_date format %r, falling back to datetime.now()", scan_date)
            scanned_at = datetime.now().isoformat()
        rows = []
        for s in signals:
            signal_type = s.get("signal_type", "unknown")
            if signal_type in self._CATEGORY_MAP:
                category = self._CATEGORY_MAP[signal_type]
            else:
                logger.warning("Unknown signal_type: %r, categorizing as 'unknown'", signal_type)
                category = "unknown"
            ticker = s.get("ticker", "")
            payload = {k: v for k, v in s.items() if k not in ("signal_type", "ticker")}
            rows.append((scan_date, scanned_at, signal_type, category, ticker,
                         json.dumps(payload, ensure_ascii=False)))
        self.conn.executemany(
            "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) "
            "VALUES (?,?,?,?,?,?)",
            rows,
        )
        self.conn.commit()
        return len(rows)

    def get_signals(self, time_range: str = "24h", category: Optional[str] = None) -> List[Dict]:
        """Return signals within time range, optionally filtered by category."""
        range_hours = {"24h": 24, "7d": 168, "30d": 720}.get(time_range, 24)
        cutoff = (datetime.now() - timedelta(hours=range_hours)).isoformat()
        query = "SELECT * FROM signals WHERE scanned_at >= ?"
        params: list = [cutoff]
        if category and category != "all":
            query += " AND category=?"
            params.append(category)
        query += " ORDER BY scanned_at DESC"
        rows = self.conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d["payload"])
            result.append(d)
        return result

    def save_risk_report(self, account_id: str, report_date: str, html_content: str) -> None:
        """Save or overwrite a risk report for a given account and date."""
        self.conn.execute(
            "INSERT OR REPLACE INTO risk_reports (account_id, report_date, html_content) "
            "VALUES (?, ?, ?)",
            (account_id, report_date, html_content),
        )
        self.conn.commit()

    def get_latest_risk_report(self, account_id: str) -> Optional[Dict]:
        """Return the most recent risk report for an account, or None."""
        row = self.conn.execute(
            "SELECT account_id, report_date, html_content, created_at "
            "FROM risk_reports WHERE account_id=? ORDER BY report_date DESC LIMIT 1",
            (account_id,),
        ).fetchone()
        return dict(row) if row else None

    def get_risk_report_by_date(self, account_id: str, report_date: str) -> Optional[Dict]:
        """Return a specific date's risk report, or None."""
        row = self.conn.execute(
            "SELECT account_id, report_date, html_content, created_at "
            "FROM risk_reports WHERE account_id=? AND report_date=?",
            (account_id, report_date),
        ).fetchone()
        return dict(row) if row else None

    def get_risk_report_dates(self, account_id: str) -> List[str]:
        """Return all available report dates for an account, newest first."""
        rows = self.conn.execute(
            "SELECT report_date FROM risk_reports WHERE account_id=? ORDER BY report_date DESC",
            (account_id,),
        ).fetchall()
        return [r["report_date"] for r in rows]

    def close(self):
        self.conn.close()
