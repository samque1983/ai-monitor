# tests/test_report.py
import pytest
from datetime import date
from src.data_engine import TickerData, EarningsGap
from src.scanners import SellPutSignal
from src.report import format_report, format_earnings_tag


def make_ticker(**kwargs) -> TickerData:
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, iv_momentum=None,
        prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
        # Phase 2: 高股息新增字段
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
            ticker="NVDA", strike=110.0, bid=1.80, ask=0.0, mid=1.80,
            spread_pct=0.0, dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True, liquidity_warn=False,
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


class TestEarningsGapSection:
    def test_gap_data_in_report(self):
        """Gap 数据出现在报告中"""
        gaps = [
            EarningsGap(
                ticker="AAPL",
                avg_gap=4.2,
                up_ratio=62.5,
                max_gap=-8.1,
                sample_count=6
            )
        ]
        ticker_map = {
            "AAPL": make_ticker(
                ticker="AAPL",
                iv_rank=85.3,
                days_to_earnings=2
            )
        }

        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )

        assert "财报 Gap 预警" in report
        assert "AAPL" in report
        assert "4.2" in report
        assert "62.5" in report
        assert "-8.1" in report
        assert "85.3" in report

    def test_high_iv_risk_warning(self):
        """高 IV + 临近财报显示风险警告"""
        gaps = [EarningsGap("AAPL", 4.2, 62.5, -8.1, 6)]
        ticker_map = {
            "AAPL": make_ticker(ticker="AAPL", iv_rank=75.0, days_to_earnings=2)
        }

        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )

        assert "IV Crush 风险" in report

    def test_empty_gaps_shows_placeholder(self):
        """无符合条件的标的显示占位符"""
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=[],
            elapsed_seconds=5.0,
        )

        assert "财报 Gap 预警" in report
        assert "无符合条件的标的" in report


def test_html_report_includes_opportunity_cards():
    from datetime import date
    from src.html_report import format_html_report

    cards = [{
        "ticker": "AAPL", "strategy": "SELL_PUT",
        "trigger_reason": "跌入便宜区间",
        "action": "卖出 6月 $170 Put",
        "one_line_logic": "安全垫充足",
        "key_params": {"strike": 170, "dte": 60, "premium": 1.6, "apy": 11.8},
        "win_scenarios": [{"prob": 0.85, "desc": "安全收租"}],
        "valuation": {"iron_floor": 163.5, "fair_value": 182.5,
                      "logic_summary": "EPS × PE 估值"},
        "fundamentals": {"moat": "iOS 生态"},
        "events": [], "take_profit": "赚80%止盈",
        "stop_loss": "营收恶化", "max_loss_usd": 9.1, "max_loss_pct": 0.09,
    }]
    html = format_html_report(
        scan_date=date(2026, 3, 6), data_source="IBKR",
        universe_count=22, iv_low=[], iv_high=[],
        ma200_bullish=[], ma200_bearish=[], leaps=[],
        sell_puts=[], elapsed_seconds=1.0,
        opportunity_cards=cards,
    )
    assert "AAPL" in html
    assert "Sell Put 收租" in html or "SELL_PUT" in html
    assert "铁底" in html
    assert "查看详细分析" in html
