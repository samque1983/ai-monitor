# src/providers/tradier.py
"""Tradier cloud API provider for US options chains (15-min delayed on sandbox)."""
import logging
import requests
import pandas as pd
from datetime import date, datetime
from typing import Optional

from src.providers.base import BaseProvider

logger = logging.getLogger(__name__)


class TradierProvider(BaseProvider):
    """Tradier cloud API provider for US options chains (15-min delayed on sandbox)."""

    SANDBOX_URL = "https://sandbox.tradier.com/v1"
    PROD_URL = "https://api.tradier.com/v1"

    def __init__(self, api_key: str, sandbox: bool = True):
        self.api_key = api_key
        self.base_url = self.SANDBOX_URL if sandbox else self.PROD_URL

    def _get(self, path: str, params: dict = None) -> dict:
        url = f"{self.base_url}{path}"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }
        resp = requests.get(url, params=params or {}, headers=headers, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options filtered by DTE. Returns empty DataFrame on failure."""
        try:
            exp_data = self._get("/markets/options/expirations", {"symbol": ticker})
            expirations = (exp_data.get("expirations") or {}).get("date") or []
            if not expirations:
                return pd.DataFrame()

            today = date.today()
            valid = []
            for exp_str in expirations:
                exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
                dte = (exp_date - today).days
                if dte_min <= dte <= dte_max:
                    valid.append((exp_str, exp_date, dte))

            if not valid:
                return pd.DataFrame()

            rows = []
            for exp_str, exp_date, dte in valid:
                chain_data = self._get(
                    "/markets/options/chains",
                    {"symbol": ticker, "expiration": exp_str, "greeks": "false"},
                )
                options = (chain_data.get("options") or {}).get("option") or []
                for opt in options:
                    if opt.get("option_type") != "put":
                        continue
                    bid = float(opt.get("bid") or 0.0)
                    rows.append({
                        "strike": float(opt["strike"]),
                        "bid": bid,
                        "dte": dte,
                        "expiration": exp_date,
                    })

            if not rows:
                return pd.DataFrame()
            return pd.DataFrame(rows)

        except Exception as e:
            logger.warning(f"Tradier options chain failed for {ticker}: {e}")
            return pd.DataFrame()
