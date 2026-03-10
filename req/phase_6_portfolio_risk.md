# Phase 6: 仓位风险报告

**状态**: 草稿（待评审）
**优先级**: 中（依赖 Phase 5 Flex Query 仓位读取）

---

## 背景

当前系统已能扫描市场机会与风险（Phase 1-4），但所有分析基于**候选标的池**（universe.csv），
不感知用户**实际持仓**。

本阶段目标：通过 IBKR Flex Query 读取真实仓位（含 IBKR 服务端计算的希腊值和保证金数据），
生成一份**面向持仓的风险报告**，以通俗语言识别风险，并为每个风险提供操作选项和 AI 建议。

**设计原则：**
- 不自行计算希腊值，直接使用 IBKR Flex 返回的服务端计算结果
- 每个风险维度触发预警时，展示 2–4 个操作选项 + LLM 生成的 AI 建议
- AI 建议格式：陈述当前处境 → 列出选项 → 给出推荐理由（不做主观买卖判断，只呈现逻辑）

---

## 多账号架构

每个账号独立配置，通过环境变量注入，无需改代码：

```bash
ACCOUNT_ALICE_NAME=我的 IB 账户
ACCOUNT_ALICE_CODE=alice_secret
ACCOUNT_ALICE_FLEX_TOKEN=xxxxx
ACCOUNT_ALICE_FLEX_QUERY_ID=12345

ACCOUNT_BOB_NAME=Bob IB
ACCOUNT_BOB_CODE=bob_secret
ACCOUNT_BOB_FLEX_TOKEN=yyyyy
ACCOUNT_BOB_FLEX_QUERY_ID=67890
```

加新账号 = 加几行 env vars，无需改代码或数据库。

### 运行方式

```bash
python -m src.main --risk-report --account alice    # 单账号
python -m src.main --risk-report --all-accounts     # 全部账号（Actions 用）
python -m src.main --risk-history --account alice --days 7
```

### GitHub Actions 定时调度

```yaml
# .github/workflows/risk-report.yml
name: Daily Risk Report
on:
  schedule:
    - cron: "0 22 * * 1-5"   # 周一到周五 22:00 UTC（美东 6pm，收盘后）
  workflow_dispatch:
jobs:
  run:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements.txt
      - run: python -m src.main --risk-report --all-accounts
    env:
      ACCOUNT_ALICE_FLEX_TOKEN: ${{ secrets.ACCOUNT_ALICE_FLEX_TOKEN }}
      ACCOUNT_ALICE_FLEX_QUERY_ID: ${{ secrets.ACCOUNT_ALICE_FLEX_QUERY_ID }}
```

---

## 数据来源：IBKR Flex Query

### 两份 Query（每个账号各配置一次）

**Query 1 — 仓位 + 希腊值（Positions 报表）**

| Flex 字段 | 含义 | 用于维度 |
|-----------|------|---------|
| `symbol` | 标的代码 | 全部 |
| `assetCategory` | STK / OPT | 区分股票/期权 |
| `description` | 期权合约描述 | 显示 |
| `putCall` | P / C | 期权方向 |
| `strike` | 行权价 | 安全垫、到期风险 |
| `expiry` | 到期日 | DTE |
| `multiplier` | 合约乘数 | 敞口计算 |
| `position` | 持仓数量（负=空头） | 全部 |
| `costBasisPrice` | 平均成本价 | P&L、安全垫 |
| `markPrice` | 当前市场价 | P&L、Moneyness |
| `unrealizedPnL` | 未实现盈亏 | 显示 |
| `delta` | IBKR 计算的 Delta | 方向性敞口 |
| `gamma` | IBKR 计算的 Gamma | 临近到期风险 |
| `theta` | IBKR 计算的 Theta | 时间价值衰减 |
| `vega` | IBKR 计算的 Vega | IV 敏感度 |

**Query 2 — 账号保证金摘要（Account Summary 报表）**

| Flex 字段 | 含义 | 用于维度 |
|-----------|------|---------|
| `netLiquidation` | 净资产 | 基准、集中度 |
| `grossPositionValue` | 持仓总市值 | 杠杆 |
| `initMarginReq` | 初始保证金要求 | 安全边际 |
| `maintMarginReq` | 维持保证金要求 | 爆仓预警 |
| `excessLiquidity` | 超额流动性 | 安全边际 |
| `availableFunds` | 可用资金 | 新开仓空间 |
| `cushion` | 保证金缓冲比例（0–1） | 安全边际 % |

---

## 操作建议格式规范

每个风险维度触发预警时，HTML 报告中展示以下结构：

```
┌─ 🔴 [风险维度名称] ──────────────────────────────┐
│                                                   │
│  [风险现状描述，1-2 句通俗中文]                     │
│                                                   │
│  操作选项：                                        │
│  A. [选项 A]                                      │
│  B. [选项 B]                                      │
│  C. [选项 C]                                      │
│                                                   │
│  💡 AI 建议：[LLM 生成，50-100 字，陈述逻辑，      │
│              不做主观判断，末尾标注推荐选项]          │
└──────────────────────────────────────────────────┘
```

**AI 建议生成规则：**
- 输入：仓位数据 + 风险指标 + 市场数据（当前 IV Rank、MA200 状态等）
- 输出：50–100 字中文，结构为「当前处境 → 各选项权衡 → 推荐哪个以及理由」
- 禁止：主观买卖建议（"应该"/"必须"），只陈述条件和逻辑
- 实现：复用现有 LLM 调用（Phase 2 LLM 防御性评分的模式）

---

## 风险维度全览

| # | 维度 | 数据来源 | 阶段 | 状态 |
|---|------|---------|------|------|
| 1 | 方向性敞口（Dollar Delta） | Flex delta | P1 | 📋 待实现 |
| 2 | 时间价值衰减（Theta 汇总） | Flex theta | P1 | 📋 待实现 |
| 3 | IV 敏感度（Vega 汇总） | Flex vega | P1 | 📋 待实现 |
| 4 | 保证金安全边际（cushion） | Flex Account Summary | P1 | 📋 待实现 |
| 5 | 集中度风险（单股占比） | Flex markPrice | P1 | 📋 待实现 |
| 6 | 财报日在仓风险 | Flex + `get_earnings_date()` | P1 | 📋 待实现 |
| 7 | 期权到期风险（DTE + Moneyness） | Flex expiry/strike | P1 | 📋 待实现 |
| 8 | Sell Put 安全垫 + 年化收益 | Flex cost/strike | P1 | 📋 待实现 |
| 9 | Gamma 临近到期放大警告 | Flex gamma | P1 | 📋 待实现 |
| 10 | 压力测试（大盘 -10%/-20%） | Flex delta + yfinance beta | P1 | 📋 待实现 |
| 11 | 持仓标的 IV Rank | `get_iv_rank()` 复用 | P2 | 📋 待实现 |
| 12 | 持仓标的 MA200 趋势 | `get_price_data()` 复用 | P2 | 📋 待实现 |
| 13 | 财报历史跳空幅度 | EarningsGapProfiler 复用 | P2 | 📋 待实现 |
| 14 | 行业集中度 | `get_fundamentals()` sector | P2 | 📋 待实现 |
| 15 | Beta 加权市场敞口 | yfinance `info['beta']` | P2 | 📋 待实现 |
| 16 | 股息除息日风险（Sell Call） | `get_dividend_history()` | P3 | 📋 待实现 |
| 17 | 期权流动性（Bid-Ask 价差） | Tradier 实时数据 | P3 | 📋 待实现 |

---

## P1 维度详解

---

### 1. 方向性敞口（Dollar Delta）

**触发条件**：组合 Dollar Delta / 净资产 > 80%

**指标计算**：
```
单仓位 Dollar Delta = delta × multiplier × abs(position) × markPrice
组合合计 Dollar Delta = Σ 所有仓位
```

**通俗展示**：
```
组合 Dollar Delta: +$87,600（净资产 73%）
含义：若持仓标的整体跌 1%，组合约损失 $876
```

**预警阈值**：> 80% 黄；> 120% 红

**操作选项与 AI 建议（触发黄/红时显示）：**

```
🟡 方向性敞口偏高
当前 Delta 敞口占净资产 95%，方向性风险集中。

操作选项：
A. 卖出部分股票仓位，降低整体 Delta 至 80% 以内
B. 买入 Put（指数或个股）作为对冲，Delta 不变但有保险
C. 卖出 Covered Call，降低净 Delta 同时收取权利金
D. 维持现状，接受当前敞口（若看多市场）

💡 AI 建议：当前 Delta 95% 处于黄色区间，在 IV Rank 低位时买 Put 保险成本
较低（选项 B）；若不愿承担对冲成本且近期无系统性风险，维持现状（选项 D）
也有合理性。若账户有大量现金可考虑选项 A 搭配新 Sell Put 降低成本。
推荐：B 或 D，视对未来走势的判断。
```

---

### 2. 时间价值衰减（Theta）

**触发条件**：组合净 Theta 为负（整体是期权买方净敞口）

**指标计算**：
```
组合净 Theta = Σ (theta × multiplier × abs(position) × position_sign)
```

**通俗展示**：
```
每日净 Theta: -$45/天（负值 = 时间在消耗你的仓位价值）
```

**操作选项与 AI 建议（净 Theta 为负时显示）：**

```
🟡 时间价值净消耗
当前组合净 Theta 为 -$45/天，持有期权买方仓位在消耗时间价值。

操作选项：
A. 平仓部分期权买方仓位，止住时间损耗
B. 等待目标催化剂（财报/事件）兑现后再平仓
C. 将买方仓位转为价差（Spread），降低 Theta 成本
D. 维持现状（若认为标的即将出现大幅波动）

💡 AI 建议：负 Theta 本身不是风险，关键看是否有近期催化剂支撑。AAPL 财报
在 12 天后，若当前期权为财报方向性押注（选项 B），时间损耗可接受。若无
明确催化剂，转价差（选项 C）可将每日损耗从 $45 降至约 $12。
推荐：先确认是否有催化剂，有则 B，无则 C。
```

---

### 3. IV 敏感度（Vega）

**触发条件**：组合净 Vega 为负（空 Vega）且 VIX 或持仓 IV Rank 快速上升

**通俗展示**：
```
组合净 Vega: -$56/1%IV（空 Vega）
含义：若市场 IV 整体上升 5%，组合约亏损 $280
```

**操作选项与 AI 建议（净 Vega 为负 + IV Rank > 60% 时显示）：**

```
🟡 IV 上升压力
组合净 Vega -$56，当前 NVDA IV Rank 已升至 72%，空 Vega 仓位承压。

操作选项：
A. 买回部分空头期权平仓，降低 Vega 敞口
B. 买入 VIX Call 或 SPY Put 作为 Vega 对冲
C. 等待 IV 回落后再决定（若认为恐慌情绪短暂）
D. 无操作（若 Theta 收益能抵消 Vega 亏损）

💡 AI 建议：IV Rank 72% 属历史高位，继续持有空 Vega 的风险在于 IV 进一步
急升（如再涨 10%，亏损 $560）。若距到期 < 21 天，Theta 收益加速，选项 D
的胜率提高；若距到期 > 30 天，建议选项 A 或 C 降低敞口。
推荐：DTE > 30 天选 A；DTE < 21 天可选 D 并设止损。
```

---

### 4. 保证金安全边际

**触发条件**：cushion < 25%

**通俗展示**：
```
保证金安全边际: 18.5%  🟡
维持保证金要求: $12,300
超额流动性:    $22,200

含义：若组合整体下跌约 18.5%，将触发追加保证金（Margin Call）。
```

**操作选项与 AI 建议：**

```
🟡 保证金缓冲偏低（cushion 18.5%）
距追加保证金线仅剩 18.5% 的下跌空间，低于建议安全线 25%。

操作选项：
A. 平仓保证金占用最大的仓位（通常是裸 Sell Put），立即释放保证金
B. 存入现金至账户，直接提升 cushion
C. 将裸 Sell Put 转为 Put Spread（限制最大亏损，大幅降低保证金要求）
D. 维持现状，等待期权到期自然释放保证金

💡 AI 建议：cushion 18.5% 处于黄色区间，市场单日跳空 -3% 即可将缓冲压缩至
危险区。选项 C（转 Put Spread）是风险最小的结构调整，保证金占用可降低 60–
70% 且不需要平仓实现亏损。若有闲置资金，选项 B 最直接。选项 D 适合距到期
< 7 天且仓位安全垫充足的情况。
推荐：C（若有足够 Put 可买）或 B（若有闲置现金）。
```

---

### 5. 集中度风险

**触发条件**：单只股票市值 / 净资产 > 20%

**通俗展示**：
```
AAPL 占组合 38.5%（净资产 $120,000 中的 $46,200）
建议上限：35%
```

**操作选项与 AI 建议：**

```
🟡 单股集中度偏高（AAPL 38.5%）
AAPL 仓位超过组合净资产 35% 的建议上限，单一事件冲击影响较大。

操作选项：
A. 分批减持 AAPL 至目标比例（如 25–30%）
B. 买入 AAPL Put 做局部对冲，持仓不变但加保险
C. 暂不减仓，但设定止损线（如跌破 MA200 时触发减仓）
D. 维持现状（若高仓位为有意策略）

💡 AI 建议：集中度超标本身不是止损信号，关键看近期风险事件。AAPL 财报在
46 天后，短期无明显催化剂。若不愿减持，选项 C（设 MA200 止损）是保留上涨
空间同时管理下行风险的折中方案。若已有 AAPL Sell Put，选项 B 的对冲成本
较高，可优先考虑选项 C。
推荐：C（设止损），或 A（若对集中风险有顾虑）。
```

---

### 6. 财报日在仓风险

**触发条件**：持仓标的财报 ≤ 14 天，或期权到期日在财报日之后（财报穿越）

**通俗展示**：
```
⚠️ NVDA 财报穿越风险
  财报日: 2026-04-23（13 天后）
  持有: NVDA 110P -1 张，到期 2026-05-16（财报后 23 天）
  历史财报平均跳空: ±8.3%，最大单次 -15.2%
  当前安全垫: 2.1%（历史平均跳空可轻易击穿）
```

**操作选项与 AI 建议：**

```
🔴 财报穿越风险（NVDA 110P 到期在财报后）
NVDA 财报在 13 天后，持有的 Sell Put 将"穿越"财报，历史平均跳空 ±8.3%
远超当前 2.1% 安全垫。

操作选项：
A. 财报前平仓，锁定当前已实现收益（避免财报跳空风险）
B. Roll 到财报前到期（如换成 2026-04-18 到期），财报前自然了结
C. Roll 降低行权价（如换成 NVDA 100P），扩大安全垫至 9% 以上
D. 维持现状，接受财报风险（若看好 NVDA 不会大跌）

💡 AI 建议：安全垫 2.1% 远低于历史财报平均跳空 8.3%，继续持有意味着接受
较大的被指派风险。若当前 Put 已实现约 50% 收益，选项 A（平仓锁利）是稳健
选择；若认为 NVDA 下行有限，选项 C（降行权价 Roll）可在不平仓的前提下将
安全垫扩大至历史跳空均值以上。
推荐：A（已盈利 > 50%）或 C（仍想持有敞口）。
```

---

### 7. 期权到期风险（DTE + Moneyness）

**触发条件**：DTE ≤ 14 天，或 Moneyness > 0（Put 已跌入行权价）

**通俗展示**：
```
🔴 NVDA 110P  到期 8 天  已跌入行权价 -2.3%
   当前 NVDA 价格: $107.5   行权价: $110
   最大名义亏损: $11,000（若被指派）
```

**操作选项与 AI 建议：**

```
🔴 期权已实值 + 临近到期（NVDA 110P，DTE 8 天，ITM 2.3%）
NVDA 已跌破行权价，期权处于实值状态，8 天内存在被指派风险。

操作选项：
A. 立即平仓，接受亏损止损（当前亏损 $XXX，避免进一步扩大）
B. 接受指派，以 $110 承接 100 股 NVDA（成本约 $10,750 含权利金）
C. Roll 延期（换至下月更低行权价），延长时间换取反弹机会
D. 等待到期日前反弹，若 NVDA 涨回 $110 以上可自然了结

💡 AI 建议：已实值且 DTE 仅 8 天，选项 D 风险最高（依赖 NVDA 在 8 天内
涨 2.3%）。若不愿持有 NVDA 股票，选项 A 最干净；若看好 NVDA 长期且有资金
承接，选项 B（接受指派）实际上相当于以 $107.3 的有效成本买入 NVDA，接近当
前价格。选项 C 需支付 Roll 成本，仅在认为 NVDA 中期会反弹时合理。
推荐：有意持股选 B；不愿持股选 A。
```

---

### 8. Sell Put 安全垫 + 年化收益

**触发条件**：安全垫 < 5%，或已实现收益 > 75%（可考虑提前平仓锁利）

**通俗展示**：
```
AAPL 180P  -2 张
  收取权利金: $3.20/股（共 $640）
  保本价:    $176.80   当前价: $182
  安全垫:    2.9%  ⚠️
  建仓年化:  18.5%
  已实现:    78%（可考虑锁利）
```

**操作选项与 AI 建议（安全垫 < 5% 或已实现 > 75% 时显示）：**

```
🟡 安全垫偏低 / 收益已充分实现（AAPL 180P）
安全垫仅 2.9%，且已实现 78% 的预期收益，继续持有的性价比下降。

操作选项：
A. 平仓锁利（买回 Put），实现 78% 收益，释放保证金
B. 继续持有至到期，争取全部权利金（剩余 17 天）
C. Roll 至更高行权价（如 AAPL 185P），扩大安全垫同时增加权利金
D. 维持现状并设止损（若标的跌至行权价即平仓）

💡 AI 建议：已实现 78% 收益、仅剩 22% 收益空间，但安全垫仅 2.9% 意味着
剩余风险/收益比不对称。经典 Sell Put 管理原则：收益超过 50% 后，平仓风险
回报更佳（选项 A）。若 AAPL IV Rank 当前 < 20%（低位），Roll 至更高行权价
（选项 C）可在安全区间获取更多权利金。
推荐：A（锁利），或 C（若 IV 仍有合理权利金）。
```

---

### 9. Gamma 临近到期放大警告

**触发条件**：DTE ≤ 14 且 `abs(gamma) > 0.05`

**通俗展示**：
```
⚠️ NVDA 110P  DTE 8 天  Gamma 0.08（高）
含义：NVDA 每波动 $1，Delta 额外变化 $8，P&L 曲线急剧弯曲
```

**操作选项与 AI 建议：**

```
🟡 高 Gamma 风险（NVDA 110P，DTE 8 天）
临近到期的高 Gamma 意味着标的价格小幅波动会引起仓位 P&L 剧烈变化，
风险不再线性，难以用简单止损管理。

操作选项：
A. 减半仓位（买回 1 张），降低 Gamma 敞口同时保留部分收益
B. 平仓全部，彻底退出高 Gamma 风险区
C. 买入更低行权价的 Put（如 105P）构成 Put Spread，限制最大亏损
D. 维持并密切监控（适合标的远离行权价、安全垫 > 5% 的情况）

💡 AI 建议：Gamma 0.08 在 DTE 8 天时属于较高风险状态，叠加当前标的已接近
行权价（安全垫 2.3%），风险呈非线性放大。选项 C（构建 Put Spread）是最优
结构化方案，将最大亏损从 $11,000 压缩至约 $500，但需要支付买 Put 的成本。
若不愿调整结构，选项 A（减半）是平衡风险和收益的折中。
推荐：C（有足够买 Put 流动性时）或 A。
```

---

### 10. 压力测试（大盘 -10% / -20%）

**触发条件**：大盘跌 10% 情景下，预估亏损 > 净资产 10%

**通俗展示**：
```
📉 压力测试结果

  大盘跌 10%：预估亏损 -$14,300（-11.9%）  🟡
  大盘跌 20%：预估亏损 -$31,200（-26.0%）  🔴
  极端情景（所有 Sell Put 被指派）：最大名义亏损 -$47,000

  注：基于 Beta 加权 + Delta 线性估算，未含 Gamma 加速效应。
  实际亏损可能更大（Gamma 放大）或更小（IV 下降抵消）。
```

**操作选项与 AI 建议（大盘跌 10% 时亏损 > 净资产 10% 时显示）：**

```
🟡 组合下行风险偏高
大盘跌 10% 时预估亏损 11.9%，超过净资产 10% 的参考阈值。
主要来源：AAPL（Beta 1.2，占组合 38.5%）+ NVDA Sell Put Delta 敞口。

操作选项：
A. 买入 SPY Put（大盘对冲），为整体组合加保险
B. 降低高 Beta 个股（NVDA）仓位，降低组合 Beta
C. 将部分裸 Sell Put 转 Put Spread，限制极端情景下的最大亏损
D. 维持现状（若认为近期大盘下跌概率低）

💡 AI 建议：压力测试属于情景估算，不代表必然发生。当前 VIX < 20 时购买 SPY
Put 保险成本相对合理（选项 A）；若不愿付对冲成本，选项 C（转 Put Spread）
可将极端情景最大亏损从 $47,000 压缩至有限范围，且不影响日常 Theta 收益。
推荐：C（结构调整，低成本降风险）或 D（若风险偏好允许）。
```

---

## P2 维度详解

---

### 11. 持仓标的 IV Rank

**触发条件**：持有 Sell Put/Call 的标的 IV Rank > 70%

**通俗展示**：
```
NVDA IV Rank: 78%  🟡
含义：当前 IV 处于过去 52 周的高位，市场处于恐慌状态
对 Sell Put 的影响：空 Vega 仓位面临 IV 继续上升的亏损压力
```

**操作选项与 AI 建议：**

```
🟡 持仓标的 IV 处于高位（NVDA IV Rank 78%）
NVDA IV Rank 78%，市场恐慌情绪浓厚，持有空 Vega 仓位承压。

操作选项：
A. 减少 NVDA 期权空头仓位（买回部分），降低 Vega 敞口
B. 等待 IV 回落（恐慌消退后期权价格下降，空头仓位盈利）
C. 此时是新开 Sell Put 的好时机（IV 高 = 权利金丰厚），可考虑加仓
D. 维持现状，关注 IV 变化

💡 AI 建议：IV Rank 78% 对已持有空 Vega 仓位是压力，但也意味着权利金收入
丰厚。若持仓安全垫 > 8%，等待 IV 回落（选项 B）历史上通常有利于卖方；若
安全垫已 < 5%，IV 高位叠加低安全垫风险较高，应优先考虑平仓（选项 A）。
推荐：安全垫 > 8% 选 B；安全垫 < 5% 选 A。
```

---

### 12. 持仓标的 MA200 趋势

**触发条件**：持仓标的当前价格 < MA200（趋势转弱）

**通俗展示**：
```
NVDA 当前价 $107.5，低于 MA200 $113.2（-5.0%）  🟡
含义：NVDA 处于长期下跌趋势，Sell Put 被指派后持有亏损股的风险上升
```

**操作选项与 AI 建议：**

```
🟡 持仓标的跌破 MA200（NVDA）
NVDA 跌破长期均线，趋势偏空，持有 Sell Put 的指派风险上升。

操作选项：
A. 平仓 NVDA 所有 Sell Put，趋势转弱期间避免卖方风险
B. 降低行权价（Roll Down），扩大与当前价格的距离
C. 维持但缩短到期日（Roll 至更近到期），减少趋势持续影响
D. 维持现状（若认为 NVDA 跌破 MA200 是短暂波动）

💡 AI 建议：MA200 跌破是中期趋势转弱的信号，持有 Sell Put 意味着在下跌趋
势中做空波动率，风险不对称。若 Put 安全垫 < MA200 跌幅（5%），建议选项 B
（Roll Down）；若到期日在 30 天内且安全垫充足，选项 C（缩短到期）可降低
趋势风险窗口。
推荐：B（行权价远离价格）或 A（若趋势明显走弱）。
```

---

### 13. 财报历史跳空幅度

**触发条件**：持有期权的标的，历史平均财报跳空 > 当前安全垫

**通俗展示**：
```
NVDA 历史财报跳空：平均 ±8.3%，最大单次 -15.2%
当前 NVDA Sell Put 安全垫：2.1%
⚠️ 安全垫远低于历史平均跳空幅度
```

**操作选项与 AI 建议：**（同维度 6 财报风险，两者联动展示）

---

### 14. 行业集中度

**触发条件**：单一行业占比 > 50%

**通俗展示**：
```
科技板块: AAPL + NVDA + MSFT = 64%  🟡
金融板块: XLF = 18%
其他: 18%

含义：科技板块系统性下跌时，64% 仓位高度相关，分散效果有限。
```

**操作选项与 AI 建议：**

```
🟡 行业集中度偏高（科技 64%）
超过一半仓位集中在科技板块，行业轮动或科技监管风险会同步冲击多个仓位。

操作选项：
A. 将部分科技仓位轮换至其他行业（如能源、消费、金融）
B. 买入 QQQ Put 作为科技板块整体对冲
C. 新增非科技标的的 Sell Put，自然稀释科技占比
D. 维持现状（若判断科技板块近期仍强势）

💡 AI 建议：行业集中度高在牛市中加速收益，在行业逆风时集中放大损失。选项
C（新增其他行业 Sell Put）是低摩擦的渐进式改善方案，不需要卖出现有仓位。
选项 B（QQQ Put）提供即时对冲但有成本。若无明确看空科技的理由，选项 D 也
可接受，但建议设定再平衡触发线（如超过 70% 时强制操作）。
推荐：C（渐进稀释）或 D（配合触发线）。
```

---

### 15. Beta 加权市场敞口

**触发条件**：组合加权 Beta > 1.5（高于市场平均波动）

**通俗展示**：
```
组合加权 Beta: 1.38
含义：若 S&P 500 跌 10%，组合预计跌 13.8%（高于市场均值）
主要贡献：NVDA（Beta 1.8，占组合 22%）
```

**操作选项与 AI 建议：**（与压力测试维度 10 联动展示，避免重复）

---

## P3 维度详解

---

### 16. 股息除息日风险（Sell Call 专属）

**触发条件**：持有 Sell Call，且标的除息日在期权到期日之前，且 Call 处于实值

**通俗展示**：
```
⚠️ XYZ Sell Call 除息日风险
  除息日: 2026-04-08（18 天后）
  期权到期: 2026-04-18，行权价 $50，当前价 $53（实值）
  股息: $0.85/股
  风险：持有人可能在除息日前提前行权，导致强制指派
```

**操作选项与 AI 建议：**

```
🟡 Sell Call 除息日提前行权风险（XYZ）
Call 已实值且除息日在到期前，买方有动机在除息日前行权以获取股息。

操作选项：
A. 在除息日前平仓 Sell Call，规避强制指派
B. 维持，若被指派则交割股票（若本就持有股票为 Covered Call）
C. Roll 至除息日后的到期日，绕过除息窗口

💡 AI 建议：若为 Covered Call（持有底层股票），被提前行权不影响资金安全，
选项 B 可接受。若为裸 Sell Call，除息日前被指派需以市价买入股票交割，风险
较大，建议选项 A 或 C。
推荐：Covered Call 选 B；裸 Call 选 A。
```

---

### 17. 期权流动性（Bid-Ask 价差）

**触发条件**：期权 Bid-Ask 价差 > 15%（平仓摩擦成本高）

**通俗展示**：
```
XYZ 15P  Bid: $0.35  Ask: $0.65  价差: 46%  🔴
含义：若现在平仓，中间价 $0.50，实际成交约 $0.40，滑点约 20%
```

**操作选项与 AI 建议：**

```
🔴 期权流动性差（XYZ 15P，价差 46%）
Bid-Ask 价差过宽，平仓成本极高，大部分剩余收益会被滑点吃掉。

操作选项：
A. 挂 Limit 单（挂在中间价或偏买方价），耐心等待成交
B. 持有至到期（避免支付平仓滑点，直接自然了结）
C. 分批少量成交，避免一次性扫盘加剧滑点

💡 AI 建议：价差 46% 意味着以 Market Order 平仓会损失大量收益，应避免市价
单。若 DTE > 14 天，挂 Limit 单（选项 A）通常能在 1–2 天内成交；若 DTE < 7
天，持有至到期（选项 B）往往是最优解，避免无谓的流动性成本。
推荐：DTE > 7 天选 A；DTE ≤ 7 天选 B。
```

---

## 数据存储

### `data/risk_reports.db`（SQLite）

```sql
CREATE TABLE risk_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      TEXT NOT NULL,
    report_date     DATE NOT NULL,
    generated_at    TIMESTAMP NOT NULL,
    report_html     TEXT NOT NULL,
    summary_json    JSON NOT NULL,
    net_liquidation REAL,
    total_pnl       REAL,
    cushion         REAL
);
CREATE INDEX idx_risk_reports_account_date ON risk_reports(account_id, report_date);
```

**summary_json 随阶段扩充：**

```json
{
  "net_liquidation": 120000,
  "total_unrealized_pnl": 3200,
  "cushion": 0.342,
  "portfolio_dollar_delta": 87600,
  "portfolio_theta_daily": 13,
  "portfolio_vega": -56,
  "stress_test": {
    "drop_10pct": -14300,
    "drop_20pct": -31200,
    "max_assignment_loss": -47000
  },
  "alerts": [
    {"dimension": 7, "level": "red", "ticker": "NVDA", "detail": "ITM 2.3%, DTE 8"},
    {"dimension": 6, "level": "red", "ticker": "NVDA", "detail": "earnings in 13d, put expires after"},
    {"dimension": 8, "level": "yellow", "ticker": "AAPL", "detail": "cushion 2.9%, realized 78%"}
  ]
}
```

### 查询接口（Phase 5 Agent API 扩展，P2）

```
GET /api/risk-reports/{account_id}                  # 最新报告 HTML
GET /api/risk-reports/{account_id}?date=2026-03-10  # 指定日期
GET /api/risk-reports/{account_id}/summary          # 最新 summary_json
GET /api/risk-reports/{account_id}/history?days=30  # 历史 cushion / P&L 趋势
```

---

## 模块设计

### 新增文件

```
src/
  flex_client.py       ← IBKR Flex Web Service 两步请求 + XML 解析
  portfolio_risk.py    ← 仓位数据模型 + 所有风险维度计算 + 通俗解释 + 操作选项文案
  portfolio_report.py  ← HTML 报告生成（dark Apple 风格）
  risk_store.py        ← risk_reports.db 读写

tests/
  test_flex_client.py
  test_portfolio_risk.py
  test_risk_store.py
```

### AI 建议生成（LLM 调用）

复用 Phase 2 LLM 防御性评分的调用模式：

```python
def generate_risk_suggestions(
    dimension_id: int,
    position: PositionRecord,
    risk_metrics: dict,
    market_context: dict,   # IV Rank, MA200, 财报日等
    llm_config: dict,
) -> str:
    """
    输入：风险维度编号 + 仓位数据 + 风险指标 + 市场上下文
    输出：50–100 字中文建议文本
    """
```

每个维度有对应的 prompt 模板，填入实际数据后发送 LLM。
若 LLM 不可用，回退到硬编码的规则文本（按触发条件匹配预设文案）。

---

## 实现路线图

### P1：基础仓位风险报告

| 功能 | 状态 |
|------|------|
| `FlexClient`：两份 Query XML 解析 | 📋 待实现 |
| 多账号配置加载（env vars 扫描） | 📋 待实现 |
| 维度 1–10（Flex + yfinance beta） | 📋 待实现 |
| 操作选项文案（规则硬编码版） | 📋 待实现 |
| AI 建议生成（LLM 调用，降级为规则文案） | 📋 待实现 |
| HTML 报告生成 | 📋 待实现 |
| `risk_store.py`：SQLite 存储 | 📋 待实现 |
| CLI：`--risk-report` / `--all-accounts` | 📋 待实现 |
| GitHub Actions workflow | 📋 待实现 |

### P2：持仓标的市场信号

| 功能 | 状态 |
|------|------|
| 维度 11–15（IV Rank / MA200 / 跳空 / 行业 / Beta） | 📋 待实现 |
| Agent API 端点（查询历史报告） | 📋 待实现（依赖 Phase 5） |
| ClawHub 对话接入 | 📋 待实现（依赖 Agent API） |

### P3：扩展维度

| 功能 | 状态 |
|------|------|
| 维度 16：股息除息日风险（Sell Call） | 📋 待实现 |
| 维度 17：期权流动性（Tradier Bid-Ask） | 📋 待实现 |

---

## 不在本阶段范围

- VaR / CVaR 统计模型（需历史相关性矩阵）
- 自行计算希腊值（直接用 IBKR 服务端数据）
- 实时保证金监控（Flex 是收盘快照，非实时）
- 多账号汇总合并视图（各账号独立报告）
- 自动减仓/平仓执行（只建议，不操作）
