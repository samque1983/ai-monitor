import pytest
import json
from agent.db import AgentDB
from agent.tools import AgentTools


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


@pytest.fixture
def tools(db):
    db.save_user("ALICE")
    return AgentTools(db, user_id="ALICE")


def test_get_opportunity_cards_no_signals(tools):
    result = tools.get_opportunity_cards("dividend")
    assert "暂无" in result


def test_get_opportunity_cards_returns_json_list(db, tools):
    db.save_signals("2026-03-13", [
        {"signal_type": "dividend", "ticker": "0700.HK",
         "company_name": "腾讯控股", "ttm_yield": 4.2, "iv_rank": 72},
        {"signal_type": "dividend", "ticker": "AAPL",
         "company_name": "Apple", "ttm_yield": 0.5, "iv_rank": 30},
    ])
    result = tools.get_opportunity_cards("dividend")
    cards = json.loads(result)
    assert isinstance(cards, list)
    assert len(cards) == 2
    tickers = [c["ticker"] for c in cards]
    assert "0700.HK" in tickers
    assert "AAPL" in tickers


def test_get_opportunity_cards_structure(db, tools):
    db.save_signals("2026-03-13", [
        {"signal_type": "dividend", "ticker": "KO",
         "ttm_yield": 3.1, "iv_rank": 45},
    ])
    result = tools.get_opportunity_cards("dividend")
    cards = json.loads(result)
    card = cards[0]
    assert card["type"] == "opportunity"
    assert card["ticker"] == "KO"
    assert "yield" in card
    assert card["action"] == "add_watchlist"


def test_get_opportunity_cards_caps_at_5(db, tools):
    signals = [
        {"signal_type": "dividend", "ticker": f"T{i}", "ttm_yield": 3.0, "iv_rank": 50}
        for i in range(8)
    ]
    db.save_signals("2026-03-13", signals)
    result = tools.get_opportunity_cards("dividend")
    cards = json.loads(result)
    assert len(cards) <= 5


def test_get_risk_summary_no_report(tools):
    result = tools.get_risk_summary()
    assert "暂无" in result


def test_get_risk_summary_returns_json(db, tools):
    db.save_risk_report("ALICE", "2026-03-13", "<html>risk</html>")
    result = tools.get_risk_summary()
    data = json.loads(result)
    assert data["type"] == "risk_summary"
    assert data["report_date"] == "2026-03-13"
    assert data["action"] == "view_risk_report"
