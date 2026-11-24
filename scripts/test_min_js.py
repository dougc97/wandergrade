#!/usr/bin/env python3
"""/app.js served minified (review #34): public/app.min.js, written by
scripts/build_min_js.py (pinned esbuild) beside app.min.js.sha256, the hash
of the app.js it was built from. Runs both files under jsc
(scripts/appjs_harness.js) and the server in-process on loopback: no
network, no esbuild needed.

    /usr/bin/python3 scripts/test_min_js.py

What it holds the code to:
  * the committed copy is current: app.min.js.sha256 names app.js's own
    sha256 (after editing app.js, run /usr/bin/python3 scripts/build_min_js.py
    and commit the three files);
  * the copy keeps every top-level name: each function, const, let and var
    declared at the start of a line in app.js is, in app.min.js, the same
    kind of thing (typeof) with the same number of parameters, so the inline
    scripts, the jsc tests and the CDP checks that use them by name still
    reach them;
  * and draws the same: Top Picks for four months, every country's pieces
    (PPP note, currency and advisory marks, season tags and strips) and the
    grades and fares lines of 30 guides come out the same from both files;
  * the guard (_app_js_file): the copy goes out for /app.js only while the
    stored hash is app.js's sha256; app.js edited, the hash file or the copy
    missing, or FX_MIN_JS=0, and app.js goes out as written; each new choice
    writes one [min-js] line, however many requests follow;
  * the stamp (_app_js_version): app.js's mtime, plus 8 digits of the copy's
    sha256 while the copy goes out, so it changes whenever the bytes served
    do (a rebuild of the same app.js, the switch);
  * the routes: /app.js?v= is the copy, immutable, gzipped; a stale copy is
    never served at any URL (/app.min.js and its hash file are 404s); the
    homepage's stamp is _app_js_version's.
"""
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402
from fxtracker import render_guide  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
readb = lambda p: open(p, "rb").read()
SRC, MIN, SHA = P("public", "app.js"), P("public", "app.min.js"), P("public", "app.min.js.sha256")
sha = lambda b: hashlib.sha256(b).hexdigest()

# --- the committed copy is current ------------------------------------------------------
stored = open(SHA, encoding="utf-8").read().split()[0] if os.path.isfile(SHA) else ""
current = os.path.isfile(MIN) and stored == sha(readb(SRC))
results.append(ok(current, "app.min.js is built from this app.js (%s)%s"
                  % (stored[:12] or "no hash", "" if current else
                     ": run /usr/bin/python3 scripts/build_min_js.py and commit public/app.min.js*")))

# --- both files under jsc ---------------------------------------------------------------
APP = open(SRC, encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
NAMES = []
for m in re.finditer(r"^(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)|^(?:const|let|var)\s+([A-Za-z_$][\w$]*)", APP, re.M):
    n = m.group(1) or m.group(2)
    if n not in NAMES:
        NAMES.append(n)
FIX = {"rates": load("scripts", "parity", "fixture_rates.json"),
       "advisories": load("scripts", "parity", "fixture_advisories.json"),
       "flights": load("scripts", "parity", "fixture_flights.json"),
       "fv": load("scripts", "parity", "fixture_flight_value.json"),
       "ppp": load("public", "ppp.json"), "climate": load("public", "climate.json"),
       "activities": load("public", "activities.json"), "world": load("public", "world.geojson"),
       "slugs": load("public", "slugs.json")}
GUIDES = [iso for _s, iso in render_guide.all_slugs()][::6][:30]
CURVES = {iso: {"origin": "US", "hub": FIX["flights"]["hub"],
                "months": {k: {"price": v[0], "dest": v[1]} for k, v in c["curve"].items()}}
          for iso, c in FIX["fv"]["countries"].items() if isinstance(c, dict) and c.get("curve") and iso in GUIDES}

# Each name read literally (not through eval), before the driver below
# reassigns any of them.
PROBE = "const __names = {};\n" + "".join(
    'try { __names[%s] = [typeof %s, typeof %s === "function" ? %s.length : null]; } '
    'catch (e) { __names[%s] = ["throws"]; }\n' % (json.dumps(n), n, n, n, json.dumps(n)) for n in NAMES)
DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
lastRates = FIX.rates; ppp = FIX.ppp; climate = FIX.climate; activities = FIX.activities; worldGeo = FIX.world;
advisories = FIX.advisories; flightsData = FIX.flights; flightValue = FIX.fv;
SLUG2ISO = FIX.slugs; ISO2SLUG = {}; for (const k in SLUG2ISO) ISO2SLUG[SLUG2ISO[k]] = k;
popularitySettled = true; valueFlightsSettled = true;
loaded.value = true; drawMap = function () {};
ensureAdvisories = async () => advisories; ensurePPP = async () => ppp;
for (const iso of FIX.guides) _fareMonthsCache["US:" + iso] = Promise.resolve(FIX.curves[iso] || null);
const out = { names: __names, views: [], parts: {}, guides: {} };
$("pickCount").value = "20"; $("safeFloor").value = "b";
for (const m of ["0", "1", "6", "12"]) {
  $("valueMonth").value = m; renderValue();
  out.views.push({ top: $("topCards").innerHTML, note: $("picksNote").innerHTML });
}
for (const iso in CUR_BY_ISO) {
  const p = { ppp: pppNotes(iso) || null, fx: fxMark(iso), adv: advMovedMark(iso), tag: [], strip: [] };
  for (let m = 1; m <= 12; m++) { p.tag.push(seasonalTags(iso, m, 1, true)); p.strip.push(seasonStrip(iso, m)); }
  out.parts[iso] = p;
}
(async () => {
  for (const iso of FIX.guides) {
    ccGuideIso = iso;
    $("guideGrades").innerHTML = ""; $("guideFares").innerHTML = ""; $("guideFares").hidden = true;
    await renderGuideGrades(iso);
    await renderGuideFares(iso);
    out.guides[iso] = { grades: $("guideGrades").innerHTML, fares: $("guideFares").hidden ? "" : $("guideFares").innerHTML };
  }
  print(JSON.stringify(out));
})().catch((e) => print(JSON.stringify({ error: String(e && e.stack || e) })));
"""


def run_jsc(code, d, tag):
    fp, sp = os.path.join(d, "fix.json"), os.path.join(d, tag + ".js")
    if not os.path.exists(fp):
        json.dump(dict(FIX, guides=GUIDES, curves=CURVES), open(fp, "w"))
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + code + "\n" + PROBE + DRIVER.replace("FIX_PATH", json.dumps(fp)))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=50)
    try:
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"error": (r.stderr or r.stdout)[-600:]}


with tempfile.TemporaryDirectory() as d:
    a = run_jsc(APP, d, "src")
    b = run_jsc(open(MIN, encoding="utf-8").read(), d, "min") if os.path.isfile(MIN) else {"error": "no app.min.js"}
ran = "error" not in a and "error" not in b
results.append(ok(ran, "both files ran under jsc %s" % (a.get("error", "") or b.get("error", ""))))
if ran:
    na, nb = a.pop("names"), b.pop("names")
    lost = [n for n in NAMES if na.get(n) != nb.get(n)]
    defined = sum(1 for n in NAMES if na[n][0] not in ("undefined", "throws"))
    results.append(ok(len(NAMES) > 800 and not lost and defined > 800,
                      "every top-level name is the same kind, with the same parameter count, in both "
                      "(%d names, %d defined; differing: %s)" % (len(NAMES), defined, lost[:8])))
    views = len(a["views"]) == 4 and all(v["top"].count("<tr data-iso=") >= 5 for v in a["views"])
    results.append(ok(views and a["views"] == b["views"],
                      "Top Picks for months 0, 1, 6 and 12 are the same rows and note from both files"))
    results.append(ok(len(a["parts"]) > 150 and a["parts"] == b["parts"],
                      "every country's pieces (%d: PPP note, marks, season tags and strips) are the same"
                      % len(a["parts"])))
    drew = sum(1 for g in a["guides"].values() if g["grades"])
    results.append(ok(len(a["guides"]) == len(GUIDES) and drew >= 25 and a["guides"] == b["guides"],
                      "the grades and fares lines of %d guides (%d graded) are the same" % (len(GUIDES), drew)))


# --- the guard and the stamp, on files of their own -------------------------------------
@contextlib.contextmanager
def log():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        yield buf


real = (server.APP_JS, server.APP_MIN_JS, server.APP_MIN_SHA, server.MIN_JS)


def point(d):
    server.APP_JS, server.APP_MIN_JS = os.path.join(d, "app.js"), os.path.join(d, "app.min.js")
    server.APP_MIN_SHA = server.APP_MIN_JS + ".sha256"
    server._app_js_memo = None


def write(p, data):
    with open(p, "wb") as f:
        f.write(data)


def lines(buf):
    return [x for x in buf.getvalue().splitlines() if x.startswith("[min-js]")]


with tempfile.TemporaryDirectory() as d:
    point(d)
    src, mini = b"function hello(name) { return 'hi ' + name; }\n" * 80, b"function hello(n){return'hi '+n}\n" * 40
    write(server.APP_JS, src)
    write(server.APP_MIN_JS, mini)
    write(server.APP_MIN_SHA, ("%s  app.js\n" % sha(src)).encode())
    try:
        with log() as buf:
            first = server._app_js_file()
            again = [server._app_js_file() for _ in range(5)]
        results.append(ok(first == server.APP_MIN_JS and set(again) == {first}
                          and lines(buf) == ["[min-js] serving app.min.js for /app.js"],
                          "hash matches: the copy, and one log line for six calls"))
        mtime = str(int(os.path.getmtime(server.APP_JS)))
        v_min = server._app_js_version()
        results.append(ok(v_min == mtime + "%08d" % (int(sha(mini), 16) % 10 ** 8),
                          "the stamp is app.js's mtime and 8 digits of the copy's sha256 (%s)" % v_min))
        # A rebuild of the same app.js: other bytes, the same app.js mtime.
        write(server.APP_MIN_JS, mini.replace(b"n", b"x"))
        with log() as buf:
            v_re = server._app_js_version()
        results.append(ok(v_re != v_min and v_re.startswith(mtime) and len(lines(buf)) == 1,
                          "a rebuild of the same app.js changes the stamp (%s)" % v_re))
        write(server.APP_MIN_JS, mini)

        # app.js edited, no rebuild.
        st = os.stat(server.APP_JS)
        write(server.APP_JS, src + b"hello('again');\n")
        os.utime(server.APP_JS, ns=(st.st_atime_ns, st.st_mtime_ns))   # even with the old mtime
        with log() as buf:
            stale = [server._app_js_file() for _ in range(6)]
            v_full = server._app_js_version()
        ln = lines(buf)
        results.append(ok(set(stale) == {server.APP_JS} and len(ln) == 1
                          and ln[0].startswith("[min-js] serving app.js as written: app.min.js was built from app.js %s"
                                               % sha(src)[:12]) and "build_min_js.py" in ln[0],
                          "app.js edited, the same mtime: app.js as written, one line for seven calls (%s)" % ln[:1]))
        results.append(ok(v_full == mtime and v_full != v_min,
                          "then the stamp is app.js's mtime alone, not the copy's (%s)" % v_full))
        write(server.APP_MIN_SHA, ("%s  app.js\n" % sha(readb(server.APP_JS))).encode())
        with log() as buf:
            back = server._app_js_file()
        results.append(ok(back == server.APP_MIN_JS and lines(buf) == ["[min-js] serving app.min.js for /app.js"],
                          "the hash brought up to date: the copy again"))

        os.remove(server.APP_MIN_SHA)
        with log() as buf:
            nohash = [server._app_js_file() for _ in range(3)]
        results.append(ok(set(nohash) == {server.APP_JS} and len(lines(buf)) == 1
                          and "no app.min.js.sha256" in lines(buf)[0], "no hash file: app.js, one line"))
        write(server.APP_MIN_SHA, b"not a hash\n")
        with log() as buf:
            junk = server._app_js_file()
        results.append(ok(junk == server.APP_JS and len(lines(buf)) == 1 and "holds no sha256" in lines(buf)[0],
                          "a hash file without a hash: app.js, one line"))
        write(server.APP_MIN_SHA, ("%s  app.js\n" % sha(readb(server.APP_JS))).encode())
        os.remove(server.APP_MIN_JS)
        with log() as buf:
            nomin = server._app_js_file()
        results.append(ok(nomin == server.APP_JS and len(lines(buf)) == 1 and "no app.min.js" in lines(buf)[0],
                          "no copy: app.js, one line"))
        write(server.APP_MIN_JS, mini)
        server.MIN_JS = False
        with log() as buf:
            off = server._app_js_file()
            v_off = server._app_js_version()
        results.append(ok(off == server.APP_JS and len(lines(buf)) == 1 and "FX_MIN_JS=0" in lines(buf)[0]
                          and v_off == mtime, "FX_MIN_JS=0: app.js as written, stamped with its mtime alone"))
        server.MIN_JS = True

        # --- the routes, on these files ---------------------------------------------------
        server.Handler.log_message = lambda self, *a: None
        httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        BASE = "http://127.0.0.1:%d" % httpd.server_address[1]

        def get(path, method="GET", gz=False):
            req = urllib.request.Request(BASE + path, method=method, headers={"Accept-Encoding": "gzip"} if gz else {})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    return r.status, dict(r.headers), r.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()

        try:
            with log() as buf:
                s1, h1, b1 = get("/app.js?v=1")
                s2, h2, b2 = get("/app.js?v=1", gz=True)
                s3, _, b3 = get("/app.js?v=1", method="HEAD")
            results.append(ok(s1 == 200 and b1 == mini and h1.get("Cache-Control") == "public, max-age=31536000, immutable"
                              and h1.get("Content-Type") == "application/javascript; charset=utf-8"
                              and h2.get("Content-Encoding") == "gzip" and gzip.decompress(b2) == mini
                              and s3 == 200 and b3 == b"" and len(lines(buf)) == 1,
                              "/app.js?v= is the copy: immutable, gzipped on request, HEAD without a body"))
            write(server.APP_JS, readb(server.APP_JS) + b"hello('a third time');\n")
            with log() as buf:
                outs = [get("/app.js?v=1") for _ in range(4)]
            results.append(ok(all(o[0] == 200 and o[2] == readb(server.APP_JS) for o in outs) and len(lines(buf)) == 1,
                              "app.js edited under a running server: the next request is app.js as written, "
                              "one line for four requests"))
            for p in ("/app.min.js", "/app.min.js.sha256", "/app.min.js?v=1", "/./app.min.js"):
                st_, _, _ = get(p)
                results.append(ok(st_ == 404, "%s is a 404" % p))
        finally:
            httpd.shutdown()
    finally:
        server.APP_JS, server.APP_MIN_JS, server.APP_MIN_SHA, server.MIN_JS = real
        server._app_js_memo = None
        server._static_memo.clear()

# --- the real files, as the site serves them --------------------------------------------
server._html_tpl = None
httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
BASE = "http://127.0.0.1:%d" % httpd.server_address[1]
try:
    with log():
        with urllib.request.urlopen(BASE + "/", timeout=30) as r:
            home = r.read().decode("utf-8")
        want = server._app_js_version()
        m = re.search(r'<script src="(/app\.js\?v=(\d+))"></script>', home)
        with urllib.request.urlopen(BASE + (m.group(1) if m else "/app.js"), timeout=30) as r:
            body = r.read()
    results.append(ok(m is not None and m.group(2) == want and body == readb(server._app_js_file()),
                      "the homepage loads /app.js?v=%s, which is %s" % (m.group(2) if m else "?",
                                                                       os.path.basename(server._app_js_file()))))
    results.append(ok(not current or (body == readb(MIN) and len(body) < 0.55 * len(readb(SRC))),
                      "with the committed copy current, that is app.min.js (%d of app.js's %d bytes)"
                      % (len(body), len(readb(SRC)))))
finally:
    httpd.shutdown()

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
