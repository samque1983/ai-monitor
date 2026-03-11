"""Tests for StrategyRiskEngine, StrategyRiskAlert, StrategyRiskReport."""
import pytest
from unittest.mock import patch
from datetime import date, timedelta
from src.strategy_risk import StrategyRiskEngine, StrategyRiskAlert, StrategyRiskReport
from src.option_strategies import StrategyGroup, OptionStrategyRecognizer
from src.flex_client import PositionRecord, AccountSummary


def _account(nlv=500000, cushion=0.30, maint=50000):
    return AccountSummary(net_liquidation=nlv, gross_position_value=0,
                          init_margin_req=0, maint_margin_req=maint,
                          excess_liquidity=0, available_funds=0, cushion=cushion)


def _near_exp(days=7):
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")


def _far_exp(days=90):
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")


def _naked_put_group(strike=180, dte_days=7, itm_pct=3.0, contracts=5, nlv=500000):
    """StrategyGroup representing a Naked Put that's ITM and near expiry."""
    mark = strike * (1 - itm_pct / 100)
    p = PositionRecord(
        symbol=f"AAPL  P{strike:.0f}", asset_category="OPT", put_call="P",
        strike=float(strike), expiry=_near_exp(dte_days), multiplier=100,
        position=-contracts, cost_basis_price=3.0, mark_price=float(mark),
        unrealized_pnl=-(mark * 100 * contracts), delta=-0.7, gamma=0.05,
        theta=-0.1, vega=0.2, underlying_symbol="AAPL", currency="USD",
    )
    sg = StrategyGroup(underlying="AAPL", strategy_type="Naked Put", intent="income",
                       legs=[p], expiry=p.expiry, dte=dte_days,
                       max_loss=None, net_credit=3.0 * 100 * contracts)
    return sg


def test_rule1_assignment_imminent():
    """Rule 1: Short leg DTE ≤ 7 AND ITM > 2% → red alert."""
    sg = _naked_put_group(strike=180, dte_days=5, itm_pct=3.0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account())
    reds = [a for a in report.alerts if a.severity == "red" and a.rule_id == 1]
    assert reds, "Rule 1 must fire for ITM naked put with DTE ≤ 7"


def test_rule4_margin_critical():
    """Rule 4: cushion < 10% → red alert."""
    sg = _naked_put_group(dte_days=45, itm_pct=0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account(cushion=0.07))
    reds = [a for a in report.alerts if a.severity == "red" and a.rule_id == 4]
    assert reds, "Rule 4 must fire when cushion < 10%"


def test_report_has_summary_stats():
    """StrategyRiskReport exposes summary_stats for RiskStore compatibility."""
    sg = _naked_put_group(dte_days=45, itm_pct=0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account())
    assert isinstance(report.summary_stats, dict)
    assert "stress_test" in report.summary_stats
