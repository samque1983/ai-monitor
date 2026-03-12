import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from agent.main import app
    return TestClient(app)


@pytest.fixture
def client_with_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENT_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    from agent.main import app
    from agent.deps import get_db
    db = get_db()
    db.save_risk_report("ALICE", "2026-03-12", "<html>latest</html>")
    db.save_risk_report("ALICE", "2026-03-11", "<html>older</html>")
    return TestClient(app)


def test_get_risk_report_no_data(client):
    resp = client.get("/api/risk-report/latest?account=ALICE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"] is None
    assert data["dates"] == []


def test_get_risk_report_latest(client_with_reports):
    resp = client_with_reports.get("/api/risk-report/latest?account=ALICE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["report_date"] == "2026-03-12"
    assert "<html>latest</html>" in data["report"]["html_content"]
    assert data["dates"] == ["2026-03-12", "2026-03-11"]


def test_get_risk_report_by_date(client_with_reports):
    resp = client_with_reports.get("/api/risk-report/latest?account=ALICE&date=2026-03-11")
    assert resp.status_code == 200
    data = resp.json()
    assert data["report"]["report_date"] == "2026-03-11"
    assert "<html>older</html>" in data["report"]["html_content"]
