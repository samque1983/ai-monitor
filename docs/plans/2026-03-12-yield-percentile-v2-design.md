# Yield Percentile v2 Design

> **Status:** Approved, ready for implementation
> **Date:** 2026-03-12

## 背景

当前 `历史分位` 用全量历史数据计算，疫情等黑天鹅期间的异常高值会拉高极值，导致正常高位股息率看起来分位偏低，参考价值减弱。

---

## 设计目标

1. **抗扭曲**：去除极端黑天鹅影响，反映"正常市场"下的高低位
2. **双重信息**：既给出百分位，又展示正常区间（P10–P90）
3. **向后兼容**：老信号无新字段时优雅降级
4. **高信息密度**：单行展示，不增加卡片高度

---

## Backend 设计

### `DividendStore.get_yield_percentile`

返回从单个 `float` 升级为 `YieldPercentileResult` dataclass：

```python
@dataclass
class YieldPercentileResult:
    percentile: float      # 当前值在剔除顶部5%后的分位（0–100）
    p10: float | None      # 历史正常区间下限（5年）
    p90: float | None      # 历史正常区间上限（5年）
    hist_max: float | None # 原始历史最大值（用于tooltip）
```

**计算逻辑：**
- 取5年滑动窗口（约1250个交易日快照）
- 剔除顶部5%极值后计算 `percentile`（Winsorized）
- `p10`/`p90` 从原始5年数据直接取（不剔除）
- `hist_max` 为原始5年最大值

**数据要求：**
- 至少30个历史点才计算 p10/p90，否则返回 `None`

### Signal Payload 新增字段

```python
signal = {
    # ...现有字段...
    "yield_percentile": result.percentile,   # 保持原字段名
    "yield_p10": result.p10,                 # 新增
    "yield_p90": result.p90,                 # 新增
    "yield_hist_max": result.hist_max,       # 新增
}
```

---

## Frontend 设计

### 新格式（有 p10/p90）

```
入场时机   ▰▰▰▰▰▰▰▰░░  82%  (正常区间 3.5–5.8%)  ℹ
```

- 进度条10格，按百分位填充（`▰` / `░`）
- 百分位 ≥70% 显示绿色（好的入场点），<30% 显示橙色
- 括号内显示 P10–P90 构成的正常区间（单位 %）
- `ℹ` 图标 hover 显示 tooltip：`历史最高 {hist_max}%（含黑天鹅期，已剔除极值计算分位）`

### 降级格式（无 p10/p90 — 老信号）

```
历史分位   82%
```

保持原样，不显示进度条和区间。

### 颜色语义

| 分位区间 | 颜色 | 含义 |
|----------|------|------|
| ≥70% | `var(--green)` | 股息率高，好的入场点 |
| 30%–70% | `var(--text)` | 中性 |
| <30% | `var(--orange)` | 股息率低，入场需谨慎 |

---

## 文件变更

| 文件 | 变更 |
|------|------|
| `src/dividend_store.py` | 新增 `YieldPercentileResult` dataclass；`get_yield_percentile` 返回新类型 |
| `src/dividend_scanners.py` | signal payload 写入 `yield_p10`, `yield_p90`, `yield_hist_max` |
| `agent/static/dashboard.html` | `buildDividendCard` 中新增进度条行，带降级逻辑 |
| `tests/test_dividend_store.py` | 新增 `get_yield_percentile` 的 Winsorized 逻辑测试 |
| `tests/test_dividend_scanners.py` | 新增 signal payload 包含新字段的测试 |

---

## 不变更

- `dividend_history` 表结构（无需迁移）
- 现有信号不重新计算（只有新生成的信号才有新字段）
- `yield_percentile` 字段名保持不变（向后兼容）
