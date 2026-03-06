# Card Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a reasoning layer that calls Claude API to generate structured opportunity cards for Sell Put and High Dividend signals, with analysis caching, DingTalk push, and HTML report integration.

**Architecture:** Two-step Claude API calls per signal (Step 1: fundamental analysis with 30d/earnings TTL cache; Step 2: card generation using cached analysis). Cards cached 24h in SQLite. Output to DingTalk + HTML report.

**Tech Stack:** anthropic==0.84.0, sqlite3 (stdlib), httpx (for SSL bypass), existing scanners output types (SellPutSignal, DividendBuySignal).

---

## Context: Existing Types You Must Know

```python
# src/scanners.py — SellPutSignal
@dataclass
class SellPutSignal:
    ticker: str; strike: float; bid: float; dte: int
    expiration: date; apy: float; earnings_risk: bool

# src/dividend_scanners.py — DividendBuySignal
@dataclass
class DividendBuySignal:
    ticker_data: TickerData   # has .ticker, .last_price, .earnings_date,
                              # .days_to_earnings, .dividend_yield, .name
    signal_type: str          # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float
    option_details: Optional[Dict]  # {strike, bid, dte, expiration, apy}

# main.py returns:
sell_put_results: List[Tuple[SellPutSignal, TickerData]]
dividend_signals: List[DividendBuySignal]
```

---

### Task 1: CardStore — SQLite storage

**Files:**
- Create: `src/card_store.py`
- Create: `tests/test_card_store.py`

**Step 1: Write the failing tests**

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_card_store.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.card_store'`

**Step 3: Implement CardStore**

```python
# src/card_store.py
import sqlite3, json, logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class CardStore:
    def __init__(self, db_path: str):
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
        CREATE TABLE IF NOT EXISTS opportunity_cards (
            card_id      TEXT PRIMARY KEY,
            ticker       TEXT NOT NULL,
            strategy     TEXT NOT NULL,
            card_json    TEXT NOT NULL,
            created_at   TEXT NOT NULL,
            signal_hash  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS analysis_cache (
            ticker                TEXT PRIMARY KEY,
            fundamentals_json     TEXT,
            valuation_json        TEXT,
            next_earnings         TEXT,
            cached_at             TEXT,
            fundamentals_expires  TEXT,
            valuation_expires     TEXT
        );
        """)
        self.conn.commit()

    def save_card(self, card_id: str, ticker: str, strategy: str,
                  card: Dict, signal_hash: str,
                  created_at: Optional[datetime] = None):
        ts = (created_at or datetime.now()).isoformat()
        self.conn.execute(
            "INSERT OR REPLACE INTO opportunity_cards VALUES (?,?,?,?,?,?)",
            (card_id, ticker, strategy, json.dumps(card, ensure_ascii=False), ts, signal_hash)
        )
        self.conn.commit()

    def get_card(self, ticker: str, strategy: str,
                 ttl_hours: int = 24) -> Optional[Dict]:
        row = self.conn.execute(
            "SELECT card_json, created_at FROM opportunity_cards "
            "WHERE ticker=? AND strategy=? ORDER BY created_at DESC LIMIT 1",
            (ticker, strategy)
        ).fetchone()
        if not row:
            return None
        created = datetime.fromisoformat(row[1])
        if datetime.now() - created > timedelta(hours=ttl_hours):
            return None
        return json.loads(row[0])

    def save_analysis(self, ticker: str, fundamentals: Dict, valuation: Dict,
                      next_earnings: str, fundamentals_expires: str, valuation_expires: str):
        self.conn.execute(
            "INSERT OR REPLACE INTO analysis_cache VALUES (?,?,?,?,?,?,?)",
            (ticker, json.dumps(fundamentals, ensure_ascii=False),
             json.dumps(valuation, ensure_ascii=False),
             next_earnings, datetime.now().isoformat(),
             fundamentals_expires, valuation_expires)
        )
        self.conn.commit()

    def get_analysis(self, ticker: str) -> Tuple[Optional[Dict], Optional[Dict]]:
        row = self.conn.execute(
            "SELECT fundamentals_json, valuation_json, "
            "fundamentals_expires, valuation_expires "
            "FROM analysis_cache WHERE ticker=?", (ticker,)
        ).fetchone()
        if not row:
            return None, None
        today = datetime.now().date().isoformat()
        f = json.loads(row[0]) if row[2] and row[2] > today else None
        v = json.loads(row[1]) if row[3] and row[3] > today else None
        return f, v

    def close(self):
        self.conn.close()
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_card_store.py -v
```
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/card_store.py tests/test_card_store.py
git commit -m "feat: add CardStore with 24h card cache and analysis cache TTL"
```

---

### Task 2: CardEngine skeleton + config

**Files:**
- Create: `src/card_engine.py`
- Modify: `config.yaml`
- Create: `tests/test_card_engine.py`

**Step 1: Write the failing test**

```python
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
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_card_engine.py -v
```
Expected: `ModuleNotFoundError: No module named 'src.card_engine'`

**Step 3: Implement CardEngine skeleton**

```python
# src/card_engine.py
import logging, os
from datetime import datetime, date
from typing import List, Dict, Any, Optional, Tuple

from src.card_store import CardStore

logger = logging.getLogger(__name__)


class CardEngine:
    """Reasoning layer: Claude API → opportunity cards."""

    def __init__(self, config: dict):
        cfg = config.get("card_engine", {})
        self.model = cfg.get("model", "claude-opus-4-6")
        self.api_key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", "")
        self.dingtalk_webhook = cfg.get("dingtalk_webhook", "")
        self.default_position_size = cfg.get("default_position_size", 10000)
        db_path = cfg.get("card_db_path", "data/card_store.db")
        self.store = CardStore(db_path)
        self._client = None  # lazy init

    def _get_client(self):
        if self._client is None:
            import anthropic, httpx
            self._client = anthropic.Anthropic(
                api_key=self.api_key,
                http_client=httpx.Client(verify=False),
            )
        return self._client

    def process_signals(
        self,
        sell_put_signals: list,
        dividend_signals: list,
    ) -> List[Dict]:
        cards = []
        for signal, ticker_data in sell_put_signals:
            card = self._process_sell_put(signal, ticker_data)
            if card:
                cards.append(card)
        for signal in dividend_signals:
            card = self._process_dividend(signal)
            if card:
                cards.append(card)
        return cards

    def _process_sell_put(self, signal, ticker_data) -> Optional[Dict]:
        raise NotImplementedError

    def _process_dividend(self, signal) -> Optional[Dict]:
        raise NotImplementedError

    def push_dingtalk(self, cards: List[Dict]):
        pass  # Task 5

    def close(self):
        self.store.close()
```

**Step 4: Add config.yaml entries**

Add to `config.yaml`:
```yaml
card_engine:
  enabled: false
  anthropic_api_key: ""        # or set ANTHROPIC_API_KEY env var
  model: "claude-opus-4-6"
  card_db_path: "data/card_store.db"
  dingtalk_webhook: ""         # set DINGTALK_WEBHOOK env var
  default_position_size: 10000
```

**Step 5: Run tests**

```bash
python3 -m pytest tests/test_card_engine.py -v
```
Expected: 2 passed

**Step 6: Commit**

```bash
git add src/card_engine.py tests/test_card_engine.py config.yaml
git commit -m "feat: add CardEngine skeleton with config and CardStore wiring"
```

---

### Task 3: Step 1 — Fundamental analysis with cache

**Files:**
- Modify: `src/card_engine.py`
- Modify: `tests/test_card_engine.py`

**Step 1: Write the failing tests**

```python
# Add to tests/test_card_engine.py
from unittest.mock import patch, MagicMock
from datetime import date, timedelta

def _make_analysis_response():
    import json
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
    from datetime import date, timedelta
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
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_card_engine.py::test_get_analysis_calls_claude_when_cache_empty tests/test_card_engine.py::test_get_analysis_uses_cache_when_fresh -v
```
Expected: AttributeError `_get_analysis`

**Step 3: Implement `_get_analysis`**

Add to `CardEngine` in `src/card_engine.py`:

```python
import json
from datetime import timedelta

def _get_analysis(self, ticker: str, price: float,
                  earnings_date: Optional[date]) -> Tuple[Optional[Dict], Optional[Dict]]:
    """Step 1: Get fundamental analysis, using cache if fresh."""
    f_cache, v_cache = self.store.get_analysis(ticker)
    if f_cache and v_cache:
        logger.debug(f"{ticker}: analysis cache hit")
        return f_cache, v_cache

    logger.info(f"{ticker}: calling Claude for fundamental analysis")
    try:
        client = self._get_client()
        prompt = (
            f"分析 {ticker}，当前价 ${price}，"
            f"下次财报日 {earnings_date or 'unknown'}。\n"
            "返回严格 JSON（不加 markdown/解释）：\n"
            '{"iron_floor": float, "fair_value": float, '
            '"logic_summary": "3-5句基础估值逻辑", '
            '"confidence": "置信说明", '
            '"moat": "护城河一句话", '
            '"risk_factors": [{"desc": str, "level": "HIGH|MEDIUM|LOW"}], '
            '"risk_level": "HIGH|MEDIUM|LOW"}'
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=800,
            system="你是专业交易分析师。只返回严格 JSON，不加任何解释或 markdown。",
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        data = json.loads(raw)

        fundamentals = {
            "moat": data.get("moat", ""),
            "risk_factors": data.get("risk_factors", []),
            "risk_level": data.get("risk_level", "MEDIUM"),
            "confidence": data.get("confidence", ""),
        }
        valuation = {
            "iron_floor": data.get("iron_floor"),
            "fair_value": data.get("fair_value"),
            "logic_summary": data.get("logic_summary", ""),
        }

        # TTL: fundamentals 30 days, valuation expires on next earnings
        f_expires = (date.today() + timedelta(days=30)).isoformat()
        v_expires = earnings_date.isoformat() if earnings_date else f_expires
        next_earnings_str = earnings_date.isoformat() if earnings_date else ""

        self.store.save_analysis(
            ticker, fundamentals, valuation,
            next_earnings=next_earnings_str,
            fundamentals_expires=f_expires,
            valuation_expires=v_expires,
        )
        return fundamentals, valuation

    except Exception as e:
        logger.warning(f"{ticker}: Claude analysis failed: {e}")
        return None, None
```

Also add import at top of `card_engine.py`:
```python
import json
from datetime import timedelta
```

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_card_engine.py -v
```
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/card_engine.py tests/test_card_engine.py
git commit -m "feat: add Step 1 fundamental analysis with 30d/earnings TTL cache"
```

---

### Task 4: Step 2 — Card generation (Sell Put + High Dividend)

**Files:**
- Modify: `src/card_engine.py`
- Modify: `tests/test_card_engine.py`

**Step 1: Write the failing tests**

```python
# Add to tests/test_card_engine.py
from datetime import date
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
    import json
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
    return json.dumps(card, ensure_ascii=False)

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

    # Pre-populate cache
    cached_card = {"ticker": "AAPL", "strategy": "SELL_PUT", "action": "cached action"}
    engine.store.save_card("AAPL_SELL_PUT_2026-03-06", "AAPL", "SELL_PUT",
                           cached_card, signal_hash="abc")

    signal = SellPutSignal("AAPL", 170.0, 1.6, 60, date(2026, 5, 5), 11.8, False)
    td = _make_ticker("AAPL", 185.0)

    with patch.object(engine, '_get_client') as mock_client_fn:
        card = engine._process_sell_put(signal, td)
        assert card["action"] == "cached action"
        assert not mock_client_fn.called  # no API call

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
    )

    div_card_json = json.dumps({
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
```

**Step 2: Run tests to verify they fail**

```bash
python3 -m pytest tests/test_card_engine.py::test_process_sell_put_generates_card tests/test_card_engine.py::test_process_sell_put_uses_24h_cache tests/test_card_engine.py::test_process_dividend_generates_card -v
```
Expected: NotImplementedError

**Step 3: Implement `_process_sell_put` and `_process_dividend`**

Replace the `NotImplementedError` stubs in `src/card_engine.py`:

```python
def _make_signal_hash(self, data: dict) -> str:
    import hashlib
    return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]

def _process_sell_put(self, signal, ticker_data) -> Optional[Dict]:
    from src.scanners import SellPutSignal
    ticker = signal.ticker
    strategy = "SELL_PUT"

    # Check 24h card cache
    cached = self.store.get_card(ticker, strategy)
    if cached:
        logger.debug(f"{ticker}: SELL_PUT card cache hit")
        return cached

    # Step 1: fundamental analysis
    f, v = self._get_analysis(
        ticker, price=ticker_data.last_price,
        earnings_date=ticker_data.earnings_date,
    )

    # Step 2: generate card
    try:
        client = self._get_client()
        prompt = (
            f"策略: Sell Put 收租  标的: {ticker}  当前价: ${ticker_data.last_price}\n"
            f"触发条件: 行权价 ${signal.strike}, 权利金 ${signal.bid}, "
            f"DTE {signal.dte}天, 年化 {signal.apy}%\n"
            f"跨财报: {'是' if signal.earnings_risk else '否'}"
            + (f"（财报 {ticker_data.days_to_earnings}天后，"
               f"需给出 Bull Put Spread 和 Naked Sell Put 双方案对比）"
               if signal.earnings_risk else "") + "\n"
            f"基本面（缓存）: {json.dumps(f or {}, ensure_ascii=False)}\n"
            f"估值（缓存）: {json.dumps(v or {}, ensure_ascii=False)}\n"
            f"默认仓位: ${self.default_position_size}\n\n"
            "生成完整机会卡片 JSON（不加 markdown）。必须包含字段：\n"
            "trigger_reason, action, key_params, one_line_logic, "
            "win_scenarios, risk_points, events, take_profit, stop_loss, "
            "max_loss_usd, max_loss_pct"
            + (", crosses_earnings(true), protected_plan, naked_plan"
               if signal.earnings_risk else "")
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=1200,
            system="你是交易领航员。生成机会卡片，返回严格 JSON，不加任何 markdown 或解释。",
            messages=[{"role": "user", "content": prompt}],
        )
        card_data = json.loads(resp.content[0].text.strip())
        card_data["ticker"] = ticker
        card_data["strategy"] = strategy
        card_data["valuation"] = v or {}
        card_data["fundamentals"] = f or {}

        sig_hash = self._make_signal_hash({"ticker": ticker, "strike": signal.strike, "dte": signal.dte})
        card_id = f"{ticker}_{strategy}_{date.today().isoformat()}"
        self.store.save_card(card_id, ticker, strategy, card_data, sig_hash)
        return card_data

    except Exception as e:
        logger.warning(f"{ticker}: card generation failed: {e}")
        return None

def _process_dividend(self, signal) -> Optional[Dict]:
    ticker = signal.ticker_data.ticker
    strategy = "HIGH_DIVIDEND"

    cached = self.store.get_card(ticker, strategy)
    if cached:
        logger.debug(f"{ticker}: HIGH_DIVIDEND card cache hit")
        return cached

    td = signal.ticker_data
    f, v = self._get_analysis(
        ticker, price=td.last_price,
        earnings_date=td.earnings_date,
    )

    try:
        client = self._get_client()
        opt = signal.option_details or {}
        prompt = (
            f"策略: 高股息防御双打  标的: {ticker}  当前价: ${td.last_price}\n"
            f"当前股息率: {signal.current_yield:.2f}%（历史 {signal.yield_percentile:.0f} 分位）\n"
            f"年度股息: ${td.dividend_yield or signal.current_yield}\n"
            + (f"期权方案: 卖 Put ${opt.get('strike')} "
               f"权利金 ${opt.get('bid')} DTE {opt.get('dte')}天\n"
               if opt else "信号类型: 纯股票买入\n")
            + f"基本面（缓存）: {json.dumps(f or {}, ensure_ascii=False)}\n"
            f"估值（缓存）: {json.dumps(v or {}, ensure_ascii=False)}\n"
            f"默认仓位: ${self.default_position_size}\n\n"
            "生成完整高股息双打机会卡片 JSON（不加 markdown）。必须包含：\n"
            "trigger_reason, action, key_params, one_line_logic, "
            "win_scenarios, risk_points, events, take_profit, stop_loss, "
            "max_loss_usd, max_loss_pct"
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=1200,
            system="你是交易领航员。生成机会卡片，返回严格 JSON，不加任何 markdown 或解释。",
            messages=[{"role": "user", "content": prompt}],
        )
        card_data = json.loads(resp.content[0].text.strip())
        card_data["ticker"] = ticker
        card_data["strategy"] = strategy
        card_data["valuation"] = v or {}
        card_data["fundamentals"] = f or {}

        sig_hash = self._make_signal_hash({"ticker": ticker, "yield": signal.current_yield})
        card_id = f"{ticker}_{strategy}_{date.today().isoformat()}"
        self.store.save_card(card_id, ticker, strategy, card_data, sig_hash)
        return card_data

    except Exception as e:
        logger.warning(f"{ticker}: dividend card generation failed: {e}")
        return None
```

**Step 4: Run all tests**

```bash
python3 -m pytest tests/test_card_engine.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/card_engine.py tests/test_card_engine.py
git commit -m "feat: implement Sell Put and High Dividend card generation with Claude API"
```

---

### Task 5: DingTalk push

**Files:**
- Modify: `src/card_engine.py`
- Modify: `tests/test_card_engine.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_card_engine.py
import json as json_module

def test_push_dingtalk_sends_markdown(tmp_path):
    config = make_config()
    config["card_engine"]["card_db_path"] = str(tmp_path / "cards.db")
    config["card_engine"]["dingtalk_webhook"] = "https://oapi.dingtalk.com/robot/send?access_token=test"
    engine = CardEngine(config)

    cards = [{
        "ticker": "AAPL", "strategy": "SELL_PUT",
        "trigger_reason": "跌入便宜区间",
        "action": "卖出 6月 $170 Put",
        "key_params": {"strike": 170, "dte": 60, "premium": 1.6, "apy": 11.8},
        "win_scenarios": [{"prob": 0.85, "desc": "安全收租"}],
        "valuation": {"iron_floor": 163.5, "fair_value": 182.5, "logic_summary": "EPS × PE"},
        "events": [{"date": "2026-05-01", "type": "财报", "days_away": 45}],
        "take_profit": "赚80%止盈", "stop_loss": "营收增速恶化",
        "max_loss_usd": 9.1, "max_loss_pct": 0.09,
        "crosses_earnings": True,
        "protected_plan": {"desc": "Bull Put Spread", "net_premium": 0.9, "max_loss": 9.1, "note": "推荐"},
        "naked_plan": {"desc": "Naked Sell Put", "net_premium": 1.6, "max_loss": 168.4, "note": "高风险"},
    }]

    with patch("requests.post") as mock_post:
        mock_post.return_value.status_code = 200
        engine.push_dingtalk(cards)
        assert mock_post.called
        payload = json_module.loads(mock_post.call_args[1]["data"])
        assert payload["msgtype"] == "markdown"
        assert "AAPL" in payload["markdown"]["text"]
        assert "Bull Put Spread" in payload["markdown"]["text"]

    engine.close()
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_card_engine.py::test_push_dingtalk_sends_markdown -v
```
Expected: FAIL (push_dingtalk is a no-op)

**Step 3: Implement `push_dingtalk`**

Add to `src/card_engine.py` (and `import requests` at top):

```python
import requests

def _format_card_markdown(self, card: Dict) -> str:
    ticker = card.get("ticker", "")
    strategy_label = "Sell Put 收租" if card.get("strategy") == "SELL_PUT" else "高股息双打"
    p = card.get("key_params", {})
    v = card.get("valuation", {})
    events = card.get("events", [])
    event_str = "、".join(f"{e.get('type','')} {e.get('days_away','')}天后" for e in events) or "无"

    lines = [
        f"## 🟢 {strategy_label} · {ticker}",
        f"**触发**: {card.get('trigger_reason','')}",
        f"**建议**: {card.get('action','')}",
        "",
    ]

    if card.get("crosses_earnings") and card.get("protected_plan"):
        pp = card["protected_plan"]
        np_ = card["naked_plan"]
        lines += [
            f"⚠️ **跨财报 — 双方案对比**",
            f"方案A（推荐）· {pp.get('desc','')}｜权利金 ${pp.get('net_premium',0):.2f}｜最大亏损 ${pp.get('max_loss',0):.2f}/股｜{pp.get('note','')}",
            f"方案B · {np_.get('desc','')}｜权利金 ${np_.get('net_premium',0):.2f}｜最大亏损 ${np_.get('max_loss',0):.2f}/股｜{np_.get('note','')}",
            "",
        ]
    else:
        if p.get("strike"):
            lines.append(f"行权价 ${p.get('strike')} | DTE {p.get('dte')}天 | 年化 {p.get('apy',0):.1f}%")

    iron = v.get("iron_floor")
    fair = v.get("fair_value")
    logic = v.get("logic_summary", "")
    if iron and fair:
        lines.append(f"💡 估值: 铁底 ${iron} | 公允价 ${fair}")
        if logic:
            lines.append(f"  {logic}")

    lines += [
        f"⚠️ 事件: {event_str}",
        f"🛑 止盈: {card.get('take_profit','')}",
        f"🔴 止损: {card.get('stop_loss','')}",
        f"最坏亏损: ${card.get('max_loss_usd',0):.1f}/股",
    ]
    return "\n".join(lines)

def push_dingtalk(self, cards: List[Dict]):
    if not self.dingtalk_webhook or not cards:
        return
    for card in cards:
        try:
            text = self._format_card_markdown(card)
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": f"交易机会: {card.get('ticker','')}",
                    "text": text,
                },
            }
            resp = requests.post(
                self.dingtalk_webhook,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                verify=False,
                timeout=10,
            )
            if resp.status_code == 200:
                logger.info(f"DingTalk pushed: {card.get('ticker')} {card.get('strategy')}")
            else:
                logger.warning(f"DingTalk push failed: {resp.status_code}")
        except Exception as e:
            logger.warning(f"DingTalk push error: {e}")
```

**Step 4: Run all tests**

```bash
python3 -m pytest tests/test_card_engine.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/card_engine.py tests/test_card_engine.py
git commit -m "feat: add DingTalk push with markdown card format and earnings dual-plan"
```

---

### Task 6: HTML report integration

**Files:**
- Modify: `src/html_report.py`
- Modify: `tests/test_report.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_report.py
from src.html_report import format_html_report

def test_html_report_includes_opportunity_cards():
    cards = [{
        "ticker": "AAPL", "strategy": "SELL_PUT",
        "trigger_reason": "跌入便宜区间",
        "action": "卖出 6月 $170 Put",
        "key_params": {"strike": 170, "dte": 60, "premium": 1.6, "apy": 11.8},
        "win_scenarios": [{"prob": 0.85, "desc": "安全收租"}],
        "valuation": {"iron_floor": 163.5, "fair_value": 182.5,
                      "logic_summary": "EPS × PE 估值"},
        "fundamentals": {"moat": "iOS 生态"},
        "events": [], "take_profit": "赚80%止盈",
        "stop_loss": "营收恶化", "max_loss_usd": 9.1, "max_loss_pct": 0.09,
    }]
    html = format_html_report(
        scan_date=date(2026, 3, 6), data_source="IBKR",
        universe_count=22, iv_low=[], iv_high=[],
        ma200_bullish=[], ma200_bearish=[], leaps=[],
        sell_puts=[], elapsed_seconds=1.0,
        opportunity_cards=cards,
    )
    assert "AAPL" in html
    assert "Sell Put 收租" in html or "SELL_PUT" in html
    assert "铁底" in html
    assert "查看详细分析" in html
```

**Step 2: Run test to verify it fails**

```bash
python3 -m pytest tests/test_report.py::test_html_report_includes_opportunity_cards -v
```
Expected: FAIL (format_html_report doesn't accept opportunity_cards)

**Step 3: Add `opportunity_cards` to `format_html_report`**

In `src/html_report.py`, find the function signature and add the parameter:

```python
def format_html_report(
    ...,
    opportunity_cards: Optional[List[Dict]] = None,   # ADD THIS
) -> str:
```

Then add a new section before the closing `</body>` tag in the HTML template. Find the section that generates the HTML body and add:

```python
# After existing sections, before </main>
cards_html = _render_cards_section(opportunity_cards or [])
```

Add this helper function:

```python
def _render_cards_section(cards: List[Dict]) -> str:
    if not cards:
        return ""
    rows = []
    for card in cards:
        ticker = card.get("ticker", "")
        strategy = card.get("strategy", "")
        strategy_label = "Sell Put 收租" if strategy == "SELL_PUT" else "高股息双打"
        v = card.get("valuation", {})
        iron = v.get("iron_floor", "—")
        fair = v.get("fair_value", "—")
        logic = v.get("logic_summary", "")
        fundamentals = card.get("fundamentals", {})

        crosses = card.get("crosses_earnings", False)
        dual_plan_html = ""
        if crosses and card.get("protected_plan"):
            pp = card["protected_plan"]
            np_ = card["naked_plan"]
            dual_plan_html = f"""
            <div class="dual-plan">
              <div class="plan-item recommended">
                <span class="plan-label">方案A（推荐）· Bull Put Spread</span>
                <span>权利金 ${pp.get('net_premium',0):.2f} | 最大亏损 ${pp.get('max_loss',0):.2f}/股</span>
                <span class="plan-note">{pp.get('note','')}</span>
              </div>
              <div class="plan-item">
                <span class="plan-label">方案B · Naked Sell Put</span>
                <span>权利金 ${np_.get('net_premium',0):.2f} | 最大亏损 ${np_.get('max_loss',0):.2f}/股</span>
                <span class="plan-note">{np_.get('note','')}</span>
              </div>
            </div>"""

        detail_id = f"detail_{ticker}_{strategy}"
        rows.append(f"""
        <div class="card">
          <div class="card-header">
            <span class="strategy-badge">{strategy_label}</span>
            <span class="ticker">{ticker}</span>
          </div>
          <div class="card-body">
            <p class="trigger">📍 {card.get('trigger_reason','')}</p>
            <p class="action"><strong>{card.get('action','')}</strong> — {card.get('one_line_logic','')}</p>
            {dual_plan_html}
            <div class="valuation-summary">
              💡 铁底 ${iron} | 公允价 ${fair}
              <p class="logic-summary">{logic}</p>
              <button class="detail-toggle" onclick="document.getElementById('{detail_id}').classList.toggle('hidden')">
                查看详细分析 ▼
              </button>
              <div id="{detail_id}" class="detail-panel hidden">
                <pre>{fundamentals}</pre>
              </div>
            </div>
            <div class="risk-row">
              🛑 止盈: {card.get('take_profit','')} &nbsp; 🔴 止损: {card.get('stop_loss','')}
            </div>
            <div class="max-loss">最坏亏损: ${card.get('max_loss_usd',0):.1f}/股</div>
          </div>
        </div>""")

    return f"""
    <section class="opportunities">
      <h2>机会卡片</h2>
      {"".join(rows)}
    </section>
    <style>
      .opportunities {{ margin: 24px 0; }}
      .card {{ background: #fff; border-radius: 12px; padding: 20px;
               margin: 12px 0; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
      .strategy-badge {{ background: #34c759; color: #fff; border-radius: 6px;
                         padding: 2px 8px; font-size: 12px; }}
      .ticker {{ font-size: 20px; font-weight: 600; margin-left: 8px; }}
      .trigger {{ color: #666; font-size: 14px; }}
      .dual-plan {{ background: #f5f5f7; border-radius: 8px; padding: 12px; margin: 8px 0; }}
      .plan-item {{ margin: 6px 0; }}
      .plan-item.recommended {{ font-weight: 600; }}
      .plan-label {{ color: #1d1d1f; }}
      .plan-note {{ color: #666; font-size: 13px; }}
      .valuation-summary {{ margin: 12px 0; padding: 12px;
                            background: #f5f5f7; border-radius: 8px; }}
      .logic-summary {{ font-size: 13px; color: #444; margin: 4px 0; }}
      .detail-toggle {{ background: none; border: none; color: #0071e3;
                        cursor: pointer; font-size: 13px; padding: 4px 0; }}
      .detail-panel {{ background: #fff; border-radius: 6px; padding: 8px;
                       margin-top: 8px; font-size: 12px; overflow-x: auto; }}
      .hidden {{ display: none; }}
      .max-loss {{ color: #ff3b30; font-size: 14px; font-weight: 500; }}
    </style>"""
```

In the main `format_html_report` function, inject `cards_html` into the returned HTML string (before `</body>`).

**Step 4: Run tests**

```bash
python3 -m pytest tests/test_report.py -v
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/html_report.py tests/test_report.py
git commit -m "feat: add opportunity cards section to HTML report with detail toggle"
```

---

### Task 7: Wire into main.py

**Files:**
- Modify: `src/main.py`
- Modify: `tests/test_integration.py`

**Step 1: Write the failing test**

```python
# Add to tests/test_integration.py
def test_main_card_engine_disabled_by_default():
    """card_engine disabled by default — no CardEngine import errors."""
    from src.config import load_config
    config = load_config("config.yaml")
    assert config.get("card_engine", {}).get("enabled", False) is False
```

**Step 2: Run test**

```bash
python3 -m pytest tests/test_integration.py::test_main_card_engine_disabled_by_default -v
```
Expected: PASS (already false in config)

**Step 3: Add CardEngine wiring to main.py**

In `src/main.py`, add import at top:

```python
from src.card_engine import CardEngine
```

In `run_scan()`, after the dividend scanner block (Step 5) and before Step 6 (report generation), add:

```python
    # Step 5.5: Opportunity card generation (reasoning layer)
    opportunity_cards = []
    card_config = config.get("card_engine", {})
    if card_config.get("enabled", False):
        try:
            import os
            if not card_config.get("anthropic_api_key"):
                card_config["anthropic_api_key"] = os.environ.get("ANTHROPIC_API_KEY", "")
            if not card_config.get("dingtalk_webhook"):
                card_config["dingtalk_webhook"] = os.environ.get("DINGTALK_WEBHOOK", "")
            card_engine = CardEngine(config)
            opportunity_cards = card_engine.process_signals(
                sell_put_signals=sell_put_results,
                dividend_signals=dividend_signals,
            )
            card_engine.push_dingtalk(opportunity_cards)
            logger.info(f"Card engine: {len(opportunity_cards)} cards generated")
            card_engine.close()
        except Exception as e:
            logger.error(f"Card engine failed: {e}", exc_info=True)
```

In the `format_html_report(...)` call, add:
```python
        opportunity_cards=opportunity_cards or None,
```

**Step 4: Run full test suite**

```bash
python3 -m pytest -x -q
```
Expected: all pass

**Step 5: Commit**

```bash
git add src/main.py tests/test_integration.py
git commit -m "feat: wire CardEngine into main.py scan pipeline"
```

---

### Task 8: End-to-end smoke test

**Files:**
- Create: `tests/test_card_engine_smoke.py`

**Step 1: Write smoke test (mocked Claude)**

```python
# tests/test_card_engine_smoke.py
"""Smoke test: full process_signals flow with mocked Claude API."""
import pytest, json
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
    # Second run should use cache (0 API calls)
    with patch.object(engine, '_get_client') as mock_client_fn2:
        cards2 = engine.process_signals(sell_put_signals=[(signal, td)], dividend_signals=[])
        assert not mock_client_fn2.called
        assert len(cards2) == 1

    engine.close()
```

**Step 2: Run smoke test**

```bash
python3 -m pytest tests/test_card_engine_smoke.py -v
```
Expected: PASS

**Step 3: Run full suite**

```bash
python3 -m pytest -q
```
Expected: all pass

**Step 4: Final commit**

```bash
git add tests/test_card_engine_smoke.py
git commit -m "test: add end-to-end smoke test for CardEngine with cache verification"
```
