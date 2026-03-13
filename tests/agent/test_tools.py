import pytest
import json
from agent.db import AgentDB
from agent.tools import AgentTools

@pytest.fixture
def db_and_tools(tmp_path):
    db = AgentDB(str(tmp_path / "agent.db"))
    db.save_user("user_123")
    tools = AgentTools(db, user_id="user_123")
    yield db, tools
    db.close()

def test_get_scan_results_empty(db_and_tools):
    _, tools = db_and_tools
    result = tools.get_scan_results()
    assert "暂无" in result or "没有" in result

def test_get_scan_results_with_data(db_and_tools):
    db, tools = db_and_tools
    db.save_scan_results("2026-03-06", [
        {"ticker": "AAPL", "strategy": "SELL_PUT",
         "trigger_reason": "跌入便宜区间", "action": "卖出 $170 Put"}
    ])
    result = tools.get_scan_results()
    assert "AAPL" in result
    assert "SELL_PUT" in result or "Sell Put" in result

def test_manage_watchlist_add(db_and_tools):
    db, tools = db_and_tools
    result = tools.manage_watchlist("add", "NVDA")
    assert "NVDA" in result
    user = db.get_user("user_123")
    assert "NVDA" in [item["ticker"] for item in json.loads(user["watchlist_json"])]

def test_manage_watchlist_remove(db_and_tools):
    db, tools = db_and_tools
    tools.manage_watchlist("add", "NVDA")
    tools.manage_watchlist("add", "AAPL")
    result = tools.manage_watchlist("remove", "NVDA")
    assert "移除" in result or "removed" in result.lower()
    user = db.get_user("user_123")
    wl = [item["ticker"] for item in json.loads(user["watchlist_json"])]
    assert "NVDA" not in wl
    assert "AAPL" in wl

def test_manage_watchlist_list(db_and_tools):
    db, tools = db_and_tools
    tools.manage_watchlist("add", "AAPL")
    tools.manage_watchlist("add", "KO")
    result = tools.manage_watchlist("list", "")
    assert "AAPL" in result
    assert "KO" in result

def test_get_card_not_found(db_and_tools):
    _, tools = db_and_tools
    result = tools.get_card("AAPL")
    assert "未找到" in result or "没有" in result
