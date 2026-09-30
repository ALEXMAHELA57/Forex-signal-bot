"""Live signal bot. Run:  python run_bot.py

Every POLL_SECONDS it:
  1. checks each pair for a newly closed M15 candle and analyzes it,
  2. posts any new signal to Telegram,
  3. follows open signals and replies when TP1/TP2/TP3 or SL is hit,
  4. posts a daily summary.
"""
import logging
import sys
import time
from datetime import datetime, timedelta

from bot import config, web
from bot.feeds import make_feed
from bot.indicators import add_indicators
from bot.strategy import analyze
from bot.telegram_notify import send_message
from bot.tracker import apply_bar, expire, make_tracker
from bot.utils import default_digits, format_event, format_signal, format_summary, utcnow

log = logging.getLogger("bot")
ENTRY_MINUTES = 15
TF_MINUTES = {"M1": 1, "M15": 15}


def setup_logging():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # emojis in PowerShell
    except AttributeError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(config.LOG_PATH, encoding="utf-8")],
    )


def in_session(now):
    return now.weekday() < 5 and config.SESSION_START_UTC <= now.hour < config.SESSION_END_UTC


def can_signal(base, symbol, feed, db, now):
    if not in_session(now):
        return False
    if db.open_trades(base):
        return False
    last = db.last_signal_time(base)
    if last and now - datetime.fromisoformat(last) < timedelta(minutes=ENTRY_MINUTES * config.COOLDOWN_BARS):
        return False
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if db.count_since(day_start.isoformat()) >= config.MAX_SIGNALS_PER_DAY:
        return False
    spread = feed.spread_pips(base, symbol)
    max_spread = config.MAX_SPREAD_PIPS.get(base, 3.0)
    if spread is None or spread > max_spread:
        log.info("%s skipped: spread %.1f pips > %.1f", base, spread or -1, max_spread)
        return False
    return True


def scan(feed, db, last_bar):
    now = utcnow()
    for base in config.SYMBOLS:
        symbol = feed.resolve(base)
        m15 = feed.rates(symbol, config.ENTRY_TF, config.BARS[config.ENTRY_TF])
        if m15 is None or len(m15) < 250:
            continue
        bar_open = m15.index[-1].to_pydatetime()
        if last_bar.get(base) == bar_open:
            continue
        last_bar[base] = bar_open
        # Only act on a candle that closed moments ago (not a stale one after restart/weekend)
        if now - (bar_open + timedelta(minutes=ENTRY_MINUTES)) > timedelta(minutes=3):
            continue
        if not can_signal(base, symbol, feed, db, now):
            continue

        h1 = feed.rates(symbol, config.TREND_TF, config.BARS[config.TREND_TF])
        h4 = feed.rates(symbol, config.BIAS_TF, config.BARS[config.BIAS_TF])
        tick = feed.tick(symbol)
        if h1 is None or h4 is None or tick is None:
            continue
        digits = feed.digits(symbol) or default_digits(base)
        sig = analyze(base, add_indicators(m15, config.ATR_PERIOD), add_indicators(h1),
                      add_indicators(h4), prices=(tick.bid, tick.ask), digits=digits)
        if not sig:
            log.info("%s: no setup", base)
            continue

        log.info("SIGNAL %s %s @ %s score %s", sig.side, base, sig.entry, sig.score)
        msg_id = send_message(format_signal(sig, digits, config.ENTRY_TF))
        db.add(sig, symbol, digits, msg_id)


def manage(feed, db):
    """Follow open signals. Returns how many are still open."""
    now = utcnow()
    tf = feed.track_tf
    step = timedelta(minutes=TF_MINUTES[tf])
    trades = db.open_trades()
    for t in trades:
        symbol = t["broker_symbol"]
        checked_before = t["last_checked"]
        last = datetime.fromisoformat(checked_before)
        if tf == "M1":
            count = max(2, min(int((now - last).total_seconds() // 60) + 2, 1500))
        else:
            count = config.BARS[tf]  # served from cache, no extra download
        bars = feed.rates(symbol, tf, count)
        tick = feed.tick(symbol)
        if tick is None:
            continue
        spread = tick.ask - tick.bid
        adj = spread if t["side"] == "SELL" else 0.0  # sells exit on the ask price

        events = []
        if bars is not None:
            # every candle that closed after the last check
            for bar_time, bar in bars[bars.index + step > last].iterrows():
                events += apply_bar(t, bar.high + adj, bar.low + adj)
                t["last_checked"] = (bar_time + step).isoformat()
                if t["status"] != "OPEN":
                    break
        if t["status"] == "OPEN":
            price = tick.bid if t["side"] == "BUY" else tick.ask
            events += apply_bar(t, price, price)
        if t["status"] == "OPEN" and now - datetime.fromisoformat(t["created_at"]) > timedelta(
                hours=config.SIGNAL_EXPIRY_HOURS):
            events += expire(t, tick.bid if t["side"] == "BUY" else tick.ask)

        if not events and t["last_checked"] == checked_before:
            continue  # nothing changed, skip the database write
        db.save(t)
        for kind, value in events:
            log.info("%s %s: %s %s", t["symbol"], t["side"], kind, value)
            send_message(format_event(t, kind, value), reply_to=t["message_id"])
    return sum(1 for t in trades if t["status"] == "OPEN")


def daily_summary(db, state):
    now = utcnow()
    today = now.date()
    if now.hour < config.DAILY_SUMMARY_HOUR_UTC or state.get("summary_day") == today:
        return
    state["summary_day"] = today
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    closed = db.closed_between(start.isoformat(), end.isoformat())
    created = db.count_since(start.isoformat())
    if created == 0 and not closed:
        return
    send_message(format_summary(today.isoformat(), created, closed, len(db.open_trades())))


def main():
    setup_logging()
    if config.PORT:
        web.start(config.PORT)   # bind first so Render sees the service as up
    feed = make_feed()
    feed.connect()
    db = make_tracker()
    for base in config.SYMBOLS:
        feed.resolve(base)

    log.info("Bot running: %s on %s. Ctrl+C to stop.", ", ".join(config.SYMBOLS), config.ENTRY_TF)
    send_message(f"🤖 Signal bot online · watching {', '.join(config.SYMBOLS)} on {config.ENTRY_TF}")

    last_bar, state = {}, {}
    while True:
        try:
            feed.ensure_connected()
            scan(feed, db, last_bar)
            open_count = manage(feed, db)
            daily_summary(db, state)
            web.mark_loop(open_signals=open_count)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            log.exception("Loop error (will retry)")
            web.mark_loop(error=repr(exc)[:300])
            time.sleep(10)
        time.sleep(config.POLL_SECONDS)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
