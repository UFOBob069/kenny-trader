"""Read-only, bounded market-data client, independent of broker/order connections."""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from datetime import date, datetime, timedelta, timezone
import math
import re
from time import monotonic
from zoneinfo import ZoneInfo

import httpx

from app.config import settings
from app.engine.technicals import analyze, chart_payload
from app.engine.trade_plan import daily_trade_plan
from app.data.market_hours import market_session

ET = ZoneInfo('America/New_York')
DEFAULT_SYMBOLS = 'AAPL MSFT NVDA AMZN GOOGL META TSLA AVGO AMD INTC QCOM MU ARM SMCI PLTR ORCL CRM ADBE NOW SHOP UBER NFLX DIS JPM BAC GS MS V MA PYPL COIN HOOD XOM CVX COP SLB CAT DE GE BA LMT COST WMT TGT HD LOW NKE SBUX MCD LLY UNH JNJ ABBV MRK PFE AMGN GILD NEM FCX F GM SOFI'.split()


class ResearchDataError(Exception):
    pass


def symbols_from_text(value: str) -> list[str]:
    symbols = list(dict.fromkeys(re.split(r'[\s,;]+', value.strip().upper())))
    if not symbols or symbols == [''] or len(symbols) > 100:
        raise ValueError('Choose 1 to 100 ticker symbols.')
    if any(not re.fullmatch(r'[A-Z]{1,5}(?:[.-][A-Z])?', s) for s in symbols):
        raise ValueError('Use ticker symbols separated by spaces or commas.')
    return symbols


def normalize_bars(rows: list[dict], today: date, include_current=False) -> list[dict]:
    result = {}
    for row in rows:
        try:
            if not isinstance(row, dict) or not isinstance(row.get('t'), str):
                continue
            timestamp = datetime.fromisoformat(row['t'].replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                continue
            day = timestamp.astimezone(ET).date()
            values = [float(row[k]) for k in ('o', 'h', 'l', 'c', 'v')]
            o, h, low, c, v = values
            if day > today or (day == today and not include_current) or not all(math.isfinite(x) for x in values):
                continue
            if min(o, h, low, c) <= 0 or v < 0 or low > min(o, c) or h < max(o, c) or low > h:
                continue
            try:
                vw = float(row['vw']) if row.get('vw') is not None else None
            except (TypeError, ValueError):
                vw = None
            if vw is not None and (not math.isfinite(vw) or not low <= vw <= h):
                vw = None
            result[day.isoformat()] = dict(time=day.isoformat(), open=o, high=h, low=low, close=c, volume=v, vwap=vw)
        except (KeyError, ValueError, TypeError):
            continue
    return [result[key] for key in sorted(result)]


class DailyResearch:
    def __init__(self):
        self.http = httpx.AsyncClient(timeout=25)
        self._cache: OrderedDict = OrderedDict()
        self._bars_lock = asyncio.Lock()
        self._earnings_lock = asyncio.Lock()
        self._snapshot_lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    def _cached(self, key):
        item = self._cache.get(key)
        if item and monotonic() < item[0]:
            self._cache.move_to_end(key)
            return item[1]
        return None

    def _save(self, key, value, ttl=900):
        self._cache[key] = (monotonic() + ttl, value)
        self._cache.move_to_end(key)
        while len(self._cache) > 300:
            self._cache.popitem(last=False)

    async def _get(self, url, **kwargs):
        try:
            response = await self.http.get(url, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            reason = {401: 'credentials rejected', 403: 'subscription or feed access denied',
                      429: 'rate limit reached; retry later'}.get(status, f'HTTP {status}')
            # Never include a Finnhub token-bearing URL in exceptions or logs.
            raise ResearchDataError(f'Market-data provider: {reason}.') from None
        except (httpx.RequestError, ValueError):
            raise ResearchDataError('Market-data provider unavailable or returned invalid data.') from None

    async def histories(self, symbols: list[str], today: date) -> dict[str, list]:
        if not settings.alpaca_api_key or not settings.alpaca_secret_key:
            raise ResearchDataError('Daily history needs ALPACA_API_KEY and ALPACA_SECRET_KEY on the server.')
        feed = settings.alpaca_data_feed.lower()
        async with self._bars_lock:
            result = {s: self._cached(('bars', s, today, feed)) for s in symbols}
            missing = [s for s in symbols if result[s] is None]
            for offset in range(0, len(missing), 10):
                batch = missing[offset:offset + 10]
                rows = {s: [] for s in batch}
                params = dict(symbols=','.join(batch), timeframe='1Day', adjustment='split', feed=feed,
                              start=(today - timedelta(days=6 * 366)).isoformat(), end=today.isoformat(),
                              limit=10000, sort='asc')
                seen_tokens = set()
                while True:
                    payload = await self._get('https://data.alpaca.markets/v2/stocks/bars', params=params,
                                              headers={'APCA-API-KEY-ID': settings.alpaca_api_key,
                                                       'APCA-API-SECRET-KEY': settings.alpaca_secret_key})
                    if not isinstance(payload, dict) or not isinstance(payload.get('bars'), dict):
                        raise ResearchDataError('Daily history response was incomplete.')
                    for symbol in batch:
                        rows[symbol].extend(payload['bars'].get(symbol) or [])
                    token = payload.get('next_page_token')
                    if not token:
                        break
                    if token in seen_tokens or len(seen_tokens) >= 50:
                        raise ResearchDataError('Daily history pagination did not complete.')
                    seen_tokens.add(token)
                    params['page_token'] = token
                for symbol in batch:
                    result[symbol] = normalize_bars(rows[symbol], today)
                    self._save(('bars', symbol, today, feed), result[symbol], 900 if result[symbol] else 60)
            return result

    async def current_histories(self, symbols: list[str], today: date):
        """Merge only today's snapshot bar into split-adjusted cached history."""
        history = await self.histories(symbols, today)
        feed = settings.alpaca_data_feed.lower()
        async with self._snapshot_lock:
            snapshots = {s: self._cached(('snapshot', s, today, feed)) for s in symbols}
            missing = [s for s in symbols if snapshots[s] is None]
            for offset in range(0, len(missing), 100):
                batch = missing[offset:offset + 100]
                fetched_at = datetime.now(timezone.utc).isoformat()
                error = None
                try:
                    payload = await self._get('https://data.alpaca.markets/v2/stocks/snapshots',
                        params={'symbols': ','.join(batch), 'feed': feed},
                        headers={'APCA-API-KEY-ID': settings.alpaca_api_key,
                                 'APCA-API-SECRET-KEY': settings.alpaca_secret_key})
                    if not isinstance(payload, dict):
                        raise ResearchDataError('Current-day snapshot response was incomplete.')
                except ResearchDataError as exc:
                    error, payload = str(exc), {}
                for symbol in batch:
                    item = payload.get(symbol) or {}
                    item = item if isinstance(item, dict) else {}
                    raw = item.get('dailyBar')
                    parsed = normalize_bars([raw], today, include_current=True) if isinstance(raw, dict) else []
                    bar = next((b for b in parsed if b['time'] == today.isoformat()), None)
                    latest_trade = item.get('latestTrade') or {}
                    trade_at = latest_trade.get('t') if isinstance(latest_trade, dict) else None
                    message = error or ("Today's candle is provisional; price, volume and signals can change."
                                        if bar else 'No current-day bar returned by the selected feed; showing prior history.')
                    value = dict(bar=bar, status='unavailable' if error else 'provisional' if bar else 'not_returned',
                                 fetched_at=fetched_at, trade_at=trade_at, date=today.isoformat(), message=message)
                    snapshots[symbol] = value
                    self._save(('snapshot', symbol, today, feed), value, 30)
        merged = {s: [*history[s], *([snapshots[s]['bar']] if snapshots[s]['bar'] else [])] for s in symbols}
        metadata = {s: {k: v for k, v in snapshots[s].items() if k != 'bar'} for s in symbols}
        return merged, metadata

    @staticmethod
    def current_context(summary, metadata):
        summary['current_day'] = metadata
        summary['provisional'] = metadata['status'] == 'provisional'
        summary['warnings'].append(metadata['message'])
        if summary['provisional']:
            summary['warnings'].append('Current-day volume is partial and not adjusted for time of day.')
        elif metadata['status'] == 'unavailable' or market_session() in ('regular', 'post'):
            summary['eligible'] = False
            summary['warnings'].append('Current-day data missing; excluded from ranked signals until refreshed.')
        for event in summary.get('signals', []):
            event['provisional'] = event['time'] == metadata['date']
        if summary.get('trigger'):
            summary['trigger']['provisional'] = summary['trigger']['time'] == metadata['date']
        return summary

    async def earnings(self, symbol: str | None, start: date, end: date) -> dict:
        key = ('earnings', symbol, start, end)
        cached = self._cached(key)
        if cached is not None:
            return cached
        if not settings.finnhub_api_key:
            return dict(events=[], status='unavailable', message='Finnhub earnings calendar is not configured.')
        async with self._earnings_lock:
            cached = self._cached(key)
            if cached is not None:
                return cached
            result = {}
            failures = 0
            cursor = start
            while cursor <= end:
                # Narrow windows avoid provider truncation of wide market-wide calendars.
                stop = min(end, cursor + timedelta(days=365 if symbol else 6))
                params = {'from': cursor.isoformat(), 'to': stop.isoformat(), 'token': settings.finnhub_api_key}
                if symbol:
                    params['symbol'] = symbol
                try:
                    payload = await self._get('https://finnhub.io/api/v1/calendar/earnings', params=params)
                    if not isinstance(payload, dict) or not isinstance(payload.get('earningsCalendar'), list):
                        raise ResearchDataError('Earnings response unavailable.')
                    rows = payload['earningsCalendar']
                    if len(rows) >= 1500:
                        failures += 1
                    for row in rows:
                        try:
                            day = date.fromisoformat(row['date'])
                            ticker = str(row['symbol']).upper()
                            if not start <= day <= end or (symbol and ticker != symbol):
                                continue
                            event = dict(date=day.isoformat(), symbol=ticker,
                                         hour=row.get('hour') or 'unknown',
                                         status='scheduled' if day >= datetime.now(ET).date() else 'historical')
                            result[(ticker, day)] = event
                        except (KeyError, ValueError, TypeError):
                            continue
                except ResearchDataError:
                    failures += 1
                cursor = stop + timedelta(days=1)
            status = 'partial' if failures and result else 'unavailable' if failures else 'available'
            value = dict(events=sorted(result.values(), key=lambda e: e['date']), status=status,
                         message='Dates as supplied by Finnhub; coverage and scheduled dates may change.' if not failures
                         else 'Some earnings dates could not be retrieved; coverage is incomplete.')
            self._save(key, value, 3600 if not failures else 60)
            return value

    async def scan(self, symbols: list[str], completed=False) -> dict:
        today = datetime.now(ET).date()
        universe = list(dict.fromkeys([*symbols, 'SPY']))
        if completed:
            histories = await self.histories(universe, today)
        else:
            histories, current = await self.current_histories(universe, today)
        calendar = await self.earnings(None, today, today + timedelta(days=30))
        benchmark = histories.get('SPY', [])
        items = []
        for symbol in symbols:
            dates = [e for e in calendar['events'] if e['symbol'] == symbol]
            item = await asyncio.to_thread(analyze, symbol, histories[symbol], benchmark, today,
                                           dates if calendar['status'] == 'available' else None)
            if completed:
                item['provisional'] = False
                item['benchmark_aligned'] = bool(benchmark and item['as_of'] == benchmark[-1]['time'])
                item['warnings'].append('Completed-session alert uses prior daily history, available from the next calendar day.')
                items.append(item)
            else:
                items.append(self.current_context(item, current[symbol]))
        items.sort(key=lambda i: (i['eligible'], i['score']), reverse=True)
        return dict(items=items, symbols=symbols, generated_at=datetime.now(timezone.utc).isoformat(),
                    feed=settings.alpaca_data_feed, earnings_status=calendar['status'], score_version='daily-v4-volatility',
                    current_day_count=sum(i['provisional'] for i in items), refresh_seconds=60,
                    review_date=max((i['as_of'] for i in items if i['as_of']), default=today.isoformat()))

    async def chart(self, symbol: str, years: int, anchor='swing_high', anchor_date=None) -> dict:
        today = datetime.now(ET).date()
        histories, current = await self.current_histories(list(dict.fromkeys([symbol, 'SPY'])), today)
        bars = histories[symbol]
        if not bars:
            raise ResearchDataError(f'No daily bars returned for {symbol} on the configured feed.')
        calendar = await self.earnings(None, today, today + timedelta(days=30))
        dates = [e for e in calendar['events'] if e['symbol'] == symbol]
        summary = await asyncio.to_thread(analyze, symbol, bars, histories['SPY'], today,
                                          dates if calendar['status'] == 'available' else None)
        self.current_context(summary, current[symbol])
        past_earnings = None
        if anchor == 'earnings':
            past = await self.earnings(symbol, today - timedelta(days=366), today)
            past_earnings = past['events']
        payload = await asyncio.to_thread(chart_payload, bars, years, today, anchor, anchor_date, past_earnings)
        if anchor == 'earnings':
            payload['avwap']['calendar_status'] = past['status']
        plan = daily_trade_plan(summary, bars, today)
        plan['provisional'] = summary['provisional']
        if summary['provisional']:
            plan['warnings'].append("Intraday plan: today's candle and these levels are provisional, not close-confirmed.")
            plan['validity'] = 'Recalculate on each refresh; current-day levels can move before the close.'
        elif current[symbol]['status'] == 'unavailable' or market_session() in ('pre', 'regular', 'post'):
            plan = dict(version='daily-plan-v1', status='unavailable', execution='research_only',
                        direction=summary['direction'], as_of=summary['as_of'], reasons=[current[symbol]['message']], warnings=[])
        for event in payload['events']:
            event['provisional'] = event['time'] == today.isoformat()
        return dict(**payload, summary=summary, trade_plan=plan, symbol=symbol, years=years,
                    current_day=current[symbol], refresh_seconds=60,
                    feed=settings.alpaca_data_feed, adjustment='split', interval='1D')
