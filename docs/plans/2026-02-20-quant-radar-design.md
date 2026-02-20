# V1.9 Quant Radar — Design Document

**Date:** 2026-02-20
**Status:** Approved

## Overview

A lightweight Python script that runs daily at 17:00 Beijing time (UTC+8). Scans a dynamically loaded stock universe from Google Sheets, computes technical indicators, and outputs a cold, data-only text report. No subjective trading advice.

## Key Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Deployment | Docker container | Reproducible, portable, long-term maintainable |
| Architecture | Monolithic with separated modules | Simple, testable, right-sized for 5 modules |
| Market data | IBKR primary, yfinance fallback | Accurate IV Rank from IBKR, resilience when Gateway is down |
| IV Rank storage | SQLite for yfinance fallback history | Builds IV Rank capability over time for fallback scenarios |
| Non-US tickers | US + HK: full scan. A-shares: price/indicators only, skip options | Options liquidity only reliable for US/HK |
| Config | config.yaml | Structured, readable, Docker-friendly |
| Output | stdout + timestamped .txt file | Email stub for later. Keep V1 simple |
| Schedule | 17:00 Beijing time | After both US and HK market close. Full closing data available |

## Data Flow

```
Google Sheet CSV
    → data_loader.py (pandas: clean, map columns, build Universe + Target Buy List)
    → market_data.py (IBKR→yfinance hybrid: price, IV, options, earnings)
    → data_engine.py (compute MA200, MA50w, RSI-14, IV Rank per ticker → TickerData)
    → scanners.py (run Modules 2-5, produce signal lists)
    → report.py (format text report → stdout + .txt file)
```

## Data Model

```python
@dataclass
class TickerData:
    ticker: str
    name: str
    market: str              # "US" | "HK" | "CN"
    last_price: float
    ma200: float | None      # Daily SMA 200
    ma50w: float | None      # Weekly SMA 50
    rsi14: float | None      # Daily RSI-14
    iv_rank: float | None    # 0-100%, None if unavailable
    prev_close: float        # For MA200 crossover detection
    earnings_date: date | None
    days_to_earnings: int | None
```

## Market Data Layer

### IBKR/yfinance Hybrid

`MarketDataProvider` class encapsulates all external data access:

- **Price data:** IBKR `reqHistoricalData` → yfinance `download()` fallback. Returns OHLCV DataFrame.
- **IV Rank:** IBKR provides IV percentile directly. yfinance fallback: derive ATM IV from options chain, store daily snapshots in `data/iv_history.db` (SQLite), compute rank from accumulated history.
- **Options chain:** IBKR `reqSecDefOptParams` + `reqMktData` → yfinance `option_chain()` fallback. Returns puts with strike/bid/DTE/IV.
- **Earnings date:** yfinance `calendar` (reliable for this). IBKR as backup.

### Ticker Classification

- US tickers: full data (price, indicators, options, IV)
- HK tickers (`.HK`): price, indicators, options attempt
- A-shares (`.SS`, `.SZ`): price + indicators only, skip options modules

## Scanner Modules

### Module 1: Data Engine
Computes per-ticker: current price, MA200 (daily SMA 200), MA50w (weekly SMA 50), RSI-14, IV Rank, earnings date/days.

### Module 2: IV Extremes
- Low IV list: `iv_rank < 20%`
- High IV list: `iv_rank > 80%`

### Module 3: MA200 Crossover
- Bullish: `prev_close < ma200` AND `last_price > ma200` (or within +1%)
- Bearish: `prev_close > ma200` AND `last_price < ma200` (or within -1%)

### Module 4: LEAPS Setup (V1.9 共振)
All 4 conditions must be true:
1. `last_price > ma200`
2. `abs(last_price - ma50w) / ma50w <= 0.03`
3. `rsi14 <= 45`
4. `iv_rank < 30%` (skip ticker if iv_rank unavailable)

### Module 5: Sell Put Scanner
- Iterates `Target Buy List` (from CSV "Strike (黄金位)" column)
- Filters options: DTE 45-60, strike ≤ target price (closest)
- APY = `(bid / strike) * (365 / dte)`
- Only output APY ≥ 4.0%
- Earnings risk flag: if earnings_date falls within DTE window → 🚨 warning

## Report Format

Clean, modular, cold text. Each signal includes mandatory earnings date + days-to-earnings. Summary footer with scan duration and error count.

## Error Handling

- Per-ticker try-except: one failure never crashes the scan
- IBKR disconnect → automatic yfinance fallback with log
- CSV fetch failure → abort (no data = no scan)
- Failed tickers logged to `logs/radar_YYYY-MM-DD.log`
- Summary footer shows skipped ticker count

## Project Structure

```
ai-monitor/
├── src/
│   ├── main.py           # Entry point + orchestration
│   ├── config.py          # Load config.yaml
│   ├── data_loader.py     # CSV fetch + pandas cleaning
│   ├── market_data.py     # IBKR/yfinance hybrid provider
│   ├── data_engine.py     # Indicator computation → TickerData
│   ├── scanners.py        # Modules 2-5 signal detection
│   ├── report.py          # Text report formatter
│   └── email_stub.py      # send_email() placeholder
├── tests/
│   ├── test_data_loader.py
│   ├── test_market_data.py
│   ├── test_data_engine.py
│   ├── test_scanners.py
│   └── test_report.py
├── data/
│   └── iv_history.db      # SQLite for IV snapshots (auto-created)
├── reports/                # Generated reports (auto-created)
├── logs/                   # Error logs (auto-created)
├── config.yaml
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── CLAUDE.md
```

## Dependencies

- `ib_insync` — IBKR API client
- `yfinance` — Yahoo Finance fallback
- `pandas` — Data manipulation
- `PyYAML` — Config loading
- `schedule` or Docker cron — Scheduling (TBD in implementation plan)
