import os
import sys
import time
import logging
from datetime import date
from typing import List

from src.config import load_config
from src.data_loader import fetch_universe
from src.market_data import MarketDataProvider
from src.data_engine import TickerData, build_ticker_data
from src.scanners import scan_iv_extremes, scan_ma200_crossover, scan_leaps_setup, scan_sell_put
from src.report import format_report
from src.email_stub import send_email

logger = logging.getLogger(__name__)


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

    setup_logging(config["reports"]["log_dir"])
    logger.info("V1.9 Quant Radar starting")

    # Step 1: Load universe
    logger.info("Fetching universe from CSV...")
    tickers, target_buys = fetch_universe(config["csv_url"])
    logger.info(f"Universe: {len(tickers)} tickers, {len(target_buys)} target buys")

    # Step 2: Connect to market data
    iv_db_path = config["data"]["iv_history_db"]
    os.makedirs(os.path.dirname(iv_db_path) or ".", exist_ok=True)
    provider = MarketDataProvider(
        ibkr_config=config.get("ibkr"),
        iv_db_path=iv_db_path,
    )
    data_source = "IBKR Gateway" if provider.ibkr else "yfinance"

    # Step 3: Build ticker data
    all_data: List[TickerData] = []
    errors_count = 0
    today = date.today()

    for ticker in tickers:
        try:
            td = build_ticker_data(ticker, provider, reference_date=today)
            if td:
                all_data.append(td)
            else:
                errors_count += 1
        except Exception as e:
            logger.error(f"Failed to process {ticker}: {e}")
            errors_count += 1

    logger.info(f"Processed {len(all_data)} tickers, {errors_count} errors")

    # Step 4: Run scanners
    iv_low, iv_high = scan_iv_extremes(all_data)
    ma200_bull, ma200_bear = scan_ma200_crossover(all_data)
    leaps = scan_leaps_setup(all_data)

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

    # Step 5: Generate report
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
        errors_count=errors_count,
        elapsed_seconds=elapsed,
    )

    # Step 6: Output
    print(report)

    # Save to file
    reports_dir = config["reports"]["output_dir"]
    os.makedirs(reports_dir, exist_ok=True)
    report_path = os.path.join(reports_dir, f"{today}_radar.txt")
    with open(report_path, "w") as f:
        f.write(report)
    logger.info(f"Report saved: {report_path}")

    # Email stub
    send_email(report, config)

    # Cleanup
    provider.disconnect()
    logger.info(f"Scan completed in {elapsed:.1f}s")


if __name__ == "__main__":
    config_file = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    run_scan(config_file)
