"""FastAPI app: REST API for the dashboard + serves the web UI."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.data.market_hours import is_extended_hours, market_session
from app.engine.orchestrator import Orchestrator

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

orch = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orch.start()
    yield
    await orch.stop()


app = FastAPI(title="VWAP Event Trading Copilot", lifespan=lifespan)


# --- signals ----------------------------------------------------------- #

@app.get("/api/signals")
def signals():
    return {
        "pending": [s.model_dump() for s in orch.store.pending_signals()],
        "recent": [s.model_dump() for s in orch.store.recent_signals()],
    }


@app.post("/api/signals/{signal_id}/approve")
async def approve(signal_id: str):
    return await orch.approve_signal(signal_id)


@app.post("/api/signals/{signal_id}/ignore")
def ignore(signal_id: str):
    return orch.ignore_signal(signal_id)


# --- trades -------------------------------------------------------------- #

@app.get("/api/trades")
def trades():
    open_trades = orch.store.open_trades()
    return {
        "open": [
            {**t.model_dump(), "unrealized_pnl": round(t.unrealized_pnl, 2)}
            for t in open_trades
        ],
        "closed": [t.model_dump() for t in orch.store.closed_trades()][-50:],
    }


@app.post("/api/trades/{trade_id}/close")
async def close_trade(trade_id: str):
    return await orch.close_trade(trade_id)


# --- P&L, settings, status ------------------------------------------------ #

@app.get("/api/pnl")
def pnl():
    return orch.store.pnl_summary()


@app.get("/api/settings")
def get_settings():
    return orch.rules.as_dict()


@app.put("/api/settings")
async def put_settings(patch: dict):
    orch.rules.update(patch)
    return orch.rules.as_dict()


@app.post("/api/automation/toggle")
def toggle_automation():
    orch.rules.auto_trade_enabled = not orch.rules.auto_trade_enabled
    return {"ok": True, "auto_trade_enabled": orch.rules.auto_trade_enabled}


@app.post("/api/automation/disable")
def disable_automation():
    orch.rules.auto_trade_enabled = False
    return {"ok": True, "auto_trade_enabled": False}


@app.get("/api/status")
def status():
    can, reason = orch.risk.can_trade()
    return {
        "broker_connected": orch.connected,
        "broker": settings.broker,
        "market_session": market_session(),
        "extended_hours": is_extended_hours(),
        "watching": sorted(orch.detectors.keys()),
        "candidates": {s: c.model_dump() for s, c in orch.candidates.items()},
        "auto_trade_enabled": orch.rules.auto_trade_enabled,
        "trades_today": orch.risk.trades_today,
        "realized_pnl_today": round(orch.risk.realized_pnl_today, 2),
        "can_trade": can,
        "blocked_reason": reason,
    }


# --- chart ------------------------------------------------------------------ #

@app.get("/api/chart/{symbol}")
def chart(symbol: str):
    payload = orch.chart(symbol)
    if payload is None:
        return JSONResponse({"error": f"not watching {symbol}"}, status_code=404)
    return payload


# --- web UI -------------------------------------------------------------- #

@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
