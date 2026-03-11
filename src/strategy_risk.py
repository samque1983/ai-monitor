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
    plain: str              # plain-language explanation
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
        nlv = account.net_liquidation
        alerts: List[StrategyRiskAlert] = []

        # Per-strategy rules
        for sg in strategies:
            alerts.extend(self._apply_strategy_rules(sg, account))

        # Portfolio-level rules (pass 1 — no stress yet)
        alerts.extend(self._apply_portfolio_rules(strategies, account))

        # Stress test
        stress = self._compute_stress(strategies, account)

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
                    technical=f"大盘跌10%预估亏损 ${stress_loss:,.0f} ({ratio * 100:.1f}% NLV)",
                    plain=f"如果大盘整体下跌10%，你的组合预计亏损 ${stress_loss:,.0f}，占净资产 {ratio * 100:.1f}%。整体下行保护不足。",
                    options=["A. 买入 SPY Put 对冲系统性风险",
                             "B. 降低高 Beta 仓位",
                             "C. 将裸 Sell Put 转为价差结构",
                             "D. 维持现状（若认为近期下跌概率低）"],
                ))

        # Sort + build top_actions
        _URGENT_RULES = {1, 2, 4, 6, 7, 8}

        def _sort_key(a):
            sev_order = {"red": 0, "yellow": 1, "watch": 2}
            return (sev_order.get(a.severity, 3),
                    0 if a.urgency or a.rule_id in _URGENT_RULES else 1)

        alerts.sort(key=_sort_key)

        report = StrategyRiskReport(
            account_id="",
            report_date=today,
            net_liquidation=nlv,
            total_pnl=total_pnl,
            cushion=account.cushion,
            strategies=strategies,
            alerts=alerts,
            summary_stats={"stress_test": stress},
        )
        report.top_actions = [a for a in alerts if a.severity == "red"][:5]
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

            # Rule 1: DTE ≤ 7 AND short put ITM > 2%
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
                        plain=f"你持有裸空仓（没有任何保护）且快到期，实值 {max(0, itm_pct):.1f}%。没有下行保护，亏损可能继续扩大。",
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
                    technical=f"{sg.underlying} {sg.strategy_type} — 已实现 {realized_pct * 100:.0f}% 收益",
                    plain=f"你的 {sg.underlying} 策略已经赚到了 {realized_pct * 100:.0f}% 的预期收益。继续持有只剩 {(1 - realized_pct) * 100:.0f}% 的空间，但风险还在。经典原则建议此时平仓锁利。",
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

    def _apply_portfolio_rules(self, strategies: List[StrategyGroup],
                                account: AccountSummary) -> List[StrategyRiskAlert]:
        alerts = []
        nlv = account.net_liquidation
        cushion = account.cushion

        # Rule 4: margin critical
        if cushion < 0.10:
            alerts.append(StrategyRiskAlert(
                rule_id=4, severity="red", urgency=True,
                strategy_ref=None, underlying="ACCOUNT",
                title="保证金危险",
                technical=f"账户 cushion {cushion * 100:.1f}%，维持保证金 ${account.maint_margin_req:,.0f}",
                plain=f"你的账户保证金缓冲只有 {cushion * 100:.1f}%。如果市场下跌，券商随时可能强制平仓你的仓位。需要立即减仓或存入现金。",
                options=["A. 平仓最大保证金占用仓位", "B. 存入现金提升 cushion",
                         "C. 将裸 Sell Put 转为价差结构", "D. 等待期权到期自然释放"],
            ))
        elif cushion < 0.20:
            alerts.append(StrategyRiskAlert(
                rule_id=14, severity="yellow", urgency=False,
                strategy_ref=None, underlying="ACCOUNT",
                title="保证金偏紧",
                technical=f"账户 cushion {cushion * 100:.1f}%",
                plain=f"保证金缓冲 {cushion * 100:.1f}%，低于安全线 25%。市场波动时有追保压力。",
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
                        technical=f"{und} 净风险敞口 ${notional:,.0f} ({ratio * 100:.1f}% NLV)",
                        plain=f"你在 {und} 上的风险敞口占账户净资产的 {ratio * 100:.1f}%。如果这只股票大跌，对整个账户的冲击会非常严重。",
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
                        technical=f"{und} 净风险敞口 ${notional:,.0f} ({ratio * 100:.1f}% NLV)",
                        plain=f"{und} 在组合中占比 {ratio * 100:.1f}%，超过建议的 20%。",
                        options=[f"A. 逐步减持 {und}", f"B. 买 Put 对冲",
                                 "C. 设止损线", "D. 维持现状"],
                    ))

        # Rule 15: net portfolio delta > 80% NLV
        if nlv > 0:
            net_delta_dollars = sum(
                sg.net_delta * (
                    sg.stock_leg.mark_price if sg.stock_leg else
                    next((p.strike for p in sg.legs if p.asset_category == "OPT"), 100)
                ) for sg in strategies
            )
            if abs(net_delta_dollars) > nlv * 0.80:
                alerts.append(StrategyRiskAlert(
                    rule_id=15, severity="watch", urgency=False,
                    strategy_ref=None, underlying="PORTFOLIO",
                    title="方向性敞口偏大",
                    technical=f"净 Delta 敞口约 ${abs(net_delta_dollars):,.0f} ({abs(net_delta_dollars) / nlv * 100:.0f}% NLV)",
                    plain=f"整体组合的方向性押注相当于净资产的 {abs(net_delta_dollars) / nlv * 100:.0f}%。市场大幅波动时风险较集中。",
                    options=["A. 减少方向性仓位", "B. 买入 Put 对冲",
                             "C. 增加空 Call 降低 Delta", "D. 维持现状"],
                ))

        return alerts

    def _compute_stress(self, strategies: List[StrategyGroup],
                         account: AccountSummary) -> dict:
        nlv = account.net_liquidation
        mdp = MarketDataProvider()
        total_loss_10 = 0.0
        underlying_prices = {
            p.symbol: p.mark_price * get_fx_rate(p.currency)
            for sg in strategies
            for p in ([sg.stock_leg] if sg.stock_leg else []) + sg.legs
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
            stock_legs = [sg.stock_leg] if sg.stock_leg else []
            for p in stock_legs + sg.legs + (sg.modifiers or []):
                fx = get_fx_rate(p.currency)
                if p.asset_category == "STK":
                    dollar_delta = p.position * p.mark_price * fx
                else:
                    u_price = underlying_prices.get(sg.underlying, p.strike * fx)
                    dollar_delta = p.delta * p.position * p.multiplier * u_price
                total_loss_10 += dollar_delta * beta * 0.10

        return {
            "drop_10pct": -total_loss_10,
            "drop_20pct": -total_loss_10 * 2,
        }


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
        prompt = (f"账户净资产 ${report.net_liquidation:,.0f}，cushion {report.cushion * 100:.1f}%，"
                  f"{red} 红色预警、{yellow} 黄色。\n主要预警：\n{top_alerts}\n\n"
                  f"请用80-120字总结核心风险和今日最优先操作。")
        return client.simple_chat(
            "你是专业期权风险管理顾问，用中文回复。", prompt, max_tokens=300)
    except Exception:
        return fallback
