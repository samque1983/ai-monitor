import sqlite3
import logging
from datetime import date, datetime
from typing import List
from src.data_engine import TickerData

logger = logging.getLogger(__name__)


class DividendStore:
    """SQLite存储股息股票池和历史数据"""

    def __init__(self, db_path: str):
        """初始化数据库连接并创建表"""
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_tables()
        logger.info(f"DividendStore initialized with database: {db_path}")

    def _create_tables(self):
        """创建必需的数据库表"""
        cursor = self.conn.cursor()

        # Table 1: dividend_pool - 当前股票池
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_pool (
                ticker TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                quality_score REAL,
                consecutive_years INTEGER,
                dividend_growth_5y REAL,
                payout_ratio REAL,
                roe REAL,
                debt_to_equity REAL,
                industry TEXT,
                sector TEXT,
                added_date TEXT,
                version TEXT
            )
        """)

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

        self.conn.commit()
        logger.info("Database tables created successfully")

    def save_pool(self, tickers: List[TickerData], version: str):
        """保存股票池（替换式更新）"""
        cursor = self.conn.cursor()

        # Step 1: Delete old pool
        cursor.execute("DELETE FROM dividend_pool")
        logger.info("Cleared existing dividend pool")

        # Step 2: Insert new tickers
        for ticker in tickers:
            cursor.execute("""
                INSERT INTO dividend_pool (
                    ticker, name, market, quality_score, consecutive_years,
                    dividend_growth_5y, payout_ratio, roe, debt_to_equity,
                    industry, sector, added_date, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker.ticker,
                ticker.name,
                ticker.market,
                ticker.dividend_quality_score,
                ticker.consecutive_years,
                ticker.dividend_growth_5y,
                ticker.payout_ratio,
                ticker.roe,
                ticker.debt_to_equity,
                ticker.industry,
                ticker.sector,
                date.today().isoformat(),
                version
            ))

        # Step 3: Record screening version
        quality_scores = [t.dividend_quality_score for t in tickers if t.dividend_quality_score is not None]
        avg_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0

        cursor.execute("""
            INSERT OR REPLACE INTO screening_versions (
                version, created_at, tickers_count, avg_quality_score
            ) VALUES (?, ?, ?, ?)
        """, (
            version,
            datetime.now().isoformat(),
            len(tickers),
            avg_score
        ))

        self.conn.commit()
        logger.info(f"Saved {len(tickers)} tickers to dividend pool (version: {version})")

    def get_current_pool(self) -> List[str]:
        """获取当前池子的ticker列表"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT ticker FROM dividend_pool")
        return [row[0] for row in cursor.fetchall()]

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

    def get_yield_percentile(self, ticker: str, current_yield: float) -> float:
        """计算当前股息率在5年历史中的分位数"""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT dividend_yield FROM dividend_history
            WHERE ticker = ?
            ORDER BY date DESC
        """, (ticker,))

        historical_yields = [row[0] for row in cursor.fetchall()]

        if not historical_yields:
            logger.warning(f"No historical dividend data for {ticker}, returning default percentile 50.0")
            return 50.0

        # 计算分位数：低于当前收益率的历史值占比
        # 高百分位数 = 当前收益率高 = 股票便宜
        count_below_or_equal = len([y for y in historical_yields if y <= current_yield])
        percentile = (count_below_or_equal / len(historical_yields)) * 100

        return percentile

    def close(self):
        """关闭数据库连接"""
        if self.conn:
            self.conn.close()
            logger.info(f"Database connection closed: {self.db_path}")
