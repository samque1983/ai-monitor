"""Phase 7 end-to-end pipeline integration tests."""
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
from src.option_strategies import OptionStrategyRecognizer
from src.strategy_risk import StrategyRiskEngine, StrategyRiskReport
from src.flex_client import PositionRecord, AccountSummary


def _make_position(symbol, asset_category, put_call="", strike=0, expiry="",
                   multiplier=100, position=-5, cost_basis=3.0, mark=2.0,
                   delta=-0.3, underlying="AAPL", currency="USD"):
    return PositionRecord(
        symbol=symbol, asset_category=asset_category, put_call=put_call,
        strike=strike, expiry=expiry, multiplier=multiplier, position=position,
        cost_basis_price=cost_basis, mark_price=mark, unrealized_pnl=0.0,
        delta=delta, gamma=0.02, theta=-0.05, vega=0.15,
        underlying_symbol=underlying, currency=currency,
    )


def test_full_pipeline_naked_put():
    """End-to-end: Flex positions → strategies → risk report."""
    expiry = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    p = _make_position("AAPL  P180", "OPT", "P", 180, expiry, position=-5)
    account = AccountSummary(net_liquidation=500000, gross_position_value=0,
                              init_margin_req=0, maint_margin_req=50000,
                              excess_liquidity=0, available_funds=0, cushion=0.30)
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize([p])
    assert strategies[0].strategy_type == "Naked Put"

    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = {"beta": 1.2}
        report = engine.analyze(strategies, account)

    assert report.net_liquidation == 500000
    assert isinstance(report.summary_stats["stress_test"]["drop_10pct"], float)


def test_full_pipeline_iron_condor():
    """Iron Condor recognized and produces strategy-level risk analysis."""
    exp = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    sc = _make_position("AAPL C210", "OPT", "C", 210, exp, position=-3, delta=0.25)
    lc = _make_position("AAPL C220", "OPT", "C", 220, exp, position=3, delta=0.15)
    sp = _make_position("AAPL P170", "OPT", "P", 170, exp, position=-3, delta=-0.25)
    lp = _make_position("AAPL P160", "OPT", "P", 160, exp, position=3, delta=-0.15)
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize([sc, lc, sp, lp])
    assert len(strategies) == 1
    assert strategies[0].strategy_type == "Iron Condor"
    assert len(strategies[0].breakevens) == 2


def test_html_report_generated():
    """generate_html_report returns valid HTML for StrategyRiskReport."""
    from src.portfolio_report import generate_html_report
    report = StrategyRiskReport(
        account_id="TEST", report_date="2026-03-11",
        net_liquidation=500000, total_pnl=5000, cushion=0.29,
    )
    html = generate_html_report(report)
    assert "<!DOCTYPE html>" in html
    assert "TEST" in html


def test_covered_call_pipeline():
    """Covered Call (stock + short call) recognized as single strategy."""
    exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    stk = _make_position("AAPL", "STK", position=100, mark=180.0,
                          underlying="AAPL")
    call = _make_position("AAPL  C200", "OPT", "C", 200, exp,
                           position=-1, delta=0.3, underlying="AAPL")
    strategies = OptionStrategyRecognizer().recognize([stk, call])
    assert len(strategies) == 1
    assert strategies[0].strategy_type == "Covered Call"
    assert strategies[0].stock_leg is not None


def test_mixed_portfolio_pipeline():
    """Multiple underlyings each produce their own strategy groups."""
    exp = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    aapl_put = _make_position("AAPL P180", "OPT", "P", 180, exp,
                               position=-3, underlying="AAPL")
    nvda_put = _make_position("NVDA P600", "OPT", "P", 600, exp,
                               position=-2, underlying="NVDA")
    strategies = OptionStrategyRecognizer().recognize([aapl_put, nvda_put])
    underlyings = {sg.underlying for sg in strategies}
    assert "AAPL" in underlyings
    assert "NVDA" in underlyings
    assert len(strategies) == 2
