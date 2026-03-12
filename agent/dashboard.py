# agent/dashboard.py
import os
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from agent.db import AgentDB
from agent.deps import get_db

router = APIRouter()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@router.get("/dashboard", response_class=FileResponse)
async def dashboard():
    return FileResponse(os.path.join(_STATIC_DIR, "dashboard.html"))


@router.get("/risk-report", response_class=FileResponse)
async def risk_report_page():
    return FileResponse(os.path.join(_STATIC_DIR, "risk-report.html"))


@router.get("/api/risk-report/latest")
async def get_risk_report(
    account: str = "ALICE",
    date: Optional[str] = None,
    db: AgentDB = Depends(get_db),
):
    """Return the latest (or date-specific) risk report HTML and available dates."""
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
