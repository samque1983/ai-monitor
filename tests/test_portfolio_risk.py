import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

from src.portfolio_risk import (
    AccountConfig,
    load_account_configs,
    RiskAlert,
    RiskReport,
    PortfolioRiskAnalyzer,
    generate_risk_suggestion,
)
from src.flex_client import PositionRecord, AccountSummary


# ---------------------------------------------------------------------------
# Task 2: Config loader
# ---------------------------------------------------------------------------

def test_load_account_configs_from_env(monkeypatch):
    monkeypatch.setenv("ACCOUNT_ALICE_NAME", "Alice IB")
    monkeypatch.setenv("ACCOUNT_ALICE_CODE", "alice")
    monkeypatch.setenv("ACCOUNT_ALICE_FLEX_TOKEN", "tok123")
    monkeypatch.setenv("ACCOUNT_ALICE_FLEX_QUERY_ID", "99")
    monkeypatch.setenv("ACCOUNT_BOB_FLEX_TOKEN", "tokBob")
    monkeypatch.setenv("ACCOUNT_BOB_FLEX_QUERY_ID", "88")
    configs = load_account_configs()
    keys = {c.key for c in configs}
    assert "ALICE" in keys
    assert "BOB" in keys
    alice = next(c for c in configs if c.key == "ALICE")
    assert alice.flex_token == "tok123"
    assert alice.flex_query_id == "99"
    assert alice.name == "Alice IB"
    bob = next(c for c in configs if c.key == "BOB")
    assert bob.name == "BOB"  # defaults to key when NAME not set


def test_load_account_configs_empty(monkeypatch):
    for k in list(os.environ):
        if k.startswith("ACCOUNT_"):
            monkeypatch.delenv(k)
    assert load_account_configs() == []


# ---------------------------------------------------------------------------
# Helpers for dims tests
# ---------------------------------------------------------------------------

def _make_position(symbol="AAPL", asset_category="STK", put_call="",
                   strike=0, expiry="", multiplier=1, position=100,
                   cost_basis=150, mark=182, pnl=3200,
                   delta=1.0, gamma=0.0, theta=0.0, vega=0.0):
    return PositionRecord(
        symbol=symbol, asset_category=asset_category, put_call=put_call,
        strike=strike, expiry=expiry, multiplier=multiplier, position=position,
        cost_basis_price=cost_basis, mark_price=mark, unrealized_pnl=pnl,
        delta=delta, gamma=gamma, theta=theta, vega=vega,
    )


def _make_account(nlv=120000, gross=95000, init_margin=18000,
                  maint_margin=12300, excess=22200, avail=25000, cushion=0.35):
    return AccountSummary(
        net_liquidation=nlv, gross_position_value=gross,
        init_margin_req=init_margin, maint_margin_req=maint_margin,
        excess_liquidity=excess, available_funds=avail, cushion=cushion,
    )


def _analyze_no_mdp(positions, account):
    """Analyze without triggering real MarketDataProvider calls."""
    analyzer = PortfolioRiskAnalyzer()
    with patch("src.portfolio_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = {"beta": 1.0}
        MockMDP.return_value.get_earnings_date.return_value = (None, None)
        return analyzer.analyze(positions, account)


# ---------------------------------------------------------------------------
# Task 3: Dims 1–5
# ---------------------------------------------------------------------------

def test_dim1_dollar_delta_yellow():
    pos = _make_position(position=100, mark=182, delta=1.0, multiplier=1)
    account = _make_account(nlv=20000)
    report = _analyze_no_mdp([pos], account)
    dim1_alerts = [a for a in report.alerts if a.dimension == 1]
    assert len(dim1_alerts) == 1
    assert dim1_alerts[0].level == "yellow"


def test_dim1_dollar_delta_no_alert():
    pos = _make_position(position=10, mark=100, delta=1.0)
    account = _make_account(nlv=100000)
    report = _analyze_no_mdp([pos], account)
    assert not any(a.dimension == 1 for a in report.alerts)


def test_dim2_negative_theta_alert():
    pos = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                         multiplier=100, position=1, theta=-0.05)
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    assert any(a.dimension == 2 for a in report.alerts)


def test_dim2_positive_theta_no_alert():
    pos = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                         multiplier=100, position=-1, theta=-0.05)
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    assert not any(a.dimension == 2 for a in report.alerts)


def test_dim4_margin_cushion_yellow():
    account = _make_account(cushion=0.18)
    report = _analyze_no_mdp([], account)
    dim4 = [a for a in report.alerts if a.dimension == 4]
    assert len(dim4) == 1
    assert dim4[0].level == "yellow"


def test_dim4_margin_cushion_red():
    account = _make_account(cushion=0.08)
    report = _analyze_no_mdp([], account)
    dim4 = [a for a in report.alerts if a.dimension == 4]
    assert dim4[0].level == "red"


def test_dim5_concentration_alert():
    pos = _make_position(symbol="AAPL", position=100, mark=182, multiplier=1)
    account = _make_account(nlv=20000)
    report = _analyze_no_mdp([pos], account)
    dim5 = [a for a in report.alerts if a.dimension == 5]
    assert len(dim5) >= 1
    assert dim5[0].ticker == "AAPL"


# ---------------------------------------------------------------------------
# Task 4: Dims 7–9
# ---------------------------------------------------------------------------

def test_dim7_dte_short_put_alert():
    expiry = (date.today() + timedelta(days=8)).strftime("%Y%m%d")
    pos = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                         strike=110, mark=107, position=-1, multiplier=100,
                         expiry=expiry, delta=-0.35, gamma=0.08)
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    dim7 = [a for a in report.alerts if a.dimension == 7]
    assert len(dim7) >= 1
    assert dim7[0].ticker == "NVDA"
    assert dim7[0].level == "red"


def test_dim7_otm_long_dte_no_alert():
    expiry = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    pos = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                         strike=160, mark=182, position=-1, multiplier=100,
                         expiry=expiry)
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    assert not any(a.dimension == 7 for a in report.alerts)


def test_dim8_sell_put_low_cushion():
    expiry = (date.today() + timedelta(days=17)).strftime("%Y%m%d")
    pos = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                         strike=177, mark=182, position=-2, multiplier=100,
                         expiry=expiry, cost_basis=25.0)
    pos.mark_price = 5.5
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    dim8 = [a for a in report.alerts if a.dimension == 8]
    assert len(dim8) >= 1


def test_dim9_gamma_near_expiry():
    expiry = (date.today() + timedelta(days=8)).strftime("%Y%m%d")
    pos = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                         strike=110, mark=107, position=-1, multiplier=100,
                         expiry=expiry, gamma=0.08)
    account = _make_account()
    report = _analyze_no_mdp([pos], account)
    dim9 = [a for a in report.alerts if a.dimension == 9]
    assert len(dim9) >= 1
    assert dim9[0].ticker == "NVDA"


# ---------------------------------------------------------------------------
# Task 5: Dim 10 + summary_stats
# ---------------------------------------------------------------------------

def test_dim10_stress_test_alert():
    pos = _make_position(symbol="AAPL", position=100, mark=182, delta=1.0, multiplier=1)
    account = _make_account(nlv=10000)
    analyzer = PortfolioRiskAnalyzer()
    mock_fund = {"beta": 1.2}
    with patch("src.portfolio_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = mock_fund
        MockMDP.return_value.get_earnings_date.return_value = (None, None)
        report = analyzer.analyze([pos], account)
    assert "stress_test" in report.summary_stats
    assert report.summary_stats["stress_test"]["drop_10pct"] < 0
    dim10 = [a for a in report.alerts if a.dimension == 10]
    assert len(dim10) >= 1


def test_dim10_no_alert_small_portfolio():
    pos = _make_position(symbol="AAPL", position=5, mark=182, delta=1.0, multiplier=1)
    account = _make_account(nlv=1000000)
    analyzer = PortfolioRiskAnalyzer()
    with patch("src.portfolio_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = {"beta": 1.0}
        MockMDP.return_value.get_earnings_date.return_value = (None, None)
        report = analyzer.analyze([pos], account)
    assert not any(a.dimension == 10 for a in report.alerts)
    assert "stress_test" in report.summary_stats


# ---------------------------------------------------------------------------
# Task 6: LLM suggestions
# ---------------------------------------------------------------------------

def test_generate_risk_suggestion_llm():
    alert = RiskAlert(dimension=4, level="yellow", ticker="ACCOUNT",
                      detail="cushion 18.5%", options=["A. 平仓", "B. 存现金"])
    with patch("src.portfolio_risk.make_llm_client_from_env") as mock_factory:
        mock_client = MagicMock()
        mock_client.simple_chat.return_value = "AI 建议文本"
        mock_factory.return_value = mock_client
        with patch("src.portfolio_risk._has_llm_key", return_value=True):
            result = generate_risk_suggestion(alert, {})
    assert result == "AI 建议文本"


def test_generate_risk_suggestion_fallback_on_exception():
    alert = RiskAlert(dimension=4, level="yellow", ticker="ACCOUNT",
                      detail="cushion 18.5%", options=[])
    with patch("src.portfolio_risk._has_llm_key", return_value=True):
        with patch("src.portfolio_risk.make_llm_client_from_env") as mock_factory:
            mock_factory.side_effect = RuntimeError("no key")
            result = generate_risk_suggestion(alert, {})
    assert isinstance(result, str)
    assert len(result) > 0


def test_generate_risk_suggestion_no_key_uses_fallback():
    alert = RiskAlert(dimension=1, level="red", ticker="PORTFOLIO",
                      detail="Delta 120%", options=[])
    with patch("src.portfolio_risk._has_llm_key", return_value=False):
        result = generate_risk_suggestion(alert, {})
    assert isinstance(result, str)
    assert len(result) > 0
