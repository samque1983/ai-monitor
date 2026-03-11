# AKShare Provider — Design Doc

**Date**: 2026-03-11
**Status**: Approved, pending implementation

---

## Goal

Add AKShare as a data source to the `src/providers/` package. AKShare is a free, no-auth Python library with strong CN/HK market coverage. It fills two gaps in the current pipeline:

1. CN/HK price and fundamental data (currently yfinance-only, lower quality)
2. A-share options chain (50ETF/300ETF) — currently completely missing

---

## Architecture

### New Files

```
src/providers/akshare.py           # AkshareProvider implementation
tests/test_akshare_provider.py     # Mirror test file
```

`src/providers/__init__.py` exports `AkshareProvider`.

### Class Structure

```python
class AkshareProvider(BaseProvider):
    def __init__(self, enabled: bool = True)

    # Internal ticker normalization
    def _normalize_cn(ticker: str) -> str   # "600519.SS" → "600519"
    def _normalize_hk(ticker: str) -> str   # "0700.HK"   → "00700" (pad to 5 digits)

    # BaseProvider overrides — market-aware internal routing
    def get_price_data(ticker, period) -> pd.DataFrame
    def get_fundamentals(ticker) -> Optional[Dict]
    def get_options_chain(ticker, dte_min, dte_max) -> pd.DataFrame
```

### config.yaml

```yaml
data_sources:
  akshare:
    enabled: true   # no api_key needed
```

`MarketDataProvider.__init__` reads this flag and instantiates `self._akshare = AkshareProvider(enabled=...)`.

---

## Data Flow & Priority Chains

| Method | US | HK | CN |
|--------|----|----|-----|
| `get_price_data` | IBKR→Polygon→AKShare→yfinance | IBKR→AKShare→yfinance | IBKR→AKShare→yfinance |
| `get_fundamentals` | Polygon+yfinance (unchanged) | AKShare→yfinance | AKShare→yfinance |
| `get_options_chain` | IBKR→Tradier→AKShare→yfinance | skip | AKShare (new capability) |

### AKShare API Mapping

| Data | Market | AKShare Function |
|------|--------|-----------------|
| Price (daily, adj) | CN | `ak.stock_zh_a_hist(symbol, adjust="hfq")` |
| Price (daily, adj) | HK | `ak.stock_hk_hist(symbol, adjust="hfq")` |
| Price (daily, adj) | US | `ak.stock_us_hist(symbol, adjust="hfq")` |
| Fundamentals | CN | `ak.stock_financial_abstract_ths(symbol)` |
| Fundamentals | HK | `ak.stock_hk_financials_em(symbol)` |
| Options chain | CN (50ETF/300ETF) | `ak.option_finance_board(symbol)` |
| Options chain | US | `ak.option_current_em(symbol)` |

### Column Normalization

AKShare returns Chinese column names. All methods apply a standard mapping before returning:

```python
COLUMN_MAP = {
    "日期": "Date", "开盘": "Open", "最高": "High",
    "最低": "Low",  "收盘": "Close", "成交量": "Volume"
}
```

Output format is identical to existing providers (Date as index, standard OHLCV columns).

---

## Error Handling

- `enabled=False` → return empty DataFrame / None immediately, no AKShare calls
- Any exception → `logger.warning(f"AKShare ... failed for {ticker}: {e}")`, return empty/None
- Column mapping uses `.get(col, col)` for forward compatibility with AKShare API changes
- Timeout: rely on AKShare's default; wrap in try/except for network failures

---

## Testing

File: `tests/test_akshare_provider.py` — all tests mock `akshare` module, no real requests.

| Test | Coverage |
|------|----------|
| `test_cn_price_data` | Chinese columns → standard columns, hfq adjust |
| `test_hk_price_data` | `0700.HK` → `00700` ticker normalization |
| `test_us_price_data` | US price fallback path |
| `test_cn_fundamentals` | ROE/FCF/dividend_yield field extraction |
| `test_hk_fundamentals` | HK fundamentals |
| `test_cn_options_chain` | 50ETF/300ETF option chain |
| `test_us_options_chain` | AKShare as US options fallback |
| `test_disabled` | `enabled=False` returns empty, no AKShare import called |
| `test_api_error` | Exception → empty DataFrame, no raise |

`tests/test_market_data.py` additions:
- CN price chain: AKShare called before yfinance, after IBKR failure
- HK price chain: AKShare called before yfinance, after IBKR failure
- US options chain: AKShare called after Tradier failure, before yfinance
- AKShare disabled: chain skips directly to yfinance

---

## Implementation Notes

- `akshare` added to `requirements.txt` / `pyproject.toml`
- `MarketDataProvider` routing changes confined to `_get_price_data_cn`, `_get_price_data_hk`, `_get_options_chain_us` internal methods — minimal diff to existing logic
- CN options (50ETF/300ETF) require ticker-to-underlying mapping (e.g. "510050" → "50ETF") — handled inside `AkshareProvider.get_options_chain`
