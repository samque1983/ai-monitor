"""
Tests for financial_service.py

Tests cover:
- DividendQualityScore dataclass structure
- FinancialServiceAnalyzer fallback scoring logic
- Dividend metric utility functions (calculate_consecutive_years, calculate_dividend_growth_rate)
"""
import pytest
from datetime import date
from src.financial_service import (
    DividendQualityScore,
    FinancialServiceAnalyzer,
    calculate_consecutive_years,
    calculate_dividend_growth_rate
)


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


FCF_SECTORS = ["Energy", "Utilities", "Real Estate"]


@pytest.mark.parametrize("sector", FCF_SECTORS)
def test_fcf_payout_used_for_capital_intensive_sectors(sector):
    """Energy/Utilities/Real Estate must use FCF payout ratio, not GAAP."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 10,
        'dividend_growth_5y': 3.0,
        'roe': 12.0,
        'debt_to_equity': 1.5,
        'payout_ratio': 120.0,          # GAAP payout > 100 — would trigger exclusion
        'sector': sector,
        'free_cash_flow': 5_000_000_000,    # $5B total FCF
        'annual_dividend': 3.00,             # $3.00 per share (TTM)
        'shares_outstanding': 1_000_000_000, # 1B shares → total = $3B → FCF payout = 60%
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result is not None
    assert result.payout_type == "FCF"
    assert result.effective_payout_ratio == pytest.approx(60.0)


def test_gaap_payout_used_for_non_fcf_sectors():
    """Consumer/Tech/Healthcare sectors must use GAAP payout ratio."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 10,
        'dividend_growth_5y': 5.0,
        'roe': 20.0,
        'debt_to_equity': 0.5,
        'payout_ratio': 65.0,
        'sector': 'Consumer Staples',
        'free_cash_flow': 5_000_000,
        'annual_dividend': 3_000_000,
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result.payout_type == "GAAP"
    assert result.effective_payout_ratio == pytest.approx(65.0)


def test_fcf_payout_uses_per_share_dividend_with_shares_outstanding():
    """FCF payout must convert per-share dividend to total via shares_outstanding.

    Real-world units: annual_dividend is per-share ($3.80/share),
    free_cash_flow is total company dollars ($18B). Without shares_outstanding
    the ratio would be ~0% instead of the correct ~21%.
    """
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 10,
        'dividend_growth_5y': 5.0,
        'roe': 15.0,
        'debt_to_equity': 0.8,
        'payout_ratio': 120.0,          # GAAP > 100 — would wrongly exclude
        'sector': 'Energy',
        'free_cash_flow': 18_000_000_000,   # $18B total FCF
        'annual_dividend': 3.80,             # $3.80 per share (TTM)
        'shares_outstanding': 1_000_000_000, # 1B shares
    }
    result = analyzer.analyze_dividend_quality("XOM", fundamentals)
    assert result.payout_type == "FCF"
    # (3.80 * 1_000_000_000) / 18_000_000_000 * 100 = 21.1%
    assert result.effective_payout_ratio == pytest.approx(21.1, rel=0.01)


def test_fcf_payout_fallback_when_shares_outstanding_missing():
    """FCF sector with missing shares_outstanding falls back to GAAP payout."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 8,
        'dividend_growth_5y': 3.0,
        'roe': 12.0,
        'debt_to_equity': 1.0,
        'payout_ratio': 55.0,
        'sector': 'Energy',
        'free_cash_flow': 18_000_000_000,
        'annual_dividend': 3.80,
        'shares_outstanding': None,     # missing → cannot compute total dividends
    }
    result = analyzer.analyze_dividend_quality("XOM", fundamentals)
    assert result.payout_type == "GAAP"
    assert result.effective_payout_ratio == pytest.approx(55.0)


def test_fcf_payout_fallback_when_free_cash_flow_missing():
    """FCF sector with missing free_cash_flow falls back to GAAP payout."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    fundamentals = {
        'consecutive_years': 8,
        'dividend_growth_5y': 2.0,
        'roe': 10.0,
        'debt_to_equity': 1.0,
        'payout_ratio': 75.0,
        'sector': 'Utilities',
        'free_cash_flow': None,
        'annual_dividend': None,
    }
    result = analyzer.analyze_dividend_quality("TEST", fundamentals)
    assert result.payout_type == "GAAP"
    assert result.effective_payout_ratio == pytest.approx(75.0)


def test_dividend_growth_rate_excludes_partial_current_year():
    """CAGR must exclude the current calendar year (may be incomplete)."""
    from datetime import date as _date
    current_year = _date.today().year
    history = [
        {"date": "2020-07-01", "amount": 1.0},
        {"date": "2021-07-01", "amount": 1.1},
        {"date": "2022-07-01", "amount": 1.2},
        {"date": "2023-07-01", "amount": 1.3},
        {"date": "2024-07-01", "amount": 1.4},
        {"date": f"{current_year}-02-01", "amount": 0.3},  # partial current year
    ]
    cagr = calculate_dividend_growth_rate(history)
    # With fix: uses 2020–2024, CAGR = (1.4/1.0)^(1/4)-1 ≈ 8.78% > 0
    # Without fix: uses 2020–current_year, end=0.3 → large negative CAGR
    assert cagr > 0, f"Should exclude partial current year, got {cagr:.2f}%"
    assert 8.0 <= cagr <= 10.0, f"Expected ~8.78%, got {cagr:.2f}%"


def test_calculate_consecutive_years():
    """测试连续派息年限计算（季度派息，2020-2025）"""
    # 模拟季度派息：每年4次，2020-2025共6年
    dividend_history = [
        {'date': '2020-03-15', 'amount': 0.50},
        {'date': '2020-06-15', 'amount': 0.50},
        {'date': '2020-09-15', 'amount': 0.50},
        {'date': '2020-12-15', 'amount': 0.50},
        {'date': '2021-03-15', 'amount': 0.52},
        {'date': '2021-06-15', 'amount': 0.52},
        {'date': '2021-09-15', 'amount': 0.52},
        {'date': '2021-12-15', 'amount': 0.52},
        {'date': '2022-03-15', 'amount': 0.55},
        {'date': '2022-06-15', 'amount': 0.55},
        {'date': '2022-09-15', 'amount': 0.55},
        {'date': '2022-12-15', 'amount': 0.55},
        {'date': '2023-03-15', 'amount': 0.60},
        {'date': '2023-06-15', 'amount': 0.60},
        {'date': '2023-09-15', 'amount': 0.60},
        {'date': '2023-12-15', 'amount': 0.60},
        {'date': '2024-03-15', 'amount': 0.65},
        {'date': '2024-06-15', 'amount': 0.65},
        {'date': '2024-09-15', 'amount': 0.65},
        {'date': '2024-12-15', 'amount': 0.65},
        {'date': '2025-03-15', 'amount': 0.70},
        {'date': '2025-06-15', 'amount': 0.70},
        {'date': '2025-09-15', 'amount': 0.70},
        {'date': '2025-12-15', 'amount': 0.70},
    ]

    years = calculate_consecutive_years(dividend_history)

    # 验证连续年限 >= 5年（2020-2025至少5年）
    assert years >= 5, f"Expected at least 5 consecutive years, got {years}"


def test_calculate_dividend_growth_rate():
    """测试股息增长率计算（2020: 0.50→2025: 0.75）"""
    # 模拟年度股息增长：2020年$2.00 → 2025年$3.00
    dividend_history = [
        {'date': '2020-03-15', 'amount': 0.50},
        {'date': '2020-06-15', 'amount': 0.50},
        {'date': '2020-09-15', 'amount': 0.50},
        {'date': '2020-12-15', 'amount': 0.50},
        {'date': '2021-03-15', 'amount': 0.54},
        {'date': '2021-06-15', 'amount': 0.54},
        {'date': '2021-09-15', 'amount': 0.54},
        {'date': '2021-12-15', 'amount': 0.54},
        {'date': '2022-03-15', 'amount': 0.58},
        {'date': '2022-06-15', 'amount': 0.58},
        {'date': '2022-09-15', 'amount': 0.58},
        {'date': '2022-12-15', 'amount': 0.58},
        {'date': '2023-03-15', 'amount': 0.64},
        {'date': '2023-06-15', 'amount': 0.64},
        {'date': '2023-09-15', 'amount': 0.64},
        {'date': '2023-12-15', 'amount': 0.64},
        {'date': '2024-03-15', 'amount': 0.69},
        {'date': '2024-06-15', 'amount': 0.69},
        {'date': '2024-09-15', 'amount': 0.69},
        {'date': '2024-12-15', 'amount': 0.69},
        {'date': '2025-03-15', 'amount': 0.75},
        {'date': '2025-06-15', 'amount': 0.75},
        {'date': '2025-09-15', 'amount': 0.75},
        {'date': '2025-12-15', 'amount': 0.75},
    ]

    cagr = calculate_dividend_growth_rate(dividend_history)

    # 验证CAGR在合理范围 [8.0, 10.0]
    # 理论值：(3.00/2.00)^(1/5) - 1 = 0.0845 = 8.45%
    assert 8.0 <= cagr <= 10.0, f"Expected CAGR in [8.0, 10.0], got {cagr:.2f}%"


from unittest.mock import MagicMock, patch


def test_defensiveness_score_calls_llm_when_enabled(tmp_path):
    """When enabled=True and no cache, LLM is called and score used."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    analyzer = FinancialServiceAnalyzer(
        enabled=True, api_key="test-key", store=store
    )

    with patch.object(analyzer, "_get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.simple_chat.return_value = '{"score": 82.0, "rationale": "公用事业，需求刚性"}'

        result = analyzer.analyze_dividend_quality("T", {
            "consecutive_years": 10, "dividend_growth_5y": 3.0,
            "roe": 15.0, "debt_to_equity": 0.5, "payout_ratio": 65.0,
            "sector": "Utilities", "industry": "Electric Utilities",
        })

    assert result is not None
    assert result.defensiveness_score == 82.0
    # 2 calls: one for defensiveness scoring, one for analysis_text
    assert mock_client.simple_chat.call_count == 2
    store.close()


def test_defensiveness_score_uses_cache_on_second_call(tmp_path):
    """Second call with same sector/industry hits DB cache, LLM not called again."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    analyzer = FinancialServiceAnalyzer(
        enabled=True, api_key="test-key", store=store
    )

    with patch.object(analyzer, "_get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.simple_chat.return_value = '{"score": 82.0, "rationale": "公用事业，需求刚性"}'

        analyzer.analyze_dividend_quality("T", {
            "consecutive_years": 10, "dividend_growth_5y": 3.0,
            "roe": 15.0, "debt_to_equity": 0.5, "payout_ratio": 65.0,
            "sector": "Utilities", "industry": "Electric Utilities",
        })
        # Second call — same sector/industry
        analyzer.analyze_dividend_quality("NEE", {
            "consecutive_years": 8, "dividend_growth_5y": 6.0,
            "roe": 12.0, "debt_to_equity": 1.0, "payout_ratio": 70.0,
            "sector": "Utilities", "industry": "Electric Utilities",
        })

    # Defensiveness scored once (cached on second call); analysis_text called per ticker.
    # First call: 2 (defensiveness + analysis). Second call: 1 (analysis only). Total: 3.
    assert mock_client.simple_chat.call_count == 3
    store.close()


def test_defensiveness_score_fallback_on_llm_failure(tmp_path):
    """When LLM raises an exception, defensiveness falls back to 50.0."""
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    analyzer = FinancialServiceAnalyzer(
        enabled=True, api_key="test-key", store=store
    )

    with patch.object(analyzer, "_get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.simple_chat.side_effect = Exception("API error")

        result = analyzer.analyze_dividend_quality("T", {
            "consecutive_years": 10, "dividend_growth_5y": 3.0,
            "roe": 15.0, "debt_to_equity": 0.5, "payout_ratio": 65.0,
            "sector": "Utilities", "industry": "Electric Utilities",
        })

    assert result is not None
    assert result.defensiveness_score == 50.0
    store.close()


def test_defensiveness_score_disabled_uses_fixed_50():
    """When enabled=False, no Claude call, defensiveness is 50.0 as before."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = analyzer.analyze_dividend_quality("T", {
        "consecutive_years": 10, "dividend_growth_5y": 3.0,
        "roe": 15.0, "debt_to_equity": 0.5, "payout_ratio": 65.0,
        "sector": "Utilities", "industry": "Electric Utilities",
    })
    assert result.defensiveness_score == 50.0


def test_quality_score_has_breakdown():
    """DividendQualityScore should include quality_breakdown dict with 5 keys."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = fs.analyze_dividend_quality("T", {
        "consecutive_years": 5,
        "dividend_growth_5y": 4.0,
        "roe": 15.0,
        "debt_to_equity": 1.0,
        "payout_ratio": 60.0,
        "sector": "Communication Services",
        "industry": "Telecom",
    })
    assert result is not None
    assert result.quality_breakdown is not None
    for key in ("continuity", "earnings_stability", "payout_safety", "debt_level", "moat"):
        assert key in result.quality_breakdown
        assert 0.0 <= result.quality_breakdown[key] <= 20.0


def test_quality_breakdown_keys_match_design_spec():
    """Verify breakdown keys match what dashboard and html_report expect."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = fs.analyze_dividend_quality("T", {
        "consecutive_years": 5,
        "dividend_growth_5y": 4.0,
        "roe": 15.0,
        "debt_to_equity": 1.0,
        "payout_ratio": 60.0,
        "sector": "Communication Services",
        "industry": "Telecom",
    })
    assert result is not None
    assert result.quality_breakdown is not None
    assert set(result.quality_breakdown.keys()) == {
        "continuity", "earnings_stability", "payout_safety", "debt_level", "moat"
    }


def test_quality_breakdown_caps_at_20():
    """Each breakdown dimension should be capped at 20."""
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    result = fs.analyze_dividend_quality("KO", {
        "consecutive_years": 62,
        "dividend_growth_5y": 50.0,
        "roe": 50.0,
        "debt_to_equity": 0.0,
        "payout_ratio": 40.0,
        "sector": "Consumer Staples",
        "industry": "Beverages",
    })
    for val in result.quality_breakdown.values():
        assert val <= 20.0


def test_quality_score_analysis_text_empty_without_api_key():
    """analysis_text should be empty string when no api_key provided, even when enabled=True."""
    from unittest.mock import patch
    from src.financial_service import FinancialServiceAnalyzer
    fs = FinancialServiceAnalyzer(enabled=True, fallback_to_rules=True, api_key="")
    with patch.object(fs, "_has_llm_key", return_value=False):
        result = fs.analyze_dividend_quality("KO", {
            "consecutive_years": 10, "dividend_growth_5y": 5.0,
            "roe": 20.0, "debt_to_equity": 0.5, "payout_ratio": 60.0,
            "sector": "Consumer Staples", "industry": "Beverages",
        })
    assert result.analysis_text == ""


def test_analysis_text_prompt_includes_business_structure(tmp_path):
    """LLM prompt must request 确定性业务/增量新业务/估值区间 structure."""
    from src.financial_service import FinancialServiceAnalyzer
    from src.dividend_store import DividendStore
    store = DividendStore(str(tmp_path / "test.db"))
    analyzer = FinancialServiceAnalyzer(
        enabled=True, api_key="test-key", store=store
    )

    with patch.object(analyzer, "_get_client") as mock_client_fn:
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        # First call: defensiveness scoring JSON, second call: analysis text
        mock_client.simple_chat.side_effect = [
            '{"score": 75.0, "rationale": "稳定公用事业"}',
            "确定性业务：电力传输。增量新业务：暂无。估值区间：PE 15-18x。",
        ]

        analyzer.analyze_dividend_quality("NEE", {
            "consecutive_years": 10, "dividend_growth_5y": 3.0,
            "roe": 12.0, "debt_to_equity": 1.0, "payout_ratio": 65.0,
            "sector": "Utilities", "industry": "Electric Utilities",
        })

    assert mock_client.simple_chat.call_count == 2
    # The second call is the analysis_text prompt — check its user message content
    analysis_call_args = mock_client.simple_chat.call_args_list[1]
    user_message = analysis_call_args[0][1]  # positional arg: system, user_message
    assert "确定性业务" in user_message, f"Prompt missing '确定性业务': {user_message}"
    assert "增量新业务" in user_message, f"Prompt missing '增量新业务': {user_message}"
    assert "估值区间" in user_message, f"Prompt missing '估值区间': {user_message}"
    store.close()


# ── Task 1: Anomaly Detection + health_rationale field ──────────────────────

# ── Task 3: LLM Health Assessment + Score Override ──────────────────────────

def test_llm_health_assessment_overrides_rule_score():
    """For anomalous company, LLM health_score replaces rule-based value."""
    mock_store = MagicMock()
    mock_store.get_health_assessment.return_value = None  # no cache
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 11, "dividend_growth_5y": 7.0,
        "roe": 126.0, "debt_to_equity": 464.0,
        "payout_ratio": 103.7, "sector": "Consumer Defensive",
        "industry": "Household Products",
        "free_cash_flow": 2_000_000_000, "shares_outstanding": 340_000_000,
        "annual_dividend": 5.00,
    }
    mock_response = '{"health_score": 72.0, "fcf_payout_est": 55.0, "rationale": "KMB负净资产结构，FCF派息率约55%，实际安全"}'
    with patch.object(analyzer, '_get_client') as mock_get_client:
        mock_client = MagicMock()
        mock_client.simple_chat.return_value = mock_response
        mock_get_client.return_value = mock_client
        result = analyzer._calculate_rule_based_score("KMB", fundamentals)
    assert result.health_score == 72.0
    assert result.payout_type == "LLM"
    assert abs(result.effective_payout_ratio - 55.0) < 0.1
    assert "负净资产" in (result.health_rationale or "")


def test_llm_health_failure_falls_back_to_rules():
    """LLM failure leaves rule-based health_score intact."""
    mock_store = MagicMock()
    mock_store.get_health_assessment.return_value = None
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 11, "dividend_growth_5y": 7.0,
        "roe": 126.0, "debt_to_equity": 464.0,
        "payout_ratio": 103.7, "sector": "Consumer Defensive",
        "industry": "Household Products",
    }
    with patch.object(analyzer, '_get_client') as mock_get_client:
        mock_client = MagicMock()
        mock_client.simple_chat.side_effect = Exception("LLM error")
        mock_get_client.return_value = mock_client
        result = analyzer._calculate_rule_based_score("KMB", fundamentals)
    # Falls back: health_rationale is None, payout_type is GAAP, health_score is rule-based
    assert result.health_rationale is None
    assert result.payout_type == "GAAP"
    assert result.health_score >= 0  # rule-based value


def test_normal_company_skips_llm():
    """Normal company (D/E 50, payout 65%) does not call LLM."""
    mock_store = MagicMock()
    analyzer = FinancialServiceAnalyzer(enabled=True, api_key="fake-key", store=mock_store)
    fundamentals = {
        "consecutive_years": 8, "dividend_growth_5y": 5.0,
        "roe": 15.0, "debt_to_equity": 50.0, "payout_ratio": 65.0,
        "sector": "Consumer Defensive",
    }
    with patch.object(analyzer, '_get_client') as mock_get_client:
        analyzer._calculate_rule_based_score("KO", fundamentals)
        mock_get_client.assert_not_called()


# ── Task 1: Anomaly Detection + health_rationale field ──────────────────────

def test_anomaly_detection_negative_equity():
    """D/E > 200 triggers anomaly detection (negative book equity signal)."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 250, "payout_ratio": 60, "sector": "Consumer Defensive"}) is True


def test_anomaly_detection_gaap_payout_over_100():
    """GAAP payout > 100% outside FCF sectors triggers anomaly."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 103, "sector": "Consumer Defensive"}) is True


def test_anomaly_detection_normal_company():
    """Normal company (D/E 50, payout 65%) does NOT trigger."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 65, "sector": "Consumer Defensive"}) is False


def test_anomaly_detection_fcf_sector_payout_over_100_not_anomalous():
    """Energy sector with payout > 100% is handled by FCF logic, not anomaly."""
    analyzer = FinancialServiceAnalyzer(enabled=False, fallback_to_rules=True)
    assert analyzer._is_anomalous({"debt_to_equity": 50, "payout_ratio": 110, "sector": "Energy"}) is False


def test_dividend_quality_score_has_health_rationale():
    """DividendQualityScore supports health_rationale field."""
    score = DividendQualityScore(
        overall_score=77.0, stability_score=80.0, health_score=70.0,
        defensiveness_score=75.0, risk_flags=[],
        health_rationale="KMB负净资产结构，FCF派息率约55%，实际安全"
    )
    assert score.health_rationale == "KMB负净资产结构，FCF派息率约55%，实际安全"
