import pytest
from datetime import date, timedelta
from src.dividend_store import DividendStore, YieldPercentileResult
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
    assert 'defensiveness_cache' in tables
    assert 'analysis_cache' in tables


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
    result_high = store.get_yield_percentile('AAPL', 7.2)
    assert result_high.percentile >= 90.0

    # 测试中等分位数：当前收益率5.1%处于中间位置
    result_mid = store.get_yield_percentile('AAPL', 5.1)
    assert 40.0 <= result_mid.percentile <= 60.0


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


def test_get_last_scan_date_returns_none_when_empty(tmp_path):
    """get_last_scan_date() returns None when no versions exist."""
    store = DividendStore(str(tmp_path / "test.db"))
    assert store.get_last_scan_date() is None
    store.close()


def test_get_last_scan_date_returns_latest_version_date(tmp_path):
    """get_last_scan_date() returns the date of the most recent saved version."""
    store = DividendStore(str(tmp_path / "test.db"))
    store.save_pool([_make_ticker("KO")], version="2026-01-01")
    store.save_pool([_make_ticker("PG")], version="2026-03-01")

    result = store.get_last_scan_date()
    assert result == date(2026, 3, 1)
    store.close()


def test_save_and_get_defensiveness_score(tmp_path):
    store = DividendStore(str(tmp_path / "test.db"))
    # Not yet cached → returns None
    assert store.get_defensiveness_score("Utilities", "Electric Utilities") is None

    store.save_defensiveness_score("Utilities", "Electric Utilities", 85.0, "需求刚性，无周期风险")
    result = store.get_defensiveness_score("Utilities", "Electric Utilities")
    assert result is not None
    score, rationale = result
    assert score == 85.0
    assert "刚性" in rationale
    store.close()


def test_defensiveness_score_expired(tmp_path):
    from datetime import date, timedelta
    store = DividendStore(str(tmp_path / "test.db"))
    # Save with a past expiry date directly via SQL
    cursor = store.conn.cursor()
    expired = (date.today() - timedelta(days=1)).isoformat()
    cursor.execute(
        "INSERT INTO defensiveness_cache (sector, industry, score, rationale, expires) VALUES (?,?,?,?,?)",
        ("Technology", "Software", 40.0, "高周期性", expired),
    )
    store.conn.commit()
    # Expired → returns None
    assert store.get_defensiveness_score("Technology", "Software") is None
    store.close()


def test_pool_records_returns_new_columns(tmp_path):
    """get_pool_records should return quality_breakdown dict and analysis_text."""
    import json
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)

    td = TickerData(
        ticker="KO", name="Coca-Cola", market="US",
        last_price=62.5, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=62.5,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=85.0,
        quality_breakdown={"continuity": 18.0, "growth": 10.0, "payout_safety": 20.0,
                           "financial_health": 17.0, "defensiveness": 16.0},
        analysis_text="KO has 62 years of consecutive dividend growth.",
        forward_dividend_rate=1.94,
        max_yield_5y=4.5,
        data_version_date=None,
    )
    store.save_pool([td], version="2026-03-09")

    records = store.get_pool_records()
    assert len(records) == 1
    r = records[0]
    assert r["ticker"] == "KO"
    assert isinstance(r["quality_breakdown"], dict)
    assert r["quality_breakdown"]["continuity"] == 18.0
    assert r["analysis_text"] == "KO has 62 years of consecutive dividend growth."
    assert r["forward_dividend_rate"] == 1.94
    assert r["max_yield_5y"] == 4.5
    store.close()


def test_analysis_text_cache(tmp_path):
    """save_analysis_text and get_analysis_text should cache with TTL."""
    from src.dividend_store import DividendStore
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    text = "确定性业务：KO is a moat stock. → $55-60\n增量新业务：暂无明显增量业务 → $62\n估值区间：基于股息率定价 → $55-65"
    store.save_analysis_text("KO", text)
    assert store.get_analysis_text("KO") == text
    assert store.get_analysis_text("MSFT") is None
    store.close()


def test_analysis_text_cache_expired(tmp_path):
    """get_analysis_text should return None for expired entries."""
    from src.dividend_store import DividendStore
    from datetime import date, timedelta
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    # Save with a TTL of 0 days (expires today — will be < tomorrow)
    # Force expiry by writing directly with a past date
    import sqlite3
    conn = sqlite3.connect(db_path)
    past_date = (date.today() - timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO analysis_cache (ticker, text, expires) VALUES (?,?,?)",
        ("KO", "some text", past_date)
    )
    conn.commit()
    conn.close()
    assert store.get_analysis_text("KO") is None
    store.close()


def test_save_and_load_sgov_yield(tmp_path):
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="AAPL", name="Apple", market="US",
        last_price=0.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=80.0,
        sgov_yield=4.8,
    )
    store.save_pool([td], "2026-03-11")
    records = store.get_pool_records()
    assert records[0]["sgov_yield"] == 4.8


def test_sgov_yield_defaults_none(tmp_path):
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="VZ", name="Verizon", market="US",
        last_price=0.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=0.0,
        earnings_date=None, days_to_earnings=None,
    )
    store.save_pool([td], "2026-03-11")
    records = store.get_pool_records()
    assert records[0]["sgov_yield"] is None


def test_get_yield_percentile_returns_result_type():
    """get_yield_percentile should return YieldPercentileResult, not float.
    Uses 30 data points so p10/p90 are populated."""
    store = DividendStore(db_path=':memory:')
    for i in range(30):
        y = 3.0 + i * 0.15  # 3.0 .. 7.35
        store.save_dividend_history('AAPL', date(2021, 1, 1) + timedelta(days=i * 7),
                                    y, y * 100, 100.0)

    result = store.get_yield_percentile('AAPL', 7.2)

    assert isinstance(result, YieldPercentileResult)
    assert result.percentile >= 90.0
    assert result.p10 is not None
    assert result.p90 is not None
    assert result.hist_max is not None
    assert result.p10 < result.p90
    assert result.hist_max >= result.p90


def test_save_and_get_pool_includes_health_rationale(tmp_path):
    """health_rationale is persisted and returned in get_pool_records."""
    from src.dividend_store import DividendStore
    from src.data_engine import TickerData
    store = DividendStore(str(tmp_path / "test.db"))
    td = TickerData(
        ticker="KMB", name="Kimberly-Clark", market="US",
        last_price=130.0, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=130.0,
        earnings_date=None, days_to_earnings=None,
        dividend_quality_score=77.0, consecutive_years=11,
        dividend_growth_5y=7.0, payout_ratio=55.0, payout_type="LLM",
        health_rationale="KMB负净资产结构，FCF派息率约55%，实际安全",
    )
    store.save_pool([td], version="2026-03-12")
    records = store.get_pool_records()
    assert len(records) == 1
    assert records[0]["health_rationale"] == "KMB负净资产结构，FCF派息率约55%，实际安全"


def test_save_and_get_health_assessment(tmp_path):
    """Health assessment round-trips through analysis_cache with :health key."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    store.save_health_assessment("KMB", health_score=72.0, fcf_payout_est=55.0,
                                  rationale="KMB负净资产结构，FCF派息率约55%，实际安全")
    result = store.get_health_assessment("KMB")
    assert result is not None
    assert result["health_score"] == 72.0
    assert result["fcf_payout_est"] == 55.0
    assert "负净资产" in result["rationale"]


def test_health_assessment_cache_miss_returns_none(tmp_path):
    """Returns None when no cached health assessment exists."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    assert store.get_health_assessment("UNKNOWN") is None


def test_get_yield_percentile_winsorized():
    """Top 5% values should not inflate the percentile calculation."""
    store = DividendStore(db_path=':memory:')
    # 100 normal values 3.0–7.0, then 10 extreme crisis values at 25.0
    for i in range(100):
        store.save_dividend_history('AAPL', date(2021, 1, 1) + timedelta(days=i),
                                    3.0 + i * 0.04, (3.0 + i * 0.04) * 100, 100.0)
    for i in range(10):
        store.save_dividend_history('AAPL', date(2023, 1, 1) + timedelta(days=i),
                                    25.0, 100.0, 100.0)

    result = store.get_yield_percentile('AAPL', 6.5)
    # After Winsorizing top 5%, a 6.5% yield should still show as high percentile
    assert result.percentile >= 70.0
    # hist_max should capture the real extreme (25.0)
    assert result.hist_max >= 20.0


def test_get_yield_percentile_p10_p90_requires_30_points():
    """p10/p90 should be None when fewer than 30 data points exist."""
    store = DividendStore(db_path=':memory:')
    for i in range(10):
        store.save_dividend_history('AAPL', date(2021, 1, i + 1), 4.0 + i * 0.1, 100.0, 100.0)

    result = store.get_yield_percentile('AAPL', 4.5)
    assert result.p10 is None
    assert result.p90 is None
    assert isinstance(result.percentile, float)


def test_get_yield_percentile_no_history_returns_default():
    """No history returns 50.0 percentile with None p10/p90 (existing behavior)."""
    store = DividendStore(db_path=':memory:')
    result = store.get_yield_percentile('AAPL', 5.0)
    assert result.percentile == 50.0
    assert result.p10 is None
    assert result.p90 is None
    assert result.hist_max is None


def test_get_yield_percentile_value_returns_75th(tmp_path):
    """Returns the 75th percentile yield value from stored history."""
    import numpy as np
    store = DividendStore(str(tmp_path / "test.db"))
    yields = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    for i, y in enumerate(yields):
        store.save_dividend_history("AAPL", date(2023, i + 1, 1), y, y * 0.01, 100.0)
    result = store.get_yield_percentile_value("AAPL", 75)
    assert result is not None
    expected = round(float(np.percentile(yields, 75)), 4)
    assert abs(result - expected) < 0.001
    store.close()


def test_get_yield_percentile_value_returns_none_insufficient_data(tmp_path):
    """Returns None when fewer than 8 data points exist."""
    store = DividendStore(str(tmp_path / "test2.db"))
    for i in range(5):
        store.save_dividend_history("AAPL", date(2023, i + 1, 1), float(i + 1), 0.1, 100.0)
    result = store.get_yield_percentile_value("AAPL", 75)
    assert result is None
    store.close()


def test_get_yield_percentile_value_returns_none_no_history(tmp_path):
    """Returns None when no history exists for ticker."""
    store = DividendStore(str(tmp_path / "test3.db"))
    result = store.get_yield_percentile_value("AAPL", 75)
    assert result is None
    store.close()


def test_save_pool_includes_golden_price(tmp_path):
    """save_pool stores golden_price; get_pool_records returns it."""
    store = DividendStore(str(tmp_path / "test4.db"))
    td = _make_ticker("AAPL")
    td.golden_price = 123.45
    store.save_pool([td], "2026-03-14")
    records = store.get_pool_records()
    assert records[0]["golden_price"] == 123.45
    store.close()
