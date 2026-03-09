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


# ── signals table ────────────────────────────────────────────────────────────

def test_save_signals_writes_rows(tmp_path):
    db = AgentDB(str(tmp_path / "test.db"))
    signals = [
        {"signal_type": "sell_put", "ticker": "AAPL",
         "strike": 180, "dte": 52, "bid": 3.2, "apy": 18.5},
        {"signal_type": "iv_high", "ticker": "NVDA", "iv_rank": 85.0},
    ]
    count = db.save_signals("2026-03-09", signals)
    assert count == 2


def test_save_signals_is_idempotent(tmp_path):
    db = AgentDB(str(tmp_path / "test.db"))
    signals = [{"signal_type": "sell_put", "ticker": "AAPL", "apy": 18.5}]
    db.save_signals("2026-03-09", signals)
    db.save_signals("2026-03-09", signals)  # second call replaces
    result = db.get_signals("30d")
    assert len(result) == 1  # not 2


def test_get_signals_filters_by_range(tmp_path):
    from datetime import datetime, timedelta
    db = AgentDB(str(tmp_path / "test.db"))

    old_date = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d")
    new_date = datetime.now().strftime("%Y-%m-%d")

    db.save_signals(old_date, [{"signal_type": "iv_low", "ticker": "AAPL", "iv_rank": 15.0}])
    db.save_signals(new_date, [{"signal_type": "sell_put", "ticker": "MSFT", "apy": 12.0}])

    result_24h = db.get_signals("24h")
    assert len(result_24h) == 1
    assert result_24h[0]["ticker"] == "MSFT"

    result_30d = db.get_signals("30d")
    assert len(result_30d) == 2


def test_get_signals_filters_by_category(tmp_path):
    db = AgentDB(str(tmp_path / "test.db"))
    signals = [
        {"signal_type": "sell_put", "ticker": "AAPL", "apy": 18.5},
        {"signal_type": "iv_high", "ticker": "NVDA", "iv_rank": 85.0},
    ]
    db.save_signals("2026-03-09", signals)

    opps = db.get_signals("30d", category="opportunity")
    assert len(opps) == 1
    assert opps[0]["signal_type"] == "sell_put"

    risks = db.get_signals("30d", category="risk")
    assert len(risks) == 1
    assert risks[0]["signal_type"] == "iv_high"


def test_get_signals_returns_payload_as_dict(tmp_path):
    db = AgentDB(str(tmp_path / "test.db"))
    db.save_signals("2026-03-09", [
        {"signal_type": "sell_put", "ticker": "AAPL", "strike": 180, "apy": 18.5}
    ])
    result = db.get_signals("30d")
    assert isinstance(result[0]["payload"], dict)
    assert result[0]["payload"]["apy"] == 18.5
