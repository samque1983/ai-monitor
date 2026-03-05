"""
Financial Service 封装层

职责：
- 封装Claude Financial Analysis能力，提供专业级基本面分析
- 提供规则化评分降级方案（当Financial Service不可用时）
- 计算股息质量综合评分（稳定性、财务健康、行业防御性）

核心数据结构：
- DividendQualityScore: 股息质量评分结果

核心类：
- FinancialServiceAnalyzer: 金融服务分析器

工具函数：
- calculate_consecutive_years: 计算派息连续年限
- calculate_dividend_growth_rate: 计算股息复合增长率
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from datetime import date, datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class DividendQualityScore:
    """股息质量评分结果

    Attributes:
        overall_score: 综合评分 (0-100)
        stability_score: 派息稳定性评分（连续性 + 增长率）
        health_score: 财务健康度评分（ROE + 负债 + FCF）
        defensiveness_score: 行业防御性评分（公用事业/消费/医疗优先）
        risk_flags: 风险标记列表
    """
    overall_score: float
    stability_score: float
    health_score: float
    defensiveness_score: float
    risk_flags: List[str]


class FinancialServiceAnalyzer:
    """金融服务分析器

    提供股息质量分析功能：
    - 优先使用Claude Financial Service进行深度分析（Task 2.2+实现）
    - 降级到规则化评分（当服务不可用时）

    规则化评分逻辑：
    - stability_score = max(0, min(100, consecutive_years*10 + min(dividend_growth*2, 30)))
    - health_score = min(100, roe_score + debt_score + payout_score)
    - defensiveness_score = 50.0 (固定值，无行业分析能力)
    - overall_score = stability*0.4 + health*0.4 + defensiveness*0.2
    """

    def __init__(self, enabled: bool = True, fallback_to_rules: bool = True):
        """初始化Financial Service Analyzer

        Args:
            enabled: 是否启用Financial Service API调用（Task 2.2+实现）
            fallback_to_rules: 服务不可用时是否降级到规则评分
        """
        self.enabled = enabled
        self.fallback_to_rules = fallback_to_rules

    def analyze_dividend_quality(
        self,
        ticker: str,
        fundamentals: Dict[str, Any]
    ) -> Optional[DividendQualityScore]:
        """分析股息质量

        当前实现：直接使用规则化评分（Financial Service集成在Task 2.2+）

        Args:
            ticker: 股票代码
            fundamentals: 基本面数据字典，包含：
                - consecutive_years: 连续派息年限
                - dividend_growth_5y: 5年股息复合增长率 (CAGR, %)
                - roe: 净资产收益率 (%)
                - debt_to_equity: 负债率
                - payout_ratio: 派息率 (%)
                - industry: 行业分类
                - sector: 行业板块

        Returns:
            DividendQualityScore对象，如果数据不足返回None
        """
        # Task 2.1: 当前所有情况都使用fallback
        # Task 2.2+: 将实现Financial Service API调用
        if not self.fallback_to_rules:
            logger.warning(f"{ticker}: Financial Service not implemented yet, no fallback allowed")
            return None

        return self._calculate_rule_based_score(ticker, fundamentals)

    def _calculate_rule_based_score(
        self,
        ticker: str,
        fundamentals: Dict[str, Any]
    ) -> DividendQualityScore:
        """规则化评分逻辑（降级方案）

        评分公式：
        - stability_score = max(0, min(100, consecutive_years*10 + min(dividend_growth*2, 30)))
          - max(0, ...) 确保非负（防止负增长导致负分）
        - health_score = min(100, roe_score + debt_score + payout_score)
          - roe_score = min(roe, 30)
          - debt_score = max(0, 30 - debt_to_equity*20)
          - payout_score = 40 if payout_ratio < 70 else 20
          - min(100, ...) 确保不超过100分
        - defensiveness_score = 50.0 (固定值，无行业分析)
        - overall_score = stability*0.4 + health*0.4 + defensiveness*0.2

        Args:
            ticker: 股票代码
            fundamentals: 基本面数据字典

        Returns:
            DividendQualityScore对象
        """
        # 提取必需字段
        consecutive_years = fundamentals.get('consecutive_years', 0)
        dividend_growth = fundamentals.get('dividend_growth_5y', 0.0)
        roe = fundamentals.get('roe', 0.0)
        debt_to_equity = fundamentals.get('debt_to_equity', 0.0)
        payout_ratio = fundamentals.get('payout_ratio', 0.0)

        # 1. 计算稳定性评分
        # consecutive_years每年+10分，dividend_growth最多贡献30分
        # 使用max确保非负（防止负增长导致负分）
        stability_score = max(0.0, min(100.0, consecutive_years * 10 + min(dividend_growth * 2, 30)))

        # 2. 计算财务健康度评分
        roe_score = min(roe, 30.0)  # ROE最多30分
        debt_score = max(0.0, 30.0 - debt_to_equity * 20)  # 负债率惩罚
        payout_score = 40.0 if payout_ratio < 70 else 20.0  # 派息率健康度
        # Cap at 100 for consistency with stability_score
        health_score = min(100.0, roe_score + debt_score + payout_score)

        # 3. 行业防御性评分（固定50分，fallback无行业分析能力）
        defensiveness_score = 50.0

        # 4. 综合评分（加权平均）
        overall_score = (
            stability_score * 0.4 +
            health_score * 0.4 +
            defensiveness_score * 0.2
        )

        # 5. 生成风险标记
        risk_flags = []
        if payout_ratio > 100:
            risk_flags.append("PAYOUT_RATIO_CRITICAL")
        elif payout_ratio > 80:
            risk_flags.append("HIGH_PAYOUT_RISK")

        if debt_to_equity > 2.0:
            risk_flags.append("HIGH_LEVERAGE")

        logger.debug(
            f"{ticker}: Rule-based score calculated - "
            f"overall={overall_score:.1f}, stability={stability_score:.1f}, "
            f"health={health_score:.1f}, defensiveness={defensiveness_score:.1f}"
        )

        return DividendQualityScore(
            overall_score=overall_score,
            stability_score=stability_score,
            health_score=health_score,
            defensiveness_score=defensiveness_score,
            risk_flags=risk_flags
        )


def calculate_consecutive_years(dividend_history: List[Dict[str, Any]]) -> int:
    """计算派息连续年限

    从最近一年往前倒推，检查每个日历年是否至少有1次派息。
    遇到第一个无派息年份时停止计数。

    Args:
        dividend_history: 股息历史记录列表，每条记录包含：
            - date: 日期字符串 ('YYYY-MM-DD') 或 date 对象
            - amount: 派息金额

    Returns:
        连续派息年限（整数）。若无历史记录则返回0。

    Examples:
        >>> history = [
        ...     {'date': '2020-03-15', 'amount': 0.5},
        ...     {'date': '2020-06-15', 'amount': 0.5},
        ...     {'date': '2021-03-15', 'amount': 0.5},
        ... ]
        >>> calculate_consecutive_years(history)
        2
    """
    if not dividend_history:
        return 0

    # 提取所有年份
    years_with_dividends = set()
    for record in dividend_history:
        dividend_date = record.get('date')
        if not dividend_date:
            continue

        # 处理字符串日期和date对象
        if isinstance(dividend_date, str):
            year = int(dividend_date.split('-')[0])
        elif isinstance(dividend_date, (date, datetime)):
            year = dividend_date.year
        else:
            continue

        years_with_dividends.add(year)

    if not years_with_dividends:
        return 0

    # 从最近一年往前倒推
    max_year = max(years_with_dividends)
    consecutive_count = 0

    for year in range(max_year, max_year - 100, -1):  # 最多检查100年
        if year in years_with_dividends:
            consecutive_count += 1
        else:
            break  # 遇到第一个无派息年份，停止计数

    return consecutive_count


def calculate_dividend_growth_rate(dividend_history: List[Dict[str, Any]], years: int = 5) -> float:
    """计算股息复合增长率 (CAGR)

    按日历年汇总年度股息，计算首尾年份的CAGR。
    公式: CAGR = (End / Start)^(1 / years) - 1

    Args:
        dividend_history: 股息历史记录列表，每条记录包含：
            - date: 日期字符串 ('YYYY-MM-DD') 或 date 对象
            - amount: 派息金额
        years: 保留参数（兼容性），实际使用数据中的实际年限

    Returns:
        CAGR百分比（例如8.45表示8.45%），保留2位小数。
        若数据不足（少于2年）或开始金额为0，则返回0.0。

    Examples:
        >>> history = [
        ...     {'date': '2020-03-15', 'amount': 0.5},
        ...     {'date': '2020-06-15', 'amount': 0.5},  # 2020总计: 1.0
        ...     {'date': '2025-03-15', 'amount': 0.625},
        ...     {'date': '2025-06-15', 'amount': 0.625},  # 2025总计: 1.25
        ... ]
        >>> calculate_dividend_growth_rate(history)
        4.56  # (1.25/1.0)^(1/5) - 1 = 0.0456 = 4.56%
    """
    if not dividend_history:
        return 0.0

    # 按日历年汇总股息
    yearly_dividends = {}
    for record in dividend_history:
        dividend_date = record.get('date')
        amount = record.get('amount', 0.0)

        if not dividend_date or amount is None:
            continue

        # 处理字符串日期和date对象
        if isinstance(dividend_date, str):
            year = int(dividend_date.split('-')[0])
        elif isinstance(dividend_date, (date, datetime)):
            year = dividend_date.year
        else:
            continue

        if year not in yearly_dividends:
            yearly_dividends[year] = 0.0
        yearly_dividends[year] += amount

    if len(yearly_dividends) < 2:
        return 0.0  # 数据不足，无法计算CAGR

    # 获取首尾年份
    sorted_years = sorted(yearly_dividends.keys())
    start_year = sorted_years[0]
    end_year = sorted_years[-1]

    start_amount = yearly_dividends[start_year]
    end_amount = yearly_dividends[end_year]

    if start_amount <= 0:
        return 0.0  # 起始金额为0或负数，无法计算增长率

    # 计算实际年限
    actual_years = end_year - start_year
    if actual_years == 0:
        return 0.0  # 同一年的数据

    # 计算CAGR: (End/Start)^(1/years) - 1
    cagr_decimal = (end_amount / start_amount) ** (1.0 / actual_years) - 1.0

    # 转换为百分比并保留2位小数
    cagr_percentage = round(cagr_decimal * 100, 2)

    return cagr_percentage
