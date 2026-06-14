"""Persistence: Supabase when configured, in-memory fallback otherwise."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.config import settings
from app.models import Signal, SignalStatus, Trade, TradeStatus

log = logging.getLogger(__name__)


class MemoryStore:
    """Keeps everything in process memory. Used when Supabase isn't configured."""

    def __init__(self) -> None:
        self.signals: dict[str, Signal] = {}
        self.trades: dict[str, Trade] = {}

    # signals ---------------------------------------------------------- #
    def save_signal(self, s: Signal) -> None:
        self.signals[s.id] = s

    def get_signal(self, signal_id: str) -> Signal | None:
        return self.signals.get(signal_id)

    def pending_signals(self) -> list[Signal]:
        return sorted(
            (s for s in self.signals.values() if s.status == SignalStatus.PENDING),
            key=lambda s: s.created_at, reverse=True,
        )

    def recent_signals(self, limit: int = 50) -> list[Signal]:
        return sorted(self.signals.values(), key=lambda s: s.created_at, reverse=True)[:limit]

    # trades ------------------------------------------------------------ #
    def save_trade(self, t: Trade) -> None:
        self.trades[t.id] = t

    def get_trade(self, trade_id: str) -> Trade | None:
        return self.trades.get(trade_id)

    def open_trades(self) -> list[Trade]:
        return [t for t in self.trades.values() if t.status == TradeStatus.OPEN]

    def closed_trades(self, since: datetime | None = None) -> list[Trade]:
        out = [t for t in self.trades.values() if t.status == TradeStatus.CLOSED]
        if since:
            out = [t for t in out if t.closed_at and t.closed_at >= since]
        return out

    # P&L ---------------------------------------------------------------- #
    def pnl_summary(self) -> dict:
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(date.today(), datetime.min.time(), tzinfo=timezone.utc)
        windows = {
            "today": today_start,
            "week": now - timedelta(days=7),
            "month": now - timedelta(days=30),
            "lifetime": None,
        }
        out = {}
        for name, since in windows.items():
            trades = self.closed_trades(since)
            pnls = [t.realized_pnl or 0.0 for t in trades]
            winners = [p for p in pnls if p > 0]
            losers = [p for p in pnls if p < 0]
            gross_win, gross_loss = sum(winners), abs(sum(losers))
            out[name] = {
                "pnl": round(sum(pnls), 2),
                "trades": len(pnls),
                "win_rate": round(len(winners) / len(pnls) * 100, 1) if pnls else 0.0,
                "avg_winner": round(gross_win / len(winners), 2) if winners else 0.0,
                "avg_loser": round(-gross_loss / len(losers), 2) if losers else 0.0,
                "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            }
        out["dashboard"] = self._dashboard_stats(today_start)
        return out

    def _dashboard_stats(self, today_start: datetime) -> dict:
        today_closed = self.closed_trades(today_start)
        pnls = [(t.symbol, t.realized_pnl or 0.0) for t in today_closed]
        best = max(pnls, key=lambda x: x[1]) if pnls else None
        worst = min(pnls, key=lambda x: x[1]) if pnls else None
        open_risk = sum(abs(t.entry - t.stop) * t.quantity for t in self.open_trades())
        week = self.closed_trades(datetime.now(timezone.utc) - timedelta(days=7))
        week_pnls = [t.realized_pnl or 0.0 for t in week]
        return {
            "open_risk": round(open_risk, 2),
            "best_trade": {"symbol": best[0], "pnl": round(best[1], 2)} if best else None,
            "worst_trade": {"symbol": worst[0], "pnl": round(worst[1], 2)} if worst else None,
            "week_pnl": round(sum(week_pnls), 2),
        }


class SupabaseStore(MemoryStore):
    """Mirrors every write to Supabase; reads stay in memory for speed.
    Tables: signals, trades (see supabase/schema.sql)."""

    def __init__(self) -> None:
        super().__init__()
        from supabase import create_client
        self._sb = create_client(settings.supabase_url, settings.supabase_key)

    def save_signal(self, s: Signal) -> None:
        super().save_signal(s)
        try:
            self._sb.table("signals").upsert(_signal_row(s)).execute()
        except Exception:
            log.exception("Supabase signal upsert failed")

    def save_trade(self, t: Trade) -> None:
        super().save_trade(t)
        try:
            self._sb.table("trades").upsert(_trade_row(t)).execute()
        except Exception:
            log.exception("Supabase trade upsert failed")


def _signal_row(s: Signal) -> dict:
    return {
        "id": s.id,
        "created_at": s.created_at.isoformat(),
        "symbol": s.symbol,
        "direction": s.direction.value,
        "setup": s.setup.value,
        "entry": s.entry,
        "stop": s.stop,
        "target": s.target,
        "confidence": s.confidence,
        "status": s.status.value,
        "breakdown": s.breakdown.model_dump() if s.breakdown else None,
    }


def _trade_row(t: Trade) -> dict:
    return {
        "id": t.id,
        "signal_id": t.signal_id,
        "symbol": t.symbol,
        "direction": t.direction.value,
        "quantity": t.quantity,
        "entry": t.entry,
        "stop": t.stop,
        "target": t.target,
        "confidence": t.confidence,
        "status": t.status.value,
        "opened_at": t.opened_at.isoformat(),
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "exit_price": t.exit_price,
        "realized_pnl": t.realized_pnl,
    }


def make_store() -> MemoryStore:
    if settings.supabase_url and settings.supabase_key:
        try:
            store = SupabaseStore()
            log.info("Using Supabase store")
            return store
        except Exception:
            log.exception("Supabase init failed; falling back to memory store")
    log.warning("Supabase not configured — using in-memory store (state lost on restart)")
    return MemoryStore()
