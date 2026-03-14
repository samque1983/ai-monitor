import pytest
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("POSITIONS_API_KEY", "test-secret")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    from agent.main import app
    return TestClient(app)


_SAMPLE_PAYLOAD = {
    "account_key": "ALICE",
    "ib_account_id": "U9376705",
    "positions": [
        {
            "symbol": "AAPL  260620P00180000",
            "asset_category": "OPT",
            "put_call": "P",
            "strike": 180.0,
            "expiry": "20260620",
            "multiplier": 100,
            "position": -1,
            "cost_basis_price": 3.0,
            "mark_price": 2.0,
            "unrealized_pnl": 100.0,
            "delta": -0.3,
            "gamma": 0.01,
            "theta": -0.05,
            "vega": 0.1,
            "underlying_symbol": "AAPL",
            "currency": "USD",
        }
    ],
    "account_summary": {
        "net_liquidation": 100000.0,
        "gross_position_value": 5000.0,
        "init_margin_req": 2000.0,
        "maint_margin_req": 1500.0,
        "excess_liquidity": 29000.0,
        "available_funds": 29000.0,
        "cushion": 0.29,
    },
}


def test_post_positions_requires_api_key(client):
    resp = client.post("/api/positions", json=_SAMPLE_PAYLOAD)
    assert resp.status_code == 403


def test_post_positions_wrong_key(client):
    resp = client.post("/api/positions", json=_SAMPLE_PAYLOAD,
                       headers={"X-API-Key": "wrong"})
    assert resp.status_code == 403


def test_post_positions_success(client):
    resp = client.post("/api/positions", json=_SAMPLE_PAYLOAD,
                       headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "report_date" in data
    assert "alerts" in data


def test_post_positions_saves_to_db(client):
    from agent.deps import get_db
    client.post("/api/positions", json=_SAMPLE_PAYLOAD,
                headers={"X-API-Key": "test-secret"})
    db = get_db()
    row = db.get_latest_risk_report("ALICE")
    assert row is not None
    assert "<html" in row["html_content"].lower()


def test_post_positions_saves_raw_payload(client):
    from agent.deps import get_db
    client.post("/api/positions", json=_SAMPLE_PAYLOAD,
                headers={"X-API-Key": "test-secret"})
    db = get_db()
    raw = db.get_raw_positions("ALICE")
    assert raw is not None
    assert raw["account_key"] == "ALICE"
    assert len(raw["positions"]) == 1


def test_regenerate_uses_saved_raw_payload(client):
    # POST positions first to seed raw data
    client.post("/api/positions", json=_SAMPLE_PAYLOAD,
                headers={"X-API-Key": "test-secret"})
    # Regenerate — should produce a new report without needing IB Gateway
    resp = client.post("/api/risk-report/regenerate/ALICE",
                       headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "report_date" in data


def test_regenerate_returns_404_when_no_raw_data(client):
    resp = client.post("/api/risk-report/regenerate/ALICE",
                       headers={"X-API-Key": "test-secret"})
    assert resp.status_code == 404
