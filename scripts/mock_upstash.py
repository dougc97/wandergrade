"""Minimal in-memory stand-in for Upstash Redis's REST API, so the accounts
flow can be exercised end-to-end without real credentials."""
import json, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer

DB = {}       # key -> (value, expires_at|None)
LOCK = threading.Lock()


def _alive(k):
    v = DB.get(k)
    if not v:
        return None
    val, exp = v
    if exp and time.time() > exp:
        DB.pop(k, None)
        return None
    return val


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        # test-only: dump live keys so the harness can find the magic token
        with LOCK:
            body = json.dumps([k for k in list(DB) if _alive(k)]).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        cmd = json.loads(self.rfile.read(n).decode())
        op = cmd[0].upper()
        with LOCK:
            if op == "SET":
                ttl = None
                if len(cmd) >= 5 and cmd[3].upper() == "EX":
                    ttl = time.time() + int(cmd[4])
                DB[cmd[1]] = (cmd[2], ttl)
                res = "OK"
            elif op == "GET":
                res = _alive(cmd[1])
            elif op == "GETEX":
                res = _alive(cmd[1])
                if res is not None and len(cmd) >= 4 and cmd[2].upper() == "EX":
                    DB[cmd[1]] = (res, time.time() + int(cmd[3]))
            elif op == "TTL":
                v = DB.get(cmd[1])
                res = -2 if _alive(cmd[1]) is None else (
                    -1 if v[1] is None else int(v[1] - time.time()))
            elif op == "DEL":
                res = 1 if DB.pop(cmd[1], None) else 0
            elif op == "INCR":
                cur = int(_alive(cmd[1]) or 0) + 1
                old = DB.get(cmd[1])
                DB[cmd[1]] = (str(cur), old[1] if old else None)
                res = cur
            elif op == "EXPIRE":
                v = DB.get(cmd[1])
                if v:
                    DB[cmd[1]] = (v[0], time.time() + int(cmd[2]))
                res = 1
            else:
                res = None
        body = json.dumps({"result": res}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 8899), H).serve_forever()
