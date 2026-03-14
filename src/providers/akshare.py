# src/providers/akshare.py
"""AKShare data provider for CN/HK/US markets."""
import logging
import re
from datetime import date, timedelta
from typing import Dict, Any, List, Optional
import pandas as pd

from src.providers.base import BaseProvider
from src.data_loader import classify_market

try:
    import akshare as ak
except ImportError:
    ak = None  # type: ignore

logger = logging.getLogger(__name__)

_PERIOD_DAYS = {
    "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
    "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
}

COLUMN_MAP = {
    "日期": "Date", "开盘": "Open", "最高": "High",
    "最低": "Low",  "收盘": "Close", "成交量": "Volume",
}

# CN ETF option underlying mapping: ticker suffix → AKShare symbol name
_CN_ETF_OPTION_MAP = {
    "510050": "50ETF",    # 上证50ETF
    "510300": "300ETF",   # 沪深300ETF (Shanghai)
    "159901": "深100ETF", # 深证100ETF
    "588000": "科创50",   # 科创50ETF
}


class AkshareProvider(BaseProvider):
    """AKShare data provider — free, no API key. Covers CN/HK/US markets."""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def _normalize_cn(self, ticker: str) -> str:
        """'600519.SS' → '600519', '000001.SZ' → '000001'."""
        return ticker.replace(".SS", "").replace(".SZ", "")

    def _cn_xq_symbol(self, ticker: str) -> str:
        """'600036.SS' → 'SH600036', '000001.SZ' → 'SZ000001' (XueQiu format)."""
        symbol = self._normalize_cn(ticker)
        prefix = "SH" if ticker.endswith(".SS") else "SZ"
        return f"{prefix}{symbol}"

    def _normalize_hk(self, ticker: str) -> str:
        """'0700.HK' → '00700' (5-digit, leading zeros)."""
        symbol = ticker.replace(".HK", "")
        return symbol.zfill(5)

    def _date_range(self, period: str) -> tuple:
        """Return (start_date_str, end_date_str) in 'YYYYMMDD' format."""
        days = _PERIOD_DAYS.get(period, 365)
        end = date.today()
        start = end - timedelta(days=days)
        return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    def _normalize_price_df(self, df: pd.DataFrame) -> pd.DataFrame:
        """Rename Chinese columns, set Date index, return standard OHLCV."""
        df = df.rename(columns=COLUMN_MAP)
        if "Date" in df.columns:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date")
            df.index.name = None
        keep = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[keep]

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch daily adjusted OHLCV. Routes by market: CN/HK/US."""
        if not self.enabled or ak is None:
            return pd.DataFrame()
        try:
            market = classify_market(ticker)
            start, end = self._date_range(period)
            if market == "CN":
                symbol = self._normalize_cn(ticker)
                raw = ak.stock_zh_a_hist(
                    symbol=symbol, period="daily",
                    start_date=start, end_date=end, adjust="qfq",
                )
            elif market == "HK":
                symbol = self._normalize_hk(ticker)
                raw = ak.stock_hk_hist(
                    symbol=symbol, period="daily",
                    start_date=start, end_date=end, adjust="qfq",
                )
            else:  # US
                raw = ak.stock_us_hist(
                    symbol=ticker, period="daily",
                    start_date=start, end_date=end, adjust="hfq",
                )
            if raw is None or raw.empty:
                return pd.DataFrame()
            return self._normalize_price_df(raw)
        except Exception as e:
            logger.warning(f"AKShare price data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch fundamentals. Supports CN and HK only. Returns None for US."""
        if not self.enabled or ak is None:
            return None
        market = classify_market(ticker)
        try:
            if market == "CN":
                return self._cn_fundamentals(ticker)
            elif market == "HK":
                return self._hk_fundamentals(ticker)
            return None  # US: not supported, triggers yfinance
        except Exception as e:
            logger.warning(f"AKShare fundamentals failed for {ticker}: {e}")
            return None

    def _cn_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        symbol = self._normalize_cn(ticker)
        info_df = ak.stock_individual_info_em(stock=symbol)
        info = dict(zip(info_df["item"], info_df["value"]))
        company_name = info.get("股票简称") or ticker
        industry = info.get("行业")

        dividend_yield = None
        try:
            xq_symbol = self._cn_xq_symbol(ticker)
            xq_df = ak.stock_individual_spot_xq(symbol=xq_symbol)
            xq_info = dict(zip(xq_df.iloc[:, 0], xq_df.iloc[:, 1]))
            val = xq_info.get("股息率(TTM)")
            if val is not None:
                dividend_yield = float(val)
        except Exception:
            pass

        return {
            "company_name": company_name,
            "industry": industry,
            "sector": None,
            "roe": None,
            "free_cash_flow": None,
            "payout_ratio": None,
            "debt_to_equity": None,
            "dividend_yield": dividend_yield,
        }

    def _hk_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        symbol = self._normalize_hk(ticker)
        df = ak.stock_hk_company_profile_em(symbol=symbol)
        if df is None or df.empty:
            return None
        row = df.iloc[0]
        company_name = row.get("公司名称") or ticker
        industry = row.get("所属行业")
        return {
            "company_name": company_name,
            "industry": industry,
            "sector": None,
            "roe": None,
            "free_cash_flow": None,
            "payout_ratio": None,
            "debt_to_equity": None,
            "dividend_yield": None,
        }

    def get_dividend_history(self, ticker: str, years: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Fetch dividend history for HK and CN stocks.

        HK: uses stock_hk_dividend_payout_em; parses 分红方案 text for per-share amount.
        CN: uses stock_dividend_cninfo; 派息比例 / 10 = per-share amount in RMB.
        US: returns None (yfinance handles it).

        Returns list of {date: datetime.date, amount: float} sorted ascending, or None.
        """
        if not self.enabled or ak is None:
            return None
        market = classify_market(ticker)
        if market == "HK":
            return self._hk_dividend_history(ticker, years)
        if market == "CN":
            return self._cn_dividend_history(ticker, years)
        return None  # US: not supported

    def _parse_hk_dividend_amount(self, text: str) -> Optional[float]:
        """Parse per-share dividend amount from 分红方案 text.

        Handles formats like:
          '每股派息0.45港元'
          '每股末期股息港币0.16元'
          '每股派发末期股息港币1.70元'
        Strategy: find all decimal numbers; take the first one > 0.
        """
        if not text or not isinstance(text, str):
            return None
        matches = re.findall(r'\d+\.\d+|\d+', text)
        for m in matches:
            val = float(m)
            if val > 0:
                return val
        return None

    def _hk_dividend_history(self, ticker: str, years: int) -> Optional[List[Dict[str, Any]]]:
        symbol = self._normalize_hk(ticker)
        try:
            df = ak.stock_hk_dividend_payout_em(symbol=symbol)
            if df is None or df.empty or "除净日" not in df.columns:
                return None
            cutoff = date.today() - timedelta(days=years * 365)
            result = []
            for _, row in df.iterrows():
                ex_date = row.get("除净日")
                if ex_date is None or (hasattr(ex_date, '__class__') and ex_date != ex_date):
                    continue  # NaT / NaN
                if isinstance(ex_date, str):
                    try:
                        ex_date = date.fromisoformat(ex_date)
                    except ValueError:
                        continue
                if ex_date < cutoff:
                    continue
                amount = self._parse_hk_dividend_amount(str(row.get("分红方案", "")))
                if amount is None or amount <= 0:
                    continue
                result.append({"date": ex_date, "amount": round(amount, 6)})
            if not result:
                return None
            result.sort(key=lambda r: r["date"])
            return result
        except Exception as e:
            logger.warning(f"AKShare HK dividend history failed for {ticker}: {e}")
            return None

    def _cn_dividend_history(self, ticker: str, years: int) -> Optional[List[Dict[str, Any]]]:
        symbol = self._normalize_cn(ticker)
        try:
            df = ak.stock_dividend_cninfo(symbol=symbol)
            if df is None or df.empty or "除权日" not in df.columns:
                return None
            cutoff = date.today() - timedelta(days=years * 365)
            result = []
            for _, row in df.iterrows():
                ex_date = row.get("除权日")
                if ex_date is None or (hasattr(ex_date, '__class__') and ex_date != ex_date):
                    continue
                if isinstance(ex_date, str):
                    try:
                        ex_date = date.fromisoformat(ex_date)
                    except ValueError:
                        continue
                if ex_date < cutoff:
                    continue
                payout = row.get("派息比例")
                try:
                    payout = float(payout)
                except (TypeError, ValueError):
                    continue
                if payout <= 0:
                    continue
                amount = round(payout / 10, 6)  # 派息比例 = per 10 shares
                result.append({"date": ex_date, "amount": amount})
            if not result:
                return None
            result.sort(key=lambda r: r["date"])
            return result
        except Exception as e:
            logger.warning(f"AKShare CN dividend history failed for {ticker}: {e}")
            return None

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options. CN: ETF options only. US: via AKShare fallback."""
        if not self.enabled or ak is None:
            return pd.DataFrame()
        market = classify_market(ticker)
        try:
            if market == "CN":
                return self._cn_options_chain(ticker, dte_min, dte_max)
            elif market == "US":
                return self._us_options_chain(ticker, dte_min, dte_max)
            return pd.DataFrame()
        except Exception as e:
            logger.warning(f"AKShare options chain failed for {ticker}: {e}")
            return pd.DataFrame()

    def _cn_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        symbol_key = self._normalize_cn(ticker)
        ak_symbol = _CN_ETF_OPTION_MAP.get(symbol_key)
        if not ak_symbol:
            return pd.DataFrame()  # not an optionable ETF

        board = ak.option_finance_board(symbol=ak_symbol)
        if board is None or board.empty:
            return pd.DataFrame()

        today = date.today()
        rows = []
        for _, row in board.iterrows():
            name = str(row.get("期权名称", ""))
            if "沽" not in name:
                continue  # skip calls
            try:
                exp_date = pd.to_datetime(row["到期日"]).date()
                dte = (exp_date - today).days
                if not (dte_min <= dte <= dte_max):
                    continue
                rows.append({
                    "strike": float(row["行权价"]),
                    "bid": float(row.get("买价", 0.0) or 0.0),
                    "dte": dte,
                    "expiration": exp_date,
                })
            except Exception:
                continue

        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows)

    def _us_options_chain(self, ticker: str, dte_min: int, dte_max: int) -> pd.DataFrame:
        """US options via AKShare — limited coverage, best-effort fallback."""
        try:
            board = ak.option_current_em(symbol=ticker)
            if board is None or board.empty:
                return pd.DataFrame()

            today = date.today()
            rows = []
            for _, row in board.iterrows():
                name = str(row.get("期权名称", ""))
                if "沽" not in name:
                    continue
                try:
                    exp_date = pd.to_datetime(row["到期日"]).date()
                    dte = (exp_date - today).days
                    if not (dte_min <= dte <= dte_max):
                        continue
                    rows.append({
                        "strike": float(row["行权价"]),
                        "bid": float(row.get("买价", 0.0) or 0.0),
                        "dte": dte,
                        "expiration": exp_date,
                    })
                except Exception:
                    continue

            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)
        except Exception as e:
            logger.warning(f"AKShare US options failed for {ticker}: {e}")
            return pd.DataFrame()
