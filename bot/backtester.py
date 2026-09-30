"""Backtest engine: replays history candle by candle using the exact live strategy."""
from datetime import timedelta

import numpy as np
import pandas as pd

from . import config
from .strategy import MIN_BARS, analyze
from .tracker import apply_bar, expire
from .utils import pip_size

TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240}


def run_backtest(symbol, m15, h1, h4, spread_pips=None):
    """m15/h1/h4: OHLC frames with indicators, UTC bar-open index. Returns list of trades."""
    spread = (spread_pips if spread_pips is not None
              else config.BACKTEST_SPREAD_PIPS.get(symbol, 1.5)) * pip_size(symbol)
    step = timedelta(minutes=TF_MINUTES[config.ENTRY_TF])
    h1_close = (h1.index + timedelta(minutes=TF_MINUTES[config.TREND_TF])).to_numpy()
    h4_close = (h4.index + timedelta(minutes=TF_MINUTES[config.BIAS_TF])).to_numpy()
    highs, lows, closes = m15["high"].to_numpy(), m15["low"].to_numpy(), m15["close"].to_numpy()
    times = m15.index

    trades, trade = [], None
    cooldown_until = times[0]
    expiry = timedelta(hours=config.SIGNAL_EXPIRY_HOURS)

    for i in range(MIN_BARS, len(m15)):
        close_time = times[i] + step

        if trade is not None:
            adj = spread if trade["side"] == "SELL" else 0.0
            apply_bar(trade, highs[i] + adj, lows[i] + adj)
            if trade["status"] == "OPEN" and close_time - trade["open_time"] >= expiry:
                expire(trade, closes[i] + adj)
            if trade["status"] != "OPEN":
                trade["close_time"] = close_time
                trades.append(trade)
                trade = None
            continue

        if close_time < cooldown_until:
            continue
        if close_time.weekday() >= 5 or not (
                config.SESSION_START_UTC <= close_time.hour < config.SESSION_END_UTC):
            continue

        j = int(np.searchsorted(h1_close, np.datetime64(close_time), side="right"))
        k = int(np.searchsorted(h4_close, np.datetime64(close_time), side="right"))
        if j < MIN_BARS or k < MIN_BARS:
            continue

        bid = closes[i]
        sig = analyze(symbol, m15.iloc[: i + 1], h1.iloc[:j], h4.iloc[:k],
                      prices=(bid, bid + spread))
        if not sig:
            continue

        trade = {
            "symbol": symbol, "side": sig.side, "entry": sig.entry, "sl": sig.sl,
            "sl_initial": sig.sl, "tps": list(sig.tps), "tp_hit": 0, "status": "OPEN",
            "result_r": None, "score": sig.score, "reasons": " · ".join(sig.reasons),
            "open_time": close_time,
        }
        cooldown_until = close_time + step * config.COOLDOWN_BARS

    return trades


def stats(trades):
    if not trades:
        return {"trades": 0}
    r = np.array([t["result_r"] for t in trades], dtype=float)
    equity = np.cumsum(r)
    peak = np.maximum.accumulate(np.concatenate([[0.0], equity]))[1:]
    gross_win, gross_loss = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "trades": len(r),
        "win_rate_%": round(float(100 * (r > 0).mean()), 1),
        "tp1_hit_%": round(float(100 * np.mean([t["tp_hit"] >= 1 for t in trades])), 1),
        "total_R": round(float(r.sum()), 2),
        "avg_R": round(float(r.mean()), 3),
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss else float("inf"),
        "max_drawdown_R": round(float((peak - equity).max()), 2),
    }


def trades_frame(trades):
    df = pd.DataFrame(trades)
    if not df.empty:
        df["tps"] = df["tps"].apply(lambda x: " / ".join(f"{v:g}" for v in x))
    return df
