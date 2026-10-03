"""fxtracker.westnile against saved copies of the real files, and the shape of
the health.json "w" dict other code builds against (contract C1). Nothing
leaves this machine: get() runs on a fake _fetch that serves the samples.

Samples (scripts/westnile_sample.*):
  ecdc-2026w37.html  ECDC weekly report, data to 10 Sep 2026 — current columns,
                     "Italy (590 cases), Greece (319 cases, of which 9 …)" summary
  ecdc-2026w28.html  data to 8 Jul 2026 — summary spells numbers out ("Italy has
                     reported six"), so the table's sums must stand
  ecdc-2025w50.html  the 2025 season's last report — no total column ("no totals
                     are provided"), "concludes its weekly reports"
  cdc-states.csv     wnv_hum_current_CountbyState.csv, fetched 2026-10-03
                     (Last-Modified Tue, 29 Sep 2026 16:28:37 GMT)
  cdc-config.json    current-data.json, the CDC map config, same day
  cdc-page.html      current-year-data.html, <main> only, same day
The ECDC ones are Internet Archive captures, trimmed of library code; each
file's first comment says which capture.

    /usr/bin/python3 scripts/test_westnile.py
"""
import base64, contextlib, copy, csv, datetime, gzip, io, json, os, re, sys, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from fxtracker import westnile as wn

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def sample(name):
    with open(os.path.join(HERE, "westnile_sample." + name), encoding="utf-8") as f:
        return f.read()


W37, W28, W2025 = sample("ecdc-2026w37.html"), sample("ecdc-2026w28.html"), sample("ecdc-2025w50.html")
CDC_CSV, CDC_PAGE = sample("cdc-states.csv"), sample("cdc-page.html")
CDC_CONFIG = json.loads(sample("cdc-config.json"))
BUILT = "2026-10-03"


def ecdc_csv(page):
    m = re.search(r"data:text/csv;base64,([A-Za-z0-9+/=]+)", page)
    return list(csv.DictReader(io.StringIO(base64.b64decode(m.group(1)).decode("utf-8"))))


# --- ECDC, Week 37 2026 -----------------------------------------------------------
e = wn.parse_ecdc(W37)
C = e["countries"]
results.append(ok(e["season"] == "2026" and e["asof"] == "2026-09-10" and not e["done"],
                  "W37: season 2026, data to 10 Sep, season not over"))
results.append(ok(e["unmapped"] == [] and len(C) == 15, "W37: all 15 countries map to an ISO"))
results.append(ok({"IT", "GR", "ES", "RO", "MK", "FR", "RS", "NL", "HR", "CY", "AT", "HU", "DE", "AL", "XK"} == set(C),
                  "W37: Kosovo* -> XK, North Macedonia -> MK, the Netherlands -> NL"))
# ECDC's own sentence: "These areas are located in Italy (64), Greece (21), …"
text = wn._text(W37[W37.find("<body"):])
located = re.search(r"These areas are located in (.*?)\. This week", text).group(1)
stated = {}
for name, n in re.findall(r"([A-Z][^(),]*?)\s*\*?\s*\((\d+)\)", located):
    name = re.sub(r"^(?:and|the)\s+", "", name.strip())
    stated[wn._name_to_iso().get(wn._norm(name))] = int(n)
results.append(ok(stated and all(len(C[i]["areas"]) == n for i, n in stated.items()) and len(stated) == 15,
                  "W37: area count per country = ECDC's 'These areas are located in …' (Italy 64, Greece 21, …)"))
results.append(ok(sum(len(c["areas"]) for c in C.values()) == 160, "W37: 160 table rows"))
results.append(ok(C["IT"]["cases"] == 590 and C["GR"]["cases"] == 319 and C["ES"]["cases"] == 104,
                  "W37: Italy 590, Greece 319, Spain 104 — ECDC's stated country totals"))
gr_rows = sum(int(r["Total human cases"]) for r in ecdc_csv(W37) if r["Country"] == "Greece")
results.append(ok(gr_rows == 310 and C["GR"]["cases"] == 319,
                  "W37: Greece's areas sum to 310; the 9 with unknown place come from the summary"))
results.append(ok(sum(c["cases"] for c in C.values()) == 1285, "W37: 1,285 cases = ECDC's '1 285 locally acquired'"))
results.append(ok(C["IT"]["areas"][0] == ("Padova", 50) and C["GR"]["areas"][0] == ("Anatoliki Attiki", 87),
                  "W37: busiest area first (Padova 50, Anatoliki Attiki 87)"))
ent = wn.ecdc_entries(e, BUILT)
results.append(ok(ent["IT"]["t"] == "ECDC: 590 locally acquired human cases, 64 affected areas, in 2026 so far (as of 10 Sep)",
                  "W37: Italy's sentence"))
results.append(ok(ent["XK"]["t"] == "ECDC: 1 locally acquired human case, 1 affected area, in 2026 so far (as of 10 Sep)"
                  and ent["XK"]["a"] == ["Gjakovë"], "W37: singular wording, Kosovo's area"))
results.append(ok(len(ent["IT"]["a"]) == 10 and ent["IT"]["a"][:3] == ["Padova", "Milano", "Roma"],
                  "W37: at most 10 areas, in ECDC's spelling"))
results.append(ok("Karditsa, Trikala" in ent["GR"]["a"], "W37: a two-place area keeps ECDC's name"))
results.append(ok(ent["GR"]["t"] == "ECDC: 319 locally acquired human cases, 21 affected areas, in 2026 so far (as of 10 Sep)",
                  "W37: Greece's 319 (9 with no known place) sit beside its 21 areas, not 'in' them"))
off = wn.ecdc_entries(e, "2027-01-15")
results.append(ok(off["IT"]["t"] == "ECDC: 590 locally acquired human cases, 64 affected areas, in the 2026 season",
                  "W37 read in January 2027: 'in the 2026 season', no 'so far'"))

# Same table from the DataTables widget when the data.csv button is gone.
no_csv = re.sub(r"data:text/csv;base64,[A-Za-z0-9+/=]+", "", W37)
e2 = wn.parse_ecdc(no_csv)
results.append(ok({i: (c["cases"], c["areas"]) for i, c in e2["countries"].items()} ==
                  {i: (c["cases"], c["areas"]) for i, c in C.items()},
                  "W37: table widget fallback gives the same countries, areas and cases"))

# A country in the summary with no table row (all its cases had an unknown
# place of infection) still gets an entry — it used to vanish, and with it
# the total stopped matching ECDC's.
GERMANY = "<strong>Germany</strong>\n(2 cases), "
assert W37.count(GERMANY) == 1
be = wn.parse_ecdc(W37.replace(GERMANY, GERMANY + "<strong>Belgium</strong> (2 cases), "))
results.append(ok(be["countries"].get("BE") == {"name": "Belgium", "cases": 2, "areas": []}
                  and sum(c["cases"] for c in be["countries"].values()) == 1287,
                  "W37 + 'Belgium (2 cases)' with no area row: BE kept, total 1,287"))
be_ent = wn.ecdc_entries(be, BUILT)
results.append(ok(be_ent["BE"] == {"t": "ECDC: 2 locally acquired human cases, place of infection not given, in 2026 so far (as of 10 Sep)"},
                  "W37 + Belgium: no 'a', 'place of infection not given'"))

# Only "ECDC concludes its weekly reports" ends a season; a mid-season notice
# of when it will conclude must not drop the "as of" date.
BASIS = "<h1>Basis and purpose of this weekly overview</h1>"
assert W37.count(BASIS) == 1
fp = wn.parse_ecdc(W37.replace(BASIS, "<p>ECDC will conclude its weekly reports at the end of November.</p>\n" + BASIS))
results.append(ok(not fp["done"] and wn.ecdc_entries(fp, BUILT)["IT"]["t"].endswith("in 2026 so far (as of 10 Sep)"),
                  "W37 + 'ECDC will conclude its weekly reports…': season not over, still 'so far (as of 10 Sep)'"))

# --- ECDC, Week 28 2026: numbers in words ---------------------------------------------
e = wn.parse_ecdc(W28)
C = e["countries"]
results.append(ok(e["asof"] == "2026-07-08" and len(C) == 5 and sum(len(c["areas"]) for c in C.values()) == 11,
                  "W28: 5 countries, 11 areas, data to 8 Jul"))
results.append(ok(C["IT"]["cases"] == 6 and sum(c["cases"] for c in C.values()) == 12,
                  "W28: 'Italy has reported six' -> table sum 6; 12 in all, as ECDC says"))

# --- ECDC, Week 50 2025: no totals, season concluded -------------------------------------
e = wn.parse_ecdc(W2025)
C = e["countries"]
results.append(ok(e["season"] == "2025" and e["asof"] == "2025-12-10" and e["done"],
                  "2025 W50: season 2025, data to 10 Dec, report concluded"))
results.append(ok(len(C) == 14 and "TR" in C and "BG" in C and e["unmapped"] == [],
                  "2025 W50: 14 countries as ECDC lists them, Türkiye -> TR"))
results.append(ok(all(c["cases"] is None for c in C.values()), "2025 W50: no case totals invented"))
ent = wn.ecdc_entries(e, "2025-12-20")
results.append(ok(ent["IT"]["t"] == "ECDC: locally acquired human cases, 64 affected areas, in the 2025 season",
                  "2025 W50: area count only, 'the 2025 season' even in December"))
it = [r for r in ecdc_csv(W2025) if r["Country"] == "Italy"]
busiest = max(it, key=lambda r: int(r["Number of probable cases"]) + int(r["Number of confirmed cases"]))
results.append(ok(ent["IT"]["a"][0] == busiest["Affected region"],
                  "2025 W50: areas ordered by probable + confirmed (%s first), not alphabetically" % busiest["Affected region"]))

# --- CDC -------------------------------------------------------------------------------
d = wn.parse_cdc(CDC_CSV, CDC_CONFIG, CDC_PAGE)
results.append(ok(d["season"] == "2026" and d["asof"] == "2026-09-29", "CDC: year from the map config, 'as of September 29'"))
# CDC's own headline files the same day: wnv_total_cases.csv 987, "States w Cases" 43.
results.append(ok(sum(n for _, n in d["states"]) == 987 and len(d["states"]) == 43,
                  "CDC: 43 jurisdictions, 987 cases = CDC's own total"))
ent = wn.cdc_entries(d, BUILT)
results.append(ok(ent["US"]["t"] == "CDC: 987 human disease cases reported from 42 states and DC in 2026 so far (as of 29 Sep)",
                  "CDC: US sentence (DC counted apart from the states)"))
results.append(ok(ent["US"]["a"][:3] == ["California", "Arizona", "Texas"] and len(ent["US"]["a"]) == 10,
                  "CDC: busiest 10 states by name"))
d2 = wn.parse_cdc(CDC_CSV, CDC_CONFIG, None, "Tue, 29 Sep 2026 16:28:37 GMT")
results.append(ok(d2["asof"] == "2026-09-29", "CDC: Last-Modified dates the data when the page can't be read"))
pr = wn.cdc_entries(wn.parse_cdc('"State","Reported Cases","Legend"\nTX,5,1 to 5\nPR,2,1 to 5\n', CDC_CONFIG, CDC_PAGE), BUILT)
results.append(ok(pr["PR"] == {"t": "CDC: 2 human disease cases reported in 2026 so far (as of 29 Sep)"}
                  and pr["US"]["t"].startswith("CDC: 5 human disease cases reported from 1 state in"),
                  "CDC: Puerto Rico is its own entry, not part of the US count"))
try:
    wn.parse_cdc(CDC_CSV, {"visualizations": {}}, CDC_PAGE)
    results.append(ok(False, "CDC: no year in the config -> error, not a guess"))
except ValueError:
    results.append(ok(True, "CDC: no year in the config -> error, not a guess"))

# --- contract C1 "w" ---------------------------------------------------------------------
ISOS = set()
with open(os.path.join(os.path.dirname(HERE), "public", "world.geojson"), encoding="utf-8") as f:
    ISOS = {ft["properties"].get("iso") for ft in json.load(f)["features"]}
# AS and MP have no map shape but are Safety-table rows (health.json's c).
with open(os.path.join(os.path.dirname(HERE), "public", "health.json"), encoding="utf-8") as f:
    ISOS |= set(json.load(f)["c"])
KEYS = {"source", "url", "season", "built", "asof", "note", "c"}


def shape(w, built):
    errs = []
    if set(w) - KEYS:
        errs.append("extra keys %s" % (set(w) - KEYS))
    if "asof" in w and not re.fullmatch(r"\d{4}-\d\d-\d\d", str(w["asof"])):
        errs.append("asof %r" % w["asof"])
    if "asof" in w and "ECDC" not in w.get("source", ""):
        errs.append("asof without ECDC")
    if w.get("source") not in ("ECDC", "CDC", "ECDC · CDC"):
        errs.append("source %r" % w.get("source"))
    if not str(w.get("url", "")).startswith("https://"):
        errs.append("url")
    if not re.fullmatch(r"\d{4}", str(w.get("season"))):
        errs.append("season %r" % w.get("season"))
    if w.get("built") != built:
        errs.append("built")
    if "note" in w and not isinstance(w["note"], str):
        errs.append("note")
    for iso, v in w["c"].items():
        if not re.fullmatch(r"[A-Z]{2}", iso) or iso not in ISOS:
            errs.append("iso %s" % iso)
        if set(v) - {"a", "t"} or not isinstance(v.get("t"), str) or not re.match(r"(ECDC|CDC): ", v["t"]):
            errs.append("entry %s" % iso)
        if "a" in v and (not isinstance(v["a"], list) or not 0 < len(v["a"]) <= wn.MAX_AREAS
                         or not all(isinstance(x, str) and x for x in v["a"])):
            errs.append("areas %s" % iso)
    json.dumps(w)
    return errs


ecdc, cdc = wn.parse_ecdc(W37), wn.parse_cdc(CDC_CSV, CDC_CONFIG, CDC_PAGE)
w = wn.build(ecdc, cdc, BUILT)
errs = shape(w, BUILT)
results.append(ok(not errs, "contract: both sources -> C1 shape, every key an ISO the map knows %s" % (errs or "")))
results.append(ok(w["source"] == "ECDC · CDC" and w["url"] == wn.ECDC_URL and w["note"] == wn.NOTE_ALL
                  and len(w["c"]) == 16 and list(w["c"]) == sorted(w["c"]),
                  "contract: 'ECDC · CDC', 16 countries in ISO order, coverage note"))
results.append(ok(w["asof"] == "2026-09-10", "contract: w.asof = the ECDC data's own date (10 Sep)"))
results.append(ok(all(x in wn.NOTE_ALL for x in ("EU/EEA", "Albania", "Bosnia and Herzegovina", "Kosovo", "Montenegro",
                                                 "North Macedonia", "Serbia", "Türkiye", "CDC covers the US"))
                  and all("no entry doesn't mean no West Nile" in n and "elsewhere" not in n
                          for n in (wn.NOTE_ALL, wn.NOTE_NO_CDC, wn.NOTE_NO_ECDC))
                  and "US data (CDC) unavailable" in wn.NOTE_NO_CDC and "Europe's data (ECDC) unavailable" in wn.NOTE_NO_ECDC,
                  "notes: ECDC's exact coverage named; the caveat applies everywhere, not 'elsewhere'"))
w1 = wn.build(ecdc, None, BUILT)
w2 = wn.build(None, cdc, BUILT)
results.append(ok(w1["source"] == "ECDC" and w1["note"] == wn.NOTE_NO_CDC and "US" not in w1["c"] and not shape(w1, BUILT),
                  "contract: ECDC only -> note says the US is missing"))
results.append(ok(w2["source"] == "CDC" and w2["url"] == wn.CDC_URL and w2["note"] == wn.NOTE_NO_ECDC
                  and list(w2["c"]) == ["US"] and "asof" not in w2 and not shape(w2, BUILT),
                  "contract: CDC only -> CDC's page, note says Europe is missing"))
results.append(ok(wn.build(None, None, BUILT) is None, "contract: nothing read -> None (w absent)"))
results.append(ok(wn.build(wn.parse_ecdc(W2025), None, "2026-03-01")["season"] == "2025",
                  "contract: off-season build carries the last season"))
be_w = wn.build(be, None, BUILT)
results.append(ok(not shape(be_w, BUILT) and "a" not in be_w["c"]["BE"], "contract: a summary-only country fits C1 (no 'a')"))
terr = wn.build(None, wn.parse_cdc('"State","Reported Cases","Legend"\nAS,1,1 to 5\nMP,1,1 to 5\n', CDC_CONFIG, CDC_PAGE), BUILT)
results.append(ok(set(terr["c"]) == {"AS", "MP"} and not shape(terr, BUILT),
                  "contract: AS and MP kept (Safety-table rows, though not on the map)"))

# built: a date object works (it used to raise inside build(), which get()
# turned into None); a malformed string raises instead of being stored.
results.append(ok(wn.build(ecdc, cdc, datetime.date(2026, 10, 3)) == w
                  and wn.build(ecdc, cdc, datetime.datetime(2026, 10, 3, 9, 30)) == w,
                  "built: date and datetime -> '2026-10-03', same w as the string"))
bad = []
for b_ in ("2026-10-3", "03/10/2026", "2026-13-01", "", 20261003):
    try:
        wn.build(ecdc, cdc, b_)
        bad.append(b_)
    except ValueError:
        pass
results.append(ok(not bad, "built: malformed values raise ValueError %s" % (bad or "")))

# Merging the stored w (old) with a new build is the server's job —
# build_health.merge_w, the one rule (westnile.keep_newer duplicated it and
# lacked its season guard). ECDC: an archive copy dated before the stored live
# read must not replace it; a source that failed keeps its stored entries.
from fxtracker import build_health as bh
NOTES = {frozenset(("ECDC", "CDC")): wn.NOTE_ALL, frozenset(("ECDC",)): wn.NOTE_NO_CDC, frozenset(("CDC",)): wn.NOTE_NO_ECDC}
merge = lambda new_w, old_w: bh.merge_w(new_w, old_w, NOTES, log=lambda *a: None)
e_live = wn.parse_ecdc(W37)
e_live["asof"] = "2026-10-01"
e_live["countries"]["IT"]["cases"] = 700
cdc_old = wn.parse_cdc('"State","Reported Cases","Legend"\nTX,5,1 to 5\n', CDC_CONFIG, CDC_PAGE)
old = wn.build(e_live, cdc_old, "2026-10-02")
new = wn.build(ecdc, cdc, BUILT)                 # archive W37 (10 Sep) + fresh CDC
k = merge(new, old)
results.append(ok(k["c"]["IT"] == old["c"]["IT"] and "700" in k["c"]["IT"]["t"] and "(as of 1 Oct)" in k["c"]["IT"]["t"]
                  and k["c"]["US"] == new["c"]["US"] and k["asof"] == "2026-10-01" and k["built"] == BUILT
                  and k["source"] == "ECDC · CDC" and k["note"] == wn.NOTE_ALL and not shape(k, BUILT),
                  "merge_w: older ECDC (10 Sep < 1 Oct) keeps the stored Europe, takes the new CDC"))
newer = dict(old, built="2026-10-04")           # built after the stored one, ECDC as of 1 Oct
results.append(ok(merge(newer, new) is newer, "merge_w: newer ECDC and CDC -> the new w as is"))
results.append(ok(merge(None, old) is old and merge(new, None) is new and merge(None, None) is None,
                  "merge_w: nothing new -> the stored w; nothing stored -> the new one"))
k = merge(wn.build(None, cdc, BUILT), old)
results.append(ok(k["c"]["IT"] == old["c"]["IT"] and k["c"]["US"] == new["c"]["US"] and k["source"] == "ECDC · CDC"
                  and k["asof"] == "2026-10-01" and k["note"] == wn.NOTE_ALL and not shape(k, BUILT),
                  "merge_w: ECDC failed -> stored Europe + new CDC"))
k = merge(wn.build(e_live, None, BUILT), new)
results.append(ok(k["c"]["IT"] == old["c"]["IT"] and k["c"]["US"] == new["c"]["US"] and k["asof"] == "2026-10-01"
                  and k["source"] == "ECDC · CDC" and not shape(k, BUILT),
                  "merge_w: CDC failed -> new Europe + stored US"))
# The season-concluded case: ECDC's last weekly report drops the "as of" from
# every sentence ("in the 2026 season"), so only w.asof says how current the
# stored Europe is — an older archive read must still not replace it.
done_old = dict(old, asof="2026-11-19", built="2026-11-25")
done_old["c"] = {iso: (dict(e, t=e["t"].replace("in 2026 so far (as of 1 Oct)", "in the 2026 season"))
                       if e["t"].startswith("ECDC") else e) for iso, e in old["c"].items()}
k = merge(dict(new, built="2026-12-02"), done_old)
results.append(ok(k["c"]["IT"] == done_old["c"]["IT"] and k.get("asof") == "2026-11-19",
                  "merge_w: season concluded (no as-of in the sentences) -> w.asof keeps the newer stored Europe"))
# A new season where only CDC was read: last season's Europe is dropped, not
# relabelled as this season's.
cdc27 = wn.parse_cdc('"State","Reported Cases","Legend"\nTX,5,1 to 5\n', CDC_CONFIG, CDC_PAGE)
k = merge(dict(wn.build(None, cdc27, "2027-07-01"), season="2027"), old)
results.append(ok(k is None or "IT" not in k["c"] or "2027" not in str(k.get("season")) or k["c"]["IT"]["t"].find("2026") >= 0,
                  "merge_w: a 2027 CDC-only build never labels 2026 Europe as 2027"))

# --- get(): routes, offline ----------------------------------------------------------------
GZ = gzip.compress(W37.encode("utf-8"))   # the archive serves ECDC's gzip bytes as they were


class Headers(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


FETCHED = []


def fake(live_ok, archive_ok, cdc_ok, config=CDC_CONFIG):
    def _fetch(url, retries=2, timeout=None):
        FETCHED.append(url)
        if url == wn.ECDC_LIVE and live_ok:
            return W37.encode("utf-8"), Headers()
        if wn.ECDC_ARCHIVE and url == wn.ECDC_ARCHIVE and archive_ok:
            return W37.encode("utf-8"), Headers()
        if cdc_ok and url == wn.CDC_CONFIG:
            return json.dumps(config).encode(), Headers()
        if cdc_ok and url.replace("%20", " ") == wn._cdc_map(config)[0]:
            return CDC_CSV.encode(), Headers({"Last-Modified": "Tue, 29 Sep 2026 16:28:37 GMT"})
        if cdc_ok and url == wn.CDC_URL:
            return CDC_PAGE.encode(), Headers()
        raise urllib.error.URLError("timed out")
    return _fetch


class Resp(io.BytesIO):
    headers = Headers()
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False


real_open = wn.urllib.request.urlopen
try:
    wn.urllib.request.urlopen = lambda req, timeout=None, context=None: Resp(GZ)
    body, _ = wn._fetch(wn.ECDC_ARCHIVE)
    results.append(ok(body == W37.encode("utf-8"), "_fetch: gzip body from the archive is unpacked"))
    wn.urllib.request.urlopen = lambda req, timeout=None, context=None: Resp(b"plain")
    results.append(ok(wn._fetch("https://example.invalid/")[0] == b"plain", "_fetch: plain body untouched"))
finally:
    wn.urllib.request.urlopen = real_open

real_fetch = wn._fetch
try:
    wn._fetch = fake(True, True, True)
    info = {}
    w = wn.get(BUILT, info)
    results.append(ok(info.get("ecdc") == "live" and info.get("cdc") == "live" and len(w["c"]) == 16,
                      "get: live ECDC + CDC -> 16 countries"))
    results.append(ok(info.get("ecdc_asof") == "2026-09-10" and info.get("cdc_asof") == "2026-09-29" and w["asof"] == "2026-09-10",
                      "get: info carries each source's 'as of' date; w.asof is ECDC's"))
    wn._fetch = fake(False, True, True)
    info = {}
    w = wn.get(BUILT, info)
    results.append(ok(info.get("ecdc") == "archive" and "live" in str(info.get("ecdc_errors")) and "IT" in w["c"],
                      "get: live ECDC unreachable -> archived copy, the failure recorded"))
    wn._fetch = fake(False, False, True)
    info = {}
    w = wn.get(BUILT, info)
    results.append(ok(str(info.get("ecdc")).startswith("failed") and w["source"] == "CDC",
                      "get: no ECDC at all -> CDC alone"))
    saved, wn.ECDC_ARCHIVE = wn.ECDC_ARCHIVE, None
    wn._fetch = fake(False, True, True)
    info = {}
    w = wn.get(BUILT, info)
    wn.ECDC_ARCHIVE = saved
    results.append(ok(w["source"] == "CDC", "get: ECDC_ARCHIVE = None turns the archive route off"))
    wn._fetch = fake(False, False, False)
    info = {}
    results.append(ok(wn.get(BUILT, info) is None and "failed" in info["cdc"], "get: both down -> None"))
    off_host = copy.deepcopy(CDC_CONFIG)
    for v in off_host["visualizations"].values():
        if "countbystate" in (v.get("dataKey") or "").lower():
            v["dataKey"] = "https://example.invalid/wnv_hum_current_CountbyState.csv"
    del FETCHED[:]
    wn._fetch = fake(False, False, True, off_host)
    info = {}
    results.append(ok(wn.get(BUILT, info) is None and "www.cdc.gov" in info["cdc"]
                      and not any("example.invalid" in u for u in FETCHED),
                      "get: a CDC config pointing the CSV off www.cdc.gov fails CDC, the URL never fetched"))
    del FETCHED[:]
    try:
        wn.get("3 Oct 2026", {})
        raised = False
    except ValueError:
        raised = True
    results.append(ok(raised and not FETCHED, "get: a malformed built raises before anything is fetched"))

    # main(): the CLI.
    def cli(*argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = wn.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    W37_PATH = os.path.join(HERE, "westnile_sample.ecdc-2026w37.html")
    rc, out, err = cli("--ecdc-file", W37_PATH, "--no-cdc", "--built", BUILT)
    lines = out.splitlines()
    results.append(ok(rc == 0 and lines[0] == "ECDC · season 2026 · built 2026-10-03 · 15 countries"
                      and lines[1] == "note: " + wn.NOTE_NO_CDC and "file" in err and "2026-09-10" in err,
                      "main --ecdc-file --no-cdc: summary line, note, route and date on stderr"))
    gr = lines[lines.index("  GR  " + wn.ecdc_entries(wn.parse_ecdc(W37), BUILT)["GR"]["t"]) + 1]
    results.append(ok("Anatoliki Attiki · " in gr and " · Karditsa, Trikala" in gr,
                      "main: areas joined with ' · ' so 'Karditsa, Trikala' stays one area"))
    rc, out, err = cli("--ecdc-file", W37_PATH, "--no-cdc", "--built", BUILT, "--json")
    results.append(ok(rc == 0 and json.loads(out) == json.loads(json.dumps(wn.build(wn.parse_ecdc(W37), None, BUILT))),
                      "main --json: the w dict"))
    wn._fetch = fake(False, True, True)
    rc, out, err = cli("--built", BUILT)
    results.append(ok(rc == 0 and "archive" in err and "ECDC · CDC · season 2026 · built 2026-10-03 · 16 countries" in out,
                      "main (fetching): live ECDC down -> archive, said on stderr; 16 countries"))
    del FETCHED[:]
    rc, out, err = cli("--built", "2026-10-3")
    results.append(ok(rc == 2 and "--built" in err and not FETCHED, "main --built 2026-10-3: exit 2, nothing fetched"))
    rc, out, err = cli("--no-ecdc", "--no-cdc", "--built", BUILT)
    results.append(ok(rc == 1 and "no West Nile data" in out, "main --no-ecdc --no-cdc: exit 1"))
finally:
    wn._fetch = real_fetch

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
