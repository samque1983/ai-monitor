# Dashboard MVP 设计文档

**日期**: 2026-03-09
**范围**: Phase 5 MVP — 公开信号页（无仓位、无认证）
**需求参考**: `req/phase_5_cloud_deployment.md`

---

## 目标

将现有静态 HTML report 升级为动态 live 页面，支持时间范围筛选（24h / 1w / 1m），公开展示市场机会提醒和风控提醒。

---

## 架构决策

- **部署方式**: 扩展现有 `agent/main.py`，不新建独立服务
- **前端方案**: JSON API + vanilla JS（方案 C），而非内联 HTML 生成
  - 理由：API 端点 OpenClaw 也需要，仓位图表未来需要 JS，扩展性更好
- **URL**: `/dashboard`（根路径保留给 health check）

---

## 组件总览

```
agent/
  main.py              ← 现有，include dashboard router
  dashboard.py         ← 新建，路由 + HTML 服务
  db.py                ← 扩展，加 signals 表 + 方法
  static/
    dashboard.html     ← 新建，单文件 HTML + CSS + vanilla JS

数据流：
  scanner
    → POST /api/scan_results
    → db.py 解析 → 写 signals 表（每条信号一行）
    → GET /api/signals?range=24h
    → JSON → vanilla JS 渲染 cards
```

---

## 数据层

### signals 表

```sql
CREATE TABLE signals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_date   DATE NOT NULL,
    scanned_at  TIMESTAMP NOT NULL,
    signal_type TEXT NOT NULL,
    category    TEXT NOT NULL,
    ticker      TEXT NOT NULL,
    payload     TEXT NOT NULL   -- JSON blob
);
CREATE INDEX idx_signals_scanned_at ON signals(scanned_at);
```

### signal_type / category 映射

| signal_type | category |
|-------------|----------|
| `sell_put` | `opportunity` |
| `leaps` | `opportunity` |
| `iv_low` | `opportunity` |
| `dividend` | `opportunity` |
| `iv_high` | `risk` |
| `ma200_bearish` | `risk` |
| `earnings_gap` | `risk` |
| `sell_put_earnings_risk` | `risk` |

### 写入策略

- 触发时机：`POST /api/scan_results` 收到数据时
- 幂等：同一 `scan_date` 先删后写，重跑不重复
- 现有 `scan_results` 表保留不变（向后兼容）

### DB 新增方法

```python
def save_signals(scan_date: str, signals: list[dict]) -> int
    # 先删同 scan_date 旧数据，再批量 insert，返回写入数量

def get_signals(range: str, category: str = None) -> list[dict]
    # range: "24h" | "7d" | "30d"
    # 按 scanned_at 过滤，可选按 category 过滤
    # 返回 list of dicts（含 payload 已解析为 dict）
```

---

## API 层

### 新增文件：`agent/dashboard.py`

```
GET /dashboard
  → FileResponse: agent/static/dashboard.html
  → 无需认证

GET /api/signals
  → 参数: range=24h|7d|30d（默认 24h）
           category=opportunity|risk|all（默认 all）
  → 响应:
    {
      "range": "24h",
      "count": 8,
      "opportunity_count": 5,
      "risk_count": 3,
      "signals": [
        {
          "id": 1,
          "signal_type": "sell_put",
          "category": "opportunity",
          "ticker": "AAPL",
          "scanned_at": "2026-03-09T17:00:00",
          "payload": { "strike": 180, "dte": 52, "bid": 3.2, "apy": 18.5 }
        }
      ]
    }
```

### 扩展现有端点

`POST /api/scan_results`：现有逻辑不变，额外调用 `db.save_signals()` 解析写入 signals 表。

### 挂载方式

```python
# agent/main.py
from agent.dashboard import router as dashboard_router
app.include_router(dashboard_router)
```

---

## 前端

### 文件：`agent/static/dashboard.html`

单文件，结构：

```
<style>   ← 直接复制 html_report.py CSS，零改动
<body>
  <header>   标题 + 时间切换 [24h] [1w] [1m]
  <nav>      tab: [机会提醒 N] [市场风控 N]
  <main>     card grid，JS 动态渲染
<script>  ← ~60 行 vanilla JS
```

### JS 逻辑

```javascript
let range = '24h'
let category = 'all'

async function load() {
  const res = await fetch(`/api/signals?range=${range}&category=${category}`)
  const data = await res.json()
  renderCards(data.signals)
  updateTabCounts(data.opportunity_count, data.risk_count)
}

function renderCards(signals) { /* 按 signal_type 分发到对应 card 模板 */ }
function cardSellPut(s) { ... }
function cardLeaps(s) { ... }
function cardIvLow(s) { ... }
function cardRisk(s) { ... }

// 事件绑定：时间切换、tab 切换 → load()
document.addEventListener('DOMContentLoaded', load)
```

### Card 样式复用

| 信号类型 | CSS 类 | 来源 |
|---------|--------|------|
| 机会（sell_put / leaps / iv_low）| `.card` | 现有 html_report.py |
| 高股息 | `.dividend-card` | 现有 html_report.py |
| 风控 | `.card` + `.risk-badge` | 现有 html_report.py |

---

## 文件变更清单

| 文件 | 变更类型 | 内容 |
|------|---------|------|
| `agent/db.py` | 扩展 | 加 signals 表 schema + `save_signals()` + `get_signals()` |
| `agent/dashboard.py` | 新建 | `GET /dashboard` + `GET /api/signals` |
| `agent/static/dashboard.html` | 新建 | 单文件前端 |
| `agent/main.py` | 扩展 | include dashboard router + serve static files |
| `agent/main.py` | 扩展 | `POST /api/scan_results` 额外调用 `save_signals()` |
| `tests/agent/test_dashboard.py` | 新建 | API 端点 + DB 方法测试 |

---

## 不在本次范围

- 账号登录 / 仓位查询（Phase 5 下一步）
- OpenClaw skill 接入
- WhatsApp 推送
- 图表（盈亏趋势）
