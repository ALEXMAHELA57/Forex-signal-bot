"""Signal storage in Supabase (Postgres) through its REST API.

Same methods as the SQLite Tracker, so the bot doesn't care which one it uses.
Uses the server-side secret key (service_role), which bypasses Row Level Security:
keep it only in the bot's environment variables, never in frontend code.
"""
import logging
import time
from datetime import datetime, timezone

import requests

from . import config
from .utils import utcnow

log = logging.getLogger(__name__)

TIME_FIELDS = ("created_at", "last_checked", "closed_at")


def _to_db_time(value):
    """Naive-UTC ISO string -> explicit UTC timestamp for Postgres."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _from_db_time(value):
    """Postgres timestamptz string -> naive-UTC ISO string (what the bot uses)."""
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


class SupabaseTracker:
    def __init__(self):
        if not config.SUPABASE_URL or not config.SUPABASE_SERVICE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY are required for STORAGE=supabase")
        self.url = f"{config.SUPABASE_URL.rstrip('/')}/rest/v1/{config.SUPABASE_TABLE}"
        key = config.SUPABASE_SERVICE_KEY
        self.headers = {"apikey": key, "Content-Type": "application/json"}
        if key.startswith("eyJ"):  # legacy JWT service_role key
            self.headers["Authorization"] = f"Bearer {key}"
        self.http = requests.Session()
        self._request("GET", params=[("select", "id"), ("limit", "1")])  # fail fast if misconfigured
        log.info("Storing signals in Supabase table '%s'", config.SUPABASE_TABLE)

    def _request(self, method, params=None, json=None, prefer=None):
        headers = dict(self.headers)
        if prefer:
            headers["Prefer"] = prefer
        last_error = None
        for attempt in range(3):
            try:
                resp = self.http.request(method, self.url, params=params, json=json,
                                         headers=headers, timeout=20)
                if resp.status_code < 300:
                    return resp.json() if resp.content else None
                last_error = f"{resp.status_code} {resp.text[:300]}"
                if resp.status_code < 500:
                    break  # bad key / missing table / bad column: retrying won't help
            except requests.RequestException as exc:
                last_error = str(exc)
            time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"Supabase {method} failed: {last_error}")

    @staticmethod
    def _row(row):
        t = dict(row)
        for f in TIME_FIELDS:
            t[f] = _from_db_time(t.get(f))
        t["tps"] = list(t["tps"] or [])
        return t

    # --- Tracker interface ------------------------------------------------------------
    def add(self, sig, broker_symbol, digits, message_id):
        now = _to_db_time(utcnow().isoformat())
        rows = self._request("POST", json={
            "symbol": sig.symbol, "broker_symbol": broker_symbol, "side": sig.side,
            "entry": sig.entry, "sl": sig.sl, "sl_initial": sig.sl, "tps": list(sig.tps),
            "score": sig.score, "reasons": " · ".join(sig.reasons), "digits": digits,
            "created_at": now, "last_checked": now, "status": "OPEN", "tp_hit": 0,
            "message_id": message_id,
        }, prefer="return=representation")
        return rows[0]["id"] if rows else None

    def save(self, t):
        body = {"sl": t["sl"], "tp_hit": t["tp_hit"], "status": t["status"],
                "result_r": t.get("result_r"), "last_checked": _to_db_time(t["last_checked"])}
        if t["status"] != "OPEN" and not t.get("closed_at"):
            body["closed_at"] = _to_db_time(utcnow().isoformat())
            t["closed_at"] = utcnow().isoformat()
        self._request("PATCH", params=[("id", f"eq.{t['id']}")], json=body,
                      prefer="return=minimal")

    def open_trades(self, symbol=None):
        params = [("select", "*"), ("status", "eq.OPEN"), ("order", "created_at.asc")]
        if symbol:
            params.append(("symbol", f"eq.{symbol}"))
        return [self._row(r) for r in self._request("GET", params=params)]

    def last_signal_time(self, symbol):
        rows = self._request("GET", params=[
            ("select", "created_at"), ("symbol", f"eq.{symbol}"),
            ("order", "created_at.desc"), ("limit", "1")])
        return _from_db_time(rows[0]["created_at"]) if rows else None

    def count_since(self, iso_time):
        rows = self._request("GET", params=[
            ("select", "id"), ("created_at", f"gte.{_to_db_time(iso_time)}")])
        return len(rows)

    def closed_between(self, start_iso, end_iso):
        rows = self._request("GET", params=[
            ("select", "*"), ("status", "neq.OPEN"),
            ("closed_at", f"gte.{_to_db_time(start_iso)}"),
            ("closed_at", f"lt.{_to_db_time(end_iso)}")])
        return [self._row(r) for r in rows]
