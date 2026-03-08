# src/providers/polygon.py
"""Polygon.io cloud API provider for US market data."""
import logging
import time
import requests
import pandas as pd
from datetime import date, timedelta
from typing import Dict, Any, Optional

from src.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class PolygonProvider(BaseProvider):
    """Polygon.io cloud API provider for US price and fundamental data."""

    BASE_URL = "https://api.polygon.io"
    _PERIOD_DAYS = {
        "5d": 5, "1mo": 30, "3mo": 90, "6mo": 180,
        "1y": 365, "2y": 730, "5y": 1825, "10y": 3650,
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    def _get(self, path: str, params: dict = None) -> dict:
        """Make a rate-limited GET request. Returns parsed JSON or raises."""
        url = f"{self.BASE_URL}{path}"
        p = dict(params or {})
        p["apiKey"] = self.api_key
        resp = requests.get(url, params=p, timeout=15)
        time.sleep(0.25)  # 5 req/min free tier
        resp.raise_for_status()
        return resp.json()

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch daily adjusted OHLCV. Returns empty DataFrame on any failure."""
        try:
            days = self._PERIOD_DAYS.get(period, 365)
            to_date = date.today()
            from_date = to_date - timedelta(days=days)
            data = self._get(
                f"/v2/aggs/ticker/{ticker}/range/1/day/{from_date}/{to_date}",
                {"adjusted": "true", "sort": "asc", "limit": 5000},
            )
            results = data.get("results")
            if not results:
                return pd.DataFrame()
            rows = []
            for bar in results:
                rows.append({
                    "Date": pd.to_datetime(bar["t"], unit="ms", utc=True).normalize(),
                    "Open": bar["o"], "High": bar["h"],
                    "Low": bar["l"], "Close": bar["c"], "Volume": bar["v"],
                })
            df = pd.DataFrame(rows).set_index("Date")
            df.index = df.index.tz_localize(None)
            return df
        except Exception as e:
            logger.warning(f"Polygon price data failed for {ticker}: {e}")
            return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch fundamentals from Polygon. Returns partial dict; None fields fall back to yfinance."""
        try:
            # Basic info: name, industry
            ticker_data = self._get(f"/v3/reference/tickers/{ticker}")
            results = ticker_data.get("results", {})
            company_name = results.get("name") or ticker
            industry = results.get("sic_description")

            # Financial statements: ROE + FCF
            roe = None
            free_cash_flow = None
            try:
                fin_data = self._get(
                    "/vX/reference/financials",
                    {"ticker": ticker, "timeframe": "annual", "limit": 1},
                )
                fin_results = fin_data.get("results", [])
                if fin_results:
                    fin = fin_results[0]["financials"]
                    net_income = fin.get("income_statement", {}).get("net_income", {}).get("value")
                    equity = fin.get("balance_sheet", {}).get("equity", {}).get("value")
                    op_cf = fin.get("cash_flow_statement", {}).get(
                        "net_cash_flow_from_operating_activities", {}
                    ).get("value")
                    capex = fin.get("cash_flow_statement", {}).get(
                        "capital_expenditure", {}
                    ).get("value")

                    if net_income is not None and equity and equity > 0:
                        roe = (net_income / equity) * 100
                    if op_cf is not None and capex is not None:
                        free_cash_flow = op_cf + capex  # capex is typically negative
            except Exception as e:
                logger.debug(f"Polygon financials fetch failed for {ticker}: {e}")

            return {
                "company_name": company_name,
                "industry": industry,
                "sector": None,          # Polygon doesn't map SIC to sector
                "roe": roe,
                "free_cash_flow": free_cash_flow,
                "payout_ratio": None,    # not available from Polygon free tier
                "debt_to_equity": None,  # not available from Polygon free tier
                "dividend_yield": None,  # not available from Polygon free tier
            }
        except Exception as e:
            logger.warning(f"Polygon fundamentals failed for {ticker}: {e}")
            return None
