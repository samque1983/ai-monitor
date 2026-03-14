"""Tests for OptionStrategyRecognizer and StrategyGroup."""
import pytest
from datetime import date, timedelta
from src.option_strategies import StrategyGroup, OptionStrategyRecognizer
from src.flex_client import PositionRecord


def _opt(symbol, put_call, strike, position, expiry="20261201",
         multiplier=100, delta=0.0, cost_basis=3.0, mark=2.0,
         underlying="AAPL", currency="USD"):
    return PositionRecord(
        symbol=symbol, asset_category="OPT", put_call=put_call,
        strike=strike, expiry=expiry, multiplier=multiplier, position=position,
        cost_basis_price=cost_basis, mark_price=mark, unrealized_pnl=0.0,
        delta=delta, gamma=0.01, theta=-0.05, vega=0.1,
        underlying_symbol=underlying, currency=currency,
    )


def _stk(symbol, position, mark=150.0, currency="USD"):
    return PositionRecord(
        symbol=symbol, asset_category="STK", put_call="",
        strike=0, expiry="", multiplier=1, position=position,
        cost_basis_price=140.0, mark_price=mark, unrealized_pnl=0.0,
        delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
        underlying_symbol="", currency=currency,
    )


def test_strategy_group_defaults():
    sg = StrategyGroup(underlying="AAPL", strategy_type="Naked Put", intent="income")
    assert sg.max_profit is None
    assert sg.max_loss is None
    assert sg.breakevens == []
    assert sg.legs == []
    assert sg.modifiers == []
    assert sg.currency == "USD"


def test_naked_put_recognition():
    p = _opt("AAPL  261201P00180000", "P", 180, -5, delta=-0.3)
    groups = OptionStrategyRecognizer().recognize([p])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Naked Put"
    assert groups[0].intent == "income"
    assert groups[0].underlying == "AAPL"


def test_long_stock_recognition():
    s = _stk("AAPL", position=100, mark=182.0)
    groups = OptionStrategyRecognizer().recognize([s])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Long Stock"
    assert groups[0].intent == "directional"


def test_long_put_recognition():
    p = _opt("AAPL  261201P00170000", "P", 170, 5, delta=-0.2)
    groups = OptionStrategyRecognizer().recognize([p])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Long Put"
    assert groups[0].intent == "speculation"


def test_bull_put_spread():
    short_p = _opt("AAPL  261201P00180000", "P", 180, -5, delta=-0.3)
    long_p = _opt("AAPL  261201P00170000", "P", 170, 5, delta=-0.2)
    groups = OptionStrategyRecognizer().recognize([short_p, long_p])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Bull Put Spread"
    assert g.intent == "income"
    assert len(g.legs) == 2


def test_covered_call():
    stock = _stk("AAPL", 100)
    call = _opt("AAPL  261201C00200000", "C", 200, -1, delta=0.3)
    groups = OptionStrategyRecognizer().recognize([stock, call])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Covered Call"
    assert groups[0].stock_leg is not None


def test_protective_put():
    stock = _stk("AAPL", 100)
    put = _opt("AAPL  261201P00160000", "P", 160, 1, delta=-0.2)
    groups = OptionStrategyRecognizer().recognize([stock, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Protective Put"


def test_straddle():
    call = _opt("AAPL  261201C00180000", "C", 180, -3, delta=0.5)
    put = _opt("AAPL  261201P00180000", "P", 180, -3, delta=-0.5)
    groups = OptionStrategyRecognizer().recognize([call, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Straddle"


def test_strangle():
    call = _opt("AAPL  261201C00200000", "C", 200, -3, delta=0.3)
    put = _opt("AAPL  261201P00160000", "P", 160, -3, delta=-0.3)
    groups = OptionStrategyRecognizer().recognize([call, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Strangle"


def test_calendar_spread():
    near = _opt("AAPL  261201P00180000", "P", 180, -3, expiry="20261201")
    far = _opt("AAPL  270319P00180000", "P", 180, 3, expiry="20270319")
    groups = OptionStrategyRecognizer().recognize([near, far])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Calendar Spread"


def test_protective_modifier_attached():
    """Bull Put Spread + extra lower long put → modifier attached, not separate strategy."""
    sp = _opt("AAPL  261201P00180000", "P", 180, -5)
    lp = _opt("AAPL  261201P00170000", "P", 170, 5)
    tail = _opt("AAPL  261201P00150000", "P", 150, 2)  # tail hedge
    groups = OptionStrategyRecognizer().recognize([sp, lp, tail])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Bull Put Spread"
    assert len(groups[0].modifiers) == 1
    assert groups[0].modifiers[0].strike == 150


def test_metrics_net_credit():
    """net_credit > 0 for income strategy (received more than paid)."""
    sp = _opt("AAPL  261201P00180000", "P", 180, -5, cost_basis=3.0, multiplier=100)
    lp = _opt("AAPL  261201P00170000", "P", 170, 5, cost_basis=1.5, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    g = groups[0]
    # net_credit = 5*3.0*100 - 5*1.5*100 = 1500 - 750 = 750
    assert g.net_credit == 750.0


def test_metrics_max_loss_spread():
    """Bull Put Spread max_loss = (spread_width - net_credit_per_contract) × contracts."""
    sp = _opt("AAPL  261201P00180000", "P", 180, -5, cost_basis=3.0, multiplier=100)
    lp = _opt("AAPL  261201P00170000", "P", 170, 5, cost_basis=1.5, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    g = groups[0]
    # spread_width=10, net_credit=750, contracts=5
    # credit_per_contract = 750 / 5 / 100 = 1.5
    # max_loss = (10 - 1.5) * 100 * 5 = 4250
    assert g.max_loss == pytest.approx(4250.0)
    assert g.max_profit == pytest.approx(750.0)


def test_pmcc_recognition():
    """Short near-term call + long LEAPS call (DTE > 365) → PMCC, intent=income."""
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    short_c = _opt("AAPL  C250", "C", 250, -1, expiry=near_exp, delta=0.3)
    long_c  = _opt("AAPL  C140", "C", 140,  1, expiry=far_exp,  delta=0.8)
    groups = OptionStrategyRecognizer().recognize([short_c, long_c])
    assert len(groups) == 1
    assert groups[0].strategy_type == "PMCC"
    assert groups[0].intent == "income"


def test_leaps_call_recognition():
    """Standalone long call with DTE > 365 → LEAPS Call."""
    from datetime import date, timedelta
    far_exp = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    p = _opt("AAPL  C140", "C", 140, 1, expiry=far_exp, delta=0.8)
    groups = OptionStrategyRecognizer().recognize([p])
    assert len(groups) == 1
    assert groups[0].strategy_type == "LEAPS Call"
    assert groups[0].intent == "speculation"


def test_leaps_put_recognition():
    """Standalone long put with DTE > 365 → LEAPS Put."""
    from datetime import date, timedelta
    far_exp = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    p = _opt("AAPL  P200", "P", 200, 1, expiry=far_exp, delta=-0.7)
    groups = OptionStrategyRecognizer().recognize([p])
    assert len(groups) == 1
    assert groups[0].strategy_type == "LEAPS Put"
    assert groups[0].intent == "hedge"


def test_leaps_not_consumed_as_modifier():
    """LEAPS long put paired with short put → Diagonal Spread (visible), not hidden modifier."""
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    naked_put = _opt("AAPL  P180", "P", 180, -5, expiry=near_exp)
    leaps_put = _opt("AAPL  P140", "P", 140,  2, expiry=far_exp)
    groups = OptionStrategyRecognizer().recognize([naked_put, leaps_put])
    # Short near + long LEAPS put → Diagonal Spread (paired, both visible)
    assert len(groups) == 1
    assert groups[0].strategy_type == "Diagonal Spread"


def test_consolidate_deduplicates_flex_duplicates():
    """Identical rows (same contract + same position) are deduplicated, not doubled."""
    # IBKR Flex often returns each position twice with identical data
    sp1 = _opt("AVGO  P260", "P", 260, -6, underlying="AVGO")
    sp2 = _opt("AVGO  P260", "P", 260, -6, underlying="AVGO")  # exact duplicate
    lp1 = _opt("AVGO  P125", "P", 125,  6, underlying="AVGO")
    lp2 = _opt("AVGO  P125", "P", 125,  6, underlying="AVGO")  # exact duplicate
    groups = OptionStrategyRecognizer().recognize([sp1, sp2, lp1, lp2])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Bull Put Spread"
    short_leg = next(p for p in g.legs if p.position < 0)
    long_leg  = next(p for p in g.legs if p.position > 0)
    assert short_leg.position == -6   # not -12
    assert long_leg.position == 6     # not 12


def test_ratio_put_spread_multi_lot():
    """Different-sized lots of short put + different-quantity long put → Ratio Put Spread."""
    # Short entered in two lots (-6 and -2), long in one lot (+6); Flex duplicates each
    sp1 = _opt("AVGO  P260", "P", 260, -6, underlying="AVGO")
    sp2 = _opt("AVGO  P260", "P", 260, -6, underlying="AVGO")  # duplicate of sp1
    sp3 = _opt("AVGO  P260", "P", 260, -2, underlying="AVGO")  # separate lot
    sp4 = _opt("AVGO  P260", "P", 260, -2, underlying="AVGO")  # duplicate of sp3
    lp1 = _opt("AVGO  P125", "P", 125,  6, underlying="AVGO")
    lp2 = _opt("AVGO  P125", "P", 125,  6, underlying="AVGO")  # duplicate of lp1
    groups = OptionStrategyRecognizer().recognize([sp1, sp2, sp3, sp4, lp1, lp2])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Ratio Put Spread"
    short_leg = next(p for p in g.legs if p.position < 0)
    long_leg  = next(p for p in g.legs if p.position > 0)
    assert short_leg.position == -8   # -6 + -2 (after dedup)
    assert long_leg.position == 6     # 6 (after dedup)


def test_ratio_put_spread_equal_becomes_bull_put():
    """Equal quantities after consolidation → Bull Put Spread (not Ratio)."""
    sp1 = _opt("AAPL  P180", "P", 180, -3)
    sp2 = _opt("AAPL  P180", "P", 180, -2)
    sp3 = _opt("AAPL  P180", "P", 180, -3)  # duplicate of sp1
    sp4 = _opt("AAPL  P180", "P", 180, -2)  # duplicate of sp2
    lp1 = _opt("AAPL  P170", "P", 170,  4)
    lp2 = _opt("AAPL  P170", "P", 170,  1)
    lp3 = _opt("AAPL  P170", "P", 170,  4)  # duplicate of lp1
    lp4 = _opt("AAPL  P170", "P", 170,  1)  # duplicate of lp2
    groups = OptionStrategyRecognizer().recognize([sp1, sp2, sp3, sp4, lp1, lp2, lp3, lp4])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Bull Put Spread"
    short_leg = next(p for p in g.legs if p.position < 0)
    long_leg  = next(p for p in g.legs if p.position > 0)
    assert short_leg.position == -5   # -3 + -2 (after dedup)
    assert long_leg.position == 5     # +4 + +1 (after dedup)


def test_naked_put_max_loss_bounded():
    """Naked Put max_loss is bounded: stock can only fall to $0.
    max_loss = (strike - credit_per_contract) × mult × |contracts|
    """
    # -3 contracts, strike=180, cost_basis=4.0 → net_credit = 3*4*100 = 1200
    # credit_per_contract = 1200 / 3 / 100 = 4.0
    # max_loss = (180 - 4) * 100 * 3 = 52800
    sp = _opt("AAPL  261201P00180000", "P", 180, -3, cost_basis=4.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp])
    g = groups[0]
    assert g.strategy_type == "Naked Put"
    assert g.max_loss is not None, "Naked Put max_loss must be finite (stock floors at $0)"
    assert g.max_loss == pytest.approx(52800.0)
    assert g.max_profit == pytest.approx(1200.0)


def test_naked_call_max_loss_unlimited():
    """Naked Call max_loss remains None — stock can rise without bound."""
    sc = _opt("AAPL  261201C00220000", "C", 220, -2, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc])
    g = groups[0]
    assert g.strategy_type == "Naked Call"
    assert g.max_loss is None, "Naked Call max_loss must be None (unlimited upside risk)"


def test_covered_call_max_loss_bounded():
    """Covered Call max_loss bounded: stock goes to $0.
    max_loss = cost_basis × shares - net_credit
    """
    # 100 shares cost_basis=140, sell 1 call cost_basis=3.0
    # net_credit = 1 * 3.0 * 100 = 300
    # max_loss = 140 * 100 - 300 = 13700
    stock = _stk("AAPL", 100, mark=150.0)   # cost_basis=140 in _stk helper
    call = _opt("AAPL  261201C00200000", "C", 200, -1, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([stock, call])
    g = groups[0]
    assert g.strategy_type == "Covered Call"
    assert g.max_loss is not None, "Covered Call max_loss must be finite"
    assert g.max_loss == pytest.approx(13700.0)


def test_naked_put_with_long_put_modifier_caps_max_loss():
    """Naked Put + cross-expiry Long Put modifier → max_loss capped by modifier strike.
    Effective max_loss = (short_strike - modifier_strike - credit_per_contract) × mult × contracts
    """
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=80)).strftime("%Y%m%d")
    sp = _opt("AAPL  P180", "P", 180, -2, expiry=near_exp, cost_basis=4.0, multiplier=100)
    lp = _opt("AAPL  P160", "P", 160,  2, expiry=far_exp,  cost_basis=1.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    # These are cross-expiry, should be a Diagonal Spread (not Naked Put + modifier)
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Diagonal Spread"
    # Diagonal spread max_loss should be bounded by the net debit / credit spread width
    assert g.max_loss is not None, "Diagonal Spread max_loss must be finite"


def test_leaps_standalone_not_modifier():
    """Standalone LEAPS put (can't be paired) stays as its own strategy, not a modifier."""
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    # Same-expiry bull put spread + unrelated LEAPS put on different expiry
    sp  = _opt("AAPL  P180", "P", 180, -5, expiry=near_exp)
    lp  = _opt("AAPL  P170", "P", 170,  5, expiry=near_exp)
    leaps_put = _opt("AAPL  P140", "P", 140, 2, expiry=far_exp)
    groups = OptionStrategyRecognizer().recognize([sp, lp, leaps_put])
    # Bull Put Spread + LEAPS Put (not consumed as modifier)
    assert len(groups) == 2
    types = {g.strategy_type for g in groups}
    assert "Bull Put Spread" in types
    assert "LEAPS Put" in types


def test_ratio_put_spread_uncovered_max_loss_bounded():
    """Ratio Put Spread with uncovered shorts must have finite max_loss.
    Stock floors at $0, so max loss = short_qty*short_strike - long_qty*long_strike - net_credit.
    Example: sell 2 puts @50, buy 1 put @45, each 1 lot, mult=100
    net_credit = 2*2.0*100 - 1*1.0*100 = 300
    max_loss = (2*50 - 1*45)*100 - 300 = 5500 - 300 = 5200
    """
    sp = _opt("AAPL  P050", "P", 50, -2, cost_basis=2.0, multiplier=100)
    lp = _opt("AAPL  P045", "P", 45,  1, cost_basis=1.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Ratio Put Spread"
    assert g.max_loss is not None, "Ratio Put Spread max_loss must be finite (stock floors at $0)"
    assert g.max_loss == pytest.approx(5200.0)


def test_ratio_call_spread_uncovered_max_loss_unlimited():
    """Ratio Call Spread with uncovered shorts must remain max_loss=None (truly unlimited)."""
    sc = _opt("AAPL  C220", "C", 220, -2, cost_basis=2.0, multiplier=100)
    lc = _opt("AAPL  C230", "C", 230,  1, cost_basis=1.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc, lc])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Ratio Call Spread"
    assert g.max_loss is None, "Ratio Call Spread with uncovered calls: unlimited upside risk"


def test_pmcc_max_loss_bounded():
    """PMCC (short near-term call + long LEAPS call) max_loss must be finite."""
    near_exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    sc = _opt("AAPL  C250", "C", 250, -1, expiry=near_exp, cost_basis=3.0, multiplier=100)
    lc = _opt("AAPL  C140", "C", 140,  1, expiry=far_exp,  cost_basis=10.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc, lc])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "PMCC"
    assert g.max_loss is not None, "PMCC max_loss must be finite (bounded by net debit)"
    # net_credit = 1*3.0*100 - 1*10.0*100 = -700 (net debit)
    assert g.max_loss == pytest.approx(700.0)


def test_long_call_max_loss_bounded():
    """Long Call max_loss = debit paid (not None)."""
    lc = _opt("AAPL  C200", "C", 200, 1, cost_basis=5.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([lc])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type in ("Long Call", "LEAPS Call")
    assert g.max_loss is not None, "Long Call max_loss must be finite (= premium paid)"
    assert g.max_loss == pytest.approx(500.0)


def test_long_put_max_loss_bounded():
    """Long Put max_loss = debit paid (not None)."""
    lp = _opt("AAPL  P180", "P", 180, 1, cost_basis=4.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([lp])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type in ("Long Put", "LEAPS Put")
    assert g.max_loss is not None, "Long Put max_loss must be finite (= premium paid)"
    assert g.max_loss == pytest.approx(400.0)


def test_covered_call_multi_expiry_not_naked():
    """200 shares + 2 short calls at different expiries → 2 Covered Calls, NOT 1 CC + 1 Naked Call.
    Common scenario: rolling a CC while still holding the old leg.
    """
    stk = PositionRecord("AAPL","STK","",0,"",1,200,140.0,150.0,0.0,1.0,0.0,0.0,0.0,"","USD")
    sc1 = _opt("AAPL C200","C",200,-1,expiry="20260320",cost_basis=3.0)
    sc2 = _opt("AAPL C205","C",205,-1,expiry="20260417",cost_basis=2.5)
    groups = OptionStrategyRecognizer().recognize([stk, sc1, sc2])
    types = [g.strategy_type for g in groups]
    assert "Naked Call" not in types, f"Short call misidentified as Naked Call: {types}"
    assert types.count("Covered Call") == 2, f"Expected 2 Covered Calls, got: {types}"
    for g in groups:
        if g.strategy_type == "Covered Call":
            assert g.max_loss is not None, "Covered Call max_loss must be finite"


def test_long_stock_max_loss_bounded():
    """Long Stock max_loss = cost_basis × shares (stock floors at $0)."""
    s = PositionRecord("AAPL","STK","",0,"",1,100,140.0,150.0,0.0,1.0,0.0,0.0,0.0,"","USD")
    groups = OptionStrategyRecognizer().recognize([s])
    g = groups[0]
    assert g.strategy_type == "Long Stock"
    assert g.max_loss is not None, "Long Stock max_loss must be finite"
    assert g.max_loss == pytest.approx(14000.0)  # 140 * 100


def test_short_stock_max_loss_unlimited():
    """Short Stock max_loss = None (stock can rise without bound)."""
    s = PositionRecord("AAPL","STK","",0,"",1,-100,140.0,150.0,0.0,-1.0,0.0,0.0,0.0,"","USD")
    groups = OptionStrategyRecognizer().recognize([s])
    g = groups[0]
    assert g.strategy_type == "Short Stock"
    assert g.max_loss is None, "Short Stock max_loss must be None (unlimited upside risk)"


def test_protective_put_max_loss_bounded():
    """Protective Put: max_loss capped at (basis - put_strike)*shares + premium_paid.
    100 shares @ 150 basis, long put @ 140, premium 3.0/share → net_credit = -300
    max_loss = (150 - 140)*100 + 300 = 1300
    """
    s = PositionRecord("AAPL","STK","",0,"",1,100,150.0,155.0,0.0,1.0,0.0,0.0,0.0,"","USD")
    lp = _opt("AAPL  P140","P",140,1,cost_basis=3.0,multiplier=100)
    groups = OptionStrategyRecognizer().recognize([s, lp])
    g = groups[0]
    assert g.strategy_type == "Protective Put"
    assert g.max_loss is not None, "Protective Put max_loss must be finite"
    assert g.max_loss == pytest.approx(1300.0)


def test_collar_max_loss_bounded():
    """Collar: max_loss = (basis - put_strike)*shares - net_credit.
    100 shares @ 150 basis, sell call @ 160 (premium 4.0), buy put @ 140 (premium 2.0)
    net_credit = 4*100 - 2*100 = 200
    max_loss = (150 - 140)*100 - 200 = 800
    """
    s  = PositionRecord("AAPL","STK","",0,"",1,100,150.0,155.0,0.0,1.0,0.0,0.0,0.0,"","USD")
    sc = _opt("AAPL  C160","C",160,-1,cost_basis=4.0,multiplier=100)
    lp = _opt("AAPL  P140","P",140, 1,cost_basis=2.0,multiplier=100)
    groups = OptionStrategyRecognizer().recognize([s, sc, lp])
    g = groups[0]
    assert g.strategy_type == "Collar"
    assert g.max_loss is not None, "Collar max_loss must be finite"
    assert g.max_loss == pytest.approx(800.0)


def test_collar_max_profit_bounded():
    """Collar max_profit = (sc_strike - basis) * shares + net_credit (capped upside).
    100 shares @ 150 basis, sell call @ 160 (premium 4.0), buy put @ 140 (premium 2.0)
    net_credit = 200; max_profit = (160 - 150)*100 + 200 = 1200
    """
    s  = PositionRecord("AAPL","STK","",0,"",1,100,150.0,155.0,0.0,1.0,0.0,0.0,0.0,"","USD")
    sc = _opt("AAPL  C160","C",160,-1,cost_basis=4.0,multiplier=100)
    lp = _opt("AAPL  P140","P",140, 1,cost_basis=2.0,multiplier=100)
    groups = OptionStrategyRecognizer().recognize([s, sc, lp])
    g = groups[0]
    assert g.strategy_type == "Collar"
    assert g.max_profit is not None, "Collar max_profit must be finite (capped at short call strike)"
    assert g.max_profit == pytest.approx(1200.0)


def test_pmcc_max_profit_bounded():
    """PMCC max_profit should be bounded by spread width.
    short call @ 250, long LEAPS call @ 140 → strike_diff = 110
    net_credit = 3*100 - 10*100 = -700 (debit)
    max_profit = 110*100 + (-700) = 10300
    """
    near_exp = (date.today() + timedelta(days=60)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=400)).strftime("%Y%m%d")
    sc = _opt("AAPL  C250", "C", 250, -1, expiry=near_exp, cost_basis=3.0, multiplier=100)
    lc = _opt("AAPL  C140", "C", 140,  1, expiry=far_exp,  cost_basis=10.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc, lc])
    g = groups[0]
    assert g.strategy_type == "PMCC"
    assert g.max_profit is not None, "PMCC max_profit must be finite (bounded by spread width)"
    assert g.max_profit == pytest.approx(10300.0)


def test_covered_call_zero_cost_basis_uses_mark_price():
    """Covered Call with cost_basis=0 should fall back to mark_price to avoid negative max_loss."""
    stk = PositionRecord(
        symbol="AAPL", asset_category="STK", put_call="",
        strike=0, expiry="", multiplier=1, position=100,
        cost_basis_price=0.0, mark_price=150.0, unrealized_pnl=0.0,
        delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
        underlying_symbol="", currency="USD",
    )
    sc = _opt("AAPL  C200", "C", 200, -1, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([stk, sc])
    g = groups[0]
    assert g.strategy_type == "Covered Call"
    assert g.max_loss is not None
    assert g.max_loss > 0, "Covered Call max_loss must be positive even when cost_basis=0"
    # max_loss = mark_price * shares - net_credit = 150*100 - 300 = 14700
    assert g.max_loss == pytest.approx(14700.0)


def test_all_short_diagonal_has_finite_max_profit_and_loss():
    """Two short puts at different strikes/expirations → Diagonal Spread.
    Both max_profit and max_loss must be finite (not None/unlimited).
    max_profit = net_credit; max_loss = total notional - net_credit.
    """
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=16)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=107)).strftime("%Y%m%d")
    # Short 7× P78 near-term @ $2 premium, Short 5× P75 far-term @ $3 premium
    sp_near = _opt("QQQ   P78",  "P", 78, -7, expiry=near_exp, cost_basis=2.0, multiplier=100)
    sp_far  = _opt("QQQ   P75",  "P", 75, -5, expiry=far_exp,  cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp_near, sp_far])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Diagonal Spread"
    # net_credit = 7*2*100 + 5*3*100 = 1400 + 1500 = 2900
    assert g.net_credit == pytest.approx(2900.0)
    # max_profit must be finite and equal to net_credit
    assert g.max_profit is not None, "All-short Diagonal max_profit must be finite (not unlimited)"
    assert g.max_profit == pytest.approx(2900.0)
    # max_loss must be finite: notional - net_credit = (7*78 + 5*75)*100 - 2900
    # = (546 + 375)*100 - 2900 = 92100 - 2900 = 89200
    assert g.max_loss is not None, "All-short Diagonal max_loss must be finite (not unlimited)"
    assert g.max_loss == pytest.approx(89200.0)


def test_short_stock_max_profit_bounded():
    """Short Stock: max_profit must be finite (stock → $0), not None/unlimited."""
    s = _stk("TSLA", position=-100, mark=200.0)
    # cost_basis_price=140 per _stk default — represents the short-sell price
    groups = OptionStrategyRecognizer().recognize([s])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Short Stock"
    assert g.max_profit is not None, "Short Stock max_profit must be finite (stock can only fall to $0)"
    # max_profit = cost_basis * |position| = 140 * 100 = 14000
    assert g.max_profit == pytest.approx(14000.0)
    assert g.max_loss is None  # stock can rise without bound


def test_all_long_diagonal_max_loss_bounded():
    """Two long puts at different strikes/expirations → Diagonal Spread.
    max_loss must be finite (= net debit paid), not None/unlimited.
    """
    from datetime import date, timedelta
    near_exp = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    far_exp  = (date.today() + timedelta(days=90)).strftime("%Y%m%d")
    # Long 3× P100 near @ $4, Long 3× P95 far @ $2 — net debit = 3*(4+2)*100 = 1800
    lp_near = _opt("SPY   P100", "P", 100, +3, expiry=near_exp, cost_basis=4.0, multiplier=100)
    lp_far  = _opt("SPY   P95",  "P",  95, +3, expiry=far_exp,  cost_basis=2.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([lp_near, lp_far])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Diagonal Spread"
    # net_credit = -(3*4*100 + 3*2*100) = -1800 (net debit)
    assert g.net_credit == pytest.approx(-1800.0)
    # max_loss must be finite and equal to the net debit paid
    assert g.max_loss is not None, "All-long Diagonal max_loss must be finite (= net debit paid)"
    assert g.max_loss == pytest.approx(1800.0)


def test_underlying_price_set_for_pure_option_strategy():
    """StrategyGroup.underlying_price should be populated for pure option positions.
    When PositionRecord.underlying_price == 0, falls back to the leg's strike.
    """
    sp = _opt("AAPL  P180", "P", 180, -1, cost_basis=3.0, multiplier=100)
    # _opt sets underlying_price=0 (default) → should fall back to strike=180
    groups = OptionStrategyRecognizer().recognize([sp])
    g = groups[0]
    assert g.strategy_type == "Naked Put"
    assert g.underlying_price > 0, "underlying_price must be set (> 0)"
    assert g.underlying_price == pytest.approx(180.0)  # fallback to strike


def test_underlying_price_prefers_position_record_field_over_strike():
    """When PositionRecord.underlying_price is set (from Flex undPrice),
    StrategyGroup.underlying_price must use it instead of the option strike.
    """
    from src.flex_client import PositionRecord as PR
    sp = PR(
        symbol="QQQ   P78", asset_category="OPT", put_call="P",
        strike=78, expiry="20260630", multiplier=100, position=-7,
        cost_basis_price=2.0, mark_price=2.0, unrealized_pnl=0.0,
        delta=-0.3, gamma=0.01, theta=0.05, vega=0.1,
        underlying_symbol="QQQ", currency="USD",
        underlying_price=94.50,   # real price from undPrice field
    )
    groups = OptionStrategyRecognizer().recognize([sp])
    g = groups[0]
    # Must use 94.50, NOT the strike 78
    assert g.underlying_price == pytest.approx(94.50), \
        "StrategyGroup.underlying_price must prefer PositionRecord.underlying_price over strike"


def test_short_strangle_max_profit_bounded():
    """Short Strangle: both legs short → net_credit > 0.
    max_profit = net_credit (premium received when both expire worthless).
    max_loss = None (unlimited; call side unbounded).
    max_loss_downside = put_notional_at_zero - net_credit (downside floor: stock → $0).
    """
    # Short 2× C240 @ $5, Short 1× P148 @ $3, multiplier=100
    # net_credit = 2*5*100 + 1*3*100 = 1000 + 300 = 1300
    # put_notional_at_zero = 148 * 100 * 1 = 14800
    # max_loss_downside = 14800 - 1300 = 13500
    sc = _opt("NVDA  C240", "C", 240, -2, cost_basis=5.0, multiplier=100)
    sp = _opt("NVDA  P148", "P", 148, -1, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc, sp])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Strangle"
    assert g.net_credit == pytest.approx(1300.0)
    assert g.max_profit is not None, "Short Strangle max_profit must be finite (= net credit received)"
    assert g.max_profit == pytest.approx(1300.0)
    assert g.max_loss is None, "Short Strangle max_loss is unlimited (call side unbounded)"
    assert g.max_loss_downside is not None, "Short Strangle max_loss_downside must show put-side floor"
    assert g.max_loss_downside == pytest.approx(13500.0)


def test_long_strangle_max_loss_bounded():
    """Long Strangle: both legs long → net_credit < 0.
    max_loss = premium paid (bounded). max_profit = None (unlimited).
    """
    # Long 1× C240 @ $5, Long 1× P148 @ $3, multiplier=100 → net_credit = -800
    lc = _opt("NVDA  C240", "C", 240, +1, cost_basis=5.0, multiplier=100)
    lp = _opt("NVDA  P148", "P", 148, +1, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([lc, lp])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Strangle"
    assert g.net_credit == pytest.approx(-800.0)
    assert g.max_loss is not None, "Long Strangle max_loss must be finite (= premium paid)"
    assert g.max_loss == pytest.approx(800.0)
    assert g.max_profit is None, "Long Strangle max_profit is unlimited"


def test_short_straddle_max_profit_bounded():
    """Short Straddle: both legs short → max_profit = net_credit, max_loss = None."""
    sc = _opt("AAPL  C180", "C", 180, -3, cost_basis=4.0, multiplier=100)
    sp = _opt("AAPL  P180", "P", 180, -3, cost_basis=3.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sc, sp])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Straddle"
    # net_credit = 3*4*100 + 3*3*100 = 1200 + 900 = 2100
    assert g.net_credit == pytest.approx(2100.0)
    assert g.max_profit is not None, "Short Straddle max_profit must be finite (= net credit received)"
    assert g.max_profit == pytest.approx(2100.0)
    assert g.max_loss is None, "Short Straddle max_loss is unlimited"


def test_underlying_price_uses_stock_mark_for_covered_call():
    """For stock+option strategies, underlying_price = stock mark_price."""
    from datetime import date, timedelta
    exp = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    stk = _stk("AAPL", position=100, mark=195.0)
    sc  = _opt("AAPL  C200", "C", 200, -1, expiry=exp, cost_basis=2.0, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([stk, sc])
    g = groups[0]
    assert g.strategy_type == "Covered Call"
    assert g.underlying_price == pytest.approx(195.0)  # from stock mark_price
