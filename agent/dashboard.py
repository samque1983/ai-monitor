# agent/dashboard.py
import os
from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from agent.db import AgentDB

router = APIRouter()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _get_db() -> AgentDB:
    from agent import main as _main
    return _main._get_db()


@router.get("/dashboard", response_class=FileResponse)
async def dashboard():
    return FileResponse(os.path.join(_STATIC_DIR, "dashboard.html"))


@router.get("/api/signals")
async def get_signals(range: str = "24h", category: str = "all"):
    if range not in ("24h", "7d", "30d"):
        range = "24h"
    cat_filter = None if category == "all" else category
    signals = _get_db().get_signals(time_range=range, category=cat_filter)
    opp_count = sum(1 for s in signals if s["category"] == "opportunity")
    risk_count = sum(1 for s in signals if s["category"] == "risk")
    return JSONResponse({
        "range": range,
        "count": len(signals),
        "opportunity_count": opp_count,
        "risk_count": risk_count,
        "signals": signals,
    })
