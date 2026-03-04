"""
Dividend Scanners Module (Phase 2 High Dividend)

职责：
- 每周筛选高股息标的池（稳定性+质量评分）
- 每日监控买入机会（股息率历史分位数+期权策略）
- 高股息Sell Put期权策略扫描

核心扫描器：
- scan_dividend_pool_weekly: 每周筛选股息标的池
- scan_dividend_entry_daily: 每日监控买入机会 (Task 3.2)
- scan_high_dividend_sell_put: 高股息Sell Put策略 (Task 3.3)
"""
from typing import TYPE_CHECKING, List, Optional, Dict, Any
from dataclasses import dataclass
import logging
from datetime import datetime, timedelta
from src.data_engine import TickerData
from src.financial_service import (
    calculate_consecutive_years,
    calculate_dividend_growth_rate,
)

if TYPE_CHECKING:
    from src.market_data import MarketDataProvider
    from src.financial_service import FinancialServiceAnalyzer
    from src.dividend_store import DividendStore

logger = logging.getLogger(__name__)


@dataclass
class DividendBuySignal:
    """股息买入信号数据类"""
    ticker_data: TickerData
    signal_type: str  # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float
    option_details: Optional[Dict[str, Any]] = None


def scan_dividend_pool_weekly(
    universe: List[str],
    provider: "MarketDataProvider",
    financial_service: "FinancialServiceAnalyzer",
    config: dict,
) -> List[TickerData]:
    """每周筛选高股息标的池

    四步流程：
    1. 遍历universe，获取5年股息历史和基本面数据
    2. 计算连续派息年限和5年股息增长率
    3. 硬排除：派息率>max_payout_ratio的标的直接跳过
    4. 调用financial_service.analyze_dividend_quality()评分
    5. 按质量评分和连续年限过滤

    Args:
        universe: 股票代码列表
        provider: MarketDataProvider实例（用于获取股息历史和基本面）
        financial_service: FinancialServiceAnalyzer实例（用于质量评分）
        config: 配置字典，包含：
            - min_quality_score: 最低质量评分（默认70）
            - min_consecutive_years: 最低连续年限（默认5）
            - max_payout_ratio: 最大派息率（默认100）

    Returns:
        符合条件的TickerData列表，包含股息相关字段

    Examples:
        >>> results = scan_dividend_pool_weekly(
        ...     universe=["AAPL", "MSFT"],
        ...     provider=market_provider,
        ...     financial_service=fs_analyzer,
        ...     config={"dividend_scanners": {"min_quality_score": 70}}
        ... )
        >>> len(results)
        2
        >>> results[0].dividend_quality_score >= 70
        True
    """
    # 提取配置参数
    scanner_config = config.get("dividend_scanners", {})
    min_quality_score = scanner_config.get("min_quality_score", 70)
    min_consecutive_years = scanner_config.get("min_consecutive_years", 5)
    max_payout_ratio = scanner_config.get("max_payout_ratio", 100)

    results = []

    for ticker in universe:
        try:
            # Step 1: 获取股息历史（5年）
            dividend_history = provider.get_dividend_history(ticker, years=5)
            if not dividend_history:
                logger.debug(f"{ticker}: No dividend history, skipping")
                continue

            # Step 2: 计算连续年限和增长率
            consecutive_years = calculate_consecutive_years(dividend_history)
            dividend_growth_5y = calculate_dividend_growth_rate(dividend_history, years=5)

            if consecutive_years < min_consecutive_years:
                logger.debug(
                    f"{ticker}: Consecutive years {consecutive_years} < {min_consecutive_years}, skipping"
                )
                continue

            # Step 3: 获取基本面数据
            fundamentals = provider.get_fundamentals(ticker)
            if not fundamentals:
                logger.warning(f"{ticker}: No fundamentals data, skipping")
                continue

            # Step 4: 硬排除 - 派息率超过max_payout_ratio
            payout_ratio = fundamentals.get("payout_ratio", 0.0)
            if payout_ratio > max_payout_ratio:
                logger.info(
                    f"{ticker}: Payout ratio {payout_ratio:.1f}% > {max_payout_ratio}%, excluded"
                )
                continue

            # Step 5: 调用Financial Service评分
            # 将连续年限和增长率添加到fundamentals
            fundamentals_with_stats = fundamentals.copy()
            fundamentals_with_stats["consecutive_years"] = consecutive_years
            fundamentals_with_stats["dividend_growth_5y"] = dividend_growth_5y

            quality_score_result = financial_service.analyze_dividend_quality(
                ticker=ticker,
                fundamentals=fundamentals_with_stats
            )

            if not quality_score_result:
                logger.warning(f"{ticker}: Quality score analysis failed, skipping")
                continue

            # Step 6: 质量评分过滤
            if quality_score_result.overall_score < min_quality_score:
                logger.debug(
                    f"{ticker}: Quality score {quality_score_result.overall_score:.1f} "
                    f"< {min_quality_score}, filtered out"
                )
                continue

            # Step 7: 创建TickerData对象（placeholder values for non-dividend fields）
            ticker_data = TickerData(
                ticker=ticker,
                name=fundamentals.get("company_name", ticker),  # Fallback to ticker if no name
                market=provider.config.get("default_market", "US"),  # Use provider config or default
                last_price=0.0,  # Placeholder - will be filled by main pipeline if needed
                ma200=None,
                ma50w=None,
                rsi14=None,
                iv_rank=None,
                iv_momentum=None,
                prev_close=0.0,  # Placeholder
                earnings_date=None,
                days_to_earnings=None,
                # Dividend fields (populated)
                dividend_yield=fundamentals.get("dividend_yield"),
                dividend_yield_5y_percentile=None,  # Will be calculated in daily scan
                dividend_quality_score=quality_score_result.overall_score,
                consecutive_years=consecutive_years,
                dividend_growth_5y=dividend_growth_5y,
                payout_ratio=payout_ratio,
                roe=fundamentals.get("roe"),
                debt_to_equity=fundamentals.get("debt_to_equity"),
                industry=fundamentals.get("industry"),
                sector=fundamentals.get("sector"),
                free_cash_flow=fundamentals.get("free_cash_flow"),
            )

            results.append(ticker_data)
            logger.info(
                f"{ticker}: Added to pool - score={quality_score_result.overall_score:.1f}, "
                f"consecutive={consecutive_years}, growth={dividend_growth_5y:.1f}%"
            )

        except Exception as e:
            logger.error(f"{ticker}: Error in weekly scan - {e}", exc_info=True)
            continue

    logger.info(f"Weekly scan complete: {len(results)}/{len(universe)} tickers qualified")
    return results


def scan_dividend_buy_signal(
    pool: List[str],
    provider: "MarketDataProvider",
    store: "DividendStore",
    config: dict,
) -> List[DividendBuySignal]:
    """每日监控股息买入信号

    六步工作流：
    1. 遍历pool中的tickers
    2. 获取当前价格（最近5天数据）
    3. 获取股息历史（最近1年）
    4. 计算当前股息率 = (年度股息 / 最新价格) * 100
    5. 从store获取股息率历史分位数
    6. 判断触发条件：current_yield >= min_yield AND yield_percentile >= min_yield_percentile

    Args:
        pool: ticker列表（来自DividendStore的当前池）
        provider: MarketDataProvider实例
        store: DividendStore实例（用于获取历史分位数）
        config: 配置字典，包含：
            - min_yield: 最低股息率阈值（默认4.0）
            - min_yield_percentile: 最低历史分位数（默认90）

    Returns:
        触发买入信号的DividendBuySignal列表

    Examples:
        >>> signals = scan_dividend_buy_signal(
        ...     pool=["AAPL", "MSFT"],
        ...     provider=market_provider,
        ...     store=dividend_store,
        ...     config={"dividend_scanners": {"min_yield": 4.0, "min_yield_percentile": 90}}
        ... )
        >>> len(signals)
        1
        >>> signals[0].signal_type
        'STOCK'
    """
    # 提取配置参数
    scanner_config = config.get("dividend_scanners", {})
    min_yield = scanner_config.get("min_yield", 4.0)
    min_yield_percentile = scanner_config.get("min_yield_percentile", 90)

    results = []

    for ticker in pool:
        try:
            # Step 1: 获取当前价格（最近5天）
            price_data = provider.get_price_data(ticker, period='5d')
            if not price_data or 'close' not in price_data or len(price_data['close']) == 0:
                logger.debug(f"{ticker}: No price data available, skipping")
                continue

            last_price = price_data['close'][-1]
            if last_price <= 0:
                logger.warning(f"{ticker}: Invalid last price {last_price}, skipping")
                continue

            # Step 2: 获取股息历史（最近1年）
            dividend_history = provider.get_dividend_history(ticker, years=1)
            if not dividend_history:
                logger.debug(f"{ticker}: No dividend history, skipping")
                continue

            # Step 3: 计算年度股息（sum last 1 year）
            one_year_ago = datetime.now() - timedelta(days=365)
            annual_dividend = sum(
                div['amount']
                for div in dividend_history
                if datetime.fromisoformat(div['date']) >= one_year_ago
            )

            if annual_dividend <= 0:
                logger.debug(f"{ticker}: Annual dividend is {annual_dividend}, skipping")
                continue

            # Step 4: 计算当前股息率
            current_yield = (annual_dividend / last_price) * 100

            # Step 5: 获取历史分位数
            yield_percentile = store.get_yield_percentile(ticker, current_yield)

            # Step 6: 判断触发条件
            if current_yield >= min_yield and yield_percentile >= min_yield_percentile:
                # 创建TickerData对象（简化版，只包含必要字段）
                ticker_data = TickerData(
                    ticker=ticker,
                    name=ticker,  # 简化：使用ticker作为name
                    market="US",  # 简化：默认US市场
                    last_price=last_price,
                    ma200=None,
                    ma50w=None,
                    rsi14=None,
                    iv_rank=None,
                    iv_momentum=None,
                    prev_close=0.0,
                    earnings_date=None,
                    days_to_earnings=None,
                    dividend_yield=current_yield,
                    dividend_yield_5y_percentile=yield_percentile,
                    dividend_quality_score=None,
                    consecutive_years=None,
                    dividend_growth_5y=None,
                    payout_ratio=None,
                    roe=None,
                    debt_to_equity=None,
                    industry=None,
                    sector=None,
                    free_cash_flow=None,
                )

                signal = DividendBuySignal(
                    ticker_data=ticker_data,
                    signal_type="STOCK",
                    current_yield=current_yield,
                    yield_percentile=yield_percentile,
                    option_details=None
                )

                results.append(signal)
                logger.info(
                    f"{ticker}: Buy signal triggered - yield={current_yield:.2f}% "
                    f"(percentile={yield_percentile:.1f}%)"
                )
            else:
                logger.debug(
                    f"{ticker}: No signal - yield={current_yield:.2f}% "
                    f"(percentile={yield_percentile:.1f}%), "
                    f"min_yield={min_yield}, min_percentile={min_yield_percentile}"
                )

        except Exception as e:
            logger.error(f"{ticker}: Error in daily scan - {e}", exc_info=True)
            continue

    logger.info(f"Daily scan complete: {len(results)}/{len(pool)} signals triggered")
    return results
