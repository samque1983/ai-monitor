# tests/test_dividend_scanners.py
import pytest
import pandas as pd
from datetime import date
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData
from src.dividend_scanners import scan_dividend_pool_weekly, scan_dividend_buy_signal, DividendBuySignal
from src.financial_service import DividendQualityScore
from src.dividend_store import DividendStore


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
        mock_provider.get_price_data.return_value = {
            "close": [45.0, 46.0, 47.0, 46.5, 46.0],
            "date": ["2026-02-28", "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04"]
        }
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
        pool = [ticker]
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
            target_yield_percentile=90,  # Not used in strike selection
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
        mock_provider.get_price_data.return_value = {
            "close": [46.0],
            "date": ["2026-03-04"]
        }
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
        pool = [ticker]
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
        assert signal.option_details['strike'] == 32.0, "Should select $32 strike"
        assert signal.option_details['bid'] == 1.20
        assert signal.option_details['dte'] == 60

        # Clean up
        store.close()
