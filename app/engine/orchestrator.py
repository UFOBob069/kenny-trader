"""Main loop: scan -> watch bars -> detect setups -> score -> alert or execute.

Runs as a background task inside the FastAPI app. Re-scans periodically,
maintains one SetupDetector per active symbol, and polls fresh 1-minute bars.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.ai.analyst import CatalystAnalyst
from app.ai.confidence import score_signal
from app.config import settings
from app.data.alpaca import AlpacaClient
from app.data.broker import make_broker
from app.data.finnhub import FinnhubClient
from app.data.scan_data import DailyScanData
from app.db.store import make_store
from app.engine.risk import RiskManager, RuntimeRules
from app.engine.scanner import Scanner
from app.engine.trader import Trader
from app.models import Candidate, Signal, SignalStatus, WatchItem
from app.signals.detector import SetupDetector

log = logging.getLogger(__name__)

SCAN_INTERVAL = 300        # re-scan candidates every 5 minutes
BAR_POLL_INTERVAL = 30     # poll for new 1-min bars every 30 s
MARK_INTERVAL = 60         # refresh open-trade marks every minute
MAX_ACTIVE_SYMBOLS = 8


class Orchestrator:
    def __init__(self) -> None:
        self.store = make_store()
        self.rules = RuntimeRules(settings)
        self.risk = RiskManager(self.rules)
        self.broker = make_broker()
        alpaca = self.broker if isinstance(self.broker, AlpacaClient) else None
        self.scan_data = DailyScanData(FinnhubClient(), alpaca)
        self.scanner = Scanner(self.scan_data)
        self.analyst = CatalystAnalyst()
        self.trader = Trader(self.broker, self.store, self.risk)

        self.detectors: dict[str, SetupDetector] = {}
        self.candidates: dict[str, Candidate] = {}
        self.scan_universe: dict[str, str] = {}
        self.watchlist: dict[str, WatchItem] = {}
        self._bar_counts: dict[str, int] = {}
        self._chart_init_tasks: dict[str, asyncio.Task] = {}
        self._tasks: list[asyncio.Task] = []
        self.connected = False

    # ------------------------------------------------------------------ #

    async def start(self) -> None:
        try:
            await self.broker.connect()
            self.connected = True
        except Exception:
            log.exception("Broker connection failed — running in signal-only mode (no data, no orders)")
        self._tasks = [
            asyncio.create_task(self._scan_loop(), name="scan"),
            asyncio.create_task(self._bar_loop(), name="bars"),
            asyncio.create_task(self._mark_loop(), name="marks"),
        ]

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        await self.scan_data.close()
        self.broker.disconnect()

    # ------------------------------------------------------------------ #

    async def rescan_universe(self) -> None:
        """Re-run daily universe + watchlist (e.g. after filter settings change)."""
        await self._run_scan()

    async def _scan_loop(self) -> None:
        while True:
            try:
                await self._run_scan()
            except Exception:
                log.exception("Scan loop error")
            await asyncio.sleep(SCAN_INTERVAL)

    async def _run_scan(self) -> None:
        self.scan_universe = await self.scanner.filtered_universe(
            self.rules.min_market_cap_floor_usd,
        )

        # Expire pending signals for symbols dropped by the scan / cap filter.
        for sig in list(self.store.pending_signals()):
            if sig.symbol.upper() not in self.scan_universe:
                sig.status = SignalStatus.EXPIRED
                self.store.save_signal(sig)
                log.info("Expired stale signal for %s", sig.symbol)

        ui_symbols: dict[str, str] = dict(self.scan_universe)
        for sym in self.detectors:
            ui_symbols.setdefault(sym, self.scan_universe.get(sym, "chart"))

        self.watchlist = {}
        for sym in self.scanner.rank_universe(ui_symbols):
            catalyst = ui_symbols.get(sym, "news")
            item = await self.scanner.watch_entry(sym, catalyst)
            item.watching = sym in self.detectors
            self.watchlist[sym] = item

        allowed_charts = set(self.scan_universe)
        stale = set(self.detectors) - allowed_charts
        for sym in stale:
            del self.detectors[sym]
            self._bar_counts.pop(sym, None)
            log.info("Stopped chart feed for %s (filtered out)", sym)

        ranked = sorted(
            [w for w in self.watchlist.values() if w.symbol in self.scan_universe],
            key=lambda w: w.score,
            reverse=True,
        )
        for item in ranked[:MAX_ACTIVE_SYMBOLS]:
            if item.symbol not in self.detectors and self.connected:
                await self._init_detector(item.symbol)
                item.watching = True

        filtered = await self.scanner.scan(self.scan_universe)
        self.candidates = {c.symbol: c for c in filtered}

        log.info(
            "Scan complete — universe: %d, watching: %d, filtered: %d",
            len(self.scan_universe),
            len(self.detectors),
            len(filtered),
        )

    async def _init_detector(self, symbol: str) -> None:
        prior, today = await self.broker.prior_session_bars(symbol)
        det = SetupDetector(symbol, prior_day_bars=prior)
        cand = self.candidates.get(symbol)
        for bar in today:
            det.on_bar(bar, cand)  # replay today's history without acting on old signals
        self.detectors[symbol] = det
        self._bar_counts[symbol] = len(today)
        log.info("Watching %s (%d prior bars, %d today)", symbol, len(prior), len(today))

    async def _bar_loop(self) -> None:
        while True:
            await asyncio.sleep(BAR_POLL_INTERVAL)
            if not self.connected:
                continue
            for symbol, det in list(self.detectors.items()):
                try:
                    bars = await self.broker.minute_bars(symbol, days=1)
                    seen = self._bar_counts.get(symbol, 0)
                    new = bars[seen:]
                    if not new:
                        continue
                    self._bar_counts[symbol] = len(bars)
                    cand = self.candidates.get(symbol)
                    for bar in new:
                        for sig in det.on_bar(bar, cand):
                            await self._handle_signal(sig, det)
                except Exception:
                    log.exception("Bar loop error for %s", symbol)

    async def _mark_loop(self) -> None:
        while True:
            await asyncio.sleep(MARK_INTERVAL)
            if not self.connected:
                continue
            try:
                await self.trader.refresh_marks()
            except Exception:
                log.exception("Mark refresh error")

    # ------------------------------------------------------------------ #

    async def _handle_signal(self, signal: Signal, det: SetupDetector) -> None:
        cand = signal.candidate
        analysis = await self.analyst.analyze(cand) if cand else {"sentiment": "neutral", "score": 50, "reasons": []}

        last_close = det.bars[-1].close
        above_vwap = det.vwap.value is not None and last_close > det.vwap.value
        above_pdv = (last_close > det.prior_vwap.value) if det.has_prior and det.prior_vwap.value else None

        breakdown = score_signal(signal, analysis, above_vwap, above_pdv)
        signal.breakdown = breakdown
        signal.confidence = breakdown.total
        self.store.save_signal(signal)
        log.info("SIGNAL %s %s @ %.2f stop %.2f target %.2f — confidence %.0f%%",
                 signal.direction.value, signal.symbol, signal.entry, signal.stop,
                 signal.target, signal.confidence)

        if self.rules.auto_trade_enabled and signal.confidence >= self.rules.auto_trade_threshold:
            trade, err = await self.trader.execute(signal, auto=True)
            if err:
                log.warning("Auto-trade failed for %s: %s", signal.symbol, err)
        # otherwise it stays PENDING for manual approval in the dashboard

    # ------------------------------------------------------------------ #
    # called from the API layer

    async def approve_signal(self, signal_id: str) -> dict:
        sig = self.store.get_signal(signal_id)
        if not sig:
            return {"ok": False, "error": "signal not found"}
        if sig.status != SignalStatus.PENDING:
            return {"ok": False, "error": f"signal is {sig.status.value}"}
        if not self.connected:
            return {"ok": False, "error": "broker not connected"}
        # signals go stale fast
        age = (datetime.now(timezone.utc) - sig.created_at).total_seconds()
        if age > 600:
            sig.status = SignalStatus.EXPIRED
            self.store.save_signal(sig)
            return {"ok": False, "error": "signal expired (>10 min old)"}
        trade, note = await self.trader.execute(sig, auto=False)
        if trade:
            return {"ok": True, "trade_id": trade.id, "message": note}
        return {"ok": False, "error": note or "order failed"}

    def ignore_signal(self, signal_id: str) -> dict:
        sig = self.store.get_signal(signal_id)
        if not sig:
            return {"ok": False, "error": "signal not found"}
        sig.status = SignalStatus.IGNORED
        self.store.save_signal(sig)
        return {"ok": True}

    async def open_orders(self) -> list[dict]:
        if isinstance(self.broker, AlpacaClient):
            return await self.broker.list_open_orders()
        return []

    async def account_info(self) -> dict:
        if isinstance(self.broker, AlpacaClient):
            return await self.broker.account_summary()
        return {}

    def chart(self, symbol: str, signal_id: str | None = None) -> dict | None:
        sym = symbol.upper()
        det = self.detectors.get(sym)
        if not det:
            return None
        payload = det.chart_payload()
        payload["markers"] = self._markers(sym)

        last = det.bars[-1].close if det.bars else None
        item = self.watchlist.get(sym)
        if item and item.price:
            last = item.price

        sig = self.store.get_signal(signal_id) if signal_id else None
        if not sig or sig.symbol.upper() != sym:
            pending = [s for s in self.store.pending_signals() if s.symbol.upper() == sym]
            sig = max(pending, key=lambda s: s.confidence) if pending else None

        levels = None
        setup_label = None
        if sig:
            levels = {
                "entry": sig.entry,
                "stop": sig.stop,
                "target": sig.target,
                "direction": sig.direction.value,
            }
            setup_label = sig.setup.value.replace("_", " ")
            payload["signal"] = {
                "id": sig.id,
                "setup": setup_label,
                "direction": sig.direction.value,
                "confidence": sig.confidence,
                "reward_risk": round(sig.reward_risk, 2),
            }

        payload["last_price"] = round(last, 2) if last else None
        payload["levels"] = levels
        return payload

    def schedule_chart_init(self, symbol: str) -> None:
        """Start chart/detector load in the background (non-blocking for HTTP)."""
        sym = symbol.upper()
        if sym not in self.scan_universe or sym in self.detectors or not self.connected:
            return
        if sym in self._chart_init_tasks:
            return

        async def _run() -> None:
            try:
                await self._init_detector(sym)
                if sym in self.watchlist:
                    self.watchlist[sym].watching = True
            except Exception:
                log.exception("Chart init failed for %s", sym)
            finally:
                self._chart_init_tasks.pop(sym, None)

        self._chart_init_tasks[sym] = asyncio.create_task(_run(), name=f"chart-{sym}")

    async def ensure_chart(self, symbol: str) -> bool:
        sym = symbol.upper()
        if sym not in self.scan_universe:
            return False
        if sym in self.detectors:
            return True
        if not self.connected:
            return False
        self.schedule_chart_init(sym)
        if sym in self._chart_init_tasks:
            await self._chart_init_tasks[sym]
        return sym in self.detectors

    async def watch_detail(self, symbol: str) -> WatchItem | None:
        sym = symbol.upper()
        if sym not in self.scan_universe:
            return None
        catalyst = self.scan_universe.get(sym, "chart")
        item = await self.scanner.watch_entry(sym, catalyst, with_news=True)
        if sym in self.detectors:
            item.watching = True
        elif self.connected and sym in self.scan_universe:
            await self.ensure_chart(sym)
            item.watching = sym in self.detectors
        self.watchlist[sym] = item
        return item

    async def close_trade(self, trade_id: str) -> dict:
        trade = self.store.get_trade(trade_id)
        if not trade:
            return {"ok": False, "error": "trade not found"}
        await self.trader.close(trade)
        return {"ok": True, "realized_pnl": trade.realized_pnl}

    def _markers(self, symbol: str) -> list[dict]:
        markers = []
        for t in self.store.trades.values():
            if t.symbol != symbol:
                continue
            markers.append({
                "time": int(t.opened_at.timestamp()),
                "position": "belowBar" if t.direction.value == "LONG" else "aboveBar",
                "shape": "arrowUp" if t.direction.value == "LONG" else "arrowDown",
                "color": "#26a69a" if t.direction.value == "LONG" else "#ef5350",
                "text": f"{t.direction.value} {t.quantity} @ {t.entry}",
            })
            if t.closed_at:
                markers.append({
                    "time": int(t.closed_at.timestamp()),
                    "position": "aboveBar" if t.direction.value == "LONG" else "belowBar",
                    "shape": "circle",
                    "color": "#ffb74d",
                    "text": f"EXIT @ {t.exit_price}",
                })
        return markers
