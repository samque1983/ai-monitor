import pytest
from src.flex_client import PositionRecord, AccountSummary
from src.risk_pipeline import run_pipeline


def _make_naked_put():
    return PositionRecord(
        symbol="AAPL  260620P00180000", asset_category="OPT",
        put_call="P", strike=180.0, expiry="20260620", multiplier=100,
        position=-1, cost_basis_price=3.0, mark_price=2.0, unrealized_pnl=100.0,
        delta=-0.3, gamma=0.01, theta=-0.05, vega=0.1,
        underlying_symbol="AAPL", currency="USD",
    )


def _make_account():
    return AccountSummary(
        net_liquidation=100000.0, gross_position_value=5000.0,
        init_margin_req=2000.0, maint_margin_req=1500.0,
        excess_liquidity=29000.0, available_funds=29000.0, cushion=0.29,
    )


def test_run_pipeline_returns_report_and_html(monkeypatch):
    """run_pipeline returns (StrategyRiskReport, html_str) without calling LLM."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    report, html = run_pipeline(
        positions=[_make_naked_put()],
        account_summary=_make_account(),
        account_key="TEST",
        account_name="Test Account",
        llm_cfg={},
    )
    assert report.account_id == "TEST"
    assert isinstance(html, str)
    assert "<html" in html.lower()


def test_run_pipeline_enriches_missing_greeks(monkeypatch):
    """Positions with delta=0 get enriched (or stay 0 if provider unavailable)."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    pos = _make_naked_put()
    pos.delta = 0.0  # simulate missing Greeks
    report, _ = run_pipeline(
        positions=[pos],
        account_summary=_make_account(),
        account_key="TEST",
        account_name="Test Account",
        llm_cfg={},
    )
    # Pipeline should complete without error regardless of Greeks availability
    assert report is not None
