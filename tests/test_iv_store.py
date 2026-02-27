# tests/test_iv_store.py
import os
import tempfile
import pytest
from datetime import date, timedelta
from src.iv_store import IVStore


@pytest.fixture
def store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    s = IVStore(path)
    yield s
    s.close()
    os.unlink(path)


class TestIVStore:
    def test_store_and_retrieve(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        store.save_iv("AAPL", date(2026, 1, 2), 0.30)
        history = store.get_iv_history("AAPL", days=365)
        assert len(history) == 2

    def test_iv_rank_insufficient_data(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        rank = store.compute_iv_rank("AAPL", current_iv=0.25)
        assert rank is None  # need at least 20 data points

    def test_iv_rank_calculation(self, store):
        # Store 30 days of IV data ranging from 0.20 to 0.50
        for i in range(30):
            d = date(2026, 1, 1 + i) if i < 28 else date(2026, 2, i - 27)
            iv = 0.20 + (i * 0.01)
            store.save_iv("AAPL", d, iv)

        # Current IV = 0.35, min=0.20, max=0.49
        # IV Rank = (0.35 - 0.20) / (0.49 - 0.20) * 100 = 51.7...
        rank = store.compute_iv_rank("AAPL", current_iv=0.35)
        assert rank is not None
        assert 50 < rank < 55

    def test_duplicate_date_updates(self, store):
        store.save_iv("AAPL", date(2026, 1, 1), 0.25)
        store.save_iv("AAPL", date(2026, 1, 1), 0.30)  # update
        history = store.get_iv_history("AAPL", days=365)
        assert len(history) == 1
        assert history[0][1] == 0.30


class TestGetIVNDaysAgo:
    def test_exact_match_5_days_ago(self, store):
        """精确匹配 5 天前的数据"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=5), 0.25)
        store.save_iv("AAPL", today - timedelta(days=3), 0.28)
        store.save_iv("AAPL", today, 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.25

    def test_window_tolerance(self, store):
        """窗口容差: 7天前的数据仍被返回 (5-8天窗口)"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=7), 0.22)
        store.save_iv("AAPL", today, 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result == 0.22

    def test_no_data_returns_none(self, store):
        """无数据时返回 None"""
        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=date(2026, 2, 27))
        assert result is None

    def test_data_too_recent_returns_none(self, store):
        """数据太新 (仅2天前), 不在窗口内"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today - timedelta(days=2), 0.30)

        result = store.get_iv_n_days_ago("AAPL", n=5, reference_date=today)
        assert result is None


class TestDataSufficiency:
    def test_sufficient_for_both(self, store):
        """数据充足: 同时满足 IVP (30天) 和 Momentum (5天)"""
        today = date(2026, 2, 27)
        for i in range(40):
            store.save_iv("AAPL", today - timedelta(days=i), 0.25)

        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 40
        assert result["sufficient_for_ivp"] is True
        assert result["sufficient_for_momentum"] is True

    def test_insufficient_for_ivp(self, store):
        """数据不足: 仅满足 Momentum"""
        today = date(2026, 2, 27)
        for i in range(10):
            store.save_iv("AAPL", today - timedelta(days=i), 0.25)

        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 10
        assert result["sufficient_for_ivp"] is False
        assert result["sufficient_for_momentum"] is True

    def test_no_data(self, store):
        """无数据时返回全 False"""
        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 0
        assert result["sufficient_for_ivp"] is False
        assert result["sufficient_for_momentum"] is False

    def test_single_day_data(self, store):
        """边界情况: 仅1天数据"""
        today = date(2026, 2, 27)
        store.save_iv("AAPL", today, 0.25)

        result = store.get_data_sufficiency("AAPL")
        assert result["total_days"] == 1
        assert result["sufficient_for_ivp"] is False
        assert result["sufficient_for_momentum"] is False
