#!/usr/bin/env python3
"""public/sw.js page navigations, run in Node against a stand-in service
worker global (fetch, caches, Response) — offline, a second or two.

    /usr/bin/python3 scripts/test_sw_fallback.py

What it holds sw.js to: a navigation answered 200 is returned and stored by
path; one answered 503 (the server shedding a crawl's load) or 502 (the
origin restarting behind Cloudflare) is served from the page's cached copy
when there is one, else the error itself goes through (never the home
shell for another page); a 404 is passed through untouched; a network
failure falls back to the page's copy, then to the cached home shell.
Skips (exit 0) when node is not installed.
"""
import json
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
const store = { "wg-pages-v3": new Map(), "wg-assets-v3": new Map() };
const keyOf = (k) => new URL(typeof k === "string" ? k : k.url, "https://wandergrade.com").href;
class Resp {
  constructor(body, status, headers) { this.body = body; this.status = status; this.type = "basic";
    this._h = headers || {}; this.headers = { get: (n) => this._h[n] || null }; }
  clone() { return new Resp(this.body, this.status, this._h); }
}
const caches = {
  open: async (name) => ({
    put: async (k, r) => { store[name].set(keyOf(k), r); },
    keys: async () => [...store[name].keys()].map((u) => ({ url: u })),
    delete: async (k) => store[name].delete(keyOf(k)),
    addAll: async () => {},
  }),
  match: async (k, opt) => store[opt.cacheName].get(keyOf(k)),
  keys: async () => Object.keys(store),
  delete: async () => true,
};
let net = null;
const handlers = {};
const self = { addEventListener: (t, f) => { handlers[t] = f; }, skipWaiting: () => {}, clients: { claim: () => {} } };
const location = { origin: "https://wandergrade.com" };
const fetch = async () => { if (net === "fail") throw new TypeError("offline"); return net.clone(); };
const Response = { error: () => new Resp("", 0) };
new Function("self", "caches", "fetch", "location", "Response", "URL", src)(self, caches, fetch, location, Response, URL);

async function nav(path, answer) {
  net = answer;
  let out = null; const waits = [];
  handlers.fetch({ request: { url: "https://wandergrade.com" + path, method: "GET", mode: "navigate",
                              headers: { has: () => false } },
                   respondWith: (p) => { out = p; }, waitUntil: (p) => waits.push(p) });
  const r = await out; await Promise.all(waits);
  return r ? [r.status, r.body] : null;
}
(async () => {
  const res = {};
  store["wg-pages-v3"].set("https://wandergrade.com/", new Resp("home shell", 200, {}));
  res.ok200 = await nav("/guide/japan?utm_source=x", new Resp("japan v1", 200, { "Cache-Control": "public, max-age=300" }));
  res.stored = store["wg-pages-v3"].has("https://wandergrade.com/guide/japan");
  res.busy_cached = await nav("/guide/japan", new Resp("busy", 503, { "Cache-Control": "no-store" }));
  res.bad_gateway_cached = await nav("/guide/japan", new Resp("502 page", 502, {}));
  res.busy_uncached = await nav("/guide/peru", new Resp("busy", 503, { "Cache-Control": "no-store" }));
  res.not_found = await nav("/guide/japan-x", new Resp("404 page", 404, { "Cache-Control": "no-store" }));
  res.offline_cached = await nav("/guide/japan", "fail");
  res.offline_uncached = await nav("/guide/chile", "fail");
  res.busy_not_stored = store["wg-pages-v3"].get("https://wandergrade.com/guide/japan").body;
  console.log(JSON.stringify(res));
})();
"""


def ok(cond, msg):
    print(("  PASS  " if cond else "  FAIL  ") + msg)
    return bool(cond)


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP: node not installed")
        return 0
    p = subprocess.run([node, "-e", HARNESS, os.path.join(ROOT, "public", "sw.js")],
                       capture_output=True, text=True, timeout=60)
    if p.returncode != 0:
        print(p.stderr)
        print("0/1 passed")
        return 1
    r = json.loads(p.stdout.strip().splitlines()[-1])
    results = [
        ok(r["ok200"] == [200, "japan v1"] and r["stored"],
           "a 200 navigation is returned and stored under its path (query dropped)"),
        ok(r["busy_cached"] == [200, "japan v1"] and r["bad_gateway_cached"] == [200, "japan v1"],
           "a 503 (load shed) or 502 (origin restarting) navigation serves the page's cached copy (%s, %s)"
           % (r["busy_cached"], r["bad_gateway_cached"])),
        ok(r["busy_uncached"] == [503, "busy"],
           "no cached copy of that page: the 503 itself goes through, not the home shell (%s)" % r["busy_uncached"]),
        ok(r["not_found"] == [404, "404 page"], "a 404 passes through untouched"),
        ok(r["offline_cached"] == [200, "japan v1"] and r["offline_uncached"] == [200, "home shell"],
           "offline: the page's copy, else the cached home shell, as before"),
        ok(r["busy_not_stored"] == "japan v1", "an error answer is never stored over the good copy"),
    ]
    print("\n%d/%d passed" % (sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
