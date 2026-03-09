import pytest
import os
from fastapi.testclient import TestClient

SCAN_API_KEY = "test-api-key-123"

def test_push_scan_results(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = SCAN_API_KEY
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    import importlib
    import agent.main
    importlib.reload(agent.main)
    from agent.main import app
    client = TestClient(app)

    payload = {
        "scan_date": "2026-03-06",
        "results": [
            {"ticker": "AAPL", "strategy": "SELL_PUT",
             "trigger_reason": "跌入便宜区间"}
        ],
    }
    resp = client.post(
        "/api/scan_results",
        json=payload,
        headers={"X-API-Key": SCAN_API_KEY},
    )
    assert resp.status_code == 200
    assert resp.json()["saved"] == 1

def test_push_scan_results_rejects_bad_key(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = SCAN_API_KEY
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    import importlib
    import agent.main
    importlib.reload(agent.main)
    from agent.main import app
    client = TestClient(app)

    resp = client.post(
        "/api/scan_results",
        json={"scan_date": "2026-03-06", "results": []},
        headers={"X-API-Key": "wrong-key"},
    )
    assert resp.status_code == 403


def test_push_also_saves_to_signals_table(tmp_path):
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["SCAN_API_KEY"] = SCAN_API_KEY
    os.environ["DINGTALK_APP_SECRET"] = ""
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    import importlib
    import agent.deps
    import agent.main
    importlib.reload(agent.deps)
    importlib.reload(agent.main)
    from agent.main import app
    from agent.deps import get_db
    client = TestClient(app)

    payload = {
        "scan_date": "2026-03-09",
        "results": [
            {"signal_type": "sell_put", "ticker": "AAPL",
             "strike": 180, "dte": 52, "bid": 3.2, "apy": 18.5},
            {"signal_type": "iv_high", "ticker": "NVDA", "iv_rank": 85.0},
        ],
    }
    resp = client.post(
        "/api/scan_results",
        json=payload,
        headers={"X-API-Key": SCAN_API_KEY},
    )
    assert resp.status_code == 200

    db = get_db()
    signals = db.get_signals("30d")
    assert len(signals) == 2
    tickers = {s["ticker"] for s in signals}
    assert tickers == {"AAPL", "NVDA"}
