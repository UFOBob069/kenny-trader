"""Confidence engine: blend technical, fundamental, and AI scores into 0-100.

Weights: technical 45%, fundamental 25%, AI catalyst read 30%.
All three sub-scores are expressed in the direction of the trade, i.e. 100 is
maximally favorable for the signal whether it is LONG or SHORT.
"""
from __future__ import annotations

from app.models import Candidate, ConfidenceBreakdown, Direction, SetupType, Signal

W_TECH, W_FUND, W_AI = 0.45, 0.25, 0.30


def technical_score(signal: Signal, above_vwap: bool, above_prior_vwap: bool | None) -> tuple[float, list[str]]:
    score = 30.0
    reasons: list[str] = []
    long_side = signal.direction == Direction.LONG

    if signal.setup == SetupType.FAUX_SHOW_BRO:
        score += 15
        reasons.append("Fakeout-shakeout-breakout pattern")
    elif signal.setup == SetupType.VWAP_BREAKDOWN:
        score += 12
        reasons.append("VWAP breakdown after extended move")

    if above_vwap == long_side:
        score += 15
        reasons.append("Above VWAP" if long_side else "Below VWAP")
    if above_prior_vwap is not None and above_prior_vwap == long_side:
        score += 15
        reasons.append("Above prior-day VWAP" if long_side else "Below prior-day VWAP")

    cand = signal.candidate
    if cand:
        rvol = cand.relative_volume
        if rvol >= 10:
            score += 15
            reasons.append(f"Relative volume {rvol:.0f}x")
        elif rvol >= 5:
            score += 10
            reasons.append(f"Relative volume {rvol:.1f}x")
        elif rvol >= 3:
            score += 5
            reasons.append(f"Relative volume {rvol:.1f}x")

        gap = cand.gap_pct if long_side else -cand.gap_pct
        if abs(cand.gap_pct) >= 8:
            score += 8 if gap > 0 else 4
            reasons.append(f"Gap {cand.gap_pct:+.1f}%")

    if signal.reward_risk >= 2.5:
        score += 5
        reasons.append(f"Reward:risk {signal.reward_risk:.1f}")

    return min(score, 100.0), reasons


def fundamental_score(signal: Signal) -> tuple[float, list[str]]:
    cand = signal.candidate
    if not cand or not cand.earnings:
        return 50.0, []

    e = cand.earnings
    reasons: list[str] = []
    eps_act, eps_est = e.get("actualEarningResult"), e.get("estimatedEarning")
    rev_act, rev_est = e.get("revenue"), e.get("revenueEstimated")

    bullish = 50.0
    if eps_act is not None and eps_est is not None:
        if eps_act > eps_est:
            bullish += 25
            reasons.append("EPS beat")
        elif eps_act < eps_est:
            bullish -= 25
            reasons.append("EPS miss")
    if rev_act and rev_est:
        if rev_act > rev_est:
            bullish += 15
            reasons.append("Revenue beat")
        elif rev_act < rev_est:
            bullish -= 15
            reasons.append("Revenue miss")

    bullish = max(0.0, min(100.0, bullish))
    score = bullish if signal.direction == Direction.LONG else 100.0 - bullish
    return score, reasons


def ai_score(signal: Signal, analysis: dict) -> tuple[float, list[str]]:
    bullish = float(analysis.get("score", 50))
    score = bullish if signal.direction == Direction.LONG else 100.0 - bullish
    reasons = list(analysis.get("reasons", []))[:4]
    if analysis.get("guidance_change") == "raised":
        reasons.append("Guidance raised")
    elif analysis.get("guidance_change") == "lowered":
        reasons.append("Guidance lowered")
    return score, reasons


def score_signal(
    signal: Signal,
    analysis: dict,
    above_vwap: bool,
    above_prior_vwap: bool | None,
) -> ConfidenceBreakdown:
    tech, tech_reasons = technical_score(signal, above_vwap, above_prior_vwap)
    fund, fund_reasons = fundamental_score(signal)
    ai, ai_reasons = ai_score(signal, analysis)

    total = round(W_TECH * tech + W_FUND * fund + W_AI * ai, 1)
    return ConfidenceBreakdown(
        technical=round(tech, 1),
        fundamental=round(fund, 1),
        ai=round(ai, 1),
        total=total,
        reasons=tech_reasons + fund_reasons + ai_reasons,
        ai_sentiment=analysis.get("sentiment", "neutral"),
    )
