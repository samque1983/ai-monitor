"""Portfolio risk analysis — data models, config loader, dimension calculations."""
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from src.llm_client import make_llm_client_from_env
from src.market_data import MarketDataProvider


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class AccountConfig:
    key: str           # env key prefix (e.g. "ALICE")
    name: str
    code: str
    flex_token: str
    flex_query_id: str


@dataclass
class RiskAlert:
    dimension: int
    level: str         # "yellow" | "red"
    ticker: str
    detail: str
    options: List[str] = field(default_factory=list)
    ai_suggestion: str = ""


@dataclass
class RiskReport:
    account_id: str
    report_date: str   # ISO date string "YYYY-MM-DD"
    net_liquidation: float
    total_pnl: float
    cushion: float
    alerts: List[RiskAlert] = field(default_factory=list)
    summary_stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

def load_account_configs() -> List[AccountConfig]:
    """Scan os.environ for ACCOUNT_*_FLEX_TOKEN pattern and return configs."""
    configs = []
    seen_keys = set()
    for env_key, val in os.environ.items():
        m = re.match(r"^ACCOUNT_([A-Z0-9_]+)_FLEX_TOKEN$", env_key)
        if not m:
            continue
        key = m.group(1)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        query_id = os.environ.get(f"ACCOUNT_{key}_FLEX_QUERY_ID", "")
        name = os.environ.get(f"ACCOUNT_{key}_NAME", key)
        code = os.environ.get(f"ACCOUNT_{key}_CODE", "")
        configs.append(AccountConfig(
            key=key,
            name=name,
            code=code,
            flex_token=val,
            flex_query_id=query_id,
        ))
    return configs


# ---------------------------------------------------------------------------
# Risk analyzer
# ---------------------------------------------------------------------------

class PortfolioRiskAnalyzer:

    def analyze(self, positions: List, account) -> RiskReport:
        from datetime import date as _date
        today = _date.today().isoformat()
        total_pnl = sum(p.unrealized_pnl for p in positions)
        alerts = []
        alerts += self._dim1_dollar_delta(positions, account)
        alerts += self._dim2_theta(positions)
        alerts += self._dim3_vega(positions)
        alerts += self._dim4_margin(account)
        alerts += self._dim5_concentration(positions, account)
        alerts += self._dim6_earnings(positions)
        alerts += self._dim7_dte_moneyness(positions)
        alerts += self._dim8_sell_put_cushion(positions)
        alerts += self._dim9_gamma_near_expiry(positions)
        summary_stats = {
            "net_liquidation": account.net_liquidation,
            "total_unrealized_pnl": total_pnl,
            "cushion": account.cushion,
        }
        dim10_alerts, stress = self._dim10_stress_test(positions, account)
        alerts += dim10_alerts
        summary_stats["stress_test"] = stress
        return RiskReport(
            account_id="",
            report_date=today,
            net_liquidation=account.net_liquidation,
            total_pnl=total_pnl,
            cushion=account.cushion,
            alerts=alerts,
            summary_stats=summary_stats,
        )

    def _sign(self, x: float) -> float:
        return 1.0 if x >= 0 else -1.0

    def _has_protective_long_put(self, short_p, positions) -> bool:
        """Return True if short_p has a long put at same (symbol, expiry) with lower strike."""
        return any(
            o.symbol == short_p.symbol and o.expiry == short_p.expiry
            and o.asset_category == "OPT" and o.put_call == "P"
            and o.position > 0 and o.strike < short_p.strike
            for o in positions
        )

    @staticmethod
    def _dte(expiry_str: str) -> Optional[int]:
        """Compute days-to-expiry from 'YYYYMMDD' string. Returns None if blank."""
        if not expiry_str or len(expiry_str) != 8:
            return None
        from datetime import date as _date
        exp = _date(int(expiry_str[:4]), int(expiry_str[4:6]), int(expiry_str[6:]))
        return (exp - _date.today()).days

    def _dim1_dollar_delta(self, positions, account) -> List[RiskAlert]:
        # Build underlying price map from stock positions
        underlying_prices = {
            p.symbol: p.mark_price for p in positions if p.asset_category == "STK"
        }
        total_dollar_delta = 0.0
        for p in positions:
            if p.asset_category == "STK":
                total_dollar_delta += p.position * p.mark_price
            elif p.asset_category == "OPT":
                u_price = underlying_prices.get(p.symbol, p.strike)
                total_dollar_delta += p.position * p.delta * p.multiplier * u_price
        nlv = account.net_liquidation
        if nlv <= 0:
            return []
        ratio = total_dollar_delta / nlv
        if ratio > 1.20:
            level = "red"
        elif ratio > 0.80:
            level = "yellow"
        else:
            return []
        return [RiskAlert(
            dimension=1,
            level=level,
            ticker="PORTFOLIO",
            detail=f"Dollar Delta ${total_dollar_delta:,.0f} ({ratio*100:.0f}% NLV)",
            options=[
                "A. 卖出部分股票仓位，降低整体 Delta 至 80% 以内",
                "B. 买入 Put（指数或个股）作为对冲",
                "C. 卖出 Covered Call，降低净 Delta 同时收取权利金",
                "D. 维持现状，接受当前敞口（若看多市场）",
            ],
        )]

    def _dim2_theta(self, positions) -> List[RiskAlert]:
        net_theta = sum(
            p.theta * p.multiplier * abs(p.position) * self._sign(p.position)
            for p in positions
        )
        if net_theta >= 0:
            return []
        daily_theta = net_theta
        return [RiskAlert(
            dimension=2,
            level="yellow",
            ticker="PORTFOLIO",
            detail=f"净 Theta {daily_theta:+.2f}/天（净期权买方）",
            options=[
                "A. 平仓部分期权买方仓位，止住时间损耗",
                "B. 等待目标催化剂（财报/事件）兑现后再平仓",
                "C. 将买方仓位转为价差（Spread），降低 Theta 成本",
                "D. 维持现状（若认为标的即将出现大幅波动）",
            ],
        )]

    def _dim3_vega(self, positions) -> List[RiskAlert]:
        net_vega = sum(
            p.vega * p.multiplier * abs(p.position) * self._sign(p.position)
            for p in positions
        )
        if net_vega >= 0:
            return []
        return [RiskAlert(
            dimension=3,
            level="yellow",
            ticker="PORTFOLIO",
            detail=f"净 Vega {net_vega:+.2f}/1%IV（空 Vega）",
            options=[
                "A. 买回部分空头期权平仓，降低 Vega 敞口",
                "B. 买入 VIX Call 或 SPY Put 作为 Vega 对冲",
                "C. 等待 IV 回落后再决定",
                "D. 无操作（若 Theta 收益能抵消 Vega 亏损）",
            ],
        )]

    def _dim4_margin(self, account) -> List[RiskAlert]:
        c = account.cushion
        if c >= 0.25:
            return []
        level = "red" if c < 0.10 else "yellow"
        return [RiskAlert(
            dimension=4,
            level=level,
            ticker="ACCOUNT",
            detail=f"保证金缓冲 {c*100:.1f}%（维持保证金 ${account.maint_margin_req:,.0f}）",
            options=[
                "A. 平仓保证金占用最大的仓位（裸 Sell Put），立即释放保证金",
                "B. 存入现金至账户，直接提升 cushion",
                "C. 将裸 Sell Put 转为 Put Spread，大幅降低保证金要求",
                "D. 维持现状，等待期权到期自然释放保证金",
            ],
        )]

    def _dim5_concentration(self, positions, account) -> List[RiskAlert]:
        nlv = account.net_liquidation
        if nlv <= 0:
            return []
        notional_by_symbol: dict = {}
        for p in positions:
            if p.asset_category == "STK":
                notional = abs(p.position) * p.mark_price * p.multiplier
            else:
                # Options: use strike-based notional (actual max exposure at assignment)
                notional = p.strike * p.multiplier * abs(p.position)
            notional_by_symbol[p.symbol] = notional_by_symbol.get(p.symbol, 0) + notional
        alerts = []
        for symbol, notional in notional_by_symbol.items():
            ratio = notional / nlv
            if ratio > 0.20:
                alerts.append(RiskAlert(
                    dimension=5,
                    level="yellow",
                    ticker=symbol,
                    detail=f"{symbol} 占组合 {ratio*100:.1f}%（${notional:,.0f} / NLV ${nlv:,.0f}）",
                    options=[
                        f"A. 分批减持 {symbol} 至目标比例（25–30%）",
                        f"B. 买入 {symbol} Put 做局部对冲，持仓不变但加保险",
                        "C. 暂不减仓，但设定止损线（如跌破 MA200 时触发减仓）",
                        "D. 维持现状（若高仓位为有意策略）",
                    ],
                ))
        return alerts

    def _dim6_earnings(self, positions) -> List[RiskAlert]:
        """Alert if option expiry crosses earnings date."""
        alerts = []
        for p in positions:
            if p.asset_category != "OPT":
                continue
            try:
                underlying = p.underlying_symbol or p.symbol
                mdp = MarketDataProvider()
                earnings_date, days_to = mdp.get_earnings_date(underlying)
            except Exception:
                continue
            if earnings_date is None or days_to is None:
                continue
            triggered = False
            reason = ""
            if days_to <= 14:
                triggered = True
                reason = f"财报在 {days_to} 天后（{earnings_date}）"
            if p.expiry:
                dte = self._dte(p.expiry)
                if dte is not None and dte > days_to:
                    triggered = True
                    reason = f"期权到期（{p.expiry}）在财报后（{earnings_date}，{days_to}d）"
            if triggered:
                alerts.append(RiskAlert(
                    dimension=6,
                    level="red",
                    ticker=p.symbol,
                    detail=f"{p.symbol} {p.put_call} {p.strike:.0f}P — {reason}",
                    options=[
                        "A. 财报前平仓，锁定当前已实现收益",
                        "B. Roll 到财报前到期，财报前自然了结",
                        "C. Roll 降低行权价，扩大安全垫至历史均值以上",
                        "D. 维持现状，接受财报风险（若看好不会大跌）",
                    ],
                ))
        return alerts

    def _dim7_dte_moneyness(self, positions) -> List[RiskAlert]:
        alerts = []
        for p in positions:
            if p.asset_category != "OPT":
                continue
            dte = self._dte(p.expiry)
            if dte is None:
                continue
            itm = p.put_call == "P" and p.mark_price < p.strike
            short_dte = dte <= 14
            if not (itm or short_dte):
                continue
            reasons = []
            if itm:
                pct = (p.strike - p.mark_price) / p.mark_price * 100
                reasons.append(f"已实值 {pct:.1f}%")
            if short_dte:
                reasons.append(f"DTE {dte} 天")
            is_spread = (p.position < 0 and self._has_protective_long_put(p, positions))
            level = "yellow" if is_spread else "red"
            alerts.append(RiskAlert(
                dimension=7,
                level=level,
                ticker=p.symbol,
                detail=f"{p.symbol} {p.put_call}{p.strike:.0f} — {', '.join(reasons)}"
                       + (" [Spread]" if is_spread else ""),
                options=[
                    "A. 立即平仓，接受亏损止损",
                    "B. 接受指派，以行权价承接底层股票",
                    "C. Roll 延期至下月更低行权价",
                    "D. 等待到期日前反弹",
                ],
            ))
        return alerts

    def _dim8_sell_put_cushion(self, positions) -> List[RiskAlert]:
        alerts = []
        for p in positions:
            if not (p.asset_category == "OPT" and p.put_call == "P" and p.position < 0):
                continue
            if p.strike <= 0:
                continue
            # Detect spread: find a long put at same (symbol, expiry) with lower strike
            protective = next((
                o for o in positions
                if o.symbol == p.symbol and o.expiry == p.expiry
                and o.asset_category == "OPT" and o.put_call == "P"
                and o.position > 0 and o.strike < p.strike
            ), None)
            if protective:
                net_received = abs(p.cost_basis_price) - abs(protective.cost_basis_price)
                net_current = max(abs(p.mark_price) - abs(protective.mark_price), 0)
                collected = net_received
                current_price = net_current
            else:
                collected = abs(p.cost_basis_price)
                current_price = abs(p.mark_price)
            if collected <= 0:
                continue
            realized_pct = (collected - current_price) / collected
            triggered = False
            reasons = []
            if realized_pct > 0.75:
                triggered = True
                reasons.append(f"已实现 {realized_pct*100:.0f}% 收益（可考虑锁利）")
            if triggered:
                alerts.append(RiskAlert(
                    dimension=8,
                    level="yellow",
                    ticker=p.symbol,
                    detail=f"{p.symbol} {p.put_call}{p.strike:.0f} — {', '.join(reasons)}",
                    options=[
                        "A. 平仓锁利（买回 Put），释放保证金",
                        "B. 继续持有至到期，争取全部权利金",
                        "C. Roll 至更高行权价，扩大安全垫同时增加权利金",
                        "D. 维持现状并设止损（标的跌至行权价即平仓）",
                    ],
                ))
        return alerts

    def _dim9_gamma_near_expiry(self, positions) -> List[RiskAlert]:
        alerts = []
        for p in positions:
            if p.asset_category != "OPT":
                continue
            dte = self._dte(p.expiry)
            if dte is None or dte > 14:
                continue
            if abs(p.gamma) <= 0.05:
                continue
            alerts.append(RiskAlert(
                dimension=9,
                level="yellow",
                ticker=p.symbol,
                detail=f"{p.symbol} {p.put_call}{p.strike:.0f} — DTE {dte}天, Gamma {p.gamma:.3f}",
                options=[
                    "A. 减半仓位（买回部分），降低 Gamma 敞口",
                    "B. 平仓全部，彻底退出高 Gamma 风险区",
                    "C. 买入更低行权价的 Put 构成 Put Spread",
                    "D. 维持并密切监控（安全垫 > 5% 时可选）",
                ],
            ))
        return alerts

    def _dim10_stress_test(self, positions, account) -> tuple:
        """Returns (alerts, stress_dict). stress_dict always populated."""
        nlv = account.net_liquidation
        mdp = MarketDataProvider()
        total_loss_10 = 0.0
        total_loss_20 = 0.0
        max_assignment_loss = 0.0
        for p in positions:
            try:
                underlying = p.underlying_symbol or p.symbol
                fund = mdp.get_fundamentals(underlying)
                beta = float(fund.get("beta") or 1.0)
            except Exception:
                beta = 1.0
            dollar_delta = p.delta * p.multiplier * abs(p.position) * p.mark_price
            total_loss_10 += dollar_delta * beta * 0.10
            total_loss_20 += dollar_delta * beta * 0.20
            if p.asset_category == "OPT" and p.put_call == "P" and p.position < 0:
                max_assignment_loss += p.strike * p.multiplier * abs(p.position)
        stress = {
            "drop_10pct": -abs(total_loss_10),
            "drop_20pct": -abs(total_loss_20),
            "max_assignment_loss": -max_assignment_loss,
        }
        alerts = []
        if nlv > 0:
            ratio_10 = abs(total_loss_10) / nlv
            if ratio_10 > 0.20:
                level = "red"
            elif ratio_10 > 0.10:
                level = "yellow"
            else:
                level = None
            if level:
                alerts.append(RiskAlert(
                    dimension=10,
                    level=level,
                    ticker="PORTFOLIO",
                    detail=f"大盘跌10%预估亏损 ${abs(total_loss_10):,.0f} ({ratio_10*100:.1f}% NLV)",
                    options=[
                        "A. 买入 SPY Put（大盘对冲），为整体组合加保险",
                        "B. 降低高 Beta 个股仓位，降低组合 Beta",
                        "C. 将部分裸 Sell Put 转 Put Spread，限制极端情景最大亏损",
                        "D. 维持现状（若认为近期大盘下跌概率低）",
                    ],
                ))
        return alerts, stress


# ---------------------------------------------------------------------------
# LLM suggestions
# ---------------------------------------------------------------------------

_RULE_FALLBACKS = {
    (1, "yellow"): "Delta 敞口超过 80%，市场单日下跌 1% 将造成明显损失。建议评估是否需要通过 Put 对冲或减仓降低方向性风险。",
    (1, "red"): "Delta 敞口超过 120%，杠杆较高，建议优先减仓或买 Put 对冲。",
    (2, "yellow"): "组合净 Theta 为负，每日消耗时间价值。确认是否有近期催化剂，否则考虑转为价差结构降低成本。",
    (3, "yellow"): "组合空 Vega，IV 上升时承压。若 DTE > 30 天，建议适当降低 Vega 敞口。",
    (4, "yellow"): "保证金缓冲低于 25%，市场下跌可能触发追保。转 Put Spread 或存入现金可有效改善。",
    (4, "red"): "保证金缓冲低于 10%，存在追保风险。建议立即平仓最大保证金占用仓位。",
    (5, "yellow"): "单股集中度超过 20%，建议设定止损线或逐步分散至其他标的。",
    (6, "red"): "财报穿越风险：期权到期在财报后，历史跳空可能击穿安全垫。建议财报前平仓或 Roll 到财报前到期。",
    (7, "red"): "期权已实值或 DTE ≤ 14 天，被指派风险上升。需尽快决定是平仓、接受指派还是 Roll 延期。",
    (8, "yellow"): "Sell Put 已实现超过 75% 收益，剩余收益空间有限但风险持续。经典原则建议锁利平仓。",
    (9, "yellow"): "高 Gamma 叠加临近到期，P&L 曲线呈非线性变化，普通止损难以管理。考虑减半仓位或构建 Put Spread。",
    (10, "yellow"): "大盘跌 10% 时预估亏损超过净资产 10%。考虑买 SPY Put 对冲或将裸 Sell Put 转为 Put Spread。",
    (10, "red"): "大盘跌 10% 时预估亏损超过净资产 20%，下行风险偏高。建议优先降低高 Beta 仓位或加保险。",
}

_PROMPT_TEMPLATES = {
    1: "当前组合 Dollar Delta 为 {detail}。请用 50-100 字中文分析：当前处境 → 各选项（{options}）权衡 → 推荐哪个及理由。只陈述条件和逻辑，不作主观买卖判断。",
    2: "当前组合 {detail}。请用 50-100 字中文分析：当前处境 → 各选项权衡 → 推荐选项。只陈述条件和逻辑。",
    3: "当前组合 {detail}。请用 50-100 字中文分析：当前处境 → 各选项权衡 → 推荐选项。",
    4: "账户 {detail}。请用 50-100 字中文分析：当前处境 → 各选项（{options}）权衡 → 推荐选项及理由。",
    5: "{detail}。请用 50-100 字中文分析集中度风险 → 各选项权衡 → 推荐选项。",
    6: "{detail}。财报穿越风险，请用 50-100 字中文分析：当前处境 → 各选项权衡 → 推荐选项。",
    7: "{detail}。请用 50-100 字中文分析期权到期风险 → 各选项权衡 → 推荐选项。",
    8: "{detail}。请用 50-100 字中文分析：Sell Put 已实现收益高，继续持有的风险收益比 → 推荐选项。",
    9: "{detail}。高 Gamma 临近到期，请用 50-100 字中文分析风险 → 各选项权衡 → 推荐选项。",
    10: "{detail}。压力测试预警，请用 50-100 字中文分析：当前处境 → 各选项权衡 → 推荐选项。",
}


def _has_llm_key() -> bool:
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("DEEPSEEK_API_KEY")
    )


def generate_risk_suggestion(alert: RiskAlert, llm_config: dict) -> str:
    """Generate AI suggestion for a risk alert. Falls back to rule text on any failure."""
    fallback = _RULE_FALLBACKS.get((alert.dimension, alert.level), "请根据具体情况评估操作选项。")
    if not _has_llm_key():
        return fallback
    try:
        api_key = llm_config.get("api_key", "")
        model = llm_config.get("model", "claude-haiku-4-5-20251001")
        client = make_llm_client_from_env(model=model, api_key=api_key)
        template = _PROMPT_TEMPLATES.get(alert.dimension, "{detail}。请分析风险并推荐操作。")
        options_str = " / ".join(alert.options[:4]) if alert.options else ""
        prompt = template.format(detail=alert.detail, options=options_str)
        return client.simple_chat(
            "你是专业期权风险管理顾问。用50-100字中文回复，只陈述条件和逻辑，末尾注明推荐选项。不作主观买卖判断。",
            prompt,
            max_tokens=200,
        )
    except Exception:
        return fallback
