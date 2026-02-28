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
1. **IBKR Gateway** (优先，实时数据)
2. **yfinance** (主要，历史数据)
3. **earnings_calendar.csv** (fallback，财报日期)

### Timeout Configuration
- yfinance: **30 秒超时**（应对周末 API 不稳定）
- IBKR: 30 秒连接超时

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
- Earnings CSV fallback
- IV momentum calculation
- Data sufficiency checks
