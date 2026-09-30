"""Pip sizes, price formatting and Telegram message text."""
from datetime import datetime, timezone


def utcnow():
    """Naive UTC datetime (all times in the bot are naive UTC)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def pip_size(symbol):
    s = symbol.upper()
    if "XAU" in s:
        return 0.1
    if "JPY" in s:
        return 0.01
    return 0.0001


def default_digits(symbol):
    s = symbol.upper()
    if "XAU" in s:
        return 2
    if "JPY" in s:
        return 3
    return 5


def to_pips(symbol, price_diff):
    return abs(price_diff) / pip_size(symbol)


def fmt(price, digits):
    return f"{price:.{digits}f}"


def confidence_label(score):
    if score >= 80:
        return "Strong"
    if score >= 70:
        return "Good"
    return "Moderate"


def format_signal(sig, digits, timeframe="M15"):
    buy = sig.side == "BUY"
    icon = "🟢" if buy else "🔴"
    risk = abs(sig.entry - sig.sl)
    lines = [
        f"{icon} <b>{sig.side} {sig.symbol}</b>  ·  {timeframe}",
        "",
        f"Entry: <code>{fmt(sig.entry, digits)}</code>",
        f"Stop Loss: <code>{fmt(sig.sl, digits)}</code>  ({to_pips(sig.symbol, risk):.1f} pips)",
    ]
    for i, tp in enumerate(sig.tps, 1):
        r = abs(tp - sig.entry) / risk if risk else 0
        lines.append(
            f"TP{i}: <code>{fmt(tp, digits)}</code>  "
            f"({to_pips(sig.symbol, tp - sig.entry):.1f} pips · {r:.1f}R)"
        )
    lines += [
        "",
        f"Confidence: <b>{confidence_label(sig.score)}</b> ({sig.score}/100)",
        "Why: " + " · ".join(sig.reasons),
        "",
        "<i>Move SL to entry when TP1 hits. Risk max 1–2% per trade. "
        "Not financial advice.</i>",
    ]
    return "\n".join(lines)


def format_event(trade, kind, value=None):
    sym, side = trade["symbol"], trade["side"]
    head = f"{sym} {side}"
    if kind == "TP":
        return f"✅ <b>{head}: TP{value} hit</b>"
    if kind == "MOVE_BE":
        return f"🔒 {head}: move Stop Loss to entry (breakeven)"
    if kind == "CLOSED_TP":
        return f"🎯 <b>{head}: all targets hit</b> — closed {value:+.2f}R"
    if kind == "SL":
        return f"❌ <b>{head}: Stop Loss hit</b> — {value:+.2f}R"
    if kind == "BE":
        return f"⚪ {head}: closed at breakeven after TP{trade['tp_hit']} — {value:+.2f}R"
    if kind == "EXPIRED":
        return f"⏱ {head}: signal expired, closed at market — {value:+.2f}R"
    return f"{head}: {kind} {value}"


def format_summary(day, created, closed, still_open):
    wins = [t for t in closed if (t["result_r"] or 0) > 0]
    losses = [t for t in closed if (t["result_r"] or 0) < 0]
    total = sum(t["result_r"] or 0 for t in closed)
    rate = f"{len(wins) / len(closed) * 100:.0f}%" if closed else "–"
    return "\n".join([
        f"📊 <b>Daily summary · {day}</b>",
        f"New signals: {created}",
        f"Closed: {len(closed)}  (wins {len(wins)} · losses {len(losses)} · win rate {rate})",
        f"Result: <b>{total:+.2f}R</b>",
        f"Still open: {still_open}",
    ])
