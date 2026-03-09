# agent/dashboard.py
import os
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, JSONResponse

from agent.db import AgentDB
from agent.deps import get_db

router = APIRouter()

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@router.get("/dashboard", response_class=FileResponse)
async def dashboard():
    return FileResponse(os.path.join(_STATIC_DIR, "dashboard.html"))


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
