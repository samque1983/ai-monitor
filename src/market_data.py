# src/market_data.py
import logging
from datetime import date, datetime
from typing import Optional
import pandas as pd
import yfinance as yf
from src.data_loader import classify_market

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Hybrid IBKR/yfinance market data provider."""

    def __init__(self, ibkr_config: Optional[dict] = None):
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
        """Get IV Rank (0-100). Placeholder -- will be implemented with IV history storage."""
        if self.should_skip_options(ticker):
            return None
        return None

    def disconnect(self):
        """Disconnect from IBKR if connected."""
        if self.ibkr:
            self.ibkr.disconnect()
            logger.info("Disconnected from IBKR")
