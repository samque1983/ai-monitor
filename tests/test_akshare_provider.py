"""Tests for AkshareProvider."""
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from src.providers.akshare import AkshareProvider


def test_provider_instantiation():
    p = AkshareProvider(enabled=True)
    assert p.enabled is True


def test_provider_disabled_returns_empty():
    p = AkshareProvider(enabled=False)
    assert p.get_price_data("600519.SS").empty
    assert p.get_fundamentals("600519.SS") is None
    assert p.get_options_chain("600519.SS").empty


def test_normalize_cn():
    p = AkshareProvider()
    assert p._normalize_cn("600519.SS") == "600519"
    assert p._normalize_cn("000001.SZ") == "000001"
    assert p._normalize_cn("510050.SS") == "510050"


def test_normalize_hk():
    p = AkshareProvider()
    assert p._normalize_hk("0700.HK") == "00700"
    assert p._normalize_hk("0005.HK") == "00005"
    assert p._normalize_hk("0823.HK") == "00823"
    assert p._normalize_hk("09988.HK") == "09988"  # already 5 digits
