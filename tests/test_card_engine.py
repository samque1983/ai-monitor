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


from datetime import date, timedelta
import json


def _make_analysis_response():
    return json.dumps({
        "iron_floor": 163.5,
        "fair_value": 182.5,
        "logic_summary": "铁底基于 iCloud+App Store EPS $3.5 × 25x PE。公允价加入 AI 换机增量。当前略高于公允价但未脱离合理区间。地缘折价已计入。",
        "confidence": "基于公开财报数据，EPS 估算±10%",
        "moat": "iOS 生态系统锁定 + 高端品牌溢价",
        "risk_factors": [{"desc": "中国市场收入波动", "level": "MEDIUM"}],
        "risk_level": "MEDIUM"
    })


def test_get_analysis_calls_claude_when_cache_empty(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)

    mock_response = MagicMock()
    mock_response.content[0].text = _make_analysis_response()

    with patch.object(engine, '_get_client') as mock_client_fn:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response
        mock_client_fn.return_value = mock_client

        f, v = engine._get_analysis("AAPL", price=185.0,
                                     earnings_date=date(2026, 5, 1))
        assert f["moat"] == "iOS 生态系统锁定 + 高端品牌溢价"
        assert v["iron_floor"] == 163.5
        assert mock_client.messages.create.called

    engine.close()


def test_get_analysis_uses_cache_when_fresh(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)

    # Populate cache manually
    expires = (date.today() + timedelta(days=20)).isoformat()
    engine.store.save_analysis(
        "AAPL",
        fundamentals={"moat": "cached moat"},
        valuation={"iron_floor": 150.0},
        next_earnings="2026-05-01",
        fundamentals_expires=expires,
        valuation_expires=expires,
    )

    with patch.object(engine, '_get_client') as mock_client_fn:
        f, v = engine._get_analysis("AAPL", price=185.0,
                                     earnings_date=date(2026, 5, 1))
        assert f["moat"] == "cached moat"
        assert not mock_client_fn.called   # no API call

    engine.close()
