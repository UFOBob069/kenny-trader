import pytest

from app.data.symbol_filter import is_common_ticker


@pytest.mark.parametrize("symbol", ["AAPL", "TSLA", "NVDA", "BRK", "GROW"])
def test_accepts_common_tickers(symbol):
    assert is_common_ticker(symbol)


@pytest.mark.parametrize("symbol", [
    "AEAQW",
    "ASPSZ",
    "UAC.WS",
    "RQI.RT",
    "KRSP.WS",
    "SCAGW",
    "BFRIW",
    "ILLRW",
    "CMIIW",
])
def test_rejects_warrants_and_rights(symbol):
    assert not is_common_ticker(symbol)
