import pytest, json
from agent.db import AgentDB


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


def _tickers(items):
    return [i["ticker"] for i in items]


def test_add_to_watchlist_creates_user_and_adds(db):
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert "AAPL" in _tickers(result)


def test_add_to_watchlist_dedup(db):
    db.add_to_watchlist("ALICE", "AAPL")
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert _tickers(result).count("AAPL") == 1


def test_add_to_watchlist_uppercases(db):
    result = db.add_to_watchlist("ALICE", "aapl")
    assert "AAPL" in _tickers(result)
    assert "aapl" not in _tickers(result)


def test_add_to_watchlist_with_metadata(db):
    result = db.add_to_watchlist("ALICE", "NVDA", metadata={"name": "英伟达", "role": "AI核心", "floor": "$700"})
    item = next(i for i in result if i["ticker"] == "NVDA")
    assert item["name"] == "英伟达"
    assert item["role"] == "AI核心"
    assert item["floor"] == "$700"


def test_remove_from_watchlist(db):
    db.add_to_watchlist("ALICE", "AAPL")
    db.add_to_watchlist("ALICE", "MSFT")
    result = db.remove_from_watchlist("ALICE", "AAPL")
    assert "AAPL" not in _tickers(result)
    assert "MSFT" in _tickers(result)


def test_remove_from_watchlist_missing_ticker(db):
    result = db.remove_from_watchlist("ALICE", "NVDA")
    assert isinstance(result, list)


def test_get_strategy_pool_returns_latest_scan(db):
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-10", "2026-03-10T12:00:00", "dividend", "opportunity", "KO",
         json.dumps({"current_yield": 3.5, "last_price": 65.0, "quality_score": 85.0, "payout_ratio": 65.0}))
    )
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-12", "2026-03-12T12:00:00", "dividend", "opportunity", "ENB",
         json.dumps({"current_yield": 7.2, "last_price": 42.0, "quality_score": 78.0, "payout_ratio": 64.0}))
    )
    db.conn.execute(
        "INSERT INTO signals (scan_date, scanned_at, signal_type, category, ticker, payload) VALUES (?,?,?,?,?,?)",
        ("2026-03-12", "2026-03-12T12:00:00", "dividend", "opportunity", "T",
         json.dumps({"current_yield": 6.5, "last_price": 20.0, "quality_score": 72.0, "payout_ratio": 70.0}))
    )
    db.conn.commit()
    pool = db.get_strategy_pool("dividend")
    tickers = [r["ticker"] for r in pool]
    assert "ENB" in tickers
    assert "T" in tickers
    assert "KO" not in tickers


def test_get_strategy_pool_empty(db):
    result = db.get_strategy_pool("dividend")
    assert result == []


def test_get_profile_empty(db):
    db.save_user("BOB")
    assert db.get_profile("BOB") == {}


def test_update_and_get_profile(db):
    profile = {"risk_level": "moderate", "strategy_tags": ["高股息"], "summary": "稳健型"}
    db.update_profile("CHARLIE", profile)
    result = db.get_profile("CHARLIE")
    assert result["risk_level"] == "moderate"
    assert "高股息" in result["strategy_tags"]
    assert result["summary"] == "稳健型"


def test_update_profile_overwrites(db):
    db.update_profile("DIANA", {"risk_level": "conservative"})
    db.update_profile("DIANA", {"risk_level": "aggressive"})
    assert db.get_profile("DIANA")["risk_level"] == "aggressive"
