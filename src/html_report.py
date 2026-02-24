# src/html_report.py
"""Apple-style HTML report renderer for the ai-monitor scanner."""
from datetime import date
from html import escape as _html_escape
from typing import List, Optional, Tuple

from src.data_engine import TickerData
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
"""


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
    elapsed_seconds: float = 0.0,
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
