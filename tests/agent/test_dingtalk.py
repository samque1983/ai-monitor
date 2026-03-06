import pytest
import hmac, hashlib, base64, time
from agent.dingtalk import verify_signature, parse_incoming, format_text_reply

APP_SECRET = "test_secret_12345"

def _make_sign(secret: str, timestamp: str) -> str:
    msg = f"{timestamp}\n{secret}"
    mac = hmac.new(secret.encode(), msg.encode(), digestmod=hashlib.sha256).digest()
    return base64.b64encode(mac).decode()

def test_verify_signature_valid():
    ts = str(int(time.time() * 1000))
    sign = _make_sign(APP_SECRET, ts)
    assert verify_signature(ts, sign, APP_SECRET) is True

def test_verify_signature_invalid():
    ts = str(int(time.time() * 1000))
    assert verify_signature(ts, "bad_sign", APP_SECRET) is False

def test_verify_signature_expired():
    old_ts = str(int((time.time() - 3600) * 1000))  # 1 hour ago
    sign = _make_sign(APP_SECRET, old_ts)
    assert verify_signature(old_ts, sign, APP_SECRET) is False

def test_parse_incoming_text():
    payload = {
        "msgtype": "text",
        "text": {"content": "今天有什么信号 @bot"},
        "senderId": "user_123",
        "senderNick": "张三",
        "sessionWebhook": "https://oapi.dingtalk.com/robot/sendBySession?session=xxx",
        "sessionWebhookExpiredTime": int(time.time() * 1000) + 60000,
        "conversationId": "cid_123",
    }
    msg = parse_incoming(payload)
    assert msg["user_id"] == "user_123"
    assert msg["text"] == "今天有什么信号"  # @bot stripped
    assert msg["session_webhook"] == payload["sessionWebhook"]

def test_format_text_reply():
    payload = format_text_reply("今天有 2 个信号")
    assert payload["msgtype"] == "markdown"
    assert "今天有 2 个信号" in payload["markdown"]["text"]
