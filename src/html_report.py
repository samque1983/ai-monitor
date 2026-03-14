# src/html_report.py
"""Apple-style HTML report renderer for the ai-monitor scanner."""
from datetime import date
from html import escape as _html_escape
from typing import Any, Dict, List, Optional, Tuple

from src.data_engine import TickerData, EarningsGap
from src.scanners import SellPutSignal


def _escape(text: str) -> str:
    """Escape user-supplied text for safe HTML embedding."""
    return _html_escape(str(text), quote=True)


def _format_earnings(earnings_date: Optional[date], days: Optional[int]) -> str:
    if earnings_date and days is not None:
        return f"财报: {earnings_date} ({days}天)"
    return "财报: N/A"


def _empty_row(colspan: int = 4) -> str:
    return (
        f'<tr><td colspan="{colspan}" class="empty">'
        f"无符合条件的标的</td></tr>"
    )


def _iv_table(tickers: List[TickerData]) -> str:
    if not tickers:
        return f"<table>{_empty_row(3)}</table>"
    rows = []
    for t in tickers:
        iv = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>IV Rank: {_escape(iv)}</td>"
            f"<td>{_escape(_format_earnings(t.earnings_date, t.days_to_earnings))}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _ma200_table(tickers: List[TickerData]) -> str:
    if not tickers:
        return f"<table>{_empty_row(4)}</table>"
    rows = []
    for t in tickers:
        pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>Price: ${t.last_price:.2f}</td>"
            f"<td>MA200: ${t.ma200:.2f} ({pct:+.2f}%)</td>"
            f"<td>{_escape(_format_earnings(t.earnings_date, t.days_to_earnings))}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _leaps_table(tickers: List[TickerData]) -> str:
    if not tickers:
        return f"<table>{_empty_row(5)}</table>"
    rows = []
    for t in tickers:
        ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>Price: ${t.last_price:.2f}</td>"
            f"<td>MA200: ${t.ma200:.2f} &nbsp; MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)</td>"
            f"<td>RSI: {t.rsi14:.1f} &nbsp; IV Rank: {t.iv_rank:.1f}%</td>"
            f"<td>{_escape(_format_earnings(t.earnings_date, t.days_to_earnings))}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _sell_put_table(sell_puts: List[Tuple[SellPutSignal, TickerData]]) -> str:
    if not sell_puts:
        return f"<table>{_empty_row(5)}</table>"
    rows = []
    for signal, t in sell_puts:
        warning = ""
        if signal.earnings_risk:
            warning = (
                '<div class="earnings-warning">'
                "\U0001f6a8 警告: 财报日在DTE窗口内 \u2014 跳空风险"
                "</div>"
            )
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(signal.ticker)}</td>'
            f"<td>Strike: ${signal.strike:.0f} &nbsp; DTE: {signal.dte}</td>"
            f"<td>Bid: ${signal.bid:.2f} &nbsp; APY: {signal.apy:.1f}%</td>"
            f"<td>{_escape(_format_earnings(t.earnings_date, t.days_to_earnings))}</td>"
            f"<td>{warning}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _skipped_table(skipped: List[Tuple[str, str]]) -> str:
    rows = []
    for ticker, reason in skipped:
        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(ticker)}</td>'
            f"<td>{_escape(reason)}</td>"
            f"</tr>"
        )
    return "<table>" + "".join(rows) + "</table>"


def _iv_momentum_table(tickers: List[TickerData]) -> str:
    """生成 IV 动量表格"""
    if not tickers:
        return f'<table>{_empty_row(4)}</table>'

    rows = []
    for t in tickers:
        mom_str = f"+{t.iv_momentum:.1f}%" if t.iv_momentum is not None else "N/A"
        iv_str = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
        earnings_str = _format_earnings(t.earnings_date, t.days_to_earnings)

        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>IV动量: {_escape(mom_str)}</td>"
            f"<td>IV Rank: {_escape(iv_str)}</td>"
            f"<td>{_escape(earnings_str)}</td>"
            f"</tr>"
        )

    return "<table>" + "".join(rows) + "</table>"


def _earnings_gap_table(gaps: list, ticker_map: dict) -> str:
    """生成财报 Gap 预警表格"""
    if not gaps:
        return f'<table>{_empty_row(4)}</table>'

    rows = []
    for g in gaps:
        td = ticker_map.get(g.ticker)
        days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
        iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"

        # 风险标注
        risk_badge = ""
        if td and td.iv_rank is not None and td.iv_rank > 70:
            risk_badge = ' <span class="risk-badge">高IV风险</span>'

        rows.append(
            f"<tr>"
            f'<td class="ticker">⚠️ {_escape(g.ticker)}{risk_badge}</td>'
            f"<td>财报还有 {_escape(days_str)}<br>"
            f"平均Gap ±{g.avg_gap:.1f}% · 上涨概率 {g.up_ratio:.1f}%</td>"
            f"<td>最大跳空 {g.max_gap:+.1f}%<br>样本数: {g.sample_count}</td>"
            f"<td>IV Rank: {_escape(iv_str)}</td>"
            f"</tr>"
        )

    return "<table>" + "".join(rows) + "</table>"


CSS = """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #f5f5f7;
    color: #1d1d1f;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
}
.container {
    max-width: 720px;
    margin: 0 auto;
    padding: 40px 20px;
}
header {
    text-align: center;
    margin-bottom: 32px;
}
header h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
}
header .meta {
    color: #86868b;
    font-size: 14px;
}
.card {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08), 0 1px 2px rgba(0,0,0,0.04);
    padding: 24px;
    margin-bottom: 20px;
}
.card h2 {
    font-size: 18px;
    font-weight: 600;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #d2d2d7;
}
.card h3 {
    font-size: 14px;
    font-weight: 600;
    color: #1d1d1f;
    margin: 12px 0 8px 0;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
}
table td {
    padding: 6px 8px;
    border-bottom: 1px solid #f0f0f0;
    vertical-align: top;
}
table tr:last-child td {
    border-bottom: none;
}
.ticker {
    font-weight: 600;
    white-space: nowrap;
}
.empty {
    color: #86868b;
    font-style: italic;
    text-align: center;
    padding: 16px 8px;
}
.earnings-warning {
    background: #fff0f0;
    color: #d00;
    border-radius: 6px;
    padding: 4px 8px;
    font-size: 13px;
    display: inline-block;
}
.risk-badge {
    background: #ff3b30;
    color: white;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.85em;
    margin-left: 8px;
}
footer {
    text-align: center;
    color: #86868b;
    font-size: 13px;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid #d2d2d7;
}
@media (max-width: 480px) {
    .container { padding: 20px 12px; }
    header h1 { font-size: 22px; }
    .card { padding: 16px; }
    table { font-size: 13px; }
    table td { padding: 4px 4px; }
}
/* 高股息防御双打 */
.info-badge { color: #58a6ff; text-decoration: none; font-size: 0.85rem;
              border: 1px solid #30363d; border-radius: 50%; padding: 0 0.3rem;
              margin-left: 0.4rem; vertical-align: middle; }
.info-badge:hover { background: #161b22; }
.dividend-pool-summary {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 14px 18px;
    border-radius: 8px;
    margin-bottom: 16px;
    font-size: 14px;
}
.dividend-signals-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
    gap: 16px;
}
.dividend-card {
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
    color: #e0e0e0;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.25);
}
.dividend-card .dc-header { margin-bottom: 14px; }
.dividend-card .dc-ticker {
    font-size: 20px;
    font-weight: 700;
    color: #fff;
    margin-bottom: 4px;
}
.dividend-card .dc-yield {
    font-size: 14px;
    color: #a8d8ea;
}
.dividend-card .dc-dim {
    background: rgba(255,255,255,0.07);
    border-radius: 8px;
    padding: 10px 12px;
    margin: 8px 0;
    font-size: 13px;
}
.dividend-card .dc-dim h4 {
    font-size: 13px;
    font-weight: 600;
    color: #c0c0e0;
    margin-bottom: 6px;
}
.dividend-card .dc-dim p { margin: 2px 0; }
.dividend-card .dc-combined {
    font-size: 15px;
    font-weight: 700;
    color: #ffd700;
}
.dividend-card .dc-warn { color: #ff9f43; }
"""


def _dividend_card(signal: Any) -> str:
    """Render a single six-dimension dividend buy-signal card."""
    td = signal.ticker_data
    cy = signal.current_yield
    pct = signal.yield_percentile
    ticker = _escape(td.ticker)

    pr = td.payout_ratio
    if pr is not None:
        pr_warn = ' <span class="dc-warn">⚠️ 接近警戒线</span>' if pr > 80 else " ✓"
        pr_str = f"{pr:.1f}%{pr_warn}"
    else:
        pr_str = "N/A"

    # Dim 1 logic: yield percentile interpretation + business stability
    if pct >= 90:
        yield_logic = "股息率达历史高位 → 价格明显低估"
    elif pct >= 80:
        yield_logic = "股息率高于历史均值 → 估值偏低"
    else:
        yield_logic = "超越多数历史区间 → 轻度低估"

    qs = td.dividend_quality_score
    if qs is not None:
        if qs >= 80:
            stab_label = f"业务稳定性: 优秀 ({qs:.0f}/100)"
        elif qs >= 60:
            stab_label = f"业务稳定性: 良好 ({qs:.0f}/100)"
        else:
            stab_label = f"业务稳定性: 一般 ({qs:.0f}/100)"
    else:
        stab_label = None

    # Dim 1 stability: if quality_breakdown present, render as <details>
    quality_breakdown = td.quality_breakdown
    analysis_text = td.analysis_text
    if stab_label and quality_breakdown:
        dims = [
            ('股息连续性', quality_breakdown.get('continuity', 0)),
            ('派息率安全', quality_breakdown.get('payout_safety', 0)),
            ('盈利稳定性', quality_breakdown.get('earnings_stability', 0)),
            ('业务护城河', quality_breakdown.get('moat', 0)),
            ('负债水平', quality_breakdown.get('debt_level', 0)),
        ]
        bars = ''.join(
            f'<div style="display:flex;align-items:center;gap:6px;margin:3px 0;font-size:12px">'
            f'<span style="width:90px;color:#888">{label}</span>'
            f'<div style="flex:1;background:#eee;border-radius:3px;height:6px">'
            f'<div style="width:{val/20*100:.0f}%;background:#4a90d9;height:6px;border-radius:3px"></div>'
            f'</div><span style="width:32px;text-align:right">{val}/20</span></div>'
            for label, val in dims
        )
        analysis = (
            f'<p style="font-size:12px;color:#666;margin-top:6px;font-style:italic">'
            f'{_escape(analysis_text)}</p>'
            if analysis_text else ''
        )
        stability_html = (
            f'<details style="margin-top:4px">'
            f'<summary style="cursor:pointer;list-style:none">{_escape(stab_label)} ℹ️</summary>'
            f'<div style="margin-top:6px">{bars}{analysis}</div>'
            f'</details>'
        )
    elif stab_label:
        stability_html = f"    <p>{_escape(stab_label)}</p>"
    else:
        stability_html = None

    # Dim 5 floor price analysis
    floor_price = signal.floor_price
    forward_dividend_rate = signal.forward_dividend_rate if signal.forward_dividend_rate is not None else td.forward_dividend_rate
    max_yield_5y = signal.max_yield_5y if signal.max_yield_5y is not None else td.max_yield_5y
    floor_downside_pct = signal.floor_downside_pct
    opt = signal.option_details
    if floor_price is not None:
        cost_basis = (opt["strike"] - opt["bid"]) if opt and not opt.get("sell_put_illiquid") else None
        cb_row = f'    <p>行权成本: ${cost_basis:.2f}</p>' if cost_basis is not None else ''
        warn = ''
        if cost_basis is not None and cost_basis > floor_price:
            my_str = f'{max_yield_5y:.1f}' if max_yield_5y is not None else '?'
            warn = (
                f'    <p style="color:#e67e22">⚠️ 行权成本高于极值底价，极端熊市下仍有浮亏风险<br>'
                f'但届时股息率将达 {my_str}%，持有收租逻辑成立</p>'
            )
        my_str = f'{max_yield_5y:.1f}' if max_yield_5y is not None else 'N/A'
        fdr_str = f'${forward_dividend_rate:.2f}' if forward_dividend_rate is not None else 'N/A'
        fdp_str = f'{-floor_downside_pct:.1f}' if floor_downside_pct is not None else '?'
        # Extreme event footnote
        _evt_label = getattr(signal, 'extreme_event_label', None)
        _evt_price = getattr(signal, 'extreme_event_price', None)
        _evt_days  = getattr(signal, 'extreme_event_days', None)
        extreme_note = ''
        if _evt_label and _evt_price is not None:
            _days_str = f'，持续 {_evt_days} 天' if _evt_days else ''
            extreme_note = (
                f'    <p style="font-size:0.82em;color:var(--text-muted,#86868b)">'
                f'↳ 已剔除更低点 ${_evt_price:.2f} ({_evt_label}{_days_str})</p>\n'
            )
        floor_html = (
            f'{cb_row}\n'
            f'    <p>历史最高股息率 (5年): {my_str}%</p>\n'
            f'    <p>Forward 股息: {fdr_str}/股</p>\n'
            f'    <p>极值底价: ${floor_price:.2f} (较当前 {fdp_str}%)</p>\n'
            f'{extreme_note}'
            f'    {warn}'
        )
    else:
        floor_html = '    <p>极值底价数据暂缺</p>'

    # Freshness badge
    needs_reeval = signal.needs_reeval
    data_age_days = signal.data_age_days
    if needs_reeval:
        freshness_html = '<p style="color:#e67e22;font-size:12px;margin-top:6px">⚠️ 财报后数据，建议重新评估</p>'
    elif data_age_days is not None and data_age_days > 14:
        freshness_html = f'<p style="color:#86868b;font-size:12px;margin-top:6px">🕐 数据较旧 ({data_age_days}天前)</p>'
    else:
        freshness_html = ''

    earnings_str = str(td.earnings_date) if td.earnings_date else "N/A"
    dim1_parts = [
        '  <div class="dc-dim">',
        "    <h4>1️⃣ 基本面估值</h4>",
        f"    <p>{yield_logic}</p>",
    ]
    if stability_html:
        if stability_html.startswith('<details'):
            dim1_parts.append(f"    {stability_html}")
        else:
            dim1_parts.append(stability_html)
    dim1_parts.append("  </div>")

    parts = [
        '<div class="dividend-card">',
        '  <div class="dc-header">',
        f'    <div class="dc-ticker">{ticker} 🛡️</div>',
        f'    <div class="dc-yield">当前股息率: <strong>{cy:.2f}%</strong>'
        f' (5年历史{pct:.0f}分位)</div>',
        "  </div>",
        # Dim 1: valuation logic + stability
        *dim1_parts,
        # Dim 2: risk
        '  <div class="dc-dim">',
        "    <h4>2️⃣ 风险分级</h4>",
        f"    <p>派息率: {pr_str}</p>",
        "  </div>",
        # Dim 3: events
        '  <div class="dc-dim">',
        "    <h4>3️⃣ 关键事件</h4>",
        f"    <p>下次财报: {_escape(earnings_str)}</p>",
        "  </div>",
        # Dim 4: action
        '  <div class="dc-dim">',
        "    <h4>4️⃣ 建议操作</h4>",
        f"    <p>📈 现货买入: ${td.last_price:.2f} (股息率{cy:.2f}%)</p>",
    ]

    if opt and not opt.get("sell_put_illiquid"):
        combined = cy + opt["apy"]
        parts += [
            f"    <p>📊 Sell Put ${opt['strike']:.0f} Strike ({opt['dte']}DTE)</p>",
            f"    <p>Premium: ${opt['bid']:.2f} → 年化{opt['apy']:.1f}%</p>",
            f'    <p class="dc-combined">综合年化: {combined:.1f}%</p>',
        ]
    elif opt and opt.get("sell_put_illiquid"):
        parts += [
            f"    <p>📊 Sell Put ${opt['strike']:.0f} Strike ({opt['dte']}DTE)</p>",
            f'    <p style="color:#e67e22">⚠️ 期权流动性不足 (价差{opt["spread_pct"]:.0f}%)，不建议操作</p>',
        ]

    parts += [
        "  </div>",
        # Dim 5: worst case / floor price analysis
        '  <div class="dc-dim">',
        "    <h4>5️⃣ 最坏情景</h4>",
        floor_html,
        "  </div>",
        # Dim 6: monitoring
        '  <div class="dc-dim">',
        "    <h4>6️⃣ AI监控承诺</h4>",
        "    <ul style='padding-left:16px;margin:4px 0;font-size:12px'>",
        "      <li>✓ 派息率&gt;100%时立即预警</li>",
        "      <li>✓ 财报前7天提醒</li>",
        "      <li>✓ 股息率回落至中位数时提示</li>",
        "    </ul>",
        "  </div>",
    ]

    if freshness_html:
        parts.append(f"  {freshness_html}")

    parts.append("</div>")
    return "\n".join(parts)


def _render_cards_section(cards) -> str:
    if not cards:
        return ""
    rows = []
    for card in cards:
        ticker = card.get("ticker", "")
        strategy = card.get("strategy", "")
        strategy_label = "Sell Put 收租" if strategy == "SELL_PUT" else "高股息双打"
        v = card.get("valuation", {})
        iron = v.get("iron_floor", "—")
        fair = v.get("fair_value", "—")
        logic = v.get("logic_summary", "")
        fundamentals = card.get("fundamentals", {})

        crosses = card.get("crosses_earnings", False)
        dual_plan_html = ""
        if crosses and card.get("protected_plan"):
            pp = card["protected_plan"]
            np_ = card.get("naked_plan", {})
            dual_plan_html = f"""
            <div class="dual-plan">
              <div class="plan-item recommended">
                <span class="plan-label">方案A（推荐）· Bull Put Spread</span>
                <span>{pp.get('desc','')} | 权利金 ${pp.get('net_premium',0):.2f} | 最大亏损 ${pp.get('max_loss',0):.2f}/股</span>
                <span class="plan-note">{pp.get('note','')}</span>
              </div>
              <div class="plan-item">
                <span class="plan-label">方案B · Naked Sell Put</span>
                <span>{np_.get('desc','')} | 权利金 ${np_.get('net_premium',0):.2f} | 最大亏损 ${np_.get('max_loss',0):.2f}/股</span>
                <span class="plan-note">{np_.get('note','')}</span>
              </div>
            </div>"""

        detail_id = f"detail_{ticker}_{strategy}"
        rows.append(f"""
        <div class="card">
          <div class="card-header">
            <span class="strategy-badge">{strategy_label}</span>
            <span class="ticker">{ticker}</span>
          </div>
          <div class="card-body">
            <p class="trigger">📍 {card.get('trigger_reason','')}</p>
            <p class="action"><strong>{card.get('action','')}</strong> — {card.get('one_line_logic','')}</p>
            {dual_plan_html}
            <div class="valuation-summary">
              💡 铁底 ${iron} | 公允价 ${fair}
              <p class="logic-summary">{logic}</p>
              <button class="detail-toggle" onclick="document.getElementById('{detail_id}').classList.toggle('hidden')">
                查看详细分析 ▼
              </button>
              <div id="{detail_id}" class="detail-panel hidden">
                <pre>{fundamentals}</pre>
              </div>
            </div>
            <div class="risk-row">
              🛑 止盈: {card.get('take_profit','')} &nbsp; 🔴 止损: {card.get('stop_loss','')}
            </div>
            <div class="max-loss">最坏亏损: ${card.get('max_loss_usd',0):.1f}/股</div>
          </div>
        </div>""")

    return f"""
    <section class="opportunities">
      <h2>机会卡片</h2>
      {"".join(rows)}
    </section>
    <style>
      .opportunities {{ margin: 24px 0; }}
      .card {{ background: #fff; border-radius: 12px; padding: 20px;
               margin: 12px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
      .strategy-badge {{ background: #34c759; color: #fff; border-radius: 6px;
                         padding: 2px 8px; font-size: 12px; }}
      .ticker {{ font-size: 20px; font-weight: 600; margin-left: 8px; }}
      .trigger {{ color: #666; font-size: 14px; }}
      .dual-plan {{ background: #f5f5f7; border-radius: 8px; padding: 12px; margin: 8px 0; }}
      .plan-item {{ margin: 6px 0; }}
      .plan-item.recommended {{ font-weight: 600; }}
      .plan-label {{ color: #1d1d1f; }}
      .plan-note {{ color: #666; font-size: 13px; }}
      .valuation-summary {{ margin: 12px 0; padding: 12px;
                            background: #f5f5f7; border-radius: 8px; }}
      .logic-summary {{ font-size: 13px; color: #444; margin: 4px 0; }}
      .detail-toggle {{ background: none; border: none; color: #0071e3;
                        cursor: pointer; font-size: 13px; padding: 4px 0; }}
      .detail-panel {{ background: #fff; border-radius: 6px; padding: 8px;
                       margin-top: 8px; font-size: 12px; overflow-x: auto; }}
      .hidden {{ display: none; }}
      .max-loss {{ color: #ff3b30; font-size: 14px; font-weight: 500; }}
    </style>"""


def _dividend_section(signals: List[Any], pool_summary: Optional[Dict[str, Any]]) -> str:
    """Render the 高股息防御双打 section."""
    count = pool_summary.get("count", 0) if pool_summary else 0
    last_update = pool_summary.get("last_update", "N/A") if pool_summary else "N/A"

    parts = [
        '<div class="card">',
        '<h2>高股息防御双打 <a href="dividend_pool.html" class="info-badge" title="查看选股逻辑与完整池子">ⓘ</a></h2>',
        f'<div class="dividend-pool-summary">当前池子: <strong>{count}只标的</strong>'
        f" · 最近更新: <strong>{_escape(str(last_update))}</strong></div>",
        '<div class="dividend-signals-grid">',
    ]
    for sig in signals:
        parts.append(_dividend_card(sig))
    parts += ["</div>", "</div>"]
    return "\n".join(parts)


def format_html_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: List[TickerData],
    iv_high: List[TickerData],
    ma200_bullish: List[TickerData],
    ma200_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_puts: List[Tuple[SellPutSignal, TickerData]],
    skipped: Optional[List[Tuple[str, str]]] = None,
    iv_momentum: Optional[List[TickerData]] = None,
    earnings_gaps: Optional[list] = None,
    earnings_gap_ticker_map: Optional[dict] = None,
    elapsed_seconds: float = 0.0,
    dividend_signals: Optional[List[Any]] = None,
    dividend_pool_summary: Optional[Dict[str, Any]] = None,
    opportunity_cards: Optional[List[Dict]] = None,
) -> str:
    """Render the scan results as a self-contained Apple-style HTML page."""
    day_cn_map = {
        "Mon": "周一", "Tue": "周二", "Wed": "周三",
        "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日",
    }
    day_name = day_cn_map.get(scan_date.strftime("%a"), scan_date.strftime("%a"))
    skipped_list = skipped or []
    skipped_count = len(skipped_list)
    processed_count = universe_count - skipped_count

    parts = []
    parts.append("<!DOCTYPE html>")
    parts.append('<html lang="zh-CN">')
    parts.append("<head>")
    parts.append('<meta charset="utf-8">')
    parts.append('<meta name="viewport" content="width=device-width, initial-scale=1">')
    parts.append(f"<title>量化扫描雷达 — {scan_date}</title>")
    parts.append(f"<style>{CSS}</style>")
    parts.append("</head>")
    parts.append("<body>")
    parts.append('<div class="container">')

    # --- Header ---
    parts.append("<header>")
    parts.append(f"<h1>量化扫描雷达</h1>")
    parts.append(
        f'<div class="meta">'
        f"{scan_date} ({day_name}) · "
        f"数据源: {_escape(data_source)} · "
        f"标的数: {universe_count}"
        f"</div>"
    )
    parts.append("</header>")

    # --- Card: IV Extremes ---
    parts.append('<div class="card">')
    parts.append("<h2>波动率极值监控</h2>")
    parts.append("<h3>▼ 低波动率 (IV Rank &lt; 20%)</h3>")
    parts.append(_iv_table(iv_low))
    parts.append("<h3>▲ 高波动率 (IV Rank &gt; 80%)</h3>")
    parts.append(_iv_table(iv_high))
    parts.append("</div>")

    # --- Card: MA200 Crossover ---
    parts.append('<div class="card">')
    parts.append("<h2>趋势反转提醒 (MA200)</h2>")
    parts.append("<h3>↑ 向上突破 MA200</h3>")
    parts.append(_ma200_table(ma200_bullish))
    parts.append("<h3>↓ 向下跌破 MA200</h3>")
    parts.append(_ma200_table(ma200_bearish))
    parts.append("</div>")

    # --- Card: LEAPS ---
    parts.append('<div class="card">')
    parts.append("<h2>LEAPS 共振信号</h2>")
    parts.append(_leaps_table(leaps))
    parts.append("</div>")

    # --- Card: Sell Put ---
    parts.append('<div class="card">')
    parts.append("<h2>Sell Put 扫描</h2>")
    parts.append(_sell_put_table(sell_puts))
    parts.append("</div>")

    # --- Card: IV Momentum ---
    iv_momentum_list = iv_momentum or []
    parts.append('<div class="card">')
    parts.append("<h2>波动率异动雷达 (5日IV动量)</h2>")
    parts.append(_iv_momentum_table(iv_momentum_list))
    parts.append("</div>")

    # --- Card: Earnings Gap ---
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}
    parts.append('<div class="card">')
    parts.append("<h2>财报 Gap 预警</h2>")
    parts.append(_earnings_gap_table(gaps_list, gap_map))
    parts.append("</div>")

    # --- Card: High Dividend Defense (Phase 2, conditional) ---
    if dividend_signals:
        parts.append(_dividend_section(dividend_signals, dividend_pool_summary))

    # --- Opportunity Cards (conditional) ---
    cards_html = _render_cards_section(opportunity_cards or [])
    if cards_html:
        parts.append(cards_html)

    # --- Card: Skipped (conditional) ---
    if skipped_list:
        parts.append('<div class="card">')
        parts.append("<h2>跳过的标的</h2>")
        parts.append(_skipped_table(skipped_list))
        parts.append("</div>")

    # --- Footer ---
    parts.append(
        f"<footer>"
        f"扫描耗时 {elapsed_seconds:.1f}s · "
        f"处理: {processed_count} · "
        f"跳过: {skipped_count}"
        f"</footer>"
    )

    parts.append("</div>")  # .container
    parts.append("</body>")
    parts.append("</html>")

    return "\n".join(parts)
