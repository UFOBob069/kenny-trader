"""Persistence: Supabase when configured, in-memory fallback otherwise."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings
from app.models import Signal, SignalStatus, Trade, TradeStatus

log = logging.getLogger(__name__)
ET = ZoneInfo('America/New_York')


class MemoryStore:
    """Keeps everything in process memory. Used when Supabase isn't configured."""

    def __init__(self) -> None:
        self.signals: dict[str, Signal] = {}
        self.trades: dict[str, Trade] = {}
        self.persistence = 'memory'
        self.storage_error: str | None = None
        self.durability_error: str | None = None

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

    def quarantine_legacy(self):
        for trade in self.trades.values():
            if trade.strategy_version == 'legacy' and not trade.order_ids and not trade.client_order_id and trade.status == TradeStatus.OPEN:
                trade.status = TradeStatus.UNATTRIBUTED
                trade.reconciliation_error = 'Historical record lacks broker order IDs; outcome unknown, excluded from results'
                trade.pnl_verified = False

    def open_trades(self) -> list[Trade]:
        return [t for t in self.trades.values() if t.status not in (TradeStatus.CLOSED, TradeStatus.CANCELED, TradeStatus.UNATTRIBUTED)]

    def closed_trades(self, since: datetime | None = None) -> list[Trade]:
        out = [t for t in self.trades.values() if t.status == TradeStatus.CLOSED and t.pnl_verified]
        if since:
            out = [t for t in out if t.closed_at and t.closed_at >= since]
        return out

    # P&L ---------------------------------------------------------------- #
    def pnl_summary(self) -> dict:
        now = datetime.now(timezone.utc)
        today_start = datetime.combine(datetime.now(ET).date(), datetime.min.time(), tzinfo=ET)
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
        out['basis'] = 'Broker-confirmed closed paper trades; gross of fees. Legacy estimates excluded.'
        return out

    def performance(self) -> dict:
        groups = {}
        for trade in self.closed_trades():
            key = (trade.setup, trade.direction.value, trade.strategy_version)
            groups.setdefault(key, []).append(trade)
        rows = []
        for (setup, direction, version), trades in groups.items():
            pnls = [t.realized_pnl for t in trades]
            rs = [t.realized_r for t in trades if t.realized_r is not None]
            losses = -sum(p for p in pnls if p < 0)
            rows.append(dict(setup=setup, direction=direction, version=version, trades=len(trades),
                             wins=sum(p > 0 for p in pnls), win_rate=round(sum(p > 0 for p in pnls) / len(trades) * 100, 1),
                             pnl=round(sum(pnls), 2), expectancy=round(sum(pnls) / len(pnls), 2),
                             average_r=round(sum(rs) / len(rs), 3) if rs else None,
                             profit_factor=round(sum(p for p in pnls if p > 0) / losses, 2) if losses else None,
                             sample_label='Small sample' if len(trades) < 30 else 'Descriptive, not proof of edge'))
        return dict(groups=sorted(rows, key=lambda r: r['pnl'], reverse=True),
                    verified_closed=len(self.closed_trades()),
                    excluded=sum((t.status == TradeStatus.CLOSED and not t.pnl_verified) or t.status == TradeStatus.UNATTRIBUTED for t in self.trades.values()),
                    unattributed=sum(t.status == TradeStatus.UNATTRIBUTED for t in self.trades.values()),
                    pending=sum(t.status in (TradeStatus.PENDING, TradeStatus.SUBMITTING) for t in self.trades.values()),
                    canceled=sum(t.status == TradeStatus.CANCELED for t in self.trades.values()),
                    unresolved=sum(bool(t.reconciliation_error) for t in self.open_trades()),
                    persistence=self.persistence, storage_error=self.storage_error,
                    basis='Paper fills, gross of fees; canceled/unfilled and legacy estimates excluded. R uses original planned risk on filled shares.')

    def _dashboard_stats(self, today_start: datetime) -> dict:
        today_closed = self.closed_trades(today_start)
        pnls = [(t.symbol, t.realized_pnl or 0.0) for t in today_closed]
        best = max(pnls, key=lambda x: x[1]) if pnls else None
        worst = min(pnls, key=lambda x: x[1]) if pnls else None
        open_risk = sum(abs((t.entry_fill_price or t.entry) - t.stop) * t.remaining_quantity for t in self.open_trades())
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
        self.persistence = 'supabase'
        # Existing settings JSONB table avoids a migration-dependent execution window.
        offset = 0
        while True:
            rows = self._sb.table('settings').select('key,value').like('key', 'paper.%').order('key').range(offset, offset + 499).execute().data
            for row in rows:
                if row['key'].startswith('paper.trade.'):
                    trade = Trade.model_validate(row['value'])
                    self.trades[trade.id] = trade
                elif row['key'].startswith('paper.signal.'):
                    signal = Signal.model_validate(row['value'])
                    self.signals[signal.id] = signal
            if len(rows) < 500:
                break
            offset += 500
        # Old rows cannot establish fills/order ownership; keep them explicitly unverified.
        offset = 0
        while True:
            rows = self._sb.table('trades').select('*').order('id').range(offset, offset + 499).execute().data
            for row in rows:
                if row['id'] not in self.trades:
                    trade = Trade.model_validate(row)
                    self.trades[trade.id] = trade
            if len(rows) < 500:
                break
            offset += 500

        self.quarantine_legacy()

    def _journal(self, key, value):
        try:
            self._sb.table('settings').upsert({'key': key, 'value': value,
                                             'updated_at': datetime.now(timezone.utc).isoformat()}).execute()
            self.storage_error = None
        except Exception:
            self.storage_error = 'Paper journal write failed; new orders blocked'
            raise RuntimeError(self.storage_error) from None

    def save_signal(self, s: Signal) -> None:
        self._journal('paper.signal.' + s.id, s.model_dump(mode='json'))
        super().save_signal(s)
        try:
            self._sb.table("signals").upsert(_signal_row(s)).execute()
        except Exception:
            log.exception("Supabase signal upsert failed")

    def save_trade(self, t: Trade) -> None:
        self._journal('paper.trade.' + t.id, t.model_dump(mode='json'))
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


class SQLiteStore(MemoryStore):
    def __init__(self, path: str):
        super().__init__()
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute('CREATE TABLE IF NOT EXISTS journal (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        self.persistence = 'sqlite'
        for key, value in self._db.execute('SELECT key, value FROM journal'):
            if key.startswith('trade.'):
                trade = Trade.model_validate_json(value)
                self.trades[trade.id] = trade
            elif key.startswith('signal.'):
                signal = Signal.model_validate_json(value)
                self.signals[signal.id] = signal

        self.quarantine_legacy()

    def _journal(self, key, model):
        try:
            with self._db:
                self._db.execute('INSERT OR REPLACE INTO journal VALUES (?, ?)', (key, model.model_dump_json()))
            self.storage_error = self.durability_error
        except Exception:
            self.storage_error = 'Paper journal write failed; new orders blocked'
            raise RuntimeError(self.storage_error) from None

    def save_signal(self, signal):
        self._journal('signal.' + signal.id, signal)
        super().save_signal(signal)

    def save_trade(self, trade):
        self._journal('trade.' + trade.id, trade)
        super().save_trade(trade)


def make_store() -> MemoryStore:
    if settings.supabase_url and settings.supabase_key:
        try:
            store = SupabaseStore()
            log.info("Using Supabase store")
            return store
        except Exception:
            log.exception("Supabase recovery failed; execution disabled")
            store = MemoryStore()
            store.storage_error = 'Supabase recovery failed; paper trading blocked until journal is restored'
            return store
    try:
        store = SQLiteStore(settings.state_db_path)
        if os.getenv('RAILWAY_ENVIRONMENT_ID'):
            mount = os.getenv('RAILWAY_VOLUME_MOUNT_PATH')
            if not mount or not Path(settings.state_db_path).resolve().is_relative_to(Path(mount).resolve()):
                store.durability_error = 'Set STATE_DB_PATH on a Railway volume or configure Supabase before paper trading'
                store.storage_error = store.durability_error
        return store
    except Exception:
        log.exception('Paper journal recovery failed')
        store = MemoryStore()
        store.storage_error = 'Paper journal unavailable; trading blocked'
        return store
