# src/market_data.py
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
import pandas as pd
import yfinance as yf
from src.data_loader import classify_market
from src.iv_store import IVStore

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Hybrid IBKR/yfinance market data provider."""

    def __init__(self, ibkr_config: Optional[dict] = None, iv_db_path: Optional[str] = None, config: Optional[dict] = None):
        self.ibkr = None
        self.ibkr_config = ibkr_config
        self.iv_store: Optional[IVStore] = None
        self.config: dict = config or {}  # Accept config parameter
        if ibkr_config:
            self.ibkr = self._try_connect_ibkr(ibkr_config)
        if iv_db_path:
            self.iv_store = IVStore(iv_db_path)

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
                readonly=True,
            )
            logger.info("Connected to IBKR Gateway")
            return ib
        except Exception as e:
            logger.warning(f"IBKR connection failed, using yfinance fallback: {e}")
            return None

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch OHLCV price data. IBKR first, yfinance fallback."""
        return self._yf_price_data(ticker, period)

    def _yf_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch price data from yfinance."""
        try:
            df = yf.download(ticker, period=period, progress=False, timeout=30)
            if df.empty:
                logger.warning(f"No price data for {ticker}")
            return df
        except Exception as e:
            logger.error(f"yfinance price fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_weekly_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch weekly OHLCV data for weekly MA calculation."""
        try:
            df = yf.download(ticker, period=period, interval="1wk", progress=False, timeout=30)
            return df
        except Exception as e:
            logger.error(f"yfinance weekly data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_earnings_date(self, ticker: str) -> Optional[date]:
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

    def get_historical_earnings_dates(self, ticker: str, count: int = 8) -> List[date]:
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

    def _load_earnings_from_csv(self, ticker: str, count: int) -> List[date]:
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

            # Validate required columns
            required_cols = ["ticker", "date"]
            if not all(col in df.columns for col in required_cols):
                logger.error(f"CSV missing required columns: {required_cols}. Found: {list(df.columns)}")
                return []

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

    def should_skip_options(self, ticker: str) -> bool:
        """Return True if options data should be skipped for this ticker."""
        return classify_market(ticker) == "CN"

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options chain filtered by DTE range."""
        if self.should_skip_options(ticker):
            return pd.DataFrame()
        return self._yf_options_chain(ticker, dte_min, dte_max)

    def _yf_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        """Fetch put options from yfinance, filtered by DTE."""
        try:
            t = yf.Ticker(ticker)
            expirations = t.options
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

    def get_iv_rank(self, ticker: str) -> Optional[float]:
        """Get IV Rank (0-100) using ATM IV from options chain and historical data."""
        if self.should_skip_options(ticker):
            return None
        try:
            t = yf.Ticker(ticker)
            current_price = t.info.get("regularMarketPrice") or t.info.get("previousClose")
            if not current_price:
                return None

            exps = t.options
            if not exps:
                return None
            # Use nearest expiration
            chain = t.option_chain(exps[0])
            calls = chain.calls
            if calls.empty:
                return None
            # Find ATM option
            calls = calls.copy()
            calls["diff"] = abs(calls["strike"] - current_price)
            atm = calls.loc[calls["diff"].idxmin()]
            current_iv = float(atm["impliedVolatility"])

            # Store snapshot and compute rank
            if self.iv_store:
                self.iv_store.save_iv(ticker, date.today(), current_iv)
                return self.iv_store.compute_iv_rank(ticker, current_iv)
            return None
        except Exception as e:
            logger.warning(f"IV rank fetch failed for {ticker}: {e}")
            return None

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

    def get_dividend_history(self, ticker: str, years: int = 5) -> Optional[List[Dict[str, Any]]]:
        """
        获取股息历史数据

        从 yfinance 获取过去 N 年的股息记录。

        参数:
        - ticker: 股票代码
        - years: 回溯年数（默认 5 年）

        返回:
        - List[Dict]: [{date: datetime.date, amount: float}, ...] 按时间升序
        - None: 无数据或发生错误

        注意:
        - 自动过滤到 cutoff_date = datetime.now() - timedelta(days=years * 365)
        - years < 1 时触发警告并返回 None
        """
        if years < 1:
            logger.warning(f"Invalid years parameter: {years}. Must be >= 1.")
            return None

        try:
            yticker = yf.Ticker(ticker)
            dividends = yticker.dividends

            if dividends is None or dividends.empty:
                logger.warning(f"No dividend data for {ticker}")
                return None

            cutoff_date = datetime.now() - timedelta(days=years * 365)
            # yfinance returns tz-aware index; make cutoff_date compatible
            if hasattr(dividends.index, 'tz') and dividends.index.tz is not None:
                import pytz
                cutoff_date = cutoff_date.replace(tzinfo=pytz.utc)
            filtered = dividends[dividends.index >= cutoff_date]

            if filtered.empty:
                return None

            result = []
            for div_date, amount in filtered.items():
                result.append({
                    "date": div_date.to_pydatetime().date(),
                    "amount": float(amount)
                })

            return result

        except Exception as e:
            logger.warning(f"Failed to fetch dividend history for {ticker}: {e}")
            return None

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        获取基本面数据

        从 yfinance 的 info 中提取关键财务指标。

        参数:
        - ticker: 股票代码

        返回:
        - Dict: {
            payout_ratio: float (百分比, 如 25.0 表示 25%),
            roe: float (百分比),
            debt_to_equity: float,
            industry: str,
            sector: str,
            free_cash_flow: float
          }
        - None: 发生错误

        注意:
        - payout_ratio 和 roe 从小数转为百分比（×100）
        - 缺失字段使用 None
        """
        try:
            yticker = yf.Ticker(ticker)
            info = yticker.info

            # Extract fields with .get() for safety
            payout_ratio = info.get("payoutRatio")
            roe = info.get("returnOnEquity")

            # Convert to percentage if present
            if payout_ratio is not None:
                payout_ratio = payout_ratio * 100
            if roe is not None:
                roe = roe * 100

            return {
                "payout_ratio": payout_ratio,
                "roe": roe,
                "debt_to_equity": info.get("debtToEquity"),
                "industry": info.get("industry"),
                "sector": info.get("sector"),
                "free_cash_flow": info.get("freeCashflow")
            }

        except Exception as e:
            logger.warning(f"Failed to fetch fundamentals for {ticker}: {e}")
            return None

    def disconnect(self):
        """Disconnect from IBKR if connected."""
        if self.ibkr:
            self.ibkr.disconnect()
            logger.info("Disconnected from IBKR")
