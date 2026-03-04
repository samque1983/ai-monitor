# tests/test_dividend_scanners.py
import pytest
from datetime import date
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData
from src.dividend_scanners import scan_dividend_pool_weekly
from src.financial_service import DividendQualityScore


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
