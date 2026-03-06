import pytest
from fastapi.testclient import TestClient


def test_health_check():
    from agent.main import app
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
