"""Generate strategy-aware HTML risk report from StrategyRiskReport."""
import re
from html import escape as _e

try:
    from src.strategy_risk import StrategyRiskReport, StrategyRiskAlert
    from src.option_strategies import StrategyGroup
    _HAS_STRATEGY_RISK = True
except ImportError:
    _HAS_STRATEGY_RISK = False

_LEVEL_COLOR = {"red": "#ff453a", "yellow": "#ffb340", "watch": "#636366"}
_LEVEL_BG = {"red": "rgba(255,69,58,0.10)", "yellow": "rgba(255,179,64,0.09)",
             "watch": "rgba(99,99,102,0.10)"}
_LEVEL_BORDER = {"red": "rgba(255,69,58,0.22)", "yellow": "rgba(255,179,64,0.20)",
                 "watch": "rgba(99,99,102,0.18)"}

_INTENT_COLOR = {
    "income": "#30d158", "hedge": "#0a84ff",
    "directional": "#ff9f0a", "speculation": "#bf5af2", "mixed": "#64d2ff",
    "unknown": "#636366",
}
_INTENT_LABEL = {
    "income": "收租", "hedge": "对冲",
    "directional": "方向", "speculation": "投机", "mixed": "混合",
    "unknown": "其他",
}

_STRATEGY_CATEGORY = {
    "Naked Put": "裸卖",        "Naked Call": "裸卖",    "Cash-Secured Put": "裸卖",
    "Bull Put Spread": "价差",  "Bear Call Spread": "价差",
    "Bull Call Spread": "价差", "Bear Put Spread": "价差",
    "Ratio Put Spread": "价差", "Ratio Call Spread": "价差",
    "Iron Condor": "综合",      "Iron Butterfly": "综合",
    "Straddle": "综合",         "Strangle": "综合",
    "Covered Call": "含股",     "Protective Put": "含股",
    "Collar": "含股",           "Long Stock": "含股",    "Short Stock": "含股",
    "PMCC": "跨期",             "Calendar Spread": "跨期", "Diagonal Spread": "跨期",
    "LEAPS Call": "长期",       "LEAPS Put": "长期",
    "Long Call": "单腿",        "Long Put": "单腿",
    "Unclassified": "其他",
}

_DTE_BUCKET_ORDER = ["≤30天", "31–90天", ">90天", "无到期"]
_CATEGORY_ORDER   = ["裸卖", "价差", "综合", "含股", "跨期", "长期", "单腿", "其他"]
_INTENT_ORDER     = ["income", "hedge", "directional", "speculation", "mixed", "unknown"]


def _dte_bucket(dte: int) -> str:
    if dte == 0:   return "无到期"
    if dte <= 30:  return "≤30天"
    if dte <= 90:  return "31–90天"
    return ">90天"


from collections import OrderedDict

def _group_strategies(strategies: list) -> dict:
    """Group strategies by 4 dimensions. Returns:
      { 'intent': {group_name: [sg, ...]}, 'underlying': {...},
        'category': {...}, 'dte': {...} }
    """
    result = {"intent": {}, "underlying": {}, "category": {}, "dte": {}}
    for sg in strategies:
        # intent
        key = sg.intent or "unknown"
        result["intent"].setdefault(key, []).append(sg)
        # underlying
        result["underlying"].setdefault(sg.underlying, []).append(sg)
        # category
        cat = _STRATEGY_CATEGORY.get(sg.strategy_type, "其他")
        result["category"].setdefault(cat, []).append(sg)
        # dte
        bucket = _dte_bucket(sg.dte)
        result["dte"].setdefault(bucket, []).append(sg)

    # Sort groups by canonical order
    def _sort(d, order):
        ordered = OrderedDict()
        for k in order:
            if k in d:
                ordered[k] = d[k]
        for k in d:
            if k not in ordered:
                ordered[k] = d[k]
        return ordered

    result["intent"]     = _sort(result["intent"],     _INTENT_ORDER)
    result["category"]   = _sort(result["category"],   _CATEGORY_ORDER)
    result["dte"]        = _sort(result["dte"],         _DTE_BUCKET_ORDER)
    # underlying: sort by underlying name
    result["underlying"] = OrderedDict(sorted(result["underlying"].items()))
    return result


def _group_stats(strategies: list, nlv: float) -> dict:
    """Compute aggregate stats for a group of StrategyGroup objects."""
    if not strategies:
        return {
            "count": 0, "total_pnl": 0.0, "total_theta": 0.0,
            "total_max_loss": 0.0, "max_loss_pct": 0.0,
            "has_naked": False, "net_delta": 0.0,
        }
    total_pnl   = sum(sg.net_pnl   for sg in strategies)
    total_theta = sum(sg.net_theta  for sg in strategies)
    net_delta   = sum(sg.net_delta  for sg in strategies)
    has_naked   = any(sg.max_loss is None for sg in strategies)
    total_max_loss = sum(sg.max_loss for sg in strategies if sg.max_loss is not None)
    max_loss_pct   = (total_max_loss / nlv * 100) if nlv > 0 else 0.0
    return {
        "count": len(strategies),
        "total_pnl": total_pnl,
        "total_theta": total_theta,
        "net_delta": net_delta,
        "total_max_loss": total_max_loss,
        "max_loss_pct": max_loss_pct,
        "has_naked": has_naked,
    }


_CATEGORY_DESC = {
    "裸卖": "卖出裸期权赚取全额权利金。裸 Put 下行风险有界（股票跌至 $0），裸 Call 上涨亏损无上限",
    "价差": "买卖双腿对冲，风险收益均有上限，资金效率较高",
    "综合": "多腿组合策略，在区间震荡中赚取时间价值",
    "含股": "股票结合期权，降低持仓成本或锁定收益区间",
    "跨期": "利用不同到期日的时间价值差套利",
    "长期": "LEAPS 长期期权，低杠杆博弈方向或作为对冲",
    "单腿": "单腿买入期权，最大亏损 = 已付权利金",
    "其他": "未分类策略，请手动核查",
}

_DTE_DESC = {
    "≤30天":   "临近到期，Theta 加速衰减，Gamma 风险上升，需密切关注",
    "31–90天": "中期策略，有充裕时间管理和调整",
    ">90天":   "长线布局，无需频繁操作，Vega 敞口是主要风险",
    "无到期":  "股票仓位或永续持仓，主要风险来自 Delta 方向",
}


def _group_subtitle(group_name: str, stats: dict, dim: str, nlv: float) -> str:
    """Generate plain-language description for a strategy group header."""
    parts = []

    if dim == "intent":
        theta = stats["total_theta"]
        delta = stats["net_delta"]
        if group_name == "income":
            if theta > 0:
                parts.append(f"靠卖出期权赚时间价值，每天自动进账 ${theta:.0f}，最怕突然大幅波动")
            else:
                parts.append("收租策略但 Theta 为负，检查是否持有过多保护腿")
        elif group_name == "hedge":
            parts.append(f"花钱买保险，每天付出 ${abs(theta):.0f} Theta，下行风险已设上限")
        elif group_name == "directional":
            direction = "多头" if delta >= 0 else "空头"
            parts.append(f"净{direction}敞口，标的涨跌影响方向性盈亏")
        elif group_name == "speculation":
            parts.append("买入期权博弈，最大亏损 = 已付权利金，到期作废则全损")
        elif group_name == "mixed":
            parts.append("兼具多种目的（如 Collar），需整体评估 Delta 和 Theta 的平衡")
        else:
            parts.append("未分类策略，请手动核查")

    elif dim == "underlying":
        delta = stats["net_delta"]
        direction = "多头" if delta >= 0 else "空头"
        parts.append(f"净{direction}敞口，共 {stats['count']} 个策略")

    elif dim == "category":
        parts.append(_CATEGORY_DESC.get(group_name, ""))

    elif dim == "dte":
        parts.append(_DTE_DESC.get(group_name, ""))

    # Append warnings
    if stats["max_loss_pct"] > 10.0:
        parts.append(f"⚠ 最大亏损 ${stats['total_max_loss']:,.0f}，占净资产 {stats['max_loss_pct']:.1f}%")
    if stats["has_naked"]:
        parts.append("⚠ 含裸 Call，股价上涨亏损无上限")

    return "，".join(p for p in parts if p)


def _render_group_header(group_name: str, display_name: str,
                          strategies: list, dim: str,
                          nlv: float, color: str) -> str:
    stats = _group_stats(strategies, nlv)
    subtitle = _group_subtitle(group_name, stats, dim, nlv)

    pnl = stats["total_pnl"]
    pnl_color = "#30d158" if pnl >= 0 else "#ff453a"
    pnl_str = _fmt_dollar(pnl)

    theta = stats["total_theta"]
    theta_str = f"{'+'  if theta >= 0 else ''}{theta:.0f}/天"
    theta_color = "#30d158" if theta >= 0 else "#ff453a"

    max_loss = stats["total_max_loss"]
    if stats["has_naked"]:
        loss_str = f"-${max_loss:,.0f} + ∞ (裸Call)"
    else:
        loss_str = f"-${max_loss:,.0f} ({stats['max_loss_pct']:.1f}%)"

    delta = stats["net_delta"]
    delta_str = f"ΔExp {'+' if delta >= 0 else ''}{delta:.1f}"

    return f"""
<div style="background:rgba(255,255,255,0.03); border-left:3px solid {color};
            border-radius:8px; padding:12px 16px; margin:20px 0 8px;">
  <div style="display:flex; align-items:center; gap:12px; flex-wrap:wrap;">
    <span style="font-size:14px; font-weight:700; color:{color};">{_e(display_name)}</span>
    <span style="font-size:12px; color:#636366;">{stats['count']} 个策略</span>
    <span style="font-size:12px; color:{pnl_color}; font-family:'SF Mono',monospace;">PnL {pnl_str}</span>
    <span style="font-size:12px; color:{theta_color}; font-family:'SF Mono',monospace;">Θ {_e(theta_str)}</span>
    <span style="font-size:12px; color:#ff453a; font-family:'SF Mono',monospace;">MaxLoss {_e(loss_str)}</span>
    <span style="font-size:12px; color:#8e8e93; font-family:'SF Mono',monospace; cursor:help;"
          title="Delta Exposure：每 $1 市场波动对组合的影响金额。正值 = 净多头，市场上涨获益；负值 = 净空头，市场下跌获益。">{_e(delta_str)}</span>
  </div>
  {f'<div style="font-size:12px; color:#8e8e93; margin-top:5px;">{_e(subtitle)}</div>' if subtitle else ''}
</div>"""


_TAB_LABELS = [
    ("intent",     "意图"),
    ("underlying", "标的"),
    ("category",   "策略类型"),
    ("dte",        "到期区间"),
]

_TAB_COLORS = {
    "intent":     None,   # uses _INTENT_COLOR per group
    "underlying": "#0a84ff",
    "category":   "#ff9f0a",
    "dte":        None,   # uses per-bucket color
}

_DTE_COLOR = {"≤30天": "#ff453a", "31–90天": "#ffb340", ">90天": "#30d158", "无到期": "#636366"}


def _render_tabbed_summary(strategies: list, nlv: float) -> str:
    if not strategies:
        return ""

    groups = _group_strategies(strategies)

    # Tab nav buttons
    tab_btns = "".join(
        f'<button class="tab-btn{" active" if i == 0 else ""}" data-tab="{key}">{label}</button>'
        for i, (key, label) in enumerate(_TAB_LABELS)
    )

    # Tab panels
    panels_html = ""
    for i, (dim_key, _) in enumerate(_TAB_LABELS):
        active_cls = " active" if i == 0 else ""
        panel_content = ""
        for group_name, group_sgs in groups[dim_key].items():
            if dim_key == "intent":
                color = _INTENT_COLOR.get(group_name, "#636366")
                display = _INTENT_LABEL.get(group_name, group_name)
            elif dim_key == "dte":
                color = _DTE_COLOR.get(group_name, "#636366")
                display = group_name
            else:
                color = _TAB_COLORS[dim_key]
                display = group_name

            header_html = _render_group_header(
                group_name=group_name, display_name=display,
                strategies=group_sgs, dim=dim_key,
                nlv=nlv, color=color,
            )
            cards_html = "".join(_strategy_card(sg) for sg in group_sgs)
            panel_content += header_html + cards_html

        panels_html += f'<div class="tab-panel{active_cls}" id="tab-{dim_key}">{panel_content}</div>\n'

    js = """
<script>
(function(){
  var btns = document.querySelectorAll('.strat-tabs .tab-btn');
  btns.forEach(function(btn){
    btn.addEventListener('click', function(){
      btns.forEach(function(b){ b.classList.remove('active'); });
      btn.classList.add('active');
      var t = btn.dataset.tab;
      document.querySelectorAll('.strat-tabs .tab-panel').forEach(function(p){
        p.classList.toggle('active', p.id === 'tab-' + t);
      });
    });
  });
})();
</script>"""

    css = """
<style>
.strat-tabs .tab-nav { display:flex; gap:4px; margin-bottom:16px; border-bottom:1px solid #2c2c2e; padding-bottom:0; }
.strat-tabs .tab-btn { background:none; border:none; color:#8e8e93; padding:8px 14px; cursor:pointer;
  font-size:13px; font-weight:500; border-bottom:2px solid transparent; margin-bottom:-1px; transition:color .15s,border-color .15s; }
.strat-tabs .tab-btn:hover { color:#e5e5ea; }
.strat-tabs .tab-btn.active { color:#0a84ff; border-bottom-color:#0a84ff; }
.strat-tabs .tab-panel { display:none; }
.strat-tabs .tab-panel.active { display:block; }
</style>"""

    return f"""
{css}
<h2>策略汇总</h2>
<div class="strat-tabs">
  <div class="tab-nav">{tab_btns}</div>
  {panels_html}
</div>
{js}"""


_CSS = """
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #000; color: #f5f5f7; font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', sans-serif; font-size: 14px; line-height: 1.5; padding: 24px; }
a { color: #0a84ff; }
h1 { font-size: 22px; font-weight: 700; letter-spacing: -0.5px; }
h2 { font-size: 15px; font-weight: 600; color: #8e8e93; text-transform: uppercase; letter-spacing: 1px; margin: 28px 0 10px; }
.summary-card { background: #1c1c1e; border: 1px solid #2c2c2e; border-radius: 16px; padding: 20px 24px; margin-bottom: 20px; display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 16px; }
.stat-item { display: flex; flex-direction: column; }
.stat-label { font-size: 11px; color: #8e8e93; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px; }
.stat-value { font-size: 20px; font-weight: 600; }
.narrative { background: #1c1c1e; border: 1px solid #2c2c2e; border-radius: 12px; padding: 14px 18px; margin-bottom: 20px; line-height: 1.6; color: #e5e5ea; }
.action-list { margin-bottom: 24px; }
.action-item { display: flex; align-items: flex-start; gap: 10px; padding: 10px 14px; background: rgba(255,69,58,0.08); border: 1px solid rgba(255,69,58,0.20); border-radius: 10px; margin-bottom: 8px; font-size: 13px; }
.action-dot { width: 8px; height: 8px; border-radius: 50%; background: #ff453a; flex-shrink: 0; margin-top: 5px; }
.section-divider { display: flex; align-items: center; gap: 12px; margin: 24px 0 14px; }
.section-divider .label { font-size: 12px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; white-space: nowrap; }
.section-divider .line { flex: 1; height: 1px; background: #2c2c2e; }
.alert-card { border-radius: 14px; padding: 16px 18px; margin-bottom: 12px; }
.alert-header { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.severity-dot { width: 9px; height: 9px; border-radius: 50%; flex-shrink: 0; }
.alert-title { font-size: 15px; font-weight: 600; }
.alert-underlying { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 20px; background: #2c2c2e; color: #e5e5ea; }
.intent-badge { font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 20px; }
.alert-technical { font-family: 'SF Mono', 'Menlo', monospace; font-size: 12px; color: #8e8e93; margin-bottom: 8px; }
.alert-body { color: #e5e5ea; font-size: 13.5px; line-height: 1.6; margin-bottom: 12px; }
.greek-row { display: flex; gap: 18px; flex-wrap: wrap; margin-bottom: 10px; }
.greek-item { display: flex; flex-direction: column; }
.greek-label { font-size: 10px; color: #8e8e93; }
.greek-value { font-size: 13px; font-weight: 600; font-family: 'SF Mono', monospace; }
.options-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.option-pill { font-size: 12px; padding: 4px 12px; border-radius: 20px; border: 1px solid #3a3a3c; color: #e5e5ea; background: #2c2c2e; cursor: default; }
.option-pill.recommended { border-color: #0a84ff; color: #0a84ff; background: rgba(10,132,255,0.10); font-weight: 600; }
.strategy-meta { font-size: 12px; color: #636366; margin-bottom: 10px; }
.no-alerts { color: #636366; font-style: italic; font-size: 13px; padding: 8px 0; }
</style>
"""


def _fmt_dollar(v: float) -> str:
    if v >= 0:
        return f"+${v:,.0f}"
    return f"-${abs(v):,.0f}"


def _parse_recommended(ai_suggestion: str) -> str:
    """Parse '推荐选项C' or 'recommend option C' → 'C'."""
    if not ai_suggestion:
        return ""
    m = re.search(r'推荐选项\s*([A-D])', ai_suggestion)
    if m:
        return m.group(1)
    m = re.search(r'\brecommend\w*\s+option\s*([A-D])\b', ai_suggestion, re.IGNORECASE)
    if m:
        return m.group(1)
    return ""


def _option_pills(options: list, ai_suggestion: str) -> str:
    if not options:
        return ""
    rec = _parse_recommended(ai_suggestion)
    pills = []
    for opt in options:
        letter = opt[0] if opt else ""
        is_rec = (letter == rec)
        cls = "option-pill recommended" if is_rec else "option-pill"
        label = f"{opt}{'★' if is_rec else ''}"
        pills.append(f'<span class="{cls}">{_e(label)}</span>')
    return f'<div class="options-row">{"".join(pills)}</div>'


def _alert_card(alert, level_color: str, level_bg: str, level_border: str) -> str:
    body_text = alert.ai_suggestion or alert.plain
    pills_html = _option_pills(alert.options, alert.ai_suggestion)
    return f"""
<div class="alert-card" style="background:{level_bg}; border:1px solid {level_border};">
  <div class="alert-header">
    <span class="severity-dot" style="background:{level_color};"></span>
    <span class="alert-title">{_e(alert.title)}</span>
    <span class="alert-underlying">{_e(alert.underlying)}</span>
  </div>
  <div class="alert-technical">{_e(alert.technical)}</div>
  <div class="alert-body">{_e(body_text)}</div>
  {pills_html}
</div>"""


def _strategy_card(sg) -> str:
    intent_color = _INTENT_COLOR.get(sg.intent, "#636366")
    intent_label = _INTENT_LABEL.get(sg.intent, sg.intent)
    legs_summary = []
    if sg.stock_leg:
        legs_summary.append(f"{sg.stock_leg.position:+.0f} STK @ {sg.stock_leg.mark_price:.2f}")
    for p in sg.legs:
        if p.asset_category == "OPT":
            direction = "Short" if p.position < 0 else "Long"
            legs_summary.append(f"{direction} {abs(p.position):.0f}× {p.put_call}{p.strike:.0f} exp {p.expiry}")
    for p in sg.modifiers:
        legs_summary.append(f"[hedge] Long {abs(p.position):.0f}× {p.put_call}{p.strike:.0f}")

    legs_str = " | ".join(legs_summary)
    dte_str = f"DTE {sg.dte}" if sg.dte else ""

    greeks_available = any(abs(v) > 1e-9 for v in
                           [sg.net_delta, sg.net_theta, sg.net_vega, sg.net_gamma])
    if greeks_available:
        greek_html = f"""
<div class="greek-row">
  <div class="greek-item"><span class="greek-label">Δ 每1%</span><span class="greek-value">{_fmt_dollar(sg.net_delta * 0.01 * 100)}</span></div>
  <div class="greek-item"><span class="greek-label">Θ 每天</span><span class="greek-value">{_fmt_dollar(sg.net_theta)}</span></div>
  <div class="greek-item"><span class="greek-label">V 每1%IV</span><span class="greek-value">{_fmt_dollar(sg.net_vega * 0.01)}</span></div>
  <div class="greek-item"><span class="greek-label">最大盈利</span><span class="greek-value">{"无上限" if sg.max_profit is None else _fmt_dollar(sg.max_profit)}</span></div>
  <div class="greek-item"><span class="greek-label">最大亏损</span><span class="greek-value">{"无限制" if sg.max_loss is None else _fmt_dollar(-sg.max_loss)}</span></div>
</div>"""
    else:
        greek_html = f"""
<div class="greek-row">
  <div class="greek-item"><span class="greek-label">最大盈利</span><span class="greek-value">{"无上限" if sg.max_profit is None else _fmt_dollar(sg.max_profit)}</span></div>
  <div class="greek-item"><span class="greek-label">最大亏损</span><span class="greek-value">{"无限制" if sg.max_loss is None else _fmt_dollar(-sg.max_loss)}</span></div>
  <span style="font-size:11px;color:#636366;">Greeks 未启用 — 在 Flex Query → Open Positions 中勾选 Delta/Theta/Vega/Gamma</span>
</div>"""

    return f"""
<div style="background:#1c1c1e; border:1px solid #2c2c2e; border-radius:14px; padding:16px 18px; margin-bottom:12px;">
  <div class="alert-header">
    <span class="alert-title">{_e(sg.strategy_type)}</span>
    <span class="alert-underlying">{_e(sg.underlying)}</span>
    <span class="intent-badge" style="background:{intent_color}22; color:{intent_color};">{intent_label}</span>
    {"<span style='font-size:12px;color:#636366;'>" + _e(dte_str) + "</span>" if dte_str else ""}
  </div>
  <div class="strategy-meta">{_e(legs_str)}</div>
  {greek_html}
</div>"""


def _section_divider(label: str, color: str) -> str:
    return f"""
<div class="section-divider">
  <span class="label" style="color:{color};">{label}</span>
  <span class="line"></span>
</div>"""


def generate_html_report(report) -> str:
    """Generate HTML report. Accepts StrategyRiskReport (Phase 7) or legacy RiskReport."""
    if _HAS_STRATEGY_RISK and isinstance(report, StrategyRiskReport):
        return _generate_strategy_report(report)
    # Fallback: legacy report type
    return _generate_legacy_report(report)


def _generate_strategy_report(report) -> str:
    nlv = report.net_liquidation
    cushion_pct = report.cushion * 100
    stress = report.summary_stats.get("stress_test", {})
    drop10 = stress.get("drop_10pct", 0)

    cushion_color = "#ff453a" if cushion_pct < 10 else "#ffb340" if cushion_pct < 20 else "#30d158"
    stress_color = "#ff453a" if drop10 < -nlv * 0.20 else "#ffb340" if drop10 < -nlv * 0.15 else "#30d158"
    pnl_color = "#30d158" if report.total_pnl >= 0 else "#ff453a"

    summary_card = f"""
<div class="summary-card">
  <div class="stat-item"><span class="stat-label">账户净资产</span><span class="stat-value">${nlv:,.0f}</span></div>
  <div class="stat-item"><span class="stat-label">未实现盈亏</span><span class="stat-value" style="color:{pnl_color};">{_fmt_dollar(report.total_pnl)}</span></div>
  <div class="stat-item"><span class="stat-label">保证金缓冲</span><span class="stat-value" style="color:{cushion_color};">{cushion_pct:.1f}%</span></div>
  <div class="stat-item"><span class="stat-label">大盘-10%压测</span><span class="stat-value" style="color:{stress_color};">{_fmt_dollar(drop10)}</span></div>
</div>"""

    narrative_html = ""
    if report.portfolio_summary:
        narrative_html = f'<div class="narrative">{_e(report.portfolio_summary)}</div>'

    # 今日操作清单
    action_items_html = ""
    if report.top_actions:
        items = "".join(
            f'<div class="action-item"><span class="action-dot"></span><span>{_e(a.title)} — {_e(a.underlying)}: {_e((a.ai_suggestion or a.plain)[:100])}</span></div>'
            for a in report.top_actions
        )
        action_items_html = f'<h2>今日操作清单</h2><div class="action-list">{items}</div>'

    # Three-tier alert sections
    reds = [a for a in report.alerts if a.severity == "red"]
    yellows = [a for a in report.alerts if a.severity == "yellow"]
    watches = [a for a in report.alerts if a.severity == "watch"]

    def _render_alerts(alerts_list, color, bg, border):
        if not alerts_list:
            return '<p class="no-alerts">暂无</p>'
        return "".join(_alert_card(a, color, bg, border) for a in alerts_list)

    red_html = _render_alerts(reds, _LEVEL_COLOR["red"], _LEVEL_BG["red"], _LEVEL_BORDER["red"])
    yellow_html = _render_alerts(yellows, _LEVEL_COLOR["yellow"], _LEVEL_BG["yellow"], _LEVEL_BORDER["yellow"])
    watch_html = _render_alerts(watches, _LEVEL_COLOR["watch"], _LEVEL_BG["watch"], _LEVEL_BORDER["watch"])

    # Strategy cards — tabbed multi-dimension summary
    strategy_cards_html = _render_tabbed_summary(report.strategies, report.net_liquidation)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>期权组合风险报告 — {_e(report.account_id)} {_e(report.report_date)}</title>
{_CSS}
</head>
<body>
<h1>期权组合风险报告</h1>
<p style="color:#8e8e93; font-size:13px; margin:4px 0 18px;">{_e(report.account_id)} · {_e(report.report_date)}</p>

{summary_card}
{narrative_html}
{action_items_html}

{_section_divider("立即处理", _LEVEL_COLOR["red"])}
{red_html}

{_section_divider("本周评估", _LEVEL_COLOR["yellow"])}
{yellow_html}

{_section_divider("持续观察", _LEVEL_COLOR["watch"])}
{watch_html}

{strategy_cards_html}

</body>
</html>"""


def _generate_legacy_report(report) -> str:
    """Minimal fallback for old RiskReport objects during migration."""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>Risk Report</title>{_CSS}</head>
<body>
<h1>风险报告（旧格式）</h1>
<p style="color:#8e8e93;">{getattr(report, 'account_id', '')} · {getattr(report, 'report_date', '')}</p>
<p style="color:#636366; margin-top:20px;">请升级至 Phase 7 策略感知版本。</p>
</body>
</html>"""
