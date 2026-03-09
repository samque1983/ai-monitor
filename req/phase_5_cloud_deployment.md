# Phase 5: 云端部署 + Dashboard + OpenClaw 集成

**状态**: 待实现
**优先级**: 中

---

## 背景

当前系统已具备扫描引擎、多数据源路由（Phase 4）。
本阶段目标：将系统部署为单租户云服务，提供 Web Dashboard 和 OpenClaw/WhatsApp 对话接口。

**关键决策：单租户私有部署，非多租户 SaaS**
- 无用户注册/计费逻辑
- 数据不需命名空间隔离
- 适合个人/小团队量化工作流

---

## 架构总览

```
[云端 VPS / Fly.io]
├── ai-monitor 扫描引擎          ← 已有
├── Dashboard (Web UI)            ← 本阶段
├── Agent API                     ← 骨架已有 (ai-monitor.fly.dev)
│    ├── OpenClaw skill 接入      ← 本阶段
│    └── WhatsApp webhook         ← 本阶段
│
└── 数据源（全云端，无本地依赖）
     ├── IBKR REST API (OAuth)    ← Phase 4 P2，审批中
     ├── Polygon                  ← Phase 4 已实现
     └── Tradier                  ← Phase 4 已实现

[本地 / 内网]
└── IB Gateway (TWS)             ← 可选，enabled=true 时本地优先
```

---

## 模块 1: Dashboard (Web UI)

### 设计基础

现有 `src/report.py` + HTML report（`reports/YYYY-MM-DD_radar.html`）已经是 Dashboard 的雏形：
- Apple 风格 card 布局、dark dividend card、badge 系统已完善
- 信号分类已定义：IV 极值、MA200 趋势、LEAPS、Sell Put、IV 动量、财报 Gap

**Dashboard = 把静态 HTML 变成动态 live 页面 + 时间筛选**

### 核心交互

**默认视图：最近 24 小时的信号**

时间切换器（页面顶部固定）：
```
[ 24小时 ]  [ 最近一周 ]  [ 最近一个月 ]
```

切换时 HTMX 异步刷新信号列表，无整页刷新。

### 页面布局

```
┌─────────────────────────────────────┐
│  量化扫描雷达  [24h] [1w] [1m]  ●●● │  ← 顶部 header + 时间切换
├─────────────────────────────────────┤
│  [机会提醒 8]  [风控提醒 3]          │  ← tab 切换
├─────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐   │
│  │ Sell Put    │  │ LEAPS 共振  │   │  ← 机会 card（沿用现有样式）
│  │ AAPL $180   │  │ MSFT        │   │
│  │ APY 18.5%   │  │ RSI 38      │   │
│  └─────────────┘  └─────────────┘   │
│  ...                                │
├─────────────────────────────────────┤
│  ┌──────────────────────────────┐   │
│  │ ⚠️ 财报 Gap 风险              │   │  ← 风控 card（红色 badge）
│  │ NVDA 财报还有 5天             │   │
│  │ 历史平均 Gap ±8.2%            │   │
│  └──────────────────────────────┘   │
└─────────────────────────────────────┘
```

### 信号分类

**机会提醒 tab：**
| 信号类型 | 来源 | 触发条件 |
|---------|------|---------|
| Sell Put | `sell_puts` | APY > 阈值，DTE 在窗口 |
| LEAPS 共振 | `leaps` | MA200 + MA50w + RSI + IV 四项共振 |
| IV 低位 | `iv_low` | IV Rank < 20% |
| 高股息双打 | `dividend_signals` | 质量评分 + 股息率 + Sell Put |

**风控提醒 tab：**
| 信号类型 | 来源 | 触发条件 |
|---------|------|---------|
| 财报 Gap 风险 | `earnings_gaps` | 财报 < 5 天 + 历史 Gap 大 |
| IV 高位 | `iv_high` | IV Rank > 80% |
| MA200 跌破 | `ma200_bearish` | 价格跌破 MA200 |
| Sell Put 财报风险 | `sell_puts.earnings_risk` | DTE 窗口内有财报 |

### 数据存储

扫描结果需持久化到 SQLite（当前只写静态文件），支持时间范围查询：

```sql
CREATE TABLE scan_signals (
    id         INTEGER PRIMARY KEY,
    scanned_at TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,   -- 'sell_put' | 'leaps' | 'iv_low' | ...
    category   TEXT NOT NULL,    -- 'opportunity' | 'risk'
    ticker     TEXT NOT NULL,
    payload    JSON NOT NULL,    -- 信号详细数据
    scan_date  DATE NOT NULL
);
```

查询接口：
```
GET /api/signals?range=24h|7d|30d&category=opportunity|risk
```

### 技术选型

- 后端：FastAPI（扩展现有 agent API 骨架）
- 前端：HTML + HTMX（轻量，无 JS 框架，直接沿用现有 CSS）
- 存储：SQLite（`data/signals.db`，与其他 db 一致）
- 认证：单用户 Bearer token（`SCAN_API_KEY` env var，现有机制）

### 访问控制

- Dashboard 公网可访问，需 Bearer token 认证
- IB Gateway 仍只在内网/本地暴露，不通过 Dashboard 透传

---

## 模块 2: OpenClaw / Claude Agent 集成

### 用途

通过对话查询：
- 当前仓位
- 最新扫描信号（哪些标的触发）
- 某只股票的基本面 / IV 状态
- 触发手动扫描

### 接入方式

- OpenClaw skill 调用 Agent API（REST）
- Agent API 路由到扫描引擎 / 数据层
- 响应格式：纯文本 + 结构化 JSON

### 关键 API 端点（扩展现有 agent API）

```
GET  /api/signals                 # 最新扫描结果
GET  /api/positions               # 当前仓位（IBKR REST 或缓存）
GET  /api/ticker/{ticker}/status  # 单标的状态（价格/IV/基本面）
POST /api/scan/trigger            # 手动触发扫描
GET  /api/datasources/status      # 各数据源健康状态
```

---

## 模块 3: WhatsApp 集成

### 用途

- 推送扫描信号（有信号时主动推送）
- 接收查询消息，回复仓位 / 机会

### 接入方式

- WhatsApp Business API（或 Twilio WhatsApp 沙盒）
- Webhook 接收用户消息 → 路由到 OpenClaw Agent 处理 → 回复

### 配置

```yaml
notifications:
  whatsapp:
    enabled: false
    webhook_url: ""    # env: WHATSAPP_WEBHOOK_URL
    phone_number: ""   # env: WHATSAPP_PHONE_NUMBER
    api_key: ""        # env: WHATSAPP_API_KEY
```

---

## 模块 4: IBKR REST API Provider

（已在 Phase 4 req 中定义，本阶段实现）

- `IBKRRestProvider` 类加入 `src/providers/` 包
- OAuth 2.0 token 管理（refresh 自动化）
- 路由优先级：TWS → IBKR REST → Polygon/Tradier → yfinance
- Token 存 Fly.io secrets，不写入代码或配置文件

---

## 仓位数据方案

IBKR REST API 支持仓位查询：
- `GET /portfolio/{accountId}/positions` → 当前持仓
- `GET /portfolio/{accountId}/summary` → 账户摘要

无需 IB Gateway 即可获取仓位数据，纯云端可用。

---

## 部署方案

### Fly.io（现有）

```toml
# fly.toml 扩展
[env]
  POLYGON_API_KEY    = ""   # set via fly secrets
  TRADIER_API_KEY    = ""
  IBKR_CLIENT_ID     = ""
  IBKR_ACCESS_TOKEN  = ""
  IBKR_REFRESH_TOKEN = ""
  SCAN_API_KEY       = ""
  WHATSAPP_API_KEY   = ""
```

### 本地运行（开发 / 内网）

```yaml
# config.yaml
data_sources:
  ibkr_tws:
    enabled: true    # 本地开 TWS，优先走本地
```

### 云端自动化

```yaml
data_sources:
  ibkr_tws:
    enabled: false   # 云端关掉 TWS，走 REST API
  ibkr_rest:
    enabled: true
```

---

## 实现优先级

| 优先级 | 模块 | 前置条件 |
|--------|------|---------|
| P1 | IBKR REST API Provider | IBKR developer 审批通过 |
| P1 | Agent API 扩展（仓位/信号端点）| 无 |
| P2 | OpenClaw skill 接入 | Agent API 完成 |
| P2 | Dashboard 基础版 | Agent API 完成 |
| P3 | WhatsApp webhook | OpenClaw 接入验证后 |

---

## 不在本阶段范围

- 多租户（用户注册、计费、命名空间隔离）
- 实时 WebSocket 推送
- 移动端 App
- 富途 OpenD 接入
