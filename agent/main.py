# agent/main.py
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Any

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import config
from agent.db import AgentDB
from agent.dingtalk import verify_signature, parse_incoming, send_reply
from agent.claude_agent import ClaudeAgent
from agent.dashboard import router as dashboard_router
from agent.deps import get_db as _deps_get_db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level singletons (initialized on startup)
claude_agent: ClaudeAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global claude_agent
    db_path = config.get("AGENT_DB_PATH", "data/agent.db")
    os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
    _db = AgentDB(db_path)
    try:
        llm_cfg = config.get_llm_config()
    except ValueError as e:
        logger.warning(f"LLM not configured: {e} — AI responses will fail")
        llm_cfg = {"provider": "anthropic", "api_key": "", "model": None}
    claude_agent = ClaudeAgent(
        db=_db,
        llm_provider=llm_cfg["provider"],
        llm_api_key=llm_cfg["api_key"],
        llm_model=llm_cfg["model"],
    )
    if not config.get("DINGTALK_APP_SECRET"):
        logger.warning("DINGTALK_APP_SECRET not set — /dingtalk/webhook is unauthenticated")
    if not config.get("SCAN_API_KEY"):
        logger.warning("SCAN_API_KEY not set — /api/scan_results is unauthenticated")
    logger.info("Agent started")
    yield
    _db.close()


app = FastAPI(title="交易领航员 Agent", lifespan=lifespan)
app.include_router(dashboard_router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/dingtalk/webhook")
async def dingtalk_webhook(request: Request):
    # Signature verification
    timestamp = request.headers.get("timestamp", "")
    sign = request.headers.get("sign", "")
    app_secret = config.get("DINGTALK_APP_SECRET")

    if app_secret and not verify_signature(timestamp, sign, app_secret):
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()
    msg = parse_incoming(payload)

    if not msg["text"]:
        return JSONResponse({"ok": True})

    try:
        reply = claude_agent.process(msg["user_id"], msg["text"])
        send_reply(msg["session_webhook"], reply)
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        send_reply(msg["session_webhook"], "处理出错，请稍后重试。")

    return JSONResponse({"ok": True})


class ScanResultsPayload(BaseModel):
    scan_date: str
    results: List[Any]


def _get_db() -> AgentDB:
    """Return the shared DB singleton from deps (supports test reloads via AGENT_DB_PATH)."""
    return _deps_get_db()


@app.get("/api/scan_results")
async def get_scan_results():
    db = _get_db()
    row = db.conn.execute(
        "SELECT scan_date, results_json FROM scan_results ORDER BY scan_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"scan_date": None, "results": []}
    return {"scan_date": row["scan_date"], "results": json.loads(row["results_json"])}


@app.post("/api/scan_results")
async def push_scan_results(payload: ScanResultsPayload, request: Request):
    api_key = config.get("SCAN_API_KEY")
    if api_key and request.headers.get("X-API-Key") != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    db = _get_db()
    db.save_scan_results(payload.scan_date, payload.results)
    db.save_signals(payload.scan_date, payload.results)
    logger.info(f"Scan results saved: {payload.scan_date}, {len(payload.results)} signals")
    return {"saved": len(payload.results), "scan_date": payload.scan_date}
