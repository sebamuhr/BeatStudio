#!/usr/bin/env python3
"""
Beatbox local sync server.

Serves the PWA over HTTPS on your LAN (so the phone can use the mic + install the
app) and accepts grooves the phone uploads when it's back on the same network.
Uploaded grooves are written as plain files under ./synced/ so they live on the
computer, and the app (on the computer) lists them via the API.

Run:  python3 server.py            # https on 0.0.0.0:8443
      python3 server.py --port 9000 --http   # plain http (localhost only; no mic)

First generate certs once:  ./make-cert.sh
"""
import argparse
import json
import os
import re
import ssl
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
SYNC_DIR = os.path.join(ROOT, "synced")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
MAX_BODY = 256 * 1024 * 1024  # 256 MB ceiling for an uploaded groove (audio included)


def _project_files():
    if not os.path.isdir(SYNC_DIR):
        return []
    return sorted(f for f in os.listdir(SYNC_DIR) if f.endswith(".json"))


def _summarize(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        return None
    state = data.get("state") or {}
    return {
        "id": data.get("id"),
        "name": data.get("name"),
        "createdAt": data.get("createdAt"),
        "bpm": state.get("bpm"),
        "tracks": len(state.get("lanes") or []),
        "notes": len(state.get("events") or []),
        "hasAudio": bool(data.get("audio")),
        "bytes": os.path.getsize(path),
    }


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=ROOT, **kw)

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    # CORS so the app works even if loaded from a different origin/port.
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        if self.path == "/api/ping":
            return self._json(200, {"ok": True, "name": "beatbox-sync", "time": time.time()})
        if self.path == "/api/projects":
            items = [s for s in (_summarize(os.path.join(SYNC_DIR, f)) for f in _project_files()) if s]
            return self._json(200, {"ok": True, "projects": items})
        m = re.match(r"^/api/projects/([^/]+)$", self.path)
        if m:
            pid = m.group(1)
            if not ID_RE.match(pid):
                return self._json(400, {"ok": False, "error": "bad id"})
            path = os.path.join(SYNC_DIR, pid + ".json")
            if not os.path.isfile(path):
                return self._json(404, {"ok": False, "error": "not found"})
            with open(path, "rb") as fh:
                body = fh.read()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self._cors()
            self.end_headers()
            return self.wfile.write(body)
        # otherwise serve static files from the app folder
        return super().do_GET()

    def do_POST(self):
        if self.path != "/api/projects":
            return self._json(404, {"ok": False, "error": "no such endpoint"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self._json(400, {"ok": False, "error": "bad length"})
        if length <= 0 or length > MAX_BODY:
            return self._json(413, {"ok": False, "error": "empty or too large"})
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return self._json(400, {"ok": False, "error": "invalid json"})

        pid = str(data.get("id") or "")
        if not ID_RE.match(pid):
            return self._json(400, {"ok": False, "error": "missing/invalid id"})
        os.makedirs(SYNC_DIR, exist_ok=True)
        path = os.path.join(SYNC_DIR, pid + ".json")
        if os.path.isfile(path):
            # idempotent: re-uploading the same groove is a no-op success
            return self._json(200, {"ok": True, "id": pid, "duplicate": True})
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)
        sys.stderr.write("  + saved groove %s (%d bytes)\n" % (pid, len(raw)))
        return self._json(200, {"ok": True, "id": pid})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8443)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--http", action="store_true", help="plain HTTP (localhost only; mic won't work)")
    ap.add_argument("--cert", default=os.path.join(ROOT, "certs", "fullchain.crt"))
    ap.add_argument("--key", default=os.path.join(ROOT, "certs", "server.key"))
    args = ap.parse_args()

    os.makedirs(SYNC_DIR, exist_ok=True)
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)

    scheme = "http"
    if not args.http:
        if not (os.path.isfile(args.cert) and os.path.isfile(args.key)):
            sys.exit("Missing certs. Run ./make-cert.sh first (or pass --http for a localhost-only test).")
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=args.cert, keyfile=args.key)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    lan = os.popen("hostname -I").read().split()
    lan_ip = lan[0] if lan else "127.0.0.1"
    print("Beatbox sync server on %s://%s:%d" % (scheme, args.host, args.port))
    print("  Phone:    %s://%s:%d/Beatbox%%20to%%20MIDI.dc.html" % (scheme, lan_ip, args.port))
    print("  Computer: %s://localhost:%d/Beatbox%%20to%%20MIDI.dc.html" % (scheme, args.port))
    print("  Grooves land in: %s" % SYNC_DIR)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
