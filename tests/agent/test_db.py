import pytest
from datetime import date
from agent.db import AgentDB

def test_save_and_get_user(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123", dingtalk_webhook="https://oapi.dingtalk.com/xxx")
    user = db.get_user("user_123")
    assert user["user_id"] == "user_123"
    assert user["dingtalk_webhook"] == "https://oapi.dingtalk.com/xxx"
    db.close()

def test_save_and_get_scan_results(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    results = [{"ticker": "AAPL", "strategy": "SELL_PUT"}]
    db.save_scan_results("2026-03-06", results)
    latest = db.get_latest_scan_results()
    assert latest is not None
    assert latest[0]["ticker"] == "AAPL"
    db.close()

def test_save_and_get_conversation(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.add_message("user_123", "user", "今天有什么信号")
    db.add_message("user_123", "assistant", "今天有 2 个信号")
    history = db.get_history("user_123", limit=10)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    db.close()

def test_get_history_respects_limit(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    for i in range(25):
        db.add_message("user_123", "user", f"msg {i}")
    history = db.get_history("user_123", limit=20)
    assert len(history) == 20
    db.close()

def test_watchlist_update(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123")
    db.update_watchlist("user_123", ["AAPL", "NVDA"])
    user = db.get_user("user_123")
    import json
    assert json.loads(user["watchlist_json"]) == ["AAPL", "NVDA"]
    db.close()
