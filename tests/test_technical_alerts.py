import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import settings
from app.db.technical_alerts import AlertStore, AlertStorageError
from app.engine.technical_alerts import AlertConfig, TechnicalAlerts, evaluate, initial_state, qualification
from app.data.daily_research import ResearchDataError

NOW = datetime(2026, 10, 19, 15, tzinfo=timezone.utc)


def item(symbol='AAPL', direction='bullish'):
    return dict(symbol=symbol, eligible=True, score=70, close=200, direction=direction,
                as_of='2026-10-19', provisional=True, chart_assessment={'available': True},
                current_day={'trade_at': NOW.isoformat(), 'fetched_at': NOW.isoformat()},
                trigger=dict(held=True, kind='price200', time='2026-10-19', label='Price / SMA 200'),
                score_version='daily-v4-volatility', warnings=['IEX only'], breakdown=[])


def state_for(**kwargs):
    state = initial_state()
    state['config'] = AlertConfig(symbols='AAPL MSFT', enabled=True, **kwargs).model_dump()
    return state


class MemoryJournal:
    def __init__(self, state=None):
        self.state = deepcopy(state)

    def read(self):
        return deepcopy(self.state)

    def write(self, state):
        self.state = deepcopy(state)


def test_tickers_and_bounds():
    assert AlertConfig(symbols='aapl, msft; AAPL').symbols == 'AAPL MSFT'
    assert AlertConfig(symbols='  ').symbols == ''
    for config in [dict(symbols='bad!'), dict(enabled=True), dict(minimum_score=49),
                   dict(minimum_score=101), dict(direction='anything'), dict(mode='live')]:
        with pytest.raises(ValidationError):
            AlertConfig(**config)


def test_buy_sell_snapshot_deduplication_and_withdrawal():
    state = state_for()
    rows = [item(), item('MSFT', 'bearish')]
    evaluate(state, rows, NOW)
    assert {a['action'] for a in state['alerts']} == {'BUY', 'SELL'}
    assert all(a['execution'] == 'research_only' for a in state['alerts'])
    evaluate(state, rows, NOW + timedelta(seconds=30))
    assert len(state['alerts']) == 2
    rows[0]['score'] = 55
    evaluate(state, rows, NOW + timedelta(seconds=40))
    alert = next(a for a in state['alerts'] if a['symbol'] == 'AAPL')
    assert alert['status'] == 'Below minimum score' and alert['score'] == 70
    rows[0]['score'] = 75
    evaluate(state, rows, NOW + timedelta(seconds=45))
    assert len(state['alerts']) == 2 and alert['status'] == 'Qualifying'
    rows[0]['trigger']['kind'] = 'ma20_50'
    evaluate(state, rows, NOW + timedelta(seconds=50))
    assert len(state['alerts']) == 3 and alert['status'] == 'Superseded'


@pytest.mark.parametrize('patch,expected', [
    ({'as_of': '2026-10-16'}, 'Current-day data unavailable'),
    ({'provisional': False}, 'Current-day data unavailable'),
    ({'current_day': {'trade_at': '2026-10-19T14:00:00Z', 'fetched_at': NOW.isoformat()}}, 'Current-day quote is stale'),
    ({'current_day': {'trade_at': '2026-10-20T14:00:00Z', 'fetched_at': NOW.isoformat()}}, 'Current-day quote is stale'),
    ({'current_day': {}}, 'Current-day quote is unverified'),
    ({'current_day': {'trade_at': '2026-10-19T15:00:00', 'fetched_at': NOW.isoformat()}}, 'Current-day quote is unverified'),
    ({'chart_assessment': {'available': False}}, 'Insufficient history'),
    ({'eligible': False, 'trigger': None}, 'No qualifying held setup'),
    ({'score': 59}, 'Below minimum score'),
])
def test_unusable_data_and_nonqualifying_charts_cannot_alert(patch, expected):
    row = item() | patch
    state = state_for()
    assert qualification(row, state['config'], NOW) == expected
    evaluate(state, [row], NOW)
    assert not state['alerts']


def test_direction_and_session_filters():
    config = state_for(direction='bullish')['config']
    assert qualification(item(direction='bearish'), config, NOW) == 'Direction filtered'
    assert qualification(item(), config, NOW.replace(hour=21)) == 'Waiting for regular session'


def test_completed_phase_requires_prior_session_and_matching_benchmark():
    state = state_for(mode='completed')
    row = item() | {'provisional': False, 'as_of': '2026-10-16', 'benchmark_aligned': True}
    row['trigger']['time'] = '2026-10-16'
    evaluate(state, [row], NOW)
    assert state['alerts'][0]['phase'] == 'completed'
    for patch in [{'benchmark_aligned': False}, {'as_of': '2026-10-19'}, {'as_of': '2026-10-10'}]:
        assert 'unavailable or stale' in qualification(row | patch, state['config'], NOW)


def test_history_is_bounded_and_seen_keys_survive_feed_retention():
    state = state_for()
    for i in range(505):
        row = item()
        row['trigger']['kind'] = str(i)
        evaluate(state, [row], NOW)
    assert len(state['alerts']) == 500 and len(state['seen']) == 505
    evaluate(state, [item() | {'trigger': dict(item()['trigger'], kind='0')}], NOW)
    assert len(state['alerts']) == 500 and len(state['seen']) == 505


@pytest.mark.asyncio
async def test_journal_restart_revision_conflict_and_read_ids():
    journal = MemoryJournal()
    research = AsyncMock()
    monitor = TechnicalAlerts(research, journal)
    first = await monitor.snapshot()
    assert not first['config']['enabled'] and first['unread'] == 0
    configured = await monitor.configure(AlertConfig(symbols='QQQ', enabled=True), 0)
    assert configured['revision'] == 1
    with pytest.raises(ValueError, match='another window'):
        await monitor.configure(AlertConfig(symbols='SPY'), 0)
    second = TechnicalAlerts(research, journal)
    assert (await second.snapshot())['config']['symbols'] == 'QQQ'
    state = state_for()
    evaluate(state, [item(), item('MSFT', 'bearish')], NOW)
    journal.write(state)
    result = await second.mark_read({state['alerts'][0]['id']})
    assert result['unread'] == 1 and 'seen' not in result
    research.scan.assert_not_called()


@pytest.mark.asyncio
async def test_monitor_failure_and_disable_never_generate_alerts(monkeypatch):
    import app.engine.technical_alerts as module
    monkeypatch.setattr(module, 'market_session', lambda now: 'regular')
    state = state_for()
    evaluate(state, [item()], NOW)
    state['last_checked'] = None
    journal = MemoryJournal(state)
    research = AsyncMock()
    research.scan.side_effect = ResearchDataError('provider failure')
    monitor = TechnicalAlerts(research, journal)
    result = await monitor.check()
    assert result['last_error'] and result['alerts'][0]['status'] == 'Data unavailable; unverified'
    assert len(result['alerts']) == 1
    research.scan.assert_awaited_once_with(['AAPL', 'MSFT'], completed=False)
    await monitor.configure(AlertConfig(symbols='AAPL', enabled=False), 0)
    await monitor.check()
    assert research.scan.await_count == 1


@pytest.mark.asyncio
async def test_background_monitor_cancellation_and_dedup_after_restart(monkeypatch):
    import app.engine.technical_alerts as module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(module, 'datetime', Clock)
    research = AsyncMock()
    research.scan.return_value = {'items': [item()]}
    journal = MemoryJournal(state_for())
    monitor = TechnicalAlerts(research, journal)
    monitor.start()
    for _ in range(100):
        if journal.state['last_checked']:
            break
        await asyncio.sleep(.01)
    await monitor.stop()
    assert len(journal.state['alerts']) == 1
    assert not (await monitor.snapshot())['worker_running']
    journal.state['last_checked'] = None
    restarted = TechnicalAlerts(research, journal)
    await restarted.check()
    assert len(journal.state['alerts']) == 1


def test_sqlite_persistence_and_no_ephemeral_cloud_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, 'supabase_url', '')
    monkeypatch.setattr(settings, 'supabase_key', '')
    monkeypatch.setattr(settings, 'state_db_path', str(tmp_path / 'alerts.sqlite'))
    monkeypatch.delenv('RAILWAY_ENVIRONMENT_ID', raising=False)
    store = AlertStore()
    assert store.read() is None
    store.write(state_for())
    assert AlertStore().read()['config']['symbols'] == 'AAPL MSFT'
    monkeypatch.setenv('RAILWAY_ENVIRONMENT_ID', 'test')
    monkeypatch.delenv('RAILWAY_VOLUME_MOUNT_PATH', raising=False)
    with pytest.raises(AlertStorageError, match='Railway volume'):
        store.read()


def test_alert_api_validation_persistence_and_failures(monkeypatch):
    import app.api.technicals as api
    from app.api.server import app
    monitor = TechnicalAlerts(AsyncMock(), MemoryJournal())
    monkeypatch.setattr(api, 'alerts', monitor)
    client = TestClient(app)
    assert client.get('/api/technicals/alerts').json()['delivery'] == 'in_app'
    response = client.put('/api/technicals/alerts', json={'symbols': 'AAPL, msft', 'enabled': True, 'revision': 0})
    assert response.status_code == 200 and response.json()['config']['symbols'] == 'AAPL MSFT'
    assert client.put('/api/technicals/alerts', json={'symbols': 'NVDA', 'revision': 0}).status_code == 409
    for body in [{'symbols': '<script>', 'revision': 1}, {'symbols': '', 'enabled': True, 'revision': 1},
                 {'symbols': 'AAPL', 'minimum_score': 101, 'revision': 1}]:
        assert client.put('/api/technicals/alerts', json=body).status_code == 422
    monkeypatch.setattr(monitor, 'snapshot', AsyncMock(side_effect=AlertStorageError('storage unavailable')))
    assert client.get('/api/technicals/alerts').status_code == 503


@pytest.mark.asyncio
async def test_pause_during_check_discards_result_without_blocking(monkeypatch):
    import app.engine.technical_alerts as module
    monkeypatch.setattr(module, 'market_session', lambda now: 'regular')
    entered, release = asyncio.Event(), asyncio.Event()

    async def scan(*args, **kwargs):
        entered.set()
        await release.wait()
        return {'items': [item()]}

    research = AsyncMock()
    research.scan.side_effect = scan
    journal = MemoryJournal(state_for())
    monitor = TechnicalAlerts(research, journal)
    checking = asyncio.create_task(monitor.check())
    await entered.wait()
    await asyncio.wait_for(monitor.snapshot(), timeout=1)
    # A second check does not start another provider request.
    await asyncio.wait_for(monitor.check(), timeout=1)
    assert research.scan.await_count == 1
    await asyncio.wait_for(monitor.configure(AlertConfig(symbols='AAPL', enabled=False), 0), timeout=1)
    release.set()
    result = await checking
    assert not result['config']['enabled'] and not result['alerts'] and result['last_checked'] is None


@pytest.mark.asyncio
async def test_write_failure_does_not_claim_configuration_saved():
    journal = MemoryJournal()

    def fail(state):
        raise AlertStorageError('Write failed')

    journal.write = fail
    monitor = TechnicalAlerts(AsyncMock(), journal)
    with pytest.raises(AlertStorageError):
        await monitor.configure(AlertConfig(symbols='AAPL', enabled=True), 0)
    assert not (await monitor.snapshot())['config']['enabled']


def test_completion_is_distinct_from_provisional_but_removal_stops_monitoring():
    state = state_for()
    row = item()
    row['trigger']['time'] = '2026-10-16'
    evaluate(state, [row], NOW)
    state['config']['mode'] = 'completed'
    row.update(as_of='2026-10-16', provisional=False, benchmark_aligned=True)
    evaluate(state, [row], NOW)
    assert {alert['phase'] for alert in state['alerts']} == {'completed', 'provisional'}
    assert len(state['alerts']) == 2
    state['config']['symbols'] = 'MSFT'
    evaluate(state, [], NOW)
    assert all(alert['status'] == 'Not monitored' for alert in state['alerts'])
