# tests/test_card_engine_smoke.py
"""Smoke test: full process_signals flow with mocked Claude API."""
import pytest
import json
from datetime import date
from unittest.mock import patch, MagicMock
from src.card_engine import CardEngine
from src.scanners import SellPutSignal
from src.data_engine import TickerData


def make_td(ticker, price=100.0):
    return TickerData(
        ticker=ticker, name=ticker, market="US",
        last_price=price, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=price-1,
        earnings_date=None, days_to_earnings=None,
        dividend_yield=None, dividend_yield_5y_percentile=None,
        dividend_quality_score=None, consecutive_years=None,
        dividend_growth_5y=None, payout_ratio=None, payout_type=None,
        roe=None, debt_to_equity=None, industry=None, sector=None,
        free_cash_flow=None,
    )


def test_full_sell_put_flow(tmp_path):
    config = {
        "card_engine": {
            "enabled": True,
            "anthropic_api_key": "sk-test",
            "model": "claude-haiku-4-5-20251001",
            "card_db_path": str(tmp_path / "cards.db"),
            "dingtalk_webhook": "",
            "default_position_size": 10000,
        }
    }
    engine = CardEngine(config)

    analysis_json = json.dumps({
        "iron_floor": 163.5, "fair_value": 182.5,
        "logic_summary": "EPS × PE", "confidence": "高",
        "moat": "生态锁定", "risk_factors": [], "risk_level": "MEDIUM"
    })
    card_json = json.dumps({
        "trigger_reason": "触发条件", "action": "卖 Put",
        "key_params": {}, "one_line_logic": "安全垫充足",
        "win_scenarios": [], "risk_points": [], "events": [],
        "take_profit": "80%止盈", "stop_loss": "基本面止损",
        "max_loss_usd": 9.1, "max_loss_pct": 0.09,
    })

    mock_resp1 = MagicMock()
    mock_resp1.content[0].text = analysis_json
    mock_resp2 = MagicMock()
    mock_resp2.content[0].text = card_json

    signal = SellPutSignal("AAPL", 170.0, 1.6, 60, date(2026, 5, 5), 11.8, False)
    td = make_td("AAPL", 185.0)

    with patch.object(engine, '_get_client') as mock_client_fn:
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = [mock_resp1, mock_resp2]
        mock_client_fn.return_value = mock_client

        cards = engine.process_signals(
            sell_put_signals=[(signal, td)],
            dividend_signals=[],
        )

    assert len(cards) == 1
    assert cards[0]["ticker"] == "AAPL"
    assert cards[0]["strategy"] == "SELL_PUT"

    # Second run: should use 24h cache — zero API calls
    with patch.object(engine, '_get_client') as mock_client_fn2:
        cards2 = engine.process_signals(sell_put_signals=[(signal, td)], dividend_signals=[])
        assert not mock_client_fn2.called
        assert len(cards2) == 1

    engine.close()
