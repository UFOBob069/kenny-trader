"""Main loop: scan -> watch bars -> detect setups -> score -> alert or execute.

Runs as a background task inside the FastAPI app. Re-scans periodically,
maintains one SetupDetector per active symbol, and polls fresh 1-minute bars.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from time import monotonic

from app.ai.analyst import CatalystAnalyst
from app.ai.confidence import score_signal
from app.config import settings
from app.data.alpaca import AlpacaClient
from app.data.bar_sessions import completed_bars
from app.data.market_hours import ET, is_morning_setup_window
from app.data.broker import make_broker
from app.data.finnhub import FinnhubClient
from app.data.scan_data import DailyScanData
from app.db.store import make_store
from app.engine.risk import RiskManager, RuntimeRules
from app.engine.signal_hygiene import expire_reason
from app.engine.scanner import Scanner
from app.engine.liquidity import execution_liquidity_reason, recent_activity
from app.engine.trader import Trader
from app.engine.execution_policy import paper_execution_allowed, require_paper_execution
from app.models import Candidate, Signal, SignalStatus, WatchItem
from app.signals.detector import SetupDetector

log = logging.getLogger(__name__)

SCAN_INTERVAL = settings.scan_interval_seconds
BAR_POLL_INTERVAL = settings.bar_poll_interval_seconds
MARK_INTERVAL = 60         # refresh marks + expire stale signals every minute
MAX_ACTIVE_SYMBOLS = settings.max_active_symbols


class Orchestrator:
    def __init__(self) -> None:
        self.store = make_store()
        self.rules = RuntimeRules(settings)
        self.risk = RiskManager(self.rules)
        self.broker = make_broker()
        alpaca = self.broker if isinstance(self.broker, AlpacaClient) else None
        self.scan_data = DailyScanData(FinnhubClient(), alpaca, self.rules)
        self.scanner = Scanner(self.scan_data)
        self.analyst = CatalystAnalyst()
        self.trader = Trader(self.broker, self.store, self.risk)

        self.detectors: dict[str, SetupDetector] = {}
        self.candidates: dict[str, Candidate] = {}
        self.scan_universe: dict[str, str] = {}
        self.watchlist: dict[str, WatchItem] = {}
        self._session_dates: dict = {}
        self._detector_locks: dict[str, asyncio.Lock] = {}
        self._poll_sem = asyncio.Semaphore(4)
        self._scan_lock = asyncio.Lock()
        self._execution_lock = asyncio.Lock()
        self._analysis: dict[str, tuple[Candidate, dict]] = {}
        self._analysis_date = datetime.now(ET).date()
        self._analysis_tasks: dict[str, asyncio.Task] = {}
        self._analysis_sem = asyncio.Semaphore(2)
        self.last_scan_at: datetime | None = None
        self.last_scan_duration_seconds: float | None = None
        self.last_poll_duration_seconds: float | None = None
        self.scan_in_progress = False
        self.last_scan_error: str | None = None
        self.scan_coverage: dict = {}
        self._chart_init_tasks: dict[str, asyncio.Task] = {}
        self._chart_init_sem = asyncio.Semaphore(4)
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
        tasks = self._tasks + list(self._chart_init_tasks.values()) + list(self._analysis_tasks.values())
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await self.scan_data.close()
        await self.analyst.close()
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
        async with self._scan_lock:
            started = monotonic()
            self.scan_in_progress = True
            try:
                await self._scan_once()
                self.last_scan_at = datetime.now(timezone.utc)
                self.last_scan_error = None
            except Exception:
                self.last_scan_error = 'Scan failed; waiting for retry'
                self.candidates = {}
                raise
            finally:
                self.scan_in_progress = False
                self.last_scan_duration_seconds = round(monotonic() - started, 3)

    async def _scan_once(self) -> None:
        self.scan_universe = await self.scanner.filtered_universe(
            self.rules.min_market_cap_floor_usd,
        )

        # Expire pending signals that aged out or are no longer actionable.
        self._expire_stale_signals()

        ui_symbols: dict[str, str] = dict(self.scan_universe)

        semaphore = asyncio.Semaphore(4)

        async def watch(sym):
            catalyst = ui_symbols.get(sym, "news")
            async with semaphore:
                item = await self.scanner.watch_entry(sym, catalyst)
            item.watching = sym in self.detectors
            return sym, item

        self.watchlist = dict(await asyncio.gather(*(watch(sym) for sym in self.scanner.rank_universe(ui_symbols))))

        allowed_charts = set(self.scan_universe)
        stale = set(self.detectors) - allowed_charts
        for sym in stale:
            del self.detectors[sym]
            self._session_dates.pop(sym, None)
            log.info("Stopped chart feed for %s (filtered out)", sym)

        ranked = sorted(
            [w for w in self.watchlist.values() if w.symbol in self.scan_universe],
            key=lambda w: (w.qualified, w.score),
            reverse=True,
        )
        if self.connected:
            pending_syms = {s.symbol.upper() for s in self.store.pending_signals()}
            to_init: list[str] = []
            seen: set[str] = set()
            for item in ranked[:MAX_ACTIVE_SYMBOLS]:
                if item.symbol not in self.detectors:
                    to_init.append(item.symbol)
                    seen.add(item.symbol)
            for sym in pending_syms:
                if sym in self.scan_universe and sym not in self.detectors and sym not in seen:
                    to_init.append(sym)
                    seen.add(sym)
            to_init = to_init[:max(0, MAX_ACTIVE_SYMBOLS - len(self.detectors))]
            if to_init:
                results = await asyncio.gather(
                    *(self._init_detector(sym) for sym in to_init),
                    return_exceptions=True,
                )
                for sym, result in zip(to_init, results):
                    if isinstance(result, Exception):
                        log.exception("Chart init failed for %s", sym)
                    elif sym in self.watchlist:
                        self.watchlist[sym].watching = True

        # Initial history loads also seed same-time-of-day volume profiles.
        refreshed = await asyncio.gather(*(watch(sym) for sym in self.detectors if sym in self.scan_universe))
        self.watchlist.update(refreshed)
        filtered = await self.scanner.scan(self.scan_universe)
        self.candidates = {c.symbol: c for c in filtered}
        self.scan_coverage = dict(raw_symbols=self.scan_data.raw_symbol_count,
                                  filtered_symbols=len(self.scan_universe),
                                  active_symbols=len(self.detectors), qualified_symbols=len(self.candidates),
                                  active_limit=MAX_ACTIVE_SYMBOLS,
                                  unmonitored_symbols=sorted(set(self.scan_universe) - set(self.detectors)))
        self._schedule_analysis()

        log.info(
            "Scan complete — universe: %d, watching: %d, filtered: %d",
            len(self.scan_universe),
            len(self.detectors),
            len(filtered),
        )

    async def _init_detector(self, symbol: str) -> None:
        lock = self._detector_locks.setdefault(symbol, asyncio.Lock())
        async with lock:
            if symbol in self.detectors and self._session_dates.get(symbol) == datetime.now(ET).date():
                return
            await self._load_detector(symbol)

    async def _load_detector(self, symbol: str) -> None:
        async with self._chart_init_sem:
            prior, today = await self.broker.prior_session_bars(symbol)
        det = SetupDetector(symbol, prior_day_bars=prior)
        cand = self.candidates.get(symbol)
        for bar in today:
            det.on_bar(bar, cand)  # replay today's history without acting on old signals
        self.detectors[symbol] = det
        self._session_dates[symbol] = datetime.now(ET).date()
        log.info("Watching %s (%d prior bars, %d today)", symbol, len(prior), len(today))

    async def _bar_loop(self) -> None:
        while True:
            started = monotonic()
            if self.connected:
                await self._poll_once()
                self._expire_stale_signals()
            self.last_poll_duration_seconds = round(monotonic() - started, 3)
            await asyncio.sleep(max(0.1, BAR_POLL_INTERVAL - (monotonic() - started)))

    async def _poll_once(self) -> None:
        detectors = list(self.detectors.items())
        if isinstance(self.broker, AlpacaClient):
            try:
                batch = await self.broker.minute_bars_many([sym for sym, _ in detectors])
            except Exception:
                log.exception("Batch bar poll failed")
                return
            await asyncio.gather(*(self._poll_symbol(sym, det, batch.get(sym, [])) for sym, det in detectors))
        else:
            await asyncio.gather(*(self._poll_symbol(sym, det) for sym, det in detectors))

    async def _poll_symbol(self, symbol: str, det: SetupDetector, bars: list | None = None) -> None:
        try:
            async with self._poll_sem:
                if self._session_dates.get(symbol) != datetime.now(ET).date():
                    await self._init_detector(symbol)
                    return
                if bars is None:
                    bars = await self.broker.minute_bars(symbol, days=1)
            if self.detectors.get(symbol) is not det:
                return
            now = datetime.now(timezone.utc)
            last_ts = det.bars[-1].ts if det.bars else None
            new = [b for b in completed_bars(bars, now)
                   if b.ts.astimezone(ET).date() == now.astimezone(ET).date()
                   and (last_ts is None or b.ts > last_ts)]
            cand = self.candidates.get(symbol)
            for bar in new:
                signals = det.on_bar(bar, cand)
                # Catch-up bars rebuild state but are never new trade opportunities.
                age = (now - (bar.ts + timedelta(minutes=1))).total_seconds()
                if cand and bar is new[-1] and age <= settings.max_signal_bar_age_seconds:
                    for sig in signals:
                        await self._handle_signal(sig, det)
        except Exception:
            log.exception("Bar loop error for %s", symbol)

    def _schedule_analysis(self) -> None:
        today = datetime.now(ET).date()
        if self._analysis_date != today:
            self._analysis.clear()
            self._analysis_date = today
        for sym, cand in self.candidates.items():
            cached = self._analysis.get(sym)
            if (cached and cached[0] == cand) or sym in self._analysis_tasks:
                continue
            self._analysis_tasks[sym] = asyncio.create_task(self._prepare_analysis(sym, cand))

    async def _prepare_analysis(self, symbol: str, candidate: Candidate) -> None:
        day = datetime.now(ET).date()
        try:
            async with self._analysis_sem:
                async def enrich():
                    enriched = candidate.model_copy(deep=True)
                    enriched.earnings = await self.scan_data.earnings_for(symbol, candidate.catalyst)
                    enriched.headlines = await self.scan_data.headlines(symbol)
                    return await self.analyst.analyze(enriched)

                analysis = await asyncio.wait_for(enrich(), timeout=15)
                if day == datetime.now(ET).date():
                    self._analysis[symbol] = (candidate, analysis)
        except Exception:
            log.warning("Catalyst analysis unavailable for %s", symbol)
        finally:
            self._analysis_tasks.pop(symbol, None)

    async def _mark_loop(self) -> None:
        while True:
            await asyncio.sleep(MARK_INTERVAL)
            if not self.connected:
                continue
            try:
                await self.trader.refresh_marks()
                self._expire_stale_signals()
            except Exception:
                log.exception("Mark refresh error")

    def _expire_stale_signals(self) -> None:
        """Drop pending opportunities that timed out or are no longer actionable."""
        now = datetime.now(timezone.utc)
        ttl = settings.signal_ttl_seconds
        for sig in list(self.store.pending_signals()):
            if sig.symbol.upper() not in self.scan_universe:
                sig.status = SignalStatus.EXPIRED
                self.store.save_signal(sig)
                log.info("Expired signal for %s — left scan universe", sig.symbol)
                continue

            price = None
            det = self.detectors.get(sig.symbol.upper())
            if det and det.bars:
                price = det.bars[-1].close
            else:
                item = self.watchlist.get(sig.symbol.upper())
                if item and item.price:
                    price = item.price

            reason = self._signal_invalid_reason(sig) or expire_reason(sig, price, now, ttl)
            if reason:
                sig.status = SignalStatus.EXPIRED
                self.store.save_signal(sig)
                log.info("Expired signal for %s — %s", sig.symbol, reason)

    # ------------------------------------------------------------------ #

    async def _handle_signal(self, signal: Signal, det: SetupDetector) -> None:
        sym = signal.symbol.upper()
        if sym not in self.candidates or sym not in self.scan_universe:
            return
        if self._signal_invalid_reason(signal):
            return
        for existing in self.store.pending_signals():
            if existing.symbol.upper() == sym and existing.id != signal.id:
                existing.status = SignalStatus.EXPIRED
                self.store.save_signal(existing)
                log.info("Replaced stale pending signal for %s", sym)

        cached = self._analysis.get(sym)
        analysis_ready = cached is not None and cached[0] == signal.candidate
        analysis = cached[1] if analysis_ready else {
            "sentiment": "neutral", "score": 50,
            "reasons": ["Catalyst analysis pending; neutral placeholder"],
        }

        last_close = det.bars[-1].close
        above_vwap = det.vwap.value is not None and last_close > det.vwap.value
        above_pdv = (last_close > det.prior_vwap.value) if det.has_prior and det.prior_vwap.value else None

        breakdown = score_signal(signal, analysis, above_vwap, above_pdv)
        signal.breakdown = breakdown
        signal.confidence = breakdown.total
        self.store.save_signal(signal)
        log.info("SIGNAL %s %s @ %.2f stop %.2f target %.2f — setup score %.0f/100",
                 signal.direction.value, signal.symbol, signal.entry, signal.stop,
                 signal.target, signal.confidence)

        if (paper_execution_allowed() and self.rules.auto_trade_enabled
                and signal.confidence >= self.rules.auto_trade_threshold):
            async with self._execution_lock:
                reason = await self._validate_execution(signal)
                if reason:
                    return
                trade, err = await self.trader.execute(signal, auto=True)
            if err:
                log.warning("Auto-trade failed for %s: %s", signal.symbol, err)
        # otherwise it stays PENDING for manual approval in the dashboard

    # ------------------------------------------------------------------ #
    # called from the API layer

    def _signal_invalid_reason(self, sig: Signal) -> str | None:
        if sig.symbol not in self.scan_universe or sig.symbol not in self.candidates:
            return "symbol no longer qualifies"
        det = self.detectors.get(sig.symbol)
        now = datetime.now(timezone.utc)
        if settings.morning_only and (
            not is_morning_setup_window(now) or not is_morning_setup_window(sig.created_at)
        ):
            return "outside morning entry windows"
        if not det or not det.bars:
            return "no current bars"
        bar = det.bars[-1]
        if bar.ts.astimezone(ET).date() != now.astimezone(ET).date():
            return "previous session data"
        if (now - (bar.ts + timedelta(minutes=1))).total_seconds() > settings.max_signal_bar_age_seconds:
            return "market data stale"
        if (now - sig.created_at).total_seconds() > settings.max_signal_bar_age_seconds:
            return "setup too old"
        return expire_reason(sig, bar.close, now, settings.signal_ttl_seconds)

    async def _validate_execution(self, sig: Signal) -> str | None:
        if sig.status != SignalStatus.PENDING:
            return f"signal is {sig.status.value}"
        reason = self._signal_invalid_reason(sig)
        if not reason:
            quote = await self.broker.bid_ask(sig.symbol)
            price = quote.get("ask" if sig.direction.value == "LONG" else "bid") if quote else None
            reason = self._signal_invalid_reason(sig)
            if not reason:
                reason = "no current quote" if not price else expire_reason(
                    sig, price, datetime.now(timezone.utc), settings.signal_ttl_seconds,
                )
            if not reason:
                now = datetime.now(timezone.utc)
                activity = recent_activity(self.detectors[sig.symbol].bars, now)
                reason = execution_liquidity_reason(
                    {**activity, **quote}, now, self.risk.position_size(sig), sig.risk_per_share,
                )
        if reason:
            sig.status = SignalStatus.EXPIRED
            self.store.save_signal(sig)
        return reason

    async def approve_signal(self, signal_id: str) -> dict:
        require_paper_execution()
        sig = self.store.get_signal(signal_id)
        if not sig:
            return {"ok": False, "error": "signal not found"}
        if sig.status != SignalStatus.PENDING:
            return {"ok": False, "error": f"signal is {sig.status.value}"}
        if not self.connected:
            return {"ok": False, "error": "broker not connected"}
        async with self._execution_lock:
            reason = await self._validate_execution(sig)
            if reason:
                return {"ok": False, "error": reason}
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
        if last is None and item and item.price:
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
        item = self.watchlist.get(sym) or await self.scanner.watch_entry(sym, catalyst)
        item.watching = sym in self.detectors
        if sym not in self.detectors and self.connected:
            self.schedule_chart_init(sym)
        self.watchlist[sym] = item
        return item

    async def close_trade(self, trade_id: str) -> dict:
        require_paper_execution()
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
