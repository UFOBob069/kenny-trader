from app.engine.scoring import criteria_score
from app.ai.confidence import score_signal
from app.models import Candidate, Direction, SetupType, Signal
from datetime import datetime, timezone


def liquid():
    now = datetime.now(timezone.utc)
    return {"bid": 1.5, "ask": 1.51, "quote_at": now, "activity_at": now,
            "dollar_volume_5m": 1_000_000, "active_minutes": 5, "shares_per_minute": 100_000}


def test_qualified_when_all_thresholds_met():
    score, qualified, checks = criteria_score(10.0, 4.0, 25.0, "earnings", liquid())
    assert qualified
    assert score >= 80
    assert all(checks[k]["ok"] for k in checks)


def test_not_qualified_low_gap():
    score, qualified, _ = criteria_score(2.0, 5.0, 50.0, "mover", liquid())
    assert not qualified
    assert score < 80


def test_liquid_sub_five_dollar_stock_can_qualify_even_with_legacy_floor(monkeypatch):
    monkeypatch.setattr("app.engine.scoring.settings.min_price", 5)
    _, qualified, checks = criteria_score(10, 4, 1.5, "mover", liquid())
    assert qualified
    assert "price" not in checks


def test_expensive_illiquid_stock_does_not_qualify():
    data = liquid()
    data["dollar_volume_5m"] = 1000
    assert not criteria_score(10, 4, 50, "mover", data)[1]


def test_unknown_liquidity_cannot_qualify():
    assert not criteria_score(10, 10, 100, "mover")[1]


def test_bad_earnings_do_not_penalize_a_technically_valid_reversal():
    candidate = Candidate(symbol="TEST", gap_pct=-10, relative_volume=5,
                          earnings={"actualEarningResult": 1, "estimatedEarning": 2})
    sig = Signal(symbol="TEST", direction=Direction.LONG, setup=SetupType.FAUX_SHOW_BRO,
                 entry=10, stop=9, target=13, candidate=candidate)
    bearish = score_signal(sig, {"score": 0}, True, True)
    bullish = score_signal(sig, {"score": 100}, True, True)
    assert bearish.total == bullish.total == bearish.technical
    assert bearish.ai != bullish.ai
