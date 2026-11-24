#!/usr/bin/env python3
"""The share images: the per-country cards in public/og/ (rendered offline by
scripts/dev/og_cards.mjs) and the site card public/og.png. In-process: no
network, a loopback server for the routes.

    /usr/bin/python3 scripts/test_og_cards.py

What it holds the code to:
  * one card per guide slug and nothing else in public/og/ but cards.json;
    each a baseline or progressive JPEG of 1200x630 (read from its SOF
    marker), at most 70 KB, 12 MB in all;
  * cards.json records, for every slug, exactly the facts the data gives
    today (display name, climate.json best months, curated or not): a
    climate.json rebuild or a renamed country fails here, naming the slugs
    to re-render (cd scripts/dev && ONLY=<slugs> node cdp.mjs ./og_cards.mjs);
  * a guide's og:image and twitter:image are https://wandergrade.com/og/<slug>.jpg,
    the homepage's and a list page's stay /og.png; a card whose facts no
    longer match, or whose file is missing, falls back to /og.png;
  * GET /og/<slug>.jpg: 200 image/jpeg, cached a day, not gzipped, not kept
    in memory; /og.png is an opaque PNG (no alpha channel) of 1200x630 under
    200 KB.
"""
import json
import os
import re
import struct
import sys
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import render_guide as rg  # noqa: E402
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
PUBLIC = os.path.join(ROOT, "public")
OG = os.path.join(PUBLIC, "og")
MAX_CARD, MAX_TOTAL = 70 * 1024, 12 * 1024 * 1024


def jpeg_size(data):
    """(width, height) from a JPEG's SOF marker, or None."""
    if data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None


d = rg._load()
slugs = d["slugs"]
files = sorted(os.listdir(OG)) if os.path.isdir(OG) else []
cards = sorted(f[:-4] for f in files if f.endswith(".jpg"))
extra = [f for f in files if not f.endswith(".jpg") and f != "cards.json"]
results.append(ok(cards == sorted(slugs) and not extra,
                  "one card per guide (%d of %d), nothing else but cards.json (missing %s, extra %s)"
                  % (len(cards), len(slugs), sorted(set(slugs) - set(cards))[:5], (sorted(set(cards) - set(slugs)) + extra)[:5])))
sizes, bad_dims, total = {}, [], 0
for s in cards:
    data = open(os.path.join(OG, s + ".jpg"), "rb").read()
    sizes[s] = len(data)
    total += len(data)
    if jpeg_size(data) != (1200, 630):
        bad_dims.append((s, jpeg_size(data)))
results.append(ok(not bad_dims, "every card is a 1200x630 JPEG (bad: %s)" % bad_dims[:5]))
big = sorted(((n, s) for s, n in sizes.items() if n > MAX_CARD), reverse=True)
results.append(ok(not big and total <= MAX_TOTAL,
                  "each card at most 70 KB (largest %d KB), %.1f MB in all (at most 12)"
                  % (max(sizes.values() or [0]) // 1024, total / 1048576)))

manifest = json.load(open(os.path.join(OG, "cards.json"), encoding="utf-8"))


def want(slug, iso):
    c = d["clim"].get(iso) or {}
    return {"iso": iso, "name": d["names"].get(iso) or slug,
            "best": [m for m in c.get("best") or [] if 1 <= m <= 12], "curated": bool(c.get("curated"))}


stale = sorted(s for s, iso in slugs.items() if manifest.get(s) != want(s, iso))
results.append(ok(not stale and set(manifest) == set(slugs),
                  "cards.json holds today's facts for every guide (stale: %s%s)"
                  % (",".join(stale[:12]), " -> cd scripts/dev && ONLY=%s CDP_TIMEOUT=55 node cdp.mjs ./og_cards.mjs"
                     % ",".join(stale) if stale else "")))

# --- the pages -------------------------------------------------------------------------
img = lambda doc: (re.findall(r'<meta property="og:image" content="([^"]+)"', doc),
                   re.findall(r'<meta name="twitter:image" content="([^"]+)"', doc))
for iso in ("TH", "GB-SCT", "CI"):
    slug = d["iso2slug"][iso]
    u = "https://wandergrade.com/og/%s.jpg" % slug
    results.append(ok(img(server._render_index(iso).decode("utf-8")) == ([u], [u]),
                      "/guide/%s: og:image and twitter:image are its card" % slug))
home = img(server._render_index(None).decode("utf-8"))
shell = re.findall(r'<meta property="og:image" content="([^"]+)"',
                   server._render_privacy_page().decode("utf-8"))
results.append(ok(home == (["https://wandergrade.com/og.png"], ["https://wandergrade.com/og.png"])
                  and shell == ["https://wandergrade.com/og.png"],
                  "the homepage and the shell pages keep /og.png"))

real_clim, real_isfile = d["clim"]["TH"], os.path.isfile
try:
    d["clim"]["TH"] = dict(real_clim, best=[1, 2, 3])
    server._og_cards_memo[0] = None
    moved = img(server._render_index("TH").decode("utf-8"))[0]
    d["clim"]["TH"] = real_clim
    server.os.path.isfile = lambda p: False if p.endswith("japan.jpg") else real_isfile(p)
    server._og_cards_memo[0] = None
    gone = img(server._render_index("JP").decode("utf-8"))[0]
finally:
    d["clim"]["TH"] = real_clim
    server.os.path.isfile = real_isfile
    server._og_cards_memo[0] = None
results.append(ok(moved == ["https://wandergrade.com/og.png"] and gone == ["https://wandergrade.com/og.png"],
                  "a card whose best months moved, or whose file is gone, falls back to /og.png"))

# --- the files as served ---------------------------------------------------------------
server.Handler.log_message = lambda self, *a: None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
try:
    req = urllib.request.Request(BASE + "/og/thailand.jpg", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=20) as r:
        st, hd, body = r.status, dict(r.headers), r.read()
finally:
    httpd.shutdown()
results.append(ok(st == 200 and hd.get("Content-Type") == "image/jpeg" and hd.get("Cache-Control") == "public, max-age=86400"
                  and "Content-Encoding" not in hd and body == open(os.path.join(OG, "thailand.jpg"), "rb").read()
                  and os.path.join(OG, "thailand.jpg") not in server._static_memo,
                  "GET /og/thailand.jpg: image/jpeg, a day's cache, not gzipped, not kept in memory"))

png = open(os.path.join(PUBLIC, "og.png"), "rb").read()
w, h, depth, ctype = struct.unpack(">IIBB", png[16:26])
results.append(ok(png[:8] == b"\x89PNG\r\n\x1a\n" and (w, h) == (1200, 630) and ctype in (0, 2, 3)
                  and b"tRNS" not in png and len(png) < 200 * 1024,
                  "og.png: an opaque %dx%d PNG (colour type %d, no alpha), %d KB" % (w, h, ctype, len(png) // 1024)))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
