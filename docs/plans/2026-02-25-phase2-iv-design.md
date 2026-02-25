# Phase 2: IV Anomaly Radar + Earnings Gap Profiler — Design

## Overview

在 Phase 1 基础上新增 3 个功能模块：
1. **IV Momentum 监控** — 5 日 IV 变化率检测
2. **财报 Gap 分析** — 历史财报跳空统计
3. **合成警报** — 合并 Gap + IV 数据的高信噪比预警

所有输出只包含客观数据，不带主观交易建议。

---

## 模块一：IV Momentum (5-Day IV Change)

### 数据层 — `iv_store.py`
- 新增 `get_iv_n_days_ago(ticker, n)` 方法
- 查询 SQLite，取距今 n 个自然日前最近一条记录的 IV 值
- 数据不足时返回 `None`

### 数据模型 — `data_engine.py`
- `TickerData` 新增字段：`iv_momentum: Optional[float]`
- 计算：`(current_iv - iv_5d_ago) / iv_5d_ago * 100`
- 在 `build_ticker_data()` 中通过 IVStore 查询计算

### 扫描器 — `scanners.py`
- `scan_iv_momentum(tickers, threshold=30.0)` → List[TickerData]
- 筛选 `iv_momentum > threshold` 的标的

### 配置 — `config.yaml`
```yaml
scanners:
  iv_momentum_threshold: 30  # 5日IV涨幅触发阈值(%)
```

---

## 模块二：Earnings Gap Profiler

### 数据层 — `market_data.py`
- 新增 `get_historical_earnings_dates(ticker, count=8)` 方法
- 使用 `yfinance` 的 `Ticker.earnings_dates` 获取历史财报日期
- 失败时返回空列表（后续可扩展本地 CSV fallback）

### 计算引擎 — `data_engine.py`
- 新增 `EarningsGap` dataclass：
  ```python
  @dataclass
  class EarningsGap:
      ticker: str
      avg_gap: float       # mean(|gap|)
      up_ratio: float      # P(gap > 0)
      max_gap: float       # max(gap) by absolute value, preserve sign
      sample_count: int    # number of earnings events analyzed
  ```
- 新增 `compute_earnings_gaps(ticker, earnings_dates, price_df)` 函数
- Gap 公式：`(earnings_date Open - prev_trading_day Close) / prev_trading_day Close`
- 处理：跳过无法匹配 K 线的日期，最少需要 2 个样本

### 扫描器 — `scanners.py`
- `scan_earnings_gap(tickers, provider, days_threshold=3)` → List[EarningsGap]
- 触发条件：`days_to_earnings <= days_threshold`
- 对符合条件的标的执行 Gap 历史分析

### 配置 — `config.yaml`
```yaml
scanners:
  earnings_gap_days: 3      # 距财报N天内触发Gap分析
  earnings_lookback: 8      # 历史财报回溯次数
```

---

## 模块三：合成警报输出

### 扫描器 — `scanners.py`
- `scan_earnings_alert(tickers, gaps, iv_data)` → 合并 EarningsGap + TickerData
- 不单独新建模块，在 report 层组装输出

### 报告 — `report.py` + `html_report.py`
- 新增 Section 6: "波动率异动雷达" — IV Momentum 触发的标的
- 新增 Section 7: "财报 Gap 预警" — 含 Gap 统计 + 当前 IV Rank
- 输出格式示例（纯数据）：
  ```
  ⚠️ AAPL 财报还有 2 天
     历史平均 Gap ±4.2%  |  上涨概率 62%  |  历史最大跳空 -8.1%
     当前 IV Rank: 85.3%
  ```

---

## 文件改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `src/iv_store.py` | 修改 | 新增 `get_iv_n_days_ago()` |
| `src/data_engine.py` | 修改 | `TickerData` 加 `iv_momentum`; 新增 `EarningsGap`, `compute_earnings_gaps()` |
| `src/market_data.py` | 修改 | 新增 `get_historical_earnings_dates()` |
| `src/scanners.py` | 修改 | 新增 `scan_iv_momentum()`, `scan_earnings_gap()` |
| `src/report.py` | 修改 | 新增 2 个 section |
| `src/html_report.py` | 修改 | 新增 2 个 section |
| `src/main.py` | 修改 | 集成新扫描器 |
| `config.yaml` | 修改 | 新增扫描器配置项 |
| `tests/test_iv_store.py` | 修改 | 测试 `get_iv_n_days_ago()` |
| `tests/test_data_engine.py` | 修改 | 测试 `EarningsGap`, `compute_earnings_gaps()` |
| `tests/test_scanners.py` | 修改 | 测试新扫描器 |
| `tests/test_market_data.py` | 修改 | 测试 `get_historical_earnings_dates()` |
| `tests/test_report.py` | 修改 | 测试新 section |
| `tests/test_integration.py` | 修改 | 集成测试 |

---

## 架构约束
- 导入方向不变：`main → scanners/report → data_engine → market_data → data_loader`
- CN/HK 标的跳过 IV Momentum 和 Gap 分析（无期权数据）
- 单 ticker 失败不影响整体运行
