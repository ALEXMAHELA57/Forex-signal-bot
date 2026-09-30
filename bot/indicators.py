"""Technical indicators in plain pandas (no TA-Lib needed on Windows)."""
import numpy as np
import pandas as pd


def ema(series, n):
    return series.ewm(span=n, adjust=False).mean()


def wilder(series, n):
    return series.ewm(alpha=1 / n, adjust=False).mean()


def rsi(close, n=14):
    delta = close.diff()
    gain = wilder(delta.clip(lower=0), n)
    loss = wilder(-delta.clip(upper=0), n)
    rs = gain / loss.replace(0, np.nan)
    out = 100 - 100 / (1 + rs)
    return out.where(loss != 0, 100.0).fillna(50.0)


def true_range(df):
    prev_close = df["close"].shift()
    return pd.concat(
        [df["high"] - df["low"],
         (df["high"] - prev_close).abs(),
         (df["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df, n=14):
    return wilder(true_range(df), n)


def adx(df, n=14):
    up = df["high"].diff()
    down = -df["low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    atr_ = wilder(true_range(df), n)
    plus_di = 100 * wilder(plus_dm, n) / atr_
    minus_di = 100 * wilder(minus_dm, n) / atr_
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return wilder(dx.fillna(0), n)


def add_indicators(df, atr_period=14):
    """Return a copy of an OHLC frame with every indicator the strategy uses."""
    df = df.copy()
    c = df["close"]
    df["ema20"] = ema(c, 20)
    df["ema50"] = ema(c, 50)
    df["ema200"] = ema(c, 200)
    df["rsi"] = rsi(c, 14)
    macd = ema(c, 12) - ema(c, 26)
    df["macd"] = macd
    df["macd_signal"] = ema(macd, 9)
    df["macd_hist"] = macd - df["macd_signal"]
    mid = c.rolling(20).mean()
    std = c.rolling(20).std()
    df["bb_mid"] = mid
    df["bb_up"] = mid + 2 * std
    df["bb_low"] = mid - 2 * std
    df["atr"] = atr(df, atr_period)
    df["adx"] = adx(df, 14)
    return df
