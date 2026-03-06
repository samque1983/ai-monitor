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


import json as json_module  # avoid conflict with json already imported
from src.scanners import SellPutSignal
from src.dividend_scanners import DividendBuySignal
from src.data_engine import TickerData


def _make_ticker(ticker="AAPL", price=185.0, earnings_date=None, days=45):
    return TickerData(
        ticker=ticker, name=ticker, market="US",
        last_price=price, ma200=None, ma50w=None, rsi14=None,
        iv_rank=None, iv_momentum=None, prev_close=price-1,
        earnings_date=earnings_date,
        days_to_earnings=days,
        dividend_yield=None, dividend_yield_5y_percentile=None,
        dividend_quality_score=None, consecutive_years=None,
        dividend_growth_5y=None, payout_ratio=None, payout_type=None,
        roe=None, debt_to_equity=None, industry=None, sector=None,
        free_cash_flow=None,
    )


def _make_card_response(crosses_earnings=False):
    card = {
        "trigger_reason": "跌入便宜区间，IV Rank 42%",
        "action": "卖出 6月 $170 Put",
        "key_params": {"strike": 170, "dte": 60, "premium": 1.6, "apy": 11.8},
        "one_line_logic": "行权价对应便宜底价区间，安全垫充足",
        "win_scenarios": [
            {"prob": 0.85, "desc": "安全收租", "pnl": 160},
            {"prob": 0.15, "desc": "行权接盘", "pnl": -1840},
        ],
        "risk_points": ["中国市场销量波动"],
        "events": [{"date": "2026-05-01", "type": "财报", "days_away": 45}],
        "take_profit": "权利金跌至 $0.32（赚80%）",
        "stop_loss": "服务营收增速 < 8%",
        "max_loss_usd": 9.1,
        "max_loss_pct": 0.09,
    }
    if crosses_earnings:
        card["crosses_earnings"] = True
        card["protected_plan"] = {
            "desc": "Bull Put Spread: 卖 $170P + 买 $160P",
            "net_premium": 0.9, "max_loss": 9.1,
            "note": "适合: 不想赌方向，保护优先"
        }
        card["naked_plan"] = {
            "desc": "Naked Sell Put: 卖 $170P",
            "net_premium": 1.6, "max_loss": 168.4,
            "note": "适合: 仓位小、确信基本面"
        }
    return json_module.dumps(card, ensure_ascii=False)


def test_process_sell_put_generates_card(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)

    signal = SellPutSignal(
        ticker="AAPL", strike=170.0, bid=1.6, dte=60,
        expiration=date(2026, 5, 5), apy=11.8, earnings_risk=False,
    )
    td = _make_ticker("AAPL", 185.0)

    f_mock = {"moat": "iOS lock-in", "risk_level": "MEDIUM", "risk_factors": [], "confidence": "high"}
    v_mock = {"iron_floor": 163.5, "fair_value": 182.5, "logic_summary": "EPS × PE"}

    mock_resp = MagicMock()
    mock_resp.content[0].text = _make_card_response()

    with patch.object(engine, '_get_analysis', return_value=(f_mock, v_mock)), \
         patch.object(engine, '_get_client') as mock_client_fn:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_client_fn.return_value = mock_client

        card = engine._process_sell_put(signal, td)

    assert card is not None
    assert card["ticker"] == "AAPL"
    assert card["strategy"] == "SELL_PUT"
    assert card["trigger_reason"] == "跌入便宜区间，IV Rank 42%"
    assert card["valuation"]["iron_floor"] == 163.5
    engine.close()


def test_process_sell_put_uses_24h_cache(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)

    cached_card = {"ticker": "AAPL", "strategy": "SELL_PUT", "action": "cached action"}
    engine.store.save_card("AAPL_SELL_PUT_2026-03-06", "AAPL", "SELL_PUT",
                           cached_card, signal_hash="abc")

    signal = SellPutSignal("AAPL", 170.0, 1.6, 60, date(2026, 5, 5), 11.8, False)
    td = _make_ticker("AAPL", 185.0)

    with patch.object(engine, '_get_client') as mock_client_fn:
        card = engine._process_sell_put(signal, td)
        assert card["action"] == "cached action"
        assert not mock_client_fn.called

    engine.close()


def test_process_dividend_generates_card(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    engine = CardEngine(config)

    td = _make_ticker("ENB", 39.0)
    td.dividend_yield = 6.2
    signal = DividendBuySignal(
        ticker_data=td, signal_type="STOCK",
        current_yield=6.2, yield_percentile=92.0,
        option_details=None,
    )

    div_card_json = json_module.dumps({
        "trigger_reason": "股息率 6.2%，历史92分位",
        "action": "现货底仓 + 卖浅虚值 Put",
        "key_params": {"yield": 6.2, "percentile": 92},
        "one_line_logic": "股息+权利金双重现金流",
        "win_scenarios": [{"prob": 0.80, "desc": "安全收息", "pnl": 2400}],
        "risk_points": ["能源转型风险"],
        "events": [],
        "take_profit": "综合年化超15%时择机兑现",
        "stop_loss": "派息率 > 100% 立即清仓",
        "max_loss_usd": 390.0,
        "max_loss_pct": 0.039,
    }, ensure_ascii=False)

    f_mock = {"moat": "管道垄断", "risk_level": "LOW", "risk_factors": [], "confidence": "高"}
    v_mock = {"iron_floor": 30.8, "fair_value": 40.4, "logic_summary": "管道 EPS × PE"}

    mock_resp = MagicMock()
    mock_resp.content[0].text = div_card_json

    with patch.object(engine, '_get_analysis', return_value=(f_mock, v_mock)), \
         patch.object(engine, '_get_client') as mock_client_fn:
        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_resp
        mock_client_fn.return_value = mock_client

        card = engine._process_dividend(signal)

    assert card is not None
    assert card["strategy"] == "HIGH_DIVIDEND"
    assert card["ticker"] == "ENB"
    engine.close()
