# tests/test_card_engine.py
import pytest
from unittest.mock import patch, MagicMock
from src.card_engine import CardEngine

def make_config():
    return {
        "card_engine": {
            "enabled": True,
            "anthropic_api_key": "sk-test",
            "model": "claude-haiku-4-5-20251001",
            "dingtalk_webhook": "",
            "default_position_size": 10000,
            "card_db_path": ":memory:",
        }
    }

def test_card_engine_init(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)
    assert engine is not None
    engine.close()

def test_process_signals_returns_empty_with_no_signals(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)
    result = engine.process_signals(sell_put_signals=[], dividend_signals=[])
    assert result == []
    engine.close()
