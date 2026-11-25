"""Simple trading signals over a list of prices (oldest -> newest)."""
from . import indicators as ind
from .indicators import sma

BUY, SELL, HOLD = "BUY", "SELL", "HOLD"


def sma_cross(prices: list[float], fast: int = 5, slow: int = 20) -> str:
    """BUY when the fast SMA crosses above the slow SMA on the latest price,
    SELL when it crosses below, otherwise HOLD.

    A cross means the fast/slow relationship flipped between the previous
    price and the latest one, so a trend that is already established returns
    HOLD. Needs slow + 1 prices to compare two points in time; with fewer than
    `slow` prices (or just `slow`, with no previous bar) it returns HOLD.
    """
    if fast < 1 or slow <= fast:
        raise ValueError("need 1 <= fast < slow")
    if len(prices) < slow + 1:
        return HOLD
    f_now, s_now = sma(prices, fast), sma(prices, slow)
    f_prev, s_prev = sma(prices[:-1], fast), sma(prices[:-1], slow)
    if f_prev <= s_prev and f_now > s_now:
        return BUY
    if f_prev >= s_prev and f_now < s_now:
        return SELL
    return HOLD


def rsi(prices: list[float], period: int = 14) -> str:
    """BUY when RSI is below 30 (oversold), SELL when above 70 (overbought),
    otherwise HOLD. HOLD if there are fewer than period + 1 prices."""
    if period < 1:
        raise ValueError("period must be >= 1")
    value = ind.rsi(prices, period)
    if value is None:
        return HOLD
    if value < 30:
        return BUY
    if value > 70:
        return SELL
    return HOLD


def breakout(prices: list[float], n: int = 20) -> str:
    """BUY when the latest price is above the highest of the previous n prices,
    SELL when it is below the lowest of the previous n, otherwise HOLD.
    HOLD if there are fewer than n + 1 prices."""
    if n < 1:
        raise ValueError("n must be >= 1")
    direction = ind.breakout(prices, n)
    return BUY if direction == 1 else SELL if direction == -1 else HOLD
