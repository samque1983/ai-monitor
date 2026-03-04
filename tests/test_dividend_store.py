import pytest
from datetime import date
from src.dividend_store import DividendStore
from tests.test_scanners import make_ticker  # Use existing helper


def test_dividend_store_init_creates_tables():
    """DividendStore应创建必需的数据库表"""
    store = DividendStore(db_path=':memory:')

    # 验证表存在
    cursor = store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    assert 'dividend_pool' in tables
    assert 'dividend_history' in tables
    assert 'screening_versions' in tables


def test_save_and_get_pool():
    """应能保存和读取股票池"""
    store = DividendStore(db_path=':memory:')

    tickers = [
        make_ticker(ticker='AAPL', dividend_quality_score=85.0, consecutive_years=10),
        make_ticker(ticker='MSFT', dividend_quality_score=88.0, consecutive_years=12),
    ]

    store.save_pool(tickers, version='weekly_2026-03-03')

    pool = store.get_current_pool()
    assert len(pool) == 2
    assert 'AAPL' in pool
    assert 'MSFT' in pool
