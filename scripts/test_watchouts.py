"""Canada's regional advisories as fxtracker/watchouts.py reads them, offline,
from the trimmed feed copies in scripts/fixtures/gac (2026-10-14, checked
against travel.gc.ca that day; see its README).

  blocks     every regional block kept (Israel's Lebanon and Gaza lines,
             Thailand's and Cambodia's shared border, Indonesian Papua), the
             country-wide one left out however its heading spells the name
  line       the area as Canada's first sentence names it, the listed places
             with their sub-lists folded in, the exceptions named (the
             second-sentence ones Kenya, Uganda, Mozambique, Azerbaijan,
             Tanzania and India carry), what a block includes (Benin's
             parks); a qualifier is never an exception; long lists cut to
             "and N more" with the right N; no line past the cap; no stars
  brief      the trip prompt's form: short lines whole, a named heading for
             a long one, a generic heading never alone
  text       Canada's whole block for the tip, without "Useful links"
  API        backward-compatible keys (iso, source, link, watchouts,
             regional[].t/.lead/.regions) beside the new ones
  stand-in   guide_sizers.py draws the same words as app.js's
             watchoutsBlockHTML, which reads line and puts text in its ⓘ
  caching    an answer is kept TTL, a failure keeps the last good copy, a
             country the feed lacks is an empty answer

    /usr/bin/python3 scripts/test_watchouts.py
"""
import io
import json
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stderr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import guide_sizers, watchouts as W  # noqa: E402

FIX = os.path.join(ROOT, "scripts", "fixtures", "gac")
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def feed(iso):
    with open(os.path.join(FIX, iso + ".json"), encoding="utf-8") as f:
        return json.load(f)


ALL = sorted(f[:-5] for f in os.listdir(FIX) if f.endswith(".json"))
OUT = {iso: W.from_feed(iso, feed(iso)) for iso in ALL}


def block(iso, heading_part):
    for r in OUT[iso]["regional"]:
        if heading_part.lower() in r["t"].lower():
            return r
    return {"t": "", "call": "", "line": "", "brief": "", "text": "", "items": [], "excepts": [], "includes": [], "lead": "", "regions": []}


def line(iso, heading_part):
    r = block(iso, heading_part)
    return (r["call"] + ": " + r["line"]) if r["line"] else ""


# --- every block kept ------------------------------------------------------------
# An independent count: every h3 but the country's own (its heading's area is
# the country's name), less GAC's [placeholder] records.
def words(s):
    s = re.sub(r"\([^)]*\)", " ", s.lower().replace("’", "'"))
    return [w for w in re.sub(r"[^a-z0-9' ]+", " ", s).split() if w != "the"]


missing = []
for iso in ALL:
    e = feed(iso)["data"]["eng"]
    heads = [re.sub(r"\s+", " ", W._txt(h)) for h in re.findall(r"<h3[^>]*>(.*?)</h3>", e.get("advisories") or "", re.S)]
    want = [h for h in heads if h and words(h.split(" - ")[0]) != words(e.get("name") or "")]
    got = [r["t"] for r in OUT[iso]["regional"]]
    if got != [h[:120] for h in want]:
        missing.append((iso, len(want), len(got)))
results.append(ok(not missing, "every regional block kept, in Canada's order, on all %d fixtures (mismatches: %s)" % (len(ALL), missing)))
il = [r["t"] for r in OUT["il"]["regional"]]
results.append(ok(len(il) == 6 and any("Lebanon" in t for t in il) and any("Gaza" in t for t in il),
                  "Israel keeps all six blocks, the Lebanon and Gaza borders among them (the old cap of 4 dropped both) (got %s)" % il))
results.append(ok(line("il", "Border with Lebanon") == "Avoid all travel: the area within 5 kilometres of the border with Lebanon"
                  and line("il", "Gaza Strip") == "Avoid all travel: the area within 10km of the border with the Gaza Strip",
                  "Israel's Lebanon and Gaza lines say Canada's bands (got %r / %r)" % (line("il", "Lebanon"), line("il", "Gaza Strip"))))
pal = line("il", "PALESTINE")
results.append(ok(pal.startswith("Avoid all travel: Palestine, except the following roads, where you should avoid non-essential travel: Highway 1; Route 90")
                  and "near Jericho" in pal,
                  "Palestine: the area, then the two roads as Canada's exceptions with their own call (got %r)" % pal))
results.append(ok(line("th", "Thailand-Cambodia") == "Avoid all travel: the area within 50 kilometres of the Thailand-Cambodia border",
                  "Thailand's Cambodia border line is kept (its heading starts with the country's name; a prefix test hid it) (got %r)" % line("th", "Thailand-Cambodia")))
results.append(ok(line("th", "Southern provinces") == "Avoid all travel: Narathiwat; Pattani; Yala; southern Songkhla province (Hat Yai city; east of Highways 408 and 4113, including Sakom)",
                  "Thailand's south: southern Songkhla's sibling list (Hat Yai) folded under it (got %r)" % line("th", "Southern provinces")))
results.append(ok(block("kh", "Cambodia-Thailand")["line"] and block("id", "Indonesian Papua")["line"].startswith("all the provinces of Indonesian Papua, except"),
                  "Cambodia's Thai border and Indonesian Papua are kept too, Papua with its Raja Ampat and Sorong exception"))
results.append(ok(not OUT["bs"]["regional"] and not OUT["ci"]["regional"][0]["t"].startswith("Côte"),
                  "the country-wide block is left out where its heading spells the name otherwise (The Bahamas on 'Bahamas', Côte d’Ivoire)"))

# --- exceptions and inclusions from later sentences --------------------------------
SECOND = [
    ("ke", "Border with Somalia", "Mandera, Wajir, Garissa and Lamu counties bordering Somalia, except Lamu Island and Manda Island"),
    ("ug", "Border with South Sudan", "areas within 50 km of the border with South Sudan, except visits to national parks when accompanied by a reputable guide"),
    ("mz", "Cabo Delgado", "Cabo Delgado Province, except Pemba City to which you should avoid non-essential travel"),
    ("az", "Border with Armenia", "except the border between Armenia and the Azerbaijani Autonomous Republic of Nakhchivan, where you should exercise a high degree of caution"),
    ("bj", "Border areas with Burkina Faso", "including the W National Park and the Pendjari National Park"),
    ("tz", "Portion of Mtwara", "except the areas within 10 km from the border with Mozambique, where you should avoid all travel; Mtwara City"),
    ("in", "Jammu and Kashmir", "the Union Territory of Jammu and Kashmir, except travelling to or within the Union Territory of Ladakh"),
    ("jo", "Borders with Iraq and Syria", "within 5 km of the borders with Iraq and Syria, except the tourist site Umm Qais"),
    ("tg", "Border with Burkina Faso", "including the city and area north of Dapaong, travel along the N28 and N16 highways, as well as the cities of Cinkassé"),
    ("eg", "Northern Sinai", "except the Al Qantra Shark – Ras Sedr road"),
]
for iso, h, want in SECOND:
    got = block(iso, h)["line"]
    results.append(ok(want in got, "%s %s: %r in the line (got %r)" % (iso.upper(), h, want, got)))
results.append(ok("where you should avoid all travel" in block("tz", "Portion of Mtwara")["brief"] + block("tz", "Portion of Mtwara")["line"],
                  "Tanzania: a stricter exception keeps its own call ('where you should avoid all travel') however short the line"))

# --- nested lists ------------------------------------------------------------------
NESTED = [
    ("mx", "Regional Advisory", "Chiapas (except Palenque, Tuxtla Gutiérrez, San Cristobal de las Casas)"),
    ("gt", "Regional advisories", "Within Guatemala City: Zone 1, Zone 3, Zones 5–7, Zone 18, Zone 21. Municipalities: in Guatemala Department (San Pedro Ayampuc, Villa Canales)"),
    ("hn", "Regional advisory", "within 20 km of the border with Guatemala (except Copán Ruinas, El Florido border crossing"),
    ("co", "Border areas", "Chocó (except the towns of Bahía Solano, Capurganá, Nuquí)"),
    ("ec", "Esmeraldas province", "in the province of El Oro (Machala, Huaquillas); in the province of Guayas (Durán"),
    ("mr", "Northern and eastern", "especially all of the following regions (Tiris Zemmour, Hodh El Gharbi, Hodh Ech Chargui)"),
    ("pe", "VRAEM", "in the Department of Apurímac (Province of Abancay, Province of Andahuaylas, Province of Chincheros)"),
    ("et", "Central regions", "zones in the Oromia region (North Shewa"),
    ("tn", "Avoid all travel", "following tourist towns: Aïn Draham, Chebika, Mides, Tabarka, Tamerza"),
    ("pk", "Regional advisory", "the province of Khyber Pakhtunkhwa (except Haripur and Abbottabad districts, Chitral district)"),
    ("ph", "Central and Eastern", "Davao del Sur (except Davao City)"),
    ("ph", "Central and Eastern", "Surigao del Norte (except Siargao Island)"),
    ("br", "Border areas", "within 20 km of the border with Bolivia (except Pantanal National Park), Colombia, French Guiana, Guyana, Paraguay, Peru, Suriname; within 50 km of the border with Venezuela"),
    ("dz", "Border areas", "Tunisia (except travel by land to/from Tunisia via the N44 highway and the Oum Tboul border crossing"),
    ("ge", "occupied regions", "(except Highway E60)"),
    ("la", "Bokeo", "(except Bokeo International Airport and Road 3 leading there)"),
    ("xk", "Northern Kosovo", "the northern part of Kosovo, particularly in the municipalities of Leposavić, North Mitrovica, Zubin Potok, Zvečan"),
    ("pa", "High-crime", "District of San Miguelito, especially the following areas (Amelia Denis de Icaza"),
]
for iso, h, want in NESTED:
    got = block(iso, h)["line"]
    results.append(ok(want in got, "%s %s: %r (got %r)" % (iso.upper(), h, want, got)))
mx = block("mx", "Regional Advisory")["items"]
co = block("co", "Border areas")["items"]
results.append(ok(len(mx) == 14 and len(mx[0].get("items", [])) == 3 and len(mx[5].get("items", [])) == 2
                  and len([x for x in co if x["t"].startswith("Chocó")][0].get("items", [])) == 3,
                  "items: Mexico's 14 states, Chiapas's 3 exclusions in its <li>, Jalisco's 2 and Chocó's 3 in a sibling <ul> after theirs"))
ka = block("pk", "Karachi")["line"]
results.append(ok(ka.startswith("the city of Karachi, except District of Karachi") and "(except the areas northwest of Muhammad Ali Jinnah Road" in ka,
                  "Karachi: the city, its exceptions, and the exception's own exclusion kept whole — cut, it would except more than Canada (got %r)" % ka))

# --- "and N more" -------------------------------------------------------------------
def top_split(s, sep):
    out, depth, cur = [], 0, ""
    i = 0
    while i < len(s):
        c = s[i]
        depth += (c == "(") - (c == ")")
        if depth == 0 and s.startswith(sep, i):
            out.append(cur)
            cur, i = "", i + len(sep)
            continue
        cur += c
        i += 1
    return out + [cur]


counts = []
for iso in ALL:
    for r in OUT[iso]["regional"]:
        m = re.search(r"(?:^|[;,] )and (\d+) more$", r["line"])
        if not m or ". " in r["line"] or " — " in r["line"] or ", except " in r["line"] or not r["items"]:
            continue
        body = r["line"][:m.start()]
        body = body.split(": ", 1)[1] if ": " in body and not body.split(": ", 1)[0].count("(") else body
        sep = "; " if "; " in r["line"] else ", "
        shown = len(top_split(body, sep))
        counts.append((iso, r["t"][:30], shown, int(m.group(1)), len(r["items"])))
bad = [c for c in counts if c[2] + c[3] != c[4]]
results.append(ok(counts and not bad, "'and N more': places shown + N = Canada's list, on every cut single-list line (%d lines; wrong: %s)" % (len(counts), bad)))
WANT_N = {("mx", "Regional Advisory"): 10, ("co", "Border areas"): 4, ("co", "Regional advisory"): 14,
          ("gt", "Regional advisories"): 8, ("pe", "VRAEM"): 3, ("pk", "Regional advisory"): 3, ("bj", "Border areas with Burkina"): 2,
          ("hn", "Regional advisory"): 2}
for (iso, h), n in WANT_N.items():
    got = block(iso, h)["line"]
    results.append(ok(got.endswith("and %d more" % n) or (" and %d more —" % n) in got,
                      "%s %s: 'and %d more' (got %r)" % (iso.upper(), h, n, got[-60:])))

# --- caps, stars, qualifiers -----------------------------------------------------------
lines = [(iso, r) for iso in ALL for r in OUT[iso]["regional"]]
over = [(iso, len(r["line"])) for iso, r in lines if len(r["line"]) > W.LINE_MAX
        or (re.search(r"and \d+ more", r["line"]) and len(r["line"]) > W.LINE_CAP)]
results.append(ok(not over, "no line past %d characters, no cut line past %d (%d lines; over: %s)" % (W.LINE_MAX, W.LINE_CAP, len(lines), over)))
results.append(ok(not [r["brief"] for _, r in lines if len(r["brief"]) > W.BRIEF_CAP],
                  "no brief past %d characters" % W.BRIEF_CAP))
results.append(ok(not [r["line"] for _, r in lines if "*" in r["line"]], "no line marks exceptions with a bare star: they are named"))
results.append(ok(all(r["line"] and r["call"] for _, r in lines), "every block has a call and a line"))
co2 = block("co", "Regional advisory")
results.append(ok(co2["line"].startswith("Amazonas, within 20 km of the border with Peru, west of Puerto Narino;")
                  and not any("Peru" in x for x in co2["excepts"]),
                  "Colombia: 'Amazonas, within 20 km of the border with Peru' is a strip of Amazonas, not Amazonas with parts excepted"))
mxl = block("mx", "Regional Advisory")["line"]
results.append(ok("Guanajuato, in all areas south of and including highways 43D and 45D" in mxl and "Guanajuato (except" not in mxl
                  and not any("Michoacán state" in x or "Sinaloa and Durango" in x for x in block("mx", "Regional Advisory")["excepts"]),
                  "Mexico: Guanajuato's highways, Jalisco's 50 km and Nayarit's 20 km are where the advice applies, never exceptions"))
qual = [(iso, r["t"]) for iso, r in lines for x in r["excepts"] if re.match(r"(?:within|in all areas)\b", x) and iso not in ("ec",)]
results.append(ok(not qual, "no exception is a 'within …' qualifier (Ecuador's is Canada's own 'except within 20 km' of a stricter band) (got %s)" % qual))

# --- brief ------------------------------------------------------------------------------
BRIEF = {("il", "PALESTINE"): "Palestine (parts excepted)",
         ("ke", "Border with Somalia"): "Mandera, Wajir, Garissa and Lamu counties bordering Somalia, except Lamu Island and Manda Island",
         ("th", "Southern provinces"): "Narathiwat; Pattani; Yala; southern Songkhla province (Hat Yai city; east of Highways 408 and 4113, including Sakom)",
         ("mz", "Cabo Delgado"): "Cabo Delgado Province, except Pemba City",
         ("ph", "Western Mindanao"): "Western Mindanao",
         ("ec", "Border areas"): "the area within 20 km of the border with Colombia in the following provinces: Carchi*, Esmeraldas, Sucumbíos"}
for (iso, h), want in BRIEF.items():
    results.append(ok(block(iso, h)["brief"] == want, "brief %s %s: %r (got %r)" % (iso.upper(), h, want, block(iso, h)["brief"])))
mxb = block("mx", "Regional Advisory")["brief"]
results.append(ok(mxb.startswith("Chiapas*; Chihuahua*; Colima*; Guanajuato, in all areas south of and including highways 43D and 45D")
                  and mxb.endswith("and 10 more"), "brief Mexico: the states starred where parts are excepted, the qualifier kept (got %r)" % mxb))
gen = [(iso, r["brief"]) for iso, r in lines if W._GENERIC.match(r["t"].split(" - ")[0].strip()) and W._GENERIC.match(r["brief"].strip())]
results.append(ok(not gen, "a generic heading ('Border areas', 'Regional advisory') never stands for its list (got %s)" % gen))

# --- the Ebola notice, text ------------------------------------------------------------
ug = block("ug", "Ebola")
results.append(ok(ug["call"].startswith("Canadian border measures related to Ebola") and ug["line"].startswith("Until November 27, 2026, Canada will have")
                  and "Useful links" not in ug["text"] and "quarantine for 21 days" in ug["text"],
                  "Uganda's Ebola notice: its heading for a call, its first sentence for a line, its rules in the tip, no 'Useful links'"))
mxt = block("mx", "Regional Advisory")["text"]
results.append(ok(all(s in mxt for s in ("Chiapas", "Zacatecas, excluding the city of Zacatecas", "◦ the area around Lake Chapala")) and len(mxt) <= W.TEXT_CAP,
                  "text: Mexico's whole block, sub-items marked, within %d characters (%d)" % (W.TEXT_CAP, len(mxt))))
results.append(ok("Natural disasters and climate" not in block("mx", "West-central")["text"],
                  "text: a paragraph that only links to another section of Canada's page is left out"))
long_html = "<h3>Somewhere - Avoid all travel</h3><p>Avoid all travel to the following areas due to x:</p><ul>" + "".join(
    "<li>Place %d is a long name that goes on for a while. And then a second sentence about it.</li>" % i for i in range(60)) + "</ul>"
lt = W.regional_blocks(long_html, "Nowhere")[0]["text"]
results.append(ok(len(lt) <= W.TEXT_CAP and lt.endswith("…"), "text: cut at a line or sentence near %d characters and marked (got %d)" % (W.TEXT_CAP, len(lt))))

# --- placeholders, the cap, the API's keys -------------------------------------------------
ph_html = "<h3>[info alert heading]</h3><p>[description of event]</p><h3>Real - Avoid all travel</h3><p>Avoid all travel to Real due to y.</p>"
results.append(ok([r["t"] for r in W.regional_blocks(ph_html, "Nowhere")] == ["Real - Avoid all travel"], "GAC's [placeholder] records are skipped"))
many = {"data": {"eng": {"name": "Nowhere", "url-slug": "nowhere", "advisories": "".join(
    "<h3>Area %d - Avoid all travel</h3><p>Avoid all travel to area %d due to z.</p>" % (i, i) for i in range(15))}}}
err = io.StringIO()
with redirect_stderr(err):
    capped = W.from_feed("zz", many)
results.append(ok(len(capped["regional"]) == W.REGIONAL_CAP and "15 regional blocks" in err.getvalue(),
                  "more than %d blocks: the first %d kept, and logged (%r)" % (W.REGIONAL_CAP, W.REGIONAL_CAP, err.getvalue().strip())))
keys_ok = all({"iso", "source", "link", "watchouts", "regional"} <= set(o) for o in OUT.values()) and all(
    isinstance(r["t"], str) and isinstance(r["lead"], str) and isinstance(r["regions"], list) and all(isinstance(x, str) for x in r["regions"])
    and {"call", "line", "brief", "text", "items", "excepts", "includes"} <= set(r) for _, r in lines)
results.append(ok(keys_ok, "API: iso, source, link, watchouts and regional[].t/.lead/.regions as before, call/line/brief/text/items/excepts/includes added"))
results.append(ok(block("pk", "Regional advisory")["regions"][:2] == ["Pakistan-administered Kashmir", "the province of Balochistan"]
                  and OUT["il"]["link"] == "https://travel.gc.ca/destinations/israel-and-palestine",
                  "regions keep today's meaning (the first list's top level), link the travel.gc.ca page"))
results.append(ok(block("ke", "Border with Somalia")["lead"] == "Avoid all travel to Mandera, Wajir, Garissa and Lamu counties bordering Somalia, due to a risk of terrorist attacks, kidnapping and armed attacks."
                  and len(block("eg", "Northern part of the Governorate")["lead"]) > 120 and "St. Catherine" in block("eg", "Northern part of the Governorate")["lead"],
                  "lead: the whole first sentence, not cut at 200 or at 'St.'"))

# --- the server's stand-in and app.js draw the same words -----------------------------------
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


m = re.search(r"^const esc = .*?;$", APP, re.M | re.S)
ESC = (m.group(0) if m else "") + "\n"
plain = lambda h: re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", h).replace("&amp;", "&").replace("&#x27;", "'").replace("&#39;", "'")
                         .replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")).strip()
pick = ["il", "th", "ke", "mx", "pk", "co", "gt", "eg"]
prog = ESC + js_fn("watchoutsBlockHTML") + "\nconst W = %s;\nconst out = {};\nfor (const c in W) out[c] = watchoutsBlockHTML(W[c]).reg;\nprint(JSON.stringify(out));" % json.dumps(
    {iso: dict(OUT[iso], watchouts=[]) for iso in pick})
try:
    js = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception:
    js = {}
same, tips = [], []
for iso in pick:
    srv = "".join(re.findall(r'<span class="woreg">.*?</span>(?=<span class="woreg">|<details|$)', guide_sizers._watchouts(dict(OUT[iso], watchouts=[]), 1)))
    same.append(plain(js.get(iso, "x")) == plain(srv) and plain(srv))
    tips.append(all(("data-tip=\"" + "Global Affairs Canada&#39;s full text:") in js.get(iso, "") for _ in [0])
                and js.get(iso, "").count("data-tip=") == len(OUT[iso]["regional"]))
results.append(ok(all(same), "guide_sizers draws the same 📍 words as app.js's watchoutsBlockHTML (%s)" % dict(zip(pick, map(bool, same)))))
results.append(ok(all(tips), "app.js: each 📍 line carries an ⓘ whose tip is Global Affairs Canada's full text"))
il_js = plain(js.get("il", ""))
results.append(ok("Avoid all travel: Palestine, except the following roads" in il_js and "Highway 1; Route 90" in il_js
                  and "parts excepted" not in il_js, "app.js renders the line (Israel), not the older reader's form (got %r)" % il_js[:160]))
old = {"watchouts": [], "regional": [{"t": "PALESTINE - AVOID ALL TRAVEL", "lead": "Avoid all travel to Palestine due to x.", "regions": ["Highway 1"]}]}
prog = (ESC + "\n".join(js_fn(n) for n in ("unshout", "avoidLead", "avoidText", "watchoutsBlockHTML"))
        + "\nconst AVOID_GENERIC = /^(regional advisory|border (areas?|regions?))$/i;\nprint(JSON.stringify(watchoutsBlockHTML(%s).reg));" % json.dumps(old))
try:
    fb = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception:
    fb = ""
results.append(ok("Avoid all travel</b>: Palestine" in fb and "data-tip" not in fb,
                  "app.js: a reply without line (cached before) takes the older reader (got %r)" % fb[:120]))

# --- caching (the network stubbed) -----------------------------------------------------------
calls = []


class HTTPErr(Exception):
    def __init__(self, code):
        self.code = code


def stub(answers):
    def f(url):
        calls.append(url)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a
    return f


real = W.rates.fetch_json
try:
    W._cache.clear()
    W.rates.fetch_json = stub([feed("ke")])
    a = W.get_watchouts("KE")
    b = W.get_watchouts("ke")
    results.append(ok(a == b and len(calls) == 1 and a["regional"] and W.cached("KE") == a, "an answer is cached for TTL and served by cached()"))
    W._cache["ke"] = (time.time() - W.TTL - 1, W._cache["ke"][1])
    W.rates.fetch_json = stub([TimeoutError("slow")])
    c = W.get_watchouts("ke")
    results.append(ok(c == a and len(calls) == 2, "a failed refresh keeps the last good copy"))
    W._cache.clear()
    W.rates.fetch_json = stub([HTTPErr(429)])
    d = W.get_watchouts("ug")
    results.append(ok(d["regional"] == [] and W._cache["ug"][1].get("_failed") and W.cached("ug") is None,
                      "a failure with nothing cached is an empty answer remembered only FAIL_TTL (a 429 included)"))
    W.rates.fetch_json = stub([HTTPErr(404)])
    e = W.get_watchouts("eh")
    results.append(ok(e["regional"] == [] and not W._cache["eh"][1].get("_failed"), "a country the feed lacks (404) is an empty answer for the full TTL"))
finally:
    W.rates.fetch_json = real
    W._cache.clear()

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
