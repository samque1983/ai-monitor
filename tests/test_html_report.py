# tests/test_html_report.py
import pytest
from datetime import date
from src.data_engine import TickerData, EarningsGap
from src.scanners import SellPutSignal
from src.html_report import format_html_report
from src.dividend_scanners import DividendBuySignal


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


class TestIVMomentumCard:
    def test_momentum_card_in_html(self):
        """IV Momentum 卡片出现在 HTML 中"""
        momentum = [make_ticker(ticker="SPIKE", iv_momentum=45.0)]
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=momentum,
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in html
        assert "SPIKE" in html


class TestEarningsGapCard:
    def test_gap_card_in_html(self):
        """Earnings Gap 卡片出现在 HTML 中"""
        gaps = [EarningsGap("AAPL", 4.2, 62.5, -8.1, 6)]
        ticker_map = {"AAPL": make_ticker(ticker="AAPL", iv_rank=85.3, days_to_earnings=2)}

        html = format_html_report(
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

        assert "财报 Gap 预警" in html
        assert "AAPL" in html


class TestDividendSection:
    """Task 4.1 + 4.2: HTML报告应包含高股息防御双打章节"""

    def _base_kwargs(self):
        return dict(
            scan_date=date(2026, 3, 5),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=1.0,
        )

    def test_dividend_section_present_when_signals_provided(self):
        """提供dividend_signals时，HTML应包含高股息防御双打章节"""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="ENB",
                last_price=34.5,
                dividend_yield=6.8,
                dividend_yield_5y_percentile=92.0,
                dividend_quality_score=85.0,
                payout_ratio=78.0,
            ),
            signal_type="OPTION",
            current_yield=6.8,
            yield_percentile=92.0,
            option_details={"strike": 33.0, "bid": 0.45, "dte": 60, "apy": 8.2},
        )

        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 23, "last_update": "2026-03-03"},
        )

        assert "高股息防御双打" in html
        assert "ENB" in html
        assert "6.8" in html   # dividend yield
        assert "92" in html    # percentile
        assert "23" in html    # pool count

    def test_dividend_section_absent_when_no_signals(self):
        """不提供dividend_signals时，不应渲染股息章节（heading标签）"""
        html = format_html_report(**self._base_kwargs())
        assert "<h2>高股息防御双打</h2>" not in html

    def test_dividend_card_shows_option_details(self):
        """期权策略信号的卡片应显示strike/dte/apy"""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="XYZ",
                last_price=50.0,
                dividend_yield=5.5,
                dividend_yield_5y_percentile=91.0,
                payout_ratio=60.0,
                dividend_quality_score=80.0,
            ),
            signal_type="OPTION",
            current_yield=5.5,
            yield_percentile=91.0,
            option_details={"strike": 48.0, "bid": 0.60, "dte": 45, "apy": 10.1},
        )

        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 5, "last_update": "2026-03-03"},
        )

        assert "48" in html    # strike
        assert "45" in html    # dte
        assert "10.1" in html  # apy

    def test_dividend_card_payout_warning(self):
        """派息率>80%应在卡片中显示警告标志"""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="RISKY",
                last_price=20.0,
                dividend_yield=8.0,
                dividend_yield_5y_percentile=95.0,
                payout_ratio=85.0,
                dividend_quality_score=72.0,
            ),
            signal_type="STOCK",
            current_yield=8.0,
            yield_percentile=95.0,
            option_details=None,
        )

        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-05"},
        )

        assert "RISKY" in html
        assert "85" in html   # payout ratio shown
        assert "⚠️" in html   # warning emoji for high payout

    def test_dividend_section_has_info_badge_linking_to_pool_page(self):
        """Dividend section heading must have ⓘ badge linking to dividend_pool.html."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="KO",
                last_price=60.0,
                dividend_yield=4.5,
                dividend_yield_5y_percentile=93.0,
                dividend_quality_score=85.0,
                payout_ratio=65.0,
            ),
            signal_type="STOCK",
            current_yield=4.5,
            yield_percentile=93.0,
            option_details=None,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 30, "last_update": "2026-03"},
        )
        assert 'href="dividend_pool.html"' in html
        assert 'ⓘ' in html or '&#9432;' in html


class TestDividendCardEnrichment:
    """Task 6: _dividend_card() renders enriched fields — floor price, quality breakdown."""

    def _base_kwargs(self):
        return dict(
            scan_date=date(2026, 3, 9),
            data_source="yfinance",
            universe_count=5,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=1.0,
        )

    def test_floor_price_displayed_when_provided(self):
        """_dividend_card() should render floor_price and floor_downside_pct."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="KO",
                last_price=62.5,
                dividend_yield=3.2,
                dividend_yield_5y_percentile=85.0,
                dividend_quality_score=85.0,
                payout_ratio=62.5,
                forward_dividend_rate=1.94,
                max_yield_5y=4.5,
            ),
            signal_type="OPTION",
            current_yield=3.2,
            yield_percentile=85.0,
            option_details={"strike": 60.0, "bid": 1.20, "dte": 30, "apy": 8.5},
            floor_price=43.11,
            floor_downside_pct=31.0,
            forward_dividend_rate=1.94,
            max_yield_5y=4.5,
            data_age_days=3,
            needs_reeval=False,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "43.11" in html          # floor_price
        assert "4.5" in html            # max_yield_5y
        assert "1.94" in html           # forward_dividend_rate
        assert "极值底价" in html

    def test_floor_price_absent_shows_fallback(self):
        """When floor_price is None, card should show the no-data fallback."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="MCD",
                last_price=280.0,
                dividend_yield=2.5,
                dividend_yield_5y_percentile=82.0,
                dividend_quality_score=90.0,
                payout_ratio=55.0,
            ),
            signal_type="STOCK",
            current_yield=2.5,
            yield_percentile=82.0,
            option_details=None,
            floor_price=None,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "极值底价数据暂缺" in html

    def test_quality_breakdown_details_rendered(self):
        """_dividend_card() should render a <details> element with quality breakdown bars."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="KO",
                last_price=62.5,
                dividend_yield=3.2,
                dividend_yield_5y_percentile=85.0,
                dividend_quality_score=85.0,
                payout_ratio=62.5,
                quality_breakdown={
                    "continuity": 18,
                    "payout_safety": 14,
                    "earnings_stability": 17,
                    "moat": 19,
                    "debt_level": 17,
                },
                analysis_text="KO is one of the widest-moat consumer staples globally.",
            ),
            signal_type="STOCK",
            current_yield=3.2,
            yield_percentile=85.0,
            option_details=None,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "<details" in html
        assert "股息连续性" in html
        assert "业务护城河" in html
        assert "KO is one of the widest-moat" in html

    def test_quality_breakdown_absent_no_details_tag(self):
        """When quality_breakdown is None, no <details> element should appear."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="JNJ",
                last_price=160.0,
                dividend_yield=3.0,
                dividend_yield_5y_percentile=80.0,
                dividend_quality_score=88.0,
                payout_ratio=50.0,
                quality_breakdown=None,
                analysis_text=None,
            ),
            signal_type="STOCK",
            current_yield=3.0,
            yield_percentile=80.0,
            option_details=None,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "<details" not in html

    def test_freshness_warn_when_needs_reeval(self):
        """needs_reeval=True should produce a re-evaluation warning in the card."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="T",
                last_price=18.0,
                dividend_yield=5.5,
                dividend_yield_5y_percentile=88.0,
                dividend_quality_score=65.0,
                payout_ratio=70.0,
            ),
            signal_type="STOCK",
            current_yield=5.5,
            yield_percentile=88.0,
            option_details=None,
            needs_reeval=True,
            data_age_days=5,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "财报后数据" in html or "建议重新评估" in html

    def test_freshness_old_data_badge(self):
        """data_age_days > 14 should produce an old-data notice."""
        signal = DividendBuySignal(
            ticker_data=make_ticker(
                ticker="VZ",
                last_price=40.0,
                dividend_yield=6.0,
                dividend_yield_5y_percentile=86.0,
                dividend_quality_score=70.0,
                payout_ratio=68.0,
            ),
            signal_type="STOCK",
            current_yield=6.0,
            yield_percentile=86.0,
            option_details=None,
            needs_reeval=False,
            data_age_days=20,
        )
        html = format_html_report(
            **self._base_kwargs(),
            dividend_signals=[signal],
            dividend_pool_summary={"count": 1, "last_update": "2026-03-09"},
        )
        assert "数据较旧" in html
