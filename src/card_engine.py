# src/card_engine.py
import json
import logging
import os
from datetime import date, timedelta
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
            import anthropic
            import httpx
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

    def _make_signal_hash(self, data: dict) -> str:
        import hashlib
        return hashlib.md5(json.dumps(data, sort_keys=True).encode()).hexdigest()[:8]

    def _get_analysis(self, ticker: str, price: float,
                      earnings_date) -> tuple:
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

    def _process_sell_put(self, signal, ticker_data) -> Optional[Dict]:
        raise NotImplementedError

    def _process_dividend(self, signal) -> Optional[Dict]:
        raise NotImplementedError

    def push_dingtalk(self, cards: List[Dict]):
        pass  # implemented in Task 5

    def close(self):
        self.store.close()
