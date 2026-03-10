import json
import pytest
from src.risk_store import RiskStore
from src.portfolio_risk import RiskReport, RiskAlert


def _make_report(account_id="alice", report_date="2026-03-10"):
    return RiskReport(
        account_id=account_id,
        report_date=report_date,
        net_liquidation=120000,
        total_pnl=3200,
        cushion=0.35,
        alerts=[RiskAlert(dimension=4, level="yellow", ticker="ACCOUNT", detail="cushion 35%")],
        summary_stats={"stress_test": {"drop_10pct": -5000}},
    )


@pytest.fixture
def store(tmp_path):
    return RiskStore(str(tmp_path / "test.db"))


def test_save_and_retrieve_latest(store):
    report = _make_report()
    store.save_report(report, "<html>test</html>")
    result = store.get_latest_report("alice")
    assert result is not None
    assert result["account_id"] == "alice"
    assert result["report_date"] == "2026-03-10"
    assert result["net_liquidation"] == 120000
    assert "<html>" in result["report_html"]
    summary = json.loads(result["summary_json"])
    assert "stress_test" in summary


def test_upsert_replaces_same_date(store):
    report = _make_report()
    store.save_report(report, "<html>v1</html>")
    store.save_report(report, "<html>v2</html>")
    result = store.get_latest_report("alice")
    assert "v2" in result["report_html"]
    # Only one row for same date
    history = store.get_history("alice", days=7)
    assert len(history) == 1


def test_get_history_returns_trend(store):
    for date_str in ["2026-03-08", "2026-03-09", "2026-03-10"]:
        report = _make_report(report_date=date_str)
        store.save_report(report, f"<html>{date_str}</html>")
    history = store.get_history("alice", days=7)
    assert len(history) == 3
    dates = [row["report_date"] for row in history]
    assert "2026-03-08" in dates


def test_get_latest_returns_none_when_empty(store):
    assert store.get_latest_report("nobody") is None
