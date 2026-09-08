"""Completed, ordered equity bars and Eastern Time session boundaries."""
from datetime import datetime, time, timedelta

from app.data.market_hours import ET
from app.models import Bar


def completed_bars(bars: list[Bar], now: datetime) -> list[Bar]:
    by_time = {
        bar.ts: bar for bar in bars
        if bar.ts + timedelta(minutes=1) <= now
        and time(4) <= bar.ts.astimezone(ET).time() < time(20)
    }
    return [by_time[ts] for ts in sorted(by_time)]


def split_sessions(bars: list[Bar], now: datetime) -> tuple[list[Bar], list[Bar]]:
    today = now.astimezone(ET).date()
    ordered = completed_bars(bars, now)
    prior_dates = {b.ts.astimezone(ET).date() for b in ordered if b.ts.astimezone(ET).date() < today}
    previous = max(prior_dates) if prior_dates else None
    return (
        [b for b in ordered if b.ts.astimezone(ET).date() == previous],
        [b for b in ordered if b.ts.astimezone(ET).date() == today],
    )
