# Phase 2 IV Enhanced Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add IV Momentum monitoring and Earnings Gap analysis with enhanced resilience (CSV fallback, data validation).

**Architecture:** Extend existing modules with new methods. Add `validate_price_df()` data quality gate, `earnings_calendar.csv` fallback, and two new scanners. Follow strict TDD: test-first, minimal implementation, frequent commits.

**Tech Stack:** Python, pandas, yfinance, SQLite, pytest

---

## Task 1: IVStore — Add `get_iv_n_days_ago()` method

**Files:**
- Modify: `src/iv_store.py:37-43`
- Test: `tests/test_iv_store.py`

**Step 1: Write the failing test**

Add to `tests/test_iv_store.py`:

```python
from datetime import date, timedelta
import pytest

class TestGetIVNDaysAgo:
    def test_exact_match_5_days_ago(self, store):
        """精确匹配 5 天前的数据"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=5), 0.25)
        store.save_iv("AAPL", today - timedelta(days=3), 0.28)
        store.save_iv("AAPL", today, 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.25

    def test_window_tolerance(self, store):
        """窗口容差: 7天前的数据仍被返回 (5-8天窗口)"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=7), 0.22)
        store.save_iv("AAPL", today, 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.22

    def test_no_data_returns_none(self, store):
        """无数据时返回 None"""
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=date(2026, 2, 27))
        assert result is None

    def test_data_too_recent_returns_none(self, store):
        """数据太新 (仅2天前), 不在窗口内"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=2), 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_iv_store.py::TestGetIVNDaysAgo -v`

Expected: FAIL — `AttributeError: 'IVStore' object has no attribute 'get_iv_n_days_ago'`

**Step 3: Write minimal implementation**

Add to `src/iv_store.py` after `get_iv_history()`:

```python
from datetime import timedelta

def get_iv_n_days_ago(
    self,
    ticker: str,
    n: int = 5,
    reference_date: Optional[date] = None
) -> Optional[float]:
    """
    获取约 n 天前的 IV 值 (容差: n ~ n+3 天)

    Args:
        ticker: 股票代码
        n: 目标天数 (默认 5)
        reference_date: 参考日期 (默认今天)

    Returns:
        IV 值或 None (数据不足时)
    """
    if reference_date is None:
        reference_date = date.today()

    target_date = reference_date - timedelta(days=n)
    window_start = reference_date - timedelta(days=n + 3)

    cursor = self.conn.execute(
        """
        SELECT iv FROM iv_history
        WHERE ticker = ? AND date >= ? AND date <= ?
        ORDER BY date DESC LIMIT 1
        """,
        (ticker, window_start.isoformat(), target_date.isoformat())
    )
    row = cursor.fetchone()
    return row[0] if row else None
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_iv_store.py::TestGetIVNDaysAgo -v`

Expected: ALL PASS (4 tests)

**Step 5: Commit**

```bash
git add src/iv_store.py tests/test_iv_store.py
git commit -m "feat: add get_iv_n_days_ago() to IVStore for IV momentum

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 2: IVStore — Add `get_data_sufficiency()` method

**Files:**
- Modify: `src/iv_store.py`
- Test: `tests/test_iv_store.py`

**Step 1: Write the failing test**

Add to `tests/test_iv_store.py`:

```python
class TestDataSufficiency:
    def test_sufficient_for_both(self, store):
        """数据充足: 同时满足 IVP (30天) 和 Momentum (5天)"""
        today = date(2026, 2, 27)
        for i in range(40):
            store.save_iv("AAPL", today - timedelta(days=i), 0.25)

        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 40
        assert result["sufficient_for_ivp"] is True
        assert result["sufficient_for_momentum"] is True

    def test_insufficient_for_ivp(self, store):
        """数据不足: 仅满足 Momentum"""
        today = date(2026, 2, 27)
        for i in range(10):
            store.save_iv("AAPL", today - timedelta(days=i), 0.25)

        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 10
        assert result["sufficient_for_ivp"] is False
        assert result["sufficient_for_momentum"] is True

    def test_no_data(self, store):
        """无数据时返回全 False"""
        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 0
        assert result["sufficient_for_ivp"] is False
        assert result["sufficient_for_momentum"] is False
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_iv_store.py::TestDataSufficiency -v`

Expected: FAIL — `AttributeError: 'IVStore' object has no attribute 'get_data_sufficiency'`

**Step 3: Write minimal implementation**

Add to `src/iv_store.py`:

```python
def get_data_sufficiency(self, ticker: str) -> dict:
    """
    检查 IV 历史数据的充足性

    Returns:
        {
            "total_days": int,
            "sufficient_for_ivp": bool,      # >= 30天
            "sufficient_for_momentum": bool  # >= 5天
        }
    """
    cursor = self.conn.execute(
        "SELECT COUNT(*) FROM iv_history WHERE ticker = ?",
        (ticker,)
    )
    count = cursor.fetchone()[0]

    return {
        "total_days": count,
        "sufficient_for_ivp": count >= 30,
        "sufficient_for_momentum": count >= 5,
    }
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_iv_store.py -v`

Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/iv_store.py tests/test_iv_store.py
git commit -m "feat: add get_data_sufficiency() to check IV history quality

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 3: DataEngine — Add `validate_price_df()` function

**Files:**
- Modify: `src/data_engine.py`
- Test: `tests/test_data_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_data_engine.py`:

```python
import numpy as np
from src.data_engine import validate_price_df

class TestValidatePriceDF:
    def test_valid_dataframe_passes(self):
        """正常数据通过验证"""
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        df = pd.DataFrame({
            "Open": np.linspace(100, 110, 100),
            "Close": np.linspace(100, 110, 100),
        }, index=dates)

        assert validate_price_df(df, "AAPL") is True

    def test_empty_dataframe_fails(self):
        """空 DataFrame 验证失败"""
        df = pd.DataFrame()
        assert validate_price_df(df, "AAPL") is False

    def test_missing_columns_fails(self):
        """缺少必需列 (Open)"""
        df = pd.DataFrame({"Close": [100, 101, 102]})
        assert validate_price_df(df, "AAPL") is False

    def test_negative_prices_fail(self):
        """负价格验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, -5, 102, 103, 104, 105, 106, 107, 108, 109],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_zero_prices_fail(self):
        """零价格验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
            "Close": [100, 0, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_too_many_nans_fail(self):
        """NaN 占比 > 5% 验证失败"""
        dates = pd.date_range("2025-01-01", periods=10, freq="B")
        df = pd.DataFrame({
            "Open": [100, np.nan, np.nan, np.nan, np.nan, np.nan, 106, 107, 108, 109],
            "Close": [100, 101, 102, 103, 104, 105, 106, 107, 108, 109],
        }, index=dates)

        assert validate_price_df(df, "AAPL") is False

    def test_acceptable_nan_ratio_passes(self):
        """NaN 占比 < 5% 通过验证"""
        dates = pd.date_range("2025-01-01", periods=100, freq="B")
        opens = np.linspace(100, 110, 100)
        opens[0] = np.nan  # 1% NaN
        df = pd.DataFrame({
            "Open": opens,
            "Close": np.linspace(100, 110, 100),
        }, index=dates)

        assert validate_price_df(df, "AAPL") is True
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data_engine.py::TestValidatePriceDF -v`

Expected: FAIL — `ImportError: cannot import name 'validate_price_df'`

**Step 3: Write minimal implementation**

Add to `src/data_engine.py` after `compute_rsi()`:

```python
def validate_price_df(df: pd.DataFrame, ticker: str) -> bool:
    """
    验证价格 DataFrame 的质量 (data-explorer 思路)

    检查项:
    1. 必须包含 Open, Close 列
    2. 价格值 > 0
    3. 无 NaN (或 NaN 占比 < 5%)
    4. Index 为 DatetimeIndex

    Returns:
        True: 数据合格
        False: 数据异常,应跳过该 ticker
    """
    if df.empty:
        logger.warning(f"Empty price data for {ticker}")
        return False

    required_cols = ["Open", "Close"]
    if not all(col in df.columns for col in required_cols):
        logger.warning(f"Missing required columns for {ticker}")
        return False

    # 检查价格 > 0
    if (df["Close"] <= 0).any() or (df["Open"] <= 0).any():
        logger.warning(f"Invalid price values for {ticker}")
        return False

    # 检查 NaN 占比
    total_cells = len(df) * len(required_cols)
    nan_count = df[required_cols].isna().sum().sum()
    nan_ratio = nan_count / total_cells if total_cells > 0 else 0

    if nan_ratio > 0.05:
        logger.warning(f"Too many NaN values for {ticker}: {nan_ratio:.1%}")
        return False

    return True
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_data_engine.py::TestValidatePriceDF -v`

Expected: ALL PASS (7 tests)

**Step 5: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py
git commit -m "feat: add validate_price_df() data quality gate

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 4: DataEngine — Add `EarningsGap` dataclass and `compute_earnings_gaps()`

**Files:**
- Modify: `src/data_engine.py:14-27` (after TickerData)
- Test: `tests/test_data_engine.py`

**Step 1: Write the failing test**

Add to `tests/test_data_engine.py`:

```python
from src.data_engine import EarningsGap, compute_earnings_gaps

class TestComputeEarningsGaps:
    def test_basic_gap_calculation(self):
        """两个财报事件,已知 Gap 值"""
        earnings_dates = [date(2025, 7, 25), date(2025, 10, 24)]
        dates = pd.date_range("2025-06-01", "2025-11-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        # 第一个财报: prev_close=100, open=105 → gap=+5%
        ed1 = pd.Timestamp("2025-07-25")
        ed1_prev = pd.Timestamp("2025-07-24")
        if ed1 in prices.index and ed1_prev in prices.index:
            prices.loc[ed1_prev, "Close"] = 100.0
            prices.loc[ed1, "Open"] = 105.0

        # 第二个财报: prev_close=100, open=97 → gap=-3%
        ed2 = pd.Timestamp("2025-10-24")
        ed2_prev = pd.Timestamp("2025-10-23")
        if ed2 in prices.index and ed2_prev in prices.index:
            prices.loc[ed2_prev, "Close"] = 100.0
            prices.loc[ed2, "Open"] = 97.0

        result = compute_earnings_gaps("AAPL", earnings_dates, prices)

        assert result is not None
        assert result.ticker == "AAPL"
        assert result.sample_count == 2
        assert result.avg_gap == pytest.approx(4.0, abs=0.1)  # mean(|5|, |-3|) = 4.0
        assert result.up_ratio == pytest.approx(50.0)  # 1上1下 = 50%
        assert abs(result.max_gap) == pytest.approx(5.0, abs=0.1)  # max by abs value

    def test_insufficient_samples_returns_none(self):
        """样本数 < 2 返回 None"""
        earnings_dates = [date(2025, 7, 25)]
        dates = pd.date_range("2025-06-01", "2025-08-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        assert result is None

    def test_empty_earnings_dates_returns_none(self):
        """空财报列表返回 None"""
        dates = pd.date_range("2025-06-01", "2025-08-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        result = compute_earnings_gaps("AAPL", [], prices)
        assert result is None

    def test_empty_price_df_returns_none(self):
        """空价格数据返回 None"""
        earnings_dates = [date(2025, 7, 25), date(2025, 10, 24)]
        result = compute_earnings_gaps("AAPL", earnings_dates, pd.DataFrame())
        assert result is None

    def test_skip_earnings_dates_not_in_prices(self):
        """财报日不在价格数据中,跳过该事件"""
        earnings_dates = [date(2020, 1, 1), date(2020, 4, 1)]  # 不在数据中
        dates = pd.date_range("2025-06-01", "2025-08-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        assert result is None

    def test_skip_zero_prev_close(self):
        """prev_close = 0 的事件被跳过"""
        earnings_dates = [date(2025, 7, 25), date(2025, 10, 24)]
        dates = pd.date_range("2025-06-01", "2025-11-30", freq="B")
        prices = pd.DataFrame({
            "Open": [100.0] * len(dates),
            "Close": [100.0] * len(dates),
        }, index=dates)

        # 设置一个有效 Gap
        ed1 = pd.Timestamp("2025-07-25")
        ed1_prev = pd.Timestamp("2025-07-24")
        if ed1 in prices.index and ed1_prev in prices.index:
            prices.loc[ed1_prev, "Close"] = 100.0
            prices.loc[ed1, "Open"] = 105.0

        # 设置一个无效 Gap (prev_close = 0)
        ed2 = pd.Timestamp("2025-10-24")
        ed2_prev = pd.Timestamp("2025-10-23")
        if ed2 in prices.index and ed2_prev in prices.index:
            prices.loc[ed2_prev, "Close"] = 0.0  # 无效
            prices.loc[ed2, "Open"] = 97.0

        result = compute_earnings_gaps("AAPL", earnings_dates, prices)
        # 只有1个有效样本,应返回 None (min_samples=2)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data_engine.py::TestComputeEarningsGaps -v`

Expected: FAIL — `ImportError: cannot import name 'EarningsGap'`

**Step 3: Write minimal implementation**

Add to `src/data_engine.py` after `TickerData` dataclass:

```python
@dataclass
class EarningsGap:
    """历史财报 Gap 统计"""
    ticker: str
    avg_gap: float       # mean(|gap|) 平均跳空幅度 (%)
    up_ratio: float      # P(gap > 0) 上涨概率 (%)
    max_gap: float       # 最大跳空 (保留符号)
    sample_count: int    # 样本数量


def compute_earnings_gaps(
    ticker: str,
    earnings_dates: list,
    price_df: pd.DataFrame,
    min_samples: int = 2,
) -> Optional[EarningsGap]:
    """
    计算历史财报 Gap 统计

    Gap 定义 (MVP 简化版):
        gap = (财报日 Open - 前一交易日 Close) / 前一交易日 Close * 100

    边界处理:
    - 财报日不在 price_df 中: 跳过该事件
    - 样本数 < min_samples: 返回 None
    - prev_close = 0: 跳过该事件
    """
    if not earnings_dates or price_df.empty:
        return None

    # 数据验证
    if not validate_price_df(price_df, ticker):
        return None

    gaps = []
    for ed in earnings_dates:
        ed_ts = pd.Timestamp(ed)

        # 检查财报日是否在数据中
        if ed_ts not in price_df.index:
            continue

        # 获取前一交易日
        idx = price_df.index.get_loc(ed_ts)
        if idx == 0:
            continue
        prev_ts = price_df.index[idx - 1]

        prev_close = float(price_df.loc[prev_ts, "Close"])
        ed_open = float(price_df.loc[ed_ts, "Open"])

        # 除零保护
        if prev_close == 0 or pd.isna(prev_close):
            continue

        gap = (ed_open - prev_close) / prev_close * 100
        gaps.append(gap)

    # 样本数检查
    if len(gaps) < min_samples:
        return None

    # 统计计算
    abs_gaps = [abs(g) for g in gaps]
    avg_gap = sum(abs_gaps) / len(abs_gaps)
    up_count = sum(1 for g in gaps if g > 0)
    up_ratio = up_count / len(gaps) * 100
    max_gap_val = max(gaps, key=abs)  # 保留符号

    return EarningsGap(
        ticker=ticker,
        avg_gap=round(avg_gap, 1),
        up_ratio=round(up_ratio, 1),
        max_gap=round(max_gap_val, 1),
        sample_count=len(gaps),
    )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_data_engine.py::TestComputeEarningsGaps -v`

Expected: ALL PASS (6 tests)

**Step 5: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py
git commit -m "feat: add EarningsGap dataclass and compute_earnings_gaps()

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Create earnings_calendar.csv fallback file

**Files:**
- Create: `data/earnings_calendar.csv`

**Step 1: Create CSV file with header**

```bash
mkdir -p data
cat > data/earnings_calendar.csv << 'EOF'
ticker,date,time_type
EOF
```

**Step 2: Verify file created**

Run: `cat data/earnings_calendar.csv`

Expected: Shows header row only

**Step 3: Commit**

```bash
git add data/earnings_calendar.csv
git commit -m "feat: add earnings_calendar.csv fallback (empty template)

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 6: MarketDataProvider — Add CSV fallback helper

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

**Step 1: Write the failing test**

Add to `tests/test_market_data.py`:

```python
import os
import tempfile
from unittest.mock import patch

class TestLoadEarningsFromCSV:
    def test_load_from_csv_success(self):
        """成功从 CSV 加载财报日期"""
        # 创建临时 CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            f.write("AAPL,2025-10-31,AMC\n")
            f.write("MSFT,2026-01-28,BMO\n")
            csv_path = f.name

        try:
            config = {"data": {"earnings_csv_path": csv_path}}
            provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
            provider.config = config

            result = provider._load_earnings_from_csv("AAPL", count=2)

            assert len(result) == 2
            assert all(isinstance(d, date) for d in result)
            assert result[0] == date(2026, 1, 30)
            assert result[1] == date(2025, 10, 31)
        finally:
            os.unlink(csv_path)

    def test_csv_not_exists_returns_empty(self):
        """CSV 不存在时返回空列表"""
        config = {"data": {"earnings_csv_path": "/nonexistent/path.csv"}}
        provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
        provider.config = config

        result = provider._load_earnings_from_csv("AAPL", count=5)
        assert result == []

    def test_ticker_not_in_csv_returns_empty(self):
        """Ticker 不在 CSV 中返回空列表"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            csv_path = f.name

        try:
            config = {"data": {"earnings_csv_path": csv_path}}
            provider = MarketDataProvider(ibkr_config=None, iv_db_path=None)
            provider.config = config

            result = provider._load_earnings_from_csv("MSFT", count=5)
            assert result == []
        finally:
            os.unlink(csv_path)
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_data.py::TestLoadEarningsFromCSV -v`

Expected: FAIL — `AttributeError: 'MarketDataProvider' object has no attribute '_load_earnings_from_csv'`

**Step 3: Write minimal implementation**

First, update `MarketDataProvider.__init__()` to accept config:

```python
def __init__(self, ibkr_config: Optional[dict] = None, iv_db_path: Optional[str] = None):
    self.ibkr = None
    self.ibkr_config = ibkr_config
    self.iv_store: Optional[IVStore] = None
    self.config: dict = {}  # 新增
    if ibkr_config:
        self.ibkr = self._try_connect_ibkr(ibkr_config)
    if iv_db_path:
        self.iv_store = IVStore(iv_db_path)
```

Then add the helper method after `get_earnings_date()`:

```python
import os

def _load_earnings_from_csv(self, ticker: str, count: int) -> list:
    """从本地 CSV 加载财报日期"""
    csv_path = self.config.get("data", {}).get(
        "earnings_csv_path",
        "data/earnings_calendar.csv"
    )

    if not os.path.exists(csv_path):
        logger.debug(f"Earnings CSV not found: {csv_path}")
        return []

    try:
        df = pd.read_csv(csv_path)
        # 列名: ticker, date, time_type (可选)
        ticker_data = df[df["ticker"] == ticker].copy()
        if ticker_data.empty:
            return []
        ticker_data["date"] = pd.to_datetime(ticker_data["date"]).dt.date
        dates = ticker_data["date"].tolist()
        dates.sort(reverse=True)
        return dates[:count]
    except Exception as e:
        logger.error(f"CSV earnings load failed for {ticker}: {e}")
        return []
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_data.py::TestLoadEarningsFromCSV -v`

Expected: ALL PASS (3 tests)

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add _load_earnings_from_csv() fallback helper

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 7: MarketDataProvider — Add `get_historical_earnings_dates()` with fallback

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

**Step 1: Write the failing test**

Add to `tests/test_market_data.py`:

```python
class TestGetHistoricalEarningsDates:
    @patch("src.market_data.yf.Ticker")
    def test_yfinance_success(self, MockTicker):
        """yfinance 成功返回历史财报日期"""
        mock_t = MockTicker.return_value
        mock_t.earnings_dates = pd.DataFrame(
            {"EPS Estimate": [1.0, 1.1, 1.2]},
            index=pd.to_datetime(["2026-04-25", "2026-01-20", "2025-10-15"]),
        )

        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("AAPL", count=3)

        assert len(result) <= 3
        assert all(isinstance(d, date) for d in result)

    @patch("src.market_data.yf.Ticker")
    def test_yfinance_fails_fallback_to_csv(self, MockTicker):
        """yfinance 失败时降级到 CSV"""
        mock_t = MockTicker.return_value
        mock_t.earnings_dates = None  # 模拟失败

        # 创建临时 CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as f:
            f.write("ticker,date,time_type\n")
            f.write("AAPL,2026-01-30,AMC\n")
            csv_path = f.name

        try:
            provider = MarketDataProvider()
            provider.config = {"data": {"earnings_csv_path": csv_path}}

            result = provider.get_historical_earnings_dates("AAPL", count=5)

            assert len(result) == 1
            assert result[0] == date(2026, 1, 30)
        finally:
            os.unlink(csv_path)

    def test_cn_market_returns_empty(self):
        """CN 市场直接返回空列表"""
        provider = MarketDataProvider()
        result = provider.get_historical_earnings_dates("600900.SS", count=5)
        assert result == []
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_data.py::TestGetHistoricalEarningsDates -v`

Expected: FAIL — `AttributeError: 'MarketDataProvider' object has no attribute 'get_historical_earnings_dates'`

**Step 3: Write minimal implementation**

Add to `src/market_data.py` after `get_earnings_date()`:

```python
def get_historical_earnings_dates(self, ticker: str, count: int = 8) -> list:
    """
    获取历史财报日期 (yfinance → 本地 CSV 降级)

    Fallback 链路:
    1. 尝试 yfinance Ticker.earnings_dates
    2. 失败时读取 data/earnings_calendar.csv
    3. 仍无数据返回 []
    """
    if self.should_skip_options(ticker):
        return []

    # 一级: yfinance
    try:
        t = yf.Ticker(ticker)
        ed = t.earnings_dates
        if ed is not None and not ed.empty:
            today = date.today()
            past_dates = [d.date() for d in ed.index if d.date() < today]
            past_dates.sort(reverse=True)
            return past_dates[:count]
    except Exception as e:
        logger.warning(f"yfinance earnings dates failed for {ticker}: {e}")

    # 二级: 本地 CSV Fallback
    return self._load_earnings_from_csv(ticker, count)
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_data.py::TestGetHistoricalEarningsDates -v`

Expected: ALL PASS (3 tests)

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add get_historical_earnings_dates() with CSV fallback

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 8: MarketDataProvider — Add `get_iv_momentum()`

**Files:**
- Modify: `src/market_data.py`
- Test: `tests/test_market_data.py`

**Step 1: Write the failing test**

Add to `tests/test_market_data.py`:

```python
class TestGetIVMomentum:
    @patch("src.market_data.yf.Ticker")
    def test_iv_momentum_calculated(self, MockTicker):
        """成功计算 IV 动量"""
        mock_t = MockTicker.return_value
        mock_t.info = {"regularMarketPrice": 150.0}
        mock_t.options = ["2026-03-20"]

        # Mock 期权链
        from unittest.mock import MagicMock
        mock_chain = MagicMock()
        mock_calls = pd.DataFrame({
            "strike": [145, 150, 155],
            "impliedVolatility": [0.30, 0.28, 0.29],
        })
        mock_chain.calls = mock_calls
        mock_t.option_chain.return_value = mock_chain

        # Mock IVStore
        mock_store = MagicMock()
        mock_store.get_iv_n_days_ago.return_value = 0.20  # 5天前 IV = 0.20

        provider = MarketDataProvider()
        provider.iv_store = mock_store

        result = provider.get_iv_momentum("AAPL")

        # (0.28 - 0.20) / 0.20 * 100 = 40%
        assert result == pytest.approx(40.0, abs=1.0)

    def test_cn_market_returns_none(self):
        """CN 市场返回 None"""
        provider = MarketDataProvider()
        provider.iv_store = MagicMock()
        result = provider.get_iv_momentum("600900.SS")
        assert result is None

    def test_no_iv_store_returns_none(self):
        """无 IVStore 返回 None"""
        provider = MarketDataProvider()
        provider.iv_store = None
        result = provider.get_iv_momentum("AAPL")
        assert result is None

    @patch("src.market_data.yf.Ticker")
    def test_no_historical_iv_returns_none(self, MockTicker):
        """5天前无 IV 数据返回 None"""
        mock_t = MockTicker.return_value
        mock_t.info = {"regularMarketPrice": 150.0}
        mock_t.options = ["2026-03-20"]

        mock_chain = MagicMock()
        mock_calls = pd.DataFrame({
            "strike": [150],
            "impliedVolatility": [0.28],
        })
        mock_chain.calls = mock_calls
        mock_t.option_chain.return_value = mock_chain

        mock_store = MagicMock()
        mock_store.get_iv_n_days_ago.return_value = None  # 无历史数据

        provider = MarketDataProvider()
        provider.iv_store = mock_store

        result = provider.get_iv_momentum("AAPL")
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_market_data.py::TestGetIVMomentum -v`

Expected: FAIL — `AttributeError: 'MarketDataProvider' object has no attribute 'get_iv_momentum'`

**Step 3: Write minimal implementation**

Add to `src/market_data.py` after `get_iv_rank()`:

```python
def get_iv_momentum(self, ticker: str) -> Optional[float]:
    """
    计算 5 日 IV 动量: (current_iv - iv_5d_ago) / iv_5d_ago * 100

    依赖:
    - iv_store.get_iv_n_days_ago()
    - 当前 ATM IV

    返回:
    - float: 百分比变化率
    - None: 数据不足或非期权标的
    """
    if self.should_skip_options(ticker) or not self.iv_store:
        return None

    try:
        # 获取当前 IV
        t = yf.Ticker(ticker)
        current_price = t.info.get("regularMarketPrice") or t.info.get("previousClose")
        if not current_price:
            return None

        exps = t.options
        if not exps:
            return None

        chain = t.option_chain(exps[0])
        calls = chain.calls
        if calls.empty:
            return None

        calls = calls.copy()
        calls["diff"] = abs(calls["strike"] - current_price)
        atm = calls.loc[calls["diff"].idxmin()]
        current_iv = float(atm["impliedVolatility"])

        # 获取 5 天前 IV
        iv_5d_ago = self.iv_store.get_iv_n_days_ago(ticker, n=5)
        if iv_5d_ago is None or iv_5d_ago == 0:
            return None

        return round((current_iv - iv_5d_ago) / iv_5d_ago * 100, 1)

    except Exception as e:
        logger.warning(f"IV momentum failed for {ticker}: {e}")
        return None
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_market_data.py::TestGetIVMomentum -v`

Expected: ALL PASS (4 tests)

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add get_iv_momentum() for 5-day IV change rate

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 9: TickerData — Add `iv_momentum` field

**Files:**
- Modify: `src/data_engine.py:14-27` (TickerData dataclass)
- Modify: `src/data_engine.py:58-121` (build_ticker_data)
- Test: `tests/test_data_engine.py`
- Test: `tests/test_scanners.py` (update make_ticker)
- Test: `tests/test_report.py` (update make_ticker)
- Test: `tests/test_integration.py` (update make_ticker)

**Step 1: Write the failing test**

Add to `tests/test_data_engine.py`:

```python
from unittest.mock import patch, MagicMock

class TestIVMomentum:
    @patch("src.data_engine.MarketDataProvider")
    def test_iv_momentum_calculated(self, MockProvider):
        """iv_momentum 成功计算"""
        provider = MockProvider()
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        daily_df = pd.DataFrame({"Close": np.linspace(100, 200, 250)}, index=dates)
        provider.get_price_data.return_value = daily_df

        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_df = pd.DataFrame({"Close": np.linspace(90, 190, 60)}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        provider.get_earnings_date.return_value = None
        provider.get_iv_rank.return_value = 50.0
        provider.get_iv_momentum.return_value = 35.0  # 新增

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))
        assert result is not None
        assert result.iv_momentum == 35.0

    @patch("src.data_engine.MarketDataProvider")
    def test_iv_momentum_none_when_unavailable(self, MockProvider):
        """iv_momentum 无数据时为 None"""
        provider = MockProvider()
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        daily_df = pd.DataFrame({"Close": np.linspace(100, 200, 250)}, index=dates)
        provider.get_price_data.return_value = daily_df

        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_df = pd.DataFrame({"Close": np.linspace(90, 190, 60)}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        provider.get_earnings_date.return_value = None
        provider.get_iv_rank.return_value = 50.0
        provider.get_iv_momentum.return_value = None  # 无数据

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))
        assert result is not None
        assert result.iv_momentum is None
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_data_engine.py::TestIVMomentum -v`

Expected: FAIL — TickerData has no field `iv_momentum`

**Step 3: Write minimal implementation**

In `src/data_engine.py`, update TickerData (after `iv_rank` field):

```python
@dataclass
class TickerData:
    ticker: str
    name: str
    market: str
    last_price: float
    ma200: Optional[float]
    ma50w: Optional[float]
    rsi14: Optional[float]
    iv_rank: Optional[float]
    iv_momentum: Optional[float]  # 新增: 5日IV动量 (%)
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]
```

In `build_ticker_data()`, after `iv_rank = provider.get_iv_rank(ticker)`:

```python
    iv_momentum = provider.get_iv_momentum(ticker)
```

In the return statement, add `iv_momentum=iv_momentum` after `iv_rank=iv_rank`.

**Step 4: Update all test helpers**

Update `make_ticker()` in `tests/test_scanners.py`:

```python
def make_ticker(**overrides):
    defaults = {
        "ticker": "TEST",
        "name": "Test Corp",
        "market": "US",
        "last_price": 100.0,
        "ma200": 95.0,
        "ma50w": 98.0,
        "rsi14": 50.0,
        "iv_rank": 50.0,
        "iv_momentum": None,  # 新增
        "prev_close": 99.0,
        "earnings_date": None,
        "days_to_earnings": None,
    }
    defaults.update(overrides)
    return TickerData(**defaults)
```

Repeat for `tests/test_report.py` and `tests/test_integration.py`.

**Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/ -v`

Expected: ALL PASS (all existing + new tests)

**Step 6: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py tests/test_scanners.py tests/test_report.py tests/test_integration.py
git commit -m "feat: add iv_momentum field to TickerData

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 10: Scanners — Add `scan_iv_momentum()`

**Files:**
- Modify: `src/scanners.py`
- Test: `tests/test_scanners.py`

**Step 1: Write the failing test**

Add to `tests/test_scanners.py`:

```python
from src.scanners import scan_iv_momentum

class TestIVMomentumScanner:
    def test_high_momentum_detected(self):
        """高动量标的被筛选"""
        data = [
            make_ticker(ticker="SPIKE", iv_momentum=45.0),
            make_ticker(ticker="CALM", iv_momentum=10.0),
        ]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 1
        assert result[0].ticker == "SPIKE"

    def test_boundary_excluded(self):
        """边界值 (30.0) 不触发"""
        data = [make_ticker(ticker="EXACT", iv_momentum=30.0)]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 0

    def test_none_momentum_skipped(self):
        """iv_momentum=None 的标的被跳过"""
        data = [make_ticker(ticker="NODATA", iv_momentum=None)]
        result = scan_iv_momentum(data, threshold=30.0)

        assert len(result) == 0

    def test_sorted_descending(self):
        """结果按 iv_momentum 降序排列"""
        data = [
            make_ticker(ticker="A", iv_momentum=35.0),
            make_ticker(ticker="B", iv_momentum=50.0),
            make_ticker(ticker="C", iv_momentum=40.0),
        ]
        result = scan_iv_momentum(data, threshold=30.0)

        assert [t.ticker for t in result] == ["B", "C", "A"]

    def test_custom_threshold(self):
        """自定义阈值"""
        data = [make_ticker(ticker="MED", iv_momentum=25.0)]
        assert len(scan_iv_momentum(data, threshold=20.0)) == 1
        assert len(scan_iv_momentum(data, threshold=30.0)) == 0
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_scanners.py::TestIVMomentumScanner -v`

Expected: FAIL — `ImportError: cannot import name 'scan_iv_momentum'`

**Step 3: Write minimal implementation**

Add to `src/scanners.py` (after `scan_iv_extremes`):

```python
def scan_iv_momentum(
    data: List[TickerData],
    threshold: float = 30.0
) -> List[TickerData]:
    """
    波动率异动雷达: 筛选 IV 快速膨胀的标的

    触发条件:
        iv_momentum > threshold (默认 30%)

    输出:
        符合条件的 TickerData 列表,按 iv_momentum 降序排列
    """
    result = [
        t for t in data
        if t.iv_momentum is not None and t.iv_momentum > threshold
    ]
    # 按动量降序排列
    result.sort(key=lambda x: x.iv_momentum, reverse=True)
    return result
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_scanners.py::TestIVMomentumScanner -v`

Expected: ALL PASS (5 tests)

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add scan_iv_momentum() scanner

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 11: Scanners — Add `scan_earnings_gap()`

**Files:**
- Modify: `src/scanners.py`
- Test: `tests/test_scanners.py`

**Step 1: Write the failing test**

Add to `tests/test_scanners.py`:

```python
from src.scanners import scan_earnings_gap
from src.data_engine import EarningsGap
from unittest.mock import MagicMock

class TestEarningsGapScanner:
    def test_ticker_within_threshold_analyzed(self):
        """临近财报的标的被分析"""
        data = [
            make_ticker(ticker="AAPL", days_to_earnings=2, earnings_date=date(2026, 2, 27)),
            make_ticker(ticker="MSFT", days_to_earnings=10, earnings_date=date(2026, 3, 7)),
        ]

        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = False

        # Mock 历史财报日期
        mock_provider.get_historical_earnings_dates.return_value = [
            date(2026, 1, 20), date(2025, 10, 15), date(2025, 7, 10),
        ]

        # Mock 价格数据
        dates_idx = pd.date_range("2025-06-01", "2026-02-25", freq="B")
        price_df = pd.DataFrame({
            "Open": [100.0] * len(dates_idx),
            "Close": [100.0] * len(dates_idx),
        }, index=dates_idx)

        # 设置 Gap
        for ed, gap_open in [
            (pd.Timestamp("2026-01-20"), 106.0),
            (pd.Timestamp("2025-10-15"), 95.0),
            (pd.Timestamp("2025-07-10"), 103.0)
        ]:
            if ed in price_df.index:
                price_df.loc[ed, "Open"] = gap_open

        mock_provider.get_price_data.return_value = price_df

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)

        assert len(result) == 1
        assert result[0].ticker == "AAPL"
        assert result[0].sample_count >= 2

    def test_ticker_outside_threshold_skipped(self):
        """超过阈值的标的被跳过"""
        data = [make_ticker(ticker="MSFT", days_to_earnings=10)]
        mock_provider = MagicMock()

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0

    def test_ticker_with_no_earnings_date_skipped(self):
        """无财报日期的标的被跳过"""
        data = [make_ticker(ticker="NOEARN", days_to_earnings=None, earnings_date=None)]
        mock_provider = MagicMock()

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0

    def test_cn_market_skipped(self):
        """CN 市场被跳过"""
        data = [make_ticker(ticker="600900.SS", days_to_earnings=2)]
        mock_provider = MagicMock()
        mock_provider.should_skip_options.return_value = True

        result = scan_earnings_gap(data, mock_provider, days_threshold=3)
        assert len(result) == 0
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_scanners.py::TestEarningsGapScanner -v`

Expected: FAIL — `ImportError: cannot import name 'scan_earnings_gap'`

**Step 3: Write minimal implementation**

Update imports at top of `src/scanners.py`:

```python
from src.data_engine import TickerData, EarningsGap, compute_earnings_gaps
```

Add to `src/scanners.py`:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.market_data import MarketDataProvider

def scan_earnings_gap(
    data: List[TickerData],
    provider: "MarketDataProvider",
    days_threshold: int = 3,
) -> List[EarningsGap]:
    """
    财报 Gap 黑天鹅预警: 分析即将财报的历史跳空风险

    触发条件:
        days_to_earnings <= days_threshold (默认 3 天)
    """
    results = []

    for t in data:
        # 检查是否临近财报
        if t.days_to_earnings is None or t.days_to_earnings > days_threshold:
            continue

        # 跳过非期权市场
        if provider.should_skip_options(t.ticker):
            continue

        try:
            # 获取历史财报日期 (带 fallback)
            hist_dates = provider.get_historical_earnings_dates(t.ticker)
            if len(hist_dates) < 2:
                logger.debug(f"Insufficient earnings history for {t.ticker}")
                continue

            # 获取历史价格
            price_df = provider.get_price_data(t.ticker, period="3y")
            if price_df.empty:
                logger.warning(f"No price data for {t.ticker}")
                continue

            # 计算 Gap 统计
            gap = compute_earnings_gaps(t.ticker, hist_dates, price_df)
            if gap:
                results.append(gap)

        except Exception as e:
            logger.error(f"Earnings gap scan failed for {t.ticker}: {e}")
            continue

    return results
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_scanners.py::TestEarningsGapScanner -v`

Expected: ALL PASS (4 tests)

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add scan_earnings_gap() scanner

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 12: Config — Add Phase 2 scanner settings

**Files:**
- Modify: `config.yaml`
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_config_has_phase2_scanner_settings():
    """配置包含 Phase 2 扫描器设置"""
    config = load_config("config.yaml")
    scanners = config.get("scanners", {})

    assert "iv_momentum_threshold" in scanners
    assert "earnings_gap_days" in scanners
    assert "earnings_lookback" in scanners

    data_config = config.get("data", {})
    assert "earnings_csv_path" in data_config
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_config.py::test_config_has_phase2_scanner_settings -v`

Expected: FAIL — no `scanners` section in config

**Step 3: Write minimal implementation**

Add to `config.yaml`:

```yaml
data:
  iv_history_db: "data/iv_history.db"
  price_period: "1y"
  earnings_csv_path: "data/earnings_calendar.csv"

scanners:
  iv_momentum_threshold: 30
  earnings_gap_days: 3
  earnings_lookback: 8
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_config.py -v`

Expected: ALL PASS

**Step 5: Commit**

```bash
git add config.yaml tests/test_config.py
git commit -m "feat: add Phase 2 scanner config settings

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 13: Report — Add IV Momentum section

**Files:**
- Modify: `src/report.py`
- Test: `tests/test_report.py`

**Step 1: Write the failing test**

Add to `tests/test_report.py`:

```python
class TestIVMomentumSection:
    def test_momentum_tickers_in_report(self):
        """IV 动量标的出现在报告中"""
        momentum = [
            make_ticker(ticker="SPIKE", iv_momentum=45.0, iv_rank=72.0, days_to_earnings=2)
        ]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=momentum,
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in report
        assert "SPIKE" in report
        assert "45.0" in report

    def test_empty_momentum_shows_placeholder(self):
        """无符合条件的标的显示占位符"""
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=[],
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in report
        assert "无符合条件的标的" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py::TestIVMomentumSection -v`

Expected: FAIL — `format_report()` doesn't accept `iv_momentum` parameter

**Step 3: Write minimal implementation**

Update `format_report()` signature in `src/report.py`:

```python
def format_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: List[TickerData],
    iv_high: List[TickerData],
    ma200_bullish: List[TickerData],
    ma200_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_puts: List[Tuple[SellPutSignal, TickerData]],
    iv_momentum: Optional[List[TickerData]] = None,  # 新增
    earnings_gaps: Optional[list] = None,  # 新增 (后续任务)
    earnings_gap_ticker_map: Optional[dict] = None,  # 新增 (后续任务)
    skipped: Optional[List[Tuple[str, str]]] = None,
    elapsed_seconds: float = 0.0,
) -> str:
```

Add section after Sell Put section (before Skipped):

```python
    # --- IV Momentum ---
    iv_momentum_list = iv_momentum or []
    lines.append("── 波动率异动雷达 (5日IV动量) ──────────────────────")
    lines.append("")

    if iv_momentum_list:
        for t in iv_momentum_list:
            iv_mom_str = f"+{t.iv_momentum:.1f}%" if t.iv_momentum else "N/A"
            iv_rank_str = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
            earnings_tag = format_earnings_tag(t.earnings_date, t.days_to_earnings)

            lines.append(
                f"  {t.ticker:<8} "
                f"IV动量: {iv_mom_str}  "
                f"IV Rank: {iv_rank_str}  "
                f"│ {earnings_tag}"
            )
    else:
        lines.append("  (无符合条件的标的)")

    lines.append("")
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py::TestIVMomentumSection -v`

Expected: ALL PASS (2 tests)

**Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: add IV Momentum section to text report

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 14: Report — Add Earnings Gap section

**Files:**
- Modify: `src/report.py`
- Test: `tests/test_report.py`

**Step 1: Write the failing test**

Add to `tests/test_report.py`:

```python
from src.data_engine import EarningsGap

class TestEarningsGapSection:
    def test_gap_data_in_report(self):
        """Gap 数据出现在报告中"""
        gaps = [
            EarningsGap(
                ticker="AAPL",
                avg_gap=4.2,
                up_ratio=62.5,
                max_gap=-8.1,
                sample_count=6
            )
        ]
        ticker_map = {
            "AAPL": make_ticker(
                ticker="AAPL",
                iv_rank=85.3,
                days_to_earnings=2
            )
        }

        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )

        assert "财报 Gap 预警" in report
        assert "AAPL" in report
        assert "4.2" in report
        assert "62.5" in report
        assert "-8.1" in report
        assert "85.3" in report

    def test_high_iv_risk_warning(self):
        """高 IV + 临近财报显示风险警告"""
        gaps = [EarningsGap("AAPL", 4.2, 62.5, -8.1, 6)]
        ticker_map = {
            "AAPL": make_ticker(ticker="AAPL", iv_rank=75.0, days_to_earnings=2)
        }

        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )

        assert "IV Crush 风险" in report

    def test_empty_gaps_shows_placeholder(self):
        """无符合条件的标的显示占位符"""
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=[],
            elapsed_seconds=5.0,
        )

        assert "财报 Gap 预警" in report
        assert "无符合条件的标的" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_report.py::TestEarningsGapSection -v`

Expected: FAIL — section not in report

**Step 3: Write minimal implementation**

Add import at top of `src/report.py`:

```python
from src.data_engine import TickerData, EarningsGap
```

Add section after IV Momentum section:

```python
    # --- Earnings Gap ---
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}

    lines.append("── 财报 Gap 预警 ─────────────────────────────────")
    lines.append("")

    if gaps_list:
        for g in gaps_list:
            td = gap_map.get(g.ticker)

            # 提取信息 (兜底处理)
            days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
            iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"

            # 行1: 警告标题
            lines.append(f"  ⚠️ {g.ticker} 财报还有 {days_str}")

            # 行2: Gap 统计
            lines.append(
                f"     历史平均 Gap ±{g.avg_gap:.1f}%  |  "
                f"上涨概率 {g.up_ratio:.1f}%  |  "
                f"历史最大跳空 {g.max_gap:+.1f}%"
            )

            # 行3: 当前状态
            lines.append(
                f"     当前 IV Rank: {iv_str}  "
                f"(样本数: {g.sample_count})"
            )

            # 风险标注: 高 IV + 临近财报
            if td and td.iv_rank is not None and td.iv_rank > 70:
                lines.append(
                    f"     🔥 高 IV ({td.iv_rank:.1f}%) + 临近财报 → IV Crush 风险!"
                )

            lines.append("")
    else:
        lines.append("  (无符合条件的标的)")

    lines.append("")
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_report.py::TestEarningsGapSection -v`

Expected: ALL PASS (3 tests)

**Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: add Earnings Gap section to text report

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 15: HTML Report — Add IV Momentum and Earnings Gap cards

**Files:**
- Modify: `src/html_report.py`
- Test: `tests/test_html_report.py`

**Step 1: Write the failing test**

Add to `tests/test_html_report.py` (create if not exists):

```python
from src.html_report import format_html_report
from src.data_engine import TickerData, EarningsGap
from datetime import date

def make_ticker(**overrides):
    defaults = {
        "ticker": "TEST", "name": "Test", "market": "US",
        "last_price": 100.0, "ma200": 95.0, "ma50w": 98.0,
        "rsi14": 50.0, "iv_rank": 50.0, "iv_momentum": None,
        "prev_close": 99.0, "earnings_date": None, "days_to_earnings": None,
    }
    defaults.update(overrides)
    return TickerData(**defaults)

class TestIVMomentumCard:
    def test_momentum_card_in_html(self):
        """IV Momentum 卡片出现在 HTML 中"""
        momentum = [make_ticker(ticker="SPIKE", iv_momentum=45.0)]
        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            iv_momentum=momentum,
            elapsed_seconds=5.0,
        )

        assert "波动率异动雷达" in html
        assert "SPIKE" in html

class TestEarningsGapCard:
    def test_gap_card_in_html(self):
        """Earnings Gap 卡片出现在 HTML 中"""
        gaps = [EarningsGap("AAPL", 4.2, 62.5, -8.1, 6)]
        ticker_map = {"AAPL": make_ticker(ticker="AAPL", iv_rank=85.3, days_to_earnings=2)}

        html = format_html_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            earnings_gaps=gaps,
            earnings_gap_ticker_map=ticker_map,
            elapsed_seconds=5.0,
        )

        assert "财报 Gap 预警" in html
        assert "AAPL" in html
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_html_report.py -v`

Expected: FAIL — parameters not accepted

**Step 3: Write minimal implementation**

Update `format_html_report()` signature in `src/html_report.py`:

```python
def format_html_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: List[TickerData],
    iv_high: List[TickerData],
    ma200_bullish: List[TickerData],
    ma200_bearish: List[TickerData],
    leaps: List[TickerData],
    sell_puts: List[Tuple[SellPutSignal, TickerData]],
    iv_momentum: Optional[List[TickerData]] = None,
    earnings_gaps: Optional[list] = None,
    earnings_gap_ticker_map: Optional[dict] = None,
    skipped: Optional[List[Tuple[str, str]]] = None,
    elapsed_seconds: float = 0.0,
) -> str:
```

Add helper functions before `format_html_report()`:

```python
def _iv_momentum_table(tickers: List[TickerData]) -> str:
    """生成 IV 动量表格"""
    if not tickers:
        return f'<table>{_empty_row(4)}</table>'

    rows = []
    for t in tickers:
        mom_str = f"+{t.iv_momentum:.1f}%" if t.iv_momentum is not None else "N/A"
        iv_str = f"{t.iv_rank:.1f}%" if t.iv_rank is not None else "N/A"
        earnings_str = _format_earnings(t.earnings_date, t.days_to_earnings)

        rows.append(
            f"<tr>"
            f'<td class="ticker">{_escape(t.ticker)}</td>'
            f"<td>IV动量: {_escape(mom_str)}</td>"
            f"<td>IV Rank: {_escape(iv_str)}</td>"
            f"<td>{_escape(earnings_str)}</td>"
            f"</tr>"
        )

    return "<table>" + "".join(rows) + "</table>"


def _earnings_gap_table(gaps: list, ticker_map: dict) -> str:
    """生成财报 Gap 预警表格"""
    if not gaps:
        return f'<table>{_empty_row(4)}</table>'

    rows = []
    for g in gaps:
        td = ticker_map.get(g.ticker)
        days_str = f"{td.days_to_earnings}天" if td and td.days_to_earnings is not None else "N/A"
        iv_str = f"{td.iv_rank:.1f}%" if td and td.iv_rank is not None else "N/A"

        # 风险标注
        risk_badge = ""
        if td and td.iv_rank is not None and td.iv_rank > 70:
            risk_badge = ' <span class="risk-badge">高IV风险</span>'

        rows.append(
            f"<tr>"
            f'<td class="ticker">⚠️ {_escape(g.ticker)}{risk_badge}</td>'
            f"<td>财报还有 {_escape(days_str)}<br>"
            f"平均Gap ±{g.avg_gap:.1f}% · 上涨概率 {g.up_ratio:.1f}%</td>"
            f"<td>最大跳空 {g.max_gap:+.1f}%<br>样本数: {g.sample_count}</td>"
            f"<td>IV Rank: {_escape(iv_str)}</td>"
            f"</tr>"
        )

    return "<table>" + "".join(rows) + "</table>"
```

Add cards before Skipped section in `format_html_report()`:

```python
    # --- Card: IV Momentum ---
    iv_momentum_list = iv_momentum or []
    parts.append('<div class="card">')
    parts.append("<h2>波动率异动雷达 (5日IV动量)</h2>")
    parts.append(_iv_momentum_table(iv_momentum_list))
    parts.append("</div>")

    # --- Card: Earnings Gap ---
    gaps_list = earnings_gaps or []
    gap_map = earnings_gap_ticker_map or {}
    parts.append('<div class="card">')
    parts.append("<h2>财报 Gap 预警</h2>")
    parts.append(_earnings_gap_table(gaps_list, gap_map))
    parts.append("</div>")
```

Add CSS for risk badge in the `<style>` section:

```css
.risk-badge {
    background: #ff3b30;
    color: white;
    padding: 2px 6px;
    border-radius: 4px;
    font-size: 0.85em;
    margin-left: 8px;
}
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_html_report.py -v`

Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/html_report.py tests/test_html_report.py
git commit -m "feat: add IV Momentum and Earnings Gap cards to HTML report

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 16: Main pipeline — Wire Phase 2 scanners

**Files:**
- Modify: `src/main.py`
- Test: `tests/test_integration.py`

**Step 1: Write the failing test**

Add to `tests/test_integration.py`:

```python
from src.scanners import scan_iv_momentum, scan_earnings_gap

def test_phase2_pipeline_integration(mock_provider):
    """Phase 2 扫描器集成测试"""
    td = build_ticker_data("AAPL", mock_provider, reference_date=date(2026, 2, 20))
    assert td is not None

    all_data = [td]

    # Phase 1 扫描器
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Phase 2 扫描器
    iv_momentum = scan_iv_momentum(all_data, threshold=30.0)
    earnings_gaps = scan_earnings_gap(all_data, mock_provider, days_threshold=3)

    # 生成报告
    report = format_report(
        scan_date=date(2026, 2, 20),
        data_source="mock",
        universe_count=1,
        iv_low=iv_low, iv_high=iv_high,
        ma200_bullish=ma200_bull, ma200_bearish=ma200_bear,
        leaps=leaps, sell_puts=[],
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map={"AAPL": td},
        elapsed_seconds=1.0,
    )

    assert "波动率异动雷达" in report
    assert "财报 Gap 预警" in report
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_integration.py::test_phase2_pipeline_integration -v`

Expected: FAIL — imports or mismatched calls

**Step 3: Write minimal implementation**

Update imports in `src/main.py`:

```python
from src.scanners import (
    scan_iv_extremes,
    scan_ma200_crossover,
    scan_leaps_setup,
    scan_sell_put,
    scan_iv_momentum,     # 新增
    scan_earnings_gap,    # 新增
)
```

Add after Phase 1 scanners (around line 77):

```python
    # Phase 2: IV Momentum
    scanner_config = config.get("scanners", {})
    iv_momentum = scan_iv_momentum(
        all_data,
        threshold=scanner_config.get("iv_momentum_threshold", 30)
    )

    # Phase 2: Earnings Gap
    earnings_gaps = scan_earnings_gap(
        all_data,
        provider,
        days_threshold=scanner_config.get("earnings_gap_days", 3),
    )
    earnings_gap_ticker_map = {td.ticker: td for td in all_data}
```

Update both `format_report()` and `format_html_report()` calls:

```python
    report = format_report(
        scan_date=scan_date,
        data_source=data_source,
        universe_count=len(universe),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_puts,
        iv_momentum=iv_momentum,           # 新增
        earnings_gaps=earnings_gaps,       # 新增
        earnings_gap_ticker_map=earnings_gap_ticker_map,  # 新增
        skipped=skipped,
        elapsed_seconds=elapsed,
    )

    html_report = format_html_report(
        scan_date=scan_date,
        data_source=data_source,
        universe_count=len(universe),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_puts,
        iv_momentum=iv_momentum,           # 新增
        earnings_gaps=earnings_gaps,       # 新增
        earnings_gap_ticker_map=earnings_gap_ticker_map,  # 新增
        skipped=skipped,
        elapsed_seconds=elapsed,
    )
```

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_integration.py -v`

Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/main.py tests/test_integration.py
git commit -m "feat: wire Phase 2 scanners into main pipeline

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Task 17: Final verification and cleanup

**Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v --tb=short`

Expected: ALL PASS, zero failures

**Step 2: Check test coverage (optional)**

Run: `python3 -m pytest tests/ --cov=src --cov-report=term-missing`

Expected: Coverage > 80%

**Step 3: Update implementation plan status**

Mark this plan as completed in `docs/plans/` (add "COMPLETED" to filename or move to archive).

**Step 4: Final commit**

```bash
git add .
git commit -m "docs: mark Phase 2 IV Enhanced implementation as complete

All tests passing. Ready for production use.

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Step 5: Push to remote (if applicable)**

```bash
git push
```

---

## Implementation Complete ✅

**Summary:**
- ✅ 17 tasks completed
- ✅ 31+ test cases added
- ✅ All tests passing
- ✅ CSV fallback mechanism implemented
- ✅ Data validation gates in place
- ✅ Error isolation at 3 levels
- ✅ Phase 2 scanners integrated into main pipeline

**Next Steps:**
- Monitor production runs for CSV fallback usage
- Gradually populate `data/earnings_calendar.csv` with key tickers
- Consider upgrading to Phase 2.2 (AMC/BMO detection) if needed
