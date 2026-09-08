import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.data.market_hours import ET
from app.db.store import MemoryStore
from app.engine.orchestrator import Orchestrator
from app.models import Bar, Candidate, Direction, SetupType, Signal, SignalStatus
from app.signals.detector import SetupDetector


def make_bar(ts, price=10):
    return Bar(ts=ts, open=price, high=price + .1, low=price - .1, close=price, volume=1000)


@pytest.fixture
def clock(monkeypatch):
    now = datetime(2026, 9, 8, 14, 10, 5, tzinfo=timezone.utc)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr("app.engine.orchestrator.datetime", FixedDatetime)
    return now


@pytest.fixture
def orch(clock):
    o = Orchestrator.__new__(Orchestrator)
    o.broker = SimpleNamespace(minute_bars=AsyncMock(), last_price=AsyncMock(return_value=10),
                              bid_ask=AsyncMock(return_value={"bid": 10, "ask": 10.01, "quote_at": clock}))
    o.risk = SimpleNamespace(position_size=Mock(return_value=25))
    o.store = MemoryStore()
    o.candidates = {"TEST": Candidate(symbol="TEST", price=10)}
    o.scan_universe = {"TEST": "earnings"}
    o._session_dates = {"TEST": clock.astimezone(ET).date()}
    o._poll_sem = asyncio.Semaphore(4)
    o._execution_lock = asyncio.Lock()
    o._analysis = {}
    o.connected = True
    o.rules = SimpleNamespace(auto_trade_enabled=False)
    o.trader = SimpleNamespace(execute=AsyncMock(return_value=(None, "mock")))
    o.analyst = SimpleNamespace(analyze=AsyncMock())
    det = SetupDetector("TEST")
    det.on_bar(make_bar(clock.replace(second=0) - timedelta(minutes=2)))
    o.detectors = {"TEST": det}
    return o


@pytest.mark.asyncio
async def test_rolling_window_does_not_replay_prior_session_or_skip_latest(orch, clock):
    det = orch.detectors["TEST"]
    first = det.bars[-1]
    last = make_bar(first.ts + timedelta(minutes=1))
    partial = make_bar(clock.replace(second=0))
    orch.broker.minute_bars.return_value = [first, make_bar(first.ts - timedelta(days=1)), partial, last, last]
    await orch._poll_symbol("TEST", det)
    assert [b.ts for b in det.bars] == [first.ts, last.ts]
    # Same-length rolling result with a new timestamp must advance too.
    second = make_bar(first.ts - timedelta(minutes=1))
    orch.broker.minute_bars.return_value = [second, last]
    await orch._poll_symbol("TEST", det)
    assert len(det.bars) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("qualified,stale,expected", [(True, False, 1), (False, False, 0), (True, True, 0)])
async def test_only_latest_fresh_qualified_setup_is_published(orch, clock, qualified, stale, expected):
    end = clock.replace(second=0) - timedelta(minutes=1 if not stale else 10)
    bars = [make_bar(end - timedelta(minutes=1)), make_bar(end)]
    det = SimpleNamespace(bars=[], on_bar=Mock(return_value=[object()]))
    orch.detectors["TEST"] = det
    orch.broker.minute_bars.return_value = bars
    orch._handle_signal = AsyncMock()
    if not qualified:
        orch.candidates = {}
    await orch._poll_symbol("TEST", det)
    assert det.on_bar.call_count == 2
    assert orch._handle_signal.await_count == expected


@pytest.mark.asyncio
async def test_session_rollover_reinitializes_vwap(orch, clock):
    orch._session_dates["TEST"] = (clock - timedelta(days=1)).date()
    orch._init_detector = AsyncMock()
    await orch._poll_symbol("TEST", orch.detectors["TEST"])
    orch._init_detector.assert_awaited_once_with("TEST")
    orch.broker.minute_bars.assert_not_awaited()


def signal(orch, clock):
    return Signal(symbol="TEST", direction=Direction.LONG, setup=SetupType.FAUX_SHOW_BRO,
                  entry=10, stop=9, target=12, created_at=clock - timedelta(seconds=5),
                  candidate=orch.candidates["TEST"])


@pytest.mark.asyncio
async def test_signal_publication_does_not_wait_for_ai(orch, clock):
    sig = signal(orch, clock)
    await orch._handle_signal(sig, orch.detectors["TEST"])
    assert orch.store.get_signal(sig.id) is sig
    orch.analyst.analyze.assert_not_awaited()
    assert "pending" in sig.breakdown.reasons[-1]
    orch.trader.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_rechecks_quote_and_expires_missed_entry(orch, clock):
    sig = signal(orch, clock)
    orch.store.save_signal(sig)
    orch.broker.bid_ask.return_value = {"bid": 10.19, "ask": 10.2, "quote_at": clock}
    result = await orch.approve_signal(sig.id)
    assert result == {"ok": False, "error": "entry missed"}
    assert sig.status == SignalStatus.EXPIRED
    orch.trader.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_feed_blocks_even_recent_signal(orch, clock):
    sig = signal(orch, clock)
    orch.store.save_signal(sig)
    orch.detectors["TEST"].bars[-1].ts -= timedelta(minutes=15)
    result = await orch.approve_signal(sig.id)
    assert result["error"] == "market data stale"
    orch.trader.execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("quantity,allowed", [(25, True), (5000, False)])
async def test_approval_checks_actual_order_size_against_liquidity(orch, clock, quantity, allowed):
    sig = signal(orch, clock)
    orch.store.save_signal(sig)
    bars = [make_bar(clock.replace(second=0) - timedelta(minutes=i)) for i in range(5, 0, -1)]
    for b in bars:
        b.volume = 10_000
    orch.detectors["TEST"].bars = bars
    orch.risk.position_size.return_value = quantity
    result = await orch.approve_signal(sig.id)
    if allowed:
        orch.trader.execute.assert_awaited_once_with(sig, auto=False)
    else:
        assert result["error"] == "order too large for recent traded volume"
        orch.trader.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_approval_rejects_stale_quote_even_when_last_trade_price_is_near_entry(orch, clock):
    sig = signal(orch, clock)
    orch.store.save_signal(sig)
    orch.broker.bid_ask.return_value = {"bid": 10, "ask": 10.01, "quote_at": clock - timedelta(minutes=2)}
    bars = [make_bar(clock.replace(second=0) - timedelta(minutes=i)) for i in range(5, 0, -1)]
    for b in bars:
        b.volume = 10_000
    orch.detectors["TEST"].bars = bars
    result = await orch.approve_signal(sig.id)
    assert "spread" in result["error"]
    orch.trader.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_polling_independent_symbols_is_concurrent(orch):
    entered = set()
    all_entered = asyncio.Event()

    async def fetch(sym, days):
        entered.add(sym)
        if len(entered) == 2:
            all_entered.set()
        await asyncio.wait_for(all_entered.wait(), 1)
        return []

    orch.broker.minute_bars.side_effect = fetch
    orch.detectors["OTHER"] = SetupDetector("OTHER")
    orch._session_dates["OTHER"] = orch._session_dates["TEST"]
    await asyncio.gather(*(orch._poll_symbol(sym, det) for sym, det in orch.detectors.items()))
    assert all_entered.is_set()
