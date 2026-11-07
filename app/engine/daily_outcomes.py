"""Forward-only Nasdaq-100 signal study. No broker, fills, or retrospective scores."""
import asyncio
from contextlib import suppress
from datetime import date, datetime, time, timedelta
import logging

from app.config import settings
from app.data.daily_research import ET
from app.db.daily_outcomes import OutcomeStore
from app.engine.technicals import SCORE_VERSION


HORIZONS = (5, 20)
BANDS = ('Below 50', '50-59', '60-69', '70+')
log = logging.getLogger(__name__)


def snapshot(items, membership, session, now, seen):
    rows = []
    for item in items:
        trigger = item.get('trigger')
        if not (item['eligible'] and trigger and not item['provisional'] and
                item['as_of'] == session and item['benchmark_aligned']):
            continue
        episode = '|'.join((item['symbol'], item['direction'], trigger['kind'], trigger['time']))
        if episode not in seen:
            rows.append(dict(episode=episode, symbol=item['symbol'], direction=item['direction'],
                             score=item['score'], plan=item['readiness']['status'],
                             blockers=item['readiness'].get('reasons', [])))
    return dict(as_of=session, captured=now.isoformat(), membership_as_of=membership['as_of'],
                requested=len(membership['symbols']), rows=rows)


def measure(cohort, benchmark, histories, horizon):
    future = [b for b in benchmark if b['time'] > cohort['as_of']]
    if len(future) < horizon:
        return None
    entry, end = future[0], future[horizon - 1]
    results = {}
    for row in cohort['rows']:
        bars = {b['time']: b for b in histories.get(row['symbol'], [])}
        value = None
        # Both endpoints must be the same actual SPY sessions, after capture.
        if (entry['time'] >= cohort['captured'][:10] and entry['time'] in bars and end['time'] in bars):
            stock = bars[end['time']]['close'] / bars[entry['time']]['open']
            spy = end['close'] / entry['open']
            value = round((stock - spy) * (100 if row['direction'] == 'bullish' else -100), 4)
        results[row['episode']] = value
    return dict(entry=entry['time'], end=end['time'], results=results)


def summarize(records, horizon, direction, plan='all'):
    groups = {b: dict(band=b, matured=0, pending=0, missing=0, mean_excess=None) for b in BANDS}
    totals = [0.] * len(BANDS)
    dates = sorted(k for k in records if '/' not in k)
    for day in dates:
        result = records.get(f'{day}/{horizon}')
        for r in records[day]['rows']:
            if direction != 'both' and r['direction'] != direction:
                continue
            if plan != 'all' and r['plan'] != plan:
                continue
            idx = sum(r['score'] >= v for v in (50, 60, 70))
            group = groups[BANDS[idx]]
            if result is None:
                group['pending'] += 1
            elif (value := result['results'].get(r['episode'])) is None:
                group['missing'] += 1
            else:
                group['matured'] += 1
                totals[idx] += value
    for i, group in enumerate(groups.values()):
        if group['matured']:
            group['mean_excess'] = round(totals[i] / group['matured'], 2)
    return dict(groups=list(groups.values()), sessions=len(dates), latest=dates[-1] if dates else None,
                version=SCORE_VERSION, feed=settings.alpaca_data_feed, horizon=horizon)


class DailyOutcomes:
    def __init__(self, research, universes, store=None):
        self.research, self.universes = research, universes
        self.store = store or OutcomeStore()
        self.task = None
        self.status = 'Awaiting collection window'

    @property
    def prefix(self):
        return f'daily.study.v1.{SCORE_VERSION}.{settings.alpaca_data_feed}.'

    async def records(self, now):
        since = (now.date() - timedelta(days=119)).isoformat()
        return await asyncio.to_thread(self.store.records, self.prefix, since)

    async def report(self, horizon, direction, plan='all'):
        data = summarize(await self.records(datetime.now(ET)), horizon, direction, plan)
        return dict(**data, status=self.status)

    async def collect(self):
        now = datetime.now(ET)
        records = await self.records(now)
        today = now.date()
        spy = (await self.research.histories(['SPY'], today))['SPY']
        if not spy:
            raise ValueError('Benchmark missing')
        day = spy[-1]['time']
        if (today - date.fromisoformat(day)).days > 5:
            raise ValueError('Stale benchmark')
        if day not in records and (now.weekday() >= 5 or now.time() < time(9, 15)):
            membership = await self.universes.get('nasdaq100')
            symbols = membership['symbols']
            items = []
            for i in range(0, len(symbols), 25):
                batch = await self.research.scan(symbols[i:i+25], completed=True)
                items.extend(batch['items'])
            stamp = datetime.now(ET)
            if stamp.date() == today and (stamp.weekday() >= 5 or stamp.time() < time(9, 30)):
                seen = {r['episode'] for k, c in records.items() if '/' not in k for r in c['rows']}
                cohort = snapshot(items, membership, day, stamp, seen)
                await asyncio.to_thread(self.store.insert, self.prefix + day, cohort)
        for key, cohort in records.items():
            if '/' in key:
                continue
            due = [h for h in HORIZONS if f'{key}/{h}' not in records and
                   sum(b['time'] > key for b in spy) >= h]
            if due:
                symbols = list({r['symbol'] for r in cohort['rows']})
                histories = await self.research.histories(symbols, today)
                for h in due:
                    result = measure(cohort, spy, histories, h)
                    await asyncio.to_thread(self.store.insert, self.prefix + f'{key}/{h}', result)

    async def run(self):
        while True:
            try:
                if settings.alpaca_api_key and settings.alpaca_secret_key:
                    await self.collect()
                    self.status = 'Monitoring'
                else:
                    self.status = 'Market data not configured'
            except Exception as exc:
                log.warning('Daily outcome collection unavailable: %s', type(exc).__name__)
                self.status = 'Collection interrupted; retrying'
            await asyncio.sleep(1800)

    def start(self):
        self.task = asyncio.create_task(self.run(), name='daily-outcomes')

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
