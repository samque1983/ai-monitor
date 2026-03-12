"""Risk pipeline: accepts List[PositionRecord] directly, no FlexClient dependency."""
import logging
from datetime import date
from typing import List, Dict, Optional, Tuple

from src.flex_client import PositionRecord, AccountSummary
from src.option_strategies import OptionStrategyRecognizer
from src.strategy_risk import (
    StrategyRiskEngine, StrategyRiskReport,
    generate_strategy_suggestion, generate_portfolio_summary,
)
from src.portfolio_report import generate_html_report

logger = logging.getLogger(__name__)


def enrich_greeks(positions: List[PositionRecord]) -> None:
    """Fill in missing Greeks (delta=0) for OPT positions using MarketDataProvider.

    Mutates positions in place. Silently skips on any provider error.
    """
    opt_missing = [p for p in positions
                   if p.asset_category == "OPT" and p.delta == 0.0]
    if not opt_missing:
        return

    try:
        from src.market_data import MarketDataProvider
        mdp = MarketDataProvider()
        by_symbol: Dict[str, List[PositionRecord]] = {}
        for p in opt_missing:
            by_symbol.setdefault(p.underlying_symbol or p.symbol, []).append(p)

        for symbol, legs in by_symbol.items():
            try:
                chain = mdp.get_options_chain(symbol)
                if not chain:
                    continue
                for p in legs:
                    match = _find_option_in_chain(chain, p)
                    if match:
                        p.delta = float(match.get("delta") or 0.0)
                        p.gamma = float(match.get("gamma") or 0.0)
                        p.theta = float(match.get("theta") or 0.0)
                        p.vega  = float(match.get("vega")  or 0.0)
            except Exception as e:
                logger.debug(f"Greeks enrichment skipped for {symbol}: {e}")
    except Exception as e:
        logger.debug(f"Greeks enrichment unavailable: {e}")


def _find_option_in_chain(chain: list, p: PositionRecord) -> Optional[dict]:
    """Find matching option in chain by put_call, strike, expiry."""
    for opt in chain:
        if (str(opt.get("option_type", "")).upper()[:1] == p.put_call
                and abs(float(opt.get("strike") or 0) - p.strike) < 0.01
                and str(opt.get("expiry", "")).replace("-", "") == p.expiry):
            return opt
    return None


def run_pipeline(
    positions: List[PositionRecord],
    account_summary: AccountSummary,
    account_key: str,
    account_name: str,
    llm_cfg: dict,
) -> Tuple[StrategyRiskReport, str]:
    """Run the full 3-layer risk pipeline and return (report, html).

    Args:
        positions: list of PositionRecord (Greeks may be 0; will be enriched)
        account_summary: NLV, margin, cushion
        account_key: account identifier (e.g. "ALICE")
        account_name: display name (e.g. "samque")
        llm_cfg: LLM config dict with keys provider/api_key/model (empty = no LLM)

    Returns:
        (StrategyRiskReport, html_string)
    """
    enrich_greeks(positions)

    # Layer 1: strategy recognition
    recognizer = OptionStrategyRecognizer()
    strategies = recognizer.recognize(positions)

    # Layer 2: risk analysis
    engine = StrategyRiskEngine()
    report = engine.analyze(strategies, account_summary)
    report.account_id = account_key
    report.report_date = date.today().isoformat()

    # Layer 3: LLM suggestions (skipped if no api_key)
    for alert in report.alerts:
        if alert.severity == "red":
            alert.ai_suggestion = generate_strategy_suggestion(alert, llm_cfg)
    report.portfolio_summary = generate_portfolio_summary(report, llm_cfg)

    html = generate_html_report(report)
    return report, html
