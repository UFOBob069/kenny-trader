"""Setup-readiness score: how close a symbol is to gap / rvol / price filters."""
from __future__ import annotations

from app.config import settings


def criteria_score(
    gap_pct: float,
    rvol: float,
    price: float,
    catalyst: str,
) -> tuple[float, bool, dict]:
    """Return (score 0-100, qualified, per-check breakdown)."""
    min_gap = settings.min_gap_pct
    min_rvol = settings.min_relative_volume
    min_price = settings.min_price
    tradeable = catalyst in ("earnings", "mover")

    price_ok = price >= min_price
    gap_ok = abs(gap_pct) >= min_gap if tradeable else True
    rvol_ok = rvol >= min_rvol if tradeable else True
    qualified = price_ok and gap_ok and rvol_ok

    gap_prog = min(100.0, abs(gap_pct) / min_gap * 100) if min_gap and tradeable else 100.0
    rvol_prog = min(100.0, rvol / min_rvol * 100) if min_rvol and tradeable else 100.0
    price_prog = min(100.0, price / min_price * 100) if min_price else 0.0

    if catalyst == "news":
        score = 50.0 if price_ok else price_prog * 0.5
    else:
        score = 0.4 * gap_prog + 0.4 * rvol_prog + 0.2 * price_prog

    checks = {
        "gap": {"ok": gap_ok, "value": round(gap_pct, 2), "need": min_gap},
        "rvol": {"ok": rvol_ok, "value": round(rvol, 2), "need": min_rvol},
        "price": {"ok": price_ok, "value": round(price, 2), "need": min_price},
    }
    return round(score, 1), qualified, checks
