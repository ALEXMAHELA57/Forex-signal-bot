"""MetaTrader 5 price feed (Windows only - needs the MT5 desktop terminal installed).

MT5 bar times are in the broker's server time. Everything is converted to UTC here
so the rest of the bot never has to think about it.
"""
import logging
from datetime import datetime, timedelta, timezone

import MetaTrader5 as mt5
import pandas as pd

from . import config
from .utils import pip_size, utcnow

log = logging.getLogger(__name__)

TIMEFRAMES = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
}


class MT5Feed:
    track_tf = "M1"  # open signals are followed on 1-minute candles

    def __init__(self):
        self.offset = timedelta(0)
        self._resolved = {}

    # --- connection ------------------------------------------------------------
    def connect(self):
        kwargs = {}
        if config.MT5_PATH:
            kwargs["path"] = config.MT5_PATH
        if config.MT5_LOGIN:
            kwargs.update(login=config.MT5_LOGIN, password=config.MT5_PASSWORD,
                          server=config.MT5_SERVER)
        if not mt5.initialize(**kwargs):
            raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
        info = mt5.account_info()
        if info:
            log.info("Connected to MT5: %s (%s)", info.server, info.login)
        self._detect_offset()

    def ensure_connected(self):
        if mt5.terminal_info() is None:
            log.warning("MT5 connection lost, reconnecting...")
            mt5.shutdown()
            self.connect()

    def shutdown(self):
        mt5.shutdown()

    def _detect_offset(self):
        if config.BROKER_UTC_OFFSET is not None:
            self.offset = timedelta(hours=config.BROKER_UTC_OFFSET)
            log.info("Broker UTC offset (from .env): %+.1fh", config.BROKER_UTC_OFFSET)
            return
        for base in config.SYMBOLS:
            tick = mt5.symbol_info_tick(self.resolve(base))
            if not tick:
                continue
            server_now = datetime.fromtimestamp(tick.time, timezone.utc).replace(tzinfo=None)
            diff_h = (server_now - utcnow()).total_seconds() / 3600
            rounded = round(diff_h * 2) / 2  # brokers use whole/half hours
            if abs(diff_h - rounded) < 0.1 and abs(rounded) <= 14:
                self.offset = timedelta(hours=rounded)
                log.info("Broker UTC offset detected: %+.1fh", rounded)
                return
        log.warning("Could not detect broker UTC offset (market closed?). Using 0. "
                    "Set BROKER_UTC_OFFSET in .env to fix session times.")

    # --- symbols ---------------------------------------------------------------
    def resolve(self, base):
        """Map EURUSD -> broker name (adds SYMBOL_SUFFIX) and enable it in Market Watch."""
        if base in self._resolved:
            return self._resolved[base]
        name = base + (config.SYMBOL_SUFFIX or "")
        if not mt5.symbol_select(name, True):
            raise RuntimeError(
                f"Symbol {name} not found at your broker. Check the exact name in "
                f"MT5 Market Watch and set SYMBOL_SUFFIX in .env.")
        self._resolved[base] = name
        return name

    def digits(self, symbol):
        info = mt5.symbol_info(symbol)
        return info.digits if info else None

    def tick(self, symbol):
        return mt5.symbol_info_tick(symbol)

    def spread_pips(self, base, symbol):
        tick = self.tick(symbol)
        if not tick:
            return None
        return (tick.ask - tick.bid) / pip_size(base)

    # --- bars ------------------------------------------------------------------
    def _frame(self, rates):
        if rates is None or len(rates) == 0:
            return None
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s") - self.offset
        return df.set_index("time")[["open", "high", "low", "close", "tick_volume"]]

    def rates(self, symbol, timeframe, count):
        """Last `count` CLOSED bars (the still-forming bar is skipped), UTC index."""
        return self._frame(mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 1, count))

    def rates_with_current(self, symbol, timeframe, count):
        """Last `count` bars including the forming one."""
        return self._frame(mt5.copy_rates_from_pos(symbol, TIMEFRAMES[timeframe], 0, count))
