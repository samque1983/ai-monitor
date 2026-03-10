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
import json
import logging
import os

from src.llm_client import make_llm_client_from_env

logger = logging.getLogger(__name__)


FCF_PAYOUT_SECTORS = {"Energy", "Utilities", "Real Estate"}


@dataclass
class DividendQualityScore:
    """股息质量评分结果

    Attributes:
        overall_score: 综合评分 (0-100)
        stability_score: 派息稳定性评分（连续性 + 增长率）
        health_score: 财务健康度评分（ROE + 负债 + FCF）
        defensiveness_score: 行业防御性评分（公用事业/消费/医疗优先）
        risk_flags: 风险标记列表
        payout_type: 使用的派息率类型 ("FCF" | "GAAP")
        effective_payout_ratio: 实际使用的派息率
    """
    overall_score: float
    stability_score: float
    health_score: float
    defensiveness_score: float
    risk_flags: List[str]
    payout_type: str = "GAAP"
    effective_payout_ratio: float = 0.0
    quality_breakdown: Optional[Dict[str, float]] = None
    # ^ Independent display view (5 dims × 0-20 = max 100).
    # NOT a mathematical decomposition of overall_score.
    analysis_text: Optional[str] = None


class FinancialServiceAnalyzer:
    """金融服务分析器

    提供股息质量分析功能：
    - 优先使用Claude Financial Service进行深度分析（Task 2.2+实现）
    - 降级到规则化评分（当服务不可用时）

    评分逻辑：
    - stability_score = max(0, min(100, consecutive_years*10 + min(dividend_growth*2, 30)))
    - health_score = min(100, roe_score + debt_score + payout_score)
    - defensiveness_score = Claude API 打分（api_key 已设置时）；否则固定 50.0
    - overall_score = stability*0.4 + health*0.4 + defensiveness*0.2
    """

    def __init__(
        self,
        enabled: bool = True,
        fallback_to_rules: bool = True,
        api_key: str = "",
        model: str = "claude-opus-4-6",
        store=None,
    ):
        """初始化Financial Service Analyzer

        Args:
            enabled: 是否启用Financial Service API调用
            fallback_to_rules: 服务不可用时是否降级到规则评分
            api_key: Anthropic API key
            model: Claude model ID
            store: DividendStore instance for caching
        """
        self.enabled = enabled
        self.fallback_to_rules = fallback_to_rules
        self.api_key = api_key
        self.model = model
        self.store = store
        self._client = None

    def _has_llm_key(self) -> bool:
        """Return True if any LLM API key is available."""
        return bool(
            self.api_key
            or os.environ.get("DEEPSEEK_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("ANTHROPIC_API_KEY")
        )

    def _get_client(self):
        """Lazy-init shared LLM client (auto-detects provider from env)."""
        if self._client is None:
            self._client = make_llm_client_from_env(model=self.model, api_key=self.api_key)
        return self._client

    def _get_defensiveness_score(self, sector: str, industry: str) -> float:
        """Return LLM-scored defensiveness (0-100). Falls back to 50.0 on any failure."""
        if not sector and not industry:
            logger.debug("Defensiveness score: sector/industry unknown, using 50.0")
            return 50.0
        if self.store:
            cached = self.store.get_defensiveness_score(sector, industry)
            if cached is not None:
                logger.debug(f"Defensiveness cache hit: {sector}/{industry} → {cached[0]}")
                return cached[0]
        try:
            client = self._get_client()
            prompt = (
                f"行业: {sector} / {industry}\n"
                "评估该行业作为长期股息标的的防御性（0-100分）：\n"
                "- 公用事业/必需消费/医疗保健 → 75-100（需求刚性，非周期）\n"
                "- 金融/工业/通信 → 45-74（有稳定性但有周期风险）\n"
                "- 科技/能源/材料/可选消费 → 0-44（高周期性，股息不稳定）\n"
                '返回严格 JSON: {"score": float, "rationale": "1句话"}'
            )
            raw = client.simple_chat(
                "你是专业行业分析师。只返回严格 JSON，不加任何解释或 markdown。",
                prompt,
                max_tokens=100,
            )
            raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            data = json.loads(raw)
            score = float(data["score"])
            rationale = data.get("rationale", "")
            if self.store:
                self.store.save_defensiveness_score(sector, industry, score, rationale)
            logger.info(f"Defensiveness scored: {sector}/{industry} → {score:.0f} ({rationale})")
            return score
        except Exception as e:
            logger.warning(f"Defensiveness scoring failed for {sector}/{industry} [{type(e).__name__}]: {e}, using 50.0")
            return 50.0

    def _get_analysis_text(self, ticker: str, sector: str, industry: str,
                           quality_result: "DividendQualityScore",
                           fundamentals: Dict[str, Any] = None) -> str:
        """Generate 2-3 sentence business stability analysis. Cached per ticker, 7-day TTL."""
        if self.store and hasattr(self.store, "get_analysis_text"):
            cached = self.store.get_analysis_text(ticker)
            if cached:
                return cached
        if not self._has_llm_key():
            logger.warning(f"{ticker}: _get_analysis_text skipped — no LLM key available")
            return ""
        try:
            client = self._get_client()
            fundamentals = fundamentals or {}
            dividend_yield = fundamentals.get("dividend_yield") or 0.0
            annual_dividend = fundamentals.get("annual_dividend") or 0.0
            # Derive approximate current price from yield and annual dividend
            current_price_str = ""
            if dividend_yield > 0 and annual_dividend > 0:
                approx_price = annual_dividend / (dividend_yield / 100)
                currency = "HK$" if ticker.endswith(".HK") else ("¥" if ticker.endswith(".SS") or ticker.endswith(".SZ") else "$")
                current_price_str = f"当前价格: 约{currency}{approx_price:.2f}，年度股息: {annual_dividend:.4f}\n"
            prompt = (
                f"股票: {ticker}\n"
                f"行业: {sector} / {industry}\n"
                f"当前股息率: {dividend_yield:.2f}%\n"
                f"{current_price_str}"
                f"综合质量评分: {quality_result.overall_score:.0f}/100\n"
                f"稳定性: {quality_result.stability_score:.0f}, "
                f"财务健康: {quality_result.health_score:.0f}, "
                f"防御性: {quality_result.defensiveness_score:.0f}\n\n"
                "请用中文按以下格式输出，每项一句话，价格区间必须基于上方提供的当前价格锚点推导：\n"
                "确定性业务：[核心业务描述，稳定现金流来源] → [基于此业务支撑的底部价格区间]\n"
                "增量新业务：[增长方向或新业务风险，若无则写\"暂无明显增量业务\"] → [考虑增量后的合理价格上限]\n"
                "估值区间：[结合股息率/PE/DCF说明定价逻辑] → [综合合理价格区间，如$XX-XX或HK$XX-XX]"
            )
            text = client.simple_chat(
                "你是专业股息投资分析师。直接返回分析文字，不加标题或格式符号。",
                prompt,
                max_tokens=300,
            )
            if self.store and hasattr(self.store, "save_analysis_text"):
                self.store.save_analysis_text(ticker, text)
            logger.info(f"Analysis text generated for {ticker}")
            return text
        except Exception as e:
            logger.warning(f"Analysis text failed for {ticker} [{type(e).__name__}]: {e}")
            return ""

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
        has_key = self._has_llm_key()
        logger.info(f"{ticker}: analyze_dividend_quality enabled={self.enabled} has_llm_key={has_key}")
        if self.enabled and has_key:
            sector = fundamentals.get("sector") or ""
            industry = fundamentals.get("industry") or ""
            defensiveness_score = self._get_defensiveness_score(sector, industry)
            result = self._calculate_rule_based_score(
                ticker, fundamentals, defensiveness_override=defensiveness_score
            )
            result.analysis_text = self._get_analysis_text(ticker, sector, industry, result, fundamentals)
            return result
        if not self.fallback_to_rules:
            logger.warning(f"{ticker}: Financial Service disabled, no fallback allowed")
            return None
        return self._calculate_rule_based_score(ticker, fundamentals)

    def _calculate_rule_based_score(
        self,
        ticker: str,
        fundamentals: Dict[str, Any],
        defensiveness_override: float = None,
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
        - defensiveness_score = defensiveness_override（来自 LLM）；未提供时固定 50.0
        - overall_score = stability*0.4 + health*0.4 + defensiveness*0.2

        Args:
            ticker: 股票代码
            fundamentals: 基本面数据字典

        Returns:
            DividendQualityScore对象
        """
        # 提取必需字段（or 0 处理 key 存在但值为 None 的情况）
        consecutive_years = fundamentals.get('consecutive_years') or 0
        dividend_growth = fundamentals.get('dividend_growth_5y') or 0.0
        roe = fundamentals.get('roe') or 0.0
        debt_to_equity = fundamentals.get('debt_to_equity') or 0.0

        # 确定行业感知的派息率
        sector = fundamentals.get('sector') or ''
        free_cash_flow = fundamentals.get('free_cash_flow')
        annual_dividend = fundamentals.get('annual_dividend')

        if sector in FCF_PAYOUT_SECTORS and free_cash_flow and annual_dividend and free_cash_flow > 0:
            effective_payout_ratio = (annual_dividend / free_cash_flow) * 100
            payout_type = "FCF"
        else:
            effective_payout_ratio = fundamentals.get('payout_ratio') or 0.0
            payout_type = "GAAP"

        # 1. 计算稳定性评分
        # consecutive_years每年+10分，dividend_growth最多贡献30分
        # 使用max确保非负（防止负增长导致负分）
        stability_score = max(0.0, min(100.0, consecutive_years * 10 + min(dividend_growth * 2, 30)))

        # 2. 计算财务健康度评分（None 值用中性分替代）
        roe_score = min(roe or 0.0, 30.0)  # ROE最多30分
        debt_score = max(0.0, 30.0 - (debt_to_equity or 0.0) * 20)  # 负债率惩罚
        payout_score = 40.0 if effective_payout_ratio < 70 else 20.0  # 派息率健康度
        # Cap at 100 for consistency with stability_score
        health_score = min(100.0, roe_score + debt_score + payout_score)

        # 3. 行业防御性评分（LLM评分或固定50分）
        defensiveness_score = defensiveness_override if defensiveness_override is not None else 50.0

        # 4. 综合评分（加权平均）
        overall_score = (
            stability_score * 0.4 +
            health_score * 0.4 +
            defensiveness_score * 0.2
        )

        quality_breakdown = {
            "continuity": min(round(consecutive_years * 2.0, 1), 20.0),
            "earnings_stability": min(round(max(dividend_growth * 0.67, 0.0), 1), 20.0),
            "payout_safety": round(payout_score / 2.0, 1),
            "debt_level": min(round((roe_score + debt_score) / 3.0, 1), 20.0),
            "moat": round(defensiveness_score * 0.2, 1),
        }

        # 5. 生成风险标记
        risk_flags = []
        if effective_payout_ratio > 100:
            risk_flags.append("PAYOUT_RATIO_CRITICAL")
        elif effective_payout_ratio > 80:
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
            risk_flags=risk_flags,
            payout_type=payout_type,
            effective_payout_ratio=effective_payout_ratio,
            quality_breakdown=quality_breakdown,
            analysis_text="",
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

    # Exclude current calendar year (may be incomplete / partial-year data)
    current_year = date.today().year
    complete_years = {y: v for y, v in yearly_dividends.items() if y < current_year}
    if len(complete_years) >= 2:
        yearly_dividends = complete_years

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
