"""FastAPI app: REST API for the dashboard + serves the web UI."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.data.market_hours import is_extended_hours, market_session
from app.engine.orchestrator import Orchestrator
from app.api.technicals import router as technicals_router, research
from app.engine.execution_policy import paper_execution_allowed

log = logging.getLogger(__name__)
WEB_DIR = Path(__file__).resolve().parent.parent / "web"

orch = Orchestrator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await orch.start()
    yield
    await orch.stop()
    await research.close()


app = FastAPI(title="VWAP Event Trading Copilot", lifespan=lifespan)
app.include_router(technicals_router)


def require_paper_mode():
    if not paper_execution_allowed():
        raise HTTPException(403, "Research-only mode: orders and automation are disabled.")


# --- signals ----------------------------------------------------------- #

@app.get("/api/signals")
def signals():
    return {
        "pending": [s.model_dump() for s in orch.store.pending_signals()],
        "recent": [s.model_dump() for s in orch.store.recent_signals()],
    }


@app.post("/api/signals/{signal_id}/approve")
async def approve(signal_id: str):
    require_paper_mode()
    return await orch.approve_signal(signal_id)


@app.post("/api/signals/{signal_id}/ignore")
def ignore(signal_id: str):
    return orch.ignore_signal(signal_id)


# --- trades -------------------------------------------------------------- #

@app.get("/api/orders")
async def orders():
    return {"open": await orch.open_orders()}


@app.get("/api/account")
async def account():
    return await orch.account_info()


@app.get("/api/trades")
async def trades():
    open_trades = orch.store.open_trades()
    untracked_positions = []
    inventory_error = None
    if paper_execution_allowed() and orch.connected:
        try:
            positions = await orch.broker.position_inventory()
            tracked = {t.symbol for t in open_trades if t.broker_account_id == orch.broker.account_id}
            untracked_positions = [p for p in positions if p['symbol'] not in tracked]
        except Exception:
            inventory_error = 'Broker position inventory unavailable; account exposure is not confirmed'
    return {
        'untracked_positions': untracked_positions,
        'inventory_error': inventory_error,
        'unattributed': [t.model_dump(exclude={'broker_account_id', 'signal_snapshot', 'orders'})
                         for t in orch.store.trades.values() if t.status.value == 'UNATTRIBUTED'],
        "open": [
            {**t.model_dump(exclude={'broker_account_id', 'signal_snapshot', 'orders'}), "unrealized_pnl": round(t.unrealized_pnl, 2),
             "remaining_quantity": t.remaining_quantity, "realized_r": t.realized_r}
            for t in open_trades
        ],
        "closed": [{**t.model_dump(exclude={'broker_account_id', 'signal_snapshot', 'orders'}), 'realized_r': t.realized_r}
                   for t in sorted(orch.store.closed_trades(), key=lambda t: t.closed_at, reverse=True)[:50]],
        "performance": orch.store.performance(),
    }


@app.post("/api/trades/{trade_id}/close")
async def close_trade(trade_id: str):
    require_paper_mode()
    return await orch.close_trade(trade_id)


# --- P&L, settings, status ------------------------------------------------ #

@app.get("/api/pnl")
def pnl():
    return orch.store.pnl_summary()


@app.get('/api/performance')
def performance():
    return orch.store.performance()


@app.get("/api/settings")
def get_settings():
    return orch.rules.as_dict()


@app.put("/api/settings")
async def put_settings(patch: dict):
    try:
        orch.rules.update(patch)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from None
    return orch.rules.as_dict()


@app.put("/api/filters/market-cap")
async def set_market_cap_filter(body: dict):
    try:
        orch.rules.update({'min_market_cap_millions': body.get('millions', 0)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    millions = orch.rules.min_market_cap_millions
    await orch.rescan_universe()
    return {"ok": True, "min_market_cap_millions": orch.rules.min_market_cap_millions}


@app.put("/api/filters/russell-1000")
async def set_russell_filter(body: dict):
    try:
        orch.rules.update({'scan_russell_1000_only': body.get('enabled', True)})
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    await orch.rescan_universe()
    return {"ok": True, "scan_russell_1000_only": orch.rules.scan_russell_1000_only}


@app.post("/api/automation/toggle")
def toggle_automation():
    require_paper_mode()
    if not orch.connected or not getattr(orch.broker, 'paper_verified', False):
        raise HTTPException(409, "Paper account is not connected and verified.")
    orch.rules.auto_trade_enabled = not orch.rules.auto_trade_enabled
    return {"ok": True, "auto_trade_enabled": orch.rules.auto_trade_enabled}


@app.post("/api/automation/disable")
def disable_automation():
    orch.rules.auto_trade_enabled = False
    return {"ok": True, "auto_trade_enabled": False}


@app.get("/api/status")
def status():
    can, reason = orch.risk.can_trade()
    verified = bool(getattr(orch.broker, 'paper_verified', False))
    if not paper_execution_allowed():
        can, reason = False, "Research-only mode"
    elif not orch.connected or not verified:
        can, reason = False, "Paper account is not connected and verified"
    elif orch.store.storage_error:
        can, reason = False, orch.store.storage_error
    elif any(t.reconciliation_error for t in orch.store.open_trades()):
        can, reason = False, "Paper reconciliation requires attention"
    return {
        "execution_mode": settings.execution_mode,
        "live_trading_allowed": False,
        "paper_verified": verified,
        "pnl_verified": not any(t.reconciliation_error for t in orch.store.open_trades()) and not orch.store.storage_error,
        "pnl_basis": "Broker-confirmed closed paper fills, gross of fees",
        "tracking": orch.store.performance(),
        "broker_connected": orch.connected,
        "broker": settings.broker,
        "market_session": market_session(),
        "extended_hours": is_extended_hours(),
        "watching": sorted(orch.detectors.keys()),
        "scan_universe": orch.scan_universe,
        "scan_filter_errors": orch.scan_data.filter_errors,
        "scan_source_errors": orch.scan_data.source_errors,
        "membership": orch.scan_data.finnhub.membership_status,
        "scan_coverage": orch.scan_coverage,
        "scan_in_progress": orch.scan_in_progress,
        "last_scan_error": orch.last_scan_error,
        "candidates": {s: c.model_dump() for s, c in orch.candidates.items()},
        "auto_trade_enabled": paper_execution_allowed() and verified and orch.connected and orch.rules.auto_trade_enabled,
        "trades_today": orch.risk.trades_today,
        "realized_pnl_today": round(orch.risk.realized_pnl_today, 2),
        "can_trade": can,
        "blocked_reason": reason,
        "min_market_cap_millions": orch.rules.min_market_cap_millions,
        "auto_trade_threshold": orch.rules.auto_trade_threshold,
        "scan_interval_seconds": settings.scan_interval_seconds,
        "bar_poll_interval_seconds": settings.bar_poll_interval_seconds,
        "last_scan_at": orch.last_scan_at,
        "last_scan_duration_seconds": orch.last_scan_duration_seconds,
        "last_poll_duration_seconds": orch.last_poll_duration_seconds,
        "data_feed": settings.alpaca_data_feed if settings.broker == "alpaca" else "ibkr",
        "morning_only": settings.morning_only,
        "setup_score_weights": {"technical": 100, "fundamental": 0, "ai": 0},
        "last_bar_at": {sym: det.bars[-1].ts if det.bars else None for sym, det in orch.detectors.items()},
        "signal_ttl_seconds": settings.signal_ttl_seconds,
        "active_detectors": len(orch.detectors),
        "scan_russell_1000_only": orch.rules.scan_russell_1000_only,
    }


# --- watchlist -------------------------------------------------------------- #

@app.get("/api/watchlist")
def get_watchlist():
    items = sorted(orch.watchlist.values(), key=lambda w: w.score, reverse=True)
    return [i.model_dump() for i in items]


@app.get("/api/watchlist/{symbol}")
async def get_watch_detail(symbol: str):
    item = await orch.watch_detail(symbol)
    if not item:
        return JSONResponse({"error": f"{symbol} not in today's scan"}, status_code=404)
    return item.model_dump()


# --- chart ------------------------------------------------------------------ #

@app.get("/api/chart/{symbol}")
async def chart(symbol: str, signal_id: str | None = None):
    sym = symbol.upper()
    if sym not in orch.scan_universe:
        return JSONResponse({"error": f"{sym} not in today's scan"}, status_code=404)
    if sym not in orch.detectors:
        orch.schedule_chart_init(sym)
        return {"loading": True, "bars": [], "vwap": [], "prior_vwap": [], "markers": []}
    payload = orch.chart(sym, signal_id=signal_id)
    if payload is None:
        return JSONResponse({"error": f"chart not ready for {symbol}"}, status_code=404)
    return payload


# --- web UI -------------------------------------------------------------- #

_NO_CACHE = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"}


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers=_NO_CACHE)


@app.get("/technicals")
def daily_technicals():
    return FileResponse(WEB_DIR / "technicals.html", headers=_NO_CACHE)


@app.get("/static/app.js")
def app_js():
    return FileResponse(
        WEB_DIR / "app.js",
        media_type="application/javascript",
        headers=_NO_CACHE,
    )


app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
