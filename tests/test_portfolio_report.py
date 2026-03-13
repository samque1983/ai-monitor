from src.strategy_risk import StrategyRiskReport, StrategyRiskAlert
from src.portfolio_report import generate_html_report


def _make_report():
    alerts = [
        StrategyRiskAlert(rule_id=4, severity="red", urgency=True,
                          strategy_ref=None, underlying="ACCOUNT",
                          title="保证金危险", technical="cushion 8%",
                          plain="保证金不足。",
                          options=["A. 平仓", "B. 存现金"],
                          ai_suggestion="建议立即操作。"),
        StrategyRiskAlert(rule_id=1, severity="red", urgency=True,
                          strategy_ref=None, underlying="NVDA",
                          title="指派风险迫近", technical="NVDA P110 DTE 8天 已实值",
                          plain="期权快到期且已实值。",
                          options=["A. 平仓", "B. 接受指派"],
                          ai_suggestion=""),
        StrategyRiskAlert(rule_id=10, severity="yellow", urgency=False,
                          strategy_ref=None, underlying="AAPL",
                          title="集中度偏高", technical="AAPL 38.5% NLV",
                          plain="AAPL占比偏高。",
                          options=["A. 减仓"], ai_suggestion=""),
    ]
    return StrategyRiskReport(
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
    assert "yellow" in html.lower() or "#ffb340" in html


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


# ── Task 1: DTE bucket + strategy category ──────────────────────────────────
from src.portfolio_report import _dte_bucket, _STRATEGY_CATEGORY

def test_dte_bucket_boundaries():
    assert _dte_bucket(0)  == "无到期"
    assert _dte_bucket(1)  == "≤30天"
    assert _dte_bucket(30) == "≤30天"
    assert _dte_bucket(31) == "31–90天"
    assert _dte_bucket(90) == "31–90天"
    assert _dte_bucket(91) == ">90天"

def test_strategy_category_mapping():
    assert _STRATEGY_CATEGORY["Naked Put"]       == "裸卖"
    assert _STRATEGY_CATEGORY["Iron Condor"]     == "综合"
    assert _STRATEGY_CATEGORY["Bull Put Spread"] == "价差"
    assert _STRATEGY_CATEGORY["Covered Call"]    == "含股"
    assert _STRATEGY_CATEGORY["PMCC"]            == "跨期"
    assert _STRATEGY_CATEGORY["LEAPS Call"]      == "长期"
    assert _STRATEGY_CATEGORY["Long Put"]        == "单腿"
    assert _STRATEGY_CATEGORY["Unclassified"]    == "其他"
