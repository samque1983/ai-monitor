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


def test_save_and_get_yield_percentile():
    """应能保存历史数据并计算分位数"""
    store = DividendStore(db_path=':memory:')

    # 保存10个历史数据点
    yields = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]
    for i, yield_value in enumerate(yields):
        store.save_dividend_history(
            ticker='AAPL',
            date=date(2021 + i // 4, 1 + (i % 4) * 3, 1),
            dividend_yield=yield_value,
            annual_dividend=yield_value * 100.0,  # 假设价格100
            price=100.0
        )

    # 测试高分位数：当前收益率7.2%高于90%的历史值
    percentile_high = store.get_yield_percentile('AAPL', 7.2)
    assert percentile_high >= 90.0

    # 测试中等分位数：当前收益率5.1%处于中间位置
    percentile_mid = store.get_yield_percentile('AAPL', 5.1)
    assert 40.0 <= percentile_mid <= 60.0
