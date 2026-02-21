# src/report.py
from datetime import date
from typing import List, Optional, Tuple
from src.data_engine import TickerData
from src.scanners import SellPutSignal


def format_earnings_tag(earnings_date: Optional[date], days: Optional[int]) -> str:
    if earnings_date and days is not None:
        return f"Earnings: {earnings_date} ({days}d)"
    return "Earnings: N/A"


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
    errors_count: int,
    elapsed_seconds: float,
) -> str:
    lines = []
    sep = "=" * 55

    # Header
    day_name = scan_date.strftime("%a")
    lines.append(sep)
    lines.append(f"  V1.9 QUANT RADAR \u2014 {scan_date} ({day_name})")
    lines.append(f"  Data Source: {data_source} | Universe: {universe_count} tickers")
    lines.append(sep)
    lines.append("")

    # Module 2: IV Extremes
    lines.append("\u2500\u2500 MODULE 2: IV EXTREMES \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append("")
    lines.append("\u25bc LOW IV (IV Rank < 20%)")
    if iv_low:
        for t in iv_low:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("\u25b2 HIGH IV (IV Rank > 80%)")
    if iv_high:
        for t in iv_high:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Module 3: MA200 Crossover
    lines.append("\u2500\u2500 MODULE 3: MA200 CROSSOVER \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append("")
    lines.append("\u2191 BULLISH CROSS (Price > MA200)")
    if ma200_bullish:
        for t in ma200_bullish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("\u2193 BEARISH CROSS (Price < MA200)")
    if ma200_bearish:
        for t in ma200_bearish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Module 4: LEAPS Setup
    lines.append("\u2500\u2500 MODULE 4: LEAPS SETUP (V1.9 \u5171\u632f) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append("")
    if leaps:
        for t in leaps:
            ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f}  MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)")
            lines.append(f"          RSI: {t.rsi14:.1f}  IV Rank: {t.iv_rank:.1f}%  \u2502 {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (no tickers meet all 4 conditions)")
    lines.append("")

    # Module 5: Sell Put
    lines.append("\u2500\u2500 MODULE 5: SELL PUT SCANNER \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500")
    lines.append("")
    if sell_puts:
        for signal, t in sell_puts:
            lines.append(f"  {signal.ticker:<8} Strike: ${signal.strike:.0f}  DTE: {signal.dte}  Bid: ${signal.bid:.2f}  APY: {signal.apy:.1f}%")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
            if signal.earnings_risk:
                lines.append(f"          \U0001f6a8 WARNING: Earnings falls within DTE window \u2014 gap risk")
    else:
        lines.append("  (none)")
    lines.append("")

    # Footer
    lines.append(sep)
    lines.append(f"  Scan completed in {elapsed_seconds:.1f}s \u2502 Errors: {errors_count} tickers skipped")
    lines.append(sep)

    return "\n".join(lines)
