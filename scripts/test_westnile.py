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
import base64, csv, gzip, io, json, os, re, sys, urllib.error

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
results.append(ok(ent["IT"]["t"] == "ECDC: 590 locally acquired human cases in 64 areas in 2026 so far (as of 10 Sep)",
                  "W37: Italy's sentence"))
results.append(ok(ent["XK"]["t"] == "ECDC: 1 locally acquired human case in 1 area in 2026 so far (as of 10 Sep)"
                  and ent["XK"]["a"] == ["Gjakovë"], "W37: singular wording, Kosovo's area"))
results.append(ok(len(ent["IT"]["a"]) == 10 and ent["IT"]["a"][:3] == ["Padova", "Milano", "Roma"],
                  "W37: at most 10 areas, in ECDC's spelling"))
results.append(ok("Karditsa, Trikala" in ent["GR"]["a"], "W37: a two-place area keeps ECDC's name"))
off = wn.ecdc_entries(e, "2027-01-15")
results.append(ok(off["IT"]["t"] == "ECDC: 590 locally acquired human cases in 64 areas in the 2026 season",
                  "W37 read in January 2027: 'in the 2026 season', no 'so far'"))

# Same table from the DataTables widget when the data.csv button is gone.
no_csv = re.sub(r"data:text/csv;base64,[A-Za-z0-9+/=]+", "", W37)
e2 = wn.parse_ecdc(no_csv)
results.append(ok({i: (c["cases"], c["areas"]) for i, c in e2["countries"].items()} ==
                  {i: (c["cases"], c["areas"]) for i, c in C.items()},
                  "W37: table widget fallback gives the same countries, areas and cases"))

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
results.append(ok(ent["IT"]["t"] == "ECDC: locally acquired human cases in 64 areas in the 2025 season",
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


def shape(w, built):
    errs = []
    if set(w) - {"source", "url", "season", "built", "note", "c"}:
        errs.append("extra keys %s" % (set(w) - {"source", "url", "season", "built", "note", "c"}))
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
w1 = wn.build(ecdc, None, BUILT)
w2 = wn.build(None, cdc, BUILT)
results.append(ok(w1["source"] == "ECDC" and w1["note"] == wn.NOTE_NO_CDC and "US" not in w1["c"] and not shape(w1, BUILT),
                  "contract: ECDC only -> note says the US is missing"))
results.append(ok(w2["source"] == "CDC" and w2["url"] == wn.CDC_URL and w2["note"] == wn.NOTE_NO_ECDC
                  and list(w2["c"]) == ["US"] and not shape(w2, BUILT),
                  "contract: CDC only -> CDC's page, note says Europe is missing"))
results.append(ok(wn.build(None, None, BUILT) is None, "contract: nothing read -> None (w absent)"))
results.append(ok(wn.build(wn.parse_ecdc(W2025), None, "2026-03-01")["season"] == "2025",
                  "contract: off-season build carries the last season"))

# --- get(): routes, offline ----------------------------------------------------------------
GZ = gzip.compress(W37.encode("utf-8"))   # the archive serves ECDC's gzip bytes as they were


class Headers(dict):
    def get(self, k, d=None):
        return dict.get(self, k, d)


def fake(live_ok, archive_ok, cdc_ok):
    def _fetch(url, retries=2, timeout=None):
        if url == wn.ECDC_LIVE and live_ok:
            return W37.encode("utf-8"), Headers()
        if wn.ECDC_ARCHIVE and url == wn.ECDC_ARCHIVE and archive_ok:
            return W37.encode("utf-8"), Headers()
        if cdc_ok and url == wn.CDC_CONFIG:
            return json.dumps(CDC_CONFIG).encode(), Headers()
        if cdc_ok and url.replace("%20", " ") == wn._cdc_map(CDC_CONFIG)[0]:
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
finally:
    wn._fetch = real_fetch

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
