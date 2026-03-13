# src/providers/base.py
"""Base provider interface for market data sources."""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import pandas as pd


class BaseProvider(ABC):
    """Abstract base class for all market data providers.

    Each provider implements the methods it supports.
    Unsupported methods return empty/None by default.
    """

    def get_price_data(self, ticker: str, period: str = "1y") -> pd.DataFrame:
        """Fetch daily OHLCV. Returns empty DataFrame if unsupported."""
        return pd.DataFrame()

    def get_options_chain(self, ticker: str, dte_min: int = 45, dte_max: int = 60) -> pd.DataFrame:
        """Fetch put options chain filtered by DTE. Returns empty DataFrame if unsupported."""
        return pd.DataFrame()

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """Fetch fundamental data. Returns None if unsupported."""
        return None

    def get_dividend_history(self, ticker: str, years: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Fetch dividend history. Returns None if unsupported."""
        return None
