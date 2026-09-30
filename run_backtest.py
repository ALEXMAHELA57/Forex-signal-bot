"""Backtest the strategy on your broker's history. Run:

    python run_backtest.py                 # all symbols, ~7 months of M15
    python run_backtest.py --bars 40000    # more history
    python run_backtest.py --symbols XAUUSD EURUSD

Prints stats per pair and writes every trade to backtest_trades.csv.
Tune bot/config.py (MIN_SCORE, SL_ATR_MULT, TP_R, sessions) and re-run.
"""
import argparse
import sys

import pandas as pd

from bot import config
from bot.backtester import run_backtest, stats, trades_frame
from bot.feeds import make_feed
from bot.indicators import add_indicators


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--bars", type=int, default=20000, help="number of M15 bars to test")
    ap.add_argument("--symbols", nargs="*", default=config.SYMBOLS)
    args = ap.parse_args()

    feed = make_feed()
    if config.DATA_SOURCE == "twelvedata" and args.bars > 5000:
        print("Twelve Data returns at most 5000 candles per request (~7 weeks of M15); using 5000.")
        args.bars = 5000
    feed.connect()
    all_trades, rows = [], []
    try:
        for base in args.symbols:
            symbol = feed.resolve(base)
            m15 = feed.rates(symbol, "M15", args.bars)
            h1 = feed.rates(symbol, "H1", args.bars // 4 + 300)
            h4 = feed.rates(symbol, "H4", args.bars // 16 + 300)
            if m15 is None or h1 is None or h4 is None:
                print(f"{base}: no history returned (open the chart in MT5 to download it)")
                continue
            print(f"{base}: testing {m15.index[0]:%Y-%m-%d} -> {m15.index[-1]:%Y-%m-%d} ...")
            trades = run_backtest(base, add_indicators(m15, config.ATR_PERIOD),
                                  add_indicators(h1), add_indicators(h4))
            all_trades += trades
            rows.append({"symbol": base, **stats(trades)})
    finally:
        feed.shutdown()

    rows.append({"symbol": "ALL", **stats(all_trades)})
    print()
    print(pd.DataFrame(rows).set_index("symbol").to_string())
    trades_frame(all_trades).to_csv("backtest_trades.csv", index=False)
    print("\nTrades saved to backtest_trades.csv")
    print("R = multiples of risk. +20R over 100 trades at 1% risk ≈ +20% before costs/slippage.")


if __name__ == "__main__":
    main()
