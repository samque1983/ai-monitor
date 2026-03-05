# Dividend Pool V2 Design

Date: 2026-03-05

## Overview

将高股息防御双打从"个人自选池扫描"升级为"全市场精选养老股池"。
核心目标：长期持有吃股息，覆盖美股/港股/A股，月度版本管理，带解释页面。

---

## 1. Universe 定义（静态种子池）

种子池硬编码在 `config.yaml` 的 `dividend_universe` 字段中，共约 70 支标的。

### 美股个股（~37 支）

**Dividend Kings（连续提息 40 年以上）**
- KO, PG, JNJ, CL, KMB, FRT, EMR, ITW

**Dividend Aristocrats（连续提息 25 年以上）**
- O, NEE, SO, DUK, WEC, ATO, HD, LOW, ABT, GD, LMT

**高质量高收益**
- ABBV, VZ, ENB, TRP, MO, JPM, BLK, MSFT

### 美股 ETF（5 支）
- SCHD, VYM, HDV, DGRO, VIG

### 港股个股（15 支）
- 0002.HK (CLP Holdings), 0006.HK (HK Electric), 0003.HK (HK Gas)
- 0823.HK (Link REIT), 0778.HK (Fortune REIT)
- 0005.HK (HSBC), 0011.HK (Hang Seng Bank), 2388.HK (BOC HK), 0939.HK (CCB), 1398.HK (ICBC)
- 0941.HK (China Mobile), 0762.HK (China Unicom)
- 0267.HK (CNOOC), 0016.HK (Sun Hung Kai), 0001.HK (CK Hutchison)

### A股个股（~10 支）
- 601398.SS (工商银行), 601939.SS (建设银行), 601988.SS (中国银行), 601288.SS (农业银行)
- 600900.SS (长江电力), 600025.SS (华能水电)
- 600941.SS (中国移动), 0267.HK mirror via 601728.SS (中国电信)
- 601088.SS (中国神华), 600028.SS (中国石化)

### A股 ETF（3 支）
- 510880.SS (红利ETF), 515080.SS (中证红利ETF), 512890.SS (红利低波ETF)

### 排除名单（永久硬排除，无论何时不进池）
- T (AT&T) — 2022年割息50%
- MMM (3M) — 2024年割息，PFAS诉讼
- KMI — 2015年割息75%

---

## 2. 固定筛选规则

以下规则固定在代码中，不通过 config 控制：

| 规则 | 阈值 | 数据来源 |
|------|------|---------|
| 连续派息年限 | ≥ 5 年 | `calculate_consecutive_years()` |
| 派息率（行业感知） | ≤ 100% | Energy/Utilities/Real Estate 用 FCF，其余用 GAAP |
| 股息质量综合评分 | ≥ 70 | `FinancialServiceAnalyzer.analyze_dividend_quality()` |
| 当前股息率 | ≥ 2.0% | `fundamentals['dividend_yield']` |
| 5年股息增长率 | ≥ 0% | `calculate_dividend_growth_rate()` |

**行业感知派息率逻辑（sector-aware payout ratio）：**
- FCF 行业：Energy、Utilities、Real Estate
- FCF 派息率（主）= `shares_outstanding × dividend_rate / free_cash_flow × 100`
- FCF 派息率（fallback）= `abs(dividends_paid) / free_cash_flow × 100`（当 `shares_outstanding` 或 `dividend_rate` 缺失时）
- 其余行业：使用 GAAP `payout_ratio`

---

## 3. 版本管理

### 更新频率
月度更新（手动触发 or 月度 cron），不需要每周。

### 版本号格式
`monthly_YYYY-MM`，例如 `monthly_2026-03`

### 存储
`DividendStore` 现有 `save_pool(pool, version)` 已支持。
新增方法：
- `list_versions() -> List[Dict]` — 返回所有版本号 + 筛选时间 + 入池数量
- `get_pool_by_version(version) -> List[TickerData]` — 按版本查询

### 月度筛选脚本
`scripts/run_dividend_screening.py`（已存在）改为版本格式 `monthly_YYYY-MM`。

---

## 4. 池子查看功能

### 命令行查看工具
`scripts/view_dividend_pool.py`

```
用法：
  python scripts/view_dividend_pool.py              # 查看当前版本
  python scripts/view_dividend_pool.py --list       # 列出所有版本
  python scripts/view_dividend_pool.py --version monthly_2026-02  # 查看历史版本
```

输出格式：
```
版本: monthly_2026-03 | 筛选时间: 2026-03-05 14:23 | 入池: 32 支

TICKER    市场  评分  连续年  股息率  派息类型  派息率
KO        US   85   61     3.0%   GAAP    65%
ENB       US   78   28     7.2%   FCF     64%
0002.HK   HK   82   80     4.0%   GAAP    72%
...
```

### dividend_pool.html 独立页面
每次月度筛选后生成，保存至 `reports/dividend_pool.html`（固定路径，每次覆盖）。

内容：
1. 选股逻辑说明（SCHD 方法论 + 派息率分类说明）
2. 当前池子完整表格（含所有评分字段 + 派息类型 + 派息率数值）
3. 版本历史列表（版本号 + 筛选时间 + 入池数量，可点击切换）
4. 最后更新时间

### 主报告 HTML 集成
`高股息防御双打` 标题旁添加 `ⓘ` 徽章，链接至 `dividend_pool.html`：
```html
<h2>高股息防御双打 <a href="dividend_pool.html" class="info-badge">ⓘ</a></h2>
```

---

## 5. 模块变更清单

| 模块 | 变更 |
|------|------|
| `config.yaml` | 新增 `dividend_universe` 字段（美/港/A股种子池列表） |
| `src/market_data.py` | `get_fundamentals()` 新增 `shares_outstanding`、`dividend_rate`、`dividends_paid` 字段 |
| `src/financial_service.py` | 新增 sector-aware payout ratio 逻辑；`_calculate_rule_based_score()` 接收 `effective_payout_ratio` |
| `src/dividend_scanners.py` | `scan_dividend_pool_weekly()` 改为接收 `dividend_universe`，内置 sector-aware payout ratio 计算 |
| `src/dividend_store.py` | 新增 `list_versions()`、`get_pool_by_version()` 方法 |
| `src/html_report.py` | `高股息防御双打` 标题添加 `ⓘ` 徽章 + 链接 |
| `scripts/run_dividend_screening.py` | 版本号改为 `monthly_YYYY-MM` 格式；生成 `dividend_pool.html` |
| `scripts/view_dividend_pool.py` | 新建，命令行版本查看工具 |
| `reports/dividend_pool.html` | 新建，月度筛选后生成的独立解释页面 |

---

## 6. 测试覆盖

| 测试文件 | 新增测试 |
|---------|---------|
| `tests/test_financial_service.py` | sector-aware payout ratio：FCF行业/非FCF行业/fallback逻辑 |
| `tests/test_dividend_scanners.py` | dividend_universe 替换 csv_url；新筛选规则 |
| `tests/test_dividend_store.py` | `list_versions()`、`get_pool_by_version()` |
| `tests/test_market_data.py` | `get_fundamentals()` 新字段 |
| `tests/test_html_report.py` | ⓘ 徽章渲染 |

---

## 7. 不在本次范围内

- A股实时行情（yfinance 对 A 股覆盖有限，数据缺失时 skip，不报错）
- 股息历史回测 / 总回报计算
- 用户自定义筛选阈值（规则固定，不配置化）
- Web UI（仍为生成式静态 HTML）
