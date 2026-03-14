# agent/main.py
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import List, Any, Optional

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
        reply, _ = claude_agent.process(msg["user_id"], msg["text"])
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


# ── Positions upload + risk pipeline ──────────────────────────────────────────

class PositionPayload(BaseModel):
    symbol: str
    asset_category: str
    put_call: str = ""
    strike: float = 0.0
    expiry: str = ""
    multiplier: float = 100.0
    position: float
    cost_basis_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    underlying_symbol: str = ""
    currency: str = "USD"


class AccountSummaryPayload(BaseModel):
    net_liquidation: float = 0.0
    gross_position_value: float = 0.0
    init_margin_req: float = 0.0
    maint_margin_req: float = 0.0
    excess_liquidity: float = 0.0
    available_funds: float = 0.0
    cushion: float = 0.0


class PositionsUploadPayload(BaseModel):
    account_key: str
    ib_account_id: str = ""
    positions: List[PositionPayload]
    account_summary: AccountSummaryPayload


@app.post("/api/positions")
async def upload_positions(payload: PositionsUploadPayload, request: Request):
    """Receive positions from local IB Gateway poller, run risk pipeline, store HTML."""
    api_key = config.get("POSITIONS_API_KEY")
    if api_key and request.headers.get("X-API-Key") != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    from src.flex_client import PositionRecord, AccountSummary
    from src.risk_pipeline import run_pipeline

    positions = [
        PositionRecord(
            symbol=p.symbol, asset_category=p.asset_category,
            put_call=p.put_call, strike=p.strike, expiry=p.expiry,
            multiplier=p.multiplier, position=p.position,
            cost_basis_price=p.cost_basis_price, mark_price=p.mark_price,
            unrealized_pnl=p.unrealized_pnl, delta=p.delta, gamma=p.gamma,
            theta=p.theta, vega=p.vega,
            underlying_symbol=p.underlying_symbol, currency=p.currency,
        )
        for p in payload.positions
    ]
    account_summary = AccountSummary(
        net_liquidation=payload.account_summary.net_liquidation,
        gross_position_value=payload.account_summary.gross_position_value,
        init_margin_req=payload.account_summary.init_margin_req,
        maint_margin_req=payload.account_summary.maint_margin_req,
        excess_liquidity=payload.account_summary.excess_liquidity,
        available_funds=payload.account_summary.available_funds,
        cushion=payload.account_summary.cushion,
    )

    try:
        llm_cfg = config.get_llm_config()
    except ValueError:
        llm_cfg = {}

    report, html = run_pipeline(
        positions=positions,
        account_summary=account_summary,
        account_key=payload.account_key,
        account_name=payload.account_key,
        llm_cfg=llm_cfg,
    )

    db = _get_db()
    db.save_risk_report(payload.account_key, report.report_date, html)
    db.save_raw_positions(payload.account_key, payload.model_dump())

    red    = sum(1 for a in report.alerts if a.severity == "red")
    yellow = sum(1 for a in report.alerts if a.severity == "yellow")
    logger.info(f"Risk report saved: {payload.account_key} {report.report_date} "
                f"— {red} red / {yellow} yellow")

    return {
        "status": "ok",
        "report_date": report.report_date,
        "alerts": {"red": red, "yellow": yellow},
    }


@app.post("/api/risk-report/regenerate/{account_key}")
async def regenerate_risk_report(account_key: str, request: Request):
    """Re-run the risk pipeline from the last saved raw positions payload."""
    api_key = config.get("POSITIONS_API_KEY")
    if api_key and request.headers.get("X-API-Key") != api_key:
        raise HTTPException(status_code=403, detail="Invalid API key")

    db = _get_db()
    raw = db.get_raw_positions(account_key)
    if raw is None:
        raise HTTPException(status_code=404, detail=f"No saved positions for {account_key}")

    from src.flex_client import PositionRecord, AccountSummary
    from src.risk_pipeline import run_pipeline

    positions = [
        PositionRecord(
            symbol=p["symbol"], asset_category=p["asset_category"],
            put_call=p.get("put_call"), strike=p.get("strike", 0.0),
            expiry=p.get("expiry", ""), multiplier=p.get("multiplier", 100),
            position=p["position"], cost_basis_price=p.get("cost_basis_price", 0.0),
            mark_price=p.get("mark_price", 0.0), unrealized_pnl=p.get("unrealized_pnl", 0.0),
            delta=p.get("delta"), gamma=p.get("gamma"),
            theta=p.get("theta"), vega=p.get("vega"),
            underlying_symbol=p.get("underlying_symbol", ""), currency=p.get("currency", "USD"),
        )
        for p in raw["positions"]
    ]
    acct = raw["account_summary"]
    account_summary = AccountSummary(
        net_liquidation=acct["net_liquidation"],
        gross_position_value=acct["gross_position_value"],
        init_margin_req=acct["init_margin_req"],
        maint_margin_req=acct["maint_margin_req"],
        excess_liquidity=acct["excess_liquidity"],
        available_funds=acct["available_funds"],
        cushion=acct["cushion"],
    )

    try:
        llm_cfg = config.get_llm_config()
    except ValueError:
        llm_cfg = {}

    report, html = run_pipeline(
        positions=positions,
        account_summary=account_summary,
        account_key=account_key,
        account_name=account_key,
        llm_cfg=llm_cfg,
    )
    db.save_risk_report(account_key, report.report_date, html)

    red    = sum(1 for a in report.alerts if a.severity == "red")
    yellow = sum(1 for a in report.alerts if a.severity == "yellow")
    logger.info(f"Regenerated risk report: {account_key} {report.report_date} "
                f"— {red} red / {yellow} yellow")

    return {
        "status": "ok",
        "report_date": report.report_date,
        "alerts": {"red": red, "yellow": yellow},
    }


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
