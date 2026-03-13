# Design: 极值底价过滤与事件标注

**Date**: 2026-03-14
**Status**: Approved
**Scope**: `src/dividend_scanners.py`, `src/html_report.py`

---

## 背景

当前 `floor_price` 基于 5 年内绝对最低价（`close_5y.min()`），不过滤 flash crash 等单日异常。
目标：改为「可持续熊市底部」定义，同时标注被剔除的异常事件。

---

## 数据处理层（`dividend_scanners.py`）

### Step 1：时间持续性过滤（滚动窗口）

```python
rolling_min_5y = close_5y.rolling(window=5, min_periods=5).min()
```

5 日滚动最小值平滑单日 flash crash。

### Step 2：百分位数取底

```python
min_5y_price_filtered = float(rolling_min_5y.dropna().quantile(0.03))
```

取第 3rd percentile，排除统计尾部极端值。

`max_yield_5y` 和 `floor_price` 改用 `min_5y_price_filtered` 计算：

```python
max_yield_5y = round((annual_dividend_ttm / min_5y_price_filtered) * 100, 2)
floor_price   = round(forward_dividend_rate / (max_yield_5y / 100), 2)
```

### Step 3：检测被剔除的异常极端点

```python
raw_min_price = float(close_5y.min())
raw_min_date  = close_5y.idxmin()  # Timestamp

# 触发阈值：原始最低比过滤后低 15% 以上
extreme_detected = raw_min_price < min_5y_price_filtered * 0.85
```

若 `extreme_detected`，进入事件标注；否则 `extreme_event_label = None`。

计算持续天数：统计 `close_5y` 在 `raw_min_price * 1.10` 以下的连续天数（以 raw_min_date 为中心的窗口）。

### Step 4：事件标注

**规则库**（按优先级匹配，取最早命中）：

| 事件名 | 时间窗口 | 市场 |
|--------|---------|------|
| COVID 抛售 | 2020-02-19 ~ 2020-03-23 | 全市场 |
| 2022 加息熊市 | 2022-01-01 ~ 2022-10-13 | 全市场 |
| 2018 Q4 崩盘 | 2018-10-01 ~ 2018-12-24 | 全市场 |
| 2020 港股暴跌 | 2020-02-19 ~ 2020-03-19 | HK |
| 2015 A股熔断 | 2015-06-12 ~ 2016-02-29 | CN |

若规则库未命中，自动对比大盘同期涨跌：
- 获取 `raw_min_date` 前后 10 个交易日的 SPY/HSI/CSI300 涨跌幅
- 大盘同期跌幅 > 10%：标注 `"系统性风险"`
- 否则：标注 `"个股事件"`

### 新增返回字段（`scan_dividend_pool_weekly` 存入 pool record）

```python
floor_price_raw: Optional[float]        # 基于原始 raw min 的底价（透明度用）
extreme_event_label: Optional[str]      # "2020-03 COVID 抛售" / "系统性风险" / "个股事件" / None
extreme_event_price: Optional[float]    # raw_min_price（被剔除的价格）
extreme_event_days: Optional[int]       # 该低位持续天数
```

`floor_price` 字段语义变更：**现在代表基于过滤后数据的极值底价**（非 raw min）。

---

## 数据结构变化（`DividendBuySignal`）

```python
@dataclass
class DividendBuySignal:
    # 已有字段（语义更新）
    floor_price: Optional[float]           # 过滤后极值底价（原：raw min 底价）

    # 新增字段
    floor_price_raw: Optional[float]       # 未过滤极值底价（透明度）
    extreme_event_label: Optional[str]     # 事件标注
    extreme_event_price: Optional[float]   # 被剔除的异常最低价
    extreme_event_days: Optional[int]      # 该低位持续天数
```

---

## UI 层（`html_report.py`）

### 当前渲染

```
极值底价: $43.11 (较当前 -31.0%)
```

### 新渲染

```
极值底价: $43.11 (较当前 -31.0%)
  ↳ 已剔除更低点 $31.20 (2020-03 COVID 抛售，持续 18 天)
```

- 若 `extreme_event_label is None`（无被剔除异常点）：不显示第二行
- 若过滤前后底价相同（差异 < 15%）：不显示第二行

---

## 测试要求

| 测试场景 | 预期 |
|---------|------|
| 含单日 flash crash 的价格序列 | `floor_price` 高于 raw min 底价 |
| 5 天持续低位（不是 flash crash）| `floor_price` 等于 raw min 底价（未被过滤） |
| raw_min_date 落在 COVID 窗口内 | `extreme_event_label = "2020-03 COVID 抛售"` |
| raw_min_date 无规则库命中，大盘同期跌 > 10% | `extreme_event_label = "系统性风险"` |
| raw_min 与 filtered_min 差 < 15% | `extreme_event_label = None`，UI 不显示第二行 |
| `extreme_event_label is None` | UI 只显示一行极值底价 |

---

## 不在本次范围内

- 修改 `DividendStore` 数据库 schema（新字段先存 pool record JSON，不加新 DB 列）
- 修改 dashboard.html（仅改 `html_report.py` 的 `_dividend_card()`）
- 修改 agent payload（后续版本考虑）
