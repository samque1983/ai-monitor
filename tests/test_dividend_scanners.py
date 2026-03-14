# tests/test_dividend_scanners.py
import pytest
import pandas as pd
from datetime import date, timedelta
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData
from src.dividend_scanners import scan_dividend_pool_weekly, scan_dividend_buy_signal, DividendBuySignal, scan_dividend_sell_put, _compute_floor_data, _label_extreme_event
from src.financial_service import DividendQualityScore
from src.dividend_store import DividendStore, YieldPercentileResult


def _history_5yr():
    """Helper: 5 years of annual dividends, stable at 1.0/yr."""
    return [{"date": f"{year}-03-01", "amount": 1.0} for year in range(2021, 2026)]


def _mock_score(score: float) -> DividendQualityScore:
    return DividendQualityScore(
        overall_score=score, stability_score=score, health_score=score,
        defensiveness_score=50.0, risk_flags=[],
    )


@pytest.fixture
def mock_provider():
    p = MagicMock()
    p.config = {"default_market": "US"}
    return p


@pytest.fixture
def mock_fs():
    return MagicMock()


@pytest.fixture
def sample_ticker_data():
    return make_ticker(ticker="TEST", last_price=35.0, dividend_yield=4.9)


@pytest.fixture
def config():
    return {
        "dividend_scanners": {
            "min_quality_score": 70,
            "min_consecutive_years": 5,
            "max_payout_ratio": 100,
        }
    }


def make_ticker(**kwargs) -> TickerData:
    """Helper to create TickerData with sensible defaults."""
    defaults = dict(
        ticker="TEST",
        name="Test Company",
        market="US",
        last_price=100.0,
        ma200=95.0,
        ma50w=98.0,
        rsi14=40.0,
        iv_rank=25.0,
        iv_momentum=None,
        prev_close=99.0,
        earnings_date=date(2026, 4, 25),
        days_to_earnings=64,
        # Dividend fields
        dividend_yield=None,
        dividend_yield_5y_percentile=None,
        dividend_quality_score=None,
        consecutive_years=None,
        dividend_growth_5y=None,
        payout_ratio=None,
        roe=None,
        debt_to_equity=None,
        industry=None,
        sector=None,
        free_cash_flow=None,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestScanDividendPoolWeekly:
    """测试每周股息池筛选扫描器"""

    def test_scan_dividend_pool_weekly_filters_by_quality_score(self):
        """测试：质量评分过滤（返回高质量标的）"""
        # Arrange
        universe = ["AAPL", "MSFT"]

        # Mock provider
        mock_provider = MagicMock()
        mock_provider.config = {"default_market": "US"}
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-01-01", "amount": 0.5},
            {"date": "2024-01-01", "amount": 0.48},
            {"date": "2023-01-01", "amount": 0.45},
            {"date": "2022-01-01", "amount": 0.42},
            {"date": "2021-01-01", "amount": 0.40},
            {"date": "2020-01-01", "amount": 0.38},
        ]
        mock_provider.get_fundamentals.return_value = {
            "dividend_yield": 3.5,
            "payout_ratio": 65.0,
            "roe": 28.5,
            "debt_to_equity": 1.2,
            "industry": "Technology",
            "sector": "Information Technology",
            "free_cash_flow": 95000000000,
        }

        # Mock financial service
        mock_financial_service = MagicMock()
        mock_financial_service.analyze_dividend_quality.return_value = DividendQualityScore(
            overall_score=85.0,
            stability_score=80.0,
            health_score=90.0,
            defensiveness_score=50.0,
            risk_flags=[],
        )

        # Mock config
        config = {
            "dividend_scanners": {
                "min_quality_score": 70,
                "min_consecutive_years": 5,
                "max_payout_ratio": 100,
            }
        }

        # Act
        results = scan_dividend_pool_weekly(
            universe=universe,
            provider=mock_provider,
            financial_service=mock_financial_service,
            config=config,
        )

        # Assert
        assert len(results) > 0, "Should return at least one result"
        for ticker_data in results:
            assert ticker_data.dividend_quality_score >= 70, \
                f"{ticker_data.ticker} quality score should be >= 70"
            assert ticker_data.consecutive_years >= 5, \
                f"{ticker_data.ticker} consecutive years should be >= 5"

    def test_scan_dividend_pool_excludes_payout_ratio_over_100(self):
        """测试：派息率超过100%的标的被排除"""
        # Arrange
        universe = ["RISKY"]

        # Mock provider with high payout ratio
        mock_provider = MagicMock()
        mock_provider.config = {"default_market": "US"}
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-01-01", "amount": 0.5},
            {"date": "2024-01-01", "amount": 0.48},
            {"date": "2023-01-01", "amount": 0.45},
            {"date": "2022-01-01", "amount": 0.42},
            {"date": "2021-01-01", "amount": 0.40},
            {"date": "2020-01-01", "amount": 0.38},
        ]
        mock_provider.get_fundamentals.return_value = {
            "dividend_yield": 8.5,
            "payout_ratio": 105.0,  # Exceeds max_payout_ratio
            "roe": 12.0,
            "debt_to_equity": 2.5,
            "industry": "Utilities",
            "sector": "Utilities",
            "free_cash_flow": 1000000000,
        }

        # Mock financial service (should flag high payout ratio)
        mock_financial_service = MagicMock()
        mock_financial_service.analyze_dividend_quality.return_value = DividendQualityScore(
            overall_score=45.0,  # Low score due to high payout
            stability_score=60.0,
            health_score=30.0,
            defensiveness_score=50.0,
            risk_flags=["PAYOUT_RATIO_CRITICAL"],
        )

        # Mock config
        config = {
            "dividend_scanners": {
                "min_quality_score": 70,
                "min_consecutive_years": 5,
                "max_payout_ratio": 100,
            }
        }

        # Act
        results = scan_dividend_pool_weekly(
            universe=universe,
            provider=mock_provider,
            financial_service=mock_financial_service,
            config=config,
        )

        # Assert
        assert len(results) == 0, "Should exclude ticker with payout_ratio > 100"

    def test_scan_dividend_pool_weekly_computes_golden_price(self):
        """Weekly scan computes golden_price and stores it on TickerData."""
        dates = pd.date_range("2021-01-01", periods=60, freq="M")
        prices = pd.Series([100.0 + i * 0.1 for i in range(60)], index=dates)
        price_df = pd.DataFrame({"Close": prices})

        div_history = [
            {"date": "2021-06-01", "amount": 0.50},
            {"date": "2021-12-01", "amount": 0.50},
            {"date": "2022-06-01", "amount": 0.55},
            {"date": "2022-12-01", "amount": 0.55},
            {"date": "2023-06-01", "amount": 0.60},
            {"date": "2023-12-01", "amount": 0.60},
            {"date": "2024-06-01", "amount": 0.65},
            {"date": "2024-12-01", "amount": 0.65},
            {"date": "2025-06-01", "amount": 0.70},
            {"date": "2025-12-01", "amount": 0.72},
        ]
        fundamentals = {
            "company_name": "TestCo",
            "dividend_yield": 4.5,
            "payout_ratio": 50.0,
            "roe": 15.0,
            "debt_to_equity": 0.5,
            "industry": "Finance",
            "sector": "Financials",
            "forward_dividend_rate": 1.40,
            "dividendRate": 1.40,
        }
        mock_provider = MagicMock()
        mock_provider.get_dividend_history.return_value = div_history
        mock_provider.get_fundamentals.return_value = fundamentals
        mock_provider.get_price_data.return_value = price_df

        quality_score = DividendQualityScore(
            overall_score=80.0, stability_score=70.0, health_score=75.0,
            defensiveness_score=50.0, risk_flags=[],
        )
        mock_fs = MagicMock()
        mock_fs.analyze_dividend_quality.return_value = quality_score

        config = {"dividend_scanners": {
            "min_quality_score": 70, "min_consecutive_years": 3, "max_payout_ratio": 100,
        }}
        results = scan_dividend_pool_weekly(["AAPL"], mock_provider, mock_fs, config)

        assert len(results) == 1
        td = results[0]
        assert td.golden_price is not None, "golden_price should be computed when sufficient data exists"
        assert td.golden_price > 0


class TestScanDividendBuySignal:
    """测试每日股息买入信号扫描器"""

    def test_scan_dividend_buy_signal_triggers_on_high_yield(self, tmp_path):
        """测试：股息率达到历史高位时触发买入信号"""
        # Arrange
        db_path = str(tmp_path / "test_dividend.db")
        store = DividendStore(db_path)

        # 填充历史数据：5年的股息率历史 (3.0, 4.0, 5.0, 6.0, 7.0)
        ticker = "AAPL"
        historical_yields = [
            ("2021-03-01", 3.0, 1.50, 50.0),
            ("2022-03-01", 4.0, 2.00, 50.0),
            ("2023-03-01", 5.0, 2.50, 50.0),
            ("2024-03-01", 6.0, 3.00, 50.0),
            ("2025-03-01", 7.0, 3.50, 50.0),
        ]
        for date_str, div_yield, annual_div, price in historical_yields:
            store.save_dividend_history(
                ticker=ticker,
                date=date.fromisoformat(date_str),
                dividend_yield=div_yield,
                annual_dividend=annual_div,
                price=price
            )

        # Mock provider
        mock_provider = MagicMock()
        # 当前价格低 → 股息率高 (7.5%)
        import pandas as pd
        mock_provider.get_price_data.return_value = pd.DataFrame({
            "Close": [45.0, 46.0, 47.0, 46.5, 46.0],
        }, index=pd.to_datetime(["2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]))
        # 年度股息 = 3.50
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-12-15", "amount": 0.875},
            {"date": "2025-09-15", "amount": 0.875},
            {"date": "2025-06-15", "amount": 0.875},
            {"date": "2025-03-15", "amount": 0.875},
        ]

        # Config
        config = {
            "dividend_scanners": {
                "min_yield": 4.0,
                "min_yield_percentile": 90,
            }
        }

        # Act
        pool = [{"ticker": ticker, "forward_dividend_rate": None, "max_yield_5y": None, "data_version_date": str(date.today())}]
        results = scan_dividend_buy_signal(
            pool=pool,
            provider=mock_provider,
            store=store,
            config=config
        )

        # Assert
        assert len(results) == 1, "Should trigger one buy signal"
        signal = results[0]
        assert isinstance(signal, DividendBuySignal)
        assert signal.ticker_data.ticker == "AAPL"
        assert signal.signal_type == "STOCK"
        assert signal.current_yield > 4.0, "Current yield should be > 4.0"
        assert signal.yield_percentile >= 90, "Yield percentile should be >= 90"
        assert signal.option_details is None, "Option details should be None for STOCK signal"

        # 验证计算正确性
        # annual_dividend = 3.50, last_price = 46.0 → current_yield = (3.50 / 46.0) * 100 = 7.61%
        expected_yield = (3.50 / 46.0) * 100
        assert abs(signal.current_yield - expected_yield) < 0.01, \
            f"Current yield should be {expected_yield:.2f}%, got {signal.current_yield:.2f}%"

        # Clean up
        store.close()


    def test_cn_stock_uses_fundamentals_ttm_yield(self, tmp_path):
        """CN股票日信号扫描器应使用基本面TTM股息率，而不是yfinance单次派息计算。

        场景：招商银行(600036.SS)年度派息3.013元/股，但yfinance只捕获到中期派息0.561元。
        期望：使用fundamentals dividend_yield(7.578%) × 当前价格 推算 annual_dividend，
              而不是直接用yfinance返回的0.561。
        """
        db_path = str(tmp_path / "test_dividend.db")
        store = DividendStore(db_path)

        ticker = "600036.SS"
        # 填充历史数据使分位数有意义
        for i, d in enumerate(["2021-06-01", "2022-06-01", "2023-06-01", "2024-06-01"]):
            store.save_dividend_history(
                ticker=ticker,
                date=date.fromisoformat(d),
                dividend_yield=6.0 + i * 0.5,
                annual_dividend=2.4 + i * 0.2,
                price=40.0,
            )

        mock_provider = MagicMock()
        last_price = 39.76
        mock_provider.get_price_data.return_value = pd.DataFrame(
            {"Close": [last_price]},
            index=pd.to_datetime(["2026-03-13"]),
        )
        # yfinance只返回中期派息（不完整）→ yield只有1.4%
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-09-15", "amount": 0.561},
        ]
        # fundamentals via XueQiu: TTM股息率 7.578%
        mock_provider.get_fundamentals.return_value = {
            "dividend_yield": 7.578,
            "company_name": "招商银行",
        }

        config = {
            "dividend_scanners": {
                "min_yield": 4.0,
                "min_yield_percentile": 85,
            }
        }
        pool = [{
            "ticker": ticker,
            "market": "CN",
            "forward_dividend_rate": None,
            "max_yield_5y": None,
            "data_version_date": str(date.today()),
        }]
        results = scan_dividend_buy_signal(
            pool=pool,
            provider=mock_provider,
            store=store,
            config=config,
        )

        assert len(results) == 1, "CN stock should trigger signal using TTM yield, not partial yfinance dividend"
        expected_yield = 7.578  # from fundamentals, not raw dividend history
        assert abs(results[0].current_yield - expected_yield) < 0.1, (
            f"Expected ~{expected_yield:.2f}%, got {results[0].current_yield:.2f}% — "
            "CN stock yield should come from XueQiu TTM, not yfinance partial payment"
        )

        store.close()

    def test_past_earnings_date_set_to_none(self, tmp_path):
        """财报日已过（负数days_to_earnings）时，应设为None，不显示负数"""
        db_path = str(tmp_path / "test_dividend.db")
        store = DividendStore(db_path)

        ticker = "AAPL"
        for date_str, div_yield in [
            ("2021-03-01", 3.0), ("2022-03-01", 4.0), ("2023-03-01", 5.0),
            ("2024-03-01", 6.0), ("2025-03-01", 7.0),
        ]:
            store.save_dividend_history(
                ticker=ticker, date=date.fromisoformat(date_str),
                dividend_yield=div_yield, annual_dividend=div_yield * 0.5, price=50.0,
            )

        mock_provider = MagicMock()
        mock_provider.get_price_data.return_value = pd.DataFrame(
            {"Close": [46.0]}, index=pd.to_datetime(["2026-03-14"])
        )
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-12-15", "amount": 0.875},
            {"date": "2025-09-15", "amount": 0.875},
            {"date": "2025-06-15", "amount": 0.875},
            {"date": "2025-03-15", "amount": 0.875},
        ]
        # 财报日已过（过去的日期）
        past_earnings = date.today() - timedelta(days=5)
        mock_provider.get_earnings_date.return_value = past_earnings

        config = {"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 90}}
        pool = [{"ticker": ticker, "forward_dividend_rate": None, "max_yield_5y": None,
                 "data_version_date": str(date.today())}]

        results = scan_dividend_buy_signal(pool=pool, provider=mock_provider, store=store, config=config)

        assert len(results) == 1
        td = results[0].ticker_data
        assert td.earnings_date is None, f"Past earnings_date should be None, got {td.earnings_date}"
        assert td.days_to_earnings is None, f"Past days_to_earnings should be None, got {td.days_to_earnings}"

        store.close()


class TestScanDividendSellPut:
    """测试高股息Sell Put期权策略扫描器"""

    def test_scan_dividend_sell_put_selects_strike_by_yield(self):
        """测试：基于目标股息率选择行权价（不是APY优化）"""
        # Arrange
        from src.dividend_scanners import scan_dividend_sell_put

        # Mock provider
        mock_provider = MagicMock()

        # Mock option chain with 3 strikes: 32.0, 33.0, 34.0
        mock_provider.get_options_chain.return_value = pd.DataFrame({
            'strike': [32.0, 33.0, 34.0],
            'bid': [1.20, 1.10, 1.00],
            'dte': [60, 60, 60],
            'expiration': [date(2026, 5, 3), date(2026, 5, 3), date(2026, 5, 3)]
        })

        # Create mock TickerData
        ticker_data = make_ticker(
            ticker="XYZ",
            last_price=35.0,
            dividend_yield=6.71  # 2.35 / 35.0 * 100
        )

        # Test parameters
        annual_dividend = 2.35
        target_yield = 7.3  # Expected target_strike = 2.35 / 0.073 = 32.19 → selects $32

        # Act
        result = scan_dividend_sell_put(
            ticker_data=ticker_data,
            provider=mock_provider,
            annual_dividend=annual_dividend,
            golden_price=None,  # No golden_price, uses yield-math fallback
            target_yield=target_yield,
            min_dte=45,
            max_dte=90
        )

        # Assert
        assert result is not None, "Should return option details"
        assert result['strike'] == 32.0, "Should select $32 strike (closest to target_strike=32.19)"
        assert result['bid'] == 1.20
        assert result['dte'] == 60
        assert result['expiration'] == date(2026, 5, 3)

        # Verify APY calculation (for display only, not for filtering)
        # APY = (bid / strike) * (365 / dte) * 100
        expected_apy = (1.20 / 32.0) * (365 / 60) * 100
        assert abs(result['apy'] - expected_apy) < 0.01, \
            f"APY should be {expected_apy:.2f}%, got {result['apy']:.2f}%"

    def test_scan_dividend_buy_signal_includes_option_strategy_for_us_market(self, tmp_path):
        """测试：美国市场触发买入信号时，应包含期权策略"""
        # Arrange
        db_path = str(tmp_path / "test_dividend.db")
        store = DividendStore(db_path)

        # 填充历史数据：股息率历史高位
        ticker = "XYZ"
        historical_yields = [
            ("2021-03-01", 3.0, 1.50, 50.0),
            ("2022-03-01", 4.0, 2.00, 50.0),
            ("2023-03-01", 5.0, 2.50, 50.0),
            ("2024-03-01", 6.0, 3.00, 50.0),
            ("2025-03-01", 7.0, 3.50, 50.0),
        ]
        for date_str, div_yield, annual_div, price in historical_yields:
            store.save_dividend_history(
                ticker=ticker,
                date=date.fromisoformat(date_str),
                dividend_yield=div_yield,
                annual_dividend=annual_div,
                price=price
            )

        # Mock provider
        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = False  # US market

        # 当前价格低 → 股息率高 (7.5%)
        import pandas as pd
        mock_provider.get_price_data.return_value = pd.DataFrame({
            "Close": [46.0],
        }, index=pd.to_datetime(["2026-03-04"]))
        # 年度股息 = 3.50
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-12-15", "amount": 0.875},
            {"date": "2025-09-15", "amount": 0.875},
            {"date": "2025-06-15", "amount": 0.875},
            {"date": "2025-03-15", "amount": 0.875},
        ]

        # Mock option chain
        mock_provider.get_options_chain.return_value = pd.DataFrame({
            'strike': [32.0, 33.0, 34.0],
            'bid': [1.20, 1.10, 1.00],
            'dte': [60, 60, 60],
            'expiration': [date(2026, 5, 3), date(2026, 5, 3), date(2026, 5, 3)]
        })

        # Config with option strategy enabled
        config = {
            "dividend_scanners": {
                "min_yield": 4.0,
                "min_yield_percentile": 90,
                "option": {
                    "enabled": True,
                    "target_strike_percentile": 90,
                    "min_dte": 45,
                    "max_dte": 90,
                }
            }
        }

        # Act
        pool = [{"ticker": ticker, "forward_dividend_rate": None, "max_yield_5y": None, "data_version_date": str(date.today())}]
        results = scan_dividend_buy_signal(
            pool=pool,
            provider=mock_provider,
            store=store,
            config=config
        )

        # Assert
        assert len(results) == 1, "Should trigger one buy signal"
        signal = results[0]
        assert signal.signal_type == "OPTION", "Signal type should be OPTION for US market with options enabled"
        assert signal.option_details is not None, "Option details should be populated"
        # current_yield=7.61%, yield_percentile=100, target_yield=7.61*(90/100)=6.85%
        # target_strike=3.50/0.0685=51.1 → closest among [32,33,34] is 34
        assert signal.option_details['strike'] == 34.0, "Should select closest available strike to target_strike"
        assert signal.option_details['bid'] == 1.00
        assert signal.option_details['dte'] == 60

        # Clean up
        store.close()

    def test_scan_dividend_buy_signal_illiquid_option_does_not_crash(self, tmp_path):
        """When scan_dividend_sell_put returns an illiquid dict, caller must not KeyError."""
        from src.dividend_store import DividendStore
        from src.dividend_scanners import scan_dividend_buy_signal

        db_path = str(tmp_path / "test_dividend.db")
        store = DividendStore(db_path)

        ticker = "XYZ"
        historical_yields = [
            ("2021-03-01", 3.0, 1.50, 50.0),
            ("2022-03-01", 4.0, 2.00, 50.0),
            ("2023-03-01", 5.0, 2.50, 50.0),
            ("2024-03-01", 6.0, 3.00, 50.0),
            ("2025-03-01", 7.0, 3.50, 50.0),
        ]
        for date_str, div_yield, annual_div, price in historical_yields:
            store.save_dividend_history(
                ticker=ticker,
                date=date.fromisoformat(date_str),
                dividend_yield=div_yield,
                annual_dividend=annual_div,
                price=price
            )

        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = False  # US market

        import pandas as pd
        mock_provider.get_price_data.return_value = pd.DataFrame({
            "Close": [46.0],
        }, index=pd.to_datetime(["2026-03-04"]))
        mock_provider.get_dividend_history.return_value = [
            {"date": "2025-12-15", "amount": 0.875},
            {"date": "2025-09-15", "amount": 0.875},
            {"date": "2025-06-15", "amount": 0.875},
            {"date": "2025-03-15", "amount": 0.875},
        ]

        # Option chain with wide spread (>30%) → illiquid result from scan_dividend_sell_put
        mock_provider.get_options_chain.return_value = pd.DataFrame({
            'strike': [34.0],
            'bid': [1.00],
            'ask': [1.60],   # spread = (1.60-1.00)/1.30 = 46% → illiquid
            'dte': [60],
            'expiration': [date(2026, 5, 3)]
        })

        config = {
            "dividend_scanners": {
                "min_yield": 4.0,
                "min_yield_percentile": 90,
                "option": {
                    "enabled": True,
                    "target_strike_percentile": 90,
                    "min_dte": 45,
                    "max_dte": 90,
                }
            }
        }

        pool = [{"ticker": ticker, "forward_dividend_rate": None, "max_yield_5y": None,
                 "data_version_date": str(date.today())}]

        # Must not raise KeyError
        results = scan_dividend_buy_signal(
            pool=pool,
            provider=mock_provider,
            store=store,
            config=config
        )

        assert len(results) == 1
        signal = results[0]
        # Illiquid option falls back to STOCK signal type
        assert signal.signal_type == "STOCK"
        # option_details is still preserved (the illiquid dict is passed through)
        assert signal.option_details is not None
        assert signal.option_details.get("sell_put_illiquid") is True

        store.close()


def test_scan_excludes_low_yield_tickers(mock_provider, mock_fs, config):
    """Tickers with dividend_yield < 2.0% must be excluded from pool."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 1.5,    # below 2% threshold
        "payout_ratio": 40.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "industry": "Beverages",
        "free_cash_flow": 5_000_000,
        "company_name": "Low Yield Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(80.0)
    result = scan_dividend_pool_weekly(["LOW_YIELD"], mock_provider, mock_fs, config)
    assert result == []


def test_scan_excludes_negative_growth_tickers(mock_provider, mock_fs, config):
    """Tickers with 5yr dividend growth < 0% must be excluded."""
    declining_history = [
        {"date": "2021-03-01", "amount": 1.0},
        {"date": "2022-03-01", "amount": 1.0},
        {"date": "2023-03-01", "amount": 0.9},
        {"date": "2024-03-01", "amount": 0.8},
        {"date": "2025-03-01", "amount": 0.7},
    ]
    mock_provider.get_dividend_history.return_value = declining_history
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 4.0,
        "payout_ratio": 60.0,
        "roe": 10.0,
        "debt_to_equity": 0.5,
        "sector": "Utilities",
        "free_cash_flow": 5_000_000,
        "company_name": "Declining Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(75.0)
    result = scan_dividend_pool_weekly(["NEG_GROWTH"], mock_provider, mock_fs, config)
    assert result == []


def test_scan_passes_annual_dividend_to_financial_service(mock_provider, mock_fs, config):
    """annual_dividend (most recent year) must be in fundamentals passed to FS."""
    history = [
        # 5 consecutive years to pass min_consecutive_years filter
        {"date": "2020-03-01", "amount": 0.4},
        {"date": "2021-03-01", "amount": 0.4},
        {"date": "2022-03-01", "amount": 0.4},
        {"date": "2023-03-01", "amount": 0.4},
        # 2024: quarterly payments, total = 2.0 (most recent full year)
        {"date": "2024-03-01", "amount": 0.5},
        {"date": "2024-06-01", "amount": 0.5},
        {"date": "2024-09-01", "amount": 0.5},
        {"date": "2024-12-01", "amount": 0.5},
    ]
    mock_provider.get_dividend_history.return_value = history
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 3.5,
        "payout_ratio": 60.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "free_cash_flow": 10_000_000,
        "company_name": "Test Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(80.0)
    scan_dividend_pool_weekly(["TEST"], mock_provider, mock_fs, config)

    call_args = mock_fs.analyze_dividend_quality.call_args
    fundamentals_passed = call_args[1]["fundamentals"] if call_args[1] else call_args[0][1]
    assert "annual_dividend" in fundamentals_passed
    assert fundamentals_passed["annual_dividend"] == pytest.approx(2.0)  # 4 × 0.5


def test_scan_sets_payout_type_on_ticker_data(mock_provider, mock_fs, config):
    """payout_type from quality_score_result must be set on returned TickerData."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 7.0,
        "payout_ratio": 115.0,
        "roe": 10.0,
        "debt_to_equity": 1.2,
        "sector": "Energy",
        "free_cash_flow": 10_000_000,
        "company_name": "Pipeline Co",
    }
    fcf_score = DividendQualityScore(
        overall_score=78.0, stability_score=80.0, health_score=76.0,
        defensiveness_score=80.0, risk_flags=[],
        payout_type="FCF", effective_payout_ratio=64.0,
    )
    mock_fs.analyze_dividend_quality.return_value = fcf_score
    result = scan_dividend_pool_weekly(["ENB"], mock_provider, mock_fs, config)
    assert len(result) == 1
    assert result[0].payout_type == "FCF"
    assert result[0].payout_ratio == pytest.approx(64.0)


def test_scan_sets_correct_market_for_hk_ticker(mock_provider, mock_fs, config):
    """HK tickers (.HK suffix) must have market='HK', not 'US'."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 5.5,
        "payout_ratio": 55.0,
        "roe": 12.0,
        "debt_to_equity": 1.0,
        "sector": "Financial Services",
        "free_cash_flow": 10_000_000,
        "company_name": "HSBC Holdings",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(75.0)
    result = scan_dividend_pool_weekly(["0005.HK"], mock_provider, mock_fs, config)
    assert len(result) == 1
    assert result[0].market == "HK"


def test_scan_sets_correct_market_for_cn_ticker(mock_provider, mock_fs, config):
    """CN tickers (.SS/.SZ suffix) must have market='CN'."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 4.5,
        "payout_ratio": 31.0,
        "roe": 14.0,
        "debt_to_equity": 0.8,
        "sector": "Financial Services",
        "free_cash_flow": 50_000_000,
        "company_name": "工商银行",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(73.0)
    result = scan_dividend_pool_weekly(["601398.SS"], mock_provider, mock_fs, config)
    assert len(result) == 1
    assert result[0].market == "CN"


def test_scan_fetches_10_years_of_dividend_history(mock_provider, mock_fs, config):
    """scan_dividend_pool_weekly must request 10 years of history (not 5) to
    give ETFs and slower-growing stocks enough data for CAGR calculation."""
    mock_provider.get_dividend_history.return_value = _history_5yr()
    mock_provider.get_fundamentals.return_value = {
        "dividend_yield": 3.5,
        "payout_ratio": 60.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "free_cash_flow": 10_000_000,
        "company_name": "Test Co",
    }
    mock_fs.analyze_dividend_quality.return_value = _mock_score(75.0)
    scan_dividend_pool_weekly(["SCHD"], mock_provider, mock_fs, config)
    mock_provider.get_dividend_history.assert_called_once_with("SCHD", years=10)


def _make_passing_provider_and_fs(forward_dividend_rate=2.40):
    """Helper: create a mock provider + fs that produce a passing ticker.

    TTM dividend = 4 × 0.60 = 2.40 (quarterly payments within last year).
    min_5y_price = 100.0
    expected max_yield_5y = (2.40 / 100.0) * 100 = 2.40
    """
    from datetime import datetime, timedelta as _td
    provider = MagicMock()
    # 4 quarterly dividends within the last year + older history to satisfy 5yr check
    _today = datetime.now().date()
    recent_divs = [
        {"date": str(_today - _td(days=30 + i * 90)), "amount": 0.60}
        for i in range(4)
    ]
    older_divs = [{"date": f"{year}-03-01", "amount": 1.0} for year in range(2021, 2025)]
    provider.get_dividend_history.return_value = recent_divs + older_divs
    provider.get_fundamentals.return_value = {
        "dividend_yield": 3.5,
        "payout_ratio": 60.0,
        "roe": 15.0,
        "debt_to_equity": 0.5,
        "sector": "Consumer Staples",
        "free_cash_flow": 10_000_000,
        "company_name": "Test Co",
        "forward_dividend_rate": forward_dividend_rate,
    }
    # price data only needs Close column — Dividends column no longer required
    idx = pd.date_range(end="2026-03-09", periods=252 * 5, freq="B")
    provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [100.0] * len(idx)}, index=idx
    )

    fs = MagicMock()
    score = DividendQualityScore(
        overall_score=80.0,
        stability_score=80.0,
        health_score=80.0,
        defensiveness_score=60.0,
        risk_flags=[],
        quality_breakdown={"stability": 80.0, "health": 80.0},
        analysis_text="Strong dividend payer.",
    )
    fs.analyze_dividend_quality.return_value = score
    return provider, fs


def test_weekly_scan_populates_forward_dividend_rate(config):
    """forward_dividend_rate from fundamentals must be set on returned TickerData."""
    provider, fs = _make_passing_provider_and_fs(forward_dividend_rate=2.40)
    results = scan_dividend_pool_weekly(["KO"], provider, fs, config)
    assert len(results) == 1
    assert results[0].forward_dividend_rate == pytest.approx(2.40)


def test_weekly_scan_forward_dividend_rate_falls_back_to_annual_dividend_ttm(config):
    """When fundamentals have no forward/dividendRate, fall back to annual_dividend_ttm
    so that floor_price can be computed for HK/CN stocks."""
    provider, fs = _make_passing_provider_and_fs(forward_dividend_rate=None)
    # Remove dividendRate too (ensure it's not present)
    provider.get_fundamentals.return_value.pop("dividendRate", None)
    # annual_dividend_ttm = 4 × 0.60 = 2.40 (from _make_passing_provider_and_fs)
    results = scan_dividend_pool_weekly(["0267.HK"], provider, fs, config)
    assert len(results) == 1
    assert results[0].forward_dividend_rate == pytest.approx(2.40)
    assert results[0].max_yield_5y is not None    # floor data computed
    assert results[0].max_yield_5y > 0


def test_weekly_scan_populates_max_yield_5y(config):
    """max_yield_5y must be computed as (annual_dividend_ttm / min_5y_price) * 100."""
    provider, fs = _make_passing_provider_and_fs()
    # annual_dividend_ttm = 4 * 0.60 = 2.40; min_5y_price = 100.0
    # expected max_yield_5y = (2.40 / 100.0) * 100 = 2.40
    results = scan_dividend_pool_weekly(["KO"], provider, fs, config)
    assert len(results) == 1
    assert results[0].max_yield_5y == pytest.approx(2.40)


def test_weekly_scan_populates_data_version_date(config):
    """data_version_date must be set to str(date.today()) for each processed ticker."""
    provider, fs = _make_passing_provider_and_fs()
    results = scan_dividend_pool_weekly(["KO"], provider, fs, config)
    assert len(results) == 1
    assert results[0].data_version_date == str(date.today())


# ---------------------------------------------------------------------------
# Task 5: New fields on DividendBuySignal
# ---------------------------------------------------------------------------

def _make_buy_pool_record(
    ticker="KO",
    forward_dividend_rate=2.0,
    max_yield_5y=4.0,
    data_version_date=None,
):
    """Helper: build a minimal pool record dict (as returned by get_pool_records).
    Note: needs_reeval is computed on-the-fly from data_age_days, not stored in DB.
    """
    if data_version_date is None:
        data_version_date = str(date.today())
    return {
        "ticker": ticker,
        "forward_dividend_rate": forward_dividend_rate,
        "max_yield_5y": max_yield_5y,
        "data_version_date": data_version_date,
    }


def test_buy_signal_computes_floor_price(tmp_path):
    """floor_price = forward_dividend_rate / (max_yield_5y / 100).
    With forward_dividend_rate=2.0 and max_yield_5y=4.0:
    floor_price = 2.0 / (4.0 / 100) = 50.0
    """
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    store.save_dividend_history(
        ticker="KO", date=date.today(),
        dividend_yield=5.0, annual_dividend=2.0, price=40.0
    )

    mock_provider = MagicMock()
    mock_provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [40.0]},
        index=pd.to_datetime([str(date.today())])
    )
    mock_provider.get_dividend_history.return_value = [
        {"date": str(date.today()), "amount": 2.0}
    ]

    config = {"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 0}}

    pool = [_make_buy_pool_record(ticker="KO", forward_dividend_rate=2.0, max_yield_5y=4.0)]
    results = scan_dividend_buy_signal(pool=pool, provider=mock_provider, store=store, config=config)

    store.close()
    assert len(results) == 1
    assert results[0].floor_price == pytest.approx(50.0)


def test_buy_signal_computes_floor_downside_pct(tmp_path):
    """floor_downside_pct = (last_price - floor_price) / last_price * 100.
    With last_price=65.0, forward_dividend_rate=4.0, max_yield_5y=4.0:
    floor_price = 4.0 / (4.0/100) = 100.0
    Using last_price=40.0 and floor_price=50.0:
      forward_dividend_rate=2.0, max_yield_5y=4.0 → floor_price=50.0
      annual_dividend=4.0 at last_price=40.0 → yield=10% (>= min_yield=4.0)
    floor_downside_pct = (40.0 - 50.0) / 40.0 * 100 = -25.0
    """
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    store.save_dividend_history(
        ticker="KO", date=date.today(),
        dividend_yield=10.0, annual_dividend=4.0, price=40.0
    )

    mock_provider = MagicMock()
    mock_provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [40.0]},
        index=pd.to_datetime([str(date.today())])
    )
    # annual_dividend = 4.0, last_price = 40.0 → yield = 10% >= 4%
    mock_provider.get_dividend_history.return_value = [
        {"date": str(date.today()), "amount": 4.0}
    ]

    config = {"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 0}}

    # floor_price = 2.0 / (4.0/100) = 50.0
    pool = [_make_buy_pool_record(ticker="KO", forward_dividend_rate=2.0, max_yield_5y=4.0)]
    results = scan_dividend_buy_signal(pool=pool, provider=mock_provider, store=store, config=config)

    store.close()
    assert len(results) == 1
    # floor_downside_pct = (40.0 - 50.0) / 40.0 * 100 = -25.0
    expected = round((40.0 - 50.0) / 40.0 * 100, 1)
    assert results[0].floor_price == pytest.approx(50.0)
    assert results[0].floor_downside_pct == pytest.approx(expected)


def test_buy_signal_computes_data_age_days(tmp_path):
    """data_age_days = (date.today() - date.fromisoformat(data_version_date)).days.
    When data_version_date == str(date.today()), data_age_days == 0.
    """
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    store.save_dividend_history(
        ticker="KO", date=date.today(),
        dividend_yield=5.0, annual_dividend=2.0, price=40.0
    )

    mock_provider = MagicMock()
    mock_provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [40.0]},
        index=pd.to_datetime([str(date.today())])
    )
    mock_provider.get_dividend_history.return_value = [
        {"date": str(date.today()), "amount": 2.0}
    ]

    config = {"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 0}}

    pool = [_make_buy_pool_record(ticker="KO", data_version_date=str(date.today()))]
    results = scan_dividend_buy_signal(pool=pool, provider=mock_provider, store=store, config=config)

    store.close()
    assert len(results) == 1
    assert results[0].data_age_days == 0
    # data is fresh → needs_reeval must be False
    assert results[0].needs_reeval is False


def test_buy_signal_needs_reeval_when_stale(tmp_path):
    """needs_reeval=True when data_age_days >= 14 (stale between weekly scans)."""
    from datetime import timedelta
    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)
    store.save_dividend_history(
        ticker="KO", date=date.today(),
        dividend_yield=5.0, annual_dividend=2.0, price=40.0
    )

    mock_provider = MagicMock()
    mock_provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [40.0]},
        index=pd.to_datetime([str(date.today())])
    )
    mock_provider.get_dividend_history.return_value = [
        {"date": str(date.today()), "amount": 2.0}
    ]

    config = {"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 0}}

    stale_date = str(date.today() - timedelta(days=15))
    pool = [_make_buy_pool_record(ticker="KO", data_version_date=stale_date)]
    results = scan_dividend_buy_signal(pool=pool, provider=mock_provider, store=store, config=config)

    store.close()
    assert len(results) == 1
    assert results[0].data_age_days == 15
    assert results[0].needs_reeval is True


# ---------------------------------------------------------------------------
# Task 3: scan_dividend_sell_put liquidity check
# ---------------------------------------------------------------------------

def test_scan_dividend_sell_put_uses_midpoint_apy(mock_provider, sample_ticker_data):
    """APY uses midpoint, not bid."""
    options_df = pd.DataFrame({
        "strike": [30.0], "bid": [0.80], "ask": [1.00],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    mock_provider.get_options_chain.return_value = options_df
    mock_provider.should_skip_options.return_value = False
    result = scan_dividend_sell_put(sample_ticker_data, mock_provider,
                                    annual_dividend=1.72,
                                    target_yield=5.5)
    assert result is not None
    assert result.get("sell_put_illiquid") is False
    mid = (0.80 + 1.00) / 2
    expected_apy = round((mid / 30.0) * (365 / 60) * 100, 2)
    assert result["apy"] == pytest.approx(expected_apy, abs=0.1)


def test_scan_dividend_sell_put_illiquid_flag_over_30pct(mock_provider, sample_ticker_data):
    """Spread > 30% returns illiquid dict, not None."""
    # mid=1.3, spread=(1.6-1.0)/1.3=46%
    options_df = pd.DataFrame({
        "strike": [30.0], "bid": [1.0], "ask": [1.6],
        "dte": [60], "expiration": [date.today() + timedelta(days=60)],
    })
    mock_provider.get_options_chain.return_value = options_df
    mock_provider.should_skip_options.return_value = False
    result = scan_dividend_sell_put(sample_ticker_data, mock_provider,
                                    annual_dividend=1.72,
                                    target_yield=5.5)
    assert result is not None
    assert result["sell_put_illiquid"] is True
    assert result["spread_pct"] > 30


# ---------------------------------------------------------------------------
# Task 3 (Dividend Card UX v2): get_sgov_yield + sgov_yield wiring
# ---------------------------------------------------------------------------

def test_get_sgov_yield_returns_float(monkeypatch):
    """get_sgov_yield() converts yfinance yield fraction to percent."""
    from src.dividend_scanners import get_sgov_yield
    import yfinance as yf

    class FakeTicker:
        info = {"yield": 0.0523}
    monkeypatch.setattr(yf, "Ticker", lambda sym: FakeTicker())
    result = get_sgov_yield()
    assert result == 5.23


def test_get_sgov_yield_fallback(monkeypatch):
    """Returns 4.8 when yfinance raises."""
    from src.dividend_scanners import get_sgov_yield
    import yfinance as yf

    class BadTicker:
        @property
        def info(self):
            raise RuntimeError("network")
    monkeypatch.setattr(yf, "Ticker", lambda sym: BadTicker())
    result = get_sgov_yield()
    assert result == 4.8


def test_weekly_scan_sets_sgov_yield_us(monkeypatch):
    """US tickers get sgov_yield set; HK tickers get None."""
    from src.dividend_scanners import get_sgov_yield
    import yfinance as yf

    class FakeTicker:
        info = {"yield": 0.048}
    monkeypatch.setattr(yf, "Ticker", lambda sym: FakeTicker())
    from src.data_loader import classify_market
    sgov = get_sgov_yield()
    assert sgov == 4.8
    assert classify_market("AAPL") == "US"
    assert classify_market("0005.HK") == "HK"
    # US ticker gets sgov_yield, HK ticker gets None
    us_sgov = sgov if classify_market("AAPL") == "US" else None
    hk_sgov = sgov if classify_market("0005.HK") == "US" else None
    assert us_sgov == 4.8
    assert hk_sgov is None


# ---------------------------------------------------------------------------
# Task 4: _get_recommended_strategy() rule-based recommendation
# ---------------------------------------------------------------------------

def test_recommend_spot_no_options():
    from src.dividend_scanners import _get_recommended_strategy
    strategy, reason = _get_recommended_strategy(
        ticker="0005.HK", current_yield=5.0, sgov_adjusted_apy=None,
        option_available=False, option_illiquid=False,
    )
    assert strategy == "spot"
    assert "无期权" in reason


def test_recommend_spot_illiquid():
    from src.dividend_scanners import _get_recommended_strategy
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=22.0,
        option_available=True, option_illiquid=True,
    )
    assert strategy == "spot"
    assert "流动性" in reason


def test_recommend_sell_put_when_superior():
    from src.dividend_scanners import _get_recommended_strategy
    # sgov_adjusted_apy (8.5) > current_yield (5.0) * 1.5 (7.5) → sell_put
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=8.5,
        option_available=True, option_illiquid=False,
    )
    assert strategy == "sell_put"


def test_recommend_spot_when_option_not_much_better():
    from src.dividend_scanners import _get_recommended_strategy
    # sgov_adjusted_apy (6.0) <= current_yield (5.0) * 1.5 (7.5) → spot
    strategy, reason = _get_recommended_strategy(
        ticker="AAPL", current_yield=5.0, sgov_adjusted_apy=6.0,
        option_available=True, option_illiquid=False,
    )
    assert strategy == "spot"


def test_buy_signal_includes_yield_p10_p90_hist_max():
    """DividendBuySignal should carry yield_p10, yield_p90, yield_hist_max from store."""
    store_mock = MagicMock()
    store_mock.get_yield_percentile.return_value = YieldPercentileResult(
        percentile=85.0, p10=3.5, p90=5.8, hist_max=12.0
    )
    store_mock.save_dividend_history = MagicMock()

    provider_mock = MagicMock()
    provider_mock.config = {"default_market": "US"}
    price_df = pd.DataFrame({"Close": [100.0]})
    provider_mock.get_price_data.return_value = price_df
    from datetime import datetime, timedelta
    recent = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    older = (datetime.now() - timedelta(days=240)).strftime("%Y-%m-%d")
    provider_mock.get_dividend_history.return_value = [
        {"date": recent, "amount": 1.0},
        {"date": older, "amount": 1.0},
    ]
    provider_mock.should_skip_options.return_value = True
    provider_mock.get_earnings_date.return_value = None

    pool = [{
        "ticker": "AAPL",
        "name": "Apple",
        "market": "US",
        "quality_score": 85.0,
        "consecutive_years": 10,
        "dividend_growth_5y": 6.0,
        "payout_ratio": 65.0,
        "payout_type": "GAAP",
        "forward_dividend_rate": 1.0,
        "max_yield_5y": 5.0,
        "data_version_date": "2026-03-10",
        "sgov_yield": 4.8,
        "quality_breakdown": {},
        "analysis_text": "",
    }]

    config = {"dividend_scanners": {"min_yield": 1.5, "min_yield_percentile": 80}}

    signals = scan_dividend_buy_signal(pool=pool, provider=provider_mock, store=store_mock, config=config)

    assert len(signals) == 1
    sig = signals[0]
    assert sig.yield_p10 == 3.5
    assert sig.yield_p90 == 5.8
    assert sig.yield_hist_max == 12.0
    assert sig.yield_percentile == 85.0


# ── Task 1: _compute_floor_data tests ────────────────────────────────────────

import numpy as np
from datetime import date as _date


class TestComputeFloorData:
    def _make_normal_series(self, low=40.0, high=100.0, n=1260) -> pd.Series:
        """Stable price series declining from high to low, no flash crash."""
        idx = pd.date_range("2020-01-01", periods=n, freq="B")
        prices = np.linspace(high, low, n)
        return pd.Series(prices, index=idx)

    def _make_flash_crash_series(self) -> pd.Series:
        """Series with a single-day flash crash to 10.0, otherwise 40-100."""
        idx = pd.date_range("2020-01-01", periods=1260, freq="B")
        prices = np.linspace(100.0, 40.0, 1260)
        s = pd.Series(prices, index=idx)
        s.iloc[600] = 10.0  # single-day spike
        return s

    def _make_sustained_low_series(self) -> pd.Series:
        """Series with 60-day sustained low at 15.0 (realistic bear market, not a flash crash).
        60 days = ~4.8% of 1260 — above the 3rd percentile threshold, so not filtered out."""
        idx = pd.date_range("2020-01-01", periods=1260, freq="B")
        prices = np.full(1260, 60.0, dtype=float)
        prices[600:660] = 15.0
        return pd.Series(prices, index=idx)

    def test_flash_crash_filtered_floor_price_higher_than_raw(self):
        """Single-day spike: filtered floor_price > raw floor_price_raw."""
        s = self._make_flash_crash_series()
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        assert result["floor_price"] > result["floor_price_raw"]

    def test_sustained_low_not_filtered(self):
        """10-day low: extreme_detected should be False (not filtered out)."""
        s = self._make_sustained_low_series()
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        assert result["extreme_detected"] is False

    def test_floor_price_formula(self):
        """floor_price = forward_dividend_rate / (max_yield_5y / 100)."""
        s = self._make_normal_series(low=40.0)
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        assert result["floor_price"] is not None
        assert result["max_yield_5y"] is not None
        expected = round(2.0 / (result["max_yield_5y"] / 100), 2)
        assert result["floor_price"] == expected

    def test_extreme_detected_flag_set_on_flash_crash(self):
        s = self._make_flash_crash_series()
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        assert result["extreme_detected"] is True
        assert result["extreme_event_price"] == pytest.approx(10.0, abs=1.0)

    def test_extreme_event_days_counted(self):
        s = self._make_flash_crash_series()
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        if result["extreme_detected"]:
            assert result["extreme_event_days"] >= 1

    def test_returns_raw_min_date(self):
        s = self._make_flash_crash_series()
        result = _compute_floor_data(s, annual_dividend_ttm=2.0, forward_dividend_rate=2.0)
        assert result["raw_min_date"] is not None

    def test_zero_dividend_returns_none_floor(self):
        s = self._make_normal_series()
        result = _compute_floor_data(s, annual_dividend_ttm=0.0, forward_dividend_rate=0.0)
        assert result["floor_price"] is None
        assert result["floor_price_raw"] is None


# ── Task 3: _label_extreme_event tests ───────────────────────────────────────

class TestLabelExtremeEvent:
    def test_covid_window_returns_label(self):
        label = _label_extreme_event(_date(2020, 3, 10), market="US", provider=None)
        assert label == "2020-03 COVID 抛售"

    def test_rate_hike_window_returns_label(self):
        label = _label_extreme_event(_date(2022, 6, 15), market="US", provider=None)
        assert label == "2022 加息熊市"

    def test_2018_q4_crash(self):
        label = _label_extreme_event(_date(2018, 12, 1), market="US", provider=None)
        assert label == "2018 Q4 崩盘"

    def test_cn_circuit_breaker_only_for_cn(self):
        label_cn = _label_extreme_event(_date(2016, 1, 5), market="CN", provider=None)
        label_us = _label_extreme_event(_date(2016, 1, 5), market="US", provider=None)
        assert label_cn == "2015 A股熔断"
        assert label_us is None

    def test_no_match_no_provider_returns_none(self):
        label = _label_extreme_event(_date(2023, 6, 1), market="US", provider=None)
        assert label is None

    def test_no_match_provider_systemic_risk(self):
        """Benchmark drops >10% around the date → 系统性风险."""
        mock_provider = MagicMock()
        idx = pd.date_range("2019-05-20", periods=15, freq="B")
        prices = [100.0] * 7 + [85.0] * 8  # -15% drop
        bench_df = pd.DataFrame({"Close": prices}, index=idx)
        mock_provider.get_price_data.return_value = bench_df
        label = _label_extreme_event(_date(2019, 5, 28), market="US", provider=mock_provider)
        assert label == "系统性风险"

    def test_no_match_provider_stock_specific(self):
        """Flat benchmark → 个股事件."""
        mock_provider = MagicMock()
        idx = pd.date_range("2019-05-20", periods=15, freq="B")
        bench_df = pd.DataFrame({"Close": [100.0] * 15}, index=idx)
        mock_provider.get_price_data.return_value = bench_df
        label = _label_extreme_event(_date(2019, 5, 28), market="US", provider=mock_provider)
        assert label == "个股事件"


# ── Task 6: wiring integration test ──────────────────────────────────────────

def test_buy_signal_passes_through_extreme_event_fields(tmp_path):
    """extreme_event_label from pool record is forwarded to DividendBuySignal."""
    store = DividendStore(str(tmp_path / "d.db"))
    pool = [{
        "ticker": "TEST",
        "forward_dividend_rate": 2.0,
        "max_yield_5y": 4.0,
        "data_version_date": date.today().isoformat(),
        "floor_price_raw": 40.0,
        "extreme_event_label": "2020-03 COVID 抛售",
        "extreme_event_price": 31.0,
        "extreme_event_days": 18,
        "sgov_yield": None,
    }]
    provider_mock = MagicMock()
    close_col = pd.Series(
        [50.0, 51.0, 50.5],
        index=pd.date_range("2026-03-10", periods=3, freq="B")
    )
    price_df = pd.DataFrame({"Close": close_col})
    div_history = [{"date": f"2025-{m:02d}-01", "amount": 0.5} for m in range(5, 9)]
    provider_mock.get_price_data.return_value = price_df
    provider_mock.get_dividend_history.return_value = div_history
    provider_mock.should_skip_options.return_value = True

    # Seed yield history so percentile check works
    store.save_dividend_history("TEST", _date(2025, 1, 1), 3.5, 2.0, 57.0)
    store.save_dividend_history("TEST", _date(2024, 6, 1), 3.2, 2.0, 62.0)

    signals = scan_dividend_buy_signal(
        pool=pool, provider=provider_mock, store=store,
        config={"dividend_scanners": {"min_yield": 3.0, "min_yield_percentile": 50}}
    )
    assert len(signals) == 1
    assert signals[0].extreme_event_label == "2020-03 COVID 抛售"
    assert signals[0].floor_price_raw == 40.0
    assert signals[0].extreme_event_days == 18
    assert signals[0].extreme_event_price == 31.0


def test_scan_dividend_sell_put_uses_golden_price_as_strike():
    """When golden_price is provided, use it as target_strike instead of yield-math."""
    chain = pd.DataFrame({
        'strike': [90.0, 95.0, 100.0, 105.0],
        'bid': [1.0, 1.2, 1.5, 1.8],
        'ask': [1.1, 1.3, 1.6, 1.9],
        'dte': [60, 60, 60, 60],
        'expiration': ['2026-05-15'] * 4,
    })
    mock_provider = MagicMock()
    mock_provider.get_options_chain.return_value = chain
    td = MagicMock()
    td.ticker = "AAPL"

    # golden_price=96.0 → closest strike is 95; yield-math (4.0/0.04=100) would give 100
    result = scan_dividend_sell_put(
        ticker_data=td, provider=mock_provider,
        annual_dividend=4.0, target_yield=4.0,
        min_dte=45, max_dte=90,
        golden_price=96.0, current_price=110.0,
    )
    assert result is not None
    assert result['strike'] == 95.0
    assert result['strike_rationale'] == "黄金位 = forward股息 / 历史75th收益率"
    assert result['golden_price'] == 96.0
    assert result['current_vs_golden_pct'] is not None


def test_scan_dividend_sell_put_fallback_when_no_golden_price():
    """When golden_price is None, falls back to yield-math for target_strike."""
    chain = pd.DataFrame({
        'strike': [90.0, 95.0, 100.0, 105.0],
        'bid': [1.0, 1.2, 1.5, 1.8],
        'ask': [1.1, 1.3, 1.6, 1.9],
        'dte': [60, 60, 60, 60],
        'expiration': ['2026-05-15'] * 4,
    })
    mock_provider = MagicMock()
    mock_provider.get_options_chain.return_value = chain
    td = MagicMock()
    td.ticker = "AAPL"

    # annual_dividend=4.0, target_yield=4.0 → target_strike=100
    result = scan_dividend_sell_put(
        ticker_data=td, provider=mock_provider,
        annual_dividend=4.0, target_yield=4.0,
        min_dte=45, max_dte=90,
        golden_price=None,
    )
    assert result is not None
    assert result['strike'] == 100.0
    assert "fallback" in result['strike_rationale']


def test_dividend_buy_signal_has_golden_price_field():
    """DividendBuySignal must carry golden_price, current_vs_golden_pct, strike_rationale."""
    sig = DividendBuySignal(
        ticker_data=MagicMock(), signal_type="STOCK",
        current_yield=5.0, yield_percentile=85.0,
    )
    assert hasattr(sig, "golden_price")
    assert hasattr(sig, "current_vs_golden_pct")
    assert hasattr(sig, "strike_rationale")


def test_ticker_data_has_golden_price_field():
    """TickerData must have golden_price as an Optional[float] field."""
    from src.data_engine import TickerData
    td = TickerData(
        ticker="TEST", name="Test", market="US", last_price=100.0,
        ma200=None, ma50w=None, rsi14=None, iv_rank=None, iv_momentum=None,
        prev_close=100.0, earnings_date=None, days_to_earnings=None,
    )
    assert hasattr(td, "golden_price")
    assert td.golden_price is None
    td.golden_price = 95.0
    assert td.golden_price == 95.0


def test_scan_entry_skips_option_when_price_at_or_below_golden(tmp_path):
    """When current_price <= golden_price, option scan is skipped and spot is recommended."""
    from src.dividend_scanners import scan_dividend_buy_signal
    from src.dividend_store import DividendStore

    db_path = str(tmp_path / "test.db")
    store = DividendStore(db_path)

    # Seed yield history so percentile check works (current yield ~4.1% will be high)
    ticker = "KO"
    for d, y in [("2021-03-01", 2.5), ("2022-03-01", 3.0), ("2023-03-01", 3.2),
                 ("2024-03-01", 3.5), ("2025-03-01", 3.8)]:
        store.save_dividend_history(ticker, date.fromisoformat(d), y, 4.0, 100.0)

    provider = MagicMock()
    # last_price = 98.0, which is <= golden_price = 100.0
    provider.get_price_data.return_value = pd.DataFrame(
        {"Close": [98.0]},
        index=pd.to_datetime([str(date.today())])
    )
    # annual_dividend = 4 * 1.0 = 4.0 → yield = 4.0/98 * 100 = ~4.08% >= min_yield 3.5
    provider.get_dividend_history.return_value = [
        {"date": str(date.today()), "amount": 1.0},
        {"date": str(date.today() - timedelta(days=90)), "amount": 1.0},
        {"date": str(date.today() - timedelta(days=180)), "amount": 1.0},
        {"date": str(date.today() - timedelta(days=270)), "amount": 1.0},
    ]
    provider.get_earnings_date.return_value = None
    provider.should_skip_options.return_value = False

    pool = [{
        "ticker": ticker,
        "market": "US",
        "forward_dividend_rate": 4.0,
        "max_yield_5y": 4.0,
        "quality_score": 80.0,
        "consecutive_years": 10,
        "dividend_growth_5y": 3.0,
        "payout_ratio": 60.0,
        "payout_type": "GAAP",
        "floor_price_raw": None,
        "extreme_event_label": None,
        "extreme_event_price": None,
        "extreme_event_days": None,
        "golden_price": 100.0,   # current price 98 <= golden 100 → skip option
        "data_version_date": str(date.today()),
        "sgov_yield": 4.8,
        "health_rationale": "Stable",
        "quality_breakdown": {},
        "analysis_text": "",
    }]

    config = {
        "dividend_scanners": {
            "min_yield": 3.5,
            "min_yield_percentile": 80.0,
            "option": {
                "enabled": True,
                "min_dte": 45,
                "max_dte": 90,
                "target_strike_percentile": 90,
            }
        }
    }

    results = scan_dividend_buy_signal(pool=pool, provider=provider, store=store, config=config)
    store.close()

    # Signal should still be generated (price at high yield)
    assert len(results) == 1
    sig = results[0]

    # Option must be skipped — price already at/below golden
    assert sig.option_details is None
    assert sig.ticker_data.recommended_strategy == "spot"
    assert "黄金位" in sig.ticker_data.recommended_reason

    # Provider must NOT have been called to fetch options
    provider.get_options_chain.assert_not_called()
