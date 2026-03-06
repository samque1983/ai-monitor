# tests/test_card_store.py
import pytest, json
from datetime import datetime, timedelta
from src.card_store import CardStore

def test_save_and_get_card(tmp_path):
    store = CardStore(str(tmp_path / "cards.db"))
    card = {"ticker": "AAPL", "strategy": "SELL_PUT", "action": "sell put"}
    store.save_card("AAPL_SELL_PUT_2026-03-06", "AAPL", "SELL_PUT", card, signal_hash="abc123")
    result = store.get_card("AAPL", "SELL_PUT")
    assert result["action"] == "sell put"
    store.close()

def test_get_card_returns_none_when_expired(tmp_path):
    store = CardStore(str(tmp_path / "cards.db"))
    card = {"ticker": "AAPL"}
    store.save_card("OLD", "AAPL", "SELL_PUT", card, signal_hash="x",
                    created_at=datetime.now() - timedelta(hours=25))
    assert store.get_card("AAPL", "SELL_PUT") is None
    store.close()

def test_save_and_get_analysis(tmp_path):
    store = CardStore(str(tmp_path / "cards.db"))
    store.save_analysis("AAPL",
        fundamentals={"moat": "ecosystem lock-in"},
        valuation={"iron_floor": 163.5, "fair_value": 182.5},
        next_earnings="2026-05-01",
        fundamentals_expires="2026-04-05",
        valuation_expires="2026-05-01")
    f, v = store.get_analysis("AAPL")
    assert f["moat"] == "ecosystem lock-in"
    assert v["iron_floor"] == 163.5
    store.close()

def test_get_analysis_returns_none_when_expired(tmp_path):
    from datetime import date
    store = CardStore(str(tmp_path / "cards.db"))
    store.save_analysis("AAPL",
        fundamentals={"moat": "x"},
        valuation={"iron_floor": 100.0},
        next_earnings="2026-01-01",
        fundamentals_expires="2026-01-01",   # already past
        valuation_expires="2026-01-01")
    f, v = store.get_analysis("AAPL")
    assert f is None
    assert v is None
    store.close()
