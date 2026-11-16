"""Classic technical indicators. Pure functions over lists of closing prices
(oldest -> newest). Each returns None when there isn't enough data yet."""


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema_series(closes: list[float], period: int) -> list[float]:
    """EMA seeded with the SMA of the first `period` values; len = len(closes)-period+1."""
    if len(closes) < period:
        return []
    k = 2 / (period + 1)
    out = [sum(closes[:period]) / period]
    for c in closes[period:]:
        out.append(c * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI, 0-100."""
    if len(closes) < period + 1:
        return None
    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gain = sum(max(d, 0) for d in deltas[:period]) / period
    loss = sum(max(-d, 0) for d in deltas[:period]) / period
    for d in deltas[period:]:
        gain = (gain * (period - 1) + max(d, 0)) / period
        loss = (loss * (period - 1) + max(-d, 0)) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def macd(closes: list[float], fast=12, slow=26, signal=9) -> tuple[float, float] | None:
    """Returns (histogram_now, histogram_previous), or None if not enough data."""
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    if not es:
        return None
    line = [f - s for f, s in zip(ef[len(ef) - len(es):], es)]
    sig = ema_series(line, signal)
    if len(sig) < 2:
        return None
    hist = [l - s for l, s in zip(line[len(line) - len(sig):], sig)]
    return hist[-1], hist[-2]


def breakout(closes: list[float], lookback: int = 20) -> int | None:
    """Donchian breakout: +1 if the last close beats the prior `lookback` high,
    -1 if it breaks the prior low, else 0."""
    if len(closes) < lookback + 1:
        return None
    window, last = closes[-lookback - 1 : -1], closes[-1]
    if last > max(window):
        return 1
    if last < min(window):
        return -1
    return 0
