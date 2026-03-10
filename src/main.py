import os
import sys
import time
import logging
from datetime import date
from typing import Dict, List, Tuple

from src.config import load_config
from src.data_loader import fetch_universe
from src.market_data import MarketDataProvider
from src.data_engine import TickerData, build_ticker_data
from src.scanners import (
    scan_iv_extremes,
    scan_ma200_crossover,
    scan_leaps_setup,
    scan_sell_put,
    scan_iv_momentum,
    scan_earnings_gap,
)
from src.report import format_report
from src.html_report import format_html_report
from src.email_stub import send_email
from src.dividend_store import DividendStore
from src.financial_service import FinancialServiceAnalyzer
from src.dividend_scanners import scan_dividend_pool_weekly, scan_dividend_buy_signal, bootstrap_yield_history
from src.card_engine import CardEngine

logger = logging.getLogger(__name__)


def _build_agent_payload(
    sell_puts, iv_low, iv_high, ma200_bull, ma200_bear,
    leaps, earnings_gaps, earnings_gap_ticker_map,
    iv_momentum, dividend_signals,
) -> list:
    """Build the flat list of signal dicts to push to the agent API."""
    signals = []

    for signal, t in (sell_puts or []):
        entry = {
            "signal_type": "sell_put",
            "ticker": signal.ticker,
            "strike": float(signal.strike),
            "dte": signal.dte,
            "bid": float(signal.bid),
            "apy": round(float(signal.apy), 1),
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        }
        signals.append(entry)
        if signal.earnings_risk:
            signals.append({**entry, "signal_type": "sell_put_earnings_risk"})

    for t in (iv_low or []):
        signals.append({
            "signal_type": "iv_low",
            "ticker": t.ticker,
            "iv_rank": round(float(t.iv_rank), 1) if t.iv_rank is not None else None,
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for t in (iv_high or []):
        signals.append({
            "signal_type": "iv_high",
            "ticker": t.ticker,
            "iv_rank": round(float(t.iv_rank), 1) if t.iv_rank is not None else None,
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for t in (ma200_bull or []):
        pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
        signals.append({
            "signal_type": "ma200_bullish",
            "ticker": t.ticker,
            "last_price": round(float(t.last_price), 2),
            "ma200": round(float(t.ma200), 2),
            "pct": round(pct, 2),
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for t in (ma200_bear or []):
        pct = ((t.last_price - t.ma200) / t.ma200 * 100) if t.ma200 else 0
        signals.append({
            "signal_type": "ma200_bearish",
            "ticker": t.ticker,
            "last_price": round(float(t.last_price), 2),
            "ma200": round(float(t.ma200), 2),
            "pct": round(pct, 2),
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for t in (leaps or []):
        ma50w_val = round(float(t.ma50w), 2) if t.ma50w is not None else None
        ma50w_pct = round((t.last_price - t.ma50w) / t.ma50w * 100, 1) if t.ma50w else None
        signals.append({
            "signal_type": "leaps",
            "ticker": t.ticker,
            "last_price": round(float(t.last_price), 2),
            "ma200": round(float(t.ma200), 2) if t.ma200 is not None else None,
            "ma50w": ma50w_val,
            "ma50w_pct": ma50w_pct,
            "rsi14": round(float(t.rsi14), 1) if t.rsi14 is not None else None,
            "iv_rank": round(float(t.iv_rank), 1) if t.iv_rank is not None else None,
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for g in (earnings_gaps or []):
        td = (earnings_gap_ticker_map or {}).get(g.ticker)
        signals.append({
            "signal_type": "earnings_gap",
            "ticker": g.ticker,
            "avg_gap": round(float(g.avg_gap), 1),
            "up_ratio": round(float(g.up_ratio), 1),
            "max_gap": round(float(g.max_gap), 1),
            "days_to_earnings": td.days_to_earnings if td else None,
            "iv_rank": round(float(td.iv_rank), 1) if td and td.iv_rank is not None else None,
            "sample_count": g.sample_count,
            "high_iv_risk": bool(td.iv_rank is not None and td.iv_rank > 70) if td else False,
        })

    for t in (iv_momentum or []):
        signals.append({
            "signal_type": "iv_momentum",
            "ticker": t.ticker,
            "iv_momentum": round(float(t.iv_momentum), 1) if t.iv_momentum is not None else None,
            "iv_rank": round(float(t.iv_rank), 1) if t.iv_rank is not None else None,
            "earnings_date": str(t.earnings_date) if t.earnings_date else None,
            "days_to_earnings": t.days_to_earnings,
        })

    for s in (dividend_signals or []):
        td = s.ticker_data
        opt = s.option_details
        signals.append({
            "signal_type": "dividend",
            "ticker": td.ticker,
            "last_price": round(float(td.last_price), 2),
            "current_yield": round(float(s.current_yield), 2),
            "yield_percentile": round(float(s.yield_percentile), 0),
            "quality_score": round(float(td.dividend_quality_score), 0) if td.dividend_quality_score is not None else None,
            "payout_ratio": round(float(td.payout_ratio), 1) if td.payout_ratio is not None else None,
            "earnings_date": str(td.earnings_date) if td.earnings_date else None,
            "days_to_earnings": td.days_to_earnings,
            "option_strike": round(float(opt["strike"]), 0) if opt else None,
            "option_dte": opt["dte"] if opt else None,
            "option_bid": round(float(opt["bid"]), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_ask": round(float(opt.get("ask", 0)), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_mid": round(float(opt.get("mid", 0)), 2) if opt and not opt.get("sell_put_illiquid") else None,
            "option_apy": round(float(opt["apy"]), 1) if opt and not opt.get("sell_put_illiquid") else None,
            "option_spread_pct": round(float(opt["spread_pct"]), 1) if opt else None,
            "option_liquidity_warn": bool(opt.get("liquidity_warn", False)) if opt else False,
            "option_illiquid": bool(opt.get("sell_put_illiquid", False)) if opt else False,
            "combined_apy": round(float(s.current_yield) + float(opt["apy"]), 1) if opt and not opt.get("sell_put_illiquid") else None,
            "forward_dividend_rate": round(float(s.forward_dividend_rate), 2) if s.forward_dividend_rate is not None else None,
            "max_yield_5y": round(float(s.max_yield_5y), 2) if s.max_yield_5y is not None else None,
            "floor_price": round(float(s.floor_price), 2) if s.floor_price is not None else None,
            "floor_downside_pct": s.floor_downside_pct,
            "data_age_days": s.data_age_days,
            "needs_reeval": s.needs_reeval,
            "quality_breakdown": td.quality_breakdown,
            "analysis_text": td.analysis_text or "",
        })

    return signals


def setup_logging(log_dir: str):
    """Configure logging to file and stderr."""
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, f"radar_{date.today()}.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stderr),
        ],
    )


def run_scan(config_path: str = "config.yaml"):
    """Main scan orchestration."""
    start_time = time.time()
    config = load_config(config_path)

    # Allow Docker / env-based overrides for IBKR connection and agent URL
    if os.environ.get("IBKR_TWS_HOST"):
        config.setdefault("ibkr", {})["host"] = os.environ["IBKR_TWS_HOST"]
        config.setdefault("data_sources", {}).setdefault("ibkr_tws", {})["host"] = os.environ["IBKR_TWS_HOST"]
    if os.environ.get("IBKR_TWS_PORT"):
        port = int(os.environ["IBKR_TWS_PORT"])
        config.setdefault("ibkr", {})["port"] = port
        config.setdefault("data_sources", {}).setdefault("ibkr_tws", {})["port"] = port
    if os.environ.get("AGENT_URL"):
        config.setdefault("agent", {})["url"] = os.environ["AGENT_URL"]

    setup_logging(os.environ.get("LOG_DIR") or config["reports"]["log_dir"])
    logger.info("V1.9 Quant Radar starting")

    # Step 1: Load universe
    logger.info("Fetching universe from CSV...")
    tickers, target_buys = fetch_universe(config["csv_url"])
    logger.info(f"Universe: {len(tickers)} tickers, {len(target_buys)} target buys")

    # Step 2: Connect to market data
    iv_db_path = os.environ.get("IV_DB_PATH") or config["data"]["iv_history_db"]
    os.makedirs(os.path.dirname(iv_db_path) or ".", exist_ok=True)
    provider = MarketDataProvider(
        ibkr_config=config.get("ibkr"),
        iv_db_path=iv_db_path,
        config=config,
    )
    data_source = "IBKR Gateway" if provider.ibkr else "yfinance"

    # Step 3: Build ticker data
    all_data: List[TickerData] = []
    skipped: List[Tuple[str, str]] = []  # (ticker, reason)
    today = date.today()

    for ticker in tickers:
        try:
            td = build_ticker_data(ticker, provider, reference_date=today)
            if td:
                all_data.append(td)
            else:
                skipped.append((ticker, "无价格数据 (no price data)"))
        except Exception as e:
            skipped.append((ticker, str(e)))

    logger.info(f"Processed {len(all_data)} tickers, {len(skipped)} skipped")

    # Step 4: Run scanners
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

    # Phase 2: IV Momentum
    scanner_config = config.get("scanners", {})
    iv_momentum = scan_iv_momentum(
        all_data,
        threshold=scanner_config.get("iv_momentum_threshold", 30)
    )

    # Phase 2: Earnings Gap
    earnings_gaps = scan_earnings_gap(
        all_data,
        provider,
        days_threshold=scanner_config.get("earnings_gap_days", 3),
    )
    earnings_gap_ticker_map = {td.ticker: td for td in all_data}

    # Module 5: Sell Put
    sell_put_results = []
    for td in all_data:
        if td.ticker in target_buys and not provider.should_skip_options(td.ticker):
            try:
                options_df = provider.get_options_chain(td.ticker)
                if not options_df.empty:
                    signal = scan_sell_put(td, target_buys[td.ticker], options_df)
                    if signal:
                        sell_put_results.append((signal, td))
            except Exception as e:
                logger.error(f"Sell Put scan failed for {td.ticker}: {e}")

    # Step 5: Dividend scanner (Phase 2, optional)
    dividend_signals = []
    dividend_pool_summary = None
    div_config = config.get("dividend_scanners", {})
    if div_config.get("enabled", False):
        db_path = os.environ.get("DIVIDEND_DB_PATH") or config.get("data", {}).get("dividend_db_path", "data/dividend_pool.db")
        dividend_store = DividendStore(db_path)
        financial_service = FinancialServiceAnalyzer(
            enabled=True,
            fallback_to_rules=True,
            api_key=config.get("card_engine", {}).get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY", ""),
            store=dividend_store,
        )
        try:
            # Weekly refresh: run pool scan if empty or last scan >= 7 days ago
            last_scan = dividend_store.get_last_scan_date()
            needs_weekly = (last_scan is None) or ((today - last_scan).days >= 7)
            if needs_weekly:
                reason = "no previous scan" if last_scan is None else f"last scan {last_scan} ({(today - last_scan).days}d ago)"
                logger.info(f"Dividend weekly scan triggered: {reason}")
                universe = config.get("dividend_universe", [])
                weekly_results = scan_dividend_pool_weekly(
                    universe=universe,
                    provider=provider,
                    financial_service=financial_service,
                    config=config,
                )
                dividend_store.save_pool(weekly_results, version=str(today))
                logger.info(f"Dividend pool updated: {len(weekly_results)} tickers (version={today})")
                # Bootstrap historical yield data (runs once per weekly scan)
                pool_tickers = [t.ticker for t in weekly_results]
                bootstrap_yield_history(pool_tickers, provider, dividend_store)

            current_pool = dividend_store.get_pool_records()
            if current_pool:
                dividend_signals = scan_dividend_buy_signal(
                    pool=current_pool,
                    provider=provider,
                    store=dividend_store,
                    config=config,
                )
                pool_count = len(current_pool)
                dividend_pool_summary = {
                    "count": pool_count,
                    "last_update": str(last_scan or today),
                }
                logger.info(f"Dividend scan: {len(dividend_signals)} buy signals from pool of {pool_count}")
        except Exception as e:
            logger.error(f"Dividend scan failed: {e}", exc_info=True)
        finally:
            dividend_store.close()

    # Step 5.5: Opportunity card generation (reasoning layer)
    opportunity_cards = []
    card_config = config.get("card_engine", {})
    if card_config.get("enabled", False):
        try:
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

    # Step 6: Generate report
    elapsed = time.time() - start_time
    report = format_report(
        scan_date=today,
        data_source=data_source,
        universe_count=len(tickers),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_put_results,
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map=earnings_gap_ticker_map,
        skipped=skipped,
        elapsed_seconds=elapsed,
    )

    html_report = format_html_report(
        scan_date=today,
        data_source=data_source,
        universe_count=len(tickers),
        iv_low=iv_low,
        iv_high=iv_high,
        ma200_bullish=ma200_bull,
        ma200_bearish=ma200_bear,
        leaps=leaps,
        sell_puts=sell_put_results,
        iv_momentum=iv_momentum,
        earnings_gaps=earnings_gaps,
        earnings_gap_ticker_map=earnings_gap_ticker_map,
        skipped=skipped,
        elapsed_seconds=elapsed,
        dividend_signals=dividend_signals or None,
        dividend_pool_summary=dividend_pool_summary,
        opportunity_cards=opportunity_cards or None,
    )

    # Step 6.5: Push scan results to cloud agent (if configured)
    agent_url = config.get("agent", {}).get("url", "")
    agent_api_key = os.environ.get("SCAN_API_KEY") or config.get("agent", {}).get("api_key", "")
    if agent_url:
        try:
            import requests as req_lib
            agent_payload = _build_agent_payload(
                sell_puts=sell_put_results,
                iv_low=iv_low,
                iv_high=iv_high,
                ma200_bull=ma200_bull,
                ma200_bear=ma200_bear,
                leaps=leaps,
                earnings_gaps=earnings_gaps,
                earnings_gap_ticker_map=earnings_gap_ticker_map,
                iv_momentum=iv_momentum,
                dividend_signals=dividend_signals,
            )
            import json as _json, subprocess as _sub, os as _os
            body = _json.dumps({"scan_date": str(today), "results": agent_payload})
            # Try requests first; fall back to curl (uses OS keychain on macOS)
            pushed = False
            try:
                ca_bundle = _os.environ.get("REQUESTS_CA_BUNDLE") or (
                    "/etc/ssl/cert.pem" if _os.path.exists("/etc/ssl/cert.pem") else True
                )
                req_lib.post(
                    f"{agent_url}/api/scan_results",
                    json={"scan_date": str(today), "results": agent_payload},
                    headers={"X-API-Key": agent_api_key},
                    timeout=10,
                    verify=ca_bundle,
                )
                pushed = True
            except Exception as req_err:
                logger.warning(f"requests push failed ({req_err}), trying curl fallback")
                result = _sub.run(
                    ["curl", "-sf", "-X", "POST",
                     "-H", "Content-Type: application/json",
                     "-H", f"X-API-Key: {agent_api_key}",
                     "-d", body,
                     f"{agent_url}/api/scan_results"],
                    capture_output=True, text=True, timeout=15,
                )
                if result.returncode == 0:
                    pushed = True
                else:
                    raise RuntimeError(f"curl push failed: {result.stderr}")
            if pushed:
                logger.info(f"Pushed {len(agent_payload)} signals to agent")
        except Exception as e:
            logger.warning(f"Agent push failed: {e}")

    # Step 6: Output
    print(report)

    # Save to file
    reports_dir = os.environ.get("REPORTS_DIR") or config["reports"]["output_dir"]
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"{today}_radar.txt")
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report saved: {report_path}")

    html_path = os.path.join(reports_dir, f"{today}_radar.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html_report)
    logger.info(f"HTML report saved: {html_path}")

    # Email stub
    send_email(report, config)

    # Cleanup
    provider.disconnect()
    logger.info(f"Scan completed in {elapsed:.1f}s")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_scan(config_file)
