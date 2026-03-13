# tests/test_dashboard_routes.py
import pytest
from fastapi.testclient import TestClient


def test_templates_dir_exists():
    """Jinja2 templates directory must exist."""
    import os
    assert os.path.isdir("agent/templates"), "agent/templates/ not found"


def test_jinja2_importable():
    """jinja2 must be installed."""
    import jinja2  # noqa: F401


def test_nav_partial_exists():
    import os
    assert os.path.isfile("agent/templates/_nav.html")

def test_nav_partial_has_all_pages():
    content = open("agent/templates/_nav.html").read()
    assert "/dashboard" in content
    assert "/risk-report" in content
    assert "/chat" in content
    assert "/watchlist" in content

def test_nav_partial_active_variable():
    """_nav.html must use active_page variable for highlighting."""
    content = open("agent/templates/_nav.html").read()
    assert "active_page" in content

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_client():
    from agent.main import app
    from fastapi.testclient import TestClient
    return TestClient(app)

def test_dashboard_returns_html_with_nav():
    client = get_client()
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "市场雷达" in resp.text
    assert "/risk-report" in resp.text
    assert "/chat" in resp.text

def test_dashboard_active_class():
    client = get_client()
    resp = client.get("/dashboard")
    assert 'active' in resp.text

def test_risk_report_page_returns_html():
    client = get_client()
    resp = client.get("/risk-report")
    assert resp.status_code == 200
    assert "风险报告" in resp.text
    assert "/dashboard" in resp.text

def test_chat_page_returns_200():
    client = get_client()
    resp = client.get("/chat")
    assert resp.status_code == 200

def test_chat_page_has_nav_and_input():
    client = get_client()
    resp = client.get("/chat")
    assert "AI 领航" in resp.text
    assert "/dashboard" in resp.text
    assert "chat-input" in resp.text

def test_watchlist_page_returns_200():
    client = get_client()
    resp = client.get("/watchlist")
    assert resp.status_code == 200

def test_watchlist_page_has_nav():
    client = get_client()
    resp = client.get("/watchlist")
    assert "自选池" in resp.text
    assert "/dashboard" in resp.text


def test_watchlist_add_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert "AAPL" in data["tickers"]


def test_watchlist_add_ticker_dedup():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert resp.json()["tickers"].count("AAPL") == 1


def test_watchlist_remove_ticker():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "NVDA"})
    resp = client.post("/api/watchlist/remove", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    assert "NVDA" not in resp.json()["tickers"]


def test_watchlist_remove_nonexistent_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/remove", json={"ticker": "ZZZZ"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["tickers"], list)


def test_watchlist_page_shows_strategy_section():
    client = get_client()
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "策略发现" in resp.text


def test_watchlist_page_shows_add_input():
    client = get_client()
    resp = client.get("/watchlist")
    assert "ticker-input" in resp.text
