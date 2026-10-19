"""Persistent technical research alerts. No broker or order-placement dependencies."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.data.daily_research import ET, ResearchDataError, symbols_from_text
from app.data.market_hours import market_session
from app.db.technical_alerts import AlertStore


class AlertConfig(BaseModel):
    symbols: str = Field(default='', max_length=1000)
    enabled: bool = False
    minimum_score: int = Field(default=60, ge=50, le=100)
    direction: Literal['both', 'bullish', 'bearish'] = 'both'
    mode: Literal['intraday', 'completed'] = 'intraday'

    @model_validator(mode='after')
    def validate_symbols(self):
        self.symbols = ' '.join(symbols_from_text(self.symbols)) if self.symbols.strip() else ''
        if self.enabled and not self.symbols:
            raise ValueError('Add at least one ticker before enabling alerts.')
        return self


def initial_state():
    return dict(config=AlertConfig().model_dump(), alerts=[], seen={}, last_checked=None,
                last_error=None, coverage=[], revision=0)


def qualification(item, config, now):
    """Reject stale/missing data before evaluating the existing setup score."""
    today = now.astimezone(ET).date()
    if config['mode'] == 'intraday':
        current = item.get('current_day') or {}
        if market_session(now) != 'regular':
            return 'Waiting for regular session'
        if not item.get('provisional') or item.get('as_of') != today.isoformat():
            return 'Current-day data unavailable'
        try:
            trade = datetime.fromisoformat(current['trade_at'].replace('Z', '+00:00'))
            fetched = datetime.fromisoformat(current['fetched_at'].replace('Z', '+00:00'))
            if not 0 <= (now - trade).total_seconds() <= 900 or not 0 <= (now - fetched).total_seconds() <= 120:
                return 'Current-day quote is stale'
        except (KeyError, TypeError, ValueError):
            return 'Current-day quote is unverified'
    else:
        try:
            age = (today - date.fromisoformat(item['as_of'])).days
            if not 1 <= age <= 5 or not item.get('benchmark_aligned'):
                return 'Completed-session data unavailable or stale'
        except (KeyError, TypeError, ValueError):
            return 'Completed-session data unavailable or stale'
    if not item.get('chart_assessment', {}).get('available'):
        return 'Insufficient history'
    if not item.get('eligible') or not item.get('trigger', {}).get('held'):
        return 'No qualifying held setup'
    if config['direction'] != 'both' and item['direction'] != config['direction']:
        return 'Direction filtered'
    if item['score'] < config['minimum_score']:
        return 'Below minimum score'
    return 'Qualifying'


def evaluate(state, items, now):
    config = state['config']
    phase = 'provisional' if config['mode'] == 'intraday' else 'completed'
    timestamp = now.isoformat()
    coverage = []
    active = set()
    by_symbol = {item['symbol']: item for item in items}
    for symbol in config['symbols'].split():
        item = by_symbol.get(symbol)
        status = qualification(item, config, now) if item else 'Data unavailable'
        coverage.append(dict(symbol=symbol, status=status, score=item.get('score') if item else None))
        if status != 'Qualifying':
            continue
        trigger = item['trigger']
        # Stable per trigger and phase, not per polling minute or price fluctuation.
        identity = '|'.join([symbol, item['direction'], trigger['kind'], trigger['time'], phase, item['score_version']])
        key = sha256(identity.encode()).hexdigest()[:24]
        active.add(key)
        if key in state['seen']:
            continue
        state['seen'][key] = now.astimezone(ET).date().isoformat()
        state['alerts'].insert(0, dict(id=key, symbol=symbol, action='BUY' if item['direction'] == 'bullish' else 'SELL',
            direction=item['direction'], score=item['score'], price=item['close'], as_of=item['as_of'],
            phase=phase, trigger=deepcopy(trigger), score_version=item['score_version'],
            created_at=timestamp, read=False, status='Qualifying', warnings=item.get('warnings', []),
            next_earnings=item.get('next_earnings'), breakdown=item.get('breakdown', []), execution='research_only'))
    statuses = {row['symbol']: row['status'] for row in coverage}
    for alert in state['alerts']:
        if alert['id'] in active:
            alert['status'] = 'Qualifying'
        elif alert['symbol'] not in statuses:
            alert['status'] = 'Not monitored'
        elif alert['phase'] != phase:
            alert['status'] = 'Historical snapshot'
        else:
            status = statuses[alert['symbol']]
            alert['status'] = 'Superseded' if status == 'Qualifying' else status
    state['alerts'] = state['alerts'][:500]
    # Trigger eligibility lasts only 10 sessions; preserve deduplication well beyond it.
    state['seen'] = {key: day for key, day in state['seen'].items()
                     if (now.astimezone(ET).date() - date.fromisoformat(day)).days <= 90}
    state.update(last_checked=timestamp, last_error=None, coverage=coverage)
    return state


class TechnicalAlerts:
    def __init__(self, research, store=None):
        self.research = research
        self.store = store or AlertStore()
        self.lock = asyncio.Lock()
        self.check_lock = asyncio.Lock()
        self.task = None
        self.error = None

    async def _read(self):
        return await asyncio.to_thread(self.store.read) or initial_state()

    def public(self, state):
        return {key: value for key, value in state.items() if key != 'seen'} | {
            'worker_running': self.task is not None and not self.task.done(),
            'last_error': self.error or state['last_error'],
            'unread': sum(not row['read'] for row in state['alerts']), 'interval_seconds': 60,
            'delivery': 'in_app', 'execution': 'research_only'}

    async def snapshot(self):
        async with self.lock:
            return self.public(await self._read())

    async def configure(self, config, revision):
        async with self.lock:
            state = await self._read()
            if revision != state['revision']:
                raise ValueError('Watchlist changed in another window. Reopen alerts before saving.')
            state['config'] = config.model_dump()
            state['revision'] += 1
            state['coverage'] = []
            state['last_checked'] = None
            state['last_error'] = None
            for alert in state['alerts']:
                alert['status'] = 'Awaiting check' if config.enabled else 'Monitoring paused'
            await asyncio.to_thread(self.store.write, state)
            self.error = None
            return self.public(state)

    async def mark_read(self, ids):
        async with self.lock:
            state = await self._read()
            for alert in state['alerts']:
                if alert['id'] in ids:
                    alert['read'] = True
            await asyncio.to_thread(self.store.write, state)
            return self.public(state)

    async def check(self):
        if self.check_lock.locked():
            return await self.snapshot()
        async with self.check_lock:
            async with self.lock:
                state = await self._read()
            if not state['config']['enabled']:
                return self.public(state)
            now = datetime.now(timezone.utc)
            if state['last_checked'] and (now - datetime.fromisoformat(state['last_checked'])).total_seconds() < 45:
                return self.public(state)
            config = state['config']
            waiting = config['mode'] == 'intraday' and market_session(now) != 'regular'
            error = None
            items = []
            try:
                if not waiting:
                    result = await asyncio.wait_for(self.research.scan(config['symbols'].split(),
                        completed=config['mode'] == 'completed'), timeout=120)
                    items = result['items']
            except (ResearchDataError, TimeoutError):
                error = 'Market data unavailable; no new alerts generated.'
            async with self.lock:
                latest = await self._read()
                # Discard an in-flight result after a pause/list/rule change, and
                # preserve read-state edits made while the provider was working.
                if latest['revision'] != state['revision']:
                    return self.public(latest)
                now = datetime.now(timezone.utc)
                if error:
                    latest.update(last_checked=now.isoformat(), last_error=error, coverage=[])
                    for alert in latest['alerts']:
                        alert['status'] = 'Data unavailable; unverified'
                else:
                    evaluate(latest, items, now)
                    if waiting:
                        for row in latest['coverage']:
                            row['status'] = 'Waiting for regular session'
                        for alert in latest['alerts']:
                            if alert['symbol'] in config['symbols'].split():
                                alert['status'] = 'Waiting for regular session'
                await asyncio.to_thread(self.store.write, latest)
                self.error = None
                return self.public(latest)

    def start(self):
        self.task = asyncio.create_task(self._run(), name='technical-alerts')

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None

    async def _run(self):
        while True:
            try:
                await self.check()
            except Exception:
                self.error = 'Alert monitor unavailable; check storage and data connections.'
            await asyncio.sleep(60)
