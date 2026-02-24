# Report Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Convert TXT report to Chinese, add Apple-style HTML report, remove "Module X" labels and version numbers.

**Architecture:** Dual renderer — modify `report.py` for Chinese TXT, create `html_report.py` for HTML. Both share same function signature. `main.py` calls both.

**Tech Stack:** Python 3.9, no new dependencies (HTML generated via f-strings)

---

### Task 1: Chinese TXT Report — Update `format_earnings_tag`

**Files:**
- Modify: `src/report.py:8-11`
- Test: `tests/test_report.py`

**Step 1: Write the failing test**

Update `tests/test_report.py` — change `TestFormatEarningsTag` assertions to expect Chinese:

```python
class TestFormatEarningsTag:
    def test_with_date(self):
        tag = format_earnings_tag(date(2026, 4, 25), 64)
        assert "2026-04-25" in tag
        assert "64天" in tag
        assert "财报" in tag

    def test_without_date(self):
        tag = format_earnings_tag(None, None)
        assert "N/A" in tag
        assert "财报" in tag
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py::TestFormatEarningsTag -v`
Expected: FAIL — "64天" not found (currently outputs "64d"), "财报" not found (currently "Earnings")

**Step 3: Write minimal implementation**

In `src/report.py`, change `format_earnings_tag`:

```python
def format_earnings_tag(earnings_date: Optional[date], days: Optional[int]) -> str:
    if earnings_date and days is not None:
        return f"财报: {earnings_date} ({days}天)"
    return "财报: N/A"
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py::TestFormatEarningsTag -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: convert earnings tag to Chinese (财报)"
```

---

### Task 2: Chinese TXT Report — Update `format_report` text

**Files:**
- Modify: `src/report.py:14-117`
- Test: `tests/test_report.py`

**Step 1: Write the failing tests**

Update the assertions in `tests/test_report.py`:

```python
class TestFormatReport:
    def test_report_contains_header(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="IBKR Gateway",
            universe_count=42,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[],
            elapsed_seconds=12.5,
        )
        assert "量化扫描雷达" in report
        assert "2026-02-20" in report
        assert "42" in report
        assert "V1.9" not in report

    def test_report_contains_iv_extremes(self):
        low = [make_ticker(ticker="AAPL", iv_rank=12.3)]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=low, iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "AAPL" in report
        assert "12.3" in report
        assert "波动率极值监控" in report

    def test_report_contains_sell_put_warning(self):
        signal = SellPutSignal(
            ticker="NVDA", strike=110.0, bid=1.80,
            dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True,
        )
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[(signal, make_ticker(ticker="NVDA"))],
            elapsed_seconds=5.0,
        )
        assert "NVDA" in report
        assert "\U0001f6a8" in report

    def test_empty_modules_show_chinese_none(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "无符合条件的标的" in report

    def test_skipped_tickers_show_reasons(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            skipped=[
                ("BRK.B", "无价格数据 (no price data)"),
                ("600900", "无价格数据 (no price data)"),
            ],
            elapsed_seconds=5.0,
        )
        assert "BRK.B" in report
        assert "600900" in report
        assert "无价格数据" in report
        assert "跳过: 2" in report
        assert "处理: 8" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py::TestFormatReport -v`
Expected: Multiple FAILs — "量化扫描雷达" not found, "波动率极值监控" not found, etc.

**Step 3: Write minimal implementation**

Replace entire `format_report` body in `src/report.py`:

```python
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
    skipped: Optional[List[Tuple[str, str]]] = None,
    elapsed_seconds: float = 0.0,
) -> str:
    DAY_NAMES = {"Mon": "周一", "Tue": "周二", "Wed": "周三", "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"}
    lines = []
    sep = "=" * 55

    # Header
    day_en = scan_date.strftime("%a")
    day_cn = DAY_NAMES.get(day_en, day_en)
    lines.append(sep)
    lines.append(f"  量化扫描雷达 — {scan_date} ({day_cn})")
    lines.append(f"  数据源: {data_source} | 标的数: {universe_count}")
    lines.append(sep)
    lines.append("")

    # 波动率极值监控
    lines.append("── 波动率极值监控 ─────────────────────────────────")
    lines.append("")
    lines.append("▼ 低波动率 (IV Rank < 20%)")
    if iv_low:
        for t in iv_low:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")
    lines.append("▲ 高波动率 (IV Rank > 80%)")
    if iv_high:
        for t in iv_high:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # 趋势反转提醒
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

    # LEAPS 共振信号
    lines.append("── LEAPS 共振信号 ────────────────────────────────")
    lines.append("")
    if leaps:
        for t in leaps:
            ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f}  MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)")
            lines.append(f"          RSI: {t.rsi14:.1f}  IV Rank: {t.iv_rank:.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (无同时满足全部4项条件的标的)")
    lines.append("")

    # Sell Put 扫描
    lines.append("── Sell Put 扫描 ─────────────────────────────────")
    lines.append("")
    if sell_puts:
        for signal, t in sell_puts:
            lines.append(f"  {signal.ticker:<8} Strike: ${signal.strike:.0f}  DTE: {signal.dte}  Bid: ${signal.bid:.2f}  APY: {signal.apy:.1f}%")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
            if signal.earnings_risk:
                lines.append(f"          \U0001f6a8 警告: 财报日在DTE窗口内 — 跳空风险")
    else:
        lines.append("  (无符合条件的标的)")
    lines.append("")

    # 跳过的标的
    if skipped:
        lines.append("── 跳过的标的 ────────────────────────────────────")
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
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: convert TXT report to Chinese, remove Module labels and version"
```

---

### Task 3: Update integration test for Chinese report

**Files:**
- Modify: `tests/test_integration.py:64-65`

**Step 1: Update assertions**

In `tests/test_integration.py`, change lines 64-65:

```python
    assert "量化扫描雷达" in report
    assert "AAPL" in report or "无符合条件的标的" in report
```

**Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/test_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: update integration test for Chinese report"
```

---

### Task 4: HTML Report — Tests

**Files:**
- Create: `tests/test_html_report.py`
- Create: `src/html_report.py` (empty stub in next task)

**Step 1: Write the failing tests**

Create `tests/test_html_report.py`:

```python
# tests/test_html_report.py
import pytest
from datetime import date
from src.data_engine import TickerData
from src.scanners import SellPutSignal
from src.html_report import format_html_report


def make_ticker(**kwargs) -> TickerData:
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestHtmlReport:
    def test_contains_html_structure(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "<!DOCTYPE html>" in html
        assert "<html" in html
        assert "</html>" in html
        assert "量化扫描雷达" in html

    def test_contains_chinese_header(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="IBKR Gateway",
            universe_count=42,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=12.5,
        )
        assert "量化扫描雷达" in html
        assert "2026-02-20" in html
        assert "42" in html
        assert "V1.9" not in html

    def test_contains_module_titles(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "波动率极值监控" in html
        assert "趋势反转提醒" in html
        assert "LEAPS 共振信号" in html
        assert "Sell Put 扫描" in html

    def test_empty_modules_show_chinese_none(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "无符合条件的标的" in html

    def test_contains_ticker_data(self):
        low = [make_ticker(ticker="AAPL", iv_rank=12.3)]
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=low, iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "AAPL" in html
        assert "12.3" in html

    def test_sell_put_earnings_warning(self):
        signal = SellPutSignal(
            ticker="NVDA", strike=110.0, bid=1.80,
            dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True,
        )
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[(signal, make_ticker(ticker="NVDA"))],
            elapsed_seconds=5.0,
        )
        assert "NVDA" in html
        assert "\U0001f6a8" in html or "🚨" in html

    def test_skipped_tickers(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            skipped=[
                ("BRK.B", "无价格数据"),
                ("600900", "无价格数据"),
            ],
            elapsed_seconds=5.0,
        )
        assert "BRK.B" in html
        assert "600900" in html
        assert "跳过: 2" in html

    def test_inline_css(self):
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            elapsed_seconds=5.0,
        )
        assert "<style>" in html
        assert "max-width" in html
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_html_report.py -v`
Expected: FAIL — ImportError (module doesn't exist yet)

**Step 3: Commit**

```bash
git add tests/test_html_report.py
git commit -m "test: add HTML report tests (red)"
```

---

### Task 5: HTML Report — Implementation

**Files:**
- Create: `src/html_report.py`

**Step 1: Create `src/html_report.py`**

```python
# src/html_report.py
from datetime import date
from typing import List, Optional, Tuple
from src.data_engine import TickerData
from src.scanners import SellPutSignal


def _earnings_tag(earnings_date: Optional[date], days: Optional[int]) -> str:
    if earnings_date and days is not None:
        return f"财报: {earnings_date} ({days}天)"
    return "财报: N/A"


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


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
    DAY_NAMES = {"Mon": "周一", "Tue": "周二", "Wed": "周三", "Thu": "周四", "Fri": "周五", "Sat": "周六", "Sun": "周日"}
    day_en = scan_date.strftime("%a")
    day_cn = DAY_NAMES.get(day_en, day_en)
    skipped_count = len(skipped) if skipped else 0
    processed_count = universe_count - skipped_count

    # --- Build card sections ---

    # IV Extremes
    iv_low_rows = ""
    if iv_low:
        for t in iv_low:
            iv_low_rows += f'<tr><td class="ticker">{_escape(t.ticker)}</td><td>IV Rank: {t.iv_rank:.1f}%</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}</td></tr>\n'
    else:
        iv_low_rows = '<tr><td colspan="3" class="empty">无符合条件的标的</td></tr>'

    iv_high_rows = ""
    if iv_high:
        for t in iv_high:
            iv_high_rows += f'<tr><td class="ticker">{_escape(t.ticker)}</td><td>IV Rank: {t.iv_rank:.1f}%</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}</td></tr>\n'
    else:
        iv_high_rows = '<tr><td colspan="3" class="empty">无符合条件的标的</td></tr>'

    # MA200 Crossover
    ma200_bull_rows = ""
    if ma200_bullish:
        for t in ma200_bullish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            ma200_bull_rows += f'<tr><td class="ticker">{_escape(t.ticker)}</td><td>${t.last_price:.2f}</td><td>MA200: ${t.ma200:.2f} ({pct:+.2f}%)</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}</td></tr>\n'
    else:
        ma200_bull_rows = '<tr><td colspan="4" class="empty">无符合条件的标的</td></tr>'

    ma200_bear_rows = ""
    if ma200_bearish:
        for t in ma200_bearish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            ma200_bear_rows += f'<tr><td class="ticker">{_escape(t.ticker)}</td><td>${t.last_price:.2f}</td><td>MA200: ${t.ma200:.2f} ({pct:+.2f}%)</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}</td></tr>\n'
    else:
        ma200_bear_rows = '<tr><td colspan="4" class="empty">无符合条件的标的</td></tr>'

    # LEAPS
    leaps_rows = ""
    if leaps:
        for t in leaps:
            ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
            leaps_rows += f'<tr><td class="ticker">{_escape(t.ticker)}</td><td>${t.last_price:.2f}</td><td>MA200: ${t.ma200:.2f}</td><td>MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)</td><td>RSI: {t.rsi14:.1f}</td><td>IV Rank: {t.iv_rank:.1f}%</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}</td></tr>\n'
    else:
        leaps_rows = '<tr><td colspan="7" class="empty">无同时满足全部4项条件的标的</td></tr>'

    # Sell Put
    sell_put_rows = ""
    if sell_puts:
        for signal, t in sell_puts:
            warning = ""
            if signal.earnings_risk:
                warning = '<div class="warning">\U0001f6a8 警告: 财报日在DTE窗口内 — 跳空风险</div>'
            sell_put_rows += f'<tr><td class="ticker">{_escape(signal.ticker)}</td><td>Strike: ${signal.strike:.0f}</td><td>DTE: {signal.dte}</td><td>Bid: ${signal.bid:.2f}</td><td>APY: {signal.apy:.1f}%</td><td class="earnings">{_earnings_tag(t.earnings_date, t.days_to_earnings)}{warning}</td></tr>\n'
    else:
        sell_put_rows = '<tr><td colspan="6" class="empty">无符合条件的标的</td></tr>'

    # Skipped
    skipped_section = ""
    if skipped:
        skip_rows = ""
        for ticker, reason in skipped:
            skip_rows += f'<tr><td class="ticker">{_escape(ticker)}</td><td>{_escape(reason)}</td></tr>\n'
        skipped_section = f'''
    <div class="card">
      <h2>跳过的标的</h2>
      <table>{skip_rows}</table>
    </div>'''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>量化扫描雷达 — {scan_date}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Text', 'Helvetica Neue', sans-serif;
    background: #f5f5f7;
    color: #1d1d1f;
    line-height: 1.6;
    padding: 40px 20px;
  }}
  .container {{ max-width: 720px; margin: 0 auto; }}
  .header {{
    text-align: center;
    margin-bottom: 32px;
    padding: 32px 0;
  }}
  .header h1 {{
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.5px;
    margin-bottom: 8px;
  }}
  .header .meta {{
    font-size: 14px;
    color: #86868b;
  }}
  .card {{
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    padding: 24px;
    margin-bottom: 16px;
  }}
  .card h2 {{
    font-size: 17px;
    font-weight: 600;
    margin-bottom: 16px;
    padding-bottom: 8px;
    border-bottom: 1px solid #d2d2d7;
  }}
  .card h3 {{
    font-size: 14px;
    font-weight: 500;
    color: #1d1d1f;
    margin: 12px 0 8px;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }}
  td {{
    padding: 6px 8px;
    vertical-align: top;
  }}
  .ticker {{
    font-weight: 600;
    font-family: 'SF Mono', 'Menlo', monospace;
    min-width: 70px;
  }}
  .earnings {{
    color: #86868b;
    font-size: 13px;
  }}
  .empty {{
    color: #86868b;
    font-style: italic;
    padding: 12px 8px;
  }}
  .warning {{
    background: #fff2f0;
    color: #d4380d;
    padding: 4px 8px;
    border-radius: 6px;
    font-size: 13px;
    margin-top: 4px;
    display: inline-block;
  }}
  .footer {{
    text-align: center;
    font-size: 13px;
    color: #86868b;
    margin-top: 24px;
    padding-top: 16px;
    border-top: 1px solid #d2d2d7;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>量化扫描雷达</h1>
    <div class="meta">{scan_date} ({day_cn}) · 数据源: {_escape(data_source)} · 标的数: {universe_count}</div>
  </div>

  <div class="card">
    <h2>波动率极值监控</h2>
    <h3>▼ 低波动率 (IV Rank &lt; 20%)</h3>
    <table>{iv_low_rows}</table>
    <h3>▲ 高波动率 (IV Rank &gt; 80%)</h3>
    <table>{iv_high_rows}</table>
  </div>

  <div class="card">
    <h2>趋势反转提醒 (MA200)</h2>
    <h3>↑ 向上突破 MA200</h3>
    <table>{ma200_bull_rows}</table>
    <h3>↓ 向下跌破 MA200</h3>
    <table>{ma200_bear_rows}</table>
  </div>

  <div class="card">
    <h2>LEAPS 共振信号</h2>
    <table>{leaps_rows}</table>
  </div>

  <div class="card">
    <h2>Sell Put 扫描</h2>
    <table>{sell_put_rows}</table>
  </div>
{skipped_section}
  <div class="footer">
    扫描耗时 {elapsed_seconds:.1f}s · 处理: {processed_count} · 跳过: {skipped_count}
  </div>
</div>
</body>
</html>'''
```

**Step 2: Run test to verify it passes**

Run: `python3 -m pytest tests/test_html_report.py -v`
Expected: ALL PASS

**Step 3: Commit**

```bash
git add src/html_report.py
git commit -m "feat: add Apple-style HTML report renderer"
```

---

### Task 6: Wire HTML report into main.py

**Files:**
- Modify: `src/main.py:14,106-116`

**Step 1: Update `src/main.py`**

Add import at top (after line 13):

```python
from src.html_report import format_html_report
```

After the existing `format_report` call (after line 105), add:

```python
    html_report = format_html_report(
        scan_date=today,
        data_source=data_source,
        universe_count=len(tickers),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_put_results,
        skipped=skipped,
        elapsed_seconds=elapsed,
    )
```

After saving the TXT file (after line 116), add:

```python
    html_path = os.path.join(reports_dir, f"{today}_radar.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    logger.info(f"HTML report saved: {html_path}")
```

**Step 2: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL PASS (main.py changes don't break anything)

**Step 3: Commit**

```bash
git add src/main.py
git commit -m "feat: wire HTML report into main pipeline"
```

---

### Task 7: Final verification

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v`
Expected: ALL tests pass

**Step 2: Quick manual test (optional)**

Run: `python3 -m src.main`
Verify: Both `.txt` and `.html` files generated in reports dir. Open HTML in browser.

**Step 3: Commit any remaining fixes if needed**
