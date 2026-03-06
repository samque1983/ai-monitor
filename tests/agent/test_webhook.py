import pytest
import json
import hmac, hashlib, base64, time
from fastapi.testclient import TestClient
from unittest.mock import patch

APP_SECRET = "test_secret"


def _make_headers(secret=APP_SECRET):
    ts = str(int(time.time() * 1000))
    msg = f"{ts}\n{secret}"
    mac = hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(mac).decode()
    return {"timestamp": ts, "sign": sign}


def _make_payload(text: str, user_id="user_123"):
    return {
        "msgtype": "text",
        "text": {"content": text},
        "senderId": user_id,
        "senderNick": "张三",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=test",
        "sessionWebhookExpiredTime": int(time.time() * 1000) + 60000,
        "conversationId": "cid_test",
    }


def test_webhook_processes_message(tmp_path):
    import os
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["DINGTALK_APP_SECRET"] = APP_SECRET
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    import importlib
    import agent.main
    importlib.reload(agent.main)
    from agent.main import app
    client = TestClient(app)

    with patch("agent.main.claude_agent") as mock_agent:
        mock_agent.process.return_value = "今天有 1 个信号。"

        with patch("agent.dingtalk.send_reply", return_value=True):
            resp = client.post(
                "/dingtalk/webhook",
                json=_make_payload("今天有什么信号"),
                headers=_make_headers(),
            )
    assert resp.status_code == 200


def test_webhook_rejects_bad_signature(tmp_path):
    import os
    os.environ["AGENT_DB_PATH"] = str(tmp_path / "agent.db")
    os.environ["DINGTALK_APP_SECRET"] = APP_SECRET
    os.environ["ANTHROPIC_API_KEY"] = "sk-test"

    import importlib
    import agent.main
    importlib.reload(agent.main)
    from agent.main import app
    client = TestClient(app)

    resp = client.post(
        "/dingtalk/webhook",
        json=_make_payload("hi"),
        headers={"timestamp": "123", "sign": "badsign"},
    )
    assert resp.status_code == 403
