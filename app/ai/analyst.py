"""OpenAI catalyst analysis: earnings + news -> sentiment, guidance read, reasons."""
from __future__ import annotations

import json
import logging

from openai import AsyncOpenAI

from app.config import settings
from app.models import Candidate

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an equity catalyst analyst for an intraday momentum desk.
Given a stock's earnings results and recent headlines, classify the catalyst.
Respond ONLY with JSON: {"sentiment": "bullish"|"neutral"|"bearish",
"score": 0-100 (100 = maximally bullish), "guidance_change": "raised"|"lowered"|"unchanged"|"unknown",
"catalyst_type": short string, "reasons": [up to 4 short strings]}"""


class CatalystAnalyst:
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None

    async def analyze(self, candidate: Candidate) -> dict:
        if self._client is None:
            return {"sentiment": "neutral", "score": 50, "guidance_change": "unknown",
                    "catalyst_type": candidate.catalyst or "unknown", "reasons": ["AI analysis disabled (no API key)"]}

        payload = {
            "symbol": candidate.symbol,
            "gap_pct": candidate.gap_pct,
            "relative_volume": candidate.relative_volume,
            "earnings": candidate.earnings,
            "headlines": candidate.headlines[:8],
        }
        try:
            resp = await self._client.chat.completions.create(
                model=settings.openai_model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": json.dumps(payload, default=str)},
                ],
                temperature=0.2,
            )
            data = json.loads(resp.choices[0].message.content)
            data["score"] = max(0, min(100, float(data.get("score", 50))))
            return data
        except Exception:
            log.exception("OpenAI analysis failed for %s", candidate.symbol)
            return {"sentiment": "neutral", "score": 50, "guidance_change": "unknown",
                    "catalyst_type": "unknown", "reasons": ["AI analysis unavailable"]}
