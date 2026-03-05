#!/usr/bin/env python3
"""
高股息防御双打 - 每周筛选脚本

用法:
    python scripts/run_dividend_screening.py
    python scripts/run_dividend_screening.py config.yaml

结果保存到 data/dividend_pool.db
"""
import sys
import os
import logging
from datetime import date

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 企业代理环境：禁用 SSL 证书验证
# yfinance 1.x 使用 curl_cffi，需要 patch Session 创建
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import requests as _requests
_orig_get = _requests.get
_requests.get = lambda *a, **kw: _orig_get(*a, **{**kw, "verify": False})

from curl_cffi import requests as _cffi_requests
_OrigSession = _cffi_requests.Session
class _NoVerifySession(_OrigSession):
    def __init__(self, *a, **kw):
        kw.setdefault("verify", False)
        super().__init__(*a, **kw)
_cffi_requests.Session = _NoVerifySession

from src.config import load_config
from src.data_loader import fetch_universe
from src.market_data import MarketDataProvider
from src.financial_service import FinancialServiceAnalyzer
from src.dividend_store import DividendStore
from src.dividend_scanners import scan_dividend_pool_weekly

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    config = load_config(config_path)

    logger.info("=== 高股息防御双打 - 每周筛选 ===")

    # 加载 universe
    logger.info("Loading universe from CSV...")
    tickers, _ = fetch_universe(config["csv_url"])
    logger.info(f"Universe: {len(tickers)} tickers")

    # 初始化 provider
    iv_db_path = config["data"]["iv_history_db"]
    os.makedirs(os.path.dirname(iv_db_path) or ".", exist_ok=True)
    provider = MarketDataProvider(
        ibkr_config=config.get("ibkr"),
        iv_db_path=iv_db_path,
        config=config,
    )
    data_source = "IBKR" if provider.ibkr else "yfinance"
    logger.info(f"Data source: {data_source}")

    # 初始化 Financial Service 和 DividendStore
    financial_service = FinancialServiceAnalyzer()
    db_path = config.get("data", {}).get("dividend_db_path", "data/dividend_pool.db")
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    store = DividendStore(db_path)

    try:
        # 运行每周筛选
        logger.info("Running weekly dividend pool screening...")
        pool = scan_dividend_pool_weekly(
            universe=tickers,
            provider=provider,
            financial_service=financial_service,
            config=config,
        )

        # 保存结果
        version = f"weekly_{date.today().isoformat()}"
        store.save_pool(pool, version=version)

        logger.info(f"=== 筛选完成 ===")
        logger.info(f"入池标的数: {len(pool)}")
        logger.info(f"版本: {version}")
        logger.info(f"数据库: {db_path}")

        if pool:
            logger.info("入池标的列表:")
            for td in pool:
                logger.info(
                    f"  {td.ticker:8s} | 评分: {td.dividend_quality_score:.0f} "
                    f"| 连续: {td.consecutive_years}年 "
                    f"| 增长: {td.dividend_growth_5y:.1f}% "
                    f"| 派息率: {td.payout_ratio:.0f}%"
                )

    finally:
        store.close()
        provider.disconnect()


if __name__ == "__main__":
    main()
