# src/report.py
from datetime import date
from typing import List, Optional, Tuple
from src.data_engine import TickerData, EarningsGap
from src.scanners import SellPutSignal


def format_earnings_tag(earnings_date: Optional[date], days: Optional[int]) -> str:
    if earnings_date and days is not None:
        return f"财报: {earnings_date} ({days}天)"
    return "财报: N/A"


def format_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: List[TickerData],
    iv_high: List[TickerData],
    ma200_bullish: List[TickerData],
    ma200_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_puts: List[Tuple[SellPutSignal, TickerData]],
    iv_momentum: Optional[List[TickerData]] = None,
    earnings_gaps: Optional[list] = None,
    earnings_gap_ticker_map: Optional[dict] = None,
    skipped: Optional[List[Tuple[str, str]]] = None,
    elapsed_seconds: float = 0.0,
) -> str:
    lines = []
    sep = "=" * 55

    # Header
    day_cn_map = {"Mon": "周一", "Tue": "周二", "Wed": "周三", "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"}
    day_name = day_cn_map.get(scan_date.strftime("%a"), scan_date.strftime("%a"))
    lines.append(sep)
    lines.append(f"  量化扫描雷达 \u2014 {scan_date} ({day_name})")
    lines.append(f"  数据源: {data_source} | 标的数: {universe_count}")
    lines.append(sep)
    lines.append("")

    # IV Extremes
    lines.append("── 波动率极值监控 ─────────────────────────────────")
    lines.append("")
    lines.append("▼ 低波动率 (IV Rank < 20%)")
    if iv_low:
        for t in iv_low:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")
    lines.append("▲ 高波动率 (IV Rank > 80%)")
    if iv_high:
        for t in iv_high:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # MA200 Crossover
    lines.append("── 趋势反转提醒 (MA200) ──────────────────────────")
    lines.append("")
    lines.append("↑ 向上突破 MA200")
    if ma200_bullish:
        for t in ma200_bullish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")
    lines.append("↓ 向下跌破 MA200")
    if ma200_bearish:
        for t in ma200_bearish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # LEAPS Setup
    lines.append("── LEAPS 共振信号 ────────────────────────────────")
    lines.append("")
    if leaps:
        for t in leaps:
            ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f}  MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)")
            lines.append(f"          RSI: {t.rsi14:.1f}  IV Rank: {t.iv_rank:.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无同时满足全部4项条件的标的)")
    lines.append("")

    # Sell Put
    lines.append("── Sell Put 扫描 ─────────────────────────────────")
    lines.append("")
    if sell_puts:
        for signal, t in sell_puts:
            lines.append(f"  {signal.ticker:<8} Strike: ${signal.strike:.0f}  DTE: {signal.dte}  Bid: ${signal.bid:.2f}  APY: {signal.apy:.1f}%")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
            if signal.earnings_risk:
                lines.append(f"          \U0001f6a8 警告: 财报日在DTE窗口内 \u2014 跳空风险")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # IV Momentum
    iv_momentum_list = iv_momentum or []
    lines.append("── 波动率异动雷达 (5日IV动量) ──────────────────────")
    lines.append("")

    if iv_momentum_list:
        for t in iv_momentum_list:
            iv_mom_str = f"+{t.iv_momentum:.1f}%" if t.iv_momentum else "N/A"
            iv_rank_str = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
            earnings_tag = format_earnings_tag(t.earnings_date, t.days_to_earnings)

            lines.append(
                f"  {t.ticker:<8} "
                f"IV动量: {iv_mom_str}  "
                f"IV Rank: {iv_rank_str}  "
                f"│ {earnings_tag}"
            )
    else:
        lines.append("  (无符合条件的标的)")

    lines.append("")

    # --- Earnings Gap ---
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}

    lines.append("── 财报 Gap 预警 ─────────────────────────────────")
    lines.append("")

    if gaps_list:
        for g in gaps_list:
            td = gap_map.get(g.ticker)

            # 提取信息 (兜底处理)
            days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
            iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"

            # 行1: 警告标题
            lines.append(f"  ⚠️ {g.ticker} 财报还有 {days_str}")

            # 行2: Gap 统计
            lines.append(
                f"     历史平均 Gap ±{g.avg_gap:.1f}%  |  "
                f"上涨概率 {g.up_ratio:.1f}%  |  "
                f"历史最大跳空 {g.max_gap:+.1f}%"
            )

            # 行3: 当前状态
            lines.append(
                f"     当前 IV Rank: {iv_str}  "
                f"(样本数: {g.sample_count})"
            )

            # 风险标注: 高 IV + 临近财报
            if td and td.iv_rank is not None and td.iv_rank > 70:
                lines.append(
                    f"     🔥 高 IV ({td.iv_rank:.1f}%) + 临近财报 → IV Crush 风险!"
                )

            lines.append("")
    else:
        lines.append("  (无符合条件的标的)")

    lines.append("")

    # Skipped tickers detail
    if skipped:
        lines.append("── 跳过的标的 (Skipped Tickers) ────────────────────")
        lines.append("")
        for ticker, reason in skipped:
            lines.append(f"  {ticker:<12} {reason}")
        lines.append("")

    # Footer
    skipped_count = len(skipped) if skipped else 0
    lines.append(sep)
    lines.append(f"  扫描耗时 {elapsed_seconds:.1f}s │ 处理: {universe_count - skipped_count} │ 跳过: {skipped_count}")
    lines.append(sep)

    return "\n".join(lines)
