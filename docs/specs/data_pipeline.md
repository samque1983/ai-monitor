# Data Pipeline Specification

**Modules**: `src/data_loader.py`, `src/market_data.py`, `src/iv_store.py`

**Purpose**: 数据获取、市场分类、IV 历史存储

---

## Architecture

```
Universe CSV → data_loader → MarketDataProvider → 各业务模块
                                    ↓
                               IVStore (SQLite)
```

---

## Module: data_loader.py

### Responsibilities
- 加载股票池 CSV (`universe.csv`)
- 市场分类判断（US/HK/CN）
- Ticker 规范化（BRK.B → BRK-B）

### Public Interface
```python
load_universe(csv_path: str) -> Tuple[List[str], List[str]]
classify_market(ticker: str) -> str
normalize_ticker(ticker: str) -> str
```

### Market Classification Rules
- **CN**: 纯数字（如 `600519`）
- **HK**: 纯数字（如 `00700`）
- **US**: 其他所有（字母开头）

### Ticker Normalization
- `BRK.B` → `BRK-B` (yfinance 兼容)
- `688xxx` → `688xxx.SS` (A 股后缀)

---

## Module: market_data.py

### Responsibilities
- 价格数据获取（日线/周线）
- IV 数据获取（期权链 → IV Rank）
- 财报日期获取（yfinance → CSV fallback）
- IV 动量计算（5 日变化率）

### Public Interface
```python
class MarketDataProvider:
    def __init__(ibkr_config, iv_db_path, config)
    def get_price_data(ticker, period) -> pd.DataFrame
    def get_weekly_price_data(ticker, period) -> pd.DataFrame
    def get_iv_rank(ticker) -> Optional[float]
    def get_earnings_date(ticker) -> Optional[date]
    def get_historical_earnings_dates(ticker, lookback) -> List[date]
    def get_iv_momentum(ticker, reference_date) -> Optional[float]
    def should_skip_options(ticker) -> bool
```

### Data Source Fallback Chain

| Method | Primary | Fallback |
|--------|---------|---------|
| `get_price_data` | IBKR `reqHistoricalData` (1 day) | yfinance `download` |
| `get_weekly_price_data` | IBKR `reqHistoricalData` (1 week) | yfinance `download` interval=1wk |
| `get_options_chain` | IBKR `reqSecDefOptParams` + `reqTickers` | yfinance `option_chain` |
| `get_earnings_date` | IBKR `reqFundamentalData('CalendarReport')` | yfinance `calendar` |
| `get_dividend_history` | — | yfinance only |
| `get_fundamentals` | — | yfinance only |
| `get_historical_earnings_dates` | — | yfinance → earnings_calendar.csv |

**Fallback pattern** (all IBKR-primary methods):
```python
if self.ibkr:
    try:
        return self._ibkr_<method>(...)
    except Exception as e:
        logger.warning(f"IBKR failed, falling back: {e}")
return self._yf_<method>(...)
```

### IBKR Contract Creation (`_make_contract`)

```python
# US:  Stock(ticker, 'SMART', 'USD')
# HK:  Stock(symbol_no_suffix, 'SEHK', 'HKD')   e.g. 0700.HK → 0700
# CN .SS: Stock(symbol, 'SSE',  'CNH')            e.g. 600900.SS → 600900
# CN .SZ: Stock(symbol, 'SZSE', 'CNH')            e.g. 000001.SZ → 000001
```

### IBKR Period Map (`_PERIOD_MAP`)

```python
{"5d": "5 D", "1mo": "1 M", "3mo": "3 M",
 "6mo": "6 M", "1y": "1 Y", "2y": "2 Y",
 "5y": "5 Y", "10y": "10 Y"}
```
Default: `"1 Y"` if period not in map.

### Timeout Configuration
- yfinance: **30 秒超时**（应对周末 API 不稳定）
- IBKR: 30 秒连接超时（`config.yaml` → `ibkr.timeout`）

### Error Isolation
- 单个 ticker 失败 → 返回 `None`，继续处理其他
- API 超时 → 记录 warning，触发 fallback

---

## Module: iv_store.py

### Responsibilities
- SQLite 存储 IV 历史数据
- IV 回溯查询（n 天前的 IV 值）
- 数据充足性检查（IVP/动量计算）

### Public Interface
```python
class IVStore:
    def __init__(db_path)
    def save_iv(ticker, iv_value, date)
    def get_iv_n_days_ago(ticker, n, reference_date) -> Optional[float]
    def get_data_sufficiency(ticker) -> Dict[str, Union[int, bool]]
```

### Data Sufficiency Thresholds
- **IVP**: ≥30 天数据
- **IV 动量**: ≥5 天数据

### Tolerance Window
- `get_iv_n_days_ago(n=5)` → 容差 n~n+3 天（应对周末/节假日）

---

## Integration Points

**→ data_engine.py**: 提供价格/IV 数据用于指标计算
**→ scanners.py**: 提供完整 TickerData 用于扫描逻辑
**→ main.py**: 统一入口，配置传递

---

## Configuration (config.yaml)

```yaml
data:
  ibkr:
    host: "127.0.0.1"
    port: 4001
    client_id: 1
    timeout: 30
  earnings_csv_path: "data/earnings_calendar.csv"
  iv_db_path: "data/iv_history.db"
```

---

## Multi-Datasource Routing (Phase 4)

### Provider Architecture

All providers live in `src/providers/` package and inherit from `BaseProvider`:

```
src/providers/
  __init__.py          # exports BaseProvider, PolygonProvider, TradierProvider, AkshareProvider
  base.py              # BaseProvider ABC (default no-op methods)
  polygon.py           # PolygonProvider
  tradier.py           # TradierProvider
  akshare.py           # AkshareProvider
```

**BaseProvider** (`src/providers/base.py`)
```python
class BaseProvider(ABC):
    def get_price_data(ticker, period) -> pd.DataFrame   # default: empty
    def get_options_chain(ticker, dte_min, dte_max) -> pd.DataFrame  # default: empty
    def get_fundamentals(ticker) -> Optional[Dict]       # default: None
```
New providers extend `BaseProvider` and override only the methods they support.

### Providers

**PolygonProvider** (`src/providers/polygon.py`)
- `get_price_data(ticker, period) → pd.DataFrame` — daily adjusted OHLCV via `/v2/aggs`
- `get_fundamentals(ticker) → Optional[Dict]` — name/industry via `/v3/reference/tickers`, ROE+FCF via `/vX/reference/financials`
- Rate limit: 250ms sleep after each request (5 req/min free tier)
- Activated via: `POLYGON_API_KEY` env var or `config.data_sources.polygon.api_key`

**TradierProvider** (`src/providers/tradier.py`)
- `get_options_chain(ticker, dte_min, dte_max) → pd.DataFrame` — put options via `/v1/markets/options/chains`
- 15-min delayed data (sandbox); suitable for end-of-day scanning
- Auth: `Authorization: Bearer {api_key}`, `Accept: application/json`
- Activated via: `TRADIER_API_KEY` env var or `config.data_sources.tradier.api_key`

**AkshareProvider** (`src/providers/akshare.py`)
- `get_price_data(ticker, period) → pd.DataFrame` — daily adjusted OHLCV for CN/HK/US via `ak.stock_zh_a_hist` / `ak.stock_hk_hist` / `ak.stock_us_hist`
- `get_fundamentals(ticker) → Optional[Dict]` — CN: name/industry via `stock_individual_info_em`; dividend_yield (TTM) via `stock_individual_spot_xq` (雪球实时行情, symbol `SH600036`/`SZ000001`); HK: name/industry via `stock_hk_company_profile_em`; US: returns None (not supported)
- `get_options_chain(ticker, dte_min, dte_max) → pd.DataFrame` — CN ETF options (50ETF/300ETF/科创50) via `option_finance_board`; US via `option_current_em` (best-effort)
- Ticker normalization: `600519.SS` → `600519` (East Money); `600036.SS` → `SH600036` (XueQiu); `0700.HK` → `00700` (5-digit pad)
- **注意**: `stock_zh_a_lg_indicator` 已在 akshare 1.18+ 移除，不可使用
- No API key required. Activated via: `config.data_sources.akshare.enabled` (default `true`)
- CN ETF option map: `510050`→`50ETF`, `510300`→`300ETF`, `588000`→`科创50`, `159901`→`深100ETF`

### Priority Chains

| Method | US Market | HK Market | CN Market |
|--------|-----------|-----------|-----------|
| `get_price_data` | IBKR → Polygon → AKShare → yfinance | IBKR → AKShare → yfinance | IBKR → AKShare → yfinance |
| `get_options_chain` | IBKR → Tradier → AKShare → yfinance | skip | AKShare (ETF only) |
| `get_fundamentals` | Polygon+yfinance merge | AKShare → yfinance | AKShare → yfinance |

**`should_skip_options` rules:**
- HK: always skip (no options market)
- CN: skip unless ticker is in `_CN_ETF_OPTION_MAP` (50ETF/300ETF/科创50/深100ETF)
- US: never skip

**Fundamentals merge (US):** Polygon provides `company_name`, `industry`, `roe`, `free_cash_flow`. yfinance fills in `sector`, `payout_ratio`, `debt_to_equity`, `dividend_yield`.

---

## Financial Data Integrity

遵循 `req/GLOBAL_MASTER.md` 第 II 章要求：

1. **复权调整**: 所有技术指标使用 Adjusted Close
2. **时差处理**: 财报日期使用 `date` 类型（不涉及时区）
3. **股息影响**: MA/RSI 基于复权价，已包含股息

---

## Testing

**Test File**: `tests/test_market_data.py`, `tests/test_data_loader.py`

**Coverage**:
- Market classification (US/HK/CN)
- Ticker normalization (BRK.B, A-shares)
- IBKR primary / yfinance fallback for price, weekly price, options chain, earnings date
- `_make_contract` routing for US/HK/CN/.SS/.SZ
- Earnings CSV fallback
- IV momentum calculation
- Data sufficiency checks
- PolygonProvider: price data, fundamentals (ROE/FCF), error handling
- TradierProvider: put options, DTE filter, error handling
- MarketDataProvider routing: Polygon for US price, Tradier for US options, yfinance fallback
- Fundamentals merge: Polygon fields + yfinance fills None fields
