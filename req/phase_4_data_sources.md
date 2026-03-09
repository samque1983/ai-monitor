# Phase 4: 多数据源互备份架构

**状态**: 待实现
**优先级**: 中（当前 yfinance 够用，本阶段按需实现）

---

## 背景

yfinance 数据不稳定（频繁 404、限流），需要引入多数据源互备份机制，提升扫描可靠性。

**设计原则**：
- 本地 TWS/Gateway（IBKR socket）仅在本地 Mac 运行扫描时可用，不保证云端自动化场景
- **IBKR REST API（OAuth 2.0）是云端可用的 IBKR 官方 API**，无需本地进程，可作为云端主力数据源
- Polygon / Tradier 作为 IBKR REST API 的互备
- yfinance 兜底，港股/A股只用 yfinance

富途 OpenD 暂不接入（需本地网关），未来按需评估。

---

## 数据源清单

| 数据源 | 类型 | 覆盖市场 | 期权 | 稳定性 | 费用 |
|--------|------|---------|------|--------|------|
| IBKR REST API | 云端 OAuth API | 全市场 | ✅ 延迟/实时 | 高 | 需开户，免费 |
| IBKR TWS | 本地网关 | 全市场 | ✅ 实时 | 依赖本地进程 | 需开户 |
| Polygon | 云端 API | 美股 | ❌ 需付费 | 高 | 免费（无期权） |
| Tradier | 云端 API | 美股 | ✅ 15分钟延迟 | 高 | 免费注册 |
| yfinance | 云端爬取 | 美/港/A股 | ✅ 不稳定 | 低 | 免费 |

---

## IBKR REST API 说明

- 文档：`https://developer.ibkr.com/en/articles/ibkr-api-overview`
- Base URL：`https://api.ibkr.com/v1/api/`
- 延迟数据：默认 15 分钟延迟（免费）；实时数据需市场数据订阅

### 认证机制（RSA 私钥签名，非 client_secret）

IBKR Web API 使用 Confidential Client OAuth，**不是**普通的 client_id + client_secret：

```
1. 本地生成 RSA-2048 密钥对
2. 上传公钥到 developer.ibkr.com（绑定到注册的应用）
3. 用私钥对请求 JWT 签名 → POST /v1/api/oauth/token
4. 换取 access_token（~1小时有效）+ refresh_token（长效）
5. access_token 过期后，用 refresh_token 自动续期
```

私钥存 Fly.io secrets（`IBKR_PRIVATE_KEY`），绝不写入代码或配置文件。

### 关键端点

**仓位查询：**
```
GET /v1/api/portfolio/accounts
  → 返回 accountId 列表

GET /v1/api/portfolio/{accountId}/positions/0
  → 仓位列表（最多 100 条/页，支持分页）
  → 字段：ticker, conid, position (负数=空头),
          mktPrice, mktValue, avgCost,
          unrealizedPnl, realizedPnl

GET /v1/api/portfolio/{accountId}/summary
  → 账户摘要（NAV, 现金, 保证金占用）
```

**Sell Put 仓位识别：**
- `position < 0` = 空头（卖出）
- 确认 contract type = OPT：`GET /v1/api/contract/{conid}/info`

**行情 / 扫描数据：**
```
GET /v1/api/iserver/marketdata/history?conid=...&period=1Y&bar=1d
  → 历史 OHLCV（conid 需先通过 /iserver/secdef/search 查询）

GET /v1/api/iserver/secdef/strikes?conid=...&sectype=OPT&...
  → 期权行权价列表

GET /v1/api/iserver/secdef/info?conid=...&sectype=OPT&...
  → 期权合约详情（bid/ask/IV）
```

> **注意**：需要去 `developer.ibkr.com` 注册应用，审批通常 1-3 天。
> 注册时选 **Read-Only** 权限即可满足扫描 + 仓位查询需求。

---

## 优先级路由设计

### 价格 / 历史数据（日线 OHLCV）

```
美股：     IBKR TWS（本地）→ IBKR REST API → Polygon → yfinance
港股/A股：  IBKR TWS（本地）→ IBKR REST API → yfinance
```

### 期权数据（Sell Put 扫描用）

```
美股期权：  IBKR TWS（本地）→ IBKR REST API → Tradier → yfinance → 跳过
```

> 无可用期权数据时，期权扫描模块静默跳过，不报错。

### 基本面数据（股息率、派息率等）

```
美股：     Polygon → yfinance（Polygon 缺失字段由 yfinance 补全）
港股/A股：  yfinance
```

> IBKR 基本面数据接口覆盖不全，不纳入基本面路由。

---

## 架构设计

### Provider 类（均在 `src/market_data.py`）

```python
class IBKRRestProvider:
    """IBKR OAuth REST API，云端无需本地进程"""
    # get_price_data(ticker, period) -> pd.DataFrame
    # get_options_chain(ticker, dte_min, dte_max) -> pd.DataFrame
    # refresh_token_if_needed()

class PolygonProvider:
    """Polygon.io 云端 API，美股价格 + 基本面"""
    # get_price_data(ticker, period) -> pd.DataFrame
    # get_fundamentals(ticker) -> Optional[Dict]

class TradierProvider:
    """Tradier 云端 API，美股期权（15分钟延迟）"""
    # get_options_chain(ticker, dte_min, dte_max) -> pd.DataFrame
```

### 路由逻辑（在 `MarketDataProvider` 中）

```python
def get_price_data(ticker, period):
    if ibkr_tws:          return ibkr_tws.get_price_data(...)
    if ibkr_rest:         return ibkr_rest.get_price_data(...) or next
    if polygon and US:    return polygon.get_price_data(...) or next
    return yfinance(...)

def get_options_chain(ticker, dte_min, dte_max):
    if cn_market:  return empty
    if ibkr_tws:   return ibkr_tws.get_options_chain(...)
    if ibkr_rest:  return ibkr_rest.get_options_chain(...) or next
    if tradier:    return tradier.get_options_chain(...) or next
    return yfinance_options(...)
```

### Token 管理

IBKR REST API 的 access_token 需要定期刷新：
- 首次：用 `client_id` + `client_secret` + 授权码换取 `access_token` + `refresh_token`
- 自动刷新：每次请求前检查 token 是否过期，过期则用 `refresh_token` 换新 token
- 存储：token 存入环境变量或本地文件（不提交到 git）

### 限流控制

| 数据源 | 限制 | 控制方式 |
|--------|------|---------|
| Polygon 免费版 | 5次/分钟 | 每次请求后 sleep(0.25s) |
| Tradier | 无严格限制 | 无需限流 |
| IBKR REST | 50次/秒 | 无需限流 |

### 配置（config.yaml）

```yaml
data_sources:
  ibkr_rest:
    enabled: false     # 注册审批后启用
    client_id: ""      # 通过环境变量 IBKR_CLIENT_ID 传入
    # access_token 和 refresh_token 通过环境变量传入，不写入配置文件
  polygon:
    enabled: true
    api_key: ""        # 通过环境变量 POLYGON_API_KEY 传入
  tradier:
    enabled: false     # 注册后启用
    api_key: ""        # 通过环境变量 TRADIER_API_KEY 传入
    sandbox: true      # true=沙盒（延迟），false=生产
  ibkr_tws:
    enabled: true      # 本地运行时自动尝试连接
    host: "127.0.0.1"
    port: 4001
```

---

## 实现范围

1. `src/market_data.py` — 新增 `PolygonProvider`、`TradierProvider`、`IBKRRestProvider` 类
2. `MarketDataProvider` — 市场感知路由逻辑更新
3. `config.yaml` — 新增 `data_sources` 配置块
4. `tests/test_market_data.py` — 覆盖路由逻辑和各 provider 的 mock

### 实现优先级

| 优先级 | Provider | 理由 |
|--------|----------|------|
| P1 | Polygon（价格） | 注册快，API 简单，解决 yfinance 不稳定 |
| P1 | Tradier（期权） | 注册免费，解决无本地 IBKR 时期权链缺失 |
| P2 | IBKR REST API | 需等审批（1-3天），但一旦上线可替代 Polygon+Tradier |
| P3 | Polygon（基本面） | yfinance 基本面稳定，优先级低 |

---

## 不在本阶段范围

- 富途 OpenD 接入（未来按需评估）
- Polygon 付费期权数据
- 实时/WebSocket 数据流
- 数据缓存层
