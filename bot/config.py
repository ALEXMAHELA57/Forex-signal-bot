"""All settings in one place. Secrets come from .env, strategy knobs live here."""
import os

from dotenv import load_dotenv

load_dotenv()


def _env(name, default=None, cast=str):
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return cast(value.strip())


# --- Price source --------------------------------------------------------------
# "mt5"        -> MetaTrader 5 on Windows (your broker's exact prices)
# "twelvedata" -> online API, runs anywhere (cloud hosting); free key at twelvedata.com
DATA_SOURCE = _env("DATA_SOURCE", "mt5").lower()
TWELVEDATA_API_KEY = _env("TWELVEDATA_API_KEY")
TWELVEDATA_MAX_PER_MINUTE = _env("TWELVEDATA_MAX_PER_MINUTE", 8, int)

# --- Secrets / account (.env) -------------------------------------------------
MT5_LOGIN = _env("MT5_LOGIN", None, int)
MT5_PASSWORD = _env("MT5_PASSWORD")
MT5_SERVER = _env("MT5_SERVER")
MT5_PATH = _env("MT5_PATH")                  # optional: path to terminal64.exe
SYMBOL_SUFFIX = _env("SYMBOL_SUFFIX", "")    # e.g. "m" if your broker shows EURUSDm
BROKER_UTC_OFFSET = _env("BROKER_UTC_OFFSET", None, float)  # hours; blank = auto-detect

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")  # "@yourchannel" or "-100..." or your user id

# --- Markets -------------------------------------------------------------------
SYMBOLS = ["EURUSD", "GBPUSD", "USDJPY", "XAUUSD"]
ENTRY_TF = "M15"   # signal timeframe
TREND_TF = "H1"    # must not oppose the trade
BIAS_TF = "H4"     # higher-timeframe bias (bonus points)
BARS = {"M15": 500, "H1": 400, "H4": 300}

# --- Strategy ------------------------------------------------------------------
MIN_SCORE = 70            # 0-100; raise for fewer, stronger signals
MIN_SCORE_BY_SYMBOL = {"XAUUSD": 80}   # gold is noisier on M15: demand more confluence
REQUIRE_H1_TREND = True        # H1 trend must agree (not just "not against")
REQUIRE_M15_STRUCTURE = True   # M15 EMA20/50 must be aligned with the trade
SKIP_IF_STRETCHED = True       # no entry when price already closed outside the Bollinger Band
ATR_PERIOD = 14
SL_ATR_MULT = 1.5         # minimum stop distance = 1.5 x ATR
SL_ATR_MAX = 3.0          # never wider than 3 x ATR
SWING_LOOKBACK = 10       # stop goes beyond the swing low/high of last N bars
TP_R = [1.0, 2.0, 3.0]    # TP1/TP2/TP3 as multiples of the stop distance (R)
MOVE_SL_TO_BE_AFTER_TP1 = True

# --- Filters -------------------------------------------------------------------
SESSION_START_UTC = 7     # London open
SESSION_END_UTC = 20      # New York afternoon
MAX_SPREAD_PIPS = {"EURUSD": 2.0, "GBPUSD": 2.5, "USDJPY": 2.0, "XAUUSD": 4.0}
COOLDOWN_BARS = 8         # wait 8 x M15 = 2h after a signal on the same pair
LOSS_COOLDOWN_HOURS = 6   # after a Stop Loss on a pair, no new signal on that pair for 6h
MAX_SIGNALS_PER_DAY = 8
SIGNAL_EXPIRY_HOURS = 24  # close tracking of a signal after this long

# --- Runtime -------------------------------------------------------------------
POLL_SECONDS = 20
DAILY_SUMMARY_HOUR_UTC = 21
DB_PATH = _env("DB_PATH", "signals.db")     # SQLite file (STORAGE=sqlite)
LOG_PATH = _env("LOG_PATH", "bot.log")

# --- Storage ---------------------------------------------------------------------
# "sqlite"   -> local signals.db file
# "supabase" -> Postgres table in your Supabase project (survives restarts, dashboard can read it)
STORAGE = _env("STORAGE", "sqlite").lower()
SUPABASE_URL = _env("SUPABASE_URL")                  # https://xxxx.supabase.co
SUPABASE_SERVICE_KEY = _env("SUPABASE_SERVICE_KEY")  # service_role / secret key, server only
SUPABASE_TABLE = _env("SUPABASE_TABLE", "bot_signals")

# --- Web (for Render free web service + uptime pinger) -------------------------------
PORT = _env("PORT", None, int)   # Render sets PORT automatically; empty = no web server

# --- Backtest / API spread ---------------------------------------------------------
BACKTEST_SPREAD_PIPS = {"EURUSD": 1.0, "GBPUSD": 1.3, "USDJPY": 1.0, "XAUUSD": 3.0}
# The API gives one mid price, so entries add this typical broker spread
ASSUMED_SPREAD_PIPS = BACKTEST_SPREAD_PIPS
