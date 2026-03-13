import pytest, json
from agent.db import AgentDB


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


def test_add_to_watchlist_creates_user_and_adds(db):
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert "AAPL" in result


def test_add_to_watchlist_dedup(db):
    db.add_to_watchlist("ALICE", "AAPL")
    result = db.add_to_watchlist("ALICE", "AAPL")
    assert result.count("AAPL") == 1


def test_add_to_watchlist_uppercases(db):
    result = db.add_to_watchlist("ALICE", "aapl")
    assert "AAPL" in result
    assert "aapl" not in result


def test_remove_from_watchlist(db):
    db.add_to_watchlist("ALICE", "AAPL")
    db.add_to_watchlist("ALICE", "MSFT")
    result = db.remove_from_watchlist("ALICE", "AAPL")
    assert "AAPL" not in result
    assert "MSFT" in result


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
