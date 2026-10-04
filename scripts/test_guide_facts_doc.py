"""Exercise the guide-facts document rules — fxtracker/guide_facts.py (one
compute for the CLI and the server, which copy is served, the CODE tag on
stored copies, failed / stale / partial inputs keeping the previous copy, a
guide's "m" moving only when its entry changed, the refresher's env) and that
render_guide, /guide-facts.json and the sitemap follow the served copy — on
the parity fixtures, against scripts/mock_upstash.py, so nothing leaves this
machine.

    /usr/bin/python3 scripts/test_guide_facts_doc.py
    (the mock is started in-process on MOCK_UPSTASH_PORT, default 8955; if
     something already listens there it is used as the mock instead)
"""
import contextlib, copy, datetime, html, io, json, os, shutil, sys, tempfile, threading, time, types
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "RENDER", "GUIDE_FACTS_REFRESH",
          "GUIDE_FACTS_REFRESH_DELAY", "HEALTH_REFRESH"):
    os.environ.pop(k, None)     # never the real store, never a real refresher

from fxtracker import accounts, rates, guide_facts as GF, render_guide as rg  # noqa: E402
import server  # noqa: E402


def _no_network(*a, **k):
    raise RuntimeError("test tried the network")


rates.fetch_json = _no_network  # every input below is a fixture

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
TMP = tempfile.mkdtemp(prefix="wg-guidefacts-test-")
J = lambda p: json.load(open(p, encoding="utf-8"))
RATES = J(os.path.join(HERE, "parity", "fixture_rates.json"))
ADV = J(os.path.join(HERE, "parity", "fixture_advisories.json"))
PPP = J(os.path.join(ROOT, "public", "ppp.json"))
COMMITTED = J(GF.OUT)
STATIC = os.path.join(TMP, "guide-facts.json")
shutil.copy(GF.OUT, STATIC)
real_out = GF.OUT
GF.OUT = STATIC                 # never the committed file
guides = GF.all_guides()
# "Today" for the checks: after every committed m (2026-10-04), so a re-dated guide shows.
D = datetime.date(2026, 10, 6)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def rates_with(as_of=None, scale=None, drop=(), **extra):
    r = copy.deepcopy(RATES)
    if as_of:
        r["as_of"] = as_of
    r["rows"] = [dict(x, rate_now=x["rate_now"] * (scale or {}).get(x["code"], 1))
                 for x in r["rows"] if x["code"] not in drop]
    r.update(extra)
    return r


def adv_with(level=None, keep=None, **extra):
    a = copy.deepcopy(ADV)
    if keep is not None:
        a["items"] = a["items"][:keep]
    for it in a["items"]:
        if level and it.get("iso") in level:
            it["level"] = level[it["iso"]]
    a.update(extra)
    return a


def getters(r=None, a=None, p=None):
    def g(x, default):
        def f():
            v = default if x is None else x
            if isinstance(v, Exception):
                raise v
            return v
        return f
    return g(r, RATES), g(a, ADV), g(p, PPP)


# --- one compute for the CLI and the server -------------------------------------------
print("One compute (scripts/build_guide_facts.py == the refresher):")
doc, changed, lost = GF.build(RATES, ADV, PPP, COMMITTED, guides, today=D)
results.append(ok(doc == COMMITTED and not changed and not lost,
                  "guide_facts.build() on the fixtures reproduces the committed file exactly "
                  "(%d guides, 0 changed)" % len(guides)))
try:
    GF.build(RATES, adv_with(keep=60), PPP, COMMITTED, guides, today=D)
    results.append(ok(False, "a truncated advisory feed raised nothing"))
except GF.InputError as e:
    results.append(ok("inputs look broken" in str(e), "a truncated advisory feed (60 items) is refused: %s" % e))

# --- "m" moves only where the entry changed ----------------------------------------------
print("Dating (m):")
doc, changed, _ = GF.build(rates_with(scale={"THB": 1.10}), ADV, PPP, COMMITTED, guides, today=D)
moved = [i for i in guides if doc[i]["m"] != COMMITTED[i]["m"]]
results.append(ok(changed == ["TH"] and moved == ["TH"] and doc["TH"]["m"] == D.isoformat()
                  and doc["TH"]["pct"] != COMMITTED["TH"]["pct"],
                  "the baht 10%% weaker: only Thailand changes (pct %d -> %d) and only its m moves"
                  % (COMMITTED["TH"]["pct"], doc["TH"]["pct"])))
doc, changed, _ = GF.build(RATES, adv_with(level={"MX": 3}), PPP, COMMITTED, guides, today=D)
results.append(ok(changed == ["MX"] and doc["MX"]["t"].startswith("Is Mexico Safe")
                  and doc["MX"]["m"] == D.isoformat(),
                  "Mexico to Level 3: only Mexico re-dated, its title now asks \"Safe\""))
doc, changed, _ = GF.build(rates_with(as_of="2026-09-29"), ADV, PPP, COMMITTED, guides, today=D)
same = [i for i in guides if all(doc[i].get(k) == COMMITTED[i].get(k) for k in GF.CHANGE_KEYS)]
results.append(ok(doc["_asof"] == "2026-09-29" and set(changed) == set(guides) - set(same)
                  and len(same) > 150 and all(doc[i]["m"] == COMMITTED[i]["m"] for i in same),
                  "the rates' date moving a day re-dates nothing by itself (%d of %d unchanged keep m; "
                  "%d whose inflation carry moved a figure are re-dated)" % (len(same), len(guides), len(changed))))

# --- against the mock store -----------------------------------------------------------------
port = int(os.environ.get("MOCK_UPSTASH_PORT", "8955"))
try:
    import mock_upstash
    srv = HTTPServer(("127.0.0.1", port), mock_upstash.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("mock Upstash started on", port)
except OSError:
    print("mock Upstash already listening on", port)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock"
accounts._kv_del(GF.KEY)
results.append(ok(accounts.storage_configured(), "storage configured -> mock Upstash"))


def reset():
    GF._mem.update(doc=None, code=None)
    GF._kv.update(doc=None, other=None, ignored=None)
    GF._static.update(doc=None, mtime=None)
    accounts._kv_del(GF.KEY)


def stored(doc, code):
    accounts._kv_set(GF.KEY, json.dumps(doc if code is None else {"code": code, "doc": doc}))


def mark(doc, marker, **kw):
    return dict(doc, _marker=marker, **kw)


print("Freshest wins:")
reset()
results.append(ok(GF.get_doc()["_asof"] == "2026-09-28" and "_built" not in GF.get_doc(),
                  "nothing computed yet: the committed file"))
GF._mem.update(doc=mark(COMMITTED, "mem", _asof="2026-10-02", _built="2026-10-02"), code=GF.CODE)
results.append(ok(GF.get_doc()["_marker"] == "mem", "a newer computed copy in memory wins over the file"))
stored(mark(COMMITTED, "kv", _asof="2026-10-03", _built="2026-10-03"), GF.CODE)
quiet(GF._load_stored)
results.append(ok(GF.get_doc()["_marker"] == "kv", "a newer stored copy (another process) wins over memory"))
GF._mem.update(doc=mark(COMMITTED, "mem", _asof="2026-10-03", _built="2026-10-04"))
results.append(ok(GF.get_doc()["_marker"] == "mem",
                  "same rates date: the later _built wins (a changed advisory on an unchanged rate date)"))
GF._mem.update(doc=mark(COMMITTED, "mem", _asof="2026-10-03", _built="2026-10-03"))
results.append(ok(GF.get_doc()["_marker"] == "mem", "an exact tie: memory over Upstash"))
GF._mem.update(doc=None)
reset()
stored(mark(COMMITTED, "kv", _built="2026-10-01"), GF.CODE)
quiet(GF._load_stored)
results.append(ok(GF.get_doc()["_marker"] == "kv", "same _asof as the file: the computed copy (the file has no _built)"))
GF._mem.update(doc=mark(COMMITTED, "mem", _asof="2026-09-20", _built="2026-09-20"), code=GF.CODE)
results.append(ok(GF.get_doc()["_marker"] == "kv", "an older copy in memory never outranks a newer one"))

print("Code tag:")
reset()
future = mark(COMMITTED, "future", _asof="2099-01-01", _built="2099-01-01")
stored(future, None)
_, out = quiet(GF._load_stored)
results.append(ok(GF._kv["doc"] is None and GF.get_doc()["_asof"] == "2026-09-28" and "untagged" in out,
                  "a bare stored document (no code tag) is ignored, however new, and the log says why"))
stored(future, "0123456789")
_, out = quiet(GF._load_stored)
results.append(ok(GF._kv["doc"] is None and GF.get_doc()["_asof"] == "2026-09-28" and "0123456789" in out
                  and GF._kv["other"]["_marker"] == "future",
                  "a copy stored by other code is not served (kept aside only to date against)"))
_, out = quiet(GF._load_stored)
results.append(ok(out == "", "...logged once, not on every check"))
stored(future, GF.CODE)
quiet(GF._load_stored)
results.append(ok(GF.get_doc()["_marker"] == "future" and GF._kv["other"] is None,
                  "a copy stored by this code is served when newer"))
GF._mem.update(doc=mark(COMMITTED, "mem", _asof="2100-01-01"), code="0123456789")
results.append(ok(GF.get_doc()["_marker"] == "future", "an in-memory copy tagged with other code is ignored"))
GF._mem.update(doc=None, code=None)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:9"
_, out = quiet(GF._load_stored)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
results.append(ok(GF._kv["doc"] is not None and GF._kv["doc"]["_marker"] == "future" and "unreadable" in out,
                  "storage unreachable: the copy read last time stays"))

pkg = os.path.join(TMP, "code")
os.makedirs(pkg)
files = []
for path in GF.CODE_FILES:
    shutil.copy(path, pkg)
    files.append(os.path.join(pkg, os.path.basename(path)))
c0 = GF._code(files)


def touched(name, extra):
    p = os.path.join(pkg, name)
    keep = open(p, "rb").read()
    with open(p, "ab") as f:
        f.write(extra)
    c = GF._code(files)
    with open(p, "wb") as f:
        f.write(keep)
    return c


c_rules = touched("render_guide.py", b"\n# a title rule changes\n")
c_clim = touched("climate.json", b" ")
results.append(ok(c0 == GF.CODE and len({c0, c_rules, c_clim}) == 3 and GF._code(files) == c0,
                  "CODE follows the title rules (render_guide.py) and the content meta() reads (climate.json)"))

print("Refresh, stored envelope, served copy:")
reset()
r_oct = rates_with(as_of="2026-10-03", scale={"THB": 1.10})
r, out = quiet(GF.refresh, *getters(r=r_oct), today=D)
env = json.loads(accounts._kv_get(GF.KEY))
doc = GF.get_doc()
results.append(ok(r == "built" and doc is GF._mem["doc"] and doc["_asof"] == "2026-10-03"
                  and doc["_built"] == D.isoformat() and env == {"code": GF.CODE, "doc": doc},
                  "a check with good inputs computes, serves and stores {code, doc} under %s" % GF.KEY))
served = json.loads(GF.get_json_bytes())
results.append(ok(served == doc and "code" not in served
                  and set(served) == {"_asof", "_built"} | set(guides),
                  "/guide-facts.json serves that document: _asof, _built and one entry per guide (no code key)"))
results.append(ok("recomputed" in out and "as of 2026-10-03" in out, "...and the log says so: " + out.strip()[:110]))
r, _ = quiet(GF.refresh, *getters(r=RuntimeError("touched")), today=D)
results.append(ok(r == "fresh", "a second check the same day computes nothing (never touches the inputs)"))
GF._mem.update(doc=None, code=None)
GF._kv.update(doc=None)
quiet(GF._load_stored)
r, _ = quiet(GF.refresh, *getters(r=RuntimeError("touched")), today=D)
results.append(ok(r == "fresh" and GF.get_doc()["_built"] == D.isoformat(),
                  "a restart picks today's copy up from Upstash and doesn't recompute"))

print("render_guide, the sitemap and /guide-facts.json follow the served copy:")
th = rg.render("TH")
pct = doc["TH"]["pct"]
results.append(ok(th["title"] == doc["TH"]["t"] and th["desc"] == doc["TH"]["d"]
                  and ("≈ %d%%" % pct) in th["desc"] and "As of Oct 2026" in th["desc"]
                  and ("Local prices ≈ %d%% of the US (Oct 2026)" % pct) in th["body"]
                  and ("As of October 2026, local prices in Thailand are about %d%%" % pct) in th["jsonld"],
                  "Thailand's title, description, SSR cost line and FAQ say %d%% as of Oct 2026" % pct))
page = server._render_index("TH").decode("utf-8")
results.append(ok("<title>%s</title>" % html.escape(th["title"]) in page
                  and 'content="%s"' % html.escape(th["desc"], quote=True) in page,
                  "...and so does the served page's <title> and meta description"))
sm = server._sitemap().decode("utf-8")
slug = {iso: s for s, iso in rg.all_slugs()}
results.append(ok("/guide/thailand</loc><lastmod>%s<" % D.isoformat() in sm
                  and "/guide/%s</loc><lastmod>%s<" % (slug["TF"], max("2026-09-24", COMMITTED["TF"]["m"])) in sm
                  and doc["TF"]["m"] == COMMITTED["TF"]["m"],
                  "sitemap: Thailand re-dated %s; the French Southern Territories (no figure, so no "
                  "\"As of\" to move) keep %s" % (D, COMMITTED["TF"]["m"])))

print("Failed or stale inputs keep the previous copy:")


def kept_case(label, **g):
    reset()
    base = mark(COMMITTED, "prev", _asof="2026-10-01", _built="2026-10-01")
    stored(base, GF.CODE)
    quiet(GF._load_stored)
    raw = accounts._kv_get(GF.KEY)
    r, out = quiet(GF.refresh, *getters(**g), today=D)
    results.append(ok(r == "kept" and GF.get_doc()["_marker"] == "prev" and accounts._kv_get(GF.KEY) == raw
                      and "keeping the copy as of 2026-10-01" in out,
                      "%s: kept, served and stored copy untouched (%s)" % (label, out.strip()[14:90])))


kept_case("rates provider 429 with nothing cached", r=RuntimeError("HTTP Error 429: Too Many Requests"))
kept_case("rates are the cache's stale copy", r=rates_with(as_of="2026-10-03", stale=True, stale_age=4000))
kept_case("rates older than the served copy", r=rates_with(as_of="2026-09-30"))
kept_case("no rate rows", r=dict(RATES, rows=[]))
kept_case("rates without a date", r=dict(RATES, as_of=None))
kept_case("advisory feed down with nothing cached", r=rates_with(as_of="2026-10-03"), a=RuntimeError("feed down"))
kept_case("advisories are the cache's stale copy", r=rates_with(as_of="2026-10-03"), a=adv_with(stale=True))
kept_case("no PPP table", r=rates_with(as_of="2026-10-03"), p={})
kept_case("a truncated advisory feed", r=rates_with(as_of="2026-10-03"), a=adv_with(keep=60))

reset()
r, out = quiet(GF.refresh, *getters(r=RuntimeError("HTTP Error 429")), today=D)
r2, _ = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03")), today=D)
results.append(ok(r == "kept" and r2 == "built" and GF.get_doc()["_asof"] == "2026-10-03",
                  "after a kept check, the next one with good inputs computes"))
reset()
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:9"
r, out = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03")), today=D)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
results.append(ok(r == "built" and GF.get_doc()["_asof"] == "2026-10-03" and "memory only" in out,
                  "storage down at store time: served from memory, and the log says so"))

print("Partial inputs:")
reset()
base = dict(GF.build(rates_with(as_of="2026-10-01"), ADV, PPP, COMMITTED, guides, today=D)[0],
            _built="2026-10-01")
stored(base, GF.CODE)
quiet(GF._load_stored)
r, out = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03", drop=("XOF",))), today=D)
results.append(ok(r == "kept" and GF.get_doc()["_asof"] == "2026-10-01" and "partial inputs: 8 guides" in out,
                  "the XOF row missing (8 West African guides would lose their figure): kept"))
r, out = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03", drop=("MNT",))), today=D)
doc = GF.get_doc()
results.append(ok(r == "built" and "pct" not in doc["MN"] and doc["MN"]["m"] == D.isoformat()
                  and "Cheap" not in doc["MN"]["t"] and "lost a figure: MN" in out,
                  "one currency missing (MNT): computed; Mongolia drops its figure, title and m honestly"))
reset()
OLD_STATIC = os.path.join(TMP, "old-guide-facts.json")   # the only copy, 23 days old
with open(OLD_STATIC, "w", encoding="utf-8") as f:
    f.write(GF.dump(dict(base, _asof="2026-09-10")))
GF.OUT = OLD_STATIC
r, out = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03", drop=("XOF",))), today=D)
GF.OUT = STATIC
results.append(ok(r == "built" and "pct" not in GF.get_doc()["SN"],
                  "the same loss with the served copy %d days older (past PARTIAL_GRACE_DAYS=%d): accepted"
                  % ((datetime.date(2026, 10, 3) - datetime.date(2026, 9, 10)).days, GF.PARTIAL_GRACE_DAYS)))
reset()
r, out = quiet(GF.refresh, *getters(r=rates_with(as_of="2026-10-03"), a=adv_with(keep=150)), today=D)
results.append(ok(r == "kept" and "inputs look broken" in out,
                  "an advisory feed of 150 items (under 90% of guides rated): kept"))

print("Dating across a deploy that changes the code:")
reset()
r_930 = rates_with(as_of="2026-09-30", scale={"THB": 1.10})
other = dict(GF.build(r_930, ADV, PPP, COMMITTED, guides, today=datetime.date(2026, 9, 30))[0],
             _built="2026-09-30")
stored(other, "0123456789")
quiet(GF._load_stored)
r, out = quiet(GF.refresh, *getters(r=r_930), today=D)
doc = GF.get_doc()
results.append(ok(r == "built" and doc["TH"]["m"] == "2026-09-30" and "0 changed" in out,
                  "the stored copy from the old code is not served but dates the new one: Thailand keeps "
                  "2026-09-30 (vs the file it would be re-dated %s)" % D))

print("Refresher env:")
reset()
results.append(ok(GF.start_refresher(*getters()) is False, "no RENDER, no GUIDE_FACTS_REFRESH: no thread"))
seen, sleeps = [], []
gate = threading.Event()
plan = ["kept", "built", "fresh"]


def recorder(*a, **k):
    seen.append(plan[len(seen)] if len(seen) < len(plan) else "fresh")
    return seen[-1]


def fake_sleep(s):
    sleeps.append(s)
    if len(sleeps) >= 4:
        gate.wait()             # parks this daemon thread for the rest of the run


real_refresh, real_time = GF.refresh, GF.time
GF.refresh, GF.time = recorder, types.SimpleNamespace(sleep=fake_sleep, time=time.time)
os.environ.update(GUIDE_FACTS_REFRESH="1", GUIDE_FACTS_REFRESH_DELAY="7")
started, out = quiet(GF.start_refresher, *getters())
t0 = time.time()
while len(sleeps) < 4 and time.time() - t0 < 5:
    time.sleep(0.02)
results.append(ok(started and sleeps[:4] == [7.0, GF.RETRY_EVERY, GF.CHECK_EVERY, GF.CHECK_EVERY],
                  "GUIDE_FACTS_REFRESH=1: boot delay, then the sooner retry after a kept check, "
                  "the 6-hourly check after a built or fresh one %s" % sleeps[:4]))
GF.refresh, GF.time = real_refresh, real_time
real_boot = GF.BOOT_DELAY
GF.BOOT_DELAY = 86400           # these threads must never reach a real check
for bad in ("90s", "inf", "-5"):
    os.environ["GUIDE_FACTS_REFRESH_DELAY"] = bad
    try:
        started, out = quiet(GF.start_refresher, *getters())
        results.append(ok(started and "isn't a delay" in out and "first check in 86400s" in out,
                          "GUIDE_FACTS_REFRESH_DELAY=%r: falls back to the boot delay, server boots" % bad))
    except Exception as e:
        results.append(ok(False, "GUIDE_FACTS_REFRESH_DELAY=%r raised %r" % (bad, e)))
os.environ.pop("GUIDE_FACTS_REFRESH_DELAY")
os.environ.pop("GUIDE_FACTS_REFRESH")
GF.BOOT_DELAY = real_boot

reset()
GF.OUT = real_out
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
