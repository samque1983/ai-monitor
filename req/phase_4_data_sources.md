# Phase 4: 多数据源互备份架构

**状态**: 待实现
**优先级**: 中（当前 yfinance 够用，本阶段按需实现）

---

## 背景

yfinance 数据不稳定（频繁 404、限流），需要引入多数据源互备份机制，提升扫描可靠性。本地网关（IBKR/富途）因需要进程常驻，不保证自动化场景下可用，**云端 API 为主力，本地网关为增强**。

富途 OpenD 暂不接入（需本地网关，与 IBKR 同类问题），未来按需评估。

---

## 数据源清单

| 数据源 | 类型 | 覆盖市场 | 期权 | 稳定性 | 费用 |
|--------|------|---------|------|--------|------|
| IBKR TWS | 本地网关 | 全市场 | ✅ 实时 | 依赖本地进程 | 需开户 |
| Polygon/Massive | 云端 API | 美股 | ❌ 需付费 | 高 | 免费（无期权） |
| Tradier | 云端 API | 美股 | ✅ 15分钟延迟 | 高 | 免费注册 |
| yfinance | 云端爬取 | 美/港/A股 | ✅ 不稳定 | 低 | 免费 |

---

## 优先级路由设计

### 价格 / 历史数据（日线 OHLCV）

```
美股：     Polygon → yfinance
港股/A股：  yfinance
```

### 期权数据（Sell Put 扫描用）

```
美股期权：  IBKR（有则用）→ Tradier（15分钟延迟，日终扫描够用）→ 跳过
```

> 无可用期权数据时，期权扫描模块静默跳过，不报错。

### 基本面数据（股息率、派息率等）

```
美股：     Polygon → yfinance
港股/A股：  yfinance
```

---

## 架构设计

### DataSourceRouter（新模块）

在 `src/market_data.py` 中扩展，或新建 `src/data_router.py`：

```python
class DataSourceRouter:
    """市场感知的数据源路由，按优先级尝试各数据源"""

    def get_price_data(ticker, period) -> pd.DataFrame:
        market = classify_market(ticker)
        if market == "US":
            return try_in_order([polygon, yfinance], ticker, period)
        else:  # HK / CN
            return yfinance(ticker, period)

    def get_options_chain(ticker) -> pd.DataFrame:
        return try_in_order([ibkr, tradier], ticker) or pd.DataFrame()

    def get_fundamentals(ticker) -> dict:
        market = classify_market(ticker)
        if market == "US":
            return try_in_order([polygon, yfinance], ticker)
        else:
            return yfinance(ticker)
```

### 限流控制

Polygon 免费版：5 次/分钟 → 每次请求间隔 ≥ 250ms

### 配置（config.yaml）

```yaml
data_sources:
  polygon:
    enabled: true
    api_key: ""        # 通过环境变量 POLYGON_API_KEY 传入
  tradier:
    enabled: false     # 注册后启用
    api_key: ""        # 通过环境变量 TRADIER_API_KEY 传入
  ibkr:
    enabled: true
    host: "127.0.0.1"
    port: 4001
```

---

## 实现范围

1. `src/market_data.py` — 新增 `PolygonProvider` 和 `TradierProvider` 类
2. `DataSourceRouter` — 市场感知路由逻辑 + 限流
3. `config.yaml` — 新增 `data_sources` 配置块
4. `tests/test_market_data.py` — 覆盖路由逻辑和各 provider 的 mock

---

## 不在本阶段范围

- 富途 OpenD 接入（未来按需评估）
- Polygon 付费期权数据
- 实时/WebSocket 数据流
- 数据缓存层
