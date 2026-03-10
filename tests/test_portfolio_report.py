from src.portfolio_risk import RiskAlert, RiskReport
from src.portfolio_report import generate_html_report


def _make_report():
    alerts = [
        RiskAlert(dimension=4, level="red", ticker="ACCOUNT",
                  detail="cushion 8%", options=["A. 平仓", "B. 存现金"],
                  ai_suggestion="建议立即操作。"),
        RiskAlert(dimension=7, level="red", ticker="NVDA",
                  detail="NVDA P110 DTE 8天 已实值", options=["A. 平仓", "B. 接受指派"],
                  ai_suggestion=""),
        RiskAlert(dimension=5, level="yellow", ticker="AAPL",
                  detail="AAPL 38.5% NLV", options=["A. 减仓"], ai_suggestion=""),
    ]
    return RiskReport(
        account_id="alice",
        report_date="2026-03-10",
        net_liquidation=120000,
        total_pnl=3200,
        cushion=0.08,
        alerts=alerts,
        summary_stats={"stress_test": {"drop_10pct": -14300}},
    )


def test_html_contains_ticker_names():
    html = generate_html_report(_make_report())
    assert "NVDA" in html
    assert "AAPL" in html
    assert "ACCOUNT" in html


def test_html_contains_alert_level_colors():
    html = generate_html_report(_make_report())
    assert "red" in html.lower() or "#ff453a" in html
    assert "yellow" in html.lower() or "#ffd60a" in html


def test_html_contains_ai_suggestion():
    html = generate_html_report(_make_report())
    assert "建议立即操作" in html


def test_html_contains_summary_stats():
    html = generate_html_report(_make_report())
    assert "120,000" in html or "120000" in html
    assert "2026-03-10" in html


def test_html_is_valid_structure():
    html = generate_html_report(_make_report())
    assert html.startswith("<!DOCTYPE html>") or "<html" in html
    assert "</html>" in html
    assert "<body" in html
