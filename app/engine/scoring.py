"""Setup-readiness score: catalyst activity and observed liquidity."""
from __future__ import annotations

from app.config import settings
from app.engine.liquidity import liquidity_checks
from app.models import utcnow


def criteria_score(
    gap_pct: float,
    rvol: float,
    price: float,
    catalyst: str,
    liquidity: dict | None = None,
) -> tuple[float, bool, dict]:
    """Return (score 0-100, qualified, per-check breakdown)."""
    min_gap = settings.min_gap_pct
    min_rvol = settings.min_relative_volume
    tradeable = catalyst in ("earnings", "mover")

    price_ok = price > 0
    gap_ok = abs(gap_pct) >= min_gap if tradeable else True
    rvol_ok = rvol >= min_rvol if tradeable else True
    liquid = liquidity_checks(liquidity, utcnow())
    qualified = price_ok and gap_ok and rvol_ok and all(c["ok"] for c in liquid.values())

    gap_prog = min(100.0, abs(gap_pct) / min_gap * 100) if min_gap and tradeable else 100.0
    rvol_prog = min(100.0, rvol / min_rvol * 100) if min_rvol and tradeable else 100.0
    liquidity_prog = sum(c["ok"] for c in liquid.values()) / len(liquid) * 100

    if catalyst == "news":
        score = liquidity_prog * 0.5 if price_ok else 0.0
    else:
        score = 0.4 * gap_prog + 0.4 * rvol_prog + 0.2 * liquidity_prog

    checks = {
        "gap": {"ok": gap_ok, "value": round(gap_pct, 2), "need": min_gap},
        "rvol": {"ok": rvol_ok, "value": round(rvol, 2), "need": min_rvol},
        **liquid,
    }
    return round(score, 1), qualified, checks
