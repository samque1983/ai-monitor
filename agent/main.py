# agent/main.py
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Module-level singletons (initialized on startup)
db: AgentDB = None
claude_agent: ClaudeAgent = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db, claude_agent
    db_path = config.get("AGENT_DB_PATH", "data/agent.db")
    os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
    db = AgentDB(db_path)
    claude_agent = ClaudeAgent(
        db=db,
        api_key=config.get("ANTHROPIC_API_KEY"),
        model=config.get("CLAUDE_MODEL", "claude-opus-4-6"),
    )
    if not config.get("DINGTALK_APP_SECRET"):
        logger.warning("DINGTALK_APP_SECRET not set — /dingtalk/webhook is unauthenticated")
    if not config.get("SCAN_API_KEY"):
        logger.warning("SCAN_API_KEY not set — /api/scan_results is unauthenticated")
    logger.info("Agent started")
    yield
    db.close()


app = FastAPI(title="交易领航员 Agent", lifespan=lifespan)


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
    """Return the module-level db, lazily initializing if lifespan didn't run (e.g. tests)."""
    global db
    if db is None:
        db_path = config.get("AGENT_DB_PATH", "data/agent.db")
        os.makedirs(os.path.dirname(db_path) if "/" in db_path else ".", exist_ok=True)
        db = AgentDB(db_path)
    return db


@app.get("/api/scan_results")
async def get_scan_results():
    db = _get_db()
    row = db.conn.execute(
        "SELECT scan_date, results_json FROM scan_results ORDER BY scan_date DESC LIMIT 1"
    ).fetchone()
    if not row:
        return {"scan_date": None, "results": []}
    import json as _json
    return {"scan_date": row["scan_date"], "results": _json.loads(row["results_json"])}


@app.post("/api/scan_results")
async def push_scan_results(payload: ScanResultsPayload, request: Request):
    api_key = config.get("SCAN_API_KEY")
    if api_key and request.headers.get("X-API-Key") != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    _get_db().save_scan_results(payload.scan_date, payload.results)
    logger.info(f"Scan results saved: {payload.scan_date}, {len(payload.results)} signals")
    return {"saved": len(payload.results), "scan_date": payload.scan_date}
