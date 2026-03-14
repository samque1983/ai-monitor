"""Tests for local/ibgateway_poller.py — underlying_price propagation."""
import sys
import types
import pytest

# ── Stub out ibapi so the module can be imported without it installed ─────────
def _stub_ibapi():
    for mod in ["ibapi", "ibapi.client", "ibapi.wrapper",
                "ibapi.contract", "ibapi.common"]:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    # Minimal stubs needed by the poller
    client_mod = sys.modules["ibapi.client"]
    wrapper_mod = sys.modules["ibapi.wrapper"]
    contract_mod = sys.modules["ibapi.contract"]
    common_mod = sys.modules["ibapi.common"]

    class EClient:
        def __init__(self, wrapper=None): pass
    class EWrapper: pass
    class Contract: pass
    common_mod.TickerId = int

    client_mod.EClient = EClient
    wrapper_mod.EWrapper = EWrapper
    contract_mod.Contract = Contract

_stub_ibapi()

from local.ibgateway_poller import PositionData, IBPoller  # noqa: E402


def _make_opt_position(symbol="QQQ   P78", underlying_symbol="QQQ",
                       strike=78.0, put_call="P") -> PositionData:
    return PositionData(
        symbol=symbol, asset_category="OPT", put_call=put_call,
        strike=strike, expiry="20260630", multiplier=100,
        position=-7, cost_basis_price=2.0, mark_price=2.0,
        unrealized_pnl=0.0, delta=0.0, gamma=0.0, theta=0.0, vega=0.0,
        underlying_symbol=underlying_symbol, currency="USD",
    )


def _make_stk_position(symbol="QQQ", mark=94.50) -> PositionData:
    return PositionData(
        symbol=symbol, asset_category="STK", put_call="",
        strike=0.0, expiry="", multiplier=1,
        position=100, cost_basis_price=90.0, mark_price=mark,
        unrealized_pnl=450.0, delta=1.0, gamma=0.0, theta=0.0, vega=0.0,
        underlying_symbol="", currency="USD",
    )


def test_position_data_has_underlying_price_field():
    """PositionData must have an underlying_price field (default 0.0)."""
    p = _make_opt_position()
    assert hasattr(p, "underlying_price"), \
        "PositionData must have underlying_price field"
    assert p.underlying_price == 0.0


def test_apply_bs_greeks_sets_underlying_price():
    """After _apply_bs_greeks(), each OPT PositionData.underlying_price
    must be filled from _underlying_prices (the Gateway stock price).
    """
    poller = IBPoller.__new__(IBPoller)
    poller._underlying_prices = {"QQQ": 94.50}
    poller._portfolio_mark = {}
    poller._portfolio_pnl = {}

    opt = _make_opt_position()
    opt.mark_price = 2.0

    from ibapi.contract import Contract
    contract = Contract()
    contract.conId = 999
    poller._opt_contracts = [(contract, opt)]
    poller.positions = [opt]   # needed for the STK loop

    poller._apply_bs_greeks()

    assert opt.underlying_price == pytest.approx(94.50), \
        "underlying_price must be set from _underlying_prices after _apply_bs_greeks()"


def test_stk_position_underlying_price_set_after_apply_bs_greeks():
    """Stock positions get underlying_price == mark_price after _apply_bs_greeks()."""
    poller = IBPoller.__new__(IBPoller)
    poller._underlying_prices = {}
    poller._portfolio_mark = {}
    poller._portfolio_pnl = {}
    poller._opt_contracts = []

    stk = _make_stk_position(mark=94.50)
    poller.positions = [stk]

    poller._apply_bs_greeks()

    assert stk.underlying_price == pytest.approx(94.50), \
        "STK underlying_price must equal mark_price after _apply_bs_greeks()"
