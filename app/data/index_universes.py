"""Dated, issuer-sourced technical scan universes (not alert watchlists)."""
import asyncio
import csv
from datetime import datetime
from io import StringIO
import re
from time import monotonic

import httpx

from app.data.daily_research import ResearchDataError
from app.data.market_hours import trading_date


SOURCES = {
    'nasdaq100': ('Nasdaq-100 (QQQ)', 'https://api.nasdaq.com/api/quote/list-type/nasdaq100'),
    'sp500': ('S&P 500 (IVV holdings)', 'https://www.ishares.com/us/products/239726/ishares-core-sp-500-etf/latest-holdings.csv'),
}


def membership(key, response, today):
    name, url = SOURCES[key]
    if key == 'nasdaq100':
        payload = response.json()['data']
        rows = payload['data']['rows']
        symbols = [r['symbol'].strip().upper() for r in rows]
        if len(rows) != int(payload['totalrecords']) or not 100 <= len(rows) <= 110:
            raise ValueError('Incomplete Nasdaq-100 membership.')
        day = datetime.strptime(payload['date'], '%b %d, %Y').date()
    else:
        rows = list(csv.reader(StringIO(response.text.lstrip('\ufeff'))))
        if not rows or rows[0] != ['iShares Core S&P 500 ETF']:
            raise ValueError('Unexpected IVV holdings document.')
        date_row = next(r for r in rows[:30] if r and r[0] == 'Fund Holdings as of')
        day = datetime.strptime(date_row[1], '%b %d, %Y').date()
        header = next(i for i,r in enumerate(rows[:30]) if {'Ticker', 'Asset Class'}.issubset(r))
        fields = rows[header]
        weight_col = next(k for k in ('Market Weight', 'Weight (%)') if k in fields)
        symbols, total = [], 0.
        for row in rows[header+1:]:
            if len(row) != len(fields):
                continue
            item = dict(zip(fields, row))
            if item['Asset Class'].strip() != 'Equity' or item[weight_col].strip() in ('-', ''):
                continue
            symbol = re.sub(r'^([A-Z]+)[ /-]([A-Z])$', r'\1.\2', item['Ticker'].strip().upper())
            symbols.append(symbol)
            total += float(item[weight_col])
        if not 495 <= len(symbols) <= 515 or not 97 <= total <= 102:
            raise ValueError('Incomplete IVV equity holdings.')
    if len(set(symbols)) != len(symbols) or not all(re.fullmatch(r'[A-Z]{1,5}(?:[.-][A-Z])?', s) for s in symbols):
        raise ValueError('Unexpected or duplicate equity ticker.')
    if not 0 <= (today - day).days <= 7:
        raise ValueError('Membership date is stale or future-dated.')
    return dict(key=key, name=name, source=url, as_of=day.isoformat(), symbols=sorted(symbols))


class IndexUniverses:
    def __init__(self, http):
        self.http = http
        self.cache = {}
        self.locks = {key: asyncio.Lock() for key in SOURCES}

    async def get(self, key):
        async with self.locks[key]:
            cached = self.cache.get(key)
            today = trading_date()
            if cached and cached[0] == today and monotonic() < cached[1]:
                return cached[2]
            try:
                response = await self.http.get(SOURCES[key][1], follow_redirects=True, timeout=12,
                                               headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('Membership response too large.')
                result = membership(key, response, today)
            except (KeyError, IndexError, TypeError, AttributeError, StopIteration, ValueError, csv.Error, httpx.HTTPError):
                raise ResearchDataError(f'{SOURCES[key][0]} membership unavailable or incomplete. Retry or select another universe.') from None
            self.cache[key] = (today, monotonic() + 3600, result)
            return result
