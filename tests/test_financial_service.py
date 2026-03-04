"""
Tests for financial_service.py

Tests cover:
- DividendQualityScore dataclass structure
- FinancialServiceAnalyzer fallback scoring logic
"""
import pytest
from src.financial_service import DividendQualityScore, FinancialServiceAnalyzer


def test_dividend_quality_score_dataclass():
    """测试DividendQualityScore数据类创建和字段访问"""
    score = DividendQualityScore(
        overall_score=85.0,
        stability_score=90.0,
        health_score=80.0,
        defensiveness_score=85.0,
        risk_flags=["HIGH_PAYOUT_RISK"]
    )

    assert score.overall_score == 85.0
    assert score.stability_score == 90.0
    assert score.health_score == 80.0
    assert score.defensiveness_score == 85.0
    assert score.risk_flags == ["HIGH_PAYOUT_RISK"]


def test_financial_service_analyzer_fallback():
    """测试Financial Service Analyzer的规则化降级评分逻辑"""
    # 创建analyzer，enabled=False强制使用fallback
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)

    # 准备测试数据（典型高质量股息股）
    fundamentals = {
        'consecutive_years': 8,  # 8年连续派息
        'dividend_growth_5y': 5.0,  # 5年CAGR 5%
        'roe': 15.0,  # ROE 15%
        'debt_to_equity': 0.8,  # 负债率0.8
        'payout_ratio': 65.0,  # 派息率65%
        'industry': 'Utilities',
        'sector': 'Utilities'
    }

    # 调用分析方法
    score = analyzer.analyze_dividend_quality('TEST', fundamentals)

    # 验证返回了DividendQualityScore对象
    assert isinstance(score, DividendQualityScore)

    # 验证defensiveness_score == 50.0（fallback指示器）
    assert score.defensiveness_score == 50.0

    # 验证stability_score计算正确
    # stability = min(100, consecutive_years*10 + min(dividend_growth*2, 30))
    # = min(100, 8*10 + min(5*2, 30)) = min(100, 80 + 10) = 90
    assert score.stability_score == 90.0

    # 验证overall_score在合理范围
    assert 0 <= score.overall_score <= 100
    assert score.overall_score > 0  # 应该有正值评分


def test_negative_dividend_growth():
    """测试负增长股息（连续派息但增长为负）"""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)

    # 连续派息但股息在下降的情况（例如成熟公司遇到困难）
    fundamentals = {
        'consecutive_years': 10,  # 10年连续派息
        'dividend_growth_5y': -3.0,  # 5年CAGR -3%（负增长）
        'roe': 8.0,  # ROE 8%
        'debt_to_equity': 1.5,  # 负债率1.5
        'payout_ratio': 75.0,  # 派息率75%
    }

    score = analyzer.analyze_dividend_quality('TEST_NEG', fundamentals)

    # 验证stability_score非负（关键bug修复验证）
    assert score.stability_score >= 0.0, "stability_score must be non-negative"

    # 验证health_score被cap在100以内
    assert score.health_score <= 100.0, "health_score must be capped at 100"

    # 验证综合评分在合理范围
    assert 0 <= score.overall_score <= 100


def test_missing_fundamentals():
    """测试缺失基本面数据（应使用默认值0）"""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)

    # 只提供部分字段，其他使用默认值
    fundamentals = {
        'consecutive_years': 3,  # 仅提供连续年限
        # dividend_growth_5y, roe, debt_to_equity, payout_ratio全部缺失
    }

    score = analyzer.analyze_dividend_quality('TEST_MISSING', fundamentals)

    # 验证不会crash，返回有效结果
    assert isinstance(score, DividendQualityScore)

    # 验证使用默认值（0）后的计算逻辑
    # stability = min(100, 3*10 + min(0*2, 30)) = 30
    assert score.stability_score == 30.0

    # health_score使用默认值：roe=0, debt=0, payout=0
    # roe_score = min(0, 30) = 0
    # debt_score = max(0, 30 - 0*20) = 30
    # payout_score = 40 (payout_ratio < 70)
    # health = 0 + 30 + 40 = 70
    assert score.health_score == 70.0

    # 验证分数非负且在范围内
    assert 0 <= score.overall_score <= 100
    assert score.stability_score >= 0
    assert score.health_score >= 0


def test_risk_flag_generation():
    """测试风险标记生成逻辑"""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)

    # 测试1: PAYOUT_RATIO_CRITICAL (> 100%)
    fundamentals_critical = {
        'consecutive_years': 5,
        'dividend_growth_5y': 2.0,
        'roe': 10.0,
        'debt_to_equity': 0.5,
        'payout_ratio': 120.0,  # 派息率超过100%（不可持续）
    }
    score_critical = analyzer.analyze_dividend_quality('TEST_CRITICAL', fundamentals_critical)
    assert "PAYOUT_RATIO_CRITICAL" in score_critical.risk_flags

    # 测试2: HIGH_PAYOUT_RISK (80-100%)
    fundamentals_high = {
        'consecutive_years': 5,
        'dividend_growth_5y': 2.0,
        'roe': 10.0,
        'debt_to_equity': 0.5,
        'payout_ratio': 85.0,  # 派息率85%（高风险）
    }
    score_high = analyzer.analyze_dividend_quality('TEST_HIGH', fundamentals_high)
    assert "HIGH_PAYOUT_RISK" in score_high.risk_flags
    assert "PAYOUT_RATIO_CRITICAL" not in score_high.risk_flags  # 不应该同时存在

    # 测试3: HIGH_LEVERAGE (debt > 2.0)
    fundamentals_leverage = {
        'consecutive_years': 5,
        'dividend_growth_5y': 2.0,
        'roe': 10.0,
        'debt_to_equity': 2.5,  # 负债率2.5（高杠杆）
        'payout_ratio': 60.0,
    }
    score_leverage = analyzer.analyze_dividend_quality('TEST_LEVERAGE', fundamentals_leverage)
    assert "HIGH_LEVERAGE" in score_leverage.risk_flags

    # 测试4: 无风险标记（健康状态）
    fundamentals_healthy = {
        'consecutive_years': 8,
        'dividend_growth_5y': 5.0,
        'roe': 15.0,
        'debt_to_equity': 0.8,
        'payout_ratio': 65.0,
    }
    score_healthy = analyzer.analyze_dividend_quality('TEST_HEALTHY', fundamentals_healthy)
    assert len(score_healthy.risk_flags) == 0
