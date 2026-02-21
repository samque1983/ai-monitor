# tests/test_iv_store.py
import os
import tempfile
import pytest
from datetime import date
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
