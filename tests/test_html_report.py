# tests/test_html_report.py
import pytest
from datetime import date
from src.data_engine import TickerData
from src.scanners import SellPutSignal
from src.html_report import format_html_report


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


class TestHtmlReport:
    def test_contains_html_structure(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "量化扫描雷达" in html

    def test_contains_chinese_header(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="IBKR Gateway",
            universe_count=42,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=12.5,
        )
        assert "量化扫描雷达" in html
        assert "2026-02-20" in html
        assert "42" in html
        assert "V1.9" not in html

    def test_contains_module_titles(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "波动率极值监控" in html
        assert "趋势反转提醒" in html
        assert "LEAPS 共振信号" in html
        assert "Sell Put 扫描" in html

    def test_empty_modules_show_chinese_none(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "无符合条件的标的" in html

    def test_contains_ticker_data(self):
        low = [make_ticker(ticker="AAPL", iv_rank=12.3)]
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=low, iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "AAPL" in html
        assert "12.3" in html

    def test_sell_put_earnings_warning(self):
        signal = SellPutSignal(
            ticker="NVDA", strike=110.0, bid=1.80,
            dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True,
        )
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[(signal, make_ticker(ticker="NVDA"))],
            elapsed_seconds=5.0,
        )
        assert "NVDA" in html
        assert "\U0001f6a8" in html or "🚨" in html

    def test_skipped_tickers(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            skipped=[
                ("BRK.B", "无价格数据"),
                ("600900", "无价格数据"),
            ],
            elapsed_seconds=5.0,
        )
        assert "BRK.B" in html
        assert "600900" in html
        assert "跳过: 2" in html

    def test_inline_css(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "<style>" in html
        assert "max-width" in html
