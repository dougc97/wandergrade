"""Canada's regional advisories as fxtracker/watchouts.py reads them, offline,
from the trimmed feed copies in scripts/fixtures/gac (2026-10-14, checked
against travel.gc.ca that day; see its README).

  blocks     every regional block kept (Israel's Lebanon and Gaza lines,
             Thailand's and Cambodia's shared border, Indonesian Papua), the
             country-wide one left out however its heading spells the name
             (counted by hand per fixture)
  line       the area as Canada's first sentence names it, the listed places
             with their sub-lists folded in, the exceptions named (the
             second-sentence ones Kenya, Uganda, Mozambique, Azerbaijan,
             Tanzania and India carry), what a block includes (Benin's
             parks); a qualifier is never an exception; long lists cut to
             "and N more" with the right N, places before exceptions
             (Honduras), each of several lists with its own count
             (Guatemala); a stricter exception's call never dropped
             (Pakistan's Chitral); no line past the cap; no stars
  full       the line uncut, for the guide's AI prompt
  brief      the trip prompt's form: short lines whole, a named heading for
             a long one, up to ten names for a generic one's list; a
             stricter exception is never "parts excepted"
  latent     shapes the feed lacks today: an exclusion inside an exception,
             a paragraph after an unclosed list
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
# Counted by hand from each fixture's h3s (2026-10-14): all of them but the
# country's own level — which Israel and Palestine's page doesn't have — so
# a fault in the parser's country-wide test can't hide here behind the same
# test re-implemented.
BLOCKS = {"az": 2, "bj": 3, "br": 2, "bs": 0, "cd": 1, "ci": 2, "co": 3, "dz": 2, "ec": 4, "eg": 3, "et": 4, "ge": 2,
          "gt": 1, "hn": 1, "id": 1, "il": 6, "in": 3, "jo": 2, "jp": 0, "ke": 4, "kh": 1, "la": 2, "ma": 3, "mr": 1,
          "mx": 2, "mz": 4, "ng": 2, "pa": 4, "pe": 4, "ph": 2, "pk": 2, "ss": 1, "tg": 2, "th": 2, "tn": 2, "tz": 2,
          "ug": 2, "xk": 1}
missing = [(iso, BLOCKS.get(iso), len(OUT[iso]["regional"])) for iso in ALL if BLOCKS.get(iso) != len(OUT[iso]["regional"])]
order = [iso for iso in ALL if [r["t"] for r in OUT[iso]["regional"]] != [
    h[:120] for h in [re.sub(r"\s+", " ", W._txt(x)) for x in re.findall(r"<h3[^>]*>(.*?)</h3>", feed(iso)["data"]["eng"]["advisories"], re.S)]
    if h[:120] in [r["t"] for r in OUT[iso]["regional"]]]]
results.append(ok(not missing and not order, "every regional block kept, in Canada's order, on all %d fixtures (counts off: %s; order off: %s)" % (len(ALL), missing, order)))
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
    ("bj", "Border areas with Burkina Faso", "includes the W National Park and the Pendjari National Park"),
    ("tz", "Portion of Mtwara", "except the areas within 10 km from the border with Mozambique, where you should avoid all travel; Mtwara City"),
    ("in", "Jammu and Kashmir", "the Union Territory of Jammu and Kashmir, except travelling to or within the Union Territory of Ladakh"),
    ("jo", "Borders with Iraq and Syria", "within 5 km of the borders with Iraq and Syria, except the tourist site Umm Qais"),
    ("tg", "Border with Burkina Faso", "including the city and area north of Dapaong, travel along the N28 and N16 highways, as well as the cities of Cinkassé"),
    ("eg", "Northern Sinai", "except the Al Qantra Shark – Ras Sedr road"),
]
for iso, h, want in SECOND:
    got = block(iso, h)["line"]
    results.append(ok(want in got, "%s %s: %r in the line (got %r)" % (iso.upper(), h, want, got)))
results.append(ok("within 10 km from the border with Mozambique, where you should avoid all travel" in block("tz", "Portion of Mtwara")["line"]
                  and "where you should avoid all travel" in W._shorten("x where you should avoid all travel", {"rank": 2, "floor": 1}),
                  "Tanzania's line: a stricter exception keeps its own call ('where you should avoid all travel'), which shortening never drops"))
# A stricter exception is no relief: no "(parts excepted)" or star for it in a
# brief (Ecuador's, Tunisia's), and each one has a stricter block of its own
# in the same country, which the trip prompt lists first.
stricter = []
for iso in ALL:
    for r in OUT[iso]["regional"]:
        for x in r["excepts"]:
            m = W._WHERE.search(x)
            if m and W._rank(m.group(1)) > W._rank(r["call"]):
                stricter.append((iso, r, W._rank(m.group(1))))
results.append(ok(len(stricter) >= 3 and all(any(W._rank(o["call"]) >= rk for o in OUT[iso]["regional"] if o is not r) for iso, r, rk in stricter),
                  "every stricter exception (%s) has a block of that call of its own" % sorted({i for i, _, _ in stricter})))
results.append(ok(block("ec", "Esmeraldas province")["brief"] == "Esmeraldas province, parts of El Oro, Guayas and Los Ríos provinces"
                  and block("tn", "non-essential")["brief"] == "the Delegation of Remada; Mount Orbata"
                  and block("tz", "Portion of Mtwara")["brief"].endswith("(parts excepted)"),
                  "brief: a stricter exception doesn't read as parts let off (Ecuador, Tunisia); Tanzania's Mtwara City does (got %r / %r)"
                  % (block("ec", "Esmeraldas province")["brief"], block("tn", "non-essential")["brief"])))

# --- nested lists ------------------------------------------------------------------
NESTED = [
    ("mx", "Regional Advisory", "Chiapas (except Palenque, Tuxtla Gutiérrez, San Cristobal de las Casas)"),
    ("gt", "Regional advisories", "Within Guatemala City: Zone 1, Zone 3, Zones 5–7, Zone 18, Zone 21. Municipalities: in Guatemala Department (San Pedro Ayampuc"),
    ("hn", "Regional advisory", "within 20 km of the border with Guatemala (except Copán Ruinas"),
    ("hn", "Regional advisory", "within 20 km of the border with El Salvador (except CA-1 Highway"),
    ("hn", "Regional advisory", "in the departments of (Choluteca"),
    ("co", "Border areas", "Chocó (except the towns of Bahía Solano, Capurganá, Nuquí)"),
    ("ec", "Esmeraldas province", "in the province of El Oro (Machala, Huaquillas); in the province of Guayas (Durán"),
    ("mr", "Northern and eastern", "especially all of the following regions (Tiris Zemmour, Hodh El Gharbi, Hodh Ech Chargui)"),
    ("pe", "VRAEM", "in the Department of Apurímac (Province of Abancay, Province of Andahuaylas, Province of Chincheros)"),
    ("et", "Central regions", "zones in the Oromia region (North Shewa"),
    ("tn", "Avoid all travel", "following tourist towns: Aïn Draham, Chebika, Mides, Tabarka, Tamerza"),
    ("pk", "Regional advisory", "the province of Khyber Pakhtunkhwa (except Haripur and Abbottabad districts"),
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
results.append(ok(ka.startswith("the city of Karachi, except District of Karachi (formerly Karachi South) (including Clifton area; Defence Housing Authorities (DHA)")
                  and "(except the areas northwest of Muhammad Ali Jinnah Road" in ka and ka.endswith("and 3 more") and len(ka) <= W.LINE_MAX,
                  "Karachi: the city, its exceptions, the exception's own exclusion kept whole — cut, it would except more than Canada — "
                  "'(formerly Karachi South)' and '(DHA)' kept (got %r)" % ka))
pkl, pkf = block("pk", "Regional advisory")["line"], block("pk", "Regional advisory")["full"]
results.append(ok("Chitral district where you should avoid non-essential travel" in pkf
                  and ("Chitral" not in pkl or "Chitral district where you should avoid non-essential travel" in pkl),
                  "Pakistan: Chitral's own call (stricter than the country's) is never dropped — the line names Chitral with it or not at all (got %r)" % pkl))

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
          ("pe", "VRAEM"): 3, ("pk", "Regional advisory"): 3, ("bj", "Border areas with Burkina"): 2}
for (iso, h), n in WANT_N.items():
    got = block(iso, h)["line"]
    results.append(ok(got.endswith("and %d more" % n) or ("; and %d more. This advisory" % n) in got,
                      "%s %s: 'and %d more' (got %r)" % (iso.upper(), h, n, got[-60:])))
# Several lists: each keeps its own words and its own count (Guatemala's
# border crossings once read as "and 8 more" municipalities).
multi = []
for iso in ALL:
    for r in OUT[iso]["regional"]:
        B = W._analyze(r["t"], next(b for t, b in [(W._txt(m.group(1)), m.group(2)) for m in re.finditer(
            r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", feed(iso)["data"]["eng"]["advisories"], re.S)] if t[:120] == r["t"]))
        gs = [g for g in B["groups"] if g["items"]]
        if len(gs) < 2:
            continue
        parts = top_split(r["line"], ". ")
        for g, part in zip(gs, parts):
            lab = g["intro"][:1].upper() + g["intro"][1:]
            body = part[len(lab) + 2:] if part.startswith(lab) else None
            m = body is not None and re.search(r"[;,] and (\d+) more$", body)
            shown = len(top_split(body[:m.start()] if m else body, "; " if "; " in (body or "") else ", ")) if body is not None else -1
            multi.append((iso, g["intro"][:20], len(parts) == len(gs) and shown + (int(m.group(1)) if m else 0) == len(g["items"])))
results.append(ok(multi and all(c for _, _, c in multi), "several lists: each under its own words, shown + its own N = its own list (%s)" % multi))
gtl = block("gt", "Regional advisories")["line"]
results.append(ok("Border crossings on the following highways: CA-01 (La Mesilla border with Mexico" in gtl and gtl.endswith("; and 7 more")
                  and "Municipalities: in Guatemala Department" in gtl, "Guatemala: the border crossings named under their own words (got %r)" % gtl))
hnl = block("hn", "Regional advisory")["line"]
results.append(ok("El Salvador" in hnl and "in the departments of" in hnl and not re.search(r"\); and \d+ more$", hnl),
                  "Honduras: all three areas named — an exception cut to 'and N more' before a place is (got %r)" % hnl))
bjl = block("bj", "Border areas with Burkina")["line"]
results.append(ok(bjl.endswith("; and 2 more. This advisory includes the W National Park and the Pendjari National Park") and " more —" not in bjl,
                  "Benin: after a cut list, the parks in Canada's own sentence, not read as the two left out (got %r)" % bjl))
egl = block("eg", "Western desert")["line"]
results.append(ok("except Marsa Matruh via the Marsa Matruh Road only; The White and Black deserts via the Oasis Road only; and 1 more" in egl
                  and len(egl) <= W.LINE_CAP, "Egypt's Western desert: the exceptions get the room the places leave (got %r)" % egl))
results.append(ok(line("ma", "Western Sahara border") == "Avoid all travel: Western Sahara border regions: within 30 km west of the militarized zone of the Berm; "
                  "between the Berm and neighbouring countries on the eastern and southern sides",
                  "Morocco: two areas Canada lists apart, joined by '; ' — a comma read the second as describing the first (got %r)" % line("ma", "Western Sahara border")))

# --- caps, stars, qualifiers -----------------------------------------------------------
lines = [(iso, r) for iso in ALL for r in OUT[iso]["regional"]]
# Past LINE_CAP only where what must stay can't be cut: then nothing is cut
# (northern Sinai), or it is cut as far as it goes (Karachi's first
# exception carries an exclusion of its own).
def at_least(iso, r):
    B = W._analyze(r["t"], next(m.group(2) for m in re.finditer(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", feed(iso)["data"]["eng"]["advisories"], re.S)
                                if W._txt(m.group(1))[:120] == r["t"]))
    return len(r["line"]) <= len(W._compose(B, "compact", 80)) or not re.search(r"and \d+ more", r["line"])


over = [(iso, len(r["line"])) for iso, r in lines if len(r["line"]) > W.LINE_MAX or (len(r["line"]) > W.LINE_CAP and not at_least(iso, r))]
results.append(ok(not over and any(len(r["line"]) > W.LINE_CAP for _, r in lines),
                  "no line past %d characters, none past %d that could be cut shorter (%d lines; over: %s)" % (W.LINE_MAX, W.LINE_CAP, len(lines), over)))
generic = lambda r: W._GENERIC.match(r["t"].split(" - ")[0].strip())
long_b = [(iso, len(r["brief"])) for iso, r in lines if len(r["brief"]) > (W.BRIEF_NAMES if generic(r) else W.BRIEF_CAP)]
results.append(ok(not long_b, "no brief past %d characters, a generic heading's list of names past %d (got %s)" % (W.BRIEF_CAP, W.BRIEF_NAMES, long_b)))
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
         ("mz", "Cabo Delgado"): "Cabo Delgado Province, except Pemba City to which you should avoid non-essential travel",
         ("ph", "Western Mindanao"): "Western Mindanao",
         ("ec", "Border areas"): "the area within 20 km of the border with Colombia in the following provinces: Carchi*, Esmeraldas, Sucumbíos"}
for (iso, h), want in BRIEF.items():
    results.append(ok(block(iso, h)["brief"] == want, "brief %s %s: %r (got %r)" % (iso.upper(), h, want, block(iso, h)["brief"])))
mxb = block("mx", "Regional Advisory")["brief"]
results.append(ok(mxb.startswith("Chiapas*; Chihuahua*; Colima*; Guanajuato, in all areas south of and including highways 43D and 45D")
                  and "Nayarit, within 20 km of the border with the states of Sinaloa and Durango; Nuevo León*" in mxb and mxb.endswith("; and 4 more"),
                  "brief Mexico: ten states as before the server's line, starred where parts are excepted, the qualifiers kept (got %r)" % mxb))
gtb = block("gt", "Regional advisories")["brief"]
results.append(ok("Municipalities: in Guatemala Department (San Pedro Ayampuc, Villa Canales)" in gtb and "Border crossings on the following highways: CA-01" in gtb
                  and gtb.endswith("; and 5 more"), "brief Guatemala: each list under its own words, the crossings counted as crossings (got %r)" % gtb))
results.append(ok(len(W._regional("A very long named heading that keeps going on and on about places " * 3 + "- Avoid all travel",
                                  "<p>Avoid all travel to the following areas due to x:</p><ul>" + "".join(
                                      "<li>Place %d, excluding the town of T%d which is long</li>" % (i, i) for i in range(8)) + "</ul>")["brief"]) <= W.BRIEF_CAP,
                  "brief: a named heading too long for the cap is cut at a word, '(parts excepted)' kept"))
gen = [(iso, r["brief"]) for iso, r in lines if W._GENERIC.match(r["t"].split(" - ")[0].strip()) and W._GENERIC.match(r["brief"].strip())]
results.append(ok(not gen, "a generic heading ('Border areas', 'Regional advisory') never stands for its list (got %s)" % gen))

# --- the Ebola notice, text ------------------------------------------------------------
ug = block("ug", "Ebola")
results.append(ok(ug["call"].startswith("Canadian border measures related to Ebola") and ug["line"].startswith("Until November 27, 2026, Canada will have")
                  and "Useful links" not in ug["text"] and "quarantine for 21 days" in ug["text"],
                  "Uganda's Ebola notice: its heading for a call, its dated sentence for a line, its rules in the tip, no 'Useful links'"))
cdl, ssl = block("cd", "Ebola")["line"], block("ss", "Ebola")["line"]
results.append(ok(cdl == "Until November 27, 2026, Canada will have temporary border measures in place for travellers who have been in the DRC, Uganda or South Sudan within the preceding 21 days"
                  and ssl.startswith("Until November 27, 2026, Canada will have temporary border measures in place for travellers who have been in South Soudan"),
                  "the Congo's and South Sudan's notices: the sentence saying until when and for whom, not 'a health notice exists' or its 'Due to …' (got %r / %r)" % (cdl, ssl)))
mxt = block("mx", "Regional Advisory")["text"]
results.append(ok(all(s in mxt for s in ("Chiapas", "Zacatecas, excluding the city of Zacatecas", "◦ the area around Lake Chapala")) and len(mxt) <= W.TEXT_CAP,
                  "text: Mexico's whole block, sub-items marked, within %d characters (%d)" % (W.TEXT_CAP, len(mxt))))
results.append(ok("Natural disasters and climate" not in block("mx", "West-central")["text"],
                  "text: a paragraph that only links to another section of Canada's page is left out"))
long_html = "<h3>Somewhere - Avoid all travel</h3><p>Avoid all travel to the following areas due to x:</p><ul>" + "".join(
    "<li>Place %d is a long name that goes on for a while. And then a second sentence about it.</li>" % i for i in range(60)) + "</ul>"
lt = W.regional_blocks(long_html, "Nowhere")[0]["text"]
results.append(ok(len(lt) <= W.TEXT_CAP and lt.endswith("…"), "text: cut at a line or sentence near %d characters and marked (got %d)" % (W.TEXT_CAP, len(lt))))

# --- latent shapes the feed doesn't have today ------------------------------------------------
# An exclusion inside an exception is never shortened (its aside put back
# under the block's call would read as excepted); a paragraph after an
# unclosed list or bare <li>s is a sentence, not one more place.
f5 = W.regional_blocks("<h3>Foo - Avoid all travel</h3><p>Avoid all travel to Foo, with the exception of the following areas where you should exercise a high degree of caution:</p><ul>"
                       "<li>District of Bar, excluding the town of Baz (and the coastal road leading there)</li>"
                       + "".join("<li>Some long excepted place number %d with a long name here</li>" % i for i in range(6)) + "</ul>", "Nowhere", 1)[0]["line"]
results.append(ok("District of Bar (except the town of Baz (and the coastal road leading there))" in f5,
                  "an exclusion from an exception keeps its words whole when the line is shortened (got %r)" % f5[:120]))
f6 = [W.regional_blocks("<h3>Foo - Avoid all travel</h3><p>Avoid all travel to the following areas due to x:</p>" + h
                        + "<li>A</li><li>B</li><p>This advisory excludes C where you should exercise a high degree of caution.</p>", "Nowhere", 1)[0] for h in ("", "<ul>")]
results.append(ok(all(r["excepts"] == ["C where you should exercise a high degree of caution"] and [i["t"] for i in r["items"]] == ["A", "B"] for r in f6),
                  "an unclosed list or bare <li>s end at the next paragraph: its 'This advisory excludes' is an exception (got %s)" % [r["line"] for r in f6]))

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
    and {"call", "line", "full", "brief", "text", "items", "excepts", "includes"} <= set(r) for _, r in lines)
results.append(ok(keys_ok, "API: iso, source, link, watchouts and regional[].t/.lead/.regions as before, call/line/full/brief/text/items/excepts/includes added"))
uncut = [(iso, r["t"][:30]) for iso, r in lines if r["call"].lower().startswith("avoid") and (re.search(r"and \d+ more", r["full"])
         or (len(r["line"]) <= W.LINE_CAP and not re.search(r"and \d+ more", r["line"]) and r["full"] != r["line"]))]
results.append(ok(not uncut, "full: the line uncut for the guide's AI prompt, the line itself wherever that isn't cut (wrong: %s)" % uncut))
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
