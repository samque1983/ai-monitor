# src/market_data.py
import logging
import os
from datetime import date, datetime, timedelta
from typing import List, Optional, Dict, Any
import pandas as pd
import yfinance as yf
from src.data_loader import classify_market
from src.iv_store import IVStore
from src.providers import PolygonProvider, TradierProvider

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Hybrid IBKR/yfinance market data provider."""

    def __init__(self, ibkr_config: Optional[dict] = None, iv_db_path: Optional[str] = None, config: Optional[dict] = None):
        self.ibkr = None
        self.ibkr_config = ibkr_config
        self.iv_store: Optional[IVStore] = None
        self.config: dict = config or {}  # Accept config parameter
        self._yf_session = self._make_yf_session()

        ds_config = (config or {}).get("data_sources", {})

        # IB Gateway (TWS) — enabled by default; disabled via ibkr_tws.enabled=false
        tws_enabled = ds_config.get("ibkr_tws", {}).get("enabled", True)
        if ibkr_config and tws_enabled:
            self.ibkr = self._try_connect_ibkr(ibkr_config)

        if iv_db_path:
            self.iv_store = IVStore(iv_db_path)

        # Polygon — requires enabled=true (default) AND api_key
        poly_cfg = ds_config.get("polygon", {})
        polygon_enabled = poly_cfg.get("enabled", True)
        polygon_key = poly_cfg.get("api_key") or os.environ.get("POLYGON_API_KEY", "")
        self._polygon: Optional[PolygonProvider] = (
            PolygonProvider(polygon_key) if (polygon_enabled and polygon_key) else None
        )

        # Tradier — requires enabled=true (default) AND api_key
        tradier_cfg = ds_config.get("tradier", {})
        tradier_enabled = tradier_cfg.get("enabled", True)
        tradier_key = tradier_cfg.get("api_key") or os.environ.get("TRADIER_API_KEY", "")
        tradier_sandbox = tradier_cfg.get("sandbox", True)
        self._tradier: Optional[TradierProvider] = (
            TradierProvider(tradier_key, sandbox=tradier_sandbox) if (tradier_enabled and tradier_key) else None
        )

    def _make_yf_session(self):
        """Create a curl_cffi session with SSL verification disabled (handles corporate proxy)."""
        try:
            from curl_cffi import requests as cffi_requests
            return cffi_requests.Session(impersonate="chrome", verify=False)
        except Exception as e:
            logger.debug(f"curl_cffi session creation failed, using default: {e}")
            return None

    _PERIOD_MAP = {
        "5d": "5 D", "1mo": "1 M", "3mo": "3 M",
        "6mo": "6 M", "1y": "1 Y", "2y": "2 Y",
        "5y": "5 Y", "10y": "10 Y",
    }

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

    def _make_contract(self, ticker: str):
        """Create an ib_insync Contract for the given ticker."""
        from ib_insync import Stock
        market = classify_market(ticker)
        if market == "HK":
            symbol = ticker.replace(".HK", "").lstrip("0") or "0"
            return Stock(symbol, "SEHK", "HKD")
        elif market == "CN":
            if ticker.endswith(".SS"):
                symbol = ticker.replace(".SS", "")
                return Stock(symbol, "SSE", "CNH")
            else:
                symbol = ticker.replace(".SZ", "")
                return Stock(symbol, "SZSE", "CNH")
        else:
            return Stock(ticker, "SMART", "USD")

    def _ibkr_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch daily OHLCV from IBKR Gateway.

        Tries real-time (ADJUSTED_LAST) first; falls back to delayed (TRADES)
        if the account has no real-time subscription.
        """
        from ib_insync import util
        contract = self._make_contract(ticker)
        duration = self._PERIOD_MAP.get(period, "1 Y")

        attempts = [
            (1, "ADJUSTED_LAST"),  # real-time / subscription
            (3, "TRADES"),         # delayed (free, 15-min)
        ]
        for mkt_data_type, what_to_show in attempts:
            try:
                self.ibkr.reqMarketDataType(mkt_data_type)
                bars = self.ibkr.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting="1 day",
                    whatToShow=what_to_show,
                    useRTH=True,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    df = df.rename(columns={
                        "open": "Open", "high": "High", "low": "Low",
                        "close": "Close", "volume": "Volume",
                    })
                    df.index = pd.to_datetime(df["date"])
                    df.index.name = None
                    logger.debug(f"{ticker}: IBKR price data via {what_to_show}")
                    return df.drop(columns=["date"], errors="ignore")
            except Exception as e:
                logger.debug(f"{ticker}: IBKR {what_to_show} failed: {e}")
                continue

        raise ValueError(f"No IBKR data for {ticker} (tried real-time and delayed)")

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch OHLCV. Routing: IBKR → Polygon (US only) → yfinance."""
        if self.ibkr:
            try:
                return self._ibkr_price_data(ticker, period)
            except Exception as e:
                logger.warning(f"IBKR price fetch failed for {ticker}, falling back: {e}")
        if self._polygon and classify_market(ticker) == "US":
            df = self._polygon.get_price_data(ticker, period)
            if not df.empty:
                logger.debug(f"{ticker}: price data via Polygon")
                return df
        return self._yf_price_data(ticker, period)

    def _yf_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch price data from yfinance."""
        try:
            df = yf.download(ticker, period=period, progress=False, timeout=30, session=self._yf_session)
            if df.empty:
                logger.warning(f"No price data for {ticker}")
            return df
        except Exception as e:
            logger.error(f"yfinance price fetch failed for {ticker}: {e}")
            return pd.DataFrame()

    def _ibkr_weekly_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch weekly OHLCV from IBKR Gateway.

        Tries real-time (ADJUSTED_LAST) first; falls back to delayed (TRADES).
        """
        from ib_insync import util
        contract = self._make_contract(ticker)
        duration = self._PERIOD_MAP.get(period, "1 Y")

        attempts = [
            (1, "ADJUSTED_LAST"),
            (3, "TRADES"),
        ]
        for mkt_data_type, what_to_show in attempts:
            try:
                self.ibkr.reqMarketDataType(mkt_data_type)
                bars = self.ibkr.reqHistoricalData(
                    contract,
                    endDateTime="",
                    durationStr=duration,
                    barSizeSetting="1 week",
                    whatToShow=what_to_show,
                    useRTH=True,
                    formatDate=1,
                )
                if bars:
                    df = util.df(bars)
                    df = df.rename(columns={
                        "open": "Open", "high": "High", "low": "Low",
                        "close": "Close", "volume": "Volume",
                    })
                    df.index = pd.to_datetime(df["date"])
                    df.index.name = None
                    logger.debug(f"{ticker}: IBKR weekly data via {what_to_show}")
                    return df.drop(columns=["date"], errors="ignore")
            except Exception as e:
                logger.debug(f"{ticker}: IBKR weekly {what_to_show} failed: {e}")
                continue

        raise ValueError(f"No IBKR data for {ticker} (tried real-time and delayed)")

    def _yf_weekly_price_data(self, ticker: str, period: str) -> pd.DataFrame:
        """Fetch weekly OHLCV from yfinance."""
        try:
            df = yf.download(ticker, period=period, interval="1wk", progress=False, timeout=30, session=self._yf_session)
            return df
        except Exception as e:
            logger.error(f"yfinance weekly data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_weekly_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch weekly OHLCV data. IBKR first, yfinance fallback."""
        if self.ibkr:
            try:
                return self._ibkr_weekly_price_data(ticker, period)
            except Exception as e:
                logger.warning(f"IBKR weekly fetch failed for {ticker}, falling back: {e}")
        return self._yf_weekly_price_data(ticker, period)

    def _ibkr_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        """Fetch put options chain from IBKR Gateway."""
        from ib_insync import Option, util

        contract = self._make_contract(ticker)
        self.ibkr.qualifyContracts(contract)

        chains = self.ibkr.reqSecDefOptParams(
            contract.symbol, "", contract.secType, contract.conId
        )
        if not chains:
            raise ValueError(f"No option chain params for {ticker}")

        chain = chains[0]
        for c in chains:
            if c.exchange == contract.exchange:
                chain = c
                break

        today = date.today()
        valid_exps = []
        for exp_str in chain.expirations:
            exp_date = datetime.strptime(exp_str, "%Y%m%d").date()
            dte = (exp_date - today).days
            if dte_min <= dte <= dte_max:
                valid_exps.append((exp_str, exp_date, dte))

        if not valid_exps:
            raise ValueError(f"No expirations in DTE range {dte_min}-{dte_max} for {ticker}")

        tickers_info = self.ibkr.reqTickers(contract)
        current_price = tickers_info[0].marketPrice() if tickers_info else 0
        if current_price <= 0:
            current_price = tickers_info[0].close if tickers_info else 0

        put_contracts = []
        for exp_str, exp_date, dte in valid_exps:
            for strike in sorted(chain.strikes):
                if current_price > 0:
                    if strike < current_price * 0.5 or strike > current_price * 1.5:
                        continue
                put_contracts.append(
                    Option(contract.symbol, exp_str, strike, "P", chain.exchange)
                )

        if not put_contracts:
            raise ValueError(f"No valid put contracts for {ticker}")

        qualified = self.ibkr.qualifyContracts(*put_contracts)
        tickers_data = self.ibkr.reqTickers(*qualified)

        rows = []
        exp_map = {exp_str: (exp_date, dte) for exp_str, exp_date, dte in valid_exps}
        for t in tickers_data:
            exp_str_key = t.contract.lastTradeDateOrContractMonth
            exp_info = exp_map.get(exp_str_key)
            if exp_info is None:
                continue
            exp_date, dte = exp_info
            rows.append({
                "strike": t.contract.strike,
                "bid": t.bid if t.bid > 0 else 0.0,
                "impliedVolatility": t.modelGreeks.impliedVol if t.modelGreeks else 0.0,
                "dte": dte,
                "expiration": exp_date,
            })

        if not rows:
            raise ValueError(f"No option tickers returned for {ticker}")
        return pd.DataFrame(rows)

    def _ibkr_earnings_date(self, ticker: str) -> Optional[date]:
        """Fetch next earnings date from IBKR CalendarReport XML."""
        import xml.etree.ElementTree as ET
        contract = self._make_contract(ticker)
        self.ibkr.qualifyContracts(contract)
        xml_data = self.ibkr.reqFundamentalData(contract, "CalendarReport")
        if not xml_data:
            raise ValueError(f"No IBKR CalendarReport for {ticker}")
        root = ET.fromstring(xml_data)
        today = date.today()
        future_dates = []
        for ann in root.findall(".//Announcement[@type='Earnings']"):
            date_el = ann.find("Date")
            if date_el is not None and date_el.text:
                try:
                    d = date.fromisoformat(date_el.text.strip())
                    if d >= today:
                        future_dates.append(d)
                except ValueError:
                    continue
        if not future_dates:
            raise ValueError(f"No future earnings dates in IBKR data for {ticker}")
        return min(future_dates)

    def get_earnings_date(self, ticker: str) -> Optional[date]:
        """Fetch next earnings date. IBKR first, yfinance fallback."""
        if self.ibkr:
            try:
                return self._ibkr_earnings_date(ticker)
            except Exception as e:
                logger.warning(f"IBKR earnings date failed for {ticker}, falling back: {e}")
        try:
            t = yf.Ticker(ticker, session=self._yf_session)
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
            t = yf.Ticker(ticker, session=self._yf_session)
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
        """Fetch put options. Routing: IBKR → Tradier (US only) → yfinance."""
        if self.should_skip_options(ticker):
            return pd.DataFrame()
        if self.ibkr:
            try:
                return self._ibkr_options_chain(ticker, dte_min, dte_max)
            except Exception as e:
                logger.warning(f"IBKR options chain failed for {ticker}, falling back: {e}")
        if self._tradier and classify_market(ticker) == "US":
            df = self._tradier.get_options_chain(ticker, dte_min=dte_min, dte_max=dte_max)
            if not df.empty:
                logger.debug(f"{ticker}: options via Tradier")
                return df
        return self._yf_options_chain(ticker, dte_min, dte_max)

    def _yf_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        """Fetch put options from yfinance, filtered by DTE."""
        try:
            t = yf.Ticker(ticker, session=self._yf_session)
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
            t = yf.Ticker(ticker, session=self._yf_session)
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
            t = yf.Ticker(ticker, session=self._yf_session)
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
            yticker = yf.Ticker(ticker, session=self._yf_session)
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

    def _yf_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        获取基本面数据 (yfinance)

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
            yticker = yf.Ticker(ticker, session=self._yf_session)
            info = yticker.info

            # Extract fields with .get() for safety
            payout_ratio = info.get("payoutRatio")
            roe = info.get("returnOnEquity")

            # Convert to percentage if present
            if payout_ratio is not None:
                payout_ratio = payout_ratio * 100
            if roe is not None:
                roe = roe * 100

            # Prefer trailingAnnualDividendYield (always decimal) when non-zero;
            # fall back to dividendYield which is usually in percentage format for yfinance 1.x
            trailing = info.get("trailingAnnualDividendYield")
            dividend_yield_raw = info.get("dividendYield")
            if trailing and trailing > 0:
                dividend_yield = round(trailing * 100, 4)
            elif dividend_yield_raw is not None:
                if dividend_yield_raw > 1.0:
                    # Already in percentage format (e.g. 5.43 = 5.43%)
                    dividend_yield = float(dividend_yield_raw)
                else:
                    # Decimal format (e.g. 0.035 = 3.5%)
                    dividend_yield = dividend_yield_raw * 100
            else:
                dividend_yield = None

            company_name = info.get("longName") or info.get("shortName") or ticker

            return {
                "payout_ratio": payout_ratio,
                "roe": roe,
                "debt_to_equity": info.get("debtToEquity"),
                "industry": info.get("industry"),
                "sector": info.get("sector"),
                "free_cash_flow": info.get("freeCashflow"),
                "dividend_yield": dividend_yield,
                "company_name": company_name,
                "forward_dividend_rate": info.get("forwardAnnualDividendRate"),
                "dividendRate": info.get("dividendRate"),
            }

        except Exception as e:
            logger.warning(f"Failed to fetch fundamentals for {ticker}: {e}")
            return None

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch fundamentals. Routing: Polygon → yfinance (US); yfinance (HK/CN).
        Polygon result has None for fields it can't provide; yfinance fills them in."""
        if self._polygon and classify_market(ticker) == "US":
            poly = self._polygon.get_fundamentals(ticker)
            if poly is not None:
                # Fill None fields from yfinance
                yf = self._yf_fundamentals(ticker) or {}
                for key, val in poly.items():
                    if val is None and yf.get(key) is not None:
                        poly[key] = yf[key]
                return poly
        return self._yf_fundamentals(ticker)

    def disconnect(self):
        """Disconnect from IBKR if connected."""
        if self.ibkr:
            self.ibkr.disconnect()
            logger.info("Disconnected from IBKR")
