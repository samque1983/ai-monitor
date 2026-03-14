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


# ── Task 2: _group_strategies ────────────────────────────────────────────────
from src.option_strategies import StrategyGroup
from src.portfolio_report import _group_strategies


def _make_sg(underlying="AAPL", strategy_type="Naked Put", intent="income",
             dte=45, net_pnl=100.0, net_theta=20.0, net_delta=-0.3,
             max_loss=500.0, net_vega=0.0, net_gamma=0.0, net_credit=100.0):
    sg = StrategyGroup(underlying=underlying, strategy_type=strategy_type, intent=intent)
    sg.dte = dte
    sg.net_pnl = net_pnl
    sg.net_theta = net_theta
    sg.net_delta = net_delta
    sg.max_loss = max_loss
    sg.net_vega = net_vega
    sg.net_gamma = net_gamma
    sg.net_credit = net_credit
    return sg


def test_group_strategies_intent():
    sgs = [
        _make_sg("AAPL", "Naked Put", "income"),
        _make_sg("TSLA", "Bull Put Spread", "income"),
        _make_sg("SPY", "Protective Put", "hedge"),
    ]
    groups = _group_strategies(sgs)
    assert "income" in groups["intent"]
    assert "hedge"  in groups["intent"]
    assert len(groups["intent"]["income"]) == 2
    assert len(groups["intent"]["hedge"])  == 1

def test_group_strategies_underlying():
    sgs = [
        _make_sg("AAPL", "Naked Put", "income"),
        _make_sg("AAPL", "Covered Call", "income"),
        _make_sg("SPY",  "Protective Put", "hedge"),
    ]
    groups = _group_strategies(sgs)
    assert len(groups["underlying"]["AAPL"]) == 2
    assert len(groups["underlying"]["SPY"])  == 1

def test_group_strategies_category():
    sgs = [
        _make_sg("AAPL", "Naked Put", "income"),
        _make_sg("TSLA", "Iron Condor", "income"),
    ]
    groups = _group_strategies(sgs)
    assert "裸卖" in groups["category"]
    assert "综合" in groups["category"]

def test_group_strategies_dte():
    sgs = [
        _make_sg(dte=15),
        _make_sg(dte=60),
        _make_sg(dte=200),
        _make_sg(dte=0),
    ]
    groups = _group_strategies(sgs)
    assert "≤30天"   in groups["dte"]
    assert "31–90天" in groups["dte"]
    assert ">90天"   in groups["dte"]
    assert "无到期"  in groups["dte"]

def test_group_strategies_empty():
    groups = _group_strategies([])
    assert groups["intent"]     == {}
    assert groups["underlying"] == {}
    assert groups["category"]   == {}
    assert groups["dte"]        == {}


# ── Task 3: _group_stats ─────────────────────────────────────────────────────
from src.portfolio_report import _group_stats


def test_group_stats_basic():
    sgs = [
        _make_sg(net_pnl=100, net_theta=20, net_delta=-0.3, max_loss=500),
        _make_sg(net_pnl=200, net_theta=30, net_delta=-0.5, max_loss=800),
    ]
    stats = _group_stats(sgs, nlv=100_000)
    assert stats["count"]      == 2
    assert stats["total_pnl"]  == 300.0
    assert stats["total_theta"] == 50.0
    assert stats["total_max_loss"] == 1300.0
    assert abs(stats["max_loss_pct"] - 1.3) < 0.01
    assert stats["has_naked"]  == False
    assert abs(stats["net_delta"] - (-0.8)) < 1e-6

def test_group_stats_naked():
    sgs = [
        _make_sg(max_loss=500),
        _make_sg(max_loss=None),   # naked — no max loss
    ]
    stats = _group_stats(sgs, nlv=100_000)
    assert stats["has_naked"]      == True
    assert stats["total_max_loss"] == 500.0   # only sum non-None

def test_group_stats_empty():
    stats = _group_stats([], nlv=100_000)
    assert stats["count"] == 0
    assert stats["total_pnl"] == 0.0


# ── Task 4: _group_subtitle ──────────────────────────────────────────────────
from src.portfolio_report import _group_subtitle


def _stats(count=2, pnl=100, theta=30, delta=-0.5,
           max_loss=1000, max_loss_pct=1.0, has_naked=False):
    return dict(count=count, total_pnl=pnl, total_theta=theta,
                net_delta=delta, total_max_loss=max_loss,
                max_loss_pct=max_loss_pct, has_naked=has_naked)

# intent tab
def test_subtitle_income_positive_theta():
    s = _group_subtitle("income", _stats(theta=48), dim="intent", nlv=100_000)
    assert "每天" in s and "48" in s

def test_subtitle_income_negative_theta():
    s = _group_subtitle("income", _stats(theta=-5), dim="intent", nlv=100_000)
    assert "Theta 为负" in s

def test_subtitle_hedge():
    s = _group_subtitle("hedge", _stats(theta=-12), dim="intent", nlv=100_000)
    assert "保险" in s

def test_subtitle_directional_long():
    s = _group_subtitle("directional", _stats(delta=2.0), dim="intent", nlv=100_000)
    assert "多头" in s

def test_subtitle_directional_short():
    s = _group_subtitle("directional", _stats(delta=-2.0), dim="intent", nlv=100_000)
    assert "空头" in s

def test_subtitle_high_risk_concentration():
    s = _group_subtitle("income", _stats(max_loss_pct=12.0), dim="intent", nlv=100_000)
    assert "最大亏损" in s and "12.0%" in s

def test_subtitle_naked_warning():
    s = _group_subtitle("income", _stats(has_naked=True), dim="intent", nlv=100_000)
    assert "裸 Call" in s and "无上限" in s

# dte tab
def test_subtitle_dte_expiring():
    s = _group_subtitle("≤30天", _stats(), dim="dte", nlv=100_000)
    assert "临近" in s or "Gamma" in s

def test_subtitle_dte_long():
    s = _group_subtitle(">90天", _stats(), dim="dte", nlv=100_000)
    assert "长线" in s or "Vega" in s


# ── Task 5: _render_group_header ─────────────────────────────────────────────
from src.portfolio_report import _render_group_header


def test_render_group_header_contains_key_data():
    sgs = [_make_sg(net_pnl=1240, net_theta=48, max_loss=6200)]
    html = _render_group_header(
        group_name="income", display_name="收租",
        strategies=sgs, dim="intent",
        nlv=150_000, color="#30d158"
    )
    assert "收租"   in html
    assert "1,240"  in html or "1240" in html
    assert "48"     in html
    # max_loss no longer shown in group header (misleading for mixed strategy groups)
    assert "最大亏损" not in html
    assert "靠卖出" in html   # subtitle present

def test_render_group_header_naked_warning():
    sgs = [_make_sg(max_loss=None)]
    html = _render_group_header(
        group_name="income", display_name="收租",
        strategies=sgs, dim="intent",
        nlv=150_000, color="#30d158"
    )
    # naked warning appears in subtitle text
    assert "裸 Call" in html or "裸Call" in html or "无上限" in html


# ── Task 6: _render_tabbed_summary ───────────────────────────────────────────
from src.portfolio_report import _render_tabbed_summary


def test_tabbed_summary_contains_four_tabs():
    sgs = [
        _make_sg("AAPL", "Naked Put", "income", dte=30),
        _make_sg("TSLA", "Protective Put", "hedge", dte=60),
    ]
    html = _render_tabbed_summary(sgs, nlv=100_000)
    assert 'data-tab="intent"'     in html
    assert 'data-tab="underlying"' in html
    assert 'data-tab="category"'   in html
    assert 'data-tab="dte"'        in html

def test_tabbed_summary_first_tab_active():
    sgs = [_make_sg()]
    html = _render_tabbed_summary(sgs, nlv=100_000)
    # first tab-panel has class active
    assert 'id="tab-intent"' in html
    # active class appears before second panel
    intent_pos = html.index('id="tab-intent"')
    underlying_pos = html.index('id="tab-underlying"')
    assert intent_pos < underlying_pos

def test_tabbed_summary_empty_returns_empty():
    html = _render_tabbed_summary([], nlv=100_000)
    assert html == ""

def test_tabbed_summary_contains_underlying_name():
    sgs = [_make_sg("NVDA", "Naked Put", "income", dte=20)]
    html = _render_tabbed_summary(sgs, nlv=100_000)
    assert "NVDA" in html

def test_tabbed_summary_js_switch_function():
    sgs = [_make_sg()]
    html = _render_tabbed_summary(sgs, nlv=100_000)
    assert "tab-btn" in html
    assert "tab-panel" in html
    assert "classList" in html   # JS is present


# ── Task 7: integration — tabbed summary wired into generate_html_report ─────
def _make_report_with_strategies():
    """Report with real StrategyGroup objects."""
    from src.option_strategies import StrategyGroup
    sg1 = _make_sg("AAPL", "Naked Put",      "income",      dte=25, net_pnl=400, net_theta=35, max_loss=3000)
    sg2 = _make_sg("TSLA", "Iron Condor",    "income",      dte=50, net_pnl=200, net_theta=28, max_loss=2000)
    sg3 = _make_sg("SPY",  "Protective Put", "hedge",       dte=80, net_pnl=-50, net_theta=-8, max_loss=800)

    report = _make_report()    # existing helper from top of file
    report.strategies = [sg1, sg2, sg3]
    return report

def test_html_report_with_strategies_has_tabs():
    html = generate_html_report(_make_report_with_strategies())
    assert 'data-tab="intent"'     in html
    assert 'data-tab="underlying"' in html
    assert 'tab-panel'             in html

def test_html_report_with_strategies_shows_underlyings():
    html = generate_html_report(_make_report_with_strategies())
    assert "AAPL" in html
    assert "TSLA" in html
    assert "SPY"  in html

def test_html_report_no_strategies_no_tabs():
    report = _make_report()
    report.strategies = []
    html = generate_html_report(report)
    assert 'class="strat-tabs"' not in html


# ── Bug fixes ────────────────────────────────────────────────────────────────

def test_strategy_card_expiry_formatted():
    """Legs summary must show formatted expiry (YYYY-MM-DD), not raw YYYYMMDD."""
    from src.portfolio_report import _strategy_card
    from src.flex_client import PositionRecord
    from src.option_strategies import StrategyGroup
    p = PositionRecord(
        symbol="QQQ   P78", asset_category="OPT", put_call="P",
        strike=78, expiry="20260330", multiplier=100, position=-7,
        cost_basis_price=2.0, mark_price=2.0, unrealized_pnl=0.0,
        delta=-0.3, gamma=0.01, theta=0.05, vega=0.1,
        underlying_symbol="QQQ", currency="USD",
    )
    sg = StrategyGroup(underlying="QQQ", strategy_type="Naked Put", intent="income")
    sg.legs = [p]
    sg.dte = 16
    sg.net_delta = 210.0
    sg.net_theta = 35.0
    sg.net_vega = -70.0
    sg.net_gamma = -7.0
    sg.net_credit = 1400.0
    html = _strategy_card(sg)
    assert "20260330" not in html, "Raw YYYYMMDD expiry must not appear in card"
    assert "2026-03-30" in html, "Formatted expiry YYYY-MM-DD must appear in card"


def test_strategy_card_delta_uses_underlying_price():
    """Delta display must use underlying_price for per-1%-move calc, not hardcoded $100."""
    from src.portfolio_report import _strategy_card
    from src.flex_client import PositionRecord
    from src.option_strategies import StrategyGroup
    p = PositionRecord(
        symbol="AAPL  P180", asset_category="OPT", put_call="P",
        strike=180, expiry="20261201", multiplier=100, position=-1,
        cost_basis_price=3.0, mark_price=2.0, unrealized_pnl=0.0,
        delta=-0.3, gamma=0.01, theta=0.05, vega=0.1,
        underlying_symbol="AAPL", currency="USD",
    )
    sg = StrategyGroup(underlying="AAPL", strategy_type="Naked Put", intent="income")
    sg.legs = [p]
    sg.dte = 45
    sg.net_delta = 30.0        # -0.3 * -1 * 100 = 30
    sg.net_theta = 5.0
    sg.net_vega = -10.0
    sg.net_gamma = -1.0
    sg.net_credit = 300.0
    sg.underlying_price = 195.0  # stock at $195, not $100
    html = _strategy_card(sg)
    # Δ per 1% = 30 * 195 * 0.01 = $58.5 → rounds to $59, NOT $30 (hardcoded $100 would give $30)
    assert "+$59" in html or "+$58" in html, \
        "Delta display must use underlying_price ($195), not hardcoded $100"
    assert "+$30" not in html, "Should NOT show net_delta directly (hardcoded $100 formula)"


def test_short_strangle_card_shows_downside_max_loss():
    """Short strangle card must show '↓ -$X | ↑ 无限制' for max_loss when max_loss_downside is set."""
    from src.portfolio_report import _strategy_card
    from src.flex_client import PositionRecord
    from src.option_strategies import StrategyGroup
    sc = PositionRecord(
        symbol="NVDA  C240", asset_category="OPT", put_call="C",
        strike=240, expiry="20260618", multiplier=100, position=-2,
        cost_basis_price=5.0, mark_price=4.0, unrealized_pnl=0.0,
        delta=0.3, gamma=0.01, theta=-0.05, vega=0.1,
        underlying_symbol="NVDA", currency="USD",
    )
    sp = PositionRecord(
        symbol="NVDA  P148", asset_category="OPT", put_call="P",
        strike=148, expiry="20260618", multiplier=100, position=-1,
        cost_basis_price=3.0, mark_price=2.5, unrealized_pnl=0.0,
        delta=-0.2, gamma=0.01, theta=-0.04, vega=0.08,
        underlying_symbol="NVDA", currency="USD",
    )
    sg = StrategyGroup(underlying="NVDA", strategy_type="Strangle", intent="speculation")
    sg.legs = [sc, sp]
    sg.dte = 96
    sg.net_delta = -40.0
    sg.net_theta = 14.0
    sg.net_vega = -28.0
    sg.net_gamma = -3.0
    sg.net_credit = 1300.0
    sg.max_profit = 1300.0
    sg.max_loss = None           # unlimited (call side)
    sg.max_loss_downside = 13500.0  # put floor: stock → $0
    sg.underlying_price = 160.0
    html = _strategy_card(sg)
    assert "13,500" in html, "Downside max loss amount must appear in card"
    assert "无限制" in html, "Upside unlimited text must appear in card"
    assert "↓" in html or "↑" in html, "Directional arrows must appear in split max_loss display"


def test_group_header_theta_negative_sign_format():
    """Group header theta must format as '-$45/天' not '$-45/天' when negative."""
    from src.portfolio_report import _render_group_header
    sg = _make_sg(net_theta=-45.0, net_pnl=100.0)
    html = _render_group_header("income", "收租", [sg], "intent", nlv=100_000, color="#30d158")
    assert "$-45" not in html, "Sign must precede $, not follow it"
    assert "-$45" in html, "Negative theta must render as -$45/天"
