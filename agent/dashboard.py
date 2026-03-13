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


STRATEGY_REGISTRY = [
    {
        "slug": "dividend",
        "name": "高股息价值股",
        "description": "筛选连续派息 5 年以上、股息率处于历史高位的价值型标的",
        "signal_type": "dividend",
        "url": "/strategy/dividend",
    },
]


def _get_default_universe() -> list:
    """Fetch full universe rows from the scan CSV. Returns [] on failure.

    Each row: {ticker, name, group, role, floor, strike, note}
    """
    try:
        import io
        import requests as _req
        import pandas as pd
        url = "https://docs.google.com/spreadsheets/d/1O_txXYVAcDp0syjexAcowRRdrNX4gyrFzrGqNgh9dfw/export?format=csv"
        resp = _req.get(url, timeout=15, verify=False)
        resp.encoding = "utf-8"
        df = pd.read_csv(io.StringIO(resp.text))
        df["代码"] = df["代码"].astype(str).str.strip()
        df = df[df["代码"].notna() & (df["代码"] != "") & (df["代码"] != "nan")]
        rows = []
        for _, r in df.iterrows():
            rows.append({
                "ticker": r["代码"],
                "name": r.get("标的", ""),
                "group": r.get("梯队", ""),
                "role": r.get("角色", ""),
                "floor": str(r.get("Floor (大底)", "") or "").strip(),
                "strike": str(r.get("Strike (黄金位)", "") or "").strip(),
                "note": str(r.get("V1.9 战术特征", "") or "").strip(),
            })
        return rows
    except Exception:
        return []


@router.get("/watchlist")
async def watchlist_page(request: Request, db: AgentDB = Depends(get_db)):
    user = db.get_user("ALICE")

    # Parse enriched watchlist (list of dicts)
    items: list = []
    if user:
        items = db._parse_watchlist(user)

    # Fallback to default universe when watchlist is empty
    is_default = False
    default_rows = []
    if not items:
        default_rows = _get_default_universe()
        is_default = bool(default_rows)

    # Build strategy tag index: ticker -> list of strategy names
    strategy_tag_index: dict = {}
    for strategy in STRATEGY_REGISTRY:
        pool = db.get_strategy_pool(strategy["signal_type"])
        for pool_item in pool:
            t = pool_item["ticker"]
            strategy_tag_index.setdefault(t, []).append(strategy["name"])

    ticker_rows = [
        {**item, "tags": strategy_tag_index.get(item["ticker"], [])}
        for item in items
    ]

    strategy_cards = []
    for strategy in STRATEGY_REGISTRY:
        pool = db.get_strategy_pool(strategy["signal_type"])
        strategy_cards.append({**strategy, "count": len(pool)})

    return templates.TemplateResponse(request, "watchlist.html", {
        "active_page": "watchlist",
        "ticker_rows": ticker_rows,
        "strategy_cards": strategy_cards,
        "is_default": is_default,
        "default_rows": default_rows,
    })


@router.get("/strategy/dividend")
async def strategy_dividend_page(request: Request, db: AgentDB = Depends(get_db)):
    pool = db.get_strategy_pool("dividend")
    return templates.TemplateResponse(request, "strategy_dividend.html", {
        "active_page": "watchlist",
        "pool": pool,
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


class WatchlistMutateRequest(BaseModel):
    ticker: str


@router.post("/api/watchlist/add")
async def watchlist_add(req: WatchlistMutateRequest, db: AgentDB = Depends(get_db)):
    ticker = req.ticker.upper().strip()
    # Look up metadata from the default universe CSV
    universe = _get_default_universe()
    meta = next((r for r in universe if r["ticker"] == ticker), None)
    metadata = None
    if meta:
        metadata = {k: v for k, v in meta.items() if k != "ticker"}
    items = db.add_to_watchlist("ALICE", ticker, metadata=metadata)
    return JSONResponse({"items": items})


@router.post("/api/watchlist/remove")
async def watchlist_remove(req: WatchlistMutateRequest, db: AgentDB = Depends(get_db)):
    items = db.remove_from_watchlist("ALICE", req.ticker)
    return JSONResponse({"items": items})


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
