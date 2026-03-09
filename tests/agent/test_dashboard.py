import os
import pytest
from fastapi.testclient import TestClient


def _make_client(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = "test-key"
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"
    import importlib
    import agent.main
    importlib.reload(agent.main)
    from agent.main import app
    return TestClient(app)


def test_dashboard_returns_html(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "量化扫描雷达" in resp.text


def test_api_signals_returns_json(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/signals?range=24h")
    assert resp.status_code == 200
    data = resp.json()
    assert "signals" in data
    assert "opportunity_count" in data
    assert "risk_count" in data
    assert data["range"] == "24h"


def test_api_signals_category_filter(tmp_path):
    from agent.db import AgentDB
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_signals("2026-03-09", [
        {"signal_type": "sell_put", "ticker": "AAPL", "apy": 18.5},
        {"signal_type": "iv_high", "ticker": "NVDA", "iv_rank": 85.0},
    ])

    client = _make_client(tmp_path)
    resp = client.get("/api/signals?range=30d&category=opportunity")
    data = resp.json()
    assert all(s["category"] == "opportunity" for s in data["signals"])


def test_api_signals_default_range_is_24h(tmp_path):
    client = _make_client(tmp_path)
    resp = client.get("/api/signals")
    assert resp.json()["range"] == "24h"
