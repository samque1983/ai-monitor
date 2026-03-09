# Phase 5: 云端部署 + Dashboard + OpenClaw 集成

**状态**: 待实现
**优先级**: 中

---

## 背景

当前系统已具备扫描引擎、多数据源路由（Phase 4）。
本阶段目标：将系统部署为单租户云服务，提供 Web Dashboard 和 OpenClaw/WhatsApp 对话接口。

**关键决策：私有部署，面向自己 + 少数朋友，非多租户 SaaS**
- 无用户注册 / 计费逻辑
- 市场信号公开可见，个人仓位 / 盈亏按账号隔离
- 适合个人 + 小圈子量化工作流

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
     ├── IBKR Flex Web Service    ← 现在就能用（仓位查询）
     ├── Polygon                  ← 已实现
     └── Tradier                  ← 已实现

[本地 / 内网，可选]
└── IB Gateway (TWS)             ← enabled=true 时本地优先
```

---

## 模块 1: Dashboard (Web UI)

### 设计基础

现有 `src/report.py` + `reports/YYYY-MM-DD_radar.html` 已是 Dashboard 雏形：
- Apple 风格 card 布局、dark dividend card、badge 系统已完善
- 信号分类已定义：IV 极值、MA200 趋势、LEAPS、Sell Put、IV 动量、财报 Gap

**Dashboard = 静态 HTML → 动态 live 页面 + 时间筛选 + 账号仓位视图**

### 访问控制分层

**公开区（无需登录）：**
- 市场机会提醒（Sell Put、LEAPS、IV 低位、高股息双打）
- 市场风控提醒（IV 高位、MA200 跌破、财报 Gap 风险）
- 时间范围筛选：24h / 1周 / 1月

**私有区（选账号 + 输 Access Code 解锁）：**
- 仓位快照（该账号持仓）
- 盈亏分析（持仓成本 vs 现价，未实现 P&L）
- 仓位风控（持仓集中度、财报日在仓风险、保证金占用）

### 页面布局

```
┌──────────────────────────────────────────────────┐
│  量化扫描雷达   [24h] [1w] [1m]                   │  ← header + 时间切换
├──────────────────────────────────────────────────┤
│  [机会提醒 8]  [市场风控 3]  [我的仓位]            │  ← tab
├──────────────────────────────────────────────────┤
│  机会 / 风控 tab（公开）：                         │
│  ┌─────────────┐  ┌─────────────┐                │
│  │ Sell Put    │  │ LEAPS 共振  │  ...            │
│  │ AAPL $180   │  │ MSFT RSI 38 │                │
│  │ APY 18.5%   │  │             │                │
│  └─────────────┘  └─────────────┘                │
├──────────────────────────────────────────────────┤
│  我的仓位 tab（私有）：                            │
│                                                  │
│  账号: [ Alice IB ▾ ]  Code: [________] [解锁]   │
│                                                  │
│  未解锁时仅显示上方输入框。                        │
│  解锁后显示：                                     │
│  ┌──────────────────────────────────────────┐    │
│  │ 仓位快照  |  盈亏分析  |  仓位风控        │    │
│  │ AAPL  100股  成本$170  现价$182  +7.1%   │    │
│  │ AAPL 180P  -1张  卖出$3.2  现价$1.8  盈利│    │
│  └──────────────────────────────────────────┘    │
└──────────────────────────────────────────────────┘
```

### 信号分类（公开区）

**机会提醒 tab：**
| 信号类型 | 来源 | 触发条件 |
|---------|------|---------|
| Sell Put | `sell_puts` | APY > 阈值，DTE 在窗口 |
| LEAPS 共振 | `leaps` | MA200 + MA50w + RSI + IV 四项共振 |
| IV 低位 | `iv_low` | IV Rank < 20% |
| 高股息双打 | `dividend_signals` | 质量评分 + 股息率 + Sell Put |

**市场风控 tab：**
| 信号类型 | 来源 | 触发条件 |
|---------|------|---------|
| 财报 Gap 风险 | `earnings_gaps` | 财报 < 5 天 + 历史 Gap 大 |
| IV 高位 | `iv_high` | IV Rank > 80% |
| MA200 跌破 | `ma200_bearish` | 价格跌破 MA200 |
| Sell Put 财报风险 | `sell_puts.earnings_risk` | DTE 窗口内有财报 |

### 仓位区（私有区）内容

| 子 tab | 内容 |
|--------|------|
| 仓位快照 | 股票 + 期权持仓列表，数量 / 成本 / 现价 / 市值 |
| 盈亏分析 | 未实现 P&L，持仓盈亏排名 |
| 仓位风控 | 集中度（单股占比）、财报日在仓提醒、Sell Put 到期预警 |

### 数据存储

**市场信号**持久化到 SQLite（`data/signals.db`）：

```sql
CREATE TABLE scan_signals (
    id          INTEGER PRIMARY KEY,
    scanned_at  TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,   -- 'sell_put' | 'leaps' | 'iv_low' | ...
    category    TEXT NOT NULL,   -- 'opportunity' | 'risk'
    ticker      TEXT NOT NULL,
    payload     JSON NOT NULL,
    scan_date   DATE NOT NULL
);
```

**仓位数据**按需从 IBKR 拉取（不持久化，或短期缓存 15 分钟）。

查询接口：
```
GET /api/signals?range=24h|7d|30d&category=opportunity|risk
GET /api/positions/{account_id}     ← 需 Access Code 验证
```

### 技术选型

- 后端：FastAPI（扩展现有 agent API 骨架）
- 前端：HTML + HTMX（无 JS 框架，直接沿用现有 CSS）
- 存储：SQLite（`data/signals.db`）
- 认证：见下方账号管理

---

## 模块 2: 账号管理

### 设计原则

- 无用户注册页面，账号由管理员（你）在 env vars 里配置
- 每个账号对应一个 IBKR IB 账户（Flex 凭证）+ 一个 Access Code
- Access Code 由你分配给朋友，朋友每次进仓位页面输入
- 朋友提供一次性 IBKR Flex 凭证（Token + Query ID），你存入服务器

### 朋友开通流程

```
朋友操作（一次性）：
  1. IBKR Account Management → Reports → Flex Queries
  2. 新建 Portfolio Query，勾选：Symbol, AssetClass, Position,
     CostBasisPrice, MarkPrice, UnrealizedPnL
  3. 得到 Query ID；API Settings 生成 Flex Token
  4. 把 Token + Query ID 发给你

你操作：
  5. 存入 Fly.io secrets（ACCOUNT_XXX_FLEX_TOKEN 等）
  6. 告知朋友他的 Access Code

朋友日常使用：
  7. 打开 Dashboard → 我的仓位 tab
  8. 选账号 → 输入 Access Code → 查看仓位 / 盈亏
```

### 账号配置（env vars）

```bash
# 账号 Alice
ACCOUNT_ALICE_NAME=Alice IB
ACCOUNT_ALICE_CODE=alice_radar       # 你分配的登录密码
ACCOUNT_ALICE_FLEX_TOKEN=xxxxx       # Alice 从 IB 拿来的
ACCOUNT_ALICE_FLEX_QUERY_ID=12345    # Alice 从 IB 拿来的

# 账号 Bob
ACCOUNT_BOB_NAME=Bob IB
ACCOUNT_BOB_CODE=bob_radar
ACCOUNT_BOB_FLEX_TOKEN=yyyyy
ACCOUNT_BOB_FLEX_QUERY_ID=67890
```

加新账号 = 加几行 env vars，无需改代码或数据库。

### Access Code 验证逻辑

```
POST /api/auth/account
  body: { account_id: "alice", code: "alice_radar" }
  → 验证通过：返回短效 session token（存 cookie，有效期 8 小时）
  → 验证失败：返回 401

后续仓位请求带 cookie，服务端校验 session → 取对应 Flex 凭证 → 查仓位
```

---

## 模块 3: 仓位数据方案

仓位查询路由（优先级）：

```
IBKR Web API（审批后）→ IBKR Flex Web Service（现在就能用）
```

### 主路：IBKR Web API

认证用 RSA 私钥签名（详见 `req/phase_4_data_sources.md`）。
审批通过前不可用，Flex 作为过渡方案。

### Fallback / 过渡：IBKR Flex Web Service

无需注册审批，Account Management 生成 token 即可：

```
Step 1 — 发起请求：
  GET https://gdcdyn.interactivebrokers.com/Universal/servlet/
      FlexStatementService.SendRequest?t={token}&q={queryId}&v=3
  → 返回 reference code

Step 2 — 取结果（等 1-5 秒）：
  GET https://gdcdyn.interactivebrokers.com/Universal/servlet/
      FlexStatementService.GetStatement?t={token}&q={referenceCode}&v=3
  → 返回 XML，包含仓位数据
```

**字段对比：**

| 字段 | Web API | Flex |
|------|---------|------|
| 持仓数量 | ✅ | ✅ |
| 平均成本 | ✅ | ✅ |
| 当前市价 | ✅ 15分钟延迟 | ✅ 收盘价 |
| 未实现 P&L | ✅ | ✅ |
| 合约类型（OPT/STK）| 需额外调用 | ✅ 直接返回 |
| 实时行情 | 需订阅 | ❌ |

**config.yaml：**
```yaml
positions:
  ibkr_web_api:
    enabled: false     # 审批通过后开
  ibkr_flex:
    enabled: true      # 现在就能用，per-account 凭证从 env vars 读取
```

---

## 模块 4: OpenClaw / Claude Agent 集成

### 用途

通过对话查询：
- 当前仓位（指定账号）
- 最新扫描信号
- 某只股票的基本面 / IV 状态
- 触发手动扫描

### 关键 API 端点

```
GET  /api/signals?range=24h|7d|30d   # 市场信号
GET  /api/positions/{account_id}      # 仓位（需认证）
GET  /api/ticker/{ticker}/status      # 单标的状态
POST /api/scan/trigger                # 手动触发扫描
GET  /api/datasources/status          # 数据源健康状态
```

---

## 模块 5: WhatsApp 集成

- 推送扫描信号（有信号时主动推送）
- 接收查询 → OpenClaw Agent 处理 → 回复

```yaml
notifications:
  whatsapp:
    enabled: false
    webhook_url: ""    # env: WHATSAPP_WEBHOOK_URL
    phone_number: ""   # env: WHATSAPP_PHONE_NUMBER
    api_key: ""        # env: WHATSAPP_API_KEY
```

---

## 部署配置

### Fly.io secrets

```bash
# 数据源
POLYGON_API_KEY=
TRADIER_API_KEY=
IBKR_PRIVATE_KEY=          # Web API（审批后）
IBKR_CLIENT_ID=

# 账号（每个账号一组）
ACCOUNT_ALICE_NAME=Alice IB
ACCOUNT_ALICE_CODE=
ACCOUNT_ALICE_FLEX_TOKEN=
ACCOUNT_ALICE_FLEX_QUERY_ID=

# 通知
WHATSAPP_API_KEY=
SCAN_API_KEY=              # Agent API 认证
```

### 本地运行（开发 / 内网 TWS）

```yaml
data_sources:
  ibkr_tws:
    enabled: true
```

### 云端（无 TWS）

```yaml
data_sources:
  ibkr_tws:
    enabled: false
  ibkr_rest:
    enabled: true      # 审批后
```

---

## 实现优先级

| P | 模块 | 前置条件 |
|---|------|---------|
| 1 | signals.db + 扫描结果持久化 | 无 |
| 1 | Flex Web Service 仓位查询 | 生成 token（朋友操作） |
| 1 | Agent API 扩展（信号 + 仓位端点） | 无 |
| 2 | Dashboard 公开区（信号 + 时间筛选） | signals.db 完成 |
| 2 | Dashboard 私有区（账号 + 仓位） | Flex 完成 |
| 2 | OpenClaw skill 接入 | Agent API 完成 |
| 3 | IBKR REST API Provider | 等审批 |
| 3 | WhatsApp webhook | OpenClaw 验证后 |

---

## 不在本阶段范围

- 用户自助注册 / 计费
- 实时 WebSocket 推送
- 移动端 App
- 富途 OpenD 接入
