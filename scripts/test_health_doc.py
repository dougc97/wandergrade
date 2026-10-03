"""Exercise the /health.json document rules — fxtracker/health.py (which copy
is served, the code tag on stored copies, the partial test run, the refresher's
env) and fxtracker/build_health.py (Palestine's shared copy, the early outage,
the West Nile merge) — on synthetic Canada pages and a fake West Nile module,
against scripts/mock_upstash.py, so nothing leaves this machine.

    python3 scripts/test_health_doc.py
    (the mock is started in-process on MOCK_UPSTASH_PORT, default 8951; if
     something already listens there it is used as the mock instead)
"""
import contextlib, io, itertools, json, os, shutil, sys, tempfile, threading, time, types
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "RENDER", "HEALTH_REFRESH",
          "HEALTH_REFRESH_DELAY", "HEALTH_REFRESH_ISOS"):
    os.environ.pop(k, None)     # never the real store, never a real refresher

import fxtracker
from fxtracker import accounts, rates, build_health as B, health as HL


def _no_network(*a, **k):
    raise RuntimeError("test tried the network")


rates.fetch_json = _no_network  # every page below comes from a temp mirror

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
TMP = tempfile.mkdtemp(prefix="wg-health-test-")


# --- synthetic Canada pages -------------------------------------------------------
def page(name, slug, head="Exercise a high degree of caution", reason="crime", extra=""):
    health = ('<h3>Diseases</h3><details><summary>Dengue</summary>'
              '<p>In %s, dengue is a risk to travellers.</p></details>' % name)
    adv = ('<div class="AdvisoryContainer HighDegree"><h3>%s - %s</h3><p>%s in %s due to %s.</p></div>'
           % (name.upper(), head.upper(), head, name, reason)) + extra
    return {"data": {"eng": {"name": name, "url-slug": slug, "health": health, "advisories": adv}}}


ISRAEL = page("Israel and Palestine", "israel-and-palestine")
ISRAEL["data"]["eng"]["advisories"] = (
    '<div class="AdvisoryContainer AvoidNonEssential"><h3>ISRAEL - AVOID NON-ESSENTIAL TRAVEL</h3>'
    '<p>Avoid non-essential travel to Israel due to the volatile security situation in the region.</p></div>'
    '<div class="AdvisoryContainer AvoidAll"><h3>PALESTINE - AVOID ALL TRAVEL</h3>'
    '<p>Avoid all travel to Palestine due to the ongoing military activities.</p></div>')
FILLER = ["%s%s" % p for p in itertools.product("ABCDEFGHJK", "ABCDEFGHIJKLMNOPQRSTUVWXYZ")
          if "%s%s" % p not in ("IL", "PS", "MX")][:160]


def mirror(name, pages, date="2026-09-20"):
    """A --dir mirror: index.json (mtime = `date`, which build() dates the
    document by) plus one cta-xx.json per page."""
    d = os.path.join(TMP, name)
    os.makedirs(d)
    for iso, pg in pages.items():
        with open(os.path.join(d, "cta-%s.json" % iso.lower()), "w") as f:
            json.dump(pg, f)
    with open(os.path.join(d, "index.json"), "w") as f:
        json.dump({"data": {iso: {} for iso in pages}}, f)
    t = time.mktime(time.strptime(date + " 12", "%Y-%m-%d %H"))
    os.utime(os.path.join(d, "index.json"), (t, t))
    return d


base = {iso: page("Land " + iso, "land-" + iso.lower()) for iso in FILLER}
base["IL"] = ISRAEL
base["MX"] = page("Mexico", "mexico", reason="high levels of criminal activity and kidnapping")
MIR = mirror("no-ps", base)
MIR_PS = mirror("own-ps", dict(base, PS=page("Palestine", "palestine", reason="crime")), "2026-10-02")


# --- S2: Palestine's shared copy never overwrites a real PS page ---------------------
print("Palestine (S2):")
doc, failed = B.build(local_dir=MIR)
ps = doc["c"]["PS"]
results.append(ok(ps.get("v") == "Israel and Palestine" and ps.get("s") == "israel-and-palestine"
                  and ps.get("rq", "").startswith("Avoid all travel to Palestine") and not failed,
                  "no PS page: PS is the Israel-and-Palestine copy with Palestine's own block"))
shared_c = doc["c"]

doc, _ = B.build(local_dir=MIR_PS)
ps = doc["c"]["PS"]
results.append(ok("v" not in ps and ps.get("s") == "palestine" and ps.get("r") == ["Crime"],
                  "Canada's own PS page wins over the copy (full run)"))
own_c = doc["c"]

doc, _ = B.build(prev=own_c, only={"IL"}, local_dir=MIR_PS)
results.append(ok(doc["c"]["PS"] == own_c["PS"], "only=IL keeps last run's own PS row (no 'v')"))

stale = json.loads(json.dumps(shared_c))
stale["PS"]["rq"] = "stale"
doc, _ = B.build(prev=stale, only={"IL"}, local_dir=MIR)
results.append(ok(doc["c"]["PS"].get("v") and doc["c"]["PS"]["rq"].startswith("Avoid all travel"),
                  "only=IL refreshes last run's shared copy from the Israel page"))
stale_il = json.loads(json.dumps(stale))
doc, _ = B.build(prev=stale_il, only={"MX"}, local_dir=MIR)
results.append(ok(doc["c"]["PS"]["rq"] == "stale", "only=MX (host not loaded) keeps last run's copy"))

real_load = B._load


def failing(isos):
    def load(iso, local_dir):
        if iso in isos:
            raise OSError("page down")
        return real_load(iso, local_dir)
    return load


B._load = failing({"PS"})
doc, failed = B.build(prev=own_c, local_dir=MIR_PS)
B._load = real_load
results.append(ok(doc["c"]["PS"] == own_c["PS"] and len(failed) == 1,
                  "a failed PS page keeps its own last row, not Israel's copy"))

doc, _ = B.build(prev=shared_c, only={"PS"}, local_dir=MIR_PS)
results.append(ok(doc["c"]["PS"].get("s") == "palestine" and "v" not in doc["c"]["PS"],
                  "only=PS with its own page: the page's row"))

# --- S4: the outage is declared at the 6th failure -------------------------------------
print("Outage (S4):")
calls = []


def all_down(iso, local_dir):
    calls.append(iso)
    raise OSError("timed out")


B._load = all_down
try:
    B.build(prev=own_c, local_dir=MIR, pause=0)
    results.append(ok(False, "an all-pages outage raised nothing"))
except B.Outage as e:
    results.append(ok(len(calls) == B.MAX_FAILED + 1,
                      "Outage raised after %d pages, not %d (%s)" % (len(calls), len(base), e)))
B._load = real_load
calls.clear()
B._load = failing(set(FILLER[:5]))
doc, failed = B.build(prev=own_c, local_dir=MIR)
B._load = real_load
results.append(ok(len(failed) == 5 and all(doc["c"][i] == own_c[i] for i in FILLER[:5]),
                  "5 failures: built, and those pages keep their last rows"))

# --- S8: a partial run keeps the document's date ------------------------------------------
print("Partial runs (S8):")
doc, _ = B.build(prev=own_c, only={"MX"}, local_dir=MIR, prev_built="2026-09-01")
results.append(ok(doc["built"] == "2026-09-01", "only=MX keeps prev_built (2026-09-01), not the mirror's date"))
doc, _ = B.build(local_dir=MIR, prev_built="2026-09-01")
results.append(ok(doc["built"] == "2026-09-20", "a full run is dated by its own read (2026-09-20)"))


# --- West Nile merge ----------------------------------------------------------------------
print("West Nile merge:")
NOTE_ALL, NOTE_NO_CDC, NOTE_NO_ECDC = "both", "ecdc only", "cdc only"
NOTES = {frozenset(["ECDC", "CDC"]): NOTE_ALL, frozenset(["ECDC"]): NOTE_NO_CDC,
         frozenset(["CDC"]): NOTE_NO_ECDC}


def W(built, ecdc=None, cdc=None, season="2026"):
    """A w as westnile.build makes it: ecdc/cdc = (when-phrase, {ISO: n})."""
    c, src = {}, []
    if ecdc is not None:
        src.append("ECDC")
        for iso, n in ecdc[1].items():
            c[iso] = {"a": ["Area %s" % iso], "t": "ECDC: %d locally acquired human cases in 1 area %s" % (n, ecdc[0])}
    if cdc is not None:
        src.append("CDC")
        for iso, n in cdc[1].items():
            c.setdefault(iso, {"t": "CDC: %d human disease cases reported from 1 state %s" % (n, cdc[0])})
    return {"source": " · ".join(src), "url": "https://ecdc" if ecdc is not None else "https://cdc",
            "season": season, "built": built,
            "note": NOTES[frozenset(src)], "c": dict(sorted(c.items()))}


log = []
L = log.append
old = W("2026-09-28", ("in 2026 so far (as of 24 Sep)", {"IT": 600, "GR": 330}),
        ("in 2026 so far (as of 22 Sep)", {"US": 900}))
arch = W("2026-10-05", ("in 2026 so far (as of 10 Sep)", {"IT": 590, "GR": 319}),
         ("in 2026 so far (as of 29 Sep)", {"US": 987, "PR": 2}))
m = B.merge_w(arch, old, NOTES, L)
results.append(ok(m["c"]["IT"]["t"].endswith("(as of 24 Sep)") and m["c"]["GR"] == old["c"]["GR"],
                  "an archive ECDC older than the served one (10 Sep < 24 Sep): the served ECDC stays"))
results.append(ok(m["c"]["US"]["t"].startswith("CDC: 987") and "PR" in m["c"],
                  "...while this build's newer CDC (29 Sep) replaces the old"))
results.append(ok(m["source"] == "ECDC · CDC" and m["note"] == NOTE_ALL and m["url"] == "https://ecdc"
                  and m["built"] == "2026-10-05" and m["season"] == "2026",
                  "...source, note, url, season, built all consistent"))
results.append(ok(any("kept ECDC" in x and "2026-09-24" in x for x in log), "...and the log says so"))

live = W("2026-10-05", ("in 2026 so far (as of 1 Oct)", {"IT": 640}), ("in 2026 so far (as of 29 Sep)", {"US": 987}))
results.append(ok(B.merge_w(live, old, NOTES, L) is live, "newer on both agencies: the new w as is"))
results.append(ok(B.merge_w(None, old, NOTES, L) is old, "nothing new (both agencies failed): the old w"))
results.append(ok(B.merge_w(live, None, NOTES, L) is live and B.merge_w(None, None, NOTES, L) is None,
                  "no old w: the new one (or none)"))

cdc_only = W("2026-10-05", cdc=("in 2026 so far (as of 29 Sep)", {"US": 987}))
m = B.merge_w(cdc_only, old, NOTES, L)
results.append(ok(m["c"]["IT"] == old["c"]["IT"] and m["c"]["US"]["t"].startswith("CDC: 987")
                  and m["source"] == "ECDC · CDC" and m["note"] == NOTE_ALL,
                  "ECDC unread this build: last w's ECDC entries kept, note for both agencies"))

old25 = W("2026-01-10", ("in the 2025 season", {"IT": 800}), ("in the 2025 season", {"US": 2000}), season="2025")
m = B.merge_w(cdc_only, old25, NOTES, L)
results.append(ok(m is cdc_only and "IT" not in m["c"],
                  "ECDC unread, last w's ECDC from an earlier season (2025): dropped, not shown beside 2026"))

empty_ecdc = W("2026-10-05", ("", {}), ("in 2026 so far (as of 29 Sep)", {"US": 987}))
results.append(ok(B.merge_w(empty_ecdc, old, NOTES, L) is empty_ecdc,
                  "ECDC read with no entries is an answer: the old ECDC entries go"))

pre = W("2026-10-05", ("in the 2025 season", {"IT": 800}), ("in 2026 so far (as of 1 Oct)", {"US": 1003}))
m = B.merge_w(pre, old, NOTES, L)
results.append(ok(m["c"]["IT"] == old["c"]["IT"] and m["c"]["US"] == pre["c"]["US"],
                  "an ECDC copy from an earlier season (2025 vs 2026) never replaces this season's"))

same = W("2026-10-01", ("in the 2026 season", {"IT": 700}), None)
older_build = W("2026-09-01", ("in the 2026 season", {"IT": 500}), None)
results.append(ok(B.merge_w(older_build, same, NOTES, L) is same,
                  "no as-of on either side: the later build wins (2026-10-01 over 2026-09-01)"))

e_only = W("2026-09-28", ("in 2026 so far (as of 24 Sep)", {"IT": 600}))
m = B.merge_w(cdc_only, e_only, NOTES, L)
results.append(ok(m["source"] == "ECDC · CDC" and m["note"] == NOTE_ALL and set(m["c"]) == {"IT", "US"},
                  "a mix neither w had (old ECDC only + new CDC only): the both-agencies note"))
odd = {"source": "ECDC", "season": "2026", "built": "2026-10-05",
       "c": {"IT": {"t": "ECDC: 650 cases in 2026 so far (as of 1 Oct)"}, "XX": {"a": ["?"]}}}
m = B.merge_w(odd, old, NOTES, L)
results.append(ok(m["c"]["IT"] is odd["c"]["IT"] and "XX" in m["c"] and m["c"]["US"] == old["c"]["US"],
                  "an entry with no agency prefix rides with the new w; no crash"))
results.append(ok(B.merge_w({"c": "bad"}, old, NOTES, L) is old and B.merge_w(live, {"w": 1}, NOTES, L) is live,
                  "a malformed w on either side is ignored"))

# with_westnile: the module is optional, its info is logged, failures keep the old w.
print("with_westnile:")
fake = types.ModuleType("fxtracker.westnile")
fake.NOTE_ALL, fake.NOTE_NO_CDC, fake.NOTE_NO_ECDC = NOTE_ALL, NOTE_NO_CDC, NOTE_NO_ECDC
fake.calls = 0
fake.result = arch
fake.info = {"ecdc": "archive", "ecdc_errors": ["live: timed out"], "cdc": "live"}


def fake_get(built=None, info=None, ecdc=True, cdc=True):
    fake.calls += 1
    if isinstance(fake.result, Exception):
        raise fake.result
    if info is not None:
        info.update(fake.info)
    return fake.result


fake.get = fake_get


@contextlib.contextmanager
def westnile(module):
    """`module` as fxtracker.westnile (None: the module isn't deployed)."""
    had = sys.modules.get("fxtracker.westnile", "absent")
    sys.modules["fxtracker.westnile"] = module
    if module is not None:
        fxtracker.westnile = module
    try:
        yield
    finally:
        if had == "absent":
            sys.modules.pop("fxtracker.westnile", None)
        else:
            sys.modules["fxtracker.westnile"] = had
        if hasattr(fxtracker, "westnile"):
            del fxtracker.westnile


log.clear()
with westnile(fake):
    d = B.with_westnile({"built": "2026-10-05", "c": {}}, {"w": old}, L)
results.append(ok(d["w"]["c"]["IT"] == old["c"]["IT"] and d["w"]["c"]["US"]["t"].startswith("CDC: 987"),
                  "with_westnile merges with the last document's w"))
results.append(ok(any("ECDC from the Internet Archive" in x and "CDC live" in x and "timed out" in x for x in log),
                  "...and logs ECDC's route (archive, with the live error) and CDC's"))
log.clear()
fake.result = RuntimeError("boom")
with westnile(fake):
    d = B.with_westnile({"built": "2026-10-05", "c": {}}, {"w": old}, L)
results.append(ok(d.get("w") is old and any("not refreshed: boom" in x for x in log),
                  "get() raising: the last w stays"))
fake.result = arch
# get() always takes info= now (the TypeError fallback re-ran a whole fetch
# whenever get() itself raised a TypeError): an old-style get() is a failed
# refresh that keeps the last w, not a second request.
with westnile(types.SimpleNamespace(get=lambda: live)):
    d = B.with_westnile({"built": "2026-10-05", "c": {}}, {"w": old}, L)
results.append(ok(d.get("w") is old, "a get() without info= is a failed refresh: the last w stays"))
with westnile(None):
    d = B.with_westnile({"built": "2026-10-05", "c": {}}, {"w": old}, L)
results.append(ok("w" not in d, "module not deployed: no w (the off switch)"))


# --- health.py against the mock store -------------------------------------------------------
port = int(os.environ.get("MOCK_UPSTASH_PORT", "8951"))
try:
    import mock_upstash
    srv = HTTPServer(("127.0.0.1", port), mock_upstash.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("mock Upstash started on", port)
except OSError:
    print("mock Upstash already listening on", port)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock"
accounts._kv_del(HL.KEY)
results.append(ok(accounts.storage_configured(), "storage configured -> mock Upstash"))

STATIC = os.path.join(TMP, "health.json")
real_out, real_build = B.OUT, B.build
B.OUT = STATIC                  # never the committed file
static_doc, _ = real_build(local_dir=MIR)
static_doc["built"] = "2026-09-30"
with open(STATIC, "w") as f:
    json.dump(static_doc, f)
B.build = lambda *a, **k: real_build(*a, local_dir=MIR_PS, **k)


def reset():
    HL._mem.update(doc=None, code=None)
    HL._kv.update(doc=None, ignored=None)
    HL._static.update(doc=None, mtime=None)
    accounts._kv_del(HL.KEY)


def quiet(fn, *a, **k):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = fn(*a, **k)
    return r, buf.getvalue()


def stored(doc, code):
    accounts._kv_set(HL.KEY, json.dumps(doc if code is None else {"code": code, "doc": doc}))


print("Code tag (S1):")
reset()
future = dict(static_doc, built="2099-01-01")
stored(future, None)
_, out = quiet(HL._load_stored)
results.append(ok(HL._kv["doc"] is None and HL.get_doc()["built"] == "2026-09-30",
                  "a bare stored document (from before the tag) is ignored, however new"))
results.append(ok("untagged" in out, "...and the log says why"))
stored(future, "0123456789")
_, out = quiet(HL._load_stored)
results.append(ok(HL._kv["doc"] is None and HL.get_doc()["built"] == "2026-09-30" and "0123456789" in out,
                  "a copy stored by other code is ignored: the newer deploy's file is served"))
_, out = quiet(HL._load_stored)
results.append(ok(out == "", "...logged once, not on every check"))
stored(future, HL.CODE)
quiet(HL._load_stored)
results.append(ok(HL.get_doc()["built"] == "2099-01-01", "a copy stored by this code is served when newer"))
HL._mem.update(doc=dict(static_doc, built="2100-01-01"), code="0123456789")
results.append(ok(HL.get_doc()["built"] == "2099-01-01", "an in-memory copy tagged with other code is ignored"))
HL._mem.update(code=HL.CODE)
results.append(ok(HL.get_doc()["built"] == "2100-01-01", "...and served once tagged with this code"))
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:9"
quiet(HL._load_stored)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
results.append(ok(HL._kv["doc"] is not None and HL._kv["doc"]["built"] == "2099-01-01",
                  "storage unreachable: the copy read last time stays"))

reset()
tie = dict(static_doc, built="2026-09-30", marker="kv")
stored(tie, HL.CODE)
quiet(HL._load_stored)
results.append(ok(HL.get_doc().get("marker") == "kv", "a tie between Upstash and the file: Upstash"))
HL._mem.update(doc=dict(static_doc, built="2026-09-30", marker="mem"), code=HL.CODE)
results.append(ok(HL.get_doc().get("marker") == "mem", "a tie with memory: memory"))

# CODE follows the code: West Nile's arrival changes it.
fake_pkg = os.path.join(TMP, "pkg")
os.makedirs(fake_pkg)
# Without westnile.py first (the state before that module ships), then with it.
for name in ("build_health.py", "advisories.py"):
    shutil.copy(os.path.join(os.path.dirname(HERE), "fxtracker", name), fake_pkg)
real_here = HL.HERE
HL.HERE = fake_pkg
c1 = HL._code()
real_wn = os.path.join(os.path.dirname(HERE), "fxtracker", "westnile.py")
if os.path.exists(real_wn):
    shutil.copy(real_wn, fake_pkg)
else:
    with open(os.path.join(fake_pkg, "westnile.py"), "w") as f:
        f.write("# arrives\n")
c2 = HL._code()
with open(os.path.join(fake_pkg, "advisories.py"), "a") as f:
    f.write("# a label rule changes\n")
c3 = HL._code()
HL.HERE = real_here
has_wn = os.path.exists(os.path.join(os.path.dirname(HERE), "fxtracker", "westnile.py"))
results.append(ok((c2 == HL.CODE if has_wn else c1 == HL.CODE) and len({c1, c2, c3}) == 3,
                  "CODE changes with westnile.py's arrival and with advisories.py (the r labels)"))

print("Refresh, stored envelope, served shape:")
reset()
fake.calls, fake.result = 0, arch
with westnile(fake):
    r, out = quiet(HL.refresh, force=True, pause=0)
env = json.loads(accounts._kv_get(HL.KEY))
results.append(ok(r and env.get("code") == HL.CODE and env["doc"]["built"] == "2026-10-02",
                  "a full refresh stores {code, doc} under health:doc"))
served = json.loads(HL.get_json_bytes())
results.append(ok("code" not in served and set(served) == {"built", "source", "url", "c", "w"},
                  "the served document's shape is unchanged (no code key)"))
results.append(ok(served["c"]["PS"].get("s") == "palestine" and fake.calls == 1,
                  "...built from the pages (own PS) with West Nile fetched once"))
results.append(ok("Internet Archive" in out, "...and the refresh log names ECDC's route"))

# The weekly run merges against the served w: an archive read can't roll it back.
reset()
stored(dict(static_doc, built="2026-10-01", w=old), HL.CODE)
quiet(HL._load_stored)
with westnile(fake):
    r, out = quiet(HL.refresh, force=True, pause=0)
w = HL.get_doc()["w"]
results.append(ok(r and w["c"]["IT"] == old["c"]["IT"] and w["c"]["US"]["t"].startswith("CDC: 987"),
                  "refresh: ECDC from the archive (10 Sep) doesn't replace the served 24 Sep; CDC updates"))
results.append(ok(json.loads(accounts._kv_get(HL.KEY))["doc"]["w"] == w, "...and that merged w is what's stored"))

print("Partial run (S8):")
reset()
base_doc = dict(static_doc, built="2026-10-01", w=old)
stored(base_doc, HL.CODE)
quiet(HL._load_stored)
raw_before = accounts._kv_get(HL.KEY)
fake.calls = 0
with westnile(fake):
    r, out = quiet(HL.refresh, force=True, only={"MX"}, pause=0)
doc = HL.get_doc()
results.append(ok(r and doc is HL._mem["doc"] and doc["built"] == "2026-10-01",
                  "a HEALTH_REFRESH_ISOS run is served yet keeps its base copy's date (2026-10-01)"))
results.append(ok(accounts._kv_get(HL.KEY) == raw_before and "not stored" in out,
                  "...and is never stored to Upstash"))
results.append(ok(doc.get("w") == old and fake.calls == 0, "...and keeps the base copy's West Nile without fetching"))
results.append(ok(HL._age_days(doc) == HL._age_days(base_doc), "...so the weekly refresh still comes due on time"))

print("Refresher env (S7, S8):")
seen = []
gate = threading.Event()


def recorder(force=False, only=None, pause=None):
    seen.append((force, sorted(only) if only else None))
    if len(seen) >= 3:
        gate.wait()             # parks this daemon thread for the rest of the run
    return False


real_refresh, real_every = HL.refresh, HL.CHECK_EVERY
HL.refresh, HL.CHECK_EVERY = recorder, 0.05
os.environ.update(HEALTH_REFRESH="1", HEALTH_REFRESH_DELAY="0", HEALTH_REFRESH_ISOS="mx, th")
started, out = quiet(HL.start_refresher)
t0 = time.time()
while len(seen) < 3 and time.time() - t0 < 5:
    time.sleep(0.05)
results.append(ok(started and seen[:3] == [(True, ["MX", "TH"]), (False, None), (False, None)],
                  "HEALTH_REFRESH_ISOS: the first check is the short run, later ones the normal check"))
HL.refresh, HL.CHECK_EVERY = real_refresh, real_every
os.environ.pop("HEALTH_REFRESH_ISOS")
real_boot = HL.BOOT_DELAY
HL.BOOT_DELAY = 86400           # these threads must never reach a real check
for bad in ("90s", "inf", "-5"):
    os.environ["HEALTH_REFRESH_DELAY"] = bad
    try:
        started, out = quiet(HL.start_refresher)
        results.append(ok(started and "isn't a delay" in out and "first check in 86400s" in out,
                          "HEALTH_REFRESH_DELAY=%r: falls back to the boot delay, server boots" % bad))
    except Exception as e:
        results.append(ok(False, "HEALTH_REFRESH_DELAY=%r raised %r" % (bad, e)))
os.environ.pop("HEALTH_REFRESH_DELAY")
os.environ.pop("HEALTH_REFRESH")
HL.BOOT_DELAY = real_boot

B.OUT, B.build = real_out, real_build
reset()
shutil.rmtree(TMP, ignore_errors=True)
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
