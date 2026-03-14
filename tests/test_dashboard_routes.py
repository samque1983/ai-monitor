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


def _tickers(items):
    return [i["ticker"] for i in items]


def test_watchlist_add_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert resp.status_code == 200
    data = resp.json()
    assert "AAPL" in _tickers(data["items"])


def test_watchlist_add_ticker_dedup():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    resp = client.post("/api/watchlist/add", json={"ticker": "AAPL"})
    assert _tickers(resp.json()["items"]).count("AAPL") == 1


def test_watchlist_remove_ticker():
    client = get_client()
    client.post("/api/watchlist/add", json={"ticker": "NVDA"})
    resp = client.post("/api/watchlist/remove", json={"ticker": "NVDA"})
    assert resp.status_code == 200
    assert "NVDA" not in _tickers(resp.json()["items"])


def test_watchlist_remove_nonexistent_ticker():
    client = get_client()
    resp = client.post("/api/watchlist/remove", json={"ticker": "ZZZZ"})
    assert resp.status_code == 200
    assert isinstance(resp.json()["items"], list)


def test_watchlist_page_shows_strategy_section():
    client = get_client()
    resp = client.get("/watchlist")
    assert resp.status_code == 200
    assert "策略发现" in resp.text


def test_watchlist_page_shows_add_input():
    client = get_client()
    resp = client.get("/watchlist")
    assert "ticker-input" in resp.text


def test_strategy_dividend_page_returns_200():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert resp.status_code == 200


def test_strategy_dividend_page_has_strategy_name():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert "高股息" in resp.text


def test_strategy_dividend_page_has_nav():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert "/dashboard" in resp.text
    assert "/watchlist" in resp.text


def test_strategy_dividend_page_handles_empty_pool():
    client = get_client()
    resp = client.get("/strategy/dividend")
    assert resp.status_code == 200


# ── Watchlist seed tests (use isolated DB via AGENT_DB_PATH) ──────────────────

import tempfile
from unittest.mock import patch

_FAKE_UNIVERSE = [
    {"ticker": "SEED1", "name": "Seed One",   "group": "Test", "role": "", "floor": "", "strike": "", "note": ""},
    {"ticker": "SEED2", "name": "Seed Two",   "group": "Test", "role": "", "floor": "", "strike": "", "note": ""},
]


def _isolated_client(db_path: str):
    """Return a TestClient backed by a fresh DB at db_path."""
    import agent.deps as deps
    os.environ["AGENT_DB_PATH"] = db_path
    deps._db = None
    deps._db_path = None
    from agent.main import app
    return TestClient(app)


def test_watchlist_page_seeds_empty_user():
    """Empty watchlist → seeded from default universe on page load."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        client = _isolated_client(db_path)
        with patch("agent.dashboard._get_default_universe", return_value=_FAKE_UNIVERSE):
            resp = client.get("/watchlist")
        assert resp.status_code == 200
        assert "SEED1" in resp.text
        assert "SEED2" in resp.text
        from agent.db import AgentDB
        db = AgentDB(db_path)
        user = db.get_user("ALICE")
        assert user is not None
        items = db._parse_watchlist(user)
        tickers = [i["ticker"] for i in items]
        assert "SEED1" in tickers
        assert "SEED2" in tickers


def test_watchlist_page_no_seed_when_default_empty():
    """If default universe is empty (CSV not ready), show empty state without seeding."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        client = _isolated_client(db_path)
        with patch("agent.dashboard._get_default_universe", return_value=[]):
            resp = client.get("/watchlist")
        assert resp.status_code == 200
        assert "暂无自选标的" in resp.text
        from agent.db import AgentDB
        db = AgentDB(db_path)
        user = db.get_user("ALICE")
        items = db._parse_watchlist(user) if user else []
        assert items == []


def test_watchlist_page_no_reseed_when_non_empty():
    """Non-empty watchlist → _get_default_universe is never called."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        client = _isolated_client(db_path)
        # Pre-populate ALICE with one ticker
        from agent.db import AgentDB
        db = AgentDB(db_path)
        db.add_to_watchlist("ALICE", "TSLA")
        with patch("agent.dashboard._get_default_universe", return_value=_FAKE_UNIVERSE) as mock_uni:
            resp = client.get("/watchlist")
        assert resp.status_code == 200
        mock_uni.assert_not_called()
