import pytest
import tempfile, os
from agent.db import AgentDB


@pytest.fixture
def db(tmp_path):
    return AgentDB(str(tmp_path / "test.db"))


def test_save_and_get_risk_report(db):
    db.save_risk_report("ALICE", "2026-03-12", "<html>report</html>")
    row = db.get_latest_risk_report("ALICE")
    assert row is not None
    assert row["account_id"] == "ALICE"
    assert row["report_date"] == "2026-03-12"
    assert row["html_content"] == "<html>report</html>"


def test_save_risk_report_upserts_same_day(db):
    db.save_risk_report("ALICE", "2026-03-12", "<html>v1</html>")
    db.save_risk_report("ALICE", "2026-03-12", "<html>v2</html>")
    row = db.get_latest_risk_report("ALICE")
    assert row["html_content"] == "<html>v2</html>"


def test_get_risk_report_dates(db):
    db.save_risk_report("ALICE", "2026-03-10", "<html>a</html>")
    db.save_risk_report("ALICE", "2026-03-11", "<html>b</html>")
    db.save_risk_report("ALICE", "2026-03-12", "<html>c</html>")
    dates = db.get_risk_report_dates("ALICE")
    assert dates == ["2026-03-12", "2026-03-11", "2026-03-10"]


def test_get_risk_report_by_date(db):
    db.save_risk_report("ALICE", "2026-03-10", "<html>old</html>")
    db.save_risk_report("ALICE", "2026-03-12", "<html>new</html>")
    row = db.get_risk_report_by_date("ALICE", "2026-03-10")
    assert row["html_content"] == "<html>old</html>"


def test_get_latest_risk_report_returns_none_when_empty(db):
    assert db.get_latest_risk_report("ALICE") is None
