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
from datetime import datetime, timedelta, date
from src.data_engine import TickerData
from src.data_loader import classify_market
from src.financial_service import (
    calculate_consecutive_years,
    calculate_dividend_growth_rate,
)

if TYPE_CHECKING:
    from src.market_data import MarketDataProvider
    from src.financial_service import FinancialServiceAnalyzer
    from src.dividend_store import DividendStore

logger = logging.getLogger(__name__)


def _to_dt(d: dict) -> datetime:
    """Convert a dividend history entry's 'date' field to a datetime object."""
    raw = d['date']
    if isinstance(raw, str):
        return datetime.fromisoformat(raw)
    return datetime.combine(raw, datetime.min.time())


@dataclass
class DividendBuySignal:
    """股息买入信号数据类"""
    ticker_data: TickerData
    signal_type: str  # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float
    option_details: Optional[Dict[str, Any]] = None
    forward_dividend_rate: Optional[float] = None
    max_yield_5y: Optional[float] = None
    floor_price: Optional[float] = None
    floor_downside_pct: Optional[float] = None  # Positive = stock is X% above floor price (downside buffer; negate to show drop direction)
    data_age_days: Optional[int] = None
    needs_reeval: bool = False


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
            # Step 1: 获取股息历史（10年，确保ETF等标的有足够历史数据用于CAGR计算）
            dividend_history = provider.get_dividend_history(ticker, years=10)
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

            # New: hard filter — no negative growth
            if dividend_growth_5y < 0:
                logger.debug(f"{ticker}: Dividend growth {dividend_growth_5y:.1f}% < 0, skipping")
                continue

            # Step 3: 获取基本面数据
            fundamentals = provider.get_fundamentals(ticker)
            if not fundamentals:
                logger.warning(f"{ticker}: No fundamentals data, skipping")
                continue

            # New: hard filter — minimum yield 2%
            dividend_yield = fundamentals.get("dividend_yield") or 0.0
            if dividend_yield < 2.0:
                logger.debug(f"{ticker}: Dividend yield {dividend_yield:.1f}% < 2%, skipping")
                continue

            # Step 4: 计算 TTM 年度股息（用于 FCF 派息率）
            one_year_ago = datetime.now() - timedelta(days=365)
            annual_dividend_ttm = sum(
                d['amount'] for d in dividend_history if _to_dt(d) >= one_year_ago
            )
            if annual_dividend_ttm > 0:
                annual_dividend = annual_dividend_ttm
            else:
                # 无近期数据：使用最近一个完整年的派息总额
                yearly: dict = {}
                for d in dividend_history:
                    year = _to_dt(d).year
                    yearly[year] = yearly.get(year, 0) + d['amount']
                annual_dividend = yearly[max(yearly)] if yearly else 0.0

            # Step 5: 调用Financial Service评分
            fundamentals_with_stats = fundamentals.copy()
            fundamentals_with_stats["consecutive_years"] = consecutive_years
            fundamentals_with_stats["dividend_growth_5y"] = dividend_growth_5y
            fundamentals_with_stats["annual_dividend"] = annual_dividend

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

            # Step 7: 获取 forward_dividend_rate
            # forwardAnnualDividendRate is unreliable in yfinance; fall back to dividendRate (TTM)
            forward_dividend_rate = (
                fundamentals.get("forward_dividend_rate")
                or fundamentals.get("dividendRate")
            )

            # Step 8: 计算 max_yield_5y using TTM annual dividend / 5y min price
            # Uses annual_dividend_ttm (already computed from dividend history) and
            # 5y price data. No Dividends column needed — only Close is required.
            max_yield_5y = None
            try:
                price_df_5y = provider.get_price_data(ticker, period='5y')
                if (
                    price_df_5y is not None
                    and not price_df_5y.empty
                    and 'Close' in price_df_5y.columns
                    and annual_dividend_ttm > 0
                ):
                    min_5y_price = float(price_df_5y['Close'].min())
                    if min_5y_price > 0:
                        max_yield_5y = round((annual_dividend_ttm / min_5y_price) * 100, 2)
            except Exception as e:
                logger.warning(f"{ticker}: Could not compute max_yield_5y - {e}")

            # Step 9: 创建TickerData对象
            ticker_data = TickerData(
                ticker=ticker,
                name=fundamentals.get("company_name", ticker),
                market=classify_market(ticker),
                last_price=0.0,
                ma200=None,
                ma50w=None,
                rsi14=None,
                iv_rank=None,
                iv_momentum=None,
                prev_close=0.0,
                earnings_date=None,
                days_to_earnings=None,
                # Dividend fields (populated)
                dividend_yield=fundamentals.get("dividend_yield"),
                dividend_yield_5y_percentile=None,
                dividend_quality_score=quality_score_result.overall_score,
                consecutive_years=consecutive_years,
                dividend_growth_5y=dividend_growth_5y,
                payout_ratio=quality_score_result.effective_payout_ratio,
                payout_type=quality_score_result.payout_type,
                roe=fundamentals.get("roe"),
                debt_to_equity=fundamentals.get("debt_to_equity"),
                industry=fundamentals.get("industry"),
                sector=fundamentals.get("sector"),
                free_cash_flow=fundamentals.get("free_cash_flow"),
                # Enrichment fields
                forward_dividend_rate=forward_dividend_rate,
                max_yield_5y=max_yield_5y,
                quality_breakdown=quality_score_result.quality_breakdown,
                analysis_text=quality_score_result.analysis_text or "",
                data_version_date=str(date.today()),
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
    pool: List[Dict],
    provider: "MarketDataProvider",
    store: "DividendStore",
    config: dict,
) -> List[DividendBuySignal]:
    """每日监控股息买入信号

    六步工作流：
    1. 遍历pool中的records（List[Dict] from get_pool_records()）
    2. 获取当前价格（最近5天数据）
    3. 获取股息历史（最近1年）
    4. 计算当前股息率 = (年度股息 / 最新价格) * 100
    5. 从store获取股息率历史分位数
    6. 判断触发条件：current_yield >= min_yield AND yield_percentile >= min_yield_percentile

    Args:
        pool: pool record dicts（来自DividendStore.get_pool_records()）
        provider: MarketDataProvider实例
        store: DividendStore实例（用于获取历史分位数）
        config: 配置字典，包含：
            - min_yield: 最低股息率阈值（默认4.0）
            - min_yield_percentile: 最低历史分位数（默认90）

    Returns:
        触发买入信号的DividendBuySignal列表

    Examples:
        >>> signals = scan_dividend_buy_signal(
        ...     pool=[{"ticker": "AAPL", ...}, {"ticker": "MSFT", ...}],
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

    for record in pool:
        ticker = record["ticker"]
        # Extract enrichment fields from pool record
        _fwd_div = record.get("forward_dividend_rate")
        _max_yield = record.get("max_yield_5y")
        _data_version_date_str = record.get("data_version_date")

        # Compute floor_price: forward_dividend_rate / (max_yield_5y / 100)
        _floor_price: Optional[float] = None
        if _fwd_div is not None and _max_yield is not None and _max_yield > 0:
            _floor_price = round(_fwd_div / (_max_yield / 100), 2)

        # Compute data_age_days
        _data_age_days: Optional[int] = None
        if _data_version_date_str:
            try:
                _data_age_days = (date.today() - date.fromisoformat(_data_version_date_str)).days
            except (ValueError, TypeError):
                _data_age_days = None

        # needs_reeval: True if data is 14+ days old (stale between weekly scans)
        _needs_reeval = _data_age_days is not None and _data_age_days >= 14

        try:
            # Step 1: 获取当前价格（最近5天）
            price_data = provider.get_price_data(ticker, period='5d')
            if price_data is None or price_data.empty or 'Close' not in price_data.columns:
                logger.debug(f"{ticker}: No price data available, skipping")
                continue

            last_price = float(price_data['Close'].iloc[-1])
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
                if _to_dt(div) >= one_year_ago
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

                # Step 7: 尝试添加期权策略（仅美国市场）
                option_details = None
                signal_type = "STOCK"

                # 检查是否启用期权策略
                option_config = scanner_config.get("option", {})
                if option_config.get("enabled", False) and not provider.should_skip_options(ticker):
                    # 计算目标股息率（基于历史分位数）
                    target_strike_percentile = option_config.get("target_strike_percentile", 90)
                    # 计算目标股息率：当前股息率 × (目标分位数 / 当前分位数)
                    target_yield = current_yield * (target_strike_percentile / yield_percentile) if yield_percentile > 0 else current_yield

                    # 调用scan_dividend_sell_put获取期权详情
                    option_details = scan_dividend_sell_put(
                        ticker_data=ticker_data,
                        provider=provider,
                        annual_dividend=annual_dividend,
                        target_yield_percentile=target_strike_percentile,
                        target_yield=target_yield,
                        min_dte=option_config.get("min_dte", 45),
                        max_dte=option_config.get("max_dte", 90),
                    )

                    if option_details:
                        signal_type = "OPTION"
                        logger.debug(
                            f"{ticker}: Option strategy added - strike=${option_details['strike']:.2f}, "
                            f"apy={option_details['apy']:.2f}%"
                        )

                # Positive value = stock is X% above the floor price (downside buffer)
                _floor_downside_pct: Optional[float] = None
                if _floor_price is not None and last_price > 0:
                    _floor_downside_pct = round((last_price - _floor_price) / last_price * 100, 1)

                signal = DividendBuySignal(
                    ticker_data=ticker_data,
                    signal_type=signal_type,
                    current_yield=current_yield,
                    yield_percentile=yield_percentile,
                    option_details=option_details,
                    forward_dividend_rate=_fwd_div,
                    max_yield_5y=_max_yield,
                    floor_price=_floor_price,
                    floor_downside_pct=_floor_downside_pct,
                    data_age_days=_data_age_days,
                    needs_reeval=_needs_reeval,
                )

                results.append(signal)
                logger.info(
                    f"{ticker}: Buy signal triggered - yield={current_yield:.2f}% "
                    f"(percentile={yield_percentile:.1f}%), signal_type={signal_type}"
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


def scan_dividend_sell_put(
    ticker_data: TickerData,
    provider: "MarketDataProvider",
    annual_dividend: float,
    target_yield_percentile: float,
    target_yield: float,
    min_dte: int = 45,
    max_dte: int = 90,
) -> Optional[Dict[str, Any]]:
    """高股息Sell Put期权策略扫描

    核心逻辑：基于目标股息率计算目标行权价，而非APY优化。
    适用场景：当股息率处于历史高位（价格低位）时，通过Sell Put获得额外现金流。

    工作流程：
    1. 计算目标行权价：target_strike = annual_dividend / (target_yield / 100)
    2. 获取期权链：从provider获取min_dte到max_dte范围内的Put期权
    3. 选择最接近目标行权价的期权：min(options, key=lambda opt: abs(opt['strike'] - target_strike))
    4. 计算APY（仅用于展示）：(bid / strike) * (365 / dte) * 100

    Args:
        ticker_data: TickerData对象
        provider: MarketDataProvider实例
        annual_dividend: 年度股息金额
        target_yield_percentile: 目标股息率分位数（用于记录，不影响行权价选择）
        target_yield: 目标股息率（百分比，如7.3表示7.3%）
        min_dte: 最小到期天数（默认45天）
        max_dte: 最大到期天数（默认90天）

    Returns:
        包含期权详情的字典：
        - strike: 行权价
        - bid: 卖出价
        - dte: 到期天数
        - expiration: 到期日
        - apy: 年化收益率（百分比）
        如果无可用期权或发生错误，返回None

    Examples:
        >>> # 年度股息2.35美元，目标股息率7.3%
        >>> # 目标行权价 = 2.35 / 0.073 = 32.19
        >>> # 如果期权链有32, 33, 34三个行权价，则选择32（最接近32.19）
        >>> result = scan_dividend_sell_put(
        ...     ticker_data=ticker_data,
        ...     provider=provider,
        ...     annual_dividend=2.35,
        ...     target_yield_percentile=90,
        ...     target_yield=7.3,
        ...     min_dte=45,
        ...     max_dte=90
        ... )
        >>> result['strike']
        32.0
        >>> result['apy']  # (1.20 / 32.0) * (365 / 60) * 100
        22.81
    """
    ticker = ticker_data.ticker

    try:
        # Step 1: 计算目标行权价
        target_strike = annual_dividend / (target_yield / 100)
        logger.debug(
            f"{ticker}: Target strike = {annual_dividend:.2f} / {target_yield}% = ${target_strike:.2f}"
        )

        # Step 2: 获取期权链
        option_chain = provider.get_options_chain(ticker, dte_min=min_dte, dte_max=max_dte)
        if option_chain.empty:
            logger.debug(f"{ticker}: No options available in DTE range {min_dte}-{max_dte}")
            return None

        # Step 3: 选择最接近目标行权价的期权
        option_chain['strike_diff'] = abs(option_chain['strike'] - target_strike)
        closest_option = option_chain.loc[option_chain['strike_diff'].idxmin()]

        strike = float(closest_option['strike'])
        bid = float(closest_option['bid'])
        dte = int(closest_option['dte'])
        expiration = closest_option['expiration']

        # Step 4: 计算APY（仅用于展示）
        apy = (bid / strike) * (365 / dte) * 100

        result = {
            'strike': strike,
            'bid': bid,
            'dte': dte,
            'expiration': expiration,
            'apy': apy,
        }

        logger.info(
            f"{ticker}: Sell Put selected - strike=${strike:.2f}, bid=${bid:.2f}, "
            f"dte={dte}, apy={apy:.2f}% (target_strike=${target_strike:.2f})"
        )

        return result

    except Exception as e:
        logger.error(f"{ticker}: Error in scan_dividend_sell_put - {e}", exc_info=True)
        return None
