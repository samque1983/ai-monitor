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
