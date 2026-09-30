"""Signal storage (SQLite) and trade management: TP/SL hits, breakeven, results in R.

Results assume the position is split into equal parts, one closed at each TP.
With TP = 1R/2R/3R and SL moved to entry after TP1:
  SL before TP1        -> -1.00R
  TP1 then breakeven   -> +0.33R
  TP2 then breakeven   -> +1.00R
  all three TPs        -> +2.00R
"""
import json
import os
import sqlite3

from . import config
from .utils import utcnow


def _risk(trade):
    return abs(trade["entry"] - trade["sl_initial"]) or 1e-12


def realized_r(trade, exit_price):
    d = 1 if trade["side"] == "BUY" else -1
    risk = _risk(trade)
    n = len(trade["tps"])
    k = trade["tp_hit"]
    tp_r = [abs(tp - trade["entry"]) / risk for tp in trade["tps"]]
    rest = d * (exit_price - trade["entry"]) / risk
    return round((sum(tp_r[:k]) + (n - k) * rest) / n, 2)


def apply_bar(trade, high, low, move_be=None):
    """Update an open trade with one price bar. Mutates trade, returns events.

    Stop is checked before targets inside the same bar (conservative).
    Events: ("TP", n), ("MOVE_BE", None), ("CLOSED_TP", r), ("SL", r), ("BE", r)
    """
    move_be = config.MOVE_SL_TO_BE_AFTER_TP1 if move_be is None else move_be
    events = []
    if trade["status"] != "OPEN":
        return events
    buy = trade["side"] == "BUY"

    if (low <= trade["sl"]) if buy else (high >= trade["sl"]):
        r = realized_r(trade, trade["sl"])
        at_be = trade["tp_hit"] > 0 and abs(trade["sl"] - trade["entry"]) < 1e-9
        trade["status"] = "BE" if at_be else "SL"
        trade["result_r"] = r
        events.append((trade["status"], r))
        return events

    for k in range(trade["tp_hit"], len(trade["tps"])):
        tp = trade["tps"][k]
        if (high >= tp) if buy else (low <= tp):
            trade["tp_hit"] = k + 1
            events.append(("TP", k + 1))
            if k == 0 and move_be:
                trade["sl"] = trade["entry"]
                events.append(("MOVE_BE", None))
        else:
            break

    if trade["tp_hit"] == len(trade["tps"]):
        r = realized_r(trade, trade["tps"][-1])
        trade["status"] = "TP"
        trade["result_r"] = r
        events.append(("CLOSED_TP", r))
    return events


def expire(trade, price):
    trade["result_r"] = realized_r(trade, price)
    trade["status"] = "EXPIRED"
    return [("EXPIRED", trade["result_r"])]


class Tracker:
    def __init__(self, path=None):
        path = path or config.DB_PATH
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT, broker_symbol TEXT, side TEXT,
                entry REAL, sl REAL, sl_initial REAL, tps TEXT,
                score INTEGER, reasons TEXT, digits INTEGER,
                created_at TEXT, last_checked TEXT, closed_at TEXT,
                status TEXT, tp_hit INTEGER DEFAULT 0, result_r REAL,
                message_id INTEGER
            )""")
        self.conn.commit()

    @staticmethod
    def _row(row):
        t = dict(row)
        t["tps"] = json.loads(t["tps"])
        return t

    def add(self, sig, broker_symbol, digits, message_id):
        now = utcnow().isoformat()
        cur = self.conn.execute(
            """INSERT INTO signals (symbol, broker_symbol, side, entry, sl, sl_initial, tps,
                   score, reasons, digits, created_at, last_checked, status, message_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?, 'OPEN', ?)""",
            (sig.symbol, broker_symbol, sig.side, sig.entry, sig.sl, sig.sl,
             json.dumps(sig.tps), sig.score, " · ".join(sig.reasons), digits,
             now, now, message_id))
        self.conn.commit()
        return cur.lastrowid

    def save(self, t):
        closed_at = utcnow().isoformat() if t["status"] != "OPEN" else None
        self.conn.execute(
            """UPDATE signals SET sl=?, tp_hit=?, status=?, result_r=?,
                   last_checked=?, closed_at=COALESCE(closed_at, ?) WHERE id=?""",
            (t["sl"], t["tp_hit"], t["status"], t.get("result_r"),
             t["last_checked"], closed_at, t["id"]))
        self.conn.commit()

    def open_trades(self, symbol=None):
        q, args = "SELECT * FROM signals WHERE status='OPEN'", ()
        if symbol:
            q, args = q + " AND symbol=?", (symbol,)
        return [self._row(r) for r in self.conn.execute(q, args)]

    def last_signal_time(self, symbol):
        row = self.conn.execute(
            "SELECT MAX(created_at) FROM signals WHERE symbol=?", (symbol,)).fetchone()
        return row[0]

    def count_since(self, iso_time):
        return self.conn.execute(
            "SELECT COUNT(*) FROM signals WHERE created_at >= ?", (iso_time,)).fetchone()[0]

    def closed_between(self, start_iso, end_iso):
        rows = self.conn.execute(
            "SELECT * FROM signals WHERE status!='OPEN' AND closed_at >= ? AND closed_at < ?",
            (start_iso, end_iso))
        return [self._row(r) for r in rows]


def make_tracker():
    """SQLite file by default; Supabase when STORAGE=supabase."""
    if config.STORAGE == "supabase":
        from .supabase_store import SupabaseTracker
        return SupabaseTracker()
    return Tracker()
