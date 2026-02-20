# V1.9 Quant Radar Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a daily stock scanning script that pulls a universe from Google Sheets, computes technical indicators via IBKR/yfinance, runs 5 scanner modules, and outputs a clean text report.

**Architecture:** Monolithic Python package with separated modules. IBKR primary data source with yfinance fallback. SQLite for IV history. Docker for deployment.

**Tech Stack:** Python 3.11+, ib_insync, yfinance, pandas, PyYAML, SQLite, Docker

---

### Task 1: Project Scaffolding

**Files:**
- Create: `requirements.txt`
- Create: `config.yaml`
- Create: `src/__init__.py`
- Create: `tests/__init__.py`
- Create: `.gitignore`

**Step 1: Create requirements.txt**

```
ib_insync>=0.9.86
yfinance>=0.2.31
pandas>=2.0.0
PyYAML>=6.0
pytest>=7.0.0
```

**Step 2: Create config.yaml**

```yaml
# V1.9 Quant Radar Configuration

csv_url: "https://docs.google.com/spreadsheets/d/1O_txXYVAcDp0syjexAcowRRdrNX4gyrFzrGqNgh9dfw/export?format=csv"

ibkr:
  host: "127.0.0.1"
  port: 4001          # IB Gateway paper=4002, live=4001
  client_id: 1
  timeout: 30          # seconds

data:
  iv_history_db: "data/iv_history.db"
  price_period: "1y"   # how far back to fetch for MA200

reports:
  output_dir: "reports"
  log_dir: "logs"

schedule:
  timezone: "Asia/Shanghai"
  run_time: "17:00"
```

**Step 3: Create .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
data/iv_history.db
reports/*.txt
logs/*.log
.env
*.egg-info/
dist/
build/
.DS_Store
```

**Step 4: Create empty __init__.py files**

```bash
mkdir -p src tests data reports logs
touch src/__init__.py tests/__init__.py
```

**Step 5: Install dependencies and verify**

Run: `pip install -r requirements.txt`
Expected: All packages install successfully

**Step 6: Commit**

```bash
git add requirements.txt config.yaml .gitignore src/__init__.py tests/__init__.py
git commit -m "chore: project scaffolding with dependencies and config"
```

---

### Task 2: Config Module

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
import os
import tempfile
import yaml
import pytest
from src.config import load_config


def test_load_config_returns_all_sections():
    """Config must contain csv_url, ibkr, data, reports, schedule sections."""
    config = load_config("config.yaml")
    assert "csv_url" in config
    assert "ibkr" in config
    assert "data" in config
    assert "reports" in config
    assert "schedule" in config


def test_load_config_ibkr_defaults():
    """IBKR config must have host, port, client_id, timeout."""
    config = load_config("config.yaml")
    assert config["ibkr"]["host"] == "127.0.0.1"
    assert isinstance(config["ibkr"]["port"], int)
    assert isinstance(config["ibkr"]["client_id"], int)


def test_load_config_missing_file_raises():
    """Loading a nonexistent config file should raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_config("nonexistent.yaml")


def test_load_config_custom_file():
    """Config should load from any valid YAML file."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump({
            "csv_url": "https://example.com/test.csv",
            "ibkr": {"host": "localhost", "port": 4002, "client_id": 2, "timeout": 10},
            "data": {"iv_history_db": "test.db", "price_period": "6mo"},
            "reports": {"output_dir": "test_reports", "log_dir": "test_logs"},
            "schedule": {"timezone": "UTC", "run_time": "12:00"},
        }, f)
        tmp_path = f.name
    try:
        config = load_config(tmp_path)
        assert config["csv_url"] == "https://example.com/test.csv"
        assert config["ibkr"]["port"] == 4002
    finally:
        os.unlink(tmp_path)
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.config'`

**Step 3: Write minimal implementation**

```python
# src/config.py
import os
import yaml


def load_config(path: str) -> dict:
    """Load configuration from a YAML file.

    Raises FileNotFoundError if the file does not exist.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r") as f:
        return yaml.safe_load(f)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: All 4 tests PASS

**Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add config module with YAML loading"
```

---

### Task 3: Data Loader (CSV Fetch & Clean)

**Files:**
- Create: `src/data_loader.py`
- Create: `tests/test_data_loader.py`

**Step 1: Write the failing tests**

```python
# tests/test_data_loader.py
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock
from src.data_loader import fetch_universe, clean_strike_price, classify_market


class TestCleanStrikePrice:
    def test_clean_numeric_string(self):
        assert clean_strike_price("150.50") == 150.50

    def test_clean_with_dollar_sign(self):
        assert clean_strike_price("$150.50") == 150.50

    def test_clean_with_chinese_chars(self):
        assert clean_strike_price("$150.50元") == 150.50

    def test_clean_empty_string(self):
        assert clean_strike_price("") is None

    def test_clean_none(self):
        assert clean_strike_price(None) is None

    def test_clean_pure_text(self):
        assert clean_strike_price("无目标") is None

    def test_clean_numeric_value(self):
        assert clean_strike_price(150.50) == 150.50


class TestClassifyMarket:
    def test_us_ticker(self):
        assert classify_market("AAPL") == "US"

    def test_hk_ticker(self):
        assert classify_market("0700.HK") == "HK"

    def test_shanghai_ticker(self):
        assert classify_market("600900.SS") == "CN"

    def test_shenzhen_ticker(self):
        assert classify_market("000001.SZ") == "CN"


class TestFetchUniverse:
    @patch("src.data_loader.pd.read_csv")
    def test_returns_ticker_list_and_target_buys(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": ["AAPL", "MSFT", "0700.HK"],
            "Strike (黄金位)": ["$150", "280.5", ""],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")

        assert tickers == ["AAPL", "MSFT", "0700.HK"]
        assert target_buys == {"AAPL": 150.0, "MSFT": 280.5}
        # 0700.HK has empty strike, so not in target_buys

    @patch("src.data_loader.pd.read_csv")
    def test_strips_whitespace_from_tickers(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": [" AAPL ", "MSFT"],
            "Strike (黄金位)": ["150", "280"],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.pd.read_csv")
    def test_skips_rows_with_empty_ticker(self, mock_read_csv):
        mock_df = pd.DataFrame({
            "代码": ["AAPL", "", None, "MSFT"],
            "Strike (黄金位)": ["150", "100", "200", "280"],
        })
        mock_read_csv.return_value = mock_df

        tickers, target_buys = fetch_universe("https://example.com/test.csv")
        assert tickers == ["AAPL", "MSFT"]

    @patch("src.data_loader.pd.read_csv")
    def test_csv_fetch_failure_raises(self, mock_read_csv):
        mock_read_csv.side_effect = Exception("Network error")
        with pytest.raises(Exception, match="Network error"):
            fetch_universe("https://example.com/test.csv")
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_loader.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/data_loader.py
import re
import pandas as pd
import logging

logger = logging.getLogger(__name__)


def clean_strike_price(value) -> float | None:
    """Clean strike price value: remove $, Chinese chars, convert to float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return None
    # Remove $ and any non-numeric chars except . and -
    cleaned = re.sub(r"[^\d.\-]", "", s)
    if not cleaned:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def classify_market(ticker: str) -> str:
    """Classify ticker into market: 'US', 'HK', or 'CN'."""
    ticker = ticker.upper()
    if ticker.endswith(".HK"):
        return "HK"
    if ticker.endswith(".SS") or ticker.endswith(".SZ"):
        return "CN"
    return "US"


def fetch_universe(csv_url: str) -> tuple[list[str], dict[str, float]]:
    """Fetch stock universe from Google Sheets CSV.

    Returns:
        tickers: List of all ticker symbols
        target_buys: Dict of {ticker: strike_price} for Sell Put scanning

    Raises on network/parse failure (no data = no scan).
    """
    df = pd.read_csv(csv_url)

    # Clean ticker column
    df["代码"] = df["代码"].astype(str).str.strip()
    df = df[df["代码"].notna() & (df["代码"] != "") & (df["代码"] != "nan")]

    tickers = df["代码"].tolist()

    # Build target buy list
    target_buys = {}
    if "Strike (黄金位)" in df.columns:
        for _, row in df.iterrows():
            ticker = row["代码"]
            strike = clean_strike_price(row.get("Strike (黄金位)"))
            if strike is not None:
                target_buys[ticker] = strike

    logger.info(f"Loaded {len(tickers)} tickers, {len(target_buys)} target buys")
    return tickers, target_buys
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_loader.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/data_loader.py tests/test_data_loader.py
git commit -m "feat: add data loader with CSV fetch and strike price cleaning"
```

---

### Task 4: Market Data Provider — Price & Indicators (yfinance)

**Files:**
- Create: `src/market_data.py`
- Create: `tests/test_market_data.py`

**Step 1: Write the failing tests**

```python
# tests/test_market_data.py
import pandas as pd
import numpy as np
import pytest
from datetime import date, datetime
from unittest.mock import patch, MagicMock, PropertyMock
from src.market_data import MarketDataProvider


@pytest.fixture
def provider_no_ibkr():
    """Provider with IBKR disabled (yfinance only)."""
    return MarketDataProvider(ibkr_config=None)


class TestGetPriceData:
    @patch("src.market_data.yf.download")
    def test_returns_ohlcv_dataframe(self, mock_download, provider_no_ibkr):
        dates = pd.date_range("2025-01-01", periods=5, freq="B")
        mock_df = pd.DataFrame({
            "Open": [100, 101, 102, 103, 104],
            "High": [105, 106, 107, 108, 109],
            "Low": [95, 96, 97, 98, 99],
            "Close": [102, 103, 104, 105, 106],
            "Volume": [1000, 1100, 1200, 1300, 1400],
        }, index=dates)
        mock_download.return_value = mock_df

        result = provider_no_ibkr.get_price_data("AAPL", period="1y")
        assert "Close" in result.columns
        assert len(result) == 5

    @patch("src.market_data.yf.download")
    def test_empty_data_returns_empty_df(self, mock_download, provider_no_ibkr):
        mock_download.return_value = pd.DataFrame()
        result = provider_no_ibkr.get_price_data("INVALID", period="1y")
        assert result.empty


class TestGetEarningsDate:
    @patch("src.market_data.yf.Ticker")
    def test_returns_next_earnings_date(self, mock_ticker_cls, provider_no_ibkr):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {"Earnings Date": [datetime(2026, 4, 25)]}
        mock_ticker_cls.return_value = mock_ticker

        result = provider_no_ibkr.get_earnings_date("AAPL")
        assert result == date(2026, 4, 25)

    @patch("src.market_data.yf.Ticker")
    def test_no_earnings_returns_none(self, mock_ticker_cls, provider_no_ibkr):
        mock_ticker = MagicMock()
        mock_ticker.calendar = {}
        mock_ticker_cls.return_value = mock_ticker

        result = provider_no_ibkr.get_earnings_date("AAPL")
        assert result is None


class TestClassifyAndSkip:
    def test_should_skip_options_cn_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("600900.SS") is True

    def test_should_not_skip_options_us_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("AAPL") is False

    def test_should_not_skip_options_hk_ticker(self, provider_no_ibkr):
        assert provider_no_ibkr.should_skip_options("0700.HK") is False
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_market_data.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/market_data.py
import logging
from datetime import date, datetime
import pandas as pd
import yfinance as yf
from src.data_loader import classify_market

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Hybrid IBKR/yfinance market data provider."""

    def __init__(self, ibkr_config: dict | None = None):
        self.ibkr = None
        self.ibkr_config = ibkr_config
        if ibkr_config:
            self.ibkr = self._try_connect_ibkr(ibkr_config)

    def _try_connect_ibkr(self, config: dict):
        """Attempt IBKR connection. Returns IB instance or None."""
        try:
            from ib_insync import IB
            ib = IB()
            ib.connect(
                config["host"],
                config["port"],
                clientId=config["client_id"],
                timeout=config.get("timeout", 30),
            )
            logger.info("Connected to IBKR Gateway")
            return ib
        except Exception as e:
            logger.warning(f"IBKR connection failed, using yfinance fallback: {e}")
            return None

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch OHLCV price data. IBKR first, yfinance fallback."""
        # TODO: IBKR implementation in future task
        return self._yf_price_data(ticker, period)

    def _yf_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch price data from yfinance."""
        try:
            df = yf.download(ticker, period=period, progress=False)
            if df.empty:
                logger.warning(f"No price data for {ticker}")
            return df
        except Exception as e:
            logger.error(f"yfinance price fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_weekly_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch weekly OHLCV data for weekly MA calculation."""
        try:
            df = yf.download(ticker, period=period, interval="1wk", progress=False)
            return df
        except Exception as e:
            logger.error(f"yfinance weekly data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_earnings_date(self, ticker: str) -> date | None:
        """Fetch next earnings date. yfinance primary."""
        try:
            t = yf.Ticker(ticker)
            cal = t.calendar
            if isinstance(cal, dict) and "Earnings Date" in cal:
                dates = cal["Earnings Date"]
                if dates:
                    dt = dates[0]
                    if isinstance(dt, datetime):
                        return dt.date()
                    if isinstance(dt, date):
                        return dt
            return None
        except Exception as e:
            logger.warning(f"Earnings date fetch failed for {ticker}: {e}")
            return None

    def should_skip_options(self, ticker: str) -> bool:
        """Return True if options data should be skipped for this ticker."""
        return classify_market(ticker) == "CN"

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options chain filtered by DTE range.

        Returns DataFrame with columns: strike, bid, dte, expiration, impliedVolatility
        """
        if self.should_skip_options(ticker):
            return pd.DataFrame()
        # TODO: IBKR implementation
        return self._yf_options_chain(ticker, dte_min, dte_max)

    def _yf_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        """Fetch put options from yfinance, filtered by DTE."""
        try:
            t = yf.Ticker(ticker)
            expirations = t.options  # list of date strings
            if not expirations:
                return pd.DataFrame()

            today = date.today()
            results = []
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                if dte_min <= dte <= dte_max:
                    chain = t.option_chain(exp_str)
                    puts = chain.puts[["strike", "bid", "impliedVolatility"]].copy()
                    puts["dte"] = dte
                    puts["expiration"] = exp_date
                    results.append(puts)

            if not results:
                return pd.DataFrame()
            return pd.concat(results, ignore_index=True)
        except Exception as e:
            logger.warning(f"Options chain fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_iv_rank(self, ticker: str) -> float | None:
        """Get IV Rank (0-100). IBKR direct, yfinance via ATM IV + history."""
        if self.should_skip_options(ticker):
            return None
        # TODO: IBKR direct IV rank
        # TODO: yfinance ATM IV + SQLite history
        # Placeholder — will be implemented with IV history storage
        return None

    def disconnect(self):
        """Disconnect from IBKR if connected."""
        if self.ibkr:
            self.ibkr.disconnect()
            logger.info("Disconnected from IBKR")
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_market_data.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add market data provider with yfinance price, earnings, options"
```

---

### Task 5: Data Engine — Indicator Computation

**Files:**
- Create: `src/data_engine.py`
- Create: `tests/test_data_engine.py`

**Step 1: Write the failing tests**

```python
# tests/test_data_engine.py
import pandas as pd
import numpy as np
import pytest
from datetime import date
from dataclasses import dataclass
from unittest.mock import MagicMock, patch
from src.data_engine import TickerData, compute_sma, compute_rsi, build_ticker_data


class TestComputeSMA:
    def test_sma_basic(self):
        prices = pd.Series([1, 2, 3, 4, 5])
        assert compute_sma(prices, 3) == pytest.approx(4.0)  # (3+4+5)/3

    def test_sma_insufficient_data(self):
        prices = pd.Series([1, 2])
        assert compute_sma(prices, 200) is None

    def test_sma_empty_series(self):
        assert compute_sma(pd.Series(dtype=float), 200) is None


class TestComputeRSI:
    def test_rsi_all_gains(self):
        prices = pd.Series(range(1, 20))  # steadily rising
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi > 90  # should be near 100

    def test_rsi_all_losses(self):
        prices = pd.Series(range(20, 1, -1))  # steadily falling
        rsi = compute_rsi(prices, 14)
        assert rsi is not None
        assert rsi < 10  # should be near 0

    def test_rsi_insufficient_data(self):
        prices = pd.Series([1, 2, 3])
        assert compute_rsi(prices, 14) is None


class TestBuildTickerData:
    @patch("src.data_engine.MarketDataProvider")
    def test_builds_complete_ticker_data(self, MockProvider):
        provider = MockProvider()

        # Mock daily price data — 250 days
        dates = pd.date_range("2025-03-01", periods=250, freq="B")
        close_prices = np.linspace(100, 200, 250)
        daily_df = pd.DataFrame({"Close": close_prices}, index=dates)
        provider.get_price_data.return_value = daily_df

        # Mock weekly price data — 60 weeks
        weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
        weekly_close = np.linspace(90, 190, 60)
        weekly_df = pd.DataFrame({"Close": weekly_close}, index=weekly_dates)
        provider.get_weekly_price_data.return_value = weekly_df

        # Mock earnings
        provider.get_earnings_date.return_value = date(2026, 4, 25)
        provider.get_iv_rank.return_value = 15.0

        result = build_ticker_data("AAPL", provider, reference_date=date(2026, 2, 20))

        assert result is not None
        assert result.ticker == "AAPL"
        assert result.market == "US"
        assert result.last_price == pytest.approx(close_prices[-1])
        assert result.ma200 is not None
        assert result.ma50w is not None
        assert result.rsi14 is not None
        assert result.iv_rank == 15.0
        assert result.earnings_date == date(2026, 4, 25)
        assert result.days_to_earnings == 64

    @patch("src.data_engine.MarketDataProvider")
    def test_empty_price_data_returns_none(self, MockProvider):
        provider = MockProvider()
        provider.get_price_data.return_value = pd.DataFrame()

        result = build_ticker_data("INVALID", provider)
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/data_engine.py
import logging
from dataclasses import dataclass
from datetime import date
import pandas as pd
import numpy as np
from src.data_loader import classify_market
from src.market_data import MarketDataProvider

logger = logging.getLogger(__name__)


@dataclass
class TickerData:
    ticker: str
    name: str
    market: str              # "US" | "HK" | "CN"
    last_price: float
    ma200: float | None
    ma50w: float | None
    rsi14: float | None
    iv_rank: float | None
    prev_close: float
    earnings_date: date | None
    days_to_earnings: int | None


def compute_sma(prices: pd.Series, window: int) -> float | None:
    """Compute Simple Moving Average. Returns None if insufficient data."""
    if len(prices) < window:
        return None
    return float(prices.iloc[-window:].mean())


def compute_rsi(prices: pd.Series, period: int = 14) -> float | None:
    """Compute RSI-14 from a price series. Returns None if insufficient data."""
    if len(prices) < period + 1:
        return None
    deltas = prices.diff().dropna()
    gains = deltas.clip(lower=0)
    losses = (-deltas.clip(upper=0))

    avg_gain = gains.iloc[:period].mean()
    avg_loss = losses.iloc[:period].mean()

    # Smoothed RSI (Wilder's method)
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains.iloc[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses.iloc[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100 - (100 / (1 + rs)))


def build_ticker_data(
    ticker: str,
    provider: MarketDataProvider,
    reference_date: date | None = None,
) -> TickerData | None:
    """Build TickerData for a single ticker. Returns None on failure."""
    if reference_date is None:
        reference_date = date.today()

    # Fetch daily price data
    daily_df = provider.get_price_data(ticker, period="1y")
    if daily_df.empty:
        logger.warning(f"No daily data for {ticker}, skipping")
        return None

    close = daily_df["Close"]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]

    last_price = float(close.iloc[-1])
    prev_close = float(close.iloc[-2]) if len(close) >= 2 else last_price

    # Daily SMA 200
    ma200 = compute_sma(close, 200)

    # RSI-14
    rsi14 = compute_rsi(close, 14)

    # Weekly SMA 50
    weekly_df = provider.get_weekly_price_data(ticker, period="1y")
    ma50w = None
    if not weekly_df.empty:
        weekly_close = weekly_df["Close"]
        if isinstance(weekly_close, pd.DataFrame):
            weekly_close = weekly_close.iloc[:, 0]
        ma50w = compute_sma(weekly_close, 50)

    # IV Rank
    iv_rank = provider.get_iv_rank(ticker)

    # Earnings date
    earnings_date = provider.get_earnings_date(ticker)
    days_to_earnings = None
    if earnings_date:
        days_to_earnings = (earnings_date - reference_date).days
        if days_to_earnings < 0:
            days_to_earnings = None
            earnings_date = None

    market = classify_market(ticker)

    return TickerData(
        ticker=ticker,
        name=ticker,  # yfinance doesn't always provide name reliably
        market=market,
        last_price=last_price,
        ma200=ma200,
        ma50w=ma50w,
        rsi14=rsi14,
        iv_rank=iv_rank,
        prev_close=prev_close,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
    )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_engine.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/data_engine.py tests/test_data_engine.py
git commit -m "feat: add data engine with SMA, RSI, and TickerData builder"
```

---

### Task 6: Scanner Modules 2-4 (IV Extremes, MA200 Cross, LEAPS)

**Files:**
- Create: `src/scanners.py`
- Create: `tests/test_scanners.py`

**Step 1: Write the failing tests**

```python
# tests/test_scanners.py
import pytest
from datetime import date
from src.data_engine import TickerData
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup


def make_ticker(**kwargs) -> TickerData:
    """Helper to create TickerData with sensible defaults."""
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestIVExtremes:
    def test_low_iv_detected(self):
        data = [make_ticker(ticker="LOW", iv_rank=15.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 1
        assert low[0].ticker == "LOW"
        assert len(high) == 0

    def test_high_iv_detected(self):
        data = [make_ticker(ticker="HIGH", iv_rank=85.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 1

    def test_normal_iv_not_included(self):
        data = [make_ticker(ticker="NORMAL", iv_rank=50.0)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0

    def test_none_iv_skipped(self):
        data = [make_ticker(ticker="NOIV", iv_rank=None)]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0

    def test_boundary_values(self):
        data = [
            make_ticker(ticker="EXACT20", iv_rank=20.0),  # NOT < 20
            make_ticker(ticker="EXACT80", iv_rank=80.0),  # NOT > 80
        ]
        low, high = scan_iv_extremes(data)
        assert len(low) == 0
        assert len(high) == 0


class TestMA200Crossover:
    def test_bullish_cross(self):
        # prev_close below MA200, current above
        data = [make_ticker(ticker="BULL", last_price=101.0, ma200=100.0, prev_close=99.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 1
        assert bullish[0].ticker == "BULL"

    def test_bearish_cross(self):
        # prev_close above MA200, current below
        data = [make_ticker(ticker="BEAR", last_price=99.0, ma200=100.0, prev_close=101.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bearish) == 1

    def test_just_above_within_1pct(self):
        # Price just crossed above MA200 (within 1%)
        data = [make_ticker(ticker="NEAR", last_price=100.5, ma200=100.0, prev_close=100.2)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 1

    def test_no_cross(self):
        # Both above MA200, not near it
        data = [make_ticker(ticker="ABOVE", last_price=110.0, ma200=100.0, prev_close=109.0)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 0
        assert len(bearish) == 0

    def test_none_ma200_skipped(self):
        data = [make_ticker(ticker="NOMA", ma200=None)]
        bullish, bearish = scan_ma200_crossover(data)
        assert len(bullish) == 0
        assert len(bearish) == 0


class TestLEAPSSetup:
    def test_all_conditions_met(self):
        data = [make_ticker(
            ticker="LEAPS",
            last_price=100.0,  # > ma200 (95)
            ma200=95.0,
            ma50w=98.0,        # within 3% of last_price
            rsi14=40.0,        # <= 45
            iv_rank=25.0,      # < 30
        )]
        result = scan_leaps_setup(data)
        assert len(result) == 1

    def test_price_below_ma200_fails(self):
        data = [make_ticker(last_price=90.0, ma200=95.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_too_far_from_ma50w_fails(self):
        data = [make_ticker(last_price=100.0, ma50w=90.0)]  # 11% away
        assert len(scan_leaps_setup(data)) == 0

    def test_rsi_too_high_fails(self):
        data = [make_ticker(rsi14=50.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_iv_rank_too_high_fails(self):
        data = [make_ticker(iv_rank=35.0)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_iv_rank_skipped(self):
        data = [make_ticker(iv_rank=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_ma200_skipped(self):
        data = [make_ticker(ma200=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_ma50w_skipped(self):
        data = [make_ticker(ma50w=None)]
        assert len(scan_leaps_setup(data)) == 0

    def test_none_rsi_skipped(self):
        data = [make_ticker(rsi14=None)]
        assert len(scan_leaps_setup(data)) == 0
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scanners.py -v`
Expected: FAIL — `ImportError`

**Step 3: Write minimal implementation**

```python
# src/scanners.py
from src.data_engine import TickerData


def scan_iv_extremes(data: list[TickerData]) -> tuple[list[TickerData], list[TickerData]]:
    """Module 2: Find tickers with extreme IV Rank.

    Returns (low_iv_list, high_iv_list).
    """
    low = [t for t in data if t.iv_rank is not None and t.iv_rank < 20]
    high = [t for t in data if t.iv_rank is not None and t.iv_rank > 80]
    return low, high


def scan_ma200_crossover(data: list[TickerData]) -> tuple[list[TickerData], list[TickerData]]:
    """Module 3: Detect MA200 crossover signals.

    Bullish: prev_close < MA200 and last_price > MA200 (or within +1% above MA200).
    Bearish: prev_close > MA200 and last_price < MA200 (or within -1% below MA200).

    Returns (bullish_list, bearish_list).
    """
    bullish = []
    bearish = []
    for t in data:
        if t.ma200 is None:
            continue
        pct_above = (t.last_price - t.ma200) / t.ma200

        # Bullish cross: was below, now above
        if t.prev_close < t.ma200 and t.last_price > t.ma200:
            bullish.append(t)
        # Just crossed above (within 1% above and not a clear prior position)
        elif 0 < pct_above <= 0.01 and t.prev_close <= t.ma200:
            bullish.append(t)
        # Bearish cross: was above, now below
        elif t.prev_close > t.ma200 and t.last_price < t.ma200:
            bearish.append(t)
        # Just crossed below (within 1% below)
        elif -0.01 <= pct_above < 0 and t.prev_close >= t.ma200:
            bearish.append(t)

    return bullish, bearish


def scan_leaps_setup(data: list[TickerData]) -> list[TickerData]:
    """Module 4: V1.9 LEAPS Setup — all 4 conditions must be met.

    1. last_price > MA200
    2. last_price within ±3% of weekly MA50
    3. RSI-14 <= 45
    4. IV Rank < 30%
    """
    results = []
    for t in data:
        if t.ma200 is None or t.ma50w is None or t.rsi14 is None or t.iv_rank is None:
            continue
        if t.last_price <= t.ma200:
            continue
        if abs(t.last_price - t.ma50w) / t.ma50w > 0.03:
            continue
        if t.rsi14 > 45:
            continue
        if t.iv_rank >= 30:
            continue
        results.append(t)
    return results
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scanners.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add scanner modules for IV extremes, MA200 crossover, LEAPS setup"
```

---

### Task 7: Scanner Module 5 — Sell Put Scanner

**Files:**
- Modify: `src/scanners.py`
- Modify: `tests/test_scanners.py`

**Step 1: Write the failing tests**

Append to `tests/test_scanners.py`:

```python
from src.scanners import scan_sell_put, SellPutSignal


class TestSellPutScanner:
    def test_basic_signal(self):
        ticker_data = make_ticker(
            ticker="AAPL",
            earnings_date=date(2026, 6, 1),  # far away
            days_to_earnings=101,
        )
        options_df = pd.DataFrame({
            "strike": [145.0, 150.0, 155.0],
            "bid": [1.5, 2.0, 3.0],
            "dte": [50, 50, 50],
            "expiration": [date(2026, 4, 11)] * 3,
            "impliedVolatility": [0.3, 0.3, 0.3],
        })
        result = scan_sell_put(
            ticker_data=ticker_data,
            target_strike=150.0,
            options_df=options_df,
        )
        assert result is not None
        assert result.strike == 150.0
        assert result.bid == 2.0
        assert result.apy == pytest.approx((2.0 / 150.0) * (365 / 50) * 100, rel=1e-2)
        assert result.earnings_risk is False

    def test_earnings_within_dte_flags_risk(self):
        ticker_data = make_ticker(
            ticker="AAPL",
            earnings_date=date(2026, 3, 15),
            days_to_earnings=23,
        )
        options_df = pd.DataFrame({
            "strike": [150.0],
            "bid": [3.0],
            "dte": [50],
            "expiration": [date(2026, 4, 11)],
            "impliedVolatility": [0.3],
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is not None
        assert result.earnings_risk is True

    def test_apy_below_threshold_returns_none(self):
        ticker_data = make_ticker(ticker="AAPL")
        options_df = pd.DataFrame({
            "strike": [150.0],
            "bid": [0.10],  # very low bid → low APY
            "dte": [50],
            "expiration": [date(2026, 4, 11)],
            "impliedVolatility": [0.1],
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is None

    def test_closest_strike_below_target(self):
        ticker_data = make_ticker(ticker="AAPL")
        options_df = pd.DataFrame({
            "strike": [145.0, 148.0, 152.0, 155.0],
            "bid": [3.0, 2.5, 2.0, 1.5],
            "dte": [50, 50, 50, 50],
            "expiration": [date(2026, 4, 11)] * 4,
            "impliedVolatility": [0.3] * 4,
        })
        result = scan_sell_put(ticker_data, 150.0, options_df)
        assert result is not None
        assert result.strike == 148.0  # closest ≤ target

    def test_empty_options_returns_none(self):
        ticker_data = make_ticker(ticker="AAPL")
        result = scan_sell_put(ticker_data, 150.0, pd.DataFrame())
        assert result is None
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scanners.py::TestSellPutScanner -v`
Expected: FAIL — `ImportError: cannot import name 'scan_sell_put'`

**Step 3: Write minimal implementation**

Add to `src/scanners.py`:

```python
from dataclasses import dataclass
from datetime import date
import pandas as pd

@dataclass
class SellPutSignal:
    ticker: str
    strike: float
    bid: float
    dte: int
    expiration: date
    apy: float           # percentage, e.g. 9.6
    earnings_risk: bool   # True if earnings falls within DTE


def scan_sell_put(
    ticker_data: TickerData,
    target_strike: float,
    options_df: pd.DataFrame,
    min_apy: float = 4.0,
) -> SellPutSignal | None:
    """Module 5: Sell Put scanner for a single ticker.

    Finds the put option with strike closest to (and ≤) target_strike.
    Returns SellPutSignal if APY >= min_apy, else None.
    """
    if options_df.empty:
        return None

    # Filter to strikes ≤ target
    eligible = options_df[options_df["strike"] <= target_strike].copy()
    if eligible.empty:
        return None

    # Find closest strike to target (from below)
    eligible = eligible.sort_values("strike", ascending=False)
    best = eligible.iloc[0]

    strike = float(best["strike"])
    bid = float(best["bid"])
    dte = int(best["dte"])
    expiration = best["expiration"]

    if strike == 0 or dte == 0:
        return None

    apy = (bid / strike) * (365 / dte) * 100

    if apy < min_apy:
        return None

    # Check earnings risk
    earnings_risk = False
    if ticker_data.earnings_date and ticker_data.days_to_earnings is not None:
        if ticker_data.days_to_earnings <= dte:
            earnings_risk = True

    return SellPutSignal(
        ticker=ticker_data.ticker,
        strike=strike,
        bid=bid,
        dte=dte,
        expiration=expiration if isinstance(expiration, date) else expiration,
        apy=round(apy, 2),
        earnings_risk=earnings_risk,
    )
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scanners.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/scanners.py tests/test_scanners.py
git commit -m "feat: add Sell Put scanner module with APY calc and earnings risk"
```

---

### Task 8: Report Formatter

**Files:**
- Create: `src/report.py`
- Create: `tests/test_report.py`

**Step 1: Write the failing tests**

```python
# tests/test_report.py
import pytest
from datetime import date
from src.data_engine import TickerData
from src.scanners import SellPutSignal
from src.report import format_report, format_earnings_tag


def make_ticker(**kwargs) -> TickerData:
    defaults = dict(
        ticker="TEST", name="Test", market="US",
        last_price=100.0, ma200=95.0, ma50w=98.0,
        rsi14=40.0, iv_rank=25.0, prev_close=99.0,
        earnings_date=date(2026, 4, 25), days_to_earnings=64,
    )
    defaults.update(kwargs)
    return TickerData(**defaults)


class TestFormatEarningsTag:
    def test_with_date(self):
        tag = format_earnings_tag(date(2026, 4, 25), 64)
        assert "2026-04-25" in tag
        assert "64d" in tag

    def test_without_date(self):
        tag = format_earnings_tag(None, None)
        assert "N/A" in tag


class TestFormatReport:
    def test_report_contains_header(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="IBKR Gateway",
            universe_count=42,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[],
            errors_count=0,
            elapsed_seconds=12.5,
        )
        assert "V1.9 QUANT RADAR" in report
        assert "2026-02-20" in report
        assert "42" in report

    def test_report_contains_iv_extremes(self):
        low = [make_ticker(ticker="AAPL", iv_rank=12.3)]
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=low, iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            errors_count=0, elapsed_seconds=5.0,
        )
        assert "AAPL" in report
        assert "12.3" in report
        assert "IV EXTREMES" in report

    def test_report_contains_sell_put_warning(self):
        signal = SellPutSignal(
            ticker="NVDA", strike=110.0, bid=1.80,
            dte=52, expiration=date(2026, 4, 13),
            apy=11.5, earnings_risk=True,
        )
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[],
            sell_puts=[(signal, make_ticker(ticker="NVDA"))],
            errors_count=0, elapsed_seconds=5.0,
        )
        assert "NVDA" in report
        assert "🚨" in report

    def test_empty_modules_show_none(self):
        report = format_report(
            scan_date=date(2026, 2, 20),
            data_source="yfinance",
            universe_count=10,
            iv_low=[], iv_high=[],
            ma200_bullish=[], ma200_bearish=[],
            leaps=[], sell_puts=[],
            errors_count=0, elapsed_seconds=5.0,
        )
        assert "(none)" in report.lower() or "no tickers" in report.lower()
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Write minimal implementation**

```python
# src/report.py
from datetime import date
from src.data_engine import TickerData
from src.scanners import SellPutSignal


def format_earnings_tag(earnings_date: date | None, days: int | None) -> str:
    if earnings_date and days is not None:
        return f"Earnings: {earnings_date} ({days}d)"
    return "Earnings: N/A"


def format_report(
    scan_date: date,
    data_source: str,
    universe_count: int,
    iv_low: list[TickerData],
    iv_high: list[TickerData],
    ma200_bullish: list[TickerData],
    ma200_bearish: list[TickerData],
    leaps: list[TickerData],
    sell_puts: list[tuple[SellPutSignal, TickerData]],
    errors_count: int,
    elapsed_seconds: float,
) -> str:
    lines = []
    sep = "=" * 55

    # Header
    day_name = scan_date.strftime("%a")
    lines.append(sep)
    lines.append(f"  V1.9 QUANT RADAR — {scan_date} ({day_name})")
    lines.append(f"  Data Source: {data_source} | Universe: {universe_count} tickers")
    lines.append(sep)
    lines.append("")

    # Module 2: IV Extremes
    lines.append("── MODULE 2: IV EXTREMES ──────────────────────────")
    lines.append("")
    lines.append("▼ LOW IV (IV Rank < 20%)")
    if iv_low:
        for t in iv_low:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("▲ HIGH IV (IV Rank > 80%)")
    if iv_high:
        for t in iv_high:
            lines.append(f"  {t.ticker:<8} IV Rank: {t.iv_rank:5.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Module 3: MA200 Crossover
    lines.append("── MODULE 3: MA200 CROSSOVER ──────────────────────")
    lines.append("")
    lines.append("↑ BULLISH CROSS (Price > MA200)")
    if ma200_bullish:
        for t in ma200_bullish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")
    lines.append("↓ BEARISH CROSS (Price < MA200)")
    if ma200_bearish:
        for t in ma200_bearish:
            pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f} ({pct:+.2f}%)")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Module 4: LEAPS Setup
    lines.append("── MODULE 4: LEAPS SETUP (V1.9 共振) ─────────────")
    lines.append("")
    if leaps:
        for t in leaps:
            ma50w_pct = ((t.last_price - t.ma50w) / t.ma50w * 100) if t.ma50w else 0
            lines.append(f"  {t.ticker:<8} Price: ${t.last_price:.2f}  MA200: ${t.ma200:.2f}  MA50w: ${t.ma50w:.2f} ({ma50w_pct:+.1f}%)")
            lines.append(f"          RSI: {t.rsi14:.1f}  IV Rank: {t.iv_rank:.1f}%  │ {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
    else:
        lines.append("  (no tickers meet all 4 conditions)")
    lines.append("")

    # Module 5: Sell Put
    lines.append("── MODULE 5: SELL PUT SCANNER ─────────────────────")
    lines.append("")
    if sell_puts:
        for signal, t in sell_puts:
            lines.append(f"  {signal.ticker:<8} Strike: ${signal.strike:.0f}  DTE: {signal.dte}  Bid: ${signal.bid:.2f}  APY: {signal.apy:.1f}%")
            lines.append(f"          {format_earnings_tag(t.earnings_date, t.days_to_earnings)}")
            if signal.earnings_risk:
                lines.append(f"          🚨 WARNING: Earnings falls within DTE window — gap risk")
    else:
        lines.append("  (none)")
    lines.append("")

    # Footer
    lines.append(sep)
    lines.append(f"  Scan completed in {elapsed_seconds:.1f}s │ Errors: {errors_count} tickers skipped")
    lines.append(sep)

    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add src/report.py tests/test_report.py
git commit -m "feat: add report formatter with clean text output"
```

---

### Task 9: Main Orchestrator

**Files:**
- Create: `src/main.py`
- Create: `src/email_stub.py`

**Step 1: Write email stub (no test needed — it's a placeholder)**

```python
# src/email_stub.py
import logging

logger = logging.getLogger(__name__)


def send_email(report_text: str, config: dict | None = None):
    """Send report via email.

    TODO: Implement with smtplib when ready.

    Usage:
        import smtplib
        from email.mime.text import MIMEText

        msg = MIMEText(report_text)
        msg['Subject'] = 'V1.9 Quant Radar Report'
        msg['From'] = config['email']['from']
        msg['To'] = config['email']['to']

        with smtplib.SMTP(config['email']['smtp_host'], config['email']['smtp_port']) as server:
            server.starttls()
            server.login(config['email']['username'], config['email']['password'])
            server.send_message(msg)
    """
    logger.info("Email sending not configured. Report printed to stdout only.")
```

**Step 2: Write main orchestrator**

```python
# src/main.py
import os
import sys
import time
import logging
from datetime import date, datetime

from src.config import load_config
from src.data_loader import fetch_universe
from src.market_data import MarketDataProvider
from src.data_engine import TickerData, build_ticker_data
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put
from src.report import format_report
from src.email_stub import send_email

logger = logging.getLogger(__name__)


def setup_logging(log_dir: str):
    """Configure logging to file and stderr."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"radar_{date.today()}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


def run_scan(config_path: str = "config.yaml"):
    """Main scan orchestration."""
    start_time = time.time()
    config = load_config(config_path)

    setup_logging(config["reports"]["log_dir"])
    logger.info("V1.9 Quant Radar starting")

    # Step 1: Load universe
    logger.info("Fetching universe from CSV...")
    tickers, target_buys = fetch_universe(config["csv_url"])
    logger.info(f"Universe: {len(tickers)} tickers, {len(target_buys)} target buys")

    # Step 2: Connect to market data
    provider = MarketDataProvider(ibkr_config=config.get("ibkr"))
    data_source = "IBKR Gateway" if provider.ibkr else "yfinance"

    # Step 3: Build ticker data
    all_data: list[TickerData] = []
    errors_count = 0
    today = date.today()

    for ticker in tickers:
        try:
            td = build_ticker_data(ticker, provider, reference_date=today)
            if td:
                all_data.append(td)
            else:
                errors_count += 1
        except Exception as e:
            logger.error(f"Failed to process {ticker}: {e}")
            errors_count += 1

    logger.info(f"Processed {len(all_data)} tickers, {errors_count} errors")

    # Step 4: Run scanners
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Module 5: Sell Put
    sell_put_results = []
    for td in all_data:
        if td.ticker in target_buys and not provider.should_skip_options(td.ticker):
            try:
                options_df = provider.get_options_chain(td.ticker)
                if not options_df.empty:
                    signal = scan_sell_put(td, target_buys[td.ticker], options_df)
                    if signal:
                        sell_put_results.append((signal, td))
            except Exception as e:
                logger.error(f"Sell Put scan failed for {td.ticker}: {e}")

    # Step 5: Generate report
    elapsed = time.time() - start_time
    report = format_report(
        scan_date=today,
        data_source=data_source,
        universe_count=len(tickers),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_put_results,
        errors_count=errors_count,
        elapsed_seconds=elapsed,
    )

    # Step 6: Output
    print(report)

    # Save to file
    reports_dir = config["reports"]["output_dir"]
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"{today}_radar.txt")
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report saved: {report_path}")

    # Email stub
    send_email(report, config)

    # Cleanup
    provider.disconnect()
    logger.info(f"Scan completed in {elapsed:.1f}s")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_scan(config_file)
```

**Step 3: Verify it imports correctly**

Run: `python -c "from src.main import run_scan; print('OK')"`
Expected: `OK`

**Step 4: Commit**

```bash
git add src/main.py src/email_stub.py
git commit -m "feat: add main orchestrator and email stub"
```

---

### Task 10: Docker Setup

**Files:**
- Create: `Dockerfile`
- Create: `docker-compose.yml`

**Step 1: Create Dockerfile**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config.yaml .

# Create runtime directories
RUN mkdir -p data reports logs

CMD ["python", "-m", "src.main"]
```

**Step 2: Create docker-compose.yml**

```yaml
version: "3.8"

services:
  radar:
    build: .
    volumes:
      - ./config.yaml:/app/config.yaml:ro
      - ./data:/app/data
      - ./reports:/app/reports
      - ./logs:/app/logs
    network_mode: host  # needed to reach IBKR Gateway on localhost
    restart: "no"
```

**Step 3: Verify Docker build**

Run: `docker build -t quant-radar .`
Expected: Build succeeds

**Step 4: Commit**

```bash
git add Dockerfile docker-compose.yml
git commit -m "feat: add Docker setup for containerized deployment"
```

---

### Task 11: Integration Smoke Test

**Files:**
- Create: `tests/test_integration.py`

**Step 1: Write integration test (mocked external services)**

```python
# tests/test_integration.py
"""Integration test: full scan pipeline with mocked data sources."""
import pytest
import pandas as pd
import numpy as np
from datetime import date, datetime
from unittest.mock import patch, MagicMock
from src.data_engine import build_ticker_data
from src.market_data import MarketDataProvider
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put
from src.report import format_report


@pytest.fixture
def mock_provider():
    provider = MagicMock(spec=MarketDataProvider)
    provider.ibkr = None

    # Generate realistic daily data (250 trading days)
    dates = pd.date_range("2025-03-01", periods=250, freq="B")
    close = np.concatenate([
        np.linspace(100, 180, 200),  # uptrend
        np.linspace(180, 170, 50),   # pullback
    ])
    daily_df = pd.DataFrame({"Close": close}, index=dates)
    provider.get_price_data.return_value = daily_df

    # Weekly data
    weekly_dates = pd.date_range("2025-01-01", periods=60, freq="W")
    weekly_close = np.linspace(95, 172, 60)
    weekly_df = pd.DataFrame({"Close": weekly_close}, index=weekly_dates)
    provider.get_weekly_price_data.return_value = weekly_df

    provider.get_earnings_date.return_value = date(2026, 4, 25)
    provider.get_iv_rank.return_value = 18.0
    provider.should_skip_options.return_value = False

    return provider


def test_full_pipeline(mock_provider):
    """Test complete scan pipeline from data to report."""
    # Build ticker data
    td = build_ticker_data("AAPL", mock_provider, reference_date=date(2026, 2, 20))
    assert td is not None
    assert td.ticker == "AAPL"

    # Run scanners
    all_data = [td]
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Generate report (should not crash)
    report = format_report(
        scan_date=date(2026, 2, 20),
        data_source="mock",
        universe_count=1,
        iv_low=iv_low, iv_high=iv_high,
        ma200_bullish=ma200_bull, ma200_bearish=ma200_bear,
        leaps=leaps, sell_puts=[],
        errors_count=0, elapsed_seconds=1.0,
    )
    assert "V1.9 QUANT RADAR" in report
    assert "AAPL" in report or "(none)" in report
```

**Step 2: Run integration test**

Run: `python -m pytest tests/test_integration.py -v`
Expected: PASS

**Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests PASS

**Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "test: add integration smoke test for full pipeline"
```

---

### Task 12: IV Rank with SQLite History (yfinance fallback)

**Files:**
- Create: `src/iv_store.py`
- Create: `tests/test_iv_store.py`
- Modify: `src/market_data.py` — wire up `get_iv_rank` to use IV store

**Step 1: Write the failing tests**

```python
# tests/test_iv_store.py
import os
import tempfile
import pytest
from datetime import date
from src.iv_store import IVStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = IVStore(path)
    yield s
    s.close()
    os.unlink(path)


class TestIVStore:
    def test_store_and_retrieve(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        store.save_iv("AAPL", date(2026, 1, 2), 0.30)
        history = store.get_iv_history("AAPL", days=365)
        assert len(history) == 2

    def test_iv_rank_insufficient_data(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        rank = store.compute_iv_rank("AAPL", current_iv=0.25)
        assert rank is None  # need at least 20 data points

    def test_iv_rank_calculation(self, store):
        # Store 30 days of IV data ranging from 0.20 to 0.50
        for i in range(30):
            iv = 0.20 + (i * 0.01)
            store.save_iv("AAPL", date(2026, 1, 1 + i) if i < 28 else date(2026, 2, i - 27), iv)

        # Current IV = 0.35, min=0.20, max=0.49
        # IV Rank = (0.35 - 0.20) / (0.49 - 0.20) = 0.5172...
        rank = store.compute_iv_rank("AAPL", current_iv=0.35)
        assert rank is not None
        assert 50 < rank < 55

    def test_duplicate_date_updates(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        store.save_iv("AAPL", date(2026, 1, 1), 0.30)  # update
        history = store.get_iv_history("AAPL", days=365)
        assert len(history) == 1
        assert history[0][1] == 0.30
```

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_iv_store.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# src/iv_store.py
import sqlite3
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)


class IVStore:
    """SQLite store for daily IV snapshots, used to compute IV Rank."""

    MIN_DATA_POINTS = 20  # minimum history needed for IV Rank

    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._create_table()

    def _create_table(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS iv_history (
                ticker TEXT NOT NULL,
                date TEXT NOT NULL,
                iv REAL NOT NULL,
                PRIMARY KEY (ticker, date)
            )
        """)
        self.conn.commit()

    def save_iv(self, ticker: str, dt: date, iv: float):
        self.conn.execute(
            "INSERT OR REPLACE INTO iv_history (ticker, date, iv) VALUES (?, ?, ?)",
            (ticker, dt.isoformat(), iv),
        )
        self.conn.commit()

    def get_iv_history(self, ticker: str, days: int = 365) -> list[tuple[str, float]]:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        cursor = self.conn.execute(
            "SELECT date, iv FROM iv_history WHERE ticker = ? AND date >= ? ORDER BY date",
            (ticker, cutoff),
        )
        return cursor.fetchall()

    def compute_iv_rank(self, ticker: str, current_iv: float) -> float | None:
        """Compute IV Rank as percentage (0-100).

        IV Rank = (current - 52w_low) / (52w_high - 52w_low) * 100
        Returns None if insufficient history.
        """
        history = self.get_iv_history(ticker, days=365)
        if len(history) < self.MIN_DATA_POINTS:
            return None

        ivs = [row[1] for row in history]
        iv_min = min(ivs)
        iv_max = max(ivs)

        if iv_max == iv_min:
            return 50.0  # flat IV

        rank = (current_iv - iv_min) / (iv_max - iv_min) * 100
        return round(rank, 1)

    def close(self):
        self.conn.close()
```

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_iv_store.py -v`
Expected: All tests PASS

**Step 5: Wire IV store into market_data.py**

Update `MarketDataProvider.__init__` to accept `iv_db_path` and create `IVStore`. Update `get_iv_rank` to:
1. Try IBKR first (if connected)
2. Get ATM IV from yfinance options chain
3. Store in IVStore
4. Compute rank from history

**Step 6: Commit**

```bash
git add src/iv_store.py tests/test_iv_store.py src/market_data.py
git commit -m "feat: add IV history store and IV Rank computation"
```

---

### Task 13: Final Verification & Cleanup

**Step 1: Run full test suite**

Run: `python -m pytest tests/ -v --tb=short`
Expected: All tests PASS

**Step 2: Verify Docker build**

Run: `docker build -t quant-radar .`
Expected: Build succeeds

**Step 3: Manual dry run (will fail on CSV fetch if no internet, that's OK)**

Run: `python -m src.main`
Expected: Either produces a report or fails gracefully at CSV fetch with a clear error

**Step 4: Update CLAUDE.md with module mappings**

Add to CLAUDE.md Spec-to-Code Mapping and Mirror Testing Rule sections.

**Step 5: Final commit**

```bash
git add -A
git commit -m "chore: final cleanup and CLAUDE.md mappings"
```
