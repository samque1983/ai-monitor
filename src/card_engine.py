# src/card_engine.py
import json
import logging
import os
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple

import requests

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

    def _process_sell_put(self, signal, ticker_data) -> Optional[Dict]:
        raise NotImplementedError

    def _process_dividend(self, signal) -> Optional[Dict]:
        raise NotImplementedError

    def push_dingtalk(self, cards: List[Dict]):
        pass  # implemented in Task 5

    def close(self):
        self.store.close()
