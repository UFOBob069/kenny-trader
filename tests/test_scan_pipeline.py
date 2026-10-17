import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.engine.orchestrator import Orchestrator
from app.models import Candidate, WatchItem


@pytest.mark.asyncio
async def test_scan_initializes_beyond_old_twelve_and_reports_coverage(monkeypatch):
    monkeypatch.setattr('app.engine.orchestrator.MAX_ACTIVE_SYMBOLS', 15)
    symbols = {f'S{i}': 'mover' for i in range(18)}
    o = Orchestrator.__new__(Orchestrator)
    o.rules = SimpleNamespace(min_market_cap_floor_usd=0)
    o.detectors = {}
    o._session_dates = {}
    o.connected = True
    o.store = SimpleNamespace(pending_signals=lambda: [])
    o.scan_data = SimpleNamespace(raw_symbol_count=18)
    o._expire_stale_signals = Mock()
    o._schedule_analysis = Mock()
    entered = 0
    maximum = 0

    async def entry(sym, catalyst):
        nonlocal entered, maximum
        entered += 1
        maximum = max(maximum, entered)
        await asyncio.sleep(.001)
        entered -= 1
        return WatchItem(symbol=sym, catalyst=catalyst, qualified=sym in o.detectors)

    async def init(sym):
        o.detectors[sym] = object()

    async def candidates(universe):
        return [Candidate(symbol=s) for s in universe if s in o.detectors]

    o._init_detector = AsyncMock(side_effect=init)
    o.scanner = SimpleNamespace(filtered_universe=AsyncMock(return_value=symbols),
                               rank_universe=lambda rows: list(rows), watch_entry=entry,
                               scan=AsyncMock(side_effect=candidates))
    await o._scan_once()
    assert len(o.detectors) == 15
    assert o.scan_coverage['qualified_symbols'] == 15
    assert len(o.scan_coverage['unmonitored_symbols']) == 3
    assert maximum == 4
    await o._scan_once()
    assert o._init_detector.await_count == 15
    o.scanner.filtered_universe.return_value = {}
    await o._scan_once()
    assert o.watchlist == {}  # Filter failures must not leave old rows looking current.
    assert o.detectors == {}
    assert o.candidates == {}


@pytest.mark.asyncio
async def test_scan_failure_exposes_health_and_clears_actionable_candidates():
    o = Orchestrator.__new__(Orchestrator)
    o._scan_lock = asyncio.Lock()
    o._scan_once = AsyncMock(side_effect=RuntimeError('provider'))
    o.candidates = {'OLD': object()}
    with pytest.raises(RuntimeError):
        await o._run_scan()
    assert not o.scan_in_progress
    assert o.last_scan_error
    assert o.candidates == {}
    assert o.last_scan_duration_seconds >= 0
