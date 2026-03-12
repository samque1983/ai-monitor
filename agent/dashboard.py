# agent/dashboard.py
import json
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent.db import AgentDB
from agent.deps import get_db

router = APIRouter()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


@router.get("/dashboard")
async def dashboard(request: Request, db: AgentDB = Depends(get_db)):
    signals_24h = db.get_signals(time_range="24h")
    return templates.TemplateResponse(request, "dashboard.html", {
        "active_page": "dashboard",
        "signal_count": len(signals_24h),
    })


@router.get("/risk-report")
async def risk_report_page(request: Request):
    return templates.TemplateResponse(request, "risk_report.html", {
        "active_page": "risk",
    })


@router.get("/chat")
async def chat_page(request: Request):
    return templates.TemplateResponse(request, "chat.html", {
        "active_page": "chat",
    })


@router.get("/watchlist")
async def watchlist_page(request: Request, db: AgentDB = Depends(get_db)):
    user = db.get_user("ALICE")
    tickers = json.loads(user["watchlist_json"]) if user and user.get("watchlist_json") else []
    return templates.TemplateResponse(request, "watchlist.html", {
        "active_page": "watchlist",
        "tickers": tickers,
    })


@router.get("/api/risk-report/latest")
async def get_risk_report(
    account: str = "ALICE",
    date: Optional[str] = None,
    db: AgentDB = Depends(get_db),
):
    dates = db.get_risk_report_dates(account)
    if date:
        row = db.get_risk_report_by_date(account, date)
    else:
        row = db.get_latest_risk_report(account)
    return JSONResponse({
        "account": account,
        "report": dict(row) if row else None,
        "dates": dates,
    })


@router.get("/api/signals")
async def get_signals(
    time_range: Literal["24h", "7d", "30d"] = "24h",
    category: str = "all",
    db: AgentDB = Depends(get_db),
):
    cat_filter = None if category == "all" else category
    signals = db.get_signals(time_range=time_range, category=cat_filter)
    opp_count = sum(1 for s in signals if s["category"] == "opportunity")
    risk_count = sum(1 for s in signals if s["category"] == "risk")
    return JSONResponse({
        "range": time_range,
        "count": len(signals),
        "opportunity_count": opp_count,
        "risk_count": risk_count,
        "signals": signals,
    })


class ChatRequest(BaseModel):
    message: str
    user_id: str = "web"


@router.post("/api/chat")
async def chat_api(req: ChatRequest):
    """Web chat endpoint — calls ClaudeAgent.process()."""
    from agent.main import claude_agent
    if claude_agent is None:
        return JSONResponse({"reply": "AI 领航员尚未初始化，请稍候。"})
    try:
        reply = claude_agent.process(req.user_id, req.message)
    except Exception as e:
        reply = f"处理失败：{e}"
    return JSONResponse({"reply": reply})
