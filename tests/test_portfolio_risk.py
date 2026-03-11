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
                   delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
                   underlying_symbol="", currency="USD"):
    return PositionRecord(
        symbol=symbol, asset_category=asset_category, put_call=put_call,
        strike=strike, expiry=expiry, multiplier=multiplier, position=position,
        cost_basis_price=cost_basis, mark_price=mark, unrealized_pnl=pnl,
        delta=delta, gamma=gamma, theta=theta, vega=vega,
        underlying_symbol=underlying_symbol, currency=currency,
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


# ---------------------------------------------------------------------------
# Bug fixes: dim1 sign/price, dim5 notional, dim7/dim8 spread detection
# ---------------------------------------------------------------------------

def test_dim1_short_put_positive_delta():
    """Short puts must contribute positive dollar delta (correct direction)."""
    # Underlying stock provides the price reference
    stk = _make_position(symbol="AAPL", asset_category="STK",
                         position=1, mark=180, delta=1.0, multiplier=1)
    # Short 5 AAPL 150P, delta=-0.30 → contribution = (-5)×(-0.30)×100×180 = +27,000
    opt = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                         strike=150, position=-5, multiplier=100,
                         mark=2.5, delta=-0.30)
    account = _make_account(nlv=10000)
    report = _analyze_no_mdp([stk, opt], account)
    # total ≈ 180 + 27,000 = 27,180 / 10,000 → red
    dim1 = [a for a in report.alerts if a.dimension == 1]
    assert len(dim1) == 1
    assert dim1[0].level == "red"


def test_dim1_long_put_reduces_delta():
    """Long puts must subtract from dollar delta (hedging)."""
    # 100 shares AAPL + long 1 ATM put should reduce net delta vs unhedged
    stk = _make_position(symbol="AAPL", asset_category="STK",
                         position=100, mark=180, delta=1.0, multiplier=1)
    # Long 1 AAPL 180P with delta=-0.50 → contribution = (+1)×(-0.50)×100×180 = -9,000
    opt = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                         strike=180, position=1, multiplier=100,
                         mark=5.0, delta=-0.50)
    account = _make_account(nlv=20000)
    report_hedged = _analyze_no_mdp([stk, opt], account)
    report_unhedged = _analyze_no_mdp([stk], account)
    # Unhedged: 100×180 / 20,000 = 90% → yellow
    assert any(a.dimension == 1 for a in report_unhedged.alerts)
    # Hedged: (18,000 - 9,000) / 20,000 = 45% → no alert
    assert not any(a.dimension == 1 for a in report_hedged.alerts)


def test_dim5_option_uses_notional_not_market_value():
    """Options concentration uses strike×multiplier×position, not tiny option premium."""
    # Short 5 AAPL 150P, mark=$2.5 (option premium)
    # OLD notional = 5×2.5×100 = 1,250 → 1.25% of 100k → no alert
    # NEW notional = 5×150×100 = 75,000 → 75% of 100k → alert
    opt = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                         strike=150, position=-5, multiplier=100, mark=2.5)
    account = _make_account(nlv=100000)
    report = _analyze_no_mdp([opt], account)
    dim5 = [a for a in report.alerts if a.dimension == 5]
    assert len(dim5) >= 1
    assert dim5[0].ticker == "AAPL"


def test_dim7_spread_downgraded_to_yellow():
    """ITM short put in a put spread should be yellow, not red (max loss is capped)."""
    expiry = (date.today() + timedelta(days=8)).strftime("%Y%m%d")
    short_put = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                               strike=110, mark=107, position=-1, multiplier=100,
                               expiry=expiry, delta=-0.65, gamma=0.08)
    long_put = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                              strike=100, mark=107, position=+1, multiplier=100,
                              expiry=expiry, delta=-0.20, gamma=0.05)
    account = _make_account()
    report = _analyze_no_mdp([short_put, long_put], account)
    dim7 = [a for a in report.alerts if a.dimension == 7 and a.ticker == "NVDA"]
    assert len(dim7) >= 1
    assert dim7[0].level == "yellow"  # downgraded from red


def test_dim7_naked_short_put_still_red():
    """Naked ITM short put (no protection) must remain red."""
    expiry = (date.today() + timedelta(days=8)).strftime("%Y%m%d")
    short_put = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                               strike=110, mark=107, position=-1, multiplier=100,
                               expiry=expiry, delta=-0.65)
    account = _make_account()
    report = _analyze_no_mdp([short_put], account)
    dim7 = [a for a in report.alerts if a.dimension == 7 and a.ticker == "NVDA"]
    assert len(dim7) >= 1
    assert dim7[0].level == "red"


def test_dim8_spread_uses_net_premium():
    """Put spread cushion calculated on net premium — avoids false positive."""
    expiry = (date.today() + timedelta(days=17)).strftime("%Y%m%d")
    # Short 2 AAPL 177P, received $25 each, now worth $5.5 → 78% alone (would fire)
    short_put = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                               strike=177, position=-2, multiplier=100,
                               expiry=expiry, cost_basis=25.0, mark=5.5)
    # Long 2 AAPL 165P, paid $8 each, now worth $1.0
    long_put = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                              strike=165, position=+2, multiplier=100,
                              expiry=expiry, cost_basis=8.0, mark=1.0)
    account = _make_account()
    # Net received = 25 - 8 = 17, net current = 5.5 - 1.0 = 4.5
    # Realized % = (17 - 4.5) / 17 = 73.5% < 75% → no alert
    report = _analyze_no_mdp([short_put, long_put], account)
    dim8 = [a for a in report.alerts if a.dimension == 8 and a.ticker == "AAPL"]
    assert len(dim8) == 0


def test_dim8_spread_fires_when_net_pct_high():
    """Put spread cushion alert fires when net realized % > 75%."""
    expiry = (date.today() + timedelta(days=17)).strftime("%Y%m%d")
    # Short 2 AAPL 177P, received $25, now $1 → net realized very high
    short_put = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                               strike=177, position=-2, multiplier=100,
                               expiry=expiry, cost_basis=25.0, mark=1.0)
    long_put = _make_position(symbol="AAPL", asset_category="OPT", put_call="P",
                              strike=165, position=+2, multiplier=100,
                              expiry=expiry, cost_basis=8.0, mark=0.2)
    # Net received = 25 - 8 = 17, net current = 1.0 - 0.2 = 0.8
    # Realized % = (17 - 0.8) / 17 = 95% > 75% → alert
    account = _make_account()
    report = _analyze_no_mdp([short_put, long_put], account)
    dim8 = [a for a in report.alerts if a.dimension == 8 and a.ticker == "AAPL"]
    assert len(dim8) >= 1


def test_generate_risk_suggestion_no_key_uses_fallback():
    alert = RiskAlert(dimension=1, level="red", ticker="PORTFOLIO",
                      detail="Delta 120%", options=[])
    with patch("src.portfolio_risk._has_llm_key", return_value=False):
        result = generate_risk_suggestion(alert, {})
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# Phase 6 fixes: stress test formula, cash-like, FX, AI suggestions
# ---------------------------------------------------------------------------

def test_dim10_stk_uses_delta_one():
    """STK positions use delta=1.0 even when Flex reports delta=0 (stocks have no delta attr)."""
    stk = _make_position(symbol="AAPL", asset_category="STK",
                         position=100, mark=200, delta=0.0, multiplier=1)
    account = _make_account(nlv=10000)
    # 100 × $200 × beta=1.0 × 0.10 = $2,000 = 20% of NLV → red dim10
    report = _analyze_no_mdp([stk], account)
    stress = report.summary_stats["stress_test"]
    assert stress["drop_10pct"] < -1000
    assert any(a.dimension == 10 for a in report.alerts)


def test_dim10_opt_uses_underlying_price():
    """OPT stress loss uses underlying stock price, not tiny option premium."""
    stk = _make_position(symbol="NVDA", asset_category="STK",
                         position=1, mark=800, delta=0.0)
    opt = _make_position(symbol="NVDA", asset_category="OPT", put_call="P",
                         strike=750, position=-10, multiplier=100,
                         mark=5.0, delta=-0.25, underlying_symbol="NVDA")
    account = _make_account(nlv=20000)
    # OPT correct: 10 × 0.25 × 100 × $800 × 0.10 = $20,000
    # OPT wrong (option mark): 10 × 0.25 × 100 × $5 × 0.10 = $125
    report = _analyze_no_mdp([stk, opt], account)
    stress = report.summary_stats["stress_test"]
    assert abs(stress["drop_10pct"]) > 5000


def test_dim10_cash_like_zero_contribution():
    """SGOV contributes zero to stress loss (beta=0, cash substitute)."""
    sgov = _make_position(symbol="SGOV", asset_category="STK",
                          position=1000, mark=100, delta=0.0)
    account = _make_account(nlv=10000)
    # If beta=1 (wrong): 1000×100×0.10 = $10,000 = 100% NLV → red
    # If beta=0 (correct): $0 → no alert
    report = _analyze_no_mdp([sgov], account)
    stress = report.summary_stats["stress_test"]
    assert abs(stress["drop_10pct"]) < 100
    assert not any(a.dimension == 10 for a in report.alerts)


def test_dim5_skips_cash_like():
    """SGOV should not trigger concentration alerts (it's a cash substitute)."""
    sgov = _make_position(symbol="SGOV", asset_category="STK",
                          position=5000, mark=100)
    account = _make_account(nlv=100000)
    report = _analyze_no_mdp([sgov], account)
    dim5 = [a for a in report.alerts if a.dimension == 5]
    assert len(dim5) == 0


def test_dim1_hkd_position_fx_converted():
    """HKD position dollar delta is converted to USD before ratio check."""
    # 1000 shares at HKD 80 = HKD 80,000 ≈ USD 10,240 (at ~0.128)
    # USD 10,240 / USD 100,000 NLV = 10.2% → well below 80% → no dim1 alert
    hk = _make_position(symbol="CHT", asset_category="STK",
                        position=1000, mark=80, delta=0.0, currency="HKD")
    account = _make_account(nlv=100000)
    report = _analyze_no_mdp([hk], account)
    dim1 = [a for a in report.alerts if a.dimension == 1]
    assert len(dim1) == 0


def test_dim1_large_hkd_position_triggers_alert():
    """Large HKD portfolio still triggers dim1 alert after FX conversion."""
    # 10000 shares at HKD 800 = HKD 8,000,000 ≈ USD 1,024,000 >> USD 100,000 NLV → red
    hk = _make_position(symbol="CMB", asset_category="STK",
                        position=10000, mark=800, delta=0.0, currency="HKD")
    account = _make_account(nlv=100000)
    report = _analyze_no_mdp([hk], account)
    dim1 = [a for a in report.alerts if a.dimension == 1]
    assert len(dim1) == 1
    assert dim1[0].level == "red"
