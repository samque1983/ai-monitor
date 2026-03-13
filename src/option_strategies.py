"""Option strategy recognition — groups raw Flex positions into named strategies."""
from dataclasses import dataclass, field
from datetime import date as _date
from typing import List, Optional, Tuple
from src.flex_client import PositionRecord
from src.risk_utils import CASH_LIKE_TICKERS


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


_INTENT_MAP = {
    "Naked Put": "income", "Cash-Secured Put": "income",
    "Naked Call": "income", "Covered Call": "income",
    "Bull Put Spread": "income", "Bear Call Spread": "income",
    "Ratio Put Spread": "income", "Ratio Call Spread": "income",
    "Iron Condor": "income", "Iron Butterfly": "income",
    "PMCC": "income",
    "Protective Put": "hedge", "Collar": "mixed",
    "Bull Call Spread": "directional", "Bear Put Spread": "directional",
    "Long Stock": "directional", "Short Stock": "directional",
    "Calendar Spread": "mixed", "Diagonal Spread": "mixed",
    "Straddle": "speculation", "Strangle": "speculation",
    "Long Put": "speculation", "Long Call": "speculation",
    "LEAPS Call": "speculation", "LEAPS Put": "hedge",
    "Unclassified": "unknown",
}

_LEAPS_DTE = 365


class OptionStrategyRecognizer:

    def recognize(self, positions: List[PositionRecord]) -> List[StrategyGroup]:
        by_underlying = self._group_by_underlying(positions)
        result = []
        for underlying, pos_list in by_underlying.items():
            consolidated = self._consolidate_positions(pos_list)
            result.extend(self._recognize_underlying(underlying, consolidated))
        return result

    def _consolidate_positions(self, positions: List[PositionRecord]) -> List[PositionRecord]:
        """Merge multiple lots of the same contract into one PositionRecord.

        Two-step process:
        1. Deduplicate exact rows (same contract key + same position size = Flex XML duplicate).
        2. Sum remaining distinct lots of the same contract into one record.
        """
        def _contract_key(p: PositionRecord):
            if p.asset_category == "OPT":
                return (p.asset_category, p.underlying_symbol, p.put_call,
                        p.strike, p.expiry)
            return (p.asset_category, p.symbol)

        # Step 1: deduplicate rows that are identical in every meaningful field
        seen: dict = {}
        deduped = []
        for p in positions:
            dedup_key = (_contract_key(p), p.position, p.cost_basis_price, p.mark_price)
            if dedup_key not in seen:
                seen[dedup_key] = True
                deduped.append(p)

        # Step 2: merge remaining distinct lots (same contract, different position sizes)
        groups: dict = {}
        for p in deduped:
            groups.setdefault(_contract_key(p), []).append(p)

        result = []
        for recs in groups.values():
            if len(recs) == 1:
                result.append(recs[0])
                continue
            total_pos = sum(r.position for r in recs)
            total_pnl = sum(r.unrealized_pnl for r in recs)
            total_abs = sum(abs(r.position) for r in recs)
            if total_abs > 0:
                def _wavg(attr, _recs=recs, _tab=total_abs):
                    return sum(getattr(r, attr) * abs(r.position) for r in _recs) / _tab
                cost = _wavg("cost_basis_price")
                mark = _wavg("mark_price")
                delta = _wavg("delta")
                gamma = _wavg("gamma")
                theta = _wavg("theta")
                vega  = _wavg("vega")
            else:
                cost = mark = delta = gamma = theta = vega = 0.0
            r0 = recs[0]
            result.append(PositionRecord(
                symbol=r0.symbol, asset_category=r0.asset_category,
                put_call=r0.put_call, strike=r0.strike, expiry=r0.expiry,
                multiplier=r0.multiplier, position=total_pos,
                cost_basis_price=cost, mark_price=mark, unrealized_pnl=total_pnl,
                delta=delta, gamma=gamma, theta=theta, vega=vega,
                underlying_symbol=r0.underlying_symbol, currency=r0.currency,
            ))
        return result

    def _group_by_underlying(self, positions: List[PositionRecord]) -> dict:
        groups: dict = {}
        for p in positions:
            key = (p.underlying_symbol if (p.asset_category == "OPT" and p.underlying_symbol)
                   else p.symbol)
            groups.setdefault(key, []).append(p)
        return groups

    def _recognize_underlying(self, underlying: str,
                               positions: List[PositionRecord]) -> List[StrategyGroup]:
        stocks = [p for p in positions if p.asset_category == "STK"]
        opts = [p for p in positions if p.asset_category == "OPT"]
        strategies = []

        # Group opts by expiry and match within each expiry
        by_expiry: dict = {}
        for p in opts:
            by_expiry.setdefault(p.expiry, []).append(p)

        # Track remaining long shares per stock (allows multiple CCs against one large position).
        # Short stocks (position < 0) are not tracked here — they always pass through.
        remaining_shares: dict = {id(s): s.position for s in stocks if s.position > 0}

        claimed_opts = set()
        for expiry, exp_opts in sorted(by_expiry.items()):
            avail_stocks = [s for s in stocks if remaining_shares.get(id(s), 0) > 0]
            sg, used = self._match_expiry_group(exp_opts, avail_stocks, underlying)
            if sg:
                strategies.append(sg)
                claimed_opts.update(id(p) for p in used)
                if sg.stock_leg and id(sg.stock_leg) in remaining_shares:
                    short_calls = [p for p in sg.legs if p.asset_category == "OPT"
                                   and p.put_call == "C" and p.position < 0]
                    if short_calls:
                        shares_used = sum(abs(p.position) * p.multiplier for p in short_calls)
                    else:
                        # Protective Put, Collar without SC, etc. — consume all remaining shares
                        shares_used = remaining_shares[id(sg.stock_leg)]
                    remaining_shares[id(sg.stock_leg)] -= shares_used

        # Keep: long stocks with remaining shares + all short stocks
        stocks = [s for s in stocks
                  if (s.position < 0)
                  or (id(s) in remaining_shares and remaining_shares[id(s)] > 0)]

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

    def _make_single_opt(self, p: PositionRecord, underlying: str) -> StrategyGroup:
        dte = self._calc_dte(p.expiry)
        is_leaps = dte is not None and dte > _LEAPS_DTE
        if p.put_call == "P" and p.position < 0:
            stype = "Naked Put"
        elif p.put_call == "C" and p.position < 0:
            stype = "Naked Call"
        elif p.put_call == "P" and p.position > 0:
            stype = "LEAPS Put" if is_leaps else "Long Put"
        else:
            stype = "LEAPS Call" if is_leaps else "Long Call"
        return StrategyGroup(
            underlying=underlying, strategy_type=stype,
            intent=_INTENT_MAP[stype], legs=[p],
            expiry=p.expiry, currency=p.currency,
        )

    def _calc_dte(self, expiry: str) -> Optional[int]:
        if not expiry or len(expiry) != 8:
            return None
        try:
            exp = _date(int(expiry[:4]), int(expiry[4:6]), int(expiry[6:]))
            return max(0, (exp - _date.today()).days)
        except ValueError:
            return None

    def _match_expiry_group(self, opts: List[PositionRecord],
                             stocks: List[PositionRecord],
                             underlying: str) -> Tuple[Optional[StrategyGroup], list]:
        """Try to match opts + stocks into one strategy. Returns (StrategyGroup|None, used_legs)."""
        puts = sorted([p for p in opts if p.put_call == "P"], key=lambda x: x.strike)
        calls = sorted([p for p in opts if p.put_call == "C"], key=lambda x: x.strike)
        short_puts = [p for p in puts if p.position < 0]
        long_puts = [p for p in puts if p.position > 0]
        short_calls = [p for p in calls if p.position < 0]
        long_calls = [p for p in calls if p.position > 0]
        expiry = opts[0].expiry if opts else ""
        currency = opts[0].currency if opts else (stocks[0].currency if stocks else "USD")

        def _sg(stype, legs, stk=None):
            return StrategyGroup(
                underlying=underlying, strategy_type=stype,
                intent=_INTENT_MAP.get(stype, "unknown"),
                legs=[p for p in legs if p is not stk],
                stock_leg=stk, expiry=expiry, currency=currency,
            ), legs

        # Iron Condor: 1 SC + 1 LC + 1 SP + 1 LP
        if (len(short_calls) == 1 and len(long_calls) == 1
                and len(short_puts) == 1 and len(long_puts) == 1):
            sc, lc = short_calls[0], long_calls[0]
            sp, lp = short_puts[0], long_puts[0]
            if lc.strike > sc.strike and sp.strike > lp.strike:
                if sc.strike == sp.strike:
                    return _sg("Iron Butterfly", [sc, lc, sp, lp])
                return _sg("Iron Condor", [sc, lc, sp, lp])

        # Collar: STK + SC + LP
        if stocks and len(short_calls) == 1 and len(long_puts) == 1 and not long_calls and not short_puts:
            stk = stocks[0]
            return _sg("Collar", [stk, short_calls[0], long_puts[0]], stk)

        # Covered Call: STK + SC
        if stocks and len(short_calls) == 1 and not puts and not long_calls:
            stk = stocks[0]
            return _sg("Covered Call", [stk, short_calls[0]], stk)

        # Protective Put: STK + LP
        if stocks and len(long_puts) == 1 and not calls and not short_puts:
            stk = stocks[0]
            return _sg("Protective Put", [stk, long_puts[0]], stk)

        # Bull Put Spread / Ratio Put Spread: SP (high) + LP (low)
        if len(short_puts) == 1 and long_puts and not calls:
            sp = short_puts[0]
            candidates = [p for p in long_puts if p.strike < sp.strike]
            if candidates:
                lp = max(candidates, key=lambda x: x.strike)
                if abs(sp.position) == abs(lp.position):
                    return _sg("Bull Put Spread", [sp, lp])
                else:
                    return _sg("Ratio Put Spread", [sp, lp])

        # Bear Call Spread / Ratio Call Spread: SC (low) + LC (high)
        if len(short_calls) == 1 and len(long_calls) == 1 and not puts:
            sc, lc = short_calls[0], long_calls[0]
            if sc.strike < lc.strike:
                if abs(sc.position) == abs(lc.position):
                    return _sg("Bear Call Spread", [sc, lc])
                else:
                    return _sg("Ratio Call Spread", [sc, lc])

        # Bull Call Spread: LC (low) + SC (high)
        if len(long_calls) == 1 and len(short_calls) == 1 and not puts:
            lc, sc = long_calls[0], short_calls[0]
            if lc.strike < sc.strike:
                return _sg("Bull Call Spread", [lc, sc])

        # Bear Put Spread: LP (high) + SP (low)
        if len(long_puts) == 1 and len(short_puts) == 1 and not calls:
            lp, sp = long_puts[0], short_puts[0]
            if lp.strike > sp.strike:
                return _sg("Bear Put Spread", [lp, sp])

        # Straddle: Call + Put same strike
        all_calls = calls
        all_puts = puts
        if len(all_calls) == 1 and len(all_puts) == 1 and not stocks:
            c, p = all_calls[0], all_puts[0]
            if c.strike == p.strike and (c.position * p.position > 0):
                return _sg("Straddle", [c, p])

        # Strangle: Call + Put different strike
        if len(all_calls) == 1 and len(all_puts) == 1 and not stocks:
            c, p = all_calls[0], all_puts[0]
            if c.position * p.position > 0:
                return _sg("Strangle", [c, p])

        return None, []

    def _match_calendar(self, remaining_opts: List[PositionRecord],
                         underlying: str) -> Tuple[List[StrategyGroup], List[PositionRecord]]:
        """Match Calendar/Diagonal from cross-expiry options. Returns (strategies, leftover)."""
        strategies = []
        used = set()
        puts = sorted([p for p in remaining_opts if p.put_call == "P"], key=lambda x: x.expiry)
        calls = sorted([p for p in remaining_opts if p.put_call == "C"], key=lambda x: x.expiry)
        for opts_group in [puts, calls]:
            for i, near in enumerate(opts_group):
                if id(near) in used:
                    continue
                for far in opts_group[i + 1:]:
                    if id(far) in used:
                        continue
                    if far.expiry <= near.expiry:
                        continue
                    far_dte = self._calc_dte(far.expiry) or 0
                    if near.strike == far.strike:
                        stype = "Calendar Spread"
                    elif (near.position < 0 and far.position > 0
                          and far_dte > _LEAPS_DTE and near.put_call == "C"):
                        stype = "PMCC"
                    else:
                        stype = "Diagonal Spread"
                    sg = StrategyGroup(
                        underlying=underlying, strategy_type=stype,
                        intent=_INTENT_MAP[stype],
                        legs=[near, far], expiry=far.expiry,
                        currency=near.currency,
                    )
                    strategies.append(sg)
                    used.add(id(near))
                    used.add(id(far))
                    break
        leftover = [p for p in remaining_opts if id(p) not in used]
        return strategies, leftover

    def _attach_modifiers(self, strategies: List[StrategyGroup],
                           underlying: str) -> List[StrategyGroup]:
        """Second pass: attach unmatched long puts/calls as protective modifiers."""
        single_longs = [sg for sg in strategies
                        if sg.strategy_type in ("Long Put", "Long Call")
                        and len(sg.legs) == 1
                        and not (sg.legs[0].expiry and self._calc_dte(sg.legs[0].expiry) is not None
                                 and self._calc_dte(sg.legs[0].expiry) > _LEAPS_DTE)]
        non_single = [sg for sg in strategies if sg not in single_longs]
        used = set()
        for mod_sg in single_longs:
            mod = mod_sg.legs[0]
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

    def _compute_metrics(self, sg: StrategyGroup) -> None:
        """Compute net Greeks, max_profit/loss, breakevens, DTE, net_pnl, net_credit."""
        all_opts = sg.legs + sg.modifiers
        # Cash-like ETFs (SGOV, BIL, etc.) have no directional equity exposure
        if sg.underlying in CASH_LIKE_TICKERS:
            sg.net_delta = 0.0
        elif sg.stock_leg:
            all_opts_only = [p for p in all_opts if p.asset_category == "OPT"]
            sg.net_delta = sg.stock_leg.position + sum(
                p.delta * p.position * p.multiplier for p in all_opts_only)
        else:
            sg.net_delta = sum(p.delta * p.position * p.multiplier for p in all_opts
                               if p.asset_category == "OPT")
        sg.net_theta = sum(p.theta * p.position * p.multiplier for p in all_opts
                           if p.asset_category == "OPT")
        sg.net_vega = sum(p.vega * p.position * p.multiplier for p in all_opts
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

        self._compute_payoff(sg, opt_legs)

    def _compute_payoff(self, sg: StrategyGroup, opt_legs: List[PositionRecord]) -> None:
        """Compute max_profit, max_loss, breakevens per strategy type."""
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

        elif stype in ("Ratio Put Spread", "Ratio Call Spread"):
            short_leg = next(p for p in opt_legs if p.position < 0)
            long_leg  = next(p for p in opt_legs if p.position > 0)
            short_qty = abs(short_leg.position)
            long_qty  = abs(long_leg.position)
            # Net credit/debit already in sg.net_credit
            sg.max_profit = sg.net_credit if sg.net_credit > 0 else None
            uncovered = short_qty - long_qty
            if uncovered > 0 and stype == "Ratio Call Spread":
                sg.max_loss = None  # Truly unlimited: stock can rise without bound
            elif uncovered > 0 and stype == "Ratio Put Spread":
                # Stock floors at $0: bounded max loss at stock = 0
                sg.max_loss = max(0.0,
                                  (short_qty * short_leg.strike - long_qty * long_leg.strike)
                                  * mult - sg.net_credit)
            else:
                sg.max_loss = abs(sg.net_credit)
            if stype == "Ratio Put Spread":
                sg.breakevens = [short_leg.strike - sg.net_credit / short_qty / mult]
            else:
                sg.breakevens = [short_leg.strike + sg.net_credit / short_qty / mult]

        elif stype in ("Bull Call Spread", "Bear Put Spread"):
            strikes = sorted(p.strike for p in opt_legs)
            width = strikes[1] - strikes[0]
            sg.max_loss = abs(sg.net_credit)
            sg.max_profit = (width - abs(credit_per_contract)) * mult * contracts
            long_p = next(p for p in opt_legs if p.position > 0)
            sg.breakevens = [long_p.strike + abs(credit_per_contract)]

        elif stype in ("Iron Condor", "Iron Butterfly"):
            short_puts = [p for p in opt_legs if p.put_call == "P" and p.position < 0]
            short_calls = [p for p in opt_legs if p.put_call == "C" and p.position < 0]
            if short_puts and short_calls:
                sp_strike = short_puts[0].strike
                sc_strike = short_calls[0].strike
                sg.max_profit = sg.net_credit
                put_strikes = sorted(p.strike for p in opt_legs if p.put_call == "P")
                call_strikes = sorted(p.strike for p in opt_legs if p.put_call == "C")
                put_width = put_strikes[1] - put_strikes[0]
                call_width = call_strikes[1] - call_strikes[0]
                max_width = max(put_width, call_width)
                sg.max_loss = (max_width - credit_per_contract) * mult * contracts
                sg.breakevens = [sp_strike - credit_per_contract,
                                 sc_strike + credit_per_contract]

        elif stype == "Naked Put":
            sp = opt_legs[0]
            sg.max_profit = sg.net_credit
            # Stock floors at $0 — max loss is bounded, not unlimited
            sg.max_loss = (sp.strike - credit_per_contract) * mult * contracts
            sg.breakevens = [sp.strike - credit_per_contract]

        elif stype == "Naked Call":
            sc = opt_legs[0]
            sg.max_profit = sg.net_credit
            sg.max_loss = None  # Truly unlimited: stock can rise without bound
            sg.breakevens = [sc.strike + credit_per_contract]

        elif stype == "Covered Call":
            sc = next((p for p in opt_legs if p.put_call == "C"), None)
            stk = sg.stock_leg
            if sc and stk:
                # Fallback to mark_price if cost_basis is missing (e.g. transferred positions)
                basis = stk.cost_basis_price if stk.cost_basis_price > 0 else stk.mark_price
                sg.max_profit = ((sc.strike - basis) * stk.position + sg.net_credit)
                # Stock goes to $0 — bounded by cost basis minus premium received
                sg.max_loss = basis * abs(stk.position) - sg.net_credit
                sg.breakevens = [basis - credit_per_contract]

        elif stype in ("Diagonal Spread", "Calendar Spread", "PMCC"):
            # Approximate max loss: net debit paid (if debit) or spread-width worst-case (if credit).
            # For a put diagonal where short_strike > long_strike and net credit received,
            # worst case at near-term expiry = (short_strike - long_strike) * mult * contracts - net_credit.
            short_legs = [p for p in opt_legs if p.position < 0]
            long_legs  = [p for p in opt_legs if p.position > 0]
            if short_legs and long_legs:
                short_leg = short_legs[0]
                long_leg  = long_legs[0]
                diag_contracts = abs(short_leg.position)
                if sg.net_credit <= 0:
                    # Net debit paid: max loss = net debit
                    sg.max_loss = abs(sg.net_credit)
                else:
                    # Net credit received: worst case is spread-width loss minus credit
                    strike_diff = abs(short_leg.strike - long_leg.strike)
                    sg.max_loss = max(0.0,
                                     (strike_diff - sg.net_credit / diag_contracts / mult)
                                     * mult * diag_contracts)

        elif stype in ("Long Call", "Long Put", "LEAPS Call", "LEAPS Put",
                       "Straddle", "Strangle"):
            # Max loss = premium paid (net debit). net_credit is negative for long positions.
            sg.max_loss = max(0.0, abs(sg.net_credit))
            sg.max_profit = None  # Unlimited for calls/straddles; leave None for simplicity

        elif stype == "Long Stock":
            stk = sg.stock_leg
            if stk:
                basis = stk.cost_basis_price if stk.cost_basis_price > 0 else stk.mark_price
                sg.max_loss = basis * abs(stk.position)
                sg.max_profit = None  # Unlimited upside

        elif stype == "Short Stock":
            sg.max_loss = None  # Truly unlimited: stock can rise without bound

        elif stype == "Protective Put":
            stk = sg.stock_leg
            lp = next((p for p in opt_legs if p.put_call == "P"), None)
            if stk and lp:
                basis = stk.cost_basis_price if stk.cost_basis_price > 0 else stk.mark_price
                # Max loss = downside below put strike + premium paid
                sg.max_loss = max(0.0, (basis - lp.strike) * abs(stk.position) + abs(sg.net_credit))
                sg.max_profit = None  # Stock can rise without bound

        elif stype == "Collar":
            stk = sg.stock_leg
            lp = next((p for p in opt_legs if p.put_call == "P"), None)
            if stk and lp:
                basis = stk.cost_basis_price if stk.cost_basis_price > 0 else stk.mark_price
                # Max loss = downside below put strike minus net premium received
                sg.max_loss = max(0.0, (basis - lp.strike) * abs(stk.position) - sg.net_credit)
