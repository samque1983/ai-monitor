import hmac
import hashlib
import base64
import time
import re
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

SIGN_TOLERANCE_MS = 60 * 60 * 1000  # 1 hour


def verify_signature(timestamp: str, sign: str, app_secret: str) -> bool:
    """Verify DingTalk request signature."""
    try:
        ts_ms = int(timestamp)
        now_ms = int(time.time() * 1000)
        if abs(now_ms - ts_ms) >= SIGN_TOLERANCE_MS:
            return False
        msg = f"{timestamp}\n{app_secret}"
        mac = hmac.new(
            app_secret.encode("utf-8"),
            msg.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).digest()
        expected = base64.b64encode(mac).decode()
        return hmac.compare_digest(expected, sign)
    except Exception:
        return False


def parse_incoming(payload: Dict) -> Dict:
    """Parse DingTalk incoming message into normalized dict."""
    raw_text = ""
    if payload.get("msgtype") == "text":
        raw_text = payload.get("text", {}).get("content", "")
    # Strip @mentions (e.g. "@bot" or "@所有人")
    text = re.sub(r"@\S+", "", raw_text).strip()
    return {
        "user_id": payload.get("senderId", ""),
        "nick": payload.get("senderNick", ""),
        "text": text,
        "session_webhook": payload.get("sessionWebhook", ""),
        "conversation_id": payload.get("conversationId", ""),
    }


def format_text_reply(text: str) -> Dict:
    """Format a reply payload for DingTalk markdown message."""
    return {
        "msgtype": "markdown",
        "markdown": {
            "title": "交易领航员",
            "text": text,
        },
    }


def send_reply(session_webhook: str, text: str) -> bool:
    """Send reply to a DingTalk session webhook."""
    if not session_webhook:
        return False
    try:
        payload = format_text_reply(text)
        resp = requests.post(
            session_webhook,
            json=payload,
            verify=False,  # corporate proxy workaround
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"DingTalk reply failed: {e}")
        return False


def push_to_webhook(webhook_url: str, text: str) -> bool:
    """Push proactive message to a DingTalk webhook URL."""
    if not webhook_url:
        return False
    try:
        payload = format_text_reply(text)
        resp = requests.post(
            webhook_url,
            json=payload,
            verify=False,  # corporate proxy workaround
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        logger.warning(f"DingTalk push failed: {e}")
        return False
