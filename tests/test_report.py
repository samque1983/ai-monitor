# tests/test_report.py
import pytest
from datetime import date
from src.data_engine import TickerData
from src.scanners import SellPutSignal
from src.report import format_report, format_earnings_tag


def make_ticker(**kwargs) -> TickerData:
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, iv_momentum=None,
        prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestFormatEarningsTag:
    def test_with_date(self):
        tag = format_earnings_tag(date(2026, 4, 25), 64)
        assert "2026-04-25" in tag
        assert "64天" in tag
        assert "财报" in tag

    def test_without_date(self):
        tag = format_earnings_tag(None, None)
        assert "N/A" in tag
        assert "财报" in tag


class TestFormatReport:
    def test_report_contains_header(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="IBKR Gateway",
            universe_count=42,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[],
            elapsed_seconds=12.5,
        )
        assert "量化扫描雷达" in report
        assert "2026-02-20" in report
        assert "42" in report
        assert "V1.9" not in report

    def test_report_contains_iv_extremes(self):
        low = [make_ticker(ticker="AAPL", iv_rank=12.3)]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=low, iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "AAPL" in report
        assert "12.3" in report
        assert "波动率极值监控" in report

    def test_report_contains_sell_put_warning(self):
        signal = SellPutSignal(
            ticker="NVDA", strike=110.0, bid=1.80,
            dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True,
        )
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[(signal, make_ticker(ticker="NVDA"))],
            elapsed_seconds=5.0,
        )
        assert "NVDA" in report
        assert "\U0001f6a8" in report

    def test_empty_modules_show_chinese_none(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "无符合条件的标的" in report

    def test_skipped_tickers_show_reasons(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            skipped=[
                ("BRK.B", "无价格数据 (no price data)"),
                ("600900", "无价格数据 (no price data)"),
            ],
            elapsed_seconds=5.0,
        )
        assert "BRK.B" in report
        assert "600900" in report
        assert "无价格数据" in report
        assert "跳过: 2" in report
        assert "处理: 8" in report


class TestIVMomentumSection:
    def test_momentum_tickers_in_report(self):
        """IV 动量标的出现在报告中"""
        momentum = [
            make_ticker(ticker="SPIKE", iv_momentum=45.0, iv_rank=72.0, days_to_earnings=2)
        ]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=momentum,
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in report
        assert "SPIKE" in report
        assert "45.0" in report

    def test_empty_momentum_shows_placeholder(self):
        """无符合条件的标的显示占位符"""
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=[],
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in report
        assert "无符合条件的标的" in report
