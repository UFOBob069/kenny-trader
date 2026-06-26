"""Keep the scan universe to liquid NYSE/Nasdaq common stocks."""
from __future__ import annotations

import re

# Plain US tickers only — no warrants (.WS), rights (.RT), units, or OTC junk.
_TICKER = re.compile(r"^[A-Z]{1,5}$")

# Nasdaq 5th-letter suffixes for non-common share classes (warrant, unit, right, …).
_FIFTH_LETTER_SKIP = frozenset("WUROXZP")


def is_common_ticker(symbol: str) -> bool:
    """Fast reject for warrants, rights, units, and non-standard symbols."""
    sym = symbol.upper().strip()
    if not sym or not _TICKER.match(sym):
        return False
    if len(sym) == 5 and sym[-1] in _FIFTH_LETTER_SKIP:
        return False
    return True
