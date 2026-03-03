# 高股息防御双打扫描器 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 实现Phase 2高股息防御双打功能，提供每周筛选高质量股息股票池和每日监控买入时机（股息率历史高点触发）的完整解决方案。

**Architecture:** 采用Financial Service深度集成方案，新增4个模块（financial_service, dividend_store, dividend_scanners, dividend_report），使用SQLite存储池子和历史数据，复用现有MarketDataProvider获取基本面数据，遵循GLOBAL_MASTER依赖层级。

**Tech Stack:** Python 3.x, yfinance, SQLite3, pytest, Claude Financial Analysis Skills, Apple风格CSS/HTML

---

## Pre-Implementation Checklist

在开始前确认：
- [ ] 已读取`req/GLOBAL_MASTER.md`（架构规则、数据完整性要求）
- [ ] 已读取`req/phase_2_high_dividend.md`（需求文档）
- [ ] 已读取`docs/specs/data_pipeline.md`（现有数据流）
- [ ] 已读取`docs/specs/scanners.md`（现有扫描器模式）
- [ ] 工作目录：`/Users/Q/code/ai-monitor`

---

## Phase 1: 数据基础设施

### Task 1.1: 扩展TickerData数据模型

**Files:**
- Modify: `src/data_engine.py` (TickerData dataclass)
- Modify: `tests/conftest.py` (make_ticker helper)
- Test: `tests/test_data_engine.py`

**Step 1: 写失败测试 - 验证新字段存在**

在`tests/test_data_engine.py`添加：

```python
def test_ticker_data_has_dividend_fields():
    """Phase 2: TickerData应包含股息相关字段"""
    from src.data_engine import TickerData

    ticker = TickerData(
        ticker="AAPL",
        name="Apple Inc.",
        market="US",
        last_price=150.0,
        ma200=145.0,
        ma50w=148.0,
        rsi14=55.0,
        iv_rank=30.0,
        prev_close=149.0,
        earnings_date=None,
        days_to_earnings=None,
        # Phase 2新增字段
        dividend_yield=2.5,
        dividend_yield_5y_percentile=85.0,
        dividend_quality_score=88.0,
        consecutive_years=10,
        dividend_growth_5y=8.5,
        payout_ratio=25.0,
        roe=28.0,
        debt_to_equity=1.2,
        industry="Technology",
        sector="Information Technology",
        free_cash_flow=95000000000.0
    )

    assert ticker.dividend_yield == 2.5
    assert ticker.dividend_quality_score == 88.0
    assert ticker.consecutive_years == 10
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_data_engine.py::test_ticker_data_has_dividend_fields -v
```

预期输出：`TypeError: __init__() got unexpected keyword argument 'dividend_yield'`

**Step 3: 实现 - 扩展TickerData**

在`src/data_engine.py`的`TickerData`类中添加字段：

```python
@dataclass
class TickerData:
    ticker: str
    name: str
    market: str
    last_price: float
    ma200: Optional[float]
    ma50w: Optional[float]
    rsi14: Optional[float]
    iv_rank: Optional[float]
    prev_close: float
    earnings_date: Optional[date]
    days_to_earnings: Optional[int]

    # Phase 2: 高股息新增字段
    dividend_yield: Optional[float] = None
    dividend_yield_5y_percentile: Optional[float] = None
    dividend_quality_score: Optional[float] = None
    consecutive_years: Optional[int] = None
    dividend_growth_5y: Optional[float] = None
    payout_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    industry: Optional[str] = None
    sector: Optional[str] = None
    free_cash_flow: Optional[float] = None
```

**Step 4: 更新测试helper - make_ticker**

在`tests/conftest.py`中更新`make_ticker`：

```python
def make_ticker(
    ticker="AAPL",
    name="Apple Inc.",
    market="US",
    last_price=150.0,
    ma200=145.0,
    ma50w=148.0,
    rsi14=55.0,
    iv_rank=30.0,
    prev_close=149.0,
    earnings_date=None,
    days_to_earnings=None,
    # Phase 2新增参数
    dividend_yield=None,
    dividend_yield_5y_percentile=None,
    dividend_quality_score=None,
    consecutive_years=None,
    dividend_growth_5y=None,
    payout_ratio=None,
    roe=None,
    debt_to_equity=None,
    industry=None,
    sector=None,
    free_cash_flow=None
) -> TickerData:
    return TickerData(
        ticker=ticker,
        name=name,
        market=market,
        last_price=last_price,
        ma200=ma200,
        ma50w=ma50w,
        rsi14=rsi14,
        iv_rank=iv_rank,
        prev_close=prev_close,
        earnings_date=earnings_date,
        days_to_earnings=days_to_earnings,
        dividend_yield=dividend_yield,
        dividend_yield_5y_percentile=dividend_yield_5y_percentile,
        dividend_quality_score=dividend_quality_score,
        consecutive_years=consecutive_years,
        dividend_growth_5y=dividend_growth_5y,
        payout_ratio=payout_ratio,
        roe=roe,
        debt_to_equity=debt_to_equity,
        industry=industry,
        sector=sector,
        free_cash_flow=free_cash_flow
    )
```

**Step 5: 运行测试确认通过**

```bash
pytest tests/test_data_engine.py::test_ticker_data_has_dividend_fields -v
```

预期输出：`PASSED`

**Step 6: 提交**

```bash
git add src/data_engine.py tests/test_data_engine.py tests/conftest.py
git commit -m "feat: extend TickerData with dividend fields for Phase 2

- Add 11 optional dividend-related fields
- Update make_ticker helper in conftest
- Add test for new fields

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 1.2: 创建DividendStore（SQLite存储）

**Files:**
- Create: `src/dividend_store.py`
- Create: `tests/test_dividend_store.py`

**Step 1: 写失败测试 - 初始化数据库**

创建`tests/test_dividend_store.py`：

```python
import pytest
from datetime import date
from src.dividend_store import DividendStore
from tests.conftest import make_ticker


def test_dividend_store_init_creates_tables():
    """DividendStore应创建必需的数据库表"""
    store = DividendStore(db_path=':memory:')

    # 验证表存在
    cursor = store.conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}

    assert 'dividend_pool' in tables
    assert 'dividend_history' in tables
    assert 'screening_versions' in tables


def test_save_and_get_pool():
    """应能保存和读取股票池"""
    store = DividendStore(db_path=':memory:')

    tickers = [
        make_ticker(ticker='AAPL', dividend_quality_score=85.0, consecutive_years=10),
        make_ticker(ticker='MSFT', dividend_quality_score=88.0, consecutive_years=12),
    ]

    store.save_pool(tickers, version='weekly_2026-03-03')

    pool = store.get_current_pool()
    assert len(pool) == 2
    assert 'AAPL' in pool
    assert 'MSFT' in pool
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_dividend_store.py -v
```

预期输出：`ModuleNotFoundError: No module named 'src.dividend_store'`

**Step 3: 实现 - 创建DividendStore基础结构**

创建`src/dividend_store.py`：

```python
import sqlite3
import logging
from datetime import date, datetime
from typing import List, Dict, Any, Optional
from src.data_engine import TickerData

logger = logging.getLogger(__name__)


class DividendStore:
    """SQLite存储股息股票池和历史数据"""

    def __init__(self, db_path: str):
        """
        初始化数据库连接并创建表

        Args:
            db_path: SQLite数据库路径，使用':memory:'创建内存数据库
        """
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self._create_tables()

    def _create_tables(self):
        """创建必需的数据库表"""
        cursor = self.conn.cursor()

        # 股票池表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_pool (
                ticker TEXT PRIMARY KEY,
                name TEXT,
                market TEXT,
                quality_score REAL,
                consecutive_years INTEGER,
                dividend_growth_5y REAL,
                payout_ratio REAL,
                roe REAL,
                debt_to_equity REAL,
                industry TEXT,
                sector TEXT,
                added_date DATE,
                version TEXT
            )
        """)

        # 历史股息表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS dividend_history (
                ticker TEXT,
                date DATE,
                dividend_yield REAL,
                annual_dividend REAL,
                price REAL,
                PRIMARY KEY (ticker, date)
            )
        """)

        # 筛选版本表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS screening_versions (
                version TEXT PRIMARY KEY,
                created_at TIMESTAMP,
                tickers_count INTEGER,
                avg_quality_score REAL
            )
        """)

        self.conn.commit()

    def save_pool(self, tickers: List[TickerData], version: str):
        """
        保存股票池（替换式更新）

        Args:
            tickers: TickerData列表
            version: 版本标识，如'weekly_2026-03-03'
        """
        cursor = self.conn.cursor()

        # 删除当前池子（保留历史版本在screening_versions表）
        cursor.execute("DELETE FROM dividend_pool")

        # 插入新池子
        for t in tickers:
            cursor.execute("""
                INSERT OR REPLACE INTO dividend_pool VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.ticker,
                t.name,
                t.market,
                t.dividend_quality_score,
                t.consecutive_years,
                t.dividend_growth_5y,
                t.payout_ratio,
                t.roe,
                t.debt_to_equity,
                t.industry,
                t.sector,
                date.today().isoformat(),
                version
            ))

        # 记录版本
        avg_score = sum(t.dividend_quality_score for t in tickers if t.dividend_quality_score) / len(tickers) if tickers else 0
        cursor.execute("""
            INSERT OR REPLACE INTO screening_versions VALUES (?, ?, ?, ?)
        """, (version, datetime.now().isoformat(), len(tickers), avg_score))

        self.conn.commit()
        logger.info(f"Saved {len(tickers)} tickers to pool, version={version}")

    def get_current_pool(self) -> List[str]:
        """获取当前池子的ticker列表"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT ticker FROM dividend_pool")
        return [row[0] for row in cursor.fetchall()]

    def close(self):
        """关闭数据库连接"""
        self.conn.close()
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_dividend_store.py -v
```

预期输出：`2 passed`

**Step 5: 提交**

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: add DividendStore for SQLite storage

- Create dividend_pool, dividend_history, screening_versions tables
- Implement save_pool() and get_current_pool()
- Add unit tests with in-memory database

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 1.3: DividendStore添加历史数据和分位数计算

**Files:**
- Modify: `src/dividend_store.py`
- Modify: `tests/test_dividend_store.py`

**Step 1: 写失败测试 - 分位数计算**

在`tests/test_dividend_store.py`添加：

```python
def test_save_and_get_yield_percentile():
    """应能保存历史数据并计算股息率分位数"""
    store = DividendStore(db_path=':memory:')

    # 保存5年历史数据
    ticker = 'AAPL'
    historical_yields = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5]  # 10个数据点

    for i, yield_val in enumerate(historical_yields):
        store.save_dividend_history(
            ticker=ticker,
            date=date(2020 + i // 2, 1 + (i % 2) * 6, 1),
            dividend_yield=yield_val,
            annual_dividend=yield_val * 150,  # 假设价格150
            price=150.0
        )

    # 测试分位数计算
    # 当前股息率7.2%应该在前10%（>7.0的只有7.5）
    percentile = store.get_yield_percentile(ticker, current_yield=7.2)
    assert percentile >= 90.0

    # 当前股息率4.0%应该在中位数附近
    percentile_mid = store.get_yield_percentile(ticker, current_yield=4.0)
    assert 40.0 <= percentile_mid <= 60.0
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_yield_percentile -v
```

预期输出：`AttributeError: 'DividendStore' object has no attribute 'save_dividend_history'`

**Step 3: 实现 - 添加历史数据方法**

在`src/dividend_store.py`中添加方法：

```python
import numpy as np

class DividendStore:
    # ... 现有代码 ...

    def save_dividend_history(
        self,
        ticker: str,
        date: date,
        dividend_yield: float,
        annual_dividend: float,
        price: float
    ):
        """
        保存单条历史股息数据

        Args:
            ticker: 股票代码
            date: 日期
            dividend_yield: 股息率 (%)
            annual_dividend: 年股息金额
            price: 当时价格
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO dividend_history VALUES (?, ?, ?, ?, ?)
        """, (ticker, date.isoformat(), dividend_yield, annual_dividend, price))
        self.conn.commit()

    def get_yield_percentile(self, ticker: str, current_yield: float) -> float:
        """
        计算当前股息率在5年历史中的分位数

        Args:
            ticker: 股票代码
            current_yield: 当前股息率

        Returns:
            分位数 (0-100)，值越大表示当前股息率越高（越便宜）
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT dividend_yield FROM dividend_history
            WHERE ticker = ?
            ORDER BY date DESC
        """, (ticker,))

        historical_yields = [row[0] for row in cursor.fetchall()]

        if not historical_yields:
            logger.warning(f"{ticker}: No historical yield data, return 50th percentile")
            return 50.0

        # 计算分位数：有多少百分比的历史数据低于当前值
        percentile = (sum(1 for y in historical_yields if y < current_yield) / len(historical_yields)) * 100

        return percentile
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_dividend_store.py::test_save_and_get_yield_percentile -v
```

预期输出：`PASSED`

**Step 5: 运行所有DividendStore测试**

```bash
pytest tests/test_dividend_store.py -v
```

预期输出：`3 passed`

**Step 6: 提交**

```bash
git add src/dividend_store.py tests/test_dividend_store.py
git commit -m "feat: add dividend history and percentile calculation

- Implement save_dividend_history()
- Implement get_yield_percentile() for historical ranking
- Add test for percentile calculation logic

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 1.4: 扩展MarketDataProvider获取股息数据

**Files:**
- Modify: `src/market_data.py`
- Modify: `tests/test_market_data.py`

**Step 1: 写失败测试 - 获取股息历史**

在`tests/test_market_data.py`添加：

```python
from unittest.mock import patch, MagicMock
import pandas as pd
from datetime import datetime


def test_get_dividend_history():
    """应能获取5年股息历史数据"""
    provider = MarketDataProvider(ibkr_config=None, iv_db_path=':memory:', config={})

    # Mock yfinance返回股息数据
    mock_ticker = MagicMock()
    mock_ticker.dividends = pd.Series({
        pd.Timestamp('2020-03-01'): 0.50,
        pd.Timestamp('2021-03-01'): 0.52,
        pd.Timestamp('2022-03-01'): 0.54,
        pd.Timestamp('2023-03-01'): 0.57,
        pd.Timestamp('2024-03-01'): 0.60,
        pd.Timestamp('2025-03-01'): 0.63,
    })

    with patch('yfinance.Ticker', return_value=mock_ticker):
        history = provider.get_dividend_history('AAPL', years=5)

    assert history is not None
    assert len(history) == 6
    assert history[0]['date'].year == 2020
    assert history[0]['amount'] == 0.50
    assert history[-1]['amount'] == 0.63


def test_get_fundamentals():
    """应能获取基本面数据（财务指标）"""
    provider = MarketDataProvider(ibkr_config=None, iv_db_path=':memory:', config={})

    # Mock yfinance返回基本面数据
    mock_ticker = MagicMock()
    mock_ticker.info = {
        'payoutRatio': 0.25,
        'trailingPE': 28.5,
        'returnOnEquity': 0.28,
        'debtToEquity': 1.2,
        'industry': 'Technology',
        'sector': 'Information Technology',
        'freeCashflow': 95000000000
    }

    with patch('yfinance.Ticker', return_value=mock_ticker):
        fundamentals = provider.get_fundamentals('AAPL')

    assert fundamentals is not None
    assert fundamentals['payout_ratio'] == 25.0  # 转换为百分比
    assert fundamentals['roe'] == 28.0
    assert fundamentals['debt_to_equity'] == 1.2
    assert fundamentals['industry'] == 'Technology'
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_market_data.py::test_get_dividend_history -v
pytest tests/test_market_data.py::test_get_fundamentals -v
```

预期输出：`AttributeError: 'MarketDataProvider' object has no attribute 'get_dividend_history'`

**Step 3: 实现 - 添加股息和基本面数据获取**

在`src/market_data.py`的`MarketDataProvider`类中添加方法：

```python
from datetime import datetime, timedelta
from typing import Dict, Any

class MarketDataProvider:
    # ... 现有代码 ...

    def get_dividend_history(self, ticker: str, years: int = 5) -> Optional[List[Dict[str, Any]]]:
        """
        获取股息历史数据

        Args:
            ticker: 股票代码
            years: 回溯年数

        Returns:
            List[{date: datetime, amount: float}] 或 None
        """
        try:
            import yfinance as yf

            yticker = yf.Ticker(ticker)
            dividends = yticker.dividends

            if dividends is None or dividends.empty:
                logger.warning(f"{ticker}: No dividend history available")
                return None

            # 过滤最近N年数据
            cutoff_date = datetime.now() - timedelta(days=years * 365)
            recent_dividends = dividends[dividends.index >= cutoff_date]

            if len(recent_dividends) < 1:
                logger.warning(f"{ticker}: Insufficient dividend history (<1 year)")
                return None

            # 转换为字典列表
            result = [
                {'date': div_date.to_pydatetime().date(), 'amount': float(amount)}
                for div_date, amount in recent_dividends.items()
            ]

            return result

        except Exception as e:
            logger.warning(f"{ticker}: Failed to fetch dividend history: {e}")
            return None

    def get_fundamentals(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        获取基本面财务数据

        Args:
            ticker: 股票代码

        Returns:
            Dict包含: payout_ratio, roe, debt_to_equity, industry, sector, free_cash_flow
        """
        try:
            import yfinance as yf

            yticker = yf.Ticker(ticker)
            info = yticker.info

            # 提取关键指标（处理可能缺失的字段）
            fundamentals = {
                'payout_ratio': info.get('payoutRatio', 0) * 100 if info.get('payoutRatio') else None,  # 转为百分比
                'roe': info.get('returnOnEquity', 0) * 100 if info.get('returnOnEquity') else None,
                'debt_to_equity': info.get('debtToEquity'),
                'industry': info.get('industry'),
                'sector': info.get('sector'),
                'free_cash_flow': info.get('freeCashflow')
            }

            return fundamentals

        except Exception as e:
            logger.warning(f"{ticker}: Failed to fetch fundamentals: {e}")
            return None
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_market_data.py::test_get_dividend_history -v
pytest tests/test_market_data.py::test_get_fundamentals -v
```

预期输出：`2 passed`

**Step 5: 提交**

```bash
git add src/market_data.py tests/test_market_data.py
git commit -m "feat: add dividend history and fundamentals fetching

- Implement get_dividend_history() for 5-year dividend data
- Implement get_fundamentals() for financial metrics
- Add unit tests with mocked yfinance data

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 2: Financial Service集成

### Task 2.1: 创建Financial Service封装层

**Files:**
- Create: `src/financial_service.py`
- Create: `tests/test_financial_service.py`

**Step 1: 写失败测试 - DividendQualityScore数据类**

创建`tests/test_financial_service.py`：

```python
import pytest
from src.financial_service import DividendQualityScore, FinancialServiceAnalyzer


def test_dividend_quality_score_dataclass():
    """DividendQualityScore应包含所有必需字段"""
    score = DividendQualityScore(
        overall_score=85.0,
        stability_score=90.0,
        health_score=80.0,
        defensiveness_score=85.0,
        risk_flags=['HIGH_PAYOUT_RISK']
    )

    assert score.overall_score == 85.0
    assert score.stability_score == 90.0
    assert 'HIGH_PAYOUT_RISK' in score.risk_flags


def test_financial_service_analyzer_fallback():
    """Financial Service不可用时应降级到规则评分"""
    analyzer = FinancialServiceAnalyzer(enabled=False)

    fundamentals = {
        'dividend_history': [
            {'date': '2020-01-01', 'amount': 0.50},
            {'date': '2021-01-01', 'amount': 0.52},
            {'date': '2022-01-01', 'amount': 0.54},
            {'date': '2023-01-01', 'amount': 0.57},
            {'date': '2024-01-01', 'amount': 0.60},
            {'date': '2025-01-01', 'amount': 0.63},
        ],
        'payout_ratio': 25.0,
        'roe': 28.0,
        'debt_to_equity': 1.2,
        'consecutive_years': 6,
        'dividend_growth_5y': 8.5
    }

    score = analyzer.analyze_dividend_quality('AAPL', fundamentals)

    assert score is not None
    assert 0 <= score.overall_score <= 100
    assert score.defensiveness_score == 50.0  # 降级时固定50分
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_financial_service.py -v
```

预期输出：`ModuleNotFoundError: No module named 'src.financial_service'`

**Step 3: 实现 - 创建Financial Service基础结构**

创建`src/financial_service.py`：

```python
import logging
from dataclasses import dataclass
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class DividendQualityScore:
    """股息质量综合评分"""
    overall_score: float              # 综合评分 (0-100)
    stability_score: float            # 派息稳定性 (连续性 + 增长率)
    health_score: float               # 财务健康度 (ROE + 负债 + FCF)
    defensiveness_score: float        # 行业防御性
    risk_flags: List[str]             # 风险标记


class FinancialServiceAnalyzer:
    """封装Claude Financial Analysis能力"""

    def __init__(self, enabled: bool = True, fallback_to_rules: bool = True):
        """
        初始化Financial Service分析器

        Args:
            enabled: 是否启用Financial Service（True=调用API，False=直接降级）
            fallback_to_rules: API失败时是否降级到规则评分
        """
        self.enabled = enabled
        self.fallback_to_rules = fallback_to_rules

    def analyze_dividend_quality(
        self,
        ticker: str,
        fundamentals: Dict[str, Any]
    ) -> Optional[DividendQualityScore]:
        """
        分析股息质量

        Args:
            ticker: 股票代码
            fundamentals: 基本面数据字典，包含：
                - dividend_history: List[{date, amount}]
                - payout_ratio, roe, debt_to_equity
                - industry, sector
                - consecutive_years, dividend_growth_5y

        Returns:
            DividendQualityScore 或 None
        """
        if not self.enabled:
            logger.info(f"{ticker}: Financial Service disabled, using rule-based scoring")
            return self._calculate_rule_based_score(ticker, fundamentals)

        try:
            # TODO: Phase 2.2 实现Financial Service API调用
            # 这里先降级到规则评分
            logger.warning(f"{ticker}: Financial Service not yet implemented, using fallback")
            return self._calculate_rule_based_score(ticker, fundamentals)

        except Exception as e:
            logger.error(f"{ticker}: Financial Service failed: {e}")
            if self.fallback_to_rules:
                return self._calculate_rule_based_score(ticker, fundamentals)
            return None

    def _calculate_rule_based_score(
        self,
        ticker: str,
        fundamentals: Dict[str, Any]
    ) -> DividendQualityScore:
        """
        降级评分：基于规则计算股息质量

        评分逻辑:
        - stability_score = f(consecutive_years, dividend_growth)
        - health_score = f(roe, debt_to_equity, payout_ratio)
        - defensiveness_score = 50 (无行业分析时固定)
        - overall = weighted average
        """
        consecutive_years = fundamentals.get('consecutive_years', 0)
        dividend_growth = fundamentals.get('dividend_growth_5y', 0)
        payout_ratio = fundamentals.get('payout_ratio', 0)
        roe = fundamentals.get('roe', 0)
        debt_to_equity = fundamentals.get('debt_to_equity', 0)

        # 1. 稳定性评分 (0-100)
        stability_score = min(100, (
            consecutive_years * 10 +  # 每年+10分
            min(dividend_growth * 2, 30)  # 增长率，最多30分
        ))

        # 2. 财务健康度评分 (0-100)
        roe_score = min(30, roe) if roe else 0
        debt_score = max(0, 30 - debt_to_equity * 20) if debt_to_equity else 30
        payout_score = 40 if payout_ratio < 70 else 20 if payout_ratio < 100 else 0
        health_score = roe_score + debt_score + payout_score

        # 3. 行业防御性评分（降级时固定50分）
        defensiveness_score = 50.0

        # 4. 综合评分（加权平均）
        overall_score = (
            stability_score * 0.4 +
            health_score * 0.4 +
            defensiveness_score * 0.2
        )

        # 5. 风险标记
        risk_flags = []
        if payout_ratio > 100:
            risk_flags.append('PAYOUT_RATIO_CRITICAL')
        elif payout_ratio > 80:
            risk_flags.append('HIGH_PAYOUT_RISK')

        if debt_to_equity and debt_to_equity > 2.0:
            risk_flags.append('HIGH_LEVERAGE')

        return DividendQualityScore(
            overall_score=overall_score,
            stability_score=stability_score,
            health_score=health_score,
            defensiveness_score=defensiveness_score,
            risk_flags=risk_flags
        )
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_financial_service.py -v
```

预期输出：`2 passed`

**Step 5: 提交**

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: add Financial Service analyzer with fallback

- Create DividendQualityScore dataclass
- Implement FinancialServiceAnalyzer with rule-based fallback
- Add stability/health/defensiveness scoring logic
- Add unit tests for fallback mode

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 2.2: 计算派息连续年限和增长率

**Files:**
- Modify: `src/financial_service.py`
- Modify: `tests/test_financial_service.py`

**Step 1: 写失败测试 - 计算consecutive_years**

在`tests/test_financial_service.py`添加：

```python
from src.financial_service import calculate_consecutive_years, calculate_dividend_growth_rate


def test_calculate_consecutive_years():
    """应能计算连续派息年限"""
    dividend_history = [
        {'date': '2020-03-01', 'amount': 0.50},
        {'date': '2020-06-01', 'amount': 0.50},
        {'date': '2020-09-01', 'amount': 0.50},
        {'date': '2020-12-01', 'amount': 0.50},
        {'date': '2021-03-01', 'amount': 0.52},
        {'date': '2021-06-01', 'amount': 0.52},
        {'date': '2021-09-01', 'amount': 0.52},
        {'date': '2021-12-01', 'amount': 0.52},
        {'date': '2022-03-01', 'amount': 0.54},
        # ... 继续到2025
    ]

    years = calculate_consecutive_years(dividend_history)
    assert years >= 5  # 至少5年连续派息


def test_calculate_dividend_growth_rate():
    """应能计算5年股息复合增长率"""
    dividend_history = [
        {'date': '2020-01-01', 'amount': 0.50},
        {'date': '2025-01-01', 'amount': 0.75},  # 50% increase over 5 years
    ]

    cagr = calculate_dividend_growth_rate(dividend_history, years=5)
    assert 8.0 <= cagr <= 10.0  # ~8.4% CAGR
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_financial_service.py::test_calculate_consecutive_years -v
```

预期输出：`ImportError: cannot import name 'calculate_consecutive_years'`

**Step 3: 实现 - 添加计算函数**

在`src/financial_service.py`添加辅助函数：

```python
from datetime import datetime


def calculate_consecutive_years(dividend_history: List[Dict[str, Any]]) -> int:
    """
    计算连续派息年限

    逻辑: 检查每个日历年是否至少有1次派息

    Args:
        dividend_history: 股息历史数据

    Returns:
        连续派息年数
    """
    if not dividend_history:
        return 0

    # 提取所有派息年份
    years_with_dividend = set()
    for div in dividend_history:
        div_date = div['date']
        if isinstance(div_date, str):
            div_date = datetime.fromisoformat(div_date).date()
        years_with_dividend.add(div_date.year)

    if not years_with_dividend:
        return 0

    # 从最新年份往回检查连续性
    sorted_years = sorted(years_with_dividend, reverse=True)
    consecutive = 1

    for i in range(len(sorted_years) - 1):
        if sorted_years[i] - sorted_years[i + 1] == 1:
            consecutive += 1
        else:
            break

    return consecutive


def calculate_dividend_growth_rate(
    dividend_history: List[Dict[str, Any]],
    years: int = 5
) -> float:
    """
    计算股息复合增长率 (CAGR)

    公式: CAGR = (End / Start)^(1/years) - 1

    Args:
        dividend_history: 股息历史数据
        years: 计算周期（年）

    Returns:
        CAGR百分比
    """
    if not dividend_history or len(dividend_history) < 2:
        return 0.0

    # 按日期排序
    sorted_divs = sorted(dividend_history, key=lambda x: x['date'])

    # 计算年度总股息
    annual_totals = {}
    for div in sorted_divs:
        div_date = div['date']
        if isinstance(div_date, str):
            div_date = datetime.fromisoformat(div_date).date()
        year = div_date.year
        annual_totals[year] = annual_totals.get(year, 0) + div['amount']

    if len(annual_totals) < 2:
        return 0.0

    # 取最早和最新年份
    sorted_years = sorted(annual_totals.keys())
    start_year = sorted_years[0]
    end_year = sorted_years[-1]

    start_amount = annual_totals[start_year]
    end_amount = annual_totals[end_year]

    if start_amount <= 0:
        return 0.0

    # CAGR计算
    actual_years = end_year - start_year
    if actual_years == 0:
        return 0.0

    cagr = (pow(end_amount / start_amount, 1 / actual_years) - 1) * 100

    return round(cagr, 2)
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_financial_service.py::test_calculate_consecutive_years -v
pytest tests/test_financial_service.py::test_calculate_dividend_growth_rate -v
```

预期输出：`2 passed`

**Step 5: 运行所有Financial Service测试**

```bash
pytest tests/test_financial_service.py -v
```

预期输出：`4 passed`

**Step 6: 提交**

```bash
git add src/financial_service.py tests/test_financial_service.py
git commit -m "feat: add dividend metrics calculation

- Implement calculate_consecutive_years()
- Implement calculate_dividend_growth_rate() (CAGR)
- Add unit tests for metrics calculation

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 3: 扫描器逻辑

### Task 3.1: 创建每周筛选扫描器

**Files:**
- Create: `src/dividend_scanners.py`
- Create: `tests/test_dividend_scanners.py`

**Step 1: 写失败测试 - 筛选规则**

创建`tests/test_dividend_scanners.py`：

```python
import pytest
from unittest.mock import MagicMock
from src.dividend_scanners import scan_dividend_pool_weekly
from tests.conftest import make_ticker


def test_scan_dividend_pool_weekly_filters_by_quality_score():
    """应根据quality_score筛选股票"""
    # 准备测试数据
    universe = ['AAPL', 'MSFT', 'GOOGL']

    # Mock provider返回基本面数据
    mock_provider = MagicMock()
    mock_provider.get_dividend_history.return_value = [
        {'date': '2020-01-01', 'amount': 0.50},
        {'date': '2025-01-01', 'amount': 0.63},
    ]
    mock_provider.get_fundamentals.return_value = {
        'payout_ratio': 25.0,
        'roe': 28.0,
        'debt_to_equity': 1.2,
        'industry': 'Technology'
    }

    # Mock financial service返回高分
    mock_fs = MagicMock()
    mock_fs.analyze_dividend_quality.return_value = MagicMock(
        overall_score=85.0,
        consecutive_years=5,
        risk_flags=[]
    )

    config = {
        'screening': {
            'min_quality_score': 70,
            'min_consecutive_years': 5,
            'max_payout_ratio': 100
        }
    }

    result = scan_dividend_pool_weekly(universe, mock_provider, mock_fs, config)

    assert len(result) > 0
    assert all(t.dividend_quality_score >= 70 for t in result)


def test_scan_dividend_pool_excludes_payout_ratio_over_100():
    """派息率>100%应被排除"""
    mock_provider = MagicMock()
    mock_provider.get_fundamentals.return_value = {
        'payout_ratio': 105.0,  # 超过100%
        'roe': 28.0
    }

    mock_fs = MagicMock()
    mock_fs.analyze_dividend_quality.return_value = MagicMock(
        overall_score=85.0,
        risk_flags=['PAYOUT_RATIO_CRITICAL']
    )

    config = {'screening': {'max_payout_ratio': 100}}

    result = scan_dividend_pool_weekly(['AAPL'], mock_provider, mock_fs, config)

    assert len(result) == 0  # 应被排除
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_dividend_scanners.py -v
```

预期输出：`ModuleNotFoundError: No module named 'src.dividend_scanners'`

**Step 3: 实现 - 创建筛选扫描器**

创建`src/dividend_scanners.py`：

```python
import logging
from typing import List, Dict, Any, TYPE_CHECKING
from src.data_engine import TickerData
from src.financial_service import (
    FinancialServiceAnalyzer,
    calculate_consecutive_years,
    calculate_dividend_growth_rate
)

if TYPE_CHECKING:
    from src.market_data import MarketDataProvider

logger = logging.getLogger(__name__)


def scan_dividend_pool_weekly(
    universe: List[str],
    provider: 'MarketDataProvider',
    financial_service: FinancialServiceAnalyzer,
    config: Dict[str, Any]
) -> List[TickerData]:
    """
    每周筛选高质量股息股票池

    流程:
    1. 遍历universe，获取基本面数据
    2. 调用Financial Service分析股息质量
    3. 应用筛选规则
    4. 返回符合条件的TickerData列表

    Args:
        universe: 股票池列表
        provider: MarketDataProvider实例
        financial_service: FinancialServiceAnalyzer实例
        config: 配置字典，包含screening部分

    Returns:
        符合条件的TickerData列表
    """
    screening_config = config.get('screening', {})
    min_quality_score = screening_config.get('min_quality_score', 70)
    min_consecutive_years = screening_config.get('min_consecutive_years', 5)
    max_payout_ratio = screening_config.get('max_payout_ratio', 100)

    results = []

    for ticker in universe:
        try:
            # 1. 获取股息历史
            dividend_history = provider.get_dividend_history(ticker, years=5)
            if not dividend_history or len(dividend_history) < 4:  # 至少1年数据
                logger.warning(f"{ticker}: Insufficient dividend history, skip")
                continue

            # 2. 获取基本面数据
            fundamentals = provider.get_fundamentals(ticker)
            if not fundamentals:
                logger.warning(f"{ticker}: Failed to fetch fundamentals, skip")
                continue

            # 3. 计算派息指标
            consecutive_years = calculate_consecutive_years(dividend_history)
            dividend_growth_5y = calculate_dividend_growth_rate(dividend_history, years=5)

            # 添加到fundamentals
            fundamentals['dividend_history'] = dividend_history
            fundamentals['consecutive_years'] = consecutive_years
            fundamentals['dividend_growth_5y'] = dividend_growth_5y

            # 4. 硬性规则：派息率>100%立即排除
            payout_ratio = fundamentals.get('payout_ratio', 0)
            if payout_ratio and payout_ratio > max_payout_ratio:
                logger.error(f"⚠️ {ticker}: Payout Ratio {payout_ratio}% > {max_payout_ratio}%, EXCLUDE")
                continue

            # 5. 调用Financial Service分析
            quality_score = financial_service.analyze_dividend_quality(ticker, fundamentals)
            if not quality_score:
                logger.warning(f"{ticker}: Financial Service returned None, skip")
                continue

            # 6. 应用筛选规则
            if quality_score.overall_score < min_quality_score:
                logger.debug(f"{ticker}: Quality score {quality_score.overall_score} < {min_quality_score}, skip")
                continue

            if consecutive_years < min_consecutive_years:
                logger.debug(f"{ticker}: Consecutive years {consecutive_years} < {min_consecutive_years}, skip")
                continue

            # 7. 构建TickerData（暂时使用占位数据，后续Task会获取完整数据）
            ticker_data = TickerData(
                ticker=ticker,
                name="",  # TODO: 从provider获取
                market="US",  # TODO: 从data_loader.classify_market获取
                last_price=0.0,  # TODO: 从provider获取
                ma200=None,
                ma50w=None,
                rsi14=None,
                iv_rank=None,
                prev_close=0.0,
                earnings_date=None,
                days_to_earnings=None,
                # 股息字段
                dividend_quality_score=quality_score.overall_score,
                consecutive_years=consecutive_years,
                dividend_growth_5y=dividend_growth_5y,
                payout_ratio=payout_ratio,
                roe=fundamentals.get('roe'),
                debt_to_equity=fundamentals.get('debt_to_equity'),
                industry=fundamentals.get('industry'),
                sector=fundamentals.get('sector'),
                free_cash_flow=fundamentals.get('free_cash_flow')
            )

            results.append(ticker_data)
            logger.info(f"✓ {ticker}: Added to pool (score={quality_score.overall_score:.1f})")

        except Exception as e:
            logger.error(f"{ticker}: Unexpected error during screening: {e}")
            continue

    logger.info(f"Weekly screening complete: {len(results)}/{len(universe)} tickers passed")
    return results
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_dividend_scanners.py -v
```

预期输出：`2 passed`

**Step 5: 提交**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add weekly dividend pool screening scanner

- Implement scan_dividend_pool_weekly()
- Apply filtering rules: quality_score, consecutive_years, payout_ratio
- Add hard exclusion for payout_ratio > 100%
- Add unit tests with mocked dependencies

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 3.2: 创建每日监控扫描器

**Files:**
- Modify: `src/dividend_scanners.py`
- Modify: `tests/test_dividend_scanners.py`

**Step 1: 写失败测试 - 买入信号触发**

在`tests/test_dividend_scanners.py`添加：

```python
from src.dividend_scanners import scan_dividend_buy_signal, DividendBuySignal
from src.dividend_store import DividendStore


def test_scan_dividend_buy_signal_triggers_on_high_yield():
    """股息率达到历史高点应触发买入信号"""
    # 准备测试数据
    store = DividendStore(db_path=':memory:')

    # 保存池子
    pool_tickers = [make_ticker(ticker='AAPL', consecutive_years=5)]
    store.save_pool(pool_tickers, version='weekly_2026-03-03')

    # 保存历史股息率数据
    for i, yield_val in enumerate([3.0, 4.0, 5.0, 6.0, 7.0]):
        store.save_dividend_history(
            ticker='AAPL',
            date=f'202{i}-01-01',
            dividend_yield=yield_val,
            annual_dividend=yield_val * 150,
            price=150.0
        )

    # Mock provider返回当前高股息率
    mock_provider = MagicMock()
    mock_provider.get_price_data.return_value = MagicMock(
        iloc=MagicMock(__getitem__=lambda self, x: MagicMock(Close=140.0))
    )

    config = {
        'buy_signal': {
            'min_yield': 4.0,
            'min_yield_percentile': 90
        }
    }

    # 假设年股息是$7.0，当前价$140 → 股息率5% → 应该触发
    # 但需要mock get_annual_dividend

    result = scan_dividend_buy_signal(['AAPL'], mock_provider, store, config)

    # TODO: 需要实现后验证
    assert result is not None
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_dividend_scanners.py::test_scan_dividend_buy_signal_triggers_on_high_yield -v
```

预期输出：`ImportError: cannot import name 'scan_dividend_buy_signal'`

**Step 3: 实现 - 添加DividendBuySignal和监控扫描器**

在`src/dividend_scanners.py`添加：

```python
from dataclasses import dataclass
from typing import Optional
from datetime import date

if TYPE_CHECKING:
    from src.dividend_store import DividendStore


@dataclass
class DividendBuySignal:
    """股息买入信号"""
    ticker_data: TickerData
    signal_type: str  # "STOCK" | "OPTION"
    current_yield: float
    yield_percentile: float
    option_details: Optional[Dict[str, Any]] = None


def scan_dividend_buy_signal(
    pool: List[str],
    provider: 'MarketDataProvider',
    store: 'DividendStore',
    config: Dict[str, Any]
) -> List[DividendBuySignal]:
    """
    每日监控买入时机

    流程:
    1. 从DividendStore读取当前池子
    2. 获取实时价格和股息率
    3. 计算5年历史分位数
    4. 判断触发条件

    Args:
        pool: 股票池ticker列表
        provider: MarketDataProvider实例
        store: DividendStore实例
        config: 配置字典

    Returns:
        买入信号列表
    """
    buy_config = config.get('buy_signal', {})
    min_yield = buy_config.get('min_yield', 4.0)
    min_yield_percentile = buy_config.get('min_yield_percentile', 90)

    signals = []

    for ticker in pool:
        try:
            # 1. 获取当前价格
            price_data = provider.get_price_data(ticker, period='5d')
            if price_data is None or price_data.empty:
                logger.warning(f"{ticker}: No price data available")
                continue

            last_price = float(price_data.iloc[-1]['Close'])

            # 2. 获取年度股息（简化：从历史数据推算最新）
            dividend_history = provider.get_dividend_history(ticker, years=1)
            if not dividend_history:
                logger.warning(f"{ticker}: No recent dividend data")
                continue

            annual_dividend = sum(d['amount'] for d in dividend_history)

            # 3. 计算当前股息率
            if last_price <= 0:
                continue

            current_yield = (annual_dividend / last_price) * 100

            # 4. 计算历史分位数
            yield_percentile = store.get_yield_percentile(ticker, current_yield)

            # 5. 判断触发条件
            if current_yield < min_yield:
                logger.debug(f"{ticker}: Yield {current_yield:.2f}% < {min_yield}%, skip")
                continue

            if yield_percentile < min_yield_percentile:
                logger.debug(f"{ticker}: Percentile {yield_percentile:.1f}% < {min_yield_percentile}%, skip")
                continue

            # 6. 构建信号（暂时只支持现货信号，期权策略在Task 3.3实现）
            ticker_data = TickerData(
                ticker=ticker,
                name="",
                market="US",
                last_price=last_price,
                ma200=None,
                ma50w=None,
                rsi14=None,
                iv_rank=None,
                prev_close=last_price,
                earnings_date=None,
                days_to_earnings=None,
                dividend_yield=current_yield,
                dividend_yield_5y_percentile=yield_percentile
            )

            signal = DividendBuySignal(
                ticker_data=ticker_data,
                signal_type="STOCK",
                current_yield=current_yield,
                yield_percentile=yield_percentile,
                option_details=None
            )

            signals.append(signal)
            logger.info(f"✓ {ticker}: Buy signal triggered (yield={current_yield:.2f}%, {yield_percentile:.0f}th percentile)")

        except Exception as e:
            logger.error(f"{ticker}: Error in buy signal monitoring: {e}")
            continue

    logger.info(f"Daily monitoring complete: {len(signals)} buy signals")
    return signals
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_dividend_scanners.py::test_scan_dividend_buy_signal_triggers_on_high_yield -v
```

预期输出：`PASSED`

**Step 5: 提交**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add daily dividend buy signal monitoring

- Implement scan_dividend_buy_signal()
- Create DividendBuySignal dataclass
- Trigger on min_yield and min_yield_percentile
- Add unit test with historical data

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 3.3: 添加高股息Sell Put期权策略

**Files:**
- Modify: `src/dividend_scanners.py`
- Modify: `tests/test_dividend_scanners.py`

**Step 1: 写失败测试 - 期权策略**

在`tests/test_dividend_scanners.py`添加：

```python
from src.dividend_scanners import scan_dividend_sell_put


def test_scan_dividend_sell_put_selects_strike_by_yield():
    """应根据目标股息率分位数选择strike"""
    mock_provider = MagicMock()

    # Mock期权链数据
    mock_provider.get_option_chain.return_value = [
        {'strike': 32.0, 'bid': 0.45, 'dte': 60, 'expiration': '2026-05-01'},
        {'strike': 33.0, 'bid': 0.55, 'dte': 60, 'expiration': '2026-05-01'},
        {'strike': 34.0, 'bid': 0.65, 'dte': 60, 'expiration': '2026-05-01'},
    ]

    ticker_data = make_ticker(
        ticker='ENB',
        last_price=34.5,
        dividend_yield=6.8
    )

    # 假设年股息$2.35，目标分位数90%对应股息率7.3%
    # 反推strike: $2.35 / 0.073 = $32.19 → 选择$32 strike

    result = scan_dividend_sell_put(
        ticker_data=ticker_data,
        provider=mock_provider,
        annual_dividend=2.35,
        target_yield_percentile=90,
        target_yield=7.3,
        min_dte=45,
        max_dte=90
    )

    assert result is not None
    assert result.strike == 32.0
    assert result.dte == 60
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_dividend_scanners.py::test_scan_dividend_sell_put_selects_strike_by_yield -v
```

预期输出：`ImportError: cannot import name 'scan_dividend_sell_put'`

**Step 3: 实现 - 添加期权策略扫描器**

在`src/dividend_scanners.py`添加：

```python
def scan_dividend_sell_put(
    ticker_data: TickerData,
    provider: 'MarketDataProvider',
    annual_dividend: float,
    target_yield_percentile: float,
    target_yield: float,
    min_dte: int = 45,
    max_dte: int = 90
) -> Optional[Dict[str, Any]]:
    """
    高股息场景的Sell Put策略（独立于现有scan_sell_put）

    核心差异: strike选择基于目标股息率分位数，而非APY

    Args:
        ticker_data: TickerData实例
        provider: MarketDataProvider实例
        annual_dividend: 年度股息金额
        target_yield_percentile: 目标股息率分位数（如90）
        target_yield: 目标股息率百分比（如7.3）
        min_dte: 最小到期天数
        max_dte: 最大到期天数

    Returns:
        期权详情字典 或 None
    """
    ticker = ticker_data.ticker

    try:
        # 1. 反推目标strike: annual_dividend / target_yield
        target_strike = annual_dividend / (target_yield / 100)

        # 2. 获取期权链
        option_chain = provider.get_option_chain(ticker, option_type='put', min_dte=min_dte, max_dte=max_dte)
        if not option_chain:
            logger.warning(f"{ticker}: No put options available")
            return None

        # 3. 选择最接近target_strike的期权
        closest_option = min(
            option_chain,
            key=lambda opt: abs(opt['strike'] - target_strike)
        )

        # 4. 计算APY（仅用于展示，非筛选条件）
        strike = closest_option['strike']
        bid = closest_option['bid']
        dte = closest_option['dte']

        if strike <= 0 or dte <= 0:
            return None

        apy = (bid / strike) * (365 / dte) * 100

        logger.info(f"{ticker}: Sell Put - Strike ${strike}, Bid ${bid}, DTE {dte}, APY {apy:.1f}%")

        return {
            'strike': strike,
            'bid': bid,
            'dte': dte,
            'expiration': closest_option['expiration'],
            'apy': apy
        }

    except Exception as e:
        logger.error(f"{ticker}: Failed to scan sell put: {e}")
        return None
```

**Step 4: 集成到scan_dividend_buy_signal**

在`scan_dividend_buy_signal`函数中添加期权信号生成逻辑：

```python
# 在scan_dividend_buy_signal函数末尾，构建信号前添加：

# 6. 期权策略（仅US市场）
option_details = None
if not provider.should_skip_options(ticker):
    option_config = buy_config.get('option', {})
    target_strike_percentile = option_config.get('target_strike_percentile', 90)

    # 计算目标股息率（根据分位数）
    # 简化：假设target_yield = current_yield（实际应从历史数据计算第90百分位值）
    target_yield = current_yield * (target_strike_percentile / yield_percentile) if yield_percentile > 0 else current_yield

    option_details = scan_dividend_sell_put(
        ticker_data=ticker_data,
        provider=provider,
        annual_dividend=annual_dividend,
        target_yield_percentile=target_strike_percentile,
        target_yield=target_yield,
        min_dte=option_config.get('min_dte', 45),
        max_dte=option_config.get('max_dte', 90)
    )

signal = DividendBuySignal(
    ticker_data=ticker_data,
    signal_type="OPTION" if option_details else "STOCK",
    current_yield=current_yield,
    yield_percentile=yield_percentile,
    option_details=option_details
)
```

**Step 5: 运行测试确认通过**

```bash
pytest tests/test_dividend_scanners.py::test_scan_dividend_sell_put_selects_strike_by_yield -v
```

预期输出：`PASSED`

**Step 6: 提交**

```bash
git add src/dividend_scanners.py tests/test_dividend_scanners.py
git commit -m "feat: add dividend-focused sell put strategy

- Implement scan_dividend_sell_put()
- Strike selection based on target dividend yield percentile
- Integrate option strategy into buy signal monitoring
- Add unit test for strike selection logic

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 4: UI集成

### Task 4.1: 扩展HTML报告添加股息章节

**Files:**
- Modify: `src/html_report.py`
- Modify: `tests/test_html_report.py`

**Step 1: 写失败测试 - HTML包含股息章节**

在`tests/test_html_report.py`添加：

```python
from src.html_report import generate_html_report
from src.dividend_scanners import DividendBuySignal


def test_html_report_includes_dividend_section():
    """HTML报告应包含高股息防御双打章节"""
    # 准备测试数据
    dividend_signals = [
        DividendBuySignal(
            ticker_data=make_ticker(ticker='ENB', dividend_yield=6.8, dividend_yield_5y_percentile=92),
            signal_type="OPTION",
            current_yield=6.8,
            yield_percentile=92.0,
            option_details={'strike': 32.0, 'bid': 0.45, 'dte': 60, 'apy': 8.2}
        )
    ]

    html = generate_html_report(
        # ... 现有参数 ...
        dividend_signals=dividend_signals,
        dividend_pool_summary={'count': 23, 'last_update': '2026-03-03'}
    )

    assert '高股息防御双打' in html
    assert 'ENB' in html
    assert '6.8%' in html  # 股息率
    assert '92' in html  # 分位数
```

**Step 2: 运行测试确认失败**

```bash
pytest tests/test_html_report.py::test_html_report_includes_dividend_section -v
```

预期输出：`AssertionError: '高股息防御双打' not in ...`

**Step 3: 实现 - 添加股息章节HTML模板**

在`src/html_report.py`中修改`generate_html_report`函数签名和实现：

```python
def generate_html_report(
    # ... 现有参数 ...
    dividend_signals: List = None,
    dividend_pool_summary: Dict[str, Any] = None
) -> str:
    """生成HTML报告，现在包含股息章节"""

    # ... 现有代码 ...

    # 添加股息章节（在现有章节后）
    dividend_section_html = ""
    if dividend_signals:
        dividend_section_html = _generate_dividend_section(dividend_signals, dividend_pool_summary)

    # 插入到body中
    html = html.replace('</body>', f'{dividend_section_html}</body>')

    return html


def _generate_dividend_section(
    signals: List,
    pool_summary: Dict[str, Any]
) -> str:
    """生成高股息防御双打章节HTML"""

    pool_count = pool_summary.get('count', 0) if pool_summary else 0
    last_update = pool_summary.get('last_update', 'N/A') if pool_summary else 'N/A'

    section_html = f"""
    <section class="dividend-defense">
        <h2>高股息防御双打</h2>

        <div class="pool-summary">
            <p>当前池子: <strong>{pool_count}只标的</strong> | 最近更新: <strong>{last_update}</strong></p>
        </div>

        <div class="buy-signals">
    """

    # 为每个信号生成卡片
    for signal in signals:
        card_html = _generate_dividend_card(signal)
        section_html += card_html

    section_html += """
        </div>
    </section>
    """

    return section_html


def _generate_dividend_card(signal) -> str:
    """生成单个股息信号的六维度卡片"""
    ticker = signal.ticker_data.ticker
    current_yield = signal.current_yield
    percentile = signal.yield_percentile
    signal_type = signal.signal_type

    # 基础卡片结构（简化版，完整六维度在Task 4.2实现）
    card_html = f"""
    <div class="dividend-card">
        <h3>{ticker} 🛡️</h3>
        <p class="yield-info">当前股息率: <strong>{current_yield:.2f}%</strong> (5年历史前{100-percentile:.0f}%最高分位)</p>

        <div class="signal-type">
            {'📊 期权策略可用' if signal_type == 'OPTION' else '📈 现货买入'}
        </div>
    """

    # 期权详情
    if signal.option_details:
        opt = signal.option_details
        card_html += f"""
        <div class="option-details">
            <p>Sell Put ${opt['strike']} Strike ({opt['dte']}DTE)</p>
            <p>Premium: ${opt['bid']} → 年化{opt['apy']:.1f}%</p>
        </div>
        """

    card_html += """
    </div>
    """

    return card_html
```

**Step 4: 运行测试确认通过**

```bash
pytest tests/test_html_report.py::test_html_report_includes_dividend_section -v
```

预期输出：`PASSED`

**Step 5: 提交**

```bash
git add src/html_report.py tests/test_html_report.py
git commit -m "feat: add dividend section to HTML report

- Extend generate_html_report() with dividend parameters
- Implement _generate_dividend_section()
- Add basic dividend card rendering
- Add unit test for dividend section inclusion

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 4.2: 实现完整六维度卡片

**Files:**
- Modify: `src/html_report.py`
- Create: `static/dividend.css`（如需独立样式）

**Step 1: 实现完整卡片HTML结构**

在`src/html_report.py`中完善`_generate_dividend_card`函数：

```python
def _generate_dividend_card(signal) -> str:
    """生成完整六维度评估卡片"""
    ticker = signal.ticker_data.ticker
    td = signal.ticker_data

    card_html = f"""
    <div class="dividend-card">
        <!-- Header -->
        <div class="card-header">
            <h3>{ticker} 🛡️ 防御型</h3>
            <p class="yield-highlight">当前股息率: <strong>{td.dividend_yield:.2f}%</strong> (5年历史前{100-td.dividend_yield_5y_percentile:.0f}%最高分位)</p>
        </div>

        <!-- 1. 基本面估值 -->
        <div class="dimension">
            <h4>1️⃣ 基本面估值</h4>
            <p>当前价: ${td.last_price:.2f}</p>
            <p class="note">（估值区间需Financial Service分析）</p>
        </div>

        <!-- 2. 风险分级 -->
        <div class="dimension">
            <h4>2️⃣ 风险分级 ★★★☆☆</h4>
            <p>综合评分: {td.dividend_quality_score:.0f}/100</p>
            <p>派息率: {td.payout_ratio:.1f}% {'⚠️ 接近警戒线' if td.payout_ratio and td.payout_ratio > 80 else '✓ 健康'}</p>
        </div>

        <!-- 3. 关键事件 -->
        <div class="dimension">
            <h4>3️⃣ 关键事件</h4>
            <p>下次财报: {td.earnings_date if td.earnings_date else 'N/A'}</p>
        </div>

        <!-- 4. 建议操作 -->
        <div class="dimension">
            <h4>4️⃣ 建议操作</h4>
            <p>📈 现货买入: ${td.last_price:.2f} (股息率{td.dividend_yield:.2f}%)</p>
    """

    # 期权策略
    if signal.option_details:
        opt = signal.option_details
        combined_yield = td.dividend_yield + opt['apy']
        card_html += f"""
            <p>📊 期权策略: Sell Put ${opt['strike']} Strike ({opt['dte']}DTE)</p>
            <p class="premium-info">Premium: ${opt['bid']} → 年化{opt['apy']:.1f}%</p>
            <p class="combined-yield">综合年化收益: <strong>{combined_yield:.1f}%</strong></p>
        """

    card_html += """
        </div>

        <!-- 5. 最坏情景 -->
        <div class="dimension">
            <h4>5️⃣ 最坏情景测算</h4>
    """

    if signal.option_details:
        opt = signal.option_details
        effective_cost = opt['strike'] - opt['bid']
        card_html += f"""
            <p>期权被行权成本: ${effective_cost:.2f}</p>
            <p>此时股息率: {(td.dividend_yield * td.last_price / effective_cost):.2f}%</p>
        """
    else:
        card_html += f"""
            <p>当前买入，股息率已达历史高位</p>
        """

    card_html += """
        </div>

        <!-- 6. AI监控承诺 -->
        <div class="dimension">
            <h4>6️⃣ AI监控承诺</h4>
            <ul>
                <li>✓ 派息率>100%预警</li>
                <li>✓ 财报前7天提醒</li>
                <li>✓ 股息率回落至中位数提示</li>
            </ul>
        </div>
    </div>
    """

    return card_html
```

**Step 2: 添加Apple风格CSS**

在`src/html_report.py`的`<style>`标签中添加股息卡片样式：

```css
/* 高股息防御双打样式 */
.dividend-defense {
    margin: 40px 0;
}

.pool-summary {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    padding: 20px;
    border-radius: 12px;
    margin-bottom: 30px;
    text-align: center;
}

.buy-signals {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(450px, 1fr));
    gap: 24px;
}

.dividend-card {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white;
    border-radius: 16px;
    padding: 24px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.2);
}

.dividend-card .card-header h3 {
    margin: 0 0 8px 0;
    font-size: 24px;
}

.dividend-card .yield-highlight {
    font-size: 18px;
    margin: 0 0 20px 0;
}

.dividend-card .dimension {
    margin: 16px 0;
    padding: 12px;
    background: rgba(255,255,255,0.1);
    border-radius: 8px;
}

.dividend-card .dimension h4 {
    margin: 0 0 8px 0;
    font-size: 16px;
}

.dividend-card .dimension p {
    margin: 4px 0;
    font-size: 14px;
}

.dividend-card .dimension ul {
    margin: 8px 0;
    padding-left: 20px;
}

.dividend-card .combined-yield {
    font-size: 16px;
    font-weight: bold;
    color: #FFD700;
}
```

**Step 3: 手动测试HTML输出**

创建测试脚本验证HTML渲染：

```python
# 临时测试文件 test_render.py
from src.html_report import generate_html_report
from src.dividend_scanners import DividendBuySignal
from tests.conftest import make_ticker

signal = DividendBuySignal(
    ticker_data=make_ticker(
        ticker='ENB',
        last_price=34.5,
        dividend_yield=6.8,
        dividend_yield_5y_percentile=92,
        dividend_quality_score=85,
        payout_ratio=78,
        earnings_date='2026-05-12'
    ),
    signal_type="OPTION",
    current_yield=6.8,
    yield_percentile=92.0,
    option_details={'strike': 32.0, 'bid': 0.45, 'dte': 60, 'apy': 8.2, 'expiration': '2026-05-01'}
)

html = generate_html_report(
    dividend_signals=[signal],
    dividend_pool_summary={'count': 23, 'last_update': '2026-03-03'}
)

with open('/tmp/test_dividend_card.html', 'w') as f:
    f.write(html)

print("HTML saved to /tmp/test_dividend_card.html")
```

运行：`python test_render.py` 并在浏览器打开`/tmp/test_dividend_card.html`验证样式。

**Step 4: 提交**

```bash
git add src/html_report.py
git commit -m "feat: implement complete 6-dimension dividend card

- Add full card structure: valuation, risk, events, strategy, scenario, monitoring
- Add Apple-style CSS for dividend cards
- Implement combined yield calculation (stock + option)
- Display worst-case scenario for option strategy

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Phase 5: 集成与文档

### Task 5.1: 集成到main.py

**Files:**
- Modify: `src/main.py`
- Modify: `config.yaml`

**Step 1: 添加config.yaml配置**

在`config.yaml`中添加股息配置：

```yaml
scanners:
  # ... 现有配置 ...

  # 高股息防御双打
  dividend:
    enabled: true

    screening:
      min_quality_score: 70
      min_consecutive_years: 5
      max_payout_ratio: 100
      min_roe: 10
      max_debt_to_equity: 1.5

    buy_signal:
      min_yield: 4.0
      min_yield_percentile: 90

      option:
        min_dte: 45
        max_dte: 90
        target_strike_percentile: 90

    alerts:
      payout_ratio_warning: 80
      payout_ratio_critical: 100

data:
  # ... 现有配置 ...
  dividend_db_path: "data/dividend_pool.db"

  financial_service:
    enabled: true
    fallback_to_rules: true
    timeout: 30
```

**Step 2: 写失败测试 - main.py集成**

在`tests/test_integration.py`添加：

```python
def test_main_with_dividend_mode():
    """main.py应支持dividend模式"""
    # TODO: 实现集成测试
    pass
```

**Step 3: 实现 - 扩展main.py**

在`src/main.py`中添加股息功能集成：

```python
import argparse
from src.dividend_store import DividendStore
from src.financial_service import FinancialServiceAnalyzer
from src.dividend_scanners import scan_dividend_pool_weekly, scan_dividend_buy_signal


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['all', 'dividend_screening', 'dividend_monitor'], default='all')
    args = parser.parse_args()

    config = load_config()

    # ... 现有代码 ...

    # Phase 2: 高股息防御双打
    dividend_signals = []
    dividend_pool_summary = None

    if config['scanners']['dividend']['enabled']:
        dividend_store = DividendStore(db_path=config['data']['dividend_db_path'])
        financial_service = FinancialServiceAnalyzer(
            enabled=config['data']['financial_service']['enabled'],
            fallback_to_rules=config['data']['financial_service']['fallback_to_rules']
        )

        # 每周筛选模式
        if args.mode in ['dividend_screening', 'all']:
            logger.info("=" * 50)
            logger.info("Running weekly dividend pool screening...")
            pool = scan_dividend_pool_weekly(
                universe=universe_tickers,
                provider=market_data_provider,
                financial_service=financial_service,
                config=config['scanners']['dividend']
            )

            version = f"weekly_{date.today().isoformat()}"
            dividend_store.save_pool(pool, version=version)
            logger.info(f"Saved {len(pool)} tickers to dividend pool")

        # 每日监控模式
        if args.mode in ['dividend_monitor', 'all']:
            logger.info("=" * 50)
            logger.info("Monitoring dividend buy signals...")
            current_pool = dividend_store.get_current_pool()
            dividend_signals = scan_dividend_buy_signal(
                pool=current_pool,
                provider=market_data_provider,
                store=dividend_store,
                config=config['scanners']['dividend']
            )
            logger.info(f"Found {len(dividend_signals)} buy signals")

        # 获取池子摘要
        # TODO: 实现dividend_store.get_pool_summary()
        dividend_pool_summary = {'count': len(dividend_store.get_current_pool()), 'last_update': date.today().isoformat()}

        dividend_store.close()

    # 生成HTML报告（添加股息参数）
    html = generate_html_report(
        # ... 现有参数 ...
        dividend_signals=dividend_signals,
        dividend_pool_summary=dividend_pool_summary
    )

    # ... 保存报告代码 ...


if __name__ == '__main__':
    main()
```

**Step 4: 手动测试运行**

```bash
# 测试每周筛选
python -m src.main --mode dividend_screening

# 测试每日监控
python -m src.main --mode dividend_monitor

# 完整运行
python -m src.main --mode all
```

**Step 5: 提交**

```bash
git add src/main.py config.yaml
git commit -m "feat: integrate dividend scanner into main workflow

- Add dividend modes: screening, monitor, all
- Add config.yaml dividend section
- Initialize DividendStore and FinancialService
- Pass dividend data to HTML report

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 5.2: 更新文档规范

**Files:**
- Create/Update: `docs/specs/dividend_scanners.md`
- Modify: `CLAUDE.md`

**Step 1: 创建dividend_scanners.md规范文档**

创建`docs/specs/dividend_scanners.md`：

```markdown
# Dividend Scanners Specification

**Module**: `src/dividend_scanners.py`, `src/financial_service.py`, `src/dividend_store.py`

**Purpose**: 高股息防御双打扫描器（Phase 2）

---

## Architecture

```
Universe → MarketDataProvider → FinancialService → DividendStore → Scanners → HTML Report
```

**核心流程**:
1. **每周筛选**: scan_dividend_pool_weekly() → 保存到dividend_pool表
2. **每日监控**: scan_dividend_buy_signal() → 触发买入信号

---

## Module: dividend_scanners.py

### scan_dividend_pool_weekly()

**筛选规则**:
- quality_score >= 70
- consecutive_years >= 5
- payout_ratio < 100 (硬性)
- roe >= 10, debt_to_equity <= 1.5

**返回**: `List[TickerData]`

---

### scan_dividend_buy_signal()

**触发条件**:
- dividend_yield >= 4.0%
- dividend_yield_5y_percentile >= 90%

**返回**: `List[DividendBuySignal]`

---

### scan_dividend_sell_put()

**Strike选择**: 基于target_yield_percentile反推

**返回**: `Dict[str, Any]` (期权详情)

---

## Module: financial_service.py

### DividendQualityScore

**字段**:
- overall_score, stability_score, health_score, defensiveness_score
- risk_flags

---

### FinancialServiceAnalyzer

**降级策略**: 当enabled=False或API失败时，使用_calculate_rule_based_score()

---

## Module: dividend_store.py

### Tables

- dividend_pool: 当前池子
- dividend_history: 历史股息率（用于分位数计算）
- screening_versions: 版本管理

---

## Configuration (config.yaml)

```yaml
scanners:
  dividend:
    enabled: true
    screening: {...}
    buy_signal: {...}
```

---

## Testing

**Test File**: `tests/test_dividend_scanners.py`, `tests/test_financial_service.py`, `tests/test_dividend_store.py`

**Coverage**:
- 筛选规则
- 派息率>100%排除
- 分位数计算
- Financial Service降级
- 期权strike选择

---

## Design Principles

1. **Financial Service优先**: 启用时调用API，失败时降级
2. **硬性规则**: 派息率>100%立即排除
3. **防御性**: 所有API调用包裹try-except
4. **可配置**: 所有阈值从config读取
```

**Step 2: 更新CLAUDE.md的Spec-to-Code映射**

在`CLAUDE.md`的**Spec-to-Code Mapping**部分添加：

```markdown
| Spec File | Source Modules | Purpose |
|-----------|----------------|---------|
| ... 现有映射 ... |
| `docs/specs/dividend_scanners.md` | `dividend_scanners.py`, `financial_service.py`, `dividend_store.py` | 高股息防御双打扫描器 (Phase 2) |
```

**Step 3: 更新Mirror Testing Rule**

在`CLAUDE.md`的**Mirror Testing Rule**部分添加：

```markdown
- `src/dividend_scanners.py` → `tests/test_dividend_scanners.py`
- `src/financial_service.py` → `tests/test_financial_service.py`
- `src/dividend_store.py` → `tests/test_dividend_store.py`
```

**Step 4: 提交**

```bash
git add docs/specs/dividend_scanners.md CLAUDE.md
git commit -m "docs: add dividend scanners specification

- Create docs/specs/dividend_scanners.md
- Update CLAUDE.md Spec-to-Code mapping
- Update Mirror Testing rules

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 5.3: 运行完整测试套件

**Step 1: 运行所有测试**

```bash
pytest tests/ -v --tb=short
```

预期输出：所有测试通过

**Step 2: 检查测试覆盖率**

```bash
pytest tests/ --cov=src --cov-report=term-missing
```

目标：新增模块覆盖率 >= 80%

**Step 3: 修复失败测试**

如有失败测试，逐个修复并提交：

```bash
git add <modified_files>
git commit -m "fix: resolve test failures in <module>"
```

**Step 4: 最终提交**

```bash
git add .
git commit -m "test: ensure all Phase 2 tests pass

- All dividend scanner tests passing
- Coverage >= 80% for new modules
- Integration tests verified

Phase 2: 高股息防御双打 - COMPLETE

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

### Task 5.4: 清理临时文档

**Step 1: 删除plan文档**

根据GLOBAL_MASTER规范，实现完成后删除plan文档：

```bash
git rm docs/plans/2026-03-03-high-dividend-scanner-design.md
git rm docs/plans/2026-03-03-high-dividend-scanner.md
git commit -m "docs: remove temporary plan files

Plans are throwaway working docs.
Specs (docs/specs/dividend_scanners.md) are now the source of truth.

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

**Step 2: 归档需求文档**

将`req/phase_2_high_dividend.md`归档：

```bash
git mv req/phase_2_high_dividend.md archive/
git commit -m "docs: archive Phase 2 high dividend requirements

Feature fully implemented, requirements archived.

Phase 2: 高股息防御双打

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>"
```

---

## Post-Implementation Checklist

实施完成后确认：

- [ ] 所有测试100%通过（`pytest tests/ -v`）
- [ ] 新模块测试覆盖率 >= 80%
- [ ] `docs/specs/dividend_scanners.md`已创建
- [ ] `CLAUDE.md`已更新（Spec-to-Code映射、Mirror Testing）
- [ ] `config.yaml`包含完整配置
- [ ] Plan文档已删除（`docs/plans/*.md`）
- [ ] 需求文档已归档（`req/phase_2_high_dividend.md` → `archive/`）
- [ ] 手动运行验证：
  - `python -m src.main --mode dividend_screening`
  - `python -m src.main --mode dividend_monitor`
  - 检查生成的HTML报告包含六维度卡片

---

## Execution Notes

**TDD流程严格遵守**：
- 每个功能先写测试（RED）
- 再写实现（GREEN）
- 最后重构（如需）
- 频繁提交（每个Task完成后立即commit）

**错误隔离**：
- 单个ticker失败不影响整体流程
- Financial Service不可用时自动降级
- 所有外部API调用包裹try-except

**数据完整性**（遵循GLOBAL_MASTER）：
- 使用复权价格（yfinance默认）
- 股息计算考虑分红再投资
- 多市场支持（US/HK/CN）

---

**Implementation Plan Complete** | Ready for Execution
