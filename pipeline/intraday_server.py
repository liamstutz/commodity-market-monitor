"""Loopback-only companion. Private observations never enter the public Pages build."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit

from intraday import INSTRUMENTS, UTC, candidates, ema_points, fetch_yahoo, iso, merge_bars, normalize, replay, update_watch

ROOT = Path(__file__).resolve().parent.parent
PRIVATE = ROOT / ".private" / "intraday"
SERVICE = "commodity-monitor-intraday-v1"
REFRESH = 300

def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, allow_nan=False, separators=(",", ":")), encoding="utf-8")
    temp.replace(path)

class Monitor:
    def __init__(self, folder=PRIVATE, fetcher=fetch_yahoo):
        self.folder, self.fetcher = Path(folder), fetcher
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.states = {}
        self.refreshing = False
        self.next_refresh = None
        self.storage_error = None
        for symbol in INSTRUMENTS:
            state = {"bars": [], "watch": [], "symbol": symbol, "status": "waiting"}
            path = self.path(symbol)
            try:
                if path.exists():
                    state = json.loads(path.read_text(encoding="utf-8"))
                    if state.get("symbol") != symbol:
                        raise ValueError("Wrong cached symbol")
                    state["bars"], _ = normalize(state["bars"])
                    state["status"] = "cached"
            except (ValueError, KeyError, OSError) as error:
                state = {"bars": [], "watch": [], "symbol": symbol, "status": "error",
                         "error": "Could not read local cache: " + str(error)[:200]}
            self.states[symbol] = state

    def path(self, symbol):
        return self.folder / (symbol.split("=")[0] + ".json")

    def refresh(self, now=None):
        now = now or dt.datetime.now(UTC)
        with self.lock:
            if self.refreshing:
                return
            self.refreshing = True
            previous = {key: dict(value) for key, value in self.states.items()}
        def fetch(symbol):
            state = previous[symbol]
            try:
                new = self.fetcher(symbol, initial=not state["bars"], now=now)
                bars = merge_bars(state["bars"], new["bars"])
                return symbol, {**state, **new, "bars": bars, "status": "connected",
                                "error": None, "last_success": now.isoformat(), "last_attempt": now.isoformat(),
                                "watch": update_watch(state["watch"], bars, symbol, now, True)}
            except Exception as error:
                return symbol, {**state, "status": "cached" if state["bars"] else "error",
                                "last_attempt": now.isoformat(), "error": str(error)[:240],
                                "watch": update_watch(state["watch"], state["bars"], symbol, now, False)}
        try:
            with ThreadPoolExecutor(max_workers=3) as pool:
                for symbol, state in pool.map(fetch, INSTRUMENTS):
                    try:
                        atomic(self.path(symbol), state)
                    except OSError as error:
                        self.storage_error = "Local records could not be saved: " + str(error)[:200]
                    with self.lock:
                        self.states[symbol] = state
        finally:
            with self.lock:
                self.refreshing = False
                self.next_refresh = dt.datetime.now(UTC).timestamp() + REFRESH

    def loop(self):
        while not self.stop.is_set():
            self.refresh()
            self.stop.wait(REFRESH)

    def view(self, symbol="CL=F", anchor="09:30", holding=60, slippage=1.0, fee=5.0):
        if symbol not in INSTRUMENTS:
            raise ValueError("Unsupported commodity")
        now = dt.datetime.now(UTC)
        with self.lock:
            state = dict(self.states[symbol])
            statuses = [self.health(key, val, now) for key, val in self.states.items()]
            refreshing, next_refresh = self.refreshing, self.next_refresh
        bars = state["bars"]
        result = replay(bars, symbol, anchor, holding, slippage, fee)
        closes = [[iso(row[0]), row[4]] for row in bars[-288:]]
        emas = [[iso(stamp), value] for stamp, value in ema_points(bars)[-288:]]
        current = candidates(bars, anchor)
        return {"schema": SERVICE, "generated": now.isoformat(), "symbol": symbol,
                "instrument": INSTRUMENTS[symbol], "source": self.health(symbol, state, now),
                "sources": statuses, "analysis": result, "watch": state["watch"],
                "chart": {"close": closes, "ema": emas},
                "last_signal": {**current[-1], "signal_time": iso(current[-1]["signal_time"])} if current else None,
                "refresh_seconds": REFRESH, "refreshing": refreshing,
                "next_refresh": iso(next_refresh) if next_refresh else None, "storage_error": self.storage_error}

    @staticmethod
    def health(symbol, state, now):
        bars = state["bars"]
        end = bars[-1][0] + 300 if bars else None
        return {"symbol": symbol, "name": INSTRUMENTS[symbol]["name"], "bars": len(bars),
                "status": state["status"], "provider_name": state.get("provider_name", symbol),
                "last_bar_end": iso(end) if end else None,
                "age_minutes": round((now.timestamp() - end) / 60, 1) if end else None,
                "first_bar": iso(bars[0][0]) if bars else None, "last_success": state.get("last_success"),
                "last_attempt": state.get("last_attempt"), "error": state.get("error"),
                "skipped": state.get("skipped", 0), "delay_minutes": None}

def handler_for(monitor):
    class Handler(BaseHTTPRequestHandler):
        def allowed(self):
            hosts = {"127.0.0.1:" + str(self.server.server_port), "localhost:" + str(self.server.server_port)}
            origin = self.headers.get("Origin")
            return (self.headers.get("Host") in hosts
                    and (not origin or origin in {"http://" + h for h in hosts})
                    and (self.headers.get("Sec-Fetch-Site") != "cross-site"
                         or (urlsplit(self.path).path in ("/", "/intraday.html")
                             and self.headers.get("Sec-Fetch-Mode") == "navigate")))

        def respond(self, status, body, content_type="application/json"):
            encoded = body if isinstance(body, bytes) else json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            if not self.allowed():
                self.respond(403, {"error": "Local origin required"})
                return
            parsed = urlsplit(self.path)
            if parsed.path == "/api/health":
                self.respond(200, {"service": SERVICE, "refresh_seconds": REFRESH})
                return
            if parsed.path == "/api/view":
                try:
                    q = parse_qs(parsed.query)
                    arg = lambda key, default: q.get(key, [default])[0]
                    view = monitor.view(arg("symbol", "CL=F"), arg("anchor", "09:30"),
                                        int(arg("holding", "60")), float(arg("slippage", "1")), float(arg("fee", "5")))
                    self.respond(200, view)
                except (ValueError, OverflowError):
                    self.respond(400, {"error": "Invalid research settings"})
                return
            static = {"/": "intraday.html", "/intraday.html": "intraday.html",
                      "/intraday.js": "intraday.js", "/intraday.css": "intraday.css",
                      "/app2.js": "app2.js", "/style.css": "style.css"}
            if parsed.path in static:
                path = ROOT / "site" / static[parsed.path]
                self.respond(200, path.read_bytes(), (mimetypes.guess_type(path.name)[0] or "application/octet-stream") + "; charset=utf-8")
                return
            self.respond(404, {"error": "Not found"})

        def do_POST(self):
            if not self.allowed() or self.headers.get("Content-Type") != "application/json":
                self.respond(403, {"error": "Local JSON request required"})
                return
            if self.path != "/api/stop":
                self.respond(404, {"error": "Not found"})
                return
            self.respond(200, {"stopped": True})
            monitor.stop.set()
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, *_):
            pass
    return Handler

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--once", action="store_true", help="Refresh private caches once and exit")
    parser.add_argument("--offline", action="store_true", help="Serve existing private caches without network calls")
    parser.add_argument("--data-dir", type=Path, default=PRIVATE)
    args = parser.parse_args()
    monitor = Monitor(args.data_dir)
    if args.once:
        monitor.refresh()
        for source in monitor.view()["sources"]:
            print(source["symbol"], source["status"], source["bars"], "completed bars", source["error"] or "")
        return 0 if all(s["status"] == "connected" for s in monitor.states.values()) else 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler_for(monitor))
    if not args.offline:
        threading.Thread(target=monitor.loop, daemon=True).start()
    print("Private intraday monitor: http://127.0.0.1:" + str(args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop.set()
        server.server_close()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
