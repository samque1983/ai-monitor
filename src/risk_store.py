"""SQLite storage for portfolio risk reports."""
import json
import sqlite3
from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any

from src.strategy_risk import StrategyRiskReport as RiskReport

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS risk_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL,
    report_date     DATE NOT NULL,
    generated_at    TIMESTAMP NOT NULL,
    report_html     TEXT NOT NULL,
    summary_json    JSON NOT NULL,
    net_liquidation REAL,
    total_pnl       REAL,
    cushion         REAL
);
CREATE INDEX IF NOT EXISTS idx_risk_reports_account_date
    ON risk_reports(account_id, report_date);
"""


class RiskStore:
    def __init__(self, db_path: str = "data/risk_reports.db"):
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_CREATE_TABLE)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def save_report(self, report: RiskReport, html: str) -> None:
        summary = json.dumps(report.summary_stats)
        generated_at = datetime.utcnow().isoformat()
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM risk_reports WHERE account_id=? AND report_date=?",
                (report.account_id, report.report_date),
            )
            conn.execute(
                """INSERT INTO risk_reports
                   (account_id, report_date, generated_at, report_html,
                    summary_json, net_liquidation, total_pnl, cushion)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (report.account_id, report.report_date, generated_at, html,
                 summary, report.net_liquidation, report.total_pnl, report.cushion),
            )
            conn.commit()

    def get_latest_report(self, account_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM risk_reports WHERE account_id=? ORDER BY report_date DESC LIMIT 1",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_history(self, account_id: str, days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT report_date, cushion, total_pnl, net_liquidation, summary_json
                   FROM risk_reports
                   WHERE account_id=? AND report_date >= ?
                   ORDER BY report_date ASC""",
                (account_id, cutoff),
            ).fetchall()
        return [dict(r) for r in rows]
