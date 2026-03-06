import pytest
from datetime import date
from src.dividend_store import DividendStore
from src.data_engine import TickerData
from tests.test_scanners import make_ticker  # Use existing helper


def _make_ticker(ticker: str, score: float = 75.0) -> TickerData:
    return TickerData(
        ticker=ticker, name=ticker, market="US",
        last_price=100.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=99.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=score, consecutive_years=8,
        dividend_growth_5y=5.0, payout_ratio=65.0,
        dividend_yield=3.5, payout_type="GAAP",
    )


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


def test_list_versions_returns_version_history(tmp_path):
    """list_versions() returns all saved versions sorted by created_at DESC."""
    store = DividendStore(str(tmp_path / "test.db"))
    pool_v1 = [_make_ticker("AAPL", score=80)]
    pool_v2 = [_make_ticker("AAPL", score=82), _make_ticker("MSFT", score=85)]

    store.save_pool(pool_v1, version="monthly_2026-01")
    store.save_pool(pool_v2, version="monthly_2026-02")

    versions = store.list_versions()
    assert len(versions) == 2
    assert versions[0]["version"] == "monthly_2026-02"   # most recent first
    assert versions[0]["tickers_count"] == 2
    assert versions[1]["version"] == "monthly_2026-01"
    assert versions[1]["tickers_count"] == 1
    store.close()


def test_get_pool_by_version_returns_correct_snapshot(tmp_path):
    """get_pool_by_version() retrieves the exact tickers for a given version."""
    store = DividendStore(str(tmp_path / "test.db"))
    pool_v1 = [_make_ticker("KO", score=85)]
    pool_v2 = [_make_ticker("KO", score=86), _make_ticker("PG", score=88)]

    store.save_pool(pool_v1, version="monthly_2026-01")
    store.save_pool(pool_v2, version="monthly_2026-02")

    result_v1 = store.get_pool_by_version("monthly_2026-01")
    assert len(result_v1) == 1
    assert result_v1[0]["ticker"] == "KO"

    result_v2 = store.get_pool_by_version("monthly_2026-02")
    assert len(result_v2) == 2
    tickers = {r["ticker"] for r in result_v2}
    assert tickers == {"KO", "PG"}
    store.close()


def test_save_pool_preserves_payout_type(tmp_path):
    """save_pool() stores payout_type field and get_pool_by_version() returns it."""
    store = DividendStore(str(tmp_path / "test.db"))
    td = _make_ticker("ENB", score=78)
    td.payout_type = "FCF"
    td.payout_ratio = 64.0

    store.save_pool([td], version="monthly_2026-03")
    result = store.get_pool_by_version("monthly_2026-03")
    assert result[0]["payout_type"] == "FCF"
    store.close()


def test_get_current_pool_uses_latest_version(tmp_path):
    """get_current_pool() returns tickers from the most recently saved version."""
    store = DividendStore(str(tmp_path / "test.db"))
    store.save_pool([_make_ticker("KO")], version="monthly_2026-01")
    store.save_pool([_make_ticker("PG"), _make_ticker("JNJ")], version="monthly_2026-02")

    pool = store.get_current_pool()
    assert set(pool) == {"PG", "JNJ"}
    store.close()
