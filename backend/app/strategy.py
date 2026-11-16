"""Combine SMA trend, MACD momentum, Donchian breakout and RSI into one signal."""
from dataclasses import dataclass

from . import indicators as ind

MIN_BARS = 60  # enough for SMA(50) and MACD(12,26,9)


@dataclass
class Signal:
    action: str  # "buy" | "sell" | "hold"
    score: int
    reasons: list[str]


def evaluate(closes: list[float], rsi_buy_max: float = 70) -> Signal:
    """Each indicator votes +1 / 0 / -1 on hourly closes; votes are summed.

    buy  : score >= 2 and RSI not overbought (no chasing)
    sell : score <= -2
    Requiring agreement between independent indicators filters out much of the
    noise a single indicator would trade on.
    """
    if len(closes) < MIN_BARS:
        return Signal("hold", 0, [f"need {MIN_BARS} bars, have {len(closes)}"])

    score, reasons = 0, []

    fast, slow = ind.sma(closes, 20), ind.sma(closes, 50)
    v = 1 if fast > slow else -1 if fast < slow else 0
    score += v; reasons.append(f"SMA20/50 {v:+d}")

    hist, prev = ind.macd(closes)
    v = 1 if hist > 0 and hist >= prev else -1 if hist < 0 and hist <= prev else 0
    score += v; reasons.append(f"MACD {v:+d}")

    v = ind.breakout(closes, 20)
    score += v; reasons.append(f"breakout20 {v:+d}")

    r = ind.rsi(closes, 14)
    v = 1 if r < 30 else -1 if r > 70 else 0
    score += v; reasons.append(f"RSI {r:.0f} {v:+d}")

    if score >= 2 and r < rsi_buy_max:
        return Signal("buy", score, reasons)
    if score <= -2:
        return Signal("sell", score, reasons)
    return Signal("hold", score, reasons)
