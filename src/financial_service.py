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
"""
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
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
