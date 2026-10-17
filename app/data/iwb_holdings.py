"""Dated issuer holdings for the existing IWB/Russell 1000 proxy filter."""
from __future__ import annotations

import asyncio
import csv
from datetime import date, datetime
from io import StringIO
from time import monotonic

import httpx

from app.data.market_hours import trading_date
from app.data.symbol_filter import is_common_ticker

HOLDINGS_URL = 'https://www.ishares.com/us/products/239707/ishares-russell-1000-etf/latest-holdings.csv'
MAX_AGE_DAYS = 5


def parse_holdings(body: str, today: date) -> tuple[set[str], date]:
    rows = list(csv.reader(StringIO(body.lstrip('\ufeff'))))
    if not rows or not rows[0] or rows[0][0].strip() != 'iShares Russell 1000 ETF':
        raise ValueError('Unexpected holdings document.')
    as_of = None
    header = None
    for i, row in enumerate(rows[:30]):
        if len(row) > 1 and row[0].strip() == 'Fund Holdings as of':
            try:
                as_of = datetime.strptime(row[1].strip(), '%b %d, %Y').date()
            except ValueError:
                raise ValueError('Holdings publication date is invalid.') from None
        if {'Ticker', 'Asset Class', 'Weight (%)'}.issubset(row):
            header = i
            break
    if as_of is None or not 0 <= (today - as_of).days <= MAX_AGE_DAYS:
        raise ValueError('Holdings publication date is missing, future-dated or stale (maximum 5 days).')
    if header is None:
        raise ValueError('Holdings table is missing.')
    columns = rows[header]
    equities = set()
    symbols = set()
    weight = 0.0
    for row in rows[header + 1:]:
        if len(row) != len(columns):
            continue
        item = dict(zip(columns, row))
        if item['Asset Class'].strip() != 'Equity':
            continue
        ticker = item['Ticker'].strip().upper()
        if ticker in equities:
            raise ValueError('Duplicate equity rows in holdings.')
        equities.add(ticker)
        try:
            weight += float(item['Weight (%)'].replace(',', ''))
        except ValueError:
            raise ValueError('Invalid holdings weight.') from None
        # Preserve the existing common-ticker policy; do not widen share classes.
        if is_common_ticker(ticker):
            symbols.add(ticker)
    if not 900 <= len(equities) <= 1200 or not 97 <= weight <= 101 or len(symbols) < 850:
        raise ValueError('Holdings failed equity-count/weight completeness checks.')
    return symbols, as_of


class IwbHoldings:
    def __init__(self, http: httpx.AsyncClient):
        self.http = http
        self._lock = asyncio.Lock()
        self._symbols: set[str] = set()
        self._loaded_on: date | None = None
        self._retry_at = 0.0
        self.status = dict(state='not_loaded', source='iShares IWB holdings (Russell proxy)',
                           url=HOLDINGS_URL, as_of=None, count=0, error=None)

    async def symbols(self) -> set[str]:
        async with self._lock:
            today = trading_date()
            if self._loaded_on == today and self._symbols:
                return set(self._symbols)
            if monotonic() < self._retry_at:
                return set()
            try:
                response = await self.http.get(HOLDINGS_URL, timeout=20, follow_redirects=True)
                response.raise_for_status()
                if len(response.content) > 2_000_000:
                    raise ValueError('Holdings response exceeded the size limit.')
                symbols, as_of = parse_holdings(response.text, today)
            except (httpx.HTTPError, ValueError, csv.Error) as exc:
                error = (f'Issuer HTTP {exc.response.status_code}' if isinstance(exc, httpx.HTTPStatusError)
                         else 'Issuer request unavailable' if isinstance(exc, httpx.HTTPError) else str(exc))
                self.status.update(state='unavailable', error=error, count=0)
                self._symbols = set()
                self._retry_at = monotonic() + 300
                return set()
            self._symbols, self._loaded_on = symbols, today
            self.status.update(state='ready', as_of=as_of.isoformat(), count=len(symbols), error=None)
            return set(symbols)
