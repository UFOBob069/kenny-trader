from app.data.finnhub import normalize_earnings


def test_normalize_earnings_calendar_row():
    row = {
        "symbol": "AAPL",
        "epsActual": 1.52,
        "epsEstimate": 1.50,
        "revenueActual": 90_000_000_000,
        "revenueEstimate": 89_000_000_000,
    }
    out = normalize_earnings(row)
    assert out["actualEarningResult"] == 1.52
    assert out["estimatedEarning"] == 1.50
    assert out["revenue"] == 90_000_000_000


def test_normalize_earnings_history_row():
    row = {"actual": 2.1, "estimate": 2.0, "revenue": None, "revenueEstimate": None}
    out = normalize_earnings(row)
    assert out["actualEarningResult"] == 2.1
    assert out["estimatedEarning"] == 2.0
