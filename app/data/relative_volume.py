"""Compare completed session volume with history at the same Eastern minute."""
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime

from app.data.bar_sessions import completed_bars
from app.data.market_hours import ET
from app.models import Bar


class RelativeVolumeProfile:
    def __init__(self, history: list[Bar], now: datetime) -> None:
        self.day = now.astimezone(ET).date()
        grouped = defaultdict(list)
        for bar in completed_bars(history, now):
            day = bar.ts.astimezone(ET).date()
            if day < self.day:
                grouped[day].append(bar)
        self.sessions = []
        for day in sorted(grouped)[-5:]:
            minutes, cumulative = [], []
            total = 0.0
            for bar in grouped[day]:
                local = bar.ts.astimezone(ET)
                total += max(0, bar.volume)
                minutes.append(local.hour * 60 + local.minute)
                cumulative.append(total)
            self.sessions.append((minutes, cumulative))

    def measure(self, bars: list[Bar], now: datetime) -> tuple[float | None, datetime | None]:
        if self.day != now.astimezone(ET).date() or len(self.sessions) < 3:
            return None, None
        today = [b for b in completed_bars(bars, now) if b.ts.astimezone(ET).date() == self.day]
        if not today:
            return None, None
        last = today[-1].ts.astimezone(ET)
        minute = last.hour * 60 + last.minute
        totals = []
        for minutes, cumulative in self.sessions:
            index = bisect_right(minutes, minute) - 1
            totals.append(cumulative[index] if index >= 0 else 0.0)
        baseline = sum(totals) / len(totals)
        rvol = sum(max(0, b.volume) for b in today) / baseline if baseline > 0 else None
        return rvol, today[-1].ts
