import sqlite3
import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Dict, Optional
from src.data_engine import TickerData

logger = logging.getLogger(__name__)


@dataclass
class YieldPercentileResult:
    percentile: float
    p10: Optional[float]
    p90: Optional[float]
    hist_max: Optional[float]


class DividendStore:
    """SQLite存储股息股票池和历史数据"""

    def __init__(self, db_path: str):
        """初始化数据库连接并创建表"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        logger.info(f"DividendStore initialized with database: {db_path}")

    def _create_tables(self):
        """创建必需的数据库表（含 schema 迁移）"""
        cursor = self.conn.cursor()

        # Migrate old schema if needed:
        # - v1: ticker TEXT PRIMARY KEY, no version column
        # - v1.5: has version column but as plain TEXT (not PK), no payout_type
        # - v2 (current): PRIMARY KEY (ticker, version), has payout_type
        cursor.execute("PRAGMA table_info(dividend_pool)")
        cols = {row[1] for row in cursor.fetchall()}
        if cols and ('version' not in cols or 'payout_type' not in cols):
            cursor.execute("DROP TABLE IF EXISTS dividend_pool")
            logger.info("Migrated dividend_pool table: old schema dropped")

        # Table 1: dividend_pool - 版本化股票池
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_pool (
                ticker TEXT NOT NULL,
                version TEXT NOT NULL,
                name TEXT,
                market TEXT,
                quality_score REAL,
                consecutive_years INTEGER,
                dividend_growth_5y REAL,
                payout_ratio REAL,
                payout_type TEXT,
                dividend_yield REAL,
                roe REAL,
                debt_to_equity REAL,
                industry TEXT,
                sector TEXT,
                added_date TEXT,
                PRIMARY KEY (ticker, version)
            )
        """)

        # Migrate dividend_pool: add enrichment columns if missing
        cursor.execute("PRAGMA table_info(dividend_pool)")
        pool_cols = {row[1] for row in cursor.fetchall()}
        for col, col_type in [
            ("quality_breakdown", "TEXT"),
            ("analysis_text", "TEXT"),
            ("forward_dividend_rate", "REAL"),
            ("max_yield_5y", "REAL"),
            ("data_version_date", "TEXT"),
            ("sgov_yield", "REAL"),
            ("health_rationale", "TEXT"),
        ]:
            if col not in pool_cols and pool_cols:
                cursor.execute(f"ALTER TABLE dividend_pool ADD COLUMN {col} {col_type}")
                logger.info(f"Migrated dividend_pool: added column {col}")

        # Table 2: dividend_history - 历史股息数据（每日快照）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_history (
                ticker TEXT,
                date TEXT,
                dividend_yield REAL,
                annual_dividend REAL,
                price REAL,
                PRIMARY KEY (ticker, date)
            )
        """)

        # Table 3: screening_versions - 筛选版本记录
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screening_versions (
                version TEXT PRIMARY KEY,
                created_at TEXT,
                tickers_count INTEGER,
                avg_quality_score REAL
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS defensiveness_cache (
                sector   TEXT NOT NULL,
                industry TEXT NOT NULL,
                score    REAL NOT NULL,
                rationale TEXT,
                expires  TEXT NOT NULL,
                PRIMARY KEY (sector, industry)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS analysis_cache (
                ticker   TEXT PRIMARY KEY,
                text     TEXT NOT NULL,
                expires  TEXT NOT NULL
            )
        """)

        self.conn.commit()
        logger.info("Database tables created successfully")

    def save_pool(self, tickers: List[TickerData], version: str):
        """保存股票池（按版本存储，保留历史版本）"""
        cursor = self.conn.cursor()

        # Delete only this version's records (preserve other versions)
        cursor.execute("DELETE FROM dividend_pool WHERE version = ?", (version,))

        for ticker in tickers:
            cursor.execute("""
                INSERT INTO dividend_pool (
                    ticker, version, name, market, quality_score,
                    consecutive_years, dividend_growth_5y, payout_ratio,
                    payout_type, dividend_yield, roe, debt_to_equity,
                    industry, sector, added_date,
                    quality_breakdown, analysis_text, forward_dividend_rate,
                    max_yield_5y, data_version_date, sgov_yield, health_rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker.ticker, version, ticker.name, ticker.market,
                ticker.dividend_quality_score, ticker.consecutive_years,
                ticker.dividend_growth_5y, ticker.payout_ratio,
                getattr(ticker, 'payout_type', None),
                getattr(ticker, 'dividend_yield', None),
                ticker.roe, ticker.debt_to_equity,
                ticker.industry, ticker.sector,
                date.today().isoformat(),
                json.dumps(getattr(ticker, 'quality_breakdown', None) or {}),
                getattr(ticker, 'analysis_text', None) or "",
                getattr(ticker, 'forward_dividend_rate', None),
                getattr(ticker, 'max_yield_5y', None),
                date.today().isoformat(),
                getattr(ticker, 'sgov_yield', None),
                getattr(ticker, 'health_rationale', None),
            ))

        quality_scores = [t.dividend_quality_score for t in tickers if t.dividend_quality_score is not None]
        avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        cursor.execute("""
            INSERT OR REPLACE INTO screening_versions (
                version, created_at, tickers_count, avg_quality_score
            ) VALUES (?, ?, ?, ?)
        """, (version, datetime.now().isoformat(), len(tickers), avg_score))

        self.conn.commit()
        logger.info(f"Saved {len(tickers)} tickers to pool (version: {version})")

    def get_last_scan_date(self) -> "date | None":
        """Return the date of the most recent screening version, or None if empty."""
        versions = self.list_versions()
        if not versions:
            return None
        try:
            return date.fromisoformat(versions[0]["version"])
        except (ValueError, KeyError):
            return None

    def get_current_pool(self) -> List[str]:
        """获取最新版本的ticker列表"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ticker FROM dividend_pool
            WHERE version = (
                SELECT version FROM screening_versions
                ORDER BY created_at DESC LIMIT 1
            )
        """)
        return [row[0] for row in cursor.fetchall()]

    def list_versions(self) -> List[Dict]:
        """Return all screening versions sorted by created_at DESC."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT version, created_at, tickers_count, avg_quality_score
            FROM screening_versions
            ORDER BY created_at DESC
        """)
        return [
            {"version": row[0], "created_at": row[1],
             "tickers_count": row[2], "avg_quality_score": row[3]}
            for row in cursor.fetchall()
        ]

    def get_pool_by_version(self, version: str) -> List[Dict]:
        """Return full pool records for a given version, sorted by quality_score DESC."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ticker, name, market, quality_score, consecutive_years,
                   dividend_growth_5y, payout_ratio, payout_type, dividend_yield,
                   roe, debt_to_equity, industry, sector
            FROM dividend_pool
            WHERE version = ?
            ORDER BY quality_score DESC
        """, (version,))
        cols = ["ticker", "name", "market", "quality_score", "consecutive_years",
                "dividend_growth_5y", "payout_ratio", "payout_type", "dividend_yield",
                "roe", "debt_to_equity", "industry", "sector"]
        return [dict(zip(cols, row)) for row in cursor.fetchall()]

    def get_pool_records(self) -> List[Dict]:
        """Return full records for the current pool version, including all enrichment fields."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT ticker, name, market, quality_score, consecutive_years,
                   dividend_growth_5y, payout_ratio, payout_type, dividend_yield,
                   roe, debt_to_equity, industry, sector,
                   quality_breakdown, analysis_text, forward_dividend_rate,
                   max_yield_5y, data_version_date, sgov_yield, health_rationale
            FROM dividend_pool
            WHERE version = (
                SELECT version FROM screening_versions
                ORDER BY created_at DESC LIMIT 1
            )
            ORDER BY quality_score DESC
        """)
        cols = [
            "ticker", "name", "market", "quality_score", "consecutive_years",
            "dividend_growth_5y", "payout_ratio", "payout_type", "dividend_yield",
            "roe", "debt_to_equity", "industry", "sector",
            "quality_breakdown", "analysis_text", "forward_dividend_rate",
            "max_yield_5y", "data_version_date", "sgov_yield", "health_rationale",
        ]
        records = []
        for row in cursor.fetchall():
            d = dict(zip(cols, row))
            if d.get("quality_breakdown"):
                try:
                    d["quality_breakdown"] = json.loads(d["quality_breakdown"])
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"quality_breakdown JSON parse error for {d.get('ticker')}: {e}")
                    d["quality_breakdown"] = {}
            records.append(d)
        return records

    def save_dividend_history(self, ticker: str, date: date, dividend_yield: float, annual_dividend: float, price: float):
        """保存单个历史股息数据点"""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO dividend_history (
                ticker, date, dividend_yield, annual_dividend, price
            ) VALUES (?, ?, ?, ?, ?)
        """, (
            ticker,
            date.isoformat(),
            dividend_yield,
            annual_dividend,
            price
        ))
        self.conn.commit()

    def get_yield_percentile(self, ticker: str, current_yield: float) -> "YieldPercentileResult":
        """计算当前股息率在5年历史中的分位数（Winsorized — 剔除顶部5%极值）"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT dividend_yield FROM dividend_history
            WHERE ticker = ?
            ORDER BY date DESC
            LIMIT 1250
        """, (ticker,))

        historical_yields = [row[0] for row in cursor.fetchall()]

        if not historical_yields:
            logger.warning(f"No historical dividend data for {ticker}, returning default percentile 50.0")
            return YieldPercentileResult(percentile=50.0, p10=None, p90=None, hist_max=None)

        n = len(historical_yields)
        hist_max = max(historical_yields)

        # Sort once; reuse for both p10/p90 and Winsorized percentile
        sorted_all = sorted(historical_yields)

        p10: Optional[float] = None
        p90: Optional[float] = None
        if n >= 30:
            p10 = sorted_all[int(n * 0.10)]
            p90 = sorted_all[int(n * 0.90)]

        # Winsorized percentile: exclude top 5% to dampen crisis spikes
        cutoff_idx = max(1, int(n * 0.95))
        trimmed = sorted_all[:cutoff_idx]
        count_below_or_equal = sum(1 for y in trimmed if y <= current_yield)
        percentile = (count_below_or_equal / len(trimmed)) * 100

        return YieldPercentileResult(
            percentile=round(percentile, 1),
            p10=round(p10, 2) if p10 is not None else None,
            p90=round(p90, 2) if p90 is not None else None,
            hist_max=round(hist_max, 2),
        )

    def get_defensiveness_score(self, sector: str, industry: str):
        """Return (score, rationale) if cached and not expired, else None."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT score, rationale, expires FROM defensiveness_cache WHERE sector=? AND industry=?",
            (sector, industry),
        )
        row = cursor.fetchone()
        if not row:
            return None
        score, rationale, expires = row
        if expires < date.today().isoformat():
            return None
        return score, rationale

    def save_defensiveness_score(self, sector: str, industry: str, score: float, rationale: str):
        """Persist defensiveness score with 30-day TTL."""
        expires = (date.today() + timedelta(days=30)).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO defensiveness_cache (sector, industry, score, rationale, expires) VALUES (?,?,?,?,?)",
            (sector, industry, score, rationale, expires),
        )
        self.conn.commit()

    def get_analysis_text(self, ticker: str) -> Optional[str]:
        """Return cached analysis text if not expired and in current format, else None."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT text, expires FROM analysis_cache WHERE ticker=?", (ticker,)
        )
        row = cursor.fetchone()
        if not row:
            return None
        text, expires = row
        if expires < date.today().isoformat():
            return None
        # Invalidate old-format entries that don't include price ranges (→ marker)
        if "→" not in text:
            return None
        return text

    def clear_analysis_cache(self):
        """Delete all entries from analysis_cache (forces LLM regeneration on next scan)."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM analysis_cache")
        deleted = cursor.rowcount
        self.conn.commit()
        logger.info(f"Cleared analysis_cache: {deleted} entries deleted")
        return deleted

    def get_health_assessment(self, ticker: str) -> Optional[Dict]:
        """Return cached LLM health assessment dict or None if missing/expired."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT text, expires FROM analysis_cache WHERE ticker=?", (f"{ticker}:health",)
        )
        row = cursor.fetchone()
        if not row:
            return None
        text, expires = row
        if expires < date.today().isoformat():
            return None
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return None

    def save_health_assessment(self, ticker: str, health_score: float,
                                fcf_payout_est: float, rationale: str,
                                ttl_days: int = 7):
        """Persist LLM health assessment with TTL (default 7 days)."""
        expires = (date.today() + timedelta(days=ttl_days)).isoformat()
        payload = json.dumps({"health_score": health_score,
                              "fcf_payout_est": fcf_payout_est,
                              "rationale": rationale})
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO analysis_cache (ticker, text, expires) VALUES (?,?,?)",
            (f"{ticker}:health", payload, expires),
        )
        self.conn.commit()

    def save_analysis_text(self, ticker: str, text: str, ttl_days: int = 7):
        """Persist analysis text with TTL (default 7 days)."""
        expires = (date.today() + timedelta(days=ttl_days)).isoformat()
        cursor = self.conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO analysis_cache (ticker, text, expires) VALUES (?,?,?)",
            (ticker, text, expires),
        )
        self.conn.commit()

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info(f"Database connection closed: {self.db_path}")
