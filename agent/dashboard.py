# agent/dashboard.py
import json
import os
import time
from collections import defaultdict
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from agent.db import AgentDB
from agent.deps import get_db

router = APIRouter()

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ── IP rate limiter: 10 requests / 60s per IP ──────────────────────────────
_rate_store: dict = defaultdict(list)
_RATE_LIMIT = 10
_RATE_WINDOW = 60  # seconds


def _check_rate_limit(request: Request) -> bool:
    """Return True if request is allowed, False if rate limit exceeded."""
    ip = request.headers.get("X-Forwarded-For", request.client.host if request.client else "unknown")
    ip = ip.split(",")[0].strip()
    now = time.time()
    timestamps = _rate_store[ip]
    # Drop entries outside the window
    _rate_store[ip] = [t for t in timestamps if now - t < _RATE_WINDOW]
    if len(_rate_store[ip]) >= _RATE_LIMIT:
        return False
    _rate_store[ip].append(now)
    return True
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


_universe_cache: list = []
_universe_cache_ts: float = 0.0
_UNIVERSE_TTL = 600  # 10 minutes


def _get_default_universe() -> list:
    """Fetch full universe rows from the scan CSV. Cached for 10 minutes.

    Each row: {ticker, name, group, role, floor, strike, note}
    """
    global _universe_cache, _universe_cache_ts
    if _universe_cache and time.time() - _universe_cache_ts < _UNIVERSE_TTL:
        return _universe_cache
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
        _universe_cache = rows
        _universe_cache_ts = time.time()
        return rows
    except Exception:
        return _universe_cache  # return stale cache on failure rather than []


def _build_tag_index(db: AgentDB) -> dict:
    """Return {ticker: [strategy_name, ...]} from latest scan results."""
    index: dict = {}
    for strategy in STRATEGY_REGISTRY:
        for item in db.get_strategy_pool(strategy["signal_type"]):
            index.setdefault(item["ticker"], []).append(strategy["name"])
    return index


@router.get("/watchlist")
async def watchlist_page(request: Request, db: AgentDB = Depends(get_db)):
    user = db.get_user("ALICE")
    items: list = db._parse_watchlist(user) if user else []

    is_default = False
    default_rows: list = []
    if not items:
        default_rows = _get_default_universe()
        is_default = bool(default_rows)

    tag_index = _build_tag_index(db)
    ticker_rows = [{**item, "tags": tag_index.get(item["ticker"], [])} for item in items]

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
    meta = next((r for r in _get_default_universe() if r["ticker"] == ticker), None)
    metadata = {k: v for k, v in meta.items() if k != "ticker"} if meta else None
    items = db.add_to_watchlist("ALICE", ticker, metadata=metadata)
    tag_index = _build_tag_index(db)
    return JSONResponse({"items": [{**i, "tags": tag_index.get(i["ticker"], [])} for i in items]})


@router.post("/api/watchlist/remove")
async def watchlist_remove(req: WatchlistMutateRequest, db: AgentDB = Depends(get_db)):
    items = db.remove_from_watchlist("ALICE", req.ticker)
    tag_index = _build_tag_index(db)
    return JSONResponse({"items": [{**i, "tags": tag_index.get(i["ticker"], [])} for i in items]})


class ChatRequest(BaseModel):
    message: str
    user_id: str = "web"


def _opportunity_cards(db: AgentDB, limit: int = 5) -> list:
    """Return recent opportunity signals formatted as chat cards."""
    signals = db.get_signals(time_range="7d", category="opportunity")
    cards = []
    for s in signals[:limit]:
        p = s.get("payload", {})
        cards.append({
            "type": "opportunity",
            "ticker": s["ticker"],
            "signal": s["signal_type"],
            "yield": p.get("current_yield"),
            "iv_rank": p.get("iv_rank"),
            "last_price": p.get("last_price"),
        })
    return cards


_CARD_KEYWORDS = {
    "opportunity": ["机会", "高股息", "sell put", "卖put", "leaps", "iv", "波动率", "买入"],
    "risk": ["风险", "持仓", "希腊字母", "delta", "gamma", "报告"],
    "watchlist": ["自选", "加入", "添加", "移除", "删除"],
}


def _infer_cards(message: str, db: AgentDB) -> list:
    msg = message.lower()
    if any(kw in msg for kw in _CARD_KEYWORDS["opportunity"]):
        return _opportunity_cards(db)
    return []


@router.post("/api/chat")
async def chat_api(req: ChatRequest, request: Request, db: AgentDB = Depends(get_db)):
    """Web chat endpoint — calls ClaudeAgent.process()."""
    if not _check_rate_limit(request):
        return JSONResponse(
            {"reply": "请求过于频繁，请稍后再试。", "cards": [], "profile_updated": False},
            status_code=429,
        )
    from agent.main import claude_agent
    if claude_agent is None:
        return JSONResponse({"reply": "AI 领航员尚未初始化，请稍候。", "cards": [], "profile_updated": False})
    try:
        reply, profile_updated = claude_agent.process(req.user_id, req.message)
    except Exception as e:
        reply = f"处理失败：{e}"
        profile_updated = False
    cards = _infer_cards(req.message, db)
    return JSONResponse({"reply": reply, "cards": cards, "profile_updated": profile_updated})


@router.get("/api/profile")
async def get_profile(user_id: str = "ALICE", db: AgentDB = Depends(get_db)):
    profile = db.get_profile(user_id)
    return JSONResponse({"profile": profile})
