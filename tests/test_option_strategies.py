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
