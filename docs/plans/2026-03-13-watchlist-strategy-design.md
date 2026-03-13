# 自选池改造 + 策略详情页 — 设计文档

**日期**: 2026-03-13
**分支**: feature/watchlist-strategy

---

## 背景

自选池页面（`/watchlist`）目前只展示 ticker 列表，添加/删除是 TODO。需要：

1. 实现自选 ticker 的网页添加/删除
2. 自选 ticker 显示策略覆盖标签（如 `[高股息]`）
3. 新增策略发现区，入口指向各策略详情页
4. 新建 `/strategy/dividend` 策略详情页，展示说明文档 + 股票池 + 关键指标

---

## 核心架构决策

### 两种池子的本质区分

| | 自选池 | 策略池 |
|--|--------|--------|
| 来源 | 用户手动维护 | 扫描器按条件自动生成 |
| 控制权 | 用户操作 | 系统只读 |
| 作用 | 驱动扫描输入 | 扫描输出结果 |
| 存储 | `users.watchlist_json` | `signals` 表最新记录 |

两者完全独立，但在自选池页面并排呈现。自选 ticker 可以通过交叉查询显示策略标签（单向关联，不混同数据）。

---

## 页面设计

### 1. 自选池页面 `/watchlist`

**Section 1 — 我的自选**

- 顶部 inline 输入框：输入 ticker（大写）→ 回车或点击"添加"
- 前端 POST `/api/watchlist/add`，后端更新 `watchlist_json`
- 每行 ticker：
  - ticker 名称（DM Mono）
  - 策略 tag（若该 ticker 出现在最新扫描的策略池中，显示对应 tag）
  - 移除按钮
- 策略 tag 渲染逻辑：后端渲染时，从最新扫描结果中提取各 `signal_type` 的 ticker 集合，与自选列表交叉，打 tag

**Section 2 — 策略发现**

- 每个策略一张卡片：策略名 + 一句话描述 + 当前池子数量 + "查看详情 →" 链接
- 卡片数组由后端构造，数据驱动（扩展时只需注册新策略元数据）
- 当前策略：高股息价值股

---

### 2. 策略详情页 `/strategy/dividend`

**Section 1 — 策略说明**（静态文案）
- 策略逻辑：选股条件（股息率阈值、PE 范围、市场分类等）
- 适用场景、风险提示

**Section 2 — 当前股票池**（动态，读最新扫描结果）
- 数据来源：`signals` 表中最新 `scan_date` 且 `signal_type='dividend'` 的记录
- 每行展示：ticker + 股息率 + PE + 当前价格（从 `payload` JSON 中读取）
- 移动端：卡片堆叠；桌面：紧凑表格

**路由扩展**：`/strategy/<slug>` 结构，后续加策略新增路由 + 模板即可

---

## 后端改动清单

### `agent/db.py`
新增方法：
```python
def get_strategy_pool(self, signal_type: str) -> List[Dict]:
    """从最新 scan_date 中返回指定 signal_type 的所有信号记录。"""

def add_to_watchlist(self, user_id: str, ticker: str) -> List[str]:
    """追加 ticker 到自选池（去重），返回更新后列表。"""

def remove_from_watchlist(self, user_id: str, ticker: str) -> List[str]:
    """从自选池移除 ticker，返回更新后列表。"""
```

### `agent/dashboard.py`
- `watchlist_page()`：增加策略 tag 交叉逻辑，构造 `strategy_cards` 列表传模板
- 新增 `GET /strategy/dividend` 路由：读策略池数据，渲染详情模板
- 新增 `POST /api/watchlist/add` 路由
- 新增 `POST /api/watchlist/remove` 路由

### 模板文件
| 文件 | 操作 |
|------|------|
| `agent/templates/watchlist.html` | 重写：输入框 + 策略 tag + 策略发现 section |
| `agent/templates/strategy_dividend.html` | 新建：策略说明 + 股票池表格，移动端适配 |

---

## API 设计

### POST `/api/watchlist/add`
```json
Request:  { "ticker": "AAPL" }
Response: { "tickers": ["AAPL", "MSFT"] }
```

### POST `/api/watchlist/remove`
```json
Request:  { "ticker": "AAPL" }
Response: { "tickers": ["MSFT"] }
```

---

## 策略元数据结构（扩展用）

```python
STRATEGY_REGISTRY = [
    {
        "slug": "dividend",
        "name": "高股息价值股",
        "description": "筛选股息率高、估值合理的价值型标的",
        "signal_type": "dividend",
        "url": "/strategy/dividend",
    },
    # 未来扩展：leaps, iv_momentum, ma200 等
]
```

后端渲染自选池页面时，遍历 registry，为每个策略查询最新池子数量，构造卡片数据。

---

## UI 规范

遵循 `docs/specs/html_design_system.md`：
- 深色主题，CSS 变量颜色
- Google Fonts：Instrument Serif italic / DM Sans / DM Mono
- 策略 tag 样式：参考现有 `nav-badge amber`
- 移动端优先：卡片堆叠，桌面用表格
- fadeUp 动画，8px grid

---

## 测试要求（TDD）

新增 `tests/test_watchlist_api.py`：
- `test_add_to_watchlist` — 添加新 ticker，验证去重
- `test_remove_from_watchlist` — 移除存在/不存在的 ticker
- `test_get_strategy_pool` — 读最新 scan_date 的指定类型信号
- `test_strategy_tags_cross_reference` — 自选 ticker 与策略池交叉逻辑

`tests/test_db.py` 补充：
- `test_add_to_watchlist_dedup`
- `test_remove_from_watchlist_missing`
