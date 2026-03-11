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
