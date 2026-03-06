# src/card_engine.py
import json
import logging
import os
import requests
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
        ticker = signal.ticker
        strategy = "SELL_PUT"

        # Check 24h card cache
        cached = self.store.get_card(ticker, strategy)
        if cached:
            logger.debug(f"{ticker}: SELL_PUT card cache hit")
            return cached

        try:
            # Step 1: fundamental analysis
            f, v = self._get_analysis(
                ticker, price=ticker_data.last_price,
                earnings_date=ticker_data.earnings_date,
            )

            # Step 2: generate card
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
        try:
            f, v = self._get_analysis(
                ticker, price=td.last_price,
                earnings_date=td.earnings_date,
            )

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

    def close(self):
        self.store.close()
