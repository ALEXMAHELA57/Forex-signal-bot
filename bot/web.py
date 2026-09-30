"""Tiny web server so the bot can live on a Render free web service.

Render needs something listening on $PORT, and a free uptime monitor (UptimeRobot,
cron-job.org ...) hitting /health every 5 minutes keeps the service from sleeping.
/health returns 503 if the main loop has stopped, so the monitor also alerts you.
"""
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .utils import utcnow

log = logging.getLogger(__name__)

STATUS = {"started": None, "last_loop": None, "loops": 0, "last_error": None, "open_signals": None}
STALE_SECONDS = 300


def mark_loop(open_signals=None, error=None):
    STATUS["last_loop"] = utcnow()
    STATUS["loops"] += 1
    if open_signals is not None:
        STATUS["open_signals"] = open_signals
    if error:
        STATUS["last_error"] = f"{utcnow():%Y-%m-%d %H:%M} UTC: {error}"


def _payload():
    now = utcnow()
    last = STATUS["last_loop"]
    healthy = last is None or (now - last).total_seconds() < STALE_SECONDS  # None = still starting
    body = {
        "status": "ok" if healthy else "stalled",
        "started_utc": STATUS["started"].isoformat() if STATUS["started"] else None,
        "last_loop_utc": last.isoformat() if last else None,
        "loops": STATUS["loops"],
        "open_signals": STATUS["open_signals"],
        "last_error": STATUS["last_error"],
    }
    return (200 if healthy else 503), json.dumps(body).encode()


class _Handler(BaseHTTPRequestHandler):
    def _send(self, include_body):
        code, body = _payload()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def do_GET(self):
        self._send(True)

    def do_HEAD(self):
        self._send(False)

    def log_message(self, *args):
        pass  # keep logs clean; the pinger hits this every few minutes


def start(port):
    STATUS["started"] = utcnow()
    server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("Health endpoint listening on port %s (/health)", port)
    return server
