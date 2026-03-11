# Phase 7: Option Strategy Risk — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace per-leg 10-dim risk analysis with a strategy-aware three-layer pipeline that identifies option strategies (stock + options together), analyses risk per strategy, and generates actionable daily recommendations with plain-language explanations.

**Architecture:** `OptionStrategyRecognizer` groups raw Flex positions by underlying and matches them to named strategies (Iron Condor, Bull Put Spread, Covered Call, etc.) including protective modifiers. `StrategyRiskEngine` applies 20 rules per strategy + portfolio aggregation. `RecommendationBuilder` sorts by severity and calls LLM for top alerts.

**Tech Stack:** Python dataclasses, pytest, existing `FlexClient`/`MarketDataProvider`/`LLMClient`, SQLite via `RiskStore`

---

## Task 1: Shared utilities module + StrategyGroup dataclass

**Files:**
- Create: `src/risk_utils.py`
- Create: `src/option_strategies.py`
- Create: `tests/test_option_strategies.py`

**Step 1: Write the failing test**

```python
# tests/test_option_strategies.py
from src.option_strategies import StrategyGroup

def test_strategy_group_defaults():
    sg = StrategyGroup(underlying="AAPL", strategy_type="Naked Put", intent="income")
    assert sg.max_profit is None
    assert sg.max_loss is None
    assert sg.breakevens == []
    assert sg.legs == []
    assert sg.modifiers == []
    assert sg.currency == "USD"
```

**Step 2: Run test to confirm RED**
```
pytest tests/test_option_strategies.py::test_strategy_group_defaults -v
# Expected: ImportError or AttributeError
```

**Step 3: Create `src/risk_utils.py`** — migrate shared constants from `portfolio_risk.py`:

```python
"""Shared utilities for risk modules."""
import os
import re
from typing import Set

CASH_LIKE_TICKERS: Set[str] = {
    "SGOV", "BIL", "SHV", "SHY", "VGSH", "JPST", "ICSH",
    "VMFXX", "SPAXX", "FDRXX", "SPRXX",
}

_FX_DEFAULTS = {
    "HKD": 0.1280, "CNH": 0.1378, "CNY": 0.1378,
    "EUR": 1.08, "GBP": 1.27, "CAD": 0.73, "JPY": 0.0066,
}

def get_fx_rate(currency: str) -> float:
    """Return USD per 1 unit of given currency. Reads FX_<CCY>USD env var first."""
    if currency == "USD":
        return 1.0
    env_key = f"FX_{currency}USD"
    env_val = os.environ.get(env_key)
    if env_val:
        try:
            return float(env_val)
        except ValueError:
            pass
    return _FX_DEFAULTS.get(currency, 1.0)

def normalize_ticker(symbol: str) -> str:
    """Normalize ticker for yfinance: numeric HK codes → 0883.HK, spaces → dash."""
    if symbol.isdigit():
        return symbol.zfill(4) + ".HK"
    if " " in symbol:
        return symbol.replace(" ", "-")
    return symbol
```

**Step 4: Create `src/option_strategies.py`** with StrategyGroup:

```python
"""Option strategy recognition — groups raw Flex positions into named strategies."""
from dataclasses import dataclass, field
from typing import List, Optional
from src.flex_client import PositionRecord


@dataclass
class StrategyGroup:
    underlying: str
    strategy_type: str   # "Iron Condor", "Bull Put Spread", "Naked Put", ...
    intent: str          # "income" | "hedge" | "directional" | "speculation" | "mixed"
    legs: List[PositionRecord] = field(default_factory=list)
    stock_leg: Optional[PositionRecord] = None
    modifiers: List[PositionRecord] = field(default_factory=list)
    net_delta: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    net_gamma: float = 0.0
    max_profit: Optional[float] = None   # None = unlimited
    max_loss: Optional[float] = None     # None = unlimited (naked)
    breakevens: List[float] = field(default_factory=list)
    expiry: str = ""     # primary leg expiry "YYYYMMDD"
    dte: int = 0
    net_pnl: float = 0.0
    net_credit: float = 0.0   # >0 = received premium, <0 = paid premium
    currency: str = "USD"
```

**Step 5: Run test GREEN**
```
pytest tests/test_option_strategies.py::test_strategy_group_defaults -v
```

**Step 6: Commit**
```bash
git add src/risk_utils.py src/option_strategies.py tests/test_option_strategies.py
git commit -m "feat: add risk_utils shared module and StrategyGroup dataclass"
```

---

## Task 2: Group positions by underlying + single-leg recognition

**Files:**
- Modify: `src/option_strategies.py`
- Modify: `tests/test_option_strategies.py`

**Step 1: Write failing tests**

```python
# add to tests/test_option_strategies.py
from datetime import date, timedelta
from src.option_strategies import OptionStrategyRecognizer
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
```

**Step 2: Run tests → RED**
```
pytest tests/test_option_strategies.py -k "recognition" -v
```

**Step 3: Implement `OptionStrategyRecognizer.recognize()` with grouping + single-leg**

```python
# add to src/option_strategies.py
from datetime import date as _date

_INTENT_MAP = {
    "Naked Put": "income", "Cash-Secured Put": "income",
    "Naked Call": "income", "Covered Call": "income",
    "Bull Put Spread": "income", "Bear Call Spread": "income",
    "Iron Condor": "income", "Iron Butterfly": "income",
    "Protective Put": "hedge", "Collar": "mixed",
    "Bull Call Spread": "directional", "Bear Put Spread": "directional",
    "Long Stock": "directional", "Short Stock": "directional",
    "Calendar Spread": "mixed", "Diagonal Spread": "mixed",
    "Straddle": "speculation", "Strangle": "speculation",
    "Long Put": "speculation", "Long Call": "speculation",
    "Unclassified": "unknown",
}


class OptionStrategyRecognizer:

    def recognize(self, positions: List[PositionRecord]) -> List["StrategyGroup"]:
        by_underlying = self._group_by_underlying(positions)
        result = []
        for underlying, pos_list in by_underlying.items():
            result.extend(self._recognize_underlying(underlying, pos_list))
        return result

    def _group_by_underlying(self, positions):
        groups: dict = {}
        for p in positions:
            key = (p.underlying_symbol if (p.asset_category == "OPT" and p.underlying_symbol)
                   else p.symbol)
            groups.setdefault(key, []).append(p)
        return groups

    def _recognize_underlying(self, underlying: str, positions: List[PositionRecord]):
        stocks = [p for p in positions if p.asset_category == "STK"]
        opts   = [p for p in positions if p.asset_category == "OPT"]
        strategies = []
        remaining_opts = list(opts)

        # Group opts by expiry and match within each expiry
        by_expiry: dict = {}
        for p in opts:
            by_expiry.setdefault(p.expiry, []).append(p)

        claimed_opts = set()
        for expiry, exp_opts in sorted(by_expiry.items()):
            sg, used = self._match_expiry_group(exp_opts, stocks, underlying)
            if sg:
                strategies.append(sg)
                claimed_opts.update(id(p) for p in used)
                # If strategy claimed the stock, mark it
                if sg.stock_leg:
                    stocks = [s for s in stocks if s is not sg.stock_leg]

        remaining_opts = [p for p in opts if id(p) not in claimed_opts]

        # Cross-expiry: Calendar / Diagonal
        cal, remaining_opts = self._match_calendar(remaining_opts, underlying)
        strategies.extend(cal)

        # Single remaining opts
        for p in remaining_opts:
            strategies.append(self._make_single_opt(p, underlying))

        # Unclaimed stocks
        for s in stocks:
            sg = StrategyGroup(
                underlying=underlying,
                strategy_type="Long Stock" if s.position > 0 else "Short Stock",
                intent="directional",
                stock_leg=s,
                currency=s.currency,
                net_delta=s.position,
                net_pnl=s.unrealized_pnl,
            )
            strategies.append(sg)

        # Second pass: attach protective modifiers
        strategies = self._attach_modifiers(strategies, underlying)
        # Compute metrics for all
        for sg in strategies:
            self._compute_metrics(sg)
        return strategies

    def _make_single_opt(self, p: PositionRecord, underlying: str) -> "StrategyGroup":
        if p.put_call == "P" and p.position < 0:
            stype = "Naked Put"
        elif p.put_call == "C" and p.position < 0:
            stype = "Naked Call"
        elif p.put_call == "P" and p.position > 0:
            stype = "Long Put"
        else:
            stype = "Long Call"
        return StrategyGroup(
            underlying=underlying, strategy_type=stype,
            intent=_INTENT_MAP[stype], legs=[p],
            expiry=p.expiry, currency=p.currency,
        )
```

**Step 4: Run tests → GREEN**
```
pytest tests/test_option_strategies.py -k "recognition" -v
```

**Step 5: Commit**
```bash
git add src/option_strategies.py tests/test_option_strategies.py
git commit -m "feat: add OptionStrategyRecognizer grouping and single-leg recognition"
```

---

## Task 3: Two-leg strategy recognition (spreads, Covered Call, Protective Put, Straddle, Strangle)

**Files:**
- Modify: `src/option_strategies.py`
- Modify: `tests/test_option_strategies.py`

**Step 1: Write failing tests**

```python
def test_bull_put_spread():
    short_p = _opt("AAPL  261201P00180000", "P", 180, -5, delta=-0.3)
    long_p  = _opt("AAPL  261201P00170000", "P", 170,  5, delta=-0.2)
    groups = OptionStrategyRecognizer().recognize([short_p, long_p])
    assert len(groups) == 1
    g = groups[0]
    assert g.strategy_type == "Bull Put Spread"
    assert g.intent == "income"
    assert len(g.legs) == 2

def test_covered_call():
    stock = _stk("AAPL", 100)
    call  = _opt("AAPL  261201C00200000", "C", 200, -1, delta=0.3)
    groups = OptionStrategyRecognizer().recognize([stock, call])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Covered Call"
    assert groups[0].stock_leg is not None

def test_protective_put():
    stock = _stk("AAPL", 100)
    put   = _opt("AAPL  261201P00160000", "P", 160, 1, delta=-0.2)
    groups = OptionStrategyRecognizer().recognize([stock, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Protective Put"

def test_straddle():
    call = _opt("AAPL  261201C00180000", "C", 180, -3, delta=0.5)
    put  = _opt("AAPL  261201P00180000", "P", 180, -3, delta=-0.5)
    groups = OptionStrategyRecognizer().recognize([call, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Straddle"

def test_strangle():
    call = _opt("AAPL  261201C00200000", "C", 200, -3, delta=0.3)
    put  = _opt("AAPL  261201P00160000", "P", 160, -3, delta=-0.3)
    groups = OptionStrategyRecognizer().recognize([call, put])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Strangle"
```

**Step 2: Implement `_match_expiry_group` for two-leg cases**

Add this method to `OptionStrategyRecognizer`:

```python
def _match_expiry_group(self, opts, stocks, underlying):
    """Try to match opts + stocks into one strategy. Returns (StrategyGroup|None, used_legs)."""
    puts  = sorted([p for p in opts if p.put_call == "P"], key=lambda x: x.strike)
    calls = sorted([p for p in opts if p.put_call == "C"], key=lambda x: x.strike)
    short_puts  = [p for p in puts  if p.position < 0]
    long_puts   = [p for p in puts  if p.position > 0]
    short_calls = [p for p in calls if p.position < 0]
    long_calls  = [p for p in calls if p.position > 0]
    expiry = opts[0].expiry if opts else ""
    currency = opts[0].currency if opts else (stocks[0].currency if stocks else "USD")

    def _sg(stype, legs, stk=None):
        return StrategyGroup(
            underlying=underlying, strategy_type=stype,
            intent=_INTENT_MAP.get(stype, "unknown"),
            legs=[p for p in legs if p is not stk],
            stock_leg=stk, expiry=expiry, currency=currency,
        ), legs

    # ── Iron Condor: 1 SC + 1 LC + 1 SP + 1 LP ─────────────────────
    if len(short_calls)==1 and len(long_calls)==1 and len(short_puts)==1 and len(long_puts)==1:
        sc, lc = short_calls[0], long_calls[0]
        sp, lp = short_puts[0],  long_puts[0]
        if lc.strike > sc.strike and sp.strike > lp.strike:
            # Iron Butterfly: SC and SP share same strike
            if sc.strike == sp.strike:
                return _sg("Iron Butterfly", [sc, lc, sp, lp])
            return _sg("Iron Condor", [sc, lc, sp, lp])

    # ── Collar: STK + SC + LP ────────────────────────────────────────
    if stocks and len(short_calls)==1 and len(long_puts)==1 and not long_calls and not short_puts:
        stk = stocks[0]
        return _sg("Collar", [stk, short_calls[0], long_puts[0]], stk)

    # ── Covered Call: STK + SC ───────────────────────────────────────
    if stocks and len(short_calls)==1 and not puts and not long_calls:
        stk = stocks[0]
        return _sg("Covered Call", [stk, short_calls[0]], stk)

    # ── Protective Put: STK + LP ─────────────────────────────────────
    if stocks and len(long_puts)==1 and not calls and not short_puts:
        stk = stocks[0]
        return _sg("Protective Put", [stk, long_puts[0]], stk)

    # ── Bull Put Spread: SP (high) + LP (low) ────────────────────────
    if len(short_puts)==1 and len(long_puts)==1 and not calls:
        sp, lp = short_puts[0], long_puts[0]
        if sp.strike > lp.strike:
            return _sg("Bull Put Spread", [sp, lp])

    # ── Bear Call Spread: SC (low) + LC (high) ───────────────────────
    if len(short_calls)==1 and len(long_calls)==1 and not puts:
        sc, lc = short_calls[0], long_calls[0]
        if sc.strike < lc.strike:
            return _sg("Bear Call Spread", [sc, lc])

    # ── Bull Call Spread: LC (low) + SC (high) ───────────────────────
    if len(long_calls)==1 and len(short_calls)==1 and not puts:
        lc, sc = long_calls[0], short_calls[0]
        if lc.strike < sc.strike:
            return _sg("Bull Call Spread", [lc, sc])

    # ── Bear Put Spread: LP (high) + SP (low) ────────────────────────
    if len(long_puts)==1 and len(short_puts)==1 and not calls:
        lp, sp = long_puts[0], short_puts[0]
        if lp.strike > sp.strike:
            return _sg("Bear Put Spread", [lp, sp])

    # ── Straddle: Call + Put same strike ─────────────────────────────
    all_calls = calls; all_puts = puts
    if len(all_calls)==1 and len(all_puts)==1 and not stocks:
        c, p = all_calls[0], all_puts[0]
        if c.strike == p.strike and (c.position * p.position > 0):
            return _sg("Straddle", [c, p])

    # ── Strangle: Call + Put different strike ────────────────────────
    if len(all_calls)==1 and len(all_puts)==1 and not stocks:
        c, p = all_calls[0], all_puts[0]
        if c.position * p.position > 0:
            return _sg("Strangle", [c, p])

    return None, []
```

**Step 3: Run tests → GREEN**
```
pytest tests/test_option_strategies.py -v
```

**Step 4: Commit**
```bash
git add src/option_strategies.py tests/test_option_strategies.py
git commit -m "feat: add two-leg and multi-leg strategy recognition"
```

---

## Task 4: Calendar/Diagonal + protective modifiers + strategy metrics

**Files:**
- Modify: `src/option_strategies.py`
- Modify: `tests/test_option_strategies.py`

**Step 1: Write failing tests**

```python
def test_calendar_spread():
    near = _opt("AAPL  261201P00180000", "P", 180, -3, expiry="20261201")
    far  = _opt("AAPL  270319P00180000", "P", 180,  3, expiry="20270319")
    groups = OptionStrategyRecognizer().recognize([near, far])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Calendar Spread"

def test_protective_modifier_attached():
    """Bull Put Spread + extra lower long put → modifier attached, not separate strategy."""
    sp  = _opt("AAPL  261201P00180000", "P", 180, -5)
    lp  = _opt("AAPL  261201P00170000", "P", 170,  5)
    tail = _opt("AAPL  261201P00150000", "P", 150,  2)  # tail hedge
    groups = OptionStrategyRecognizer().recognize([sp, lp, tail])
    assert len(groups) == 1
    assert groups[0].strategy_type == "Bull Put Spread"
    assert len(groups[0].modifiers) == 1
    assert groups[0].modifiers[0].strike == 150

def test_metrics_net_credit():
    """net_credit > 0 for income strategy (received more than paid)."""
    sp = _opt("AAPL  261201P00180000", "P", 180, -5, cost_basis=3.0, multiplier=100)
    lp = _opt("AAPL  261201P00170000", "P", 170,  5, cost_basis=1.5, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    g = groups[0]
    # net_credit = 5*3.0*100 - 5*1.5*100 = 1500 - 750 = 750
    assert g.net_credit == 750.0

def test_metrics_max_loss_spread():
    """Bull Put Spread max_loss = (spread_width - net_credit_per_contract) × contracts."""
    sp = _opt("AAPL  261201P00180000", "P", 180, -5, cost_basis=3.0, multiplier=100)
    lp = _opt("AAPL  261201P00170000", "P", 170,  5, cost_basis=1.5, multiplier=100)
    groups = OptionStrategyRecognizer().recognize([sp, lp])
    g = groups[0]
    # spread_width=10, net_credit=750, contracts=5
    # max_loss = (10 - 750/500) * 100 * 5 = (10 - 1.5) * 500 = 4250
    assert g.max_loss == pytest.approx(4250.0)
    assert g.max_profit == pytest.approx(750.0)
```

**Step 2: Implement Calendar matching + modifiers + metrics**

Add to `OptionStrategyRecognizer`:

```python
def _match_calendar(self, remaining_opts, underlying):
    """Match Calendar/Diagonal from cross-expiry options. Returns (strategies, leftover)."""
    strategies = []
    used = set()
    puts  = sorted([p for p in remaining_opts if p.put_call == "P"], key=lambda x: x.expiry)
    calls = sorted([p for p in remaining_opts if p.put_call == "C"], key=lambda x: x.expiry)
    for opts_group in [puts, calls]:
        for i, near in enumerate(opts_group):
            if id(near) in used:
                continue
            for far in opts_group[i+1:]:
                if id(far) in used:
                    continue
                if far.expiry <= near.expiry:
                    continue
                stype = ("Calendar Spread" if near.strike == far.strike
                         else "Diagonal Spread")
                sg = StrategyGroup(
                    underlying=underlying, strategy_type=stype,
                    intent=_INTENT_MAP[stype],
                    legs=[near, far], expiry=far.expiry,
                    currency=near.currency,
                )
                strategies.append(sg)
                used.add(id(near)); used.add(id(far))
                break
    leftover = [p for p in remaining_opts if id(p) not in used]
    return strategies, leftover

def _attach_modifiers(self, strategies, underlying):
    """Second pass: attach unmatched long puts/calls as protective modifiers."""
    # Collect single long-option strategies that could be modifiers
    single_longs = [sg for sg in strategies
                    if sg.strategy_type in ("Long Put", "Long Call")
                    and len(sg.legs) == 1]
    non_single = [sg for sg in strategies if sg not in single_longs]
    used = set()
    for mod_sg in single_longs:
        mod = mod_sg.legs[0]
        # Find the strategy on same underlying that this long option protects
        target = next(
            (sg for sg in non_single
             if sg.underlying == underlying
             and sg.strategy_type not in ("Long Stock", "Short Stock")
             and id(sg) not in used),
            None
        )
        if target:
            target.modifiers.append(mod)
            used.add(id(mod_sg))
    result = non_single + [sg for sg in single_longs if id(sg) not in used]
    return result

def _compute_metrics(self, sg: "StrategyGroup"):
    """Compute net Greeks, max_profit/loss, breakevens, DTE, net_pnl, net_credit."""
    from datetime import date as _date
    all_opts = sg.legs + sg.modifiers
    if sg.stock_leg:
        all_opts_only = [p for p in all_opts if p.asset_category == "OPT"]
        sg.net_delta = sg.stock_leg.position + sum(
            p.delta * p.position * p.multiplier for p in all_opts_only)
    else:
        sg.net_delta = sum(p.delta * p.position * p.multiplier for p in all_opts
                           if p.asset_category == "OPT")
    sg.net_theta = sum(p.theta * p.position * p.multiplier for p in all_opts
                       if p.asset_category == "OPT")
    sg.net_vega  = sum(p.vega  * p.position * p.multiplier for p in all_opts
                       if p.asset_category == "OPT")
    sg.net_gamma = sum(p.gamma * p.position * p.multiplier for p in all_opts
                       if p.asset_category == "OPT")

    opt_legs = [p for p in sg.legs if p.asset_category == "OPT"]
    sg.net_credit = sum(-p.position * p.cost_basis_price * p.multiplier
                        for p in opt_legs)
    sg.net_pnl = sum(p.unrealized_pnl for p in sg.legs)
    if sg.stock_leg:
        sg.net_pnl += sg.stock_leg.unrealized_pnl

    # DTE
    if sg.expiry and len(sg.expiry) == 8:
        try:
            exp = _date(int(sg.expiry[:4]), int(sg.expiry[4:6]), int(sg.expiry[6:]))
            sg.dte = max(0, (exp - _date.today()).days)
        except ValueError:
            sg.dte = 0

    # max_profit / max_loss / breakevens per strategy type
    self._compute_payoff(sg, opt_legs)

def _compute_payoff(self, sg, opt_legs):
    stype = sg.strategy_type
    contracts = abs(opt_legs[0].position) if opt_legs else 1
    mult = opt_legs[0].multiplier if opt_legs else 100
    credit_per_contract = sg.net_credit / contracts / mult if contracts > 0 else 0

    if stype in ("Bull Put Spread", "Bear Call Spread"):
        strikes = sorted(p.strike for p in opt_legs)
        width = strikes[1] - strikes[0]
        sg.max_profit = sg.net_credit
        sg.max_loss = (width - credit_per_contract) * mult * contracts
        short_p = next(p for p in opt_legs if p.position < 0)
        sg.breakevens = [short_p.strike - credit_per_contract]

    elif stype in ("Bull Call Spread", "Bear Put Spread"):
        strikes = sorted(p.strike for p in opt_legs)
        width = strikes[1] - strikes[0]
        sg.max_loss = abs(sg.net_credit)  # net debit paid
        sg.max_profit = (width - abs(credit_per_contract)) * mult * contracts
        long_p = next(p for p in opt_legs if p.position > 0)
        sg.breakevens = [long_p.strike + abs(credit_per_contract)]

    elif stype in ("Iron Condor", "Iron Butterfly"):
        short_puts  = [p for p in opt_legs if p.put_call=="P" and p.position<0]
        short_calls = [p for p in opt_legs if p.put_call=="C" and p.position<0]
        if short_puts and short_calls:
            sp_strike = short_puts[0].strike
            sc_strike = short_calls[0].strike
            sg.max_profit = sg.net_credit
            put_strikes = sorted(p.strike for p in opt_legs if p.put_call=="P")
            call_strikes = sorted(p.strike for p in opt_legs if p.put_call=="C")
            put_width  = put_strikes[1]  - put_strikes[0]
            call_width = call_strikes[1] - call_strikes[0]
            max_width = max(put_width, call_width)
            sg.max_loss = (max_width - credit_per_contract) * mult * contracts
            sg.breakevens = [sp_strike - credit_per_contract,
                             sc_strike + credit_per_contract]

    elif stype == "Naked Put":
        sp = opt_legs[0]
        sg.max_profit = sg.net_credit
        sg.max_loss = None  # unlimited downside to 0
        sg.breakevens = [sp.strike - credit_per_contract]

    elif stype == "Naked Call":
        sc = opt_legs[0]
        sg.max_profit = sg.net_credit
        sg.max_loss = None  # unlimited upside
        sg.breakevens = [sc.strike + credit_per_contract]

    elif stype == "Covered Call":
        sc = next((p for p in opt_legs if p.put_call=="C"), None)
        stk = sg.stock_leg
        if sc and stk:
            sg.max_profit = ((sc.strike - stk.cost_basis_price) * stk.position
                             + sg.net_credit)
            sg.max_loss = None  # stock can go to 0
            sg.breakevens = [stk.cost_basis_price - credit_per_contract]
```

**Step 3: Run tests → GREEN**
```
pytest tests/test_option_strategies.py -v
# Expected: all pass
```

**Step 4: Commit**
```bash
git add src/option_strategies.py tests/test_option_strategies.py
git commit -m "feat: add calendar/diagonal recognition, protective modifiers, strategy metrics"
```

---

## Task 5: StrategyRiskEngine skeleton + red rules (rules 1–6)

**Files:**
- Create: `src/strategy_risk.py`
- Create: `tests/test_strategy_risk.py`

**Step 1: Write failing tests**

```python
# tests/test_strategy_risk.py
import pytest
from unittest.mock import patch
from datetime import date, timedelta
from src.strategy_risk import StrategyRiskEngine, StrategyRiskAlert, StrategyRiskReport
from src.option_strategies import StrategyGroup, OptionStrategyRecognizer
from src.flex_client import PositionRecord, AccountSummary

def _account(nlv=500000, cushion=0.30, maint=50000):
    return AccountSummary(net_liquidation=nlv, gross_position_value=0,
                          init_margin_req=0, maint_margin_req=maint,
                          excess_liquidity=0, available_funds=0, cushion=cushion)

def _near_exp(days=7):
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")

def _far_exp(days=90):
    return (date.today() + timedelta(days=days)).strftime("%Y%m%d")

def _naked_put_group(strike=180, dte_days=7, itm_pct=3.0, contracts=5, nlv=500000):
    """StrategyGroup representing a Naked Put that's ITM and near expiry."""
    mark = strike * (1 - itm_pct/100)
    p = PositionRecord(
        symbol=f"AAPL  P{strike:.0f}", asset_category="OPT", put_call="P",
        strike=float(strike), expiry=_near_exp(dte_days), multiplier=100,
        position=-contracts, cost_basis_price=3.0, mark_price=float(mark),
        unrealized_pnl=-(mark*100*contracts), delta=-0.7, gamma=0.05,
        theta=-0.1, vega=0.2, underlying_symbol="AAPL", currency="USD",
    )
    sg = StrategyGroup(underlying="AAPL", strategy_type="Naked Put", intent="income",
                       legs=[p], expiry=p.expiry, dte=dte_days,
                       max_loss=None, net_credit=3.0*100*contracts)
    return sg

def test_rule1_assignment_imminent():
    """Rule 1: Short leg DTE ≤ 7 AND ITM > 2% → red alert."""
    sg = _naked_put_group(strike=180, dte_days=5, itm_pct=3.0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account())
    reds = [a for a in report.alerts if a.severity == "red" and a.rule_id == 1]
    assert reds, "Rule 1 must fire for ITM naked put with DTE ≤ 7"

def test_rule4_margin_critical():
    """Rule 4: cushion < 10% → red alert."""
    sg = _naked_put_group(dte_days=45, itm_pct=0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account(cushion=0.07))
    reds = [a for a in report.alerts if a.severity == "red" and a.rule_id == 4]
    assert reds, "Rule 4 must fire when cushion < 10%"

def test_report_has_summary_stats():
    """StrategyRiskReport exposes summary_stats for RiskStore compatibility."""
    sg = _naked_put_group(dte_days=45, itm_pct=0)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze([sg], _account())
    assert isinstance(report.summary_stats, dict)
    assert "stress_test" in report.summary_stats
```

**Step 2: Create `src/strategy_risk.py`**

```python
"""Strategy-aware risk engine: rules, aggregation, recommendations."""
import os
from dataclasses import dataclass, field
from typing import List, Optional
from datetime import date as _date

from src.option_strategies import StrategyGroup
from src.flex_client import AccountSummary
from src.risk_utils import CASH_LIKE_TICKERS, get_fx_rate, normalize_ticker
from src.market_data import MarketDataProvider


@dataclass
class StrategyRiskAlert:
    rule_id: int
    severity: str           # "red" | "yellow" | "watch"
    strategy_ref: Optional[StrategyGroup]
    underlying: str
    title: str              # short label e.g. "指派风险迫近"
    technical: str          # "AAPL Naked Put 180 — DTE 5, ITM 3.2%"
    plain: str              # "你的 AAPL 期权快到期了，而且已经亏损中..."
    options: List[str] = field(default_factory=list)
    ai_suggestion: str = ""
    urgency: bool = False   # True = sorts before other same-severity alerts


@dataclass
class StrategyRiskReport:
    account_id: str
    report_date: str
    net_liquidation: float
    total_pnl: float
    cushion: float
    strategies: List[StrategyGroup] = field(default_factory=list)
    alerts: List[StrategyRiskAlert] = field(default_factory=list)
    summary_stats: dict = field(default_factory=dict)
    portfolio_summary: str = ""
    top_actions: List[StrategyRiskAlert] = field(default_factory=list)


class StrategyRiskEngine:

    def analyze(self, strategies: List[StrategyGroup],
                account: AccountSummary) -> StrategyRiskReport:
        today = _date.today().isoformat()
        total_pnl = sum(sg.net_pnl for sg in strategies)
        alerts: List[StrategyRiskAlert] = []

        # Per-strategy rules
        for sg in strategies:
            alerts.extend(self._apply_strategy_rules(sg, account))

        # Portfolio-level rules
        alerts.extend(self._apply_portfolio_rules(strategies, account))

        # Stress test
        stress = self._compute_stress(strategies, account)

        report = StrategyRiskReport(
            account_id="",
            report_date=today,
            net_liquidation=account.net_liquidation,
            total_pnl=total_pnl,
            cushion=account.cushion,
            strategies=strategies,
            alerts=alerts,
            summary_stats={"stress_test": stress},
        )
        return report

    def _dte(self, expiry_str: str) -> Optional[int]:
        if not expiry_str or len(expiry_str) != 8:
            return None
        try:
            exp = _date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:]))
            return max(0, (exp - _date.today()).days)
        except ValueError:
            return None

    def _apply_strategy_rules(self, sg: StrategyGroup,
                               account: AccountSummary) -> List[StrategyRiskAlert]:
        alerts = []
        short_legs = [p for p in sg.legs
                      if p.asset_category == "OPT" and p.position < 0]

        for leg in short_legs:
            dte = self._dte(leg.expiry)
            if dte is None:
                continue
            # Rule 1: DTE ≤ 7 AND ITM > 2%
            if dte <= 7 and leg.put_call == "P":
                itm_pct = (leg.strike - leg.mark_price) / leg.mark_price * 100
                if itm_pct > 2.0:
                    alerts.append(StrategyRiskAlert(
                        rule_id=1, severity="red", urgency=True,
                        strategy_ref=sg, underlying=sg.underlying,
                        title="指派风险迫近",
                        technical=f"{sg.underlying} {sg.strategy_type} {leg.strike:.0f}P — DTE {dte}天, 实值 {itm_pct:.1f}%",
                        plain=f"你的 {sg.underlying} 期权只剩 {dte} 天到期，而且已经亏损 {itm_pct:.1f}%。券商可能强制你以 {leg.strike:.0f} 的价格买入股票，需要立即决定：平仓止损、接受买入还是展期到下月。",
                        options=["A. 立即平仓止损，锁定亏损", "B. 接受指派，以行权价承接股票",
                                 "C. Roll 到下月更低行权价", "D. 等待最后关头反弹"],
                    ))

            # Rule 6: Naked short (no modifier) DTE ≤ 14 AND ITM
            if (dte <= 14 and not sg.modifiers
                    and sg.strategy_type in ("Naked Put", "Naked Call")):
                if leg.put_call == "P":
                    itm_pct = (leg.strike - leg.mark_price) / leg.mark_price * 100
                else:
                    itm_pct = (leg.mark_price - leg.strike) / leg.strike * 100
                if itm_pct > 0:
                    alerts.append(StrategyRiskAlert(
                        rule_id=6, severity="red", urgency=True,
                        strategy_ref=sg, underlying=sg.underlying,
                        title="裸空仓到期高风险",
                        technical=f"{sg.underlying} 裸 {leg.put_call} {leg.strike:.0f} — DTE {dte}天, 无对冲",
                        plain=f"你持有裸空仓（没有任何保护）且快到期，实值 {max(0,itm_pct):.1f}%。没有下行保护，亏损可能继续扩大。",
                        options=["A. 立即平仓", "B. 买入保护 Put 构成价差",
                                 "C. Roll 到更低行权价 / 更远到期", "D. 接受指派"],
                    ))

        # Rule 7: Income strategy realized profit > 75%
        if sg.intent == "income" and sg.net_credit > 0:
            current_value = sum(abs(p.mark_price) * abs(p.position) * p.multiplier
                                for p in sg.legs if p.asset_category == "OPT")
            realized_pct = (sg.net_credit - current_value) / sg.net_credit
            if realized_pct > 0.75:
                alerts.append(StrategyRiskAlert(
                    rule_id=7, severity="yellow", urgency=False,
                    strategy_ref=sg, underlying=sg.underlying,
                    title="锁利时机",
                    technical=f"{sg.underlying} {sg.strategy_type} — 已实现 {realized_pct*100:.0f}% 收益",
                    plain=f"你的 {sg.underlying} 策略已经赚到了 {realized_pct*100:.0f}% 的预期收益。继续持有只剩 {(1-realized_pct)*100:.0f}% 的空间，但风险还在。经典原则建议此时平仓锁利。",
                    options=["A. 平仓锁利，释放保证金", "B. 继续持有到期，争取全收",
                             "C. Roll 到更高行权价或更远到期", "D. 设止损保护，继续等待"],
                ))

        # Rule 8: Protective hedge expiring soon
        if sg.strategy_type in ("Protective Put", "Collar"):
            put_legs = [p for p in sg.legs if p.put_call == "P" and p.position > 0]
            for leg in put_legs:
                dte = self._dte(leg.expiry)
                if dte is not None and dte <= 21:
                    alerts.append(StrategyRiskAlert(
                        rule_id=8, severity="yellow", urgency=True,
                        strategy_ref=sg, underlying=sg.underlying,
                        title="保险快到期",
                        technical=f"{sg.underlying} {sg.strategy_type} — 保护 Put {leg.strike:.0f} DTE {dte}天",
                        plain=f"你买的下行保险（{leg.strike:.0f} Put）还有 {dte} 天到期。到期后你的正股就没有保护了，需要决定是否续保。",
                        options=["A. 立即买入下月同行权价 Put 续保", "B. 换更低行权价降低续保成本",
                                 "C. 暂时不续保，接受裸露风险", "D. 同时卖出 Call 构成 Collar 对冲续保成本"],
                    ))

        return alerts

    def _apply_portfolio_rules(self, strategies, account) -> List[StrategyRiskAlert]:
        alerts = []
        nlv = account.net_liquidation
        cushion = account.cushion

        # Rule 4: margin critical
        if cushion < 0.10:
            alerts.append(StrategyRiskAlert(
                rule_id=4, severity="red", urgency=True,
                strategy_ref=None, underlying="ACCOUNT",
                title="保证金危险",
                technical=f"账户 cushion {cushion*100:.1f}%，维持保证金 ${account.maint_margin_req:,.0f}",
                plain=f"你的账户保证金缓冲只有 {cushion*100:.1f}%。如果市场下跌，券商随时可能强制平仓你的仓位。需要立即减仓或存入现金。",
                options=["A. 平仓最大保证金占用仓位", "B. 存入现金提升 cushion",
                         "C. 将裸 Sell Put 转为价差结构", "D. 等待期权到期自然释放"],
            ))
        elif cushion < 0.20:
            alerts.append(StrategyRiskAlert(
                rule_id=14, severity="yellow", urgency=False,
                strategy_ref=None, underlying="ACCOUNT",
                title="保证金偏紧",
                technical=f"账户 cushion {cushion*100:.1f}%",
                plain=f"保证金缓冲 {cushion*100:.1f}%，低于安全线 25%。市场波动时有追保压力。",
                options=["A. 减少高保证金占用的仓位", "B. 将裸空转为价差",
                         "C. 暂不操作，持续观察", "D. 备用资金待命"],
            ))

        # Rule 5 & 10: concentration
        if nlv > 0:
            notional_by_und: dict = {}
            for sg in strategies:
                if sg.underlying in CASH_LIKE_TICKERS:
                    continue
                notional = 0.0
                for p in sg.legs:
                    fx = get_fx_rate(p.currency)
                    if p.asset_category == "STK":
                        notional += p.position * p.mark_price * fx
                    else:
                        notional += -p.position * p.strike * p.multiplier * fx
                notional_by_und[sg.underlying] = (
                    notional_by_und.get(sg.underlying, 0) + notional)
            for und, notional in notional_by_und.items():
                if notional <= 0:
                    continue
                ratio = notional / nlv
                if ratio > 0.40:
                    alerts.append(StrategyRiskAlert(
                        rule_id=5, severity="red", urgency=False,
                        strategy_ref=None, underlying=und,
                        title="集中度危险",
                        technical=f"{und} 净风险敞口 ${notional:,.0f} ({ratio*100:.1f}% NLV)",
                        plain=f"你在 {und} 上的风险敞口占账户净资产的 {ratio*100:.1f}%。如果这只股票大跌，对整个账户的冲击会非常严重。",
                        options=[f"A. 分批减少 {und} 仓位至 20%以下",
                                 f"B. 买入 {und} Put 做局部对冲",
                                 "C. 设硬止损（跌破 MA200 时触发）",
                                 "D. 维持现状（如高仓位为有意策略）"],
                    ))
                elif ratio > 0.20:
                    alerts.append(StrategyRiskAlert(
                        rule_id=10, severity="yellow", urgency=False,
                        strategy_ref=None, underlying=und,
                        title="集中度偏高",
                        technical=f"{und} 净风险敞口 ${notional:,.0f} ({ratio*100:.1f}% NLV)",
                        plain=f"{und} 在组合中占比 {ratio*100:.1f}%，超过建议的 20%。",
                        options=[f"A. 逐步减持 {und}", f"B. 买 Put 对冲",
                                 "C. 设止损线", "D. 维持现状"],
                    ))
        return alerts

    def _compute_stress(self, strategies, account) -> dict:
        nlv = account.net_liquidation
        mdp = MarketDataProvider()
        total_loss_10 = 0.0
        underlying_prices = {
            p.symbol: p.mark_price * get_fx_rate(p.currency)
            for sg in strategies for p in (sg.legs + ([sg.stock_leg] if sg.stock_leg else []))
            if p.asset_category == "STK"
        }
        for sg in strategies:
            if sg.underlying in CASH_LIKE_TICKERS:
                continue
            try:
                fund = mdp.get_fundamentals(normalize_ticker(sg.underlying))
                beta = float(fund.get("beta") or 1.0)
            except Exception:
                beta = 1.0
            for p in sg.legs + (sg.modifiers or []):
                fx = get_fx_rate(p.currency)
                if p.asset_category == "STK":
                    dollar_delta = p.position * p.mark_price * fx
                else:
                    u_price = underlying_prices.get(sg.underlying, p.strike * fx)
                    dollar_delta = p.delta * p.position * p.multiplier * u_price
                total_loss_10 += dollar_delta * beta * 0.10

        # Rule 11: stress loss > 15% NLV
        # (alert added in portfolio rules based on summary_stats)
        return {
            "drop_10pct": -total_loss_10,
            "drop_20pct": -total_loss_10 * 2,
        }
```

**Step 3: Run tests → GREEN**
```
pytest tests/test_strategy_risk.py -v
```

**Step 4: Commit**
```bash
git add src/strategy_risk.py tests/test_strategy_risk.py
git commit -m "feat: add StrategyRiskEngine with red/yellow rules and stress test"
```

---

## Task 6: Remaining yellow/watch rules + RecommendationBuilder + LLM integration

**Files:**
- Modify: `src/strategy_risk.py`
- Modify: `tests/test_strategy_risk.py`

**Step 1: Add tests**

```python
def test_rule11_stress_loss_yellow():
    """Rule 11: stress loss > 15% NLV → yellow alert."""
    # Build a strategy that causes a large stress loss
    # stock position: 1000 shares × $150, beta=1.0 → loss 10% = $15,000 on $50k NLV = 30%
    from src.flex_client import PositionRecord
    stk = PositionRecord(
        symbol="AAPL", asset_category="STK", put_call="", strike=0, expiry="",
        multiplier=1, position=1000, cost_basis_price=140, mark_price=150,
        unrealized_pnl=10000, delta=1.0, gamma=0, theta=0, vega=0,
        underlying_symbol="", currency="USD",
    )
    sg = StrategyGroup(underlying="AAPL", strategy_type="Long Stock", intent="directional",
                       stock_leg=stk, legs=[], net_pnl=10000)
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = {"beta": 1.0}
        report = engine.analyze([sg], _account(nlv=50000))
    # stress = 1000×150×1.0×0.10 = 15,000, ratio = 15000/50000 = 30% > 15%
    stress_alerts = [a for a in report.alerts if a.rule_id == 11]
    assert stress_alerts

def test_recommendation_builder_sorts_red_urgent_first():
    """Red urgent alerts appear before regular red in top_actions."""
    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider"):
        report = engine.analyze(
            [_naked_put_group(dte_days=5, itm_pct=3.0)],
            _account(cushion=0.07),
        )
    # Both rule 1 (urgent) and rule 4 (urgent) should be in top_actions
    assert len(report.top_actions) >= 1
    assert report.top_actions[0].severity == "red"
```

**Step 2: Add remaining rules + RecommendationBuilder to `strategy_risk.py`**

Add to `_apply_portfolio_rules`:

```python
        # Rule 11: stress loss alert (requires stress already computed — use stored result)
        # Triggered post-hoc in analyze() after stress is known

        # Rule 15: net portfolio delta > 80% NLV
        if nlv > 0:
            net_delta_dollars = sum(
                sg.net_delta * (
                    (sg.stock_leg.mark_price if sg.stock_leg else
                     next((p.strike for p in sg.legs if p.asset_category=="OPT"), 100))
                ) for sg in strategies
            )
            if abs(net_delta_dollars) > nlv * 0.80:
                alerts.append(StrategyRiskAlert(
                    rule_id=15, severity="watch", urgency=False,
                    strategy_ref=None, underlying="PORTFOLIO",
                    title="方向性敞口偏大",
                    technical=f"净 Delta 敞口约 ${abs(net_delta_dollars):,.0f} ({abs(net_delta_dollars)/nlv*100:.0f}% NLV)",
                    plain=f"整体组合的方向性押注相当于净资产的 {abs(net_delta_dollars)/nlv*100:.0f}%。市场大幅波动时风险较集中。",
                    options=["A. 减少方向性仓位", "B. 买入 Put 对冲",
                             "C. 增加空 Call 降低 Delta", "D. 维持现状"],
                ))
```

Add `RecommendationBuilder` class and update `analyze()`:

```python
# Add to analyze() method after computing stress:

        # Rule 11 post-hoc: add stress alert now that we have stress numbers
        if nlv > 0 and stress["drop_10pct"] < 0:
            stress_loss = abs(stress["drop_10pct"])
            ratio = stress_loss / nlv
            if ratio > 0.15:
                sev = "red" if ratio > 0.20 else "yellow"
                alerts.append(StrategyRiskAlert(
                    rule_id=11, severity=sev, urgency=False,
                    strategy_ref=None, underlying="PORTFOLIO",
                    title="尾部风险偏高",
                    technical=f"大盘跌10%预估亏损 ${stress_loss:,.0f} ({ratio*100:.1f}% NLV)",
                    plain=f"如果大盘整体下跌10%，你的组合预计亏损 ${stress_loss:,.0f}，占净资产 {ratio*100:.1f}%。整体下行保护不足。",
                    options=["A. 买入 SPY Put 对冲系统性风险",
                             "B. 降低高 Beta 仓位",
                             "C. 将裸 Sell Put 转为价差结构",
                             "D. 维持现状（若认为近期下跌概率低）"],
                ))

        # Sort + build top_actions
        _URGENT_RULES = {1, 2, 4, 6, 7, 8}
        def _sort_key(a):
            sev_order = {"red": 0, "yellow": 1, "watch": 2}
            return (sev_order.get(a.severity, 3), 0 if a.urgency or a.rule_id in _URGENT_RULES else 1)
        alerts.sort(key=_sort_key)
        report.alerts = alerts
        report.top_actions = [a for a in alerts if a.severity == "red"][:5]
        return report
```

Add LLM suggestion generation:

```python
def generate_strategy_suggestion(alert: StrategyRiskAlert, llm_config: dict) -> str:
    """Generate AI suggestion for an alert. Falls back to plain text."""
    fallback = alert.plain
    try:
        from src.llm_client import make_llm_client_from_env
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "claude-haiku-4-5-20251001")
        client = make_llm_client_from_env(model=model, api_key=api_key)
        options_str = " / ".join(alert.options[:4])
        prompt = (f"策略：{alert.technical}\n问题：{alert.plain}\n"
                  f"选项：{options_str}\n\n"
                  f"请用80-120字中文分析：当前处境 → 各选项利弊 → 推荐选项及理由。"
                  f"只陈述条件和逻辑，末尾注明推荐选项（如：推荐选项C）。")
        return client.simple_chat(
            "你是专业期权风险管理顾问。简明扼要，末尾注明推荐选项。",
            prompt, max_tokens=250,
        )
    except Exception:
        return fallback


def generate_portfolio_summary(report: StrategyRiskReport, llm_config: dict) -> str:
    """Portfolio-level narrative. Falls back to rule text."""
    red = sum(1 for a in report.alerts if a.severity == "red")
    yellow = sum(1 for a in report.alerts if a.severity == "yellow")
    fallback = f"当前组合存在 {red} 项红色预警、{yellow} 项黄色提示。"
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")):
        return fallback
    try:
        from src.llm_client import make_llm_client_from_env
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "claude-haiku-4-5-20251001")
        client = make_llm_client_from_env(model=model, api_key=api_key)
        top_alerts = "\n".join(f"{a.severity}: {a.technical}" for a in report.alerts[:10])
        prompt = (f"账户净资产 ${report.net_liquidation:,.0f}，cushion {report.cushion*100:.1f}%，"
                  f"{red} 红色预警、{yellow} 黄色。\n主要预警：\n{top_alerts}\n\n"
                  f"请用80-120字总结核心风险和今日最优先操作。")
        return client.simple_chat(
            "你是专业期权风险管理顾问，用中文回复。", prompt, max_tokens=300)
    except Exception:
        return fallback
```

**Step 3: Run tests → GREEN**
```
pytest tests/test_strategy_risk.py -v
```

**Step 4: Commit**
```bash
git add src/strategy_risk.py tests/test_strategy_risk.py
git commit -m "feat: add remaining risk rules, RecommendationBuilder, LLM suggestions"
```

---

## Task 7: Rewrite `portfolio_report.py` — strategy-card layout

**Files:**
- Modify: `src/portfolio_report.py`

**Step 1: Full rewrite of `portfolio_report.py`**

The new report uses `StrategyRiskReport` from `strategy_risk.py`. Keep the same function signature `generate_html_report(report)` for compatibility.

Key sections:
1. Summary card (NLV, cushion, stress loss, AI narrative)
2. 今日操作清单 (top 5 red alerts)
3. Three tiers: 立即处理 / 本周评估 / 持续观察
4. Strategy cards: name + intent badge + legs summary + Greeks row + scenario row + ABCD options

```python
"""Generate strategy-aware HTML risk report from StrategyRiskReport."""
import re
from html import escape as _e
# Accept both old RiskReport and new StrategyRiskReport
try:
    from src.strategy_risk import StrategyRiskReport as _ReportType
except ImportError:
    _ReportType = None

_LEVEL_COLOR  = {"red": "#ff453a", "yellow": "#ffb340", "watch": "#636366"}
_LEVEL_BG     = {"red": "rgba(255,69,58,0.10)", "yellow": "rgba(255,179,64,0.09)", "watch": "rgba(99,99,102,0.10)"}
_LEVEL_BORDER = {"red": "rgba(255,69,58,0.22)", "yellow": "rgba(255,179,64,0.20)", "watch": "rgba(99,99,102,0.18)"}

_INTENT_COLOR = {
    "income": "#30d158", "hedge": "#0a84ff",
    "directional": "#ff9f0a", "speculation": "#bf5af2", "mixed": "#64d2ff",
}
_INTENT_LABEL = {
    "income": "收租", "hedge": "对冲",
    "directional": "方向", "speculation": "投机", "mixed": "混合",
}
```

The `_alert_card` function renders a `StrategyRiskAlert`:
- Card header: severity dot + `alert.title` + `alert.underlying` badge
- Tech line: `alert.technical` in monospace
- Body text: `alert.ai_suggestion or alert.plain`
- ABCD pills with ★ on recommended option (parsed from ai_suggestion)

The `_strategy_summary_card` (optional collapsible) shows the full strategy list.

The `generate_html_report(report)` detects report type and routes appropriately.

**Step 2: Test smoke**
```bash
python3 -c "
from src.strategy_risk import StrategyRiskReport
from src.portfolio_report import generate_html_report
r = StrategyRiskReport(account_id='TEST', report_date='2026-03-11',
    net_liquidation=500000, total_pnl=1000, cushion=0.29)
html = generate_html_report(r)
assert '<html' in html
print('OK')
"
```

**Step 3: Commit**
```bash
git add src/portfolio_report.py
git commit -m "feat: rewrite portfolio_report for strategy-card layout"
```

---

## Task 8: Wire `main.py` + update `risk_store.py` + delete old files

**Files:**
- Modify: `src/main.py`
- Modify: `src/risk_store.py`
- Delete: `src/portfolio_risk.py`
- Delete: `tests/test_portfolio_risk.py`

**Step 1: Update `risk_store.py`** — import from `strategy_risk` instead of `portfolio_risk`:

```python
# src/risk_store.py — change line 7:
# Before:
from src.portfolio_risk import RiskReport
# After:
try:
    from src.strategy_risk import StrategyRiskReport as RiskReport
except ImportError:
    from src.portfolio_risk import RiskReport  # fallback during migration
```

`save_report` already accesses `.account_id`, `.report_date`, `.summary_stats`, `.net_liquidation`, `.total_pnl`, `.cushion` — all present on `StrategyRiskReport`. No other changes needed.

**Step 2: Update `main.py`**

Replace the import block and `run_risk_report`:

```python
# Replace:
from src.portfolio_risk import load_account_configs, PortfolioRiskAnalyzer, generate_risk_suggestion, generate_portfolio_summary
# With:
from src.portfolio_risk import load_account_configs  # keep only config loader temporarily
from src.option_strategies import OptionStrategyRecognizer
from src.strategy_risk import (StrategyRiskEngine, generate_strategy_suggestion,
                                generate_portfolio_summary)
```

Replace `run_risk_report`:

```python
def run_risk_report(account_config, config):
    """Fetch Flex data, run strategy recognition + risk engine, save HTML report."""
    store = RiskStore()
    client = FlexClient(token=account_config.flex_token, query_id=account_config.flex_query_id)
    positions, account_summary = client.fetch()

    # Env var overrides for cushion/NLV
    key = account_config.key
    if nlv := os.environ.get(f"ACCOUNT_{key}_NLV"):
        account_summary.net_liquidation = float(nlv)
    if cushion := os.environ.get(f"ACCOUNT_{key}_CUSHION"):
        account_summary.cushion = float(cushion)
    if maint := os.environ.get(f"ACCOUNT_{key}_MAINT_MARGIN"):
        account_summary.maint_margin_req = float(maint)

    # Layer 1: recognize strategies
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize(positions)

    # Layer 2: risk analysis
    engine = StrategyRiskEngine()
    report = engine.analyze(strategies, account_summary)
    report.account_id = account_config.key

    # Layer 3: LLM suggestions
    llm_cfg = config.get("llm", {}) if config else {}
    for alert in report.alerts:
        if alert.severity == "red":
            alert.ai_suggestion = generate_strategy_suggestion(alert, llm_cfg)
    report.portfolio_summary = generate_portfolio_summary(report, llm_cfg)

    html = generate_html_report(report)
    store.save_report(report, html)

    reports_dir = os.environ.get("REPORTS_DIR", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    html_path = os.path.join(reports_dir, f"risk_{account_config.key}_{report.report_date}.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Report saved: {html_path}")
    red = sum(1 for a in report.alerts if a.severity == "red")
    yellow = sum(1 for a in report.alerts if a.severity == "yellow")
    print(f"[{account_config.name}] NLV=${report.net_liquidation:,.0f} "
          f"cushion={report.cushion*100:.1f}% alerts: {red} red / {yellow} yellow")
```

**Step 3: Move `load_account_configs` to `risk_utils.py`** (or keep in portfolio_risk.py until a clean migration is done — keep it for now, delete later)

**Step 4: Delete old files**
```bash
git rm src/portfolio_risk.py
git rm tests/test_portfolio_risk.py
```

**Step 5: Run full test suite**
```
pytest -q --ignore=tests/agent/test_config.py --ignore=tests/test_financial_service.py
# Expected: all pass
```

**Step 6: Commit**
```bash
git add src/main.py src/risk_store.py
git commit -m "feat: wire Phase 7 three-layer pipeline in main.py, retire portfolio_risk.py"
```

---

## Task 9: Integration test + smoke test with real Flex data

**Files:**
- Create: `tests/test_phase7_integration.py`
- Modify: `tests/test_integration.py`

**Step 1: Add integration tests**

```python
# tests/test_phase7_integration.py
from unittest.mock import patch, MagicMock
from src.option_strategies import OptionStrategyRecognizer
from src.strategy_risk import StrategyRiskEngine
from src.flex_client import PositionRecord, AccountSummary

def _make_position(symbol, asset_category, put_call="", strike=0, expiry="",
                   multiplier=100, position=-5, cost_basis=3.0, mark=2.0,
                   delta=-0.3, underlying="AAPL", currency="USD"):
    return PositionRecord(
        symbol=symbol, asset_category=asset_category, put_call=put_call,
        strike=strike, expiry=expiry, multiplier=multiplier, position=position,
        cost_basis_price=cost_basis, mark_price=mark, unrealized_pnl=0.0,
        delta=delta, gamma=0.02, theta=-0.05, vega=0.15,
        underlying_symbol=underlying, currency=currency,
    )

def test_full_pipeline_naked_put():
    """End-to-end: Flex positions → strategies → risk report."""
    from datetime import date, timedelta
    expiry = (date.today() + timedelta(days=45)).strftime("%Y%m%d")
    p = _make_position("AAPL  P180", "OPT", "P", 180, expiry, position=-5)
    account = AccountSummary(net_liquidation=500000, gross_position_value=0,
                              init_margin_req=0, maint_margin_req=50000,
                              excess_liquidity=0, available_funds=0, cushion=0.30)
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize([p])
    assert strategies[0].strategy_type == "Naked Put"

    engine = StrategyRiskEngine()
    with patch("src.strategy_risk.MarketDataProvider") as MockMDP:
        MockMDP.return_value.get_fundamentals.return_value = {"beta": 1.2}
        report = engine.analyze(strategies, account)

    assert report.net_liquidation == 500000
    assert isinstance(report.summary_stats["stress_test"]["drop_10pct"], float)

def test_full_pipeline_iron_condor():
    """Iron Condor recognized and produces strategy-level risk analysis."""
    from datetime import date, timedelta
    exp = (date.today() + timedelta(days=30)).strftime("%Y%m%d")
    sc = _make_position("AAPL C210", "OPT", "C", 210, exp, position=-3, delta=0.25)
    lc = _make_position("AAPL C220", "OPT", "C", 220, exp, position=3,  delta=0.15)
    sp = _make_position("AAPL P170", "OPT", "P", 170, exp, position=-3, delta=-0.25)
    lp = _make_position("AAPL P160", "OPT", "P", 160, exp, position=3,  delta=-0.15)
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize([sc, lc, sp, lp])
    assert len(strategies) == 1
    assert strategies[0].strategy_type == "Iron Condor"
    assert len(strategies[0].breakevens) == 2

def test_html_report_generated():
    """generate_html_report returns valid HTML for StrategyRiskReport."""
    from src.strategy_risk import StrategyRiskReport
    from src.portfolio_report import generate_html_report
    report = StrategyRiskReport(
        account_id="TEST", report_date="2026-03-11",
        net_liquidation=500000, total_pnl=5000, cushion=0.29,
    )
    html = generate_html_report(report)
    assert "<!DOCTYPE html>" in html
    assert "TEST" in html
```

**Step 2: Run all tests**
```
pytest -q --ignore=tests/agent/test_config.py --ignore=tests/test_financial_service.py
# Expected: all pass
```

**Step 3: Smoke test with real Flex**
```bash
python3 -m src.main --risk-report --account ALICE
open reports/risk_ALICE_$(date +%Y-%m-%d).html
```

**Step 4: Commit**
```bash
git add tests/test_phase7_integration.py
git commit -m "test: add Phase 7 end-to-end integration tests"
```

---

## Task 10: Move `load_account_configs` out of `portfolio_risk.py` + final cleanup

**Files:**
- Modify: `src/risk_utils.py`
- Modify: `src/main.py`
- Delete: `src/portfolio_risk.py` (if not already deleted in Task 8)

**Step 1: Move `load_account_configs` to `risk_utils.py`**

Copy the function (it only uses `os.environ`) — no dependencies on the rest of `portfolio_risk.py`.

**Step 2: Update all imports**

```bash
grep -r "from src.portfolio_risk" src/ tests/
# Fix any remaining imports
```

**Step 3: Update `docs/specs/` to reflect new modules**

Add `docs/specs/option_strategies.md` and `docs/specs/strategy_risk.md` based on the new module structure.

**Step 4: Final test run**
```
pytest -q --ignore=tests/agent/test_config.py --ignore=tests/test_financial_service.py
# Expected: all pass, 0 import errors
```

**Step 5: Final commit**
```bash
git add -u
git commit -m "feat: complete Phase 7 — strategy-aware option risk pipeline"
```

---

## Summary of New Files

| File | Purpose |
|------|---------|
| `src/risk_utils.py` | Shared: CASH_LIKE_TICKERS, get_fx_rate, normalize_ticker, load_account_configs |
| `src/option_strategies.py` | StrategyGroup + OptionStrategyRecognizer (Layer 1) |
| `src/strategy_risk.py` | StrategyRiskAlert + StrategyRiskReport + StrategyRiskEngine + LLM (Layer 2+3) |
| `tests/test_option_strategies.py` | Unit tests for recognition |
| `tests/test_strategy_risk.py` | Unit tests for risk rules |
| `tests/test_phase7_integration.py` | End-to-end pipeline tests |

## Deleted Files

| File | Replaced by |
|------|------------|
| `src/portfolio_risk.py` | `src/risk_utils.py` + `src/strategy_risk.py` |
| `tests/test_portfolio_risk.py` | `tests/test_strategy_risk.py` |
