from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest

from app.config import settings
from app.data.daily_research import ET
from app.db.daily_outcomes import OutcomeStore
from app.engine import daily_outcomes as study


def item(sym='ABC', side='bullish'):
    return dict(symbol=sym, as_of='2026-11-06', eligible=True, trigger=dict(kind='range20', time='2026-11-05'),
                direction=side, provisional=False, benchmark_aligned=True, score=72, readiness=dict(status='wait'))


def cohort():
    now = datetime(2026, 11, 7, 10, tzinfo=ET)
    rows = [item(), dict(item('XYZ', 'bearish'), score=55), dict(item('MISS'), score=49),
            dict(item('PROV'), provisional=True), dict(item('OLD'), benchmark_aligned=False)]
    return study.snapshot(rows, dict(symbols=[r['symbol'] for r in rows], as_of='2026-11-06'), '2026-11-06', now, set())


def test_forward_sessions_direction_pending_missing_and_comparison():
    c = cohort()
    assert len(c['rows']) == 3
    spy = [dict(time=f'2026-11-{d:02}', open=100, close=102) for d in (6, 9, 10, 11, 12, 13)]
    stock = [dict(b, close=110) for b in spy]
    assert study.measure(c, spy[:-1], {}, 5) is None
    result = study.measure(c, spy, dict(ABC=stock, XYZ=stock, MISS=stock[:-1]), 5)
    records = {'2026-11-06': c, '2026-11-06/5': result}
    assert result['entry'] == '2026-11-09' and result['end'] == '2026-11-13'
    groups = study.summarize(records, 5, 'both')['groups']
    assert groups[3]['mean_excess'] == 8 and groups[1]['mean_excess'] == -8
    assert groups[0]['missing'] == 1 and groups[0]['mean_excess'] is None
    assert study.summarize(records, 5, 'bullish')['groups'][1]['matured'] == 0
    assert study.summarize(records, 5, 'both', 'conditional')['groups'][3]['matured'] == 0
    assert study.summarize(records, 20, 'both')['groups'][3]['pending'] == 1
    assert all(v is None for v in study.measure(dict(c, captured='2026-11-10T05:00'), spy, dict(ABC=stock), 5)['results'].values())


@pytest.mark.asyncio
async def test_worker_dedupes_restarts_and_repeated_held_events(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'state_db_path', str(tmp_path / 'outcomes.db'))
    monkeypatch.setattr(settings, 'supabase_url', '')
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_ID', raising=False)
    class Clock(datetime):
        day = 7

        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, cls.day, 6, tzinfo=ET)

    monkeypatch.setattr(study, 'datetime', Clock)
    research = Mock()
    research.histories = AsyncMock(return_value={'SPY': [dict(time='2026-11-06')]})
    research.scan = AsyncMock(return_value={'items': [item()]})
    universe = Mock(get=AsyncMock(return_value=dict(as_of='2026-11-06', symbols=['ABC'])))
    worker = study.DailyOutcomes(research, universe)
    await worker.collect()
    worker = study.DailyOutcomes(research, universe, OutcomeStore())
    await worker.collect()
    research.scan.assert_awaited_once()
    Clock.day = 10
    research.histories.return_value = {'SPY': [dict(time='2026-11-09')]}
    research.scan.return_value = {'items': [dict(item(), as_of='2026-11-09')]}
    await worker.collect()
    report = await worker.report(5, 'both')
    assert report['sessions'] == 2 and report['groups'][3]['pending'] == 1
    worker.store.insert(worker.prefix + '2026-11-06', {'wrong': True})
    assert (await worker.records(Clock.now()))['2026-11-06']['rows'][0]['plan'] == 'wait'
