"""Multi-timeframe confluence strategy.

A setup is scored 0-100 for BUY and for SELL. The best side becomes a signal
when its score reaches config.MIN_SCORE and all hard filters pass.

Scoring (BUY shown; SELL is the mirror image):
  20  H4 trend up        (close > EMA50 > EMA200, EMA50 rising)
  20  H1 trend up
  15  M15 structure      (EMA20 > EMA50 and close > EMA20)
  15  MACD momentum      (histogram positive and rising; 10 for a fresh cross)
  10  RSI in 50-68       (momentum without being overbought)
  10  Pullback           (price dipped to EMA20 in the last few bars, then bounced)
  10  ADX >= 20          (market is trending, not ranging)
 -10  Over-extended      (close outside the Bollinger Band)

Hard filters: H1 trend must not point the other way, the signal candle must
close in the trade direction, RSI must not be extreme (>75 buy / <25 sell).
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import config
from .utils import default_digits

MIN_BARS = 210  # EMA200 needs history to settle


@dataclass
class Signal:
    symbol: str
    side: str                  # "BUY" or "SELL"
    entry: float
    sl: float
    tps: list
    score: int
    reasons: list = field(default_factory=list)
    atr: float = 0.0
    time: datetime = None      # UTC close time of the signal candle


def trend_bias(df):
    """+1 uptrend, -1 downtrend, 0 no clear trend (uses last closed bar)."""
    if len(df) < MIN_BARS:
        return 0
    r = df.iloc[-1]
    prev_ema50 = df["ema50"].iloc[-6]
    if r.close > r.ema50 > r.ema200 and r.ema50 > prev_ema50:
        return 1
    if r.close < r.ema50 < r.ema200 and r.ema50 < prev_ema50:
        return -1
    return 0


def score_side(d, m15, h1_bias, h4_bias):
    """Score one direction. d = +1 for BUY, -1 for SELL. Returns (score, reasons)."""
    if h1_bias == -d:
        return 0, []

    r = m15.iloc[-1]
    p = m15.iloc[-2]

    # Hard filters
    if d * (r.close - r.open) <= 0:
        return 0, []
    if (d == 1 and r.rsi > 75) or (d == -1 and r.rsi < 25):
        return 0, []

    word = "up" if d == 1 else "down"
    score, reasons = 0, []

    if h4_bias == d:
        score += 20
        reasons.append(f"H4 trend {word}")
    if h1_bias == d:
        score += 20
        reasons.append(f"H1 trend {word}")

    if d * (r.ema20 - r.ema50) > 0 and d * (r.close - r.ema20) > 0:
        score += 15
        reasons.append("M15 EMAs aligned")

    hist = m15["macd_hist"].iloc[-4:].to_numpy()
    if d * hist[-1] > 0 and d * (hist[-1] - hist[-2]) > 0:
        score += 15
        reasons.append("MACD momentum rising")
    elif d * hist[-1] > 0 and any(d * h <= 0 for h in hist[:-1]):
        score += 10
        reasons.append("fresh MACD cross")

    if (d == 1 and 50 <= r.rsi <= 68) or (d == -1 and 32 <= r.rsi <= 50):
        score += 10
        reasons.append(f"RSI {r.rsi:.0f}")

    recent = m15.iloc[-6:-1]
    zone = 0.2 * r.atr
    if d == 1:
        touched = (recent["low"] <= recent["ema20"] + zone).any()
    else:
        touched = (recent["high"] >= recent["ema20"] - zone).any()
    if touched and d * (r.close - r.ema20) > 0:
        score += 10
        reasons.append("pullback to EMA20")

    if r.adx >= 20:
        score += 10
        reasons.append(f"ADX {r.adx:.0f}")

    if (d == 1 and r.close > r.bb_up) or (d == -1 and r.close < r.bb_low):
        score -= 10
        reasons.append("stretched past Bollinger Band")

    return max(score, 0), reasons


def build_levels(symbol, side, entry, m15, digits=None):
    """Stop beyond the recent swing (at least 1.5 ATR, at most 3 ATR) and 3 targets."""
    digits = digits if digits is not None else default_digits(symbol)
    atr_now = float(m15["atr"].iloc[-1])
    window = m15.iloc[-config.SWING_LOOKBACK:]
    d = 1 if side == "BUY" else -1
    if d == 1:
        swing_dist = entry - float(window["low"].min()) + 0.2 * atr_now
    else:
        swing_dist = float(window["high"].max()) - entry + 0.2 * atr_now
    dist = max(atr_now * config.SL_ATR_MULT, swing_dist)
    dist = min(dist, atr_now * config.SL_ATR_MAX)
    sl = round(entry - d * dist, digits)
    tps = [round(entry + d * dist * r, digits) for r in config.TP_R]
    return round(entry, digits), sl, tps, atr_now


def analyze(symbol, m15, h1, h4, prices=None, digits=None, timeframe_minutes=15):
    """Analyze closed candles (indicators already added).

    prices: optional (bid, ask) for live entry; otherwise entry = last close.
    Returns a Signal or None.
    """
    if len(m15) < MIN_BARS or len(h1) < MIN_BARS or len(h4) < MIN_BARS:
        return None

    h1_bias = trend_bias(h1)
    h4_bias = trend_bias(h4)

    buy_score, buy_reasons = score_side(1, m15, h1_bias, h4_bias)
    sell_score, sell_reasons = score_side(-1, m15, h1_bias, h4_bias)

    if buy_score >= sell_score:
        side, score, reasons = "BUY", buy_score, buy_reasons
    else:
        side, score, reasons = "SELL", sell_score, sell_reasons

    if score < config.MIN_SCORE:
        return None

    close = float(m15["close"].iloc[-1])
    if prices:
        bid, ask = prices
        entry = ask if side == "BUY" else bid
    else:
        entry = close

    entry, sl, tps, atr_now = build_levels(symbol, side, entry, m15, digits)
    bar_time = m15.index[-1] + timedelta(minutes=timeframe_minutes)
    return Signal(symbol, side, entry, sl, tps, int(score), reasons, atr_now,
                  bar_time.to_pydatetime() if hasattr(bar_time, "to_pydatetime") else bar_time)
