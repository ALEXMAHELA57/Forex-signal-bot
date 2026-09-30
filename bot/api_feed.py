"""Cloud price feed using the Twelve Data API (no MetaTrader needed, runs on Linux).

Free plan limits: 8 requests/minute, 800 requests/day. To stay well under that,
bars are cached and a timeframe is only re-downloaded after a new candle has
closed, and nothing is fetched while the forex market is closed at the weekend.
4 pairs use roughly 400-500 requests per day.
"""
import logging
import time
from collections import deque
from datetime import timedelta
from types import SimpleNamespace

import pandas as pd
import requests

from . import config
from .utils import default_digits, pip_size, utcnow

log = logging.getLogger(__name__)

BASE_URL = "https://api.twelvedata.com"
INTERVALS = {"M1": "1min", "M5": "5min", "M15": "15min", "M30": "30min",
             "H1": "1h", "H4": "4h", "D1": "1day"}
MINUTES = {"M1": 1, "M5": 5, "M15": 15, "M30": 30, "H1": 60, "H4": 240, "D1": 1440}
MAX_OUTPUT = 5000
CLOSE_DELAY = timedelta(seconds=20)   # give the provider a moment to finalize a candle
RETRY_EVERY = timedelta(minutes=5)    # if an expected candle hasn't arrived yet


def market_closed(now):
    """Forex closes Friday ~21:00 UTC and reopens Sunday ~21:00 UTC."""
    wd, h = now.weekday(), now.hour
    return (wd == 4 and h >= 21) or wd == 5 or (wd == 6 and h < 21)


class TwelveDataFeed:
    track_tf = "M15"  # open signals are followed on M15 candles (saves API credits)

    def __init__(self):
        self.key = config.TWELVEDATA_API_KEY
        self.session = requests.Session()
        self._calls = deque()
        self._cache = {}   # (symbol, tf) -> {"df", "count", "fetched"}
        self.credits_today = 0
        self._credit_day = None

    # --- same interface as MT5Feed -----------------------------------------------
    def connect(self):
        if not self.key:
            raise RuntimeError("TWELVEDATA_API_KEY is missing. Get a free key at twelvedata.com")
        log.info("Using Twelve Data price feed")

    def ensure_connected(self):
        pass

    def shutdown(self):
        self.session.close()

    def resolve(self, base):
        return f"{base[:3]}/{base[3:]}"   # EURUSD -> EUR/USD, XAUUSD -> XAU/USD

    def digits(self, symbol):
        return default_digits(symbol.replace("/", ""))

    def _assumed_spread(self, symbol):
        base = symbol.replace("/", "")
        return config.ASSUMED_SPREAD_PIPS.get(base, 1.5) * pip_size(base)

    def spread_pips(self, base, symbol):
        return config.ASSUMED_SPREAD_PIPS.get(base, 1.5)

    def tick(self, symbol):
        """Latest price from the cached M15 candles (no extra API call)."""
        entry = self._cache.get((symbol, config.ENTRY_TF))
        if entry is None or entry["df"] is None or entry["df"].empty:
            return None
        mid = float(entry["df"]["close"].iloc[-1])
        half = self._assumed_spread(symbol) / 2
        return SimpleNamespace(bid=mid - half, ask=mid + half)

    def rates(self, symbol, timeframe, count):
        """Last `count` CLOSED candles (UTC index). Downloads only when a new one is due."""
        key = (symbol, timeframe)
        now = utcnow()
        entry = self._cache.get(key)
        if entry and entry["df"] is not None and entry["count"] >= min(count, MAX_OUTPUT):
            if not self._refresh_due(entry, timeframe, now):
                return entry["df"].iloc[-count:]
        df = self._download(symbol, timeframe, min(count, MAX_OUTPUT))
        if df is None:
            return entry["df"].iloc[-count:] if entry and entry["df"] is not None else None
        self._cache[key] = {"df": df, "count": min(count, MAX_OUTPUT), "fetched": now}
        return df

    # --- internals --------------------------------------------------------------------
    def _refresh_due(self, entry, timeframe, now):
        if market_closed(now):
            return False
        step = timedelta(minutes=MINUTES[timeframe])
        next_close = entry["df"].index[-1] + 2 * step   # close time of the next candle
        if now < next_close + CLOSE_DELAY:
            return False
        # candle is due; if we already asked recently and it wasn't there, wait a bit
        return now - entry["fetched"] >= min(RETRY_EVERY, step)

    def _throttle(self):
        now = time.monotonic()
        while self._calls and now - self._calls[0] > 60:
            self._calls.popleft()
        if len(self._calls) >= config.TWELVEDATA_MAX_PER_MINUTE:
            wait = 61 - (now - self._calls[0])
            log.info("Rate limit: waiting %.0fs", wait)
            time.sleep(max(wait, 1))
        self._calls.append(time.monotonic())

    def _count_credit(self):
        today = utcnow().date()
        if today != self._credit_day:
            self._credit_day, self.credits_today = today, 0
        self.credits_today += 1
        if self.credits_today in (600, 750):
            log.warning("Twelve Data: %d requests used today (free limit 800)", self.credits_today)

    def _download(self, symbol, timeframe, count):
        params = {"symbol": symbol, "interval": INTERVALS[timeframe], "outputsize": count,
                  "timezone": "UTC", "order": "ASC", "apikey": self.key}
        for attempt in range(2):
            self._throttle()
            self._count_credit()
            try:
                resp = self.session.get(f"{BASE_URL}/time_series", params=params, timeout=20)
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("Twelve Data request failed for %s %s: %s", symbol, timeframe, exc)
                time.sleep(5)
                continue
            if data.get("status") == "error":
                log.warning("Twelve Data error for %s %s: %s", symbol, timeframe, data.get("message"))
                if data.get("code") == 429 and attempt == 0:
                    time.sleep(60)
                    continue
                return None
            return self._frame(data.get("values") or [], timeframe)
        return None

    @staticmethod
    def _frame(values, timeframe):
        if not values:
            return None
        df = pd.DataFrame(values)
        df["time"] = pd.to_datetime(df["datetime"])
        df = df.set_index("time").sort_index()
        df = df[["open", "high", "low", "close"]].astype(float)
        df = df[~df.index.duplicated(keep="last")]
        # drop the candle that is still forming
        closes = df.index + timedelta(minutes=MINUTES[timeframe])
        return df[closes <= pd.Timestamp(utcnow())]
