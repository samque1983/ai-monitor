"""Tests for dividend_pool_page.py — standalone pool HTML generator."""
import pytest
from src.dividend_pool_page import generate_dividend_pool_page


def _versions():
    return [
        {"version": "monthly_2026-03", "created_at": "2026-03-05T14:23:00",
         "tickers_count": 2, "avg_quality_score": 81.0},
        {"version": "monthly_2026-02", "created_at": "2026-02-03T09:11:00",
         "tickers_count": 1, "avg_quality_score": 80.0},
    ]


def _pool_records():
    return [
        {"ticker": "KO", "name": "Coca-Cola", "market": "US",
         "quality_score": 85.0, "consecutive_years": 61,
         "dividend_growth_5y": 4.5, "payout_ratio": 65.0,
         "payout_type": "GAAP", "dividend_yield": 3.0,
         "roe": 45.0, "debt_to_equity": 1.8,
         "industry": "Beverages", "sector": "Consumer Staples"},
        {"ticker": "ENB", "name": "Enbridge", "market": "US",
         "quality_score": 78.0, "consecutive_years": 28,
         "dividend_growth_5y": 3.0, "payout_ratio": 64.0,
         "payout_type": "FCF", "dividend_yield": 7.2,
         "roe": 10.0, "debt_to_equity": 1.5,
         "industry": "Oil & Gas Midstream", "sector": "Energy"},
    ]


def test_generate_page_returns_html_string():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert isinstance(html, str)
    assert html.startswith("<!DOCTYPE html>")


def test_page_contains_ticker_data():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "KO" in html
    assert "ENB" in html
    assert "Coca-Cola" in html


def test_page_shows_payout_type_badge():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "FCF" in html
    assert "GAAP" in html


def test_page_shows_version_history():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "monthly_2026-03" in html
    assert "monthly_2026-02" in html
    assert "2 支" in html or "tickers_count" in html or "2</" in html


def test_page_contains_methodology_explanation():
    html = generate_dividend_pool_page(_versions(), _pool_records(), "monthly_2026-03")
    assert "连续派息" in html or "consecutive" in html.lower()
    assert "FCF" in html


def test_page_handles_empty_pool():
    html = generate_dividend_pool_page(_versions(), [], "monthly_2026-03")
    assert "<!DOCTYPE html>" in html
