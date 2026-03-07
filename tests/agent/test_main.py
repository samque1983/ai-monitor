import pytest
from fastapi.testclient import TestClient


def test_health_check():
    from agent.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_get_scan_results_empty():
    """Returns empty list when no scan results exist."""
    from agent.main import app
    client = TestClient(app)
    resp = client.get("/api/scan_results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_date"] is None
    assert data["results"] == []


def test_get_scan_results_returns_latest():
    """Returns latest scan results after they are saved."""
    import os, tempfile
    os.environ["AGENT_DB_PATH"] = tempfile.mktemp(suffix=".db")
    from agent.main import app, _get_db
    client = TestClient(app)

    # Push some results first
    _get_db().save_scan_results("2026-03-07", [{"ticker": "AAPL", "strategy": "SELL_PUT"}])

    resp = client.get("/api/scan_results")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_date"] == "2026-03-07"
    assert len(data["results"]) == 1
    assert data["results"][0]["ticker"] == "AAPL"
