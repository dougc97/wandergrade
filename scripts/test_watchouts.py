"""Canada's regional advisories as fxtracker/watchouts.py reads them, offline,
from the trimmed feed copies in scripts/fixtures/gac (2026-10-14, checked
against travel.gc.ca that day; see its README).

  blocks     every regional block kept (Israel's Lebanon and Gaza lines,
             Thailand's and Cambodia's shared border, Indonesian Papua), the
             country-wide one left out however its heading spells the name
             (counted by hand per fixture); notices with no call and no
             area (the Ebola border measures) left out, and only those
  line       the area as Canada's first sentence names it, the listed places
             with their sub-lists folded in, the exceptions named (the
             second-sentence ones Kenya, Uganda, Mozambique, Azerbaijan,
             Tanzania and India carry), what a block includes (Benin's
             parks, never cut); a qualifier is never an exception; several
             exceptions under words that say they are exceptions (Egypt),
             each of Canada's sentences its own (Tanzania); every place
             named before any detail (Honduras, Pakistan, Mexico, Colombia,
             Peru's VRAEM, Karachi), at its shortest honest form ("parts of
             Cortés", "parts of Amazonas", "(parts excepted)"), past the cap
             only for that; more room never names fewer places; every
             excepted place flagged or none (Colombia); "and N more"
             counting places, not headings (Guatemala); "the city of" kept
             in an exception; a stricter exception's call never dropped
             (Pakistan's Chitral), nor a bare exception after one; a
             repeated "the province of" said once among places only; no
             line past the ceiling; no stars
  full       the block uncut, in Canada's words, for the guide's AI prompt
  brief      the trip prompt's form: short lines whole, a named heading (or
             Canada's own fuller words for it: "and surroundings") for a
             long one, up to ten names for a generic one's list or every
             one where they all fit at their shortest; a stricter exception
             is never "parts excepted"; a place whose list names parts of
             it never bare
  latent     shapes the feed lacks today: an exclusion inside an exception,
             a paragraph after an unclosed list, a call-less block that
             names a call further on, a heading over places two levels down,
             a call spelled with a non-breaking hyphen or space or "non
             essential", a stricter exception or an include on the
             over-ceiling paths
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
BLOCKS = {"az": 2, "bj": 3, "br": 2, "bs": 0, "cd": 0, "ci": 2, "co": 3, "dz": 2, "ec": 4, "eg": 3, "et": 4, "ge": 2,
          "gt": 1, "hn": 1, "id": 1, "il": 6, "in": 3, "jo": 2, "jp": 0, "ke": 4, "kh": 1, "la": 2, "ma": 3, "mr": 1,
          "mx": 2, "mz": 4, "ng": 2, "pa": 4, "pe": 4, "ph": 2, "pk": 2, "ss": 0, "tg": 2, "th": 2, "tn": 2, "tz": 2,
          "ug": 1, "xk": 1}
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
results.append(ok(pal == "Avoid all travel: Palestine. This advisory excludes the following roads, where you should avoid non-essential travel: "
                         "Highway 1; Route 90, from the intersection with Highway 1 to King Hussein Bridge (Allenby), near Jericho",
                  "Palestine: the area, then the two roads in Canada's own sentence of exceptions with their own call (got %r)" % pal))
results.append(ok(line("th", "Thailand-Cambodia") == "Avoid all travel: the area within 50 kilometres of the Thailand-Cambodia border",
                  "Thailand's Cambodia border line is kept (its heading starts with the country's name; a prefix test hid it) (got %r)" % line("th", "Thailand-Cambodia")))
results.append(ok(line("th", "Southern provinces") == "Avoid all travel: Narathiwat; Pattani; Yala; southern Songkhla province (Hat Yai city; east of Highways 408 and 4113, including Sakom)",
                  "Thailand's south: southern Songkhla's sibling list (Hat Yai) folded under it (got %r)" % line("th", "Southern provinces")))
results.append(ok(block("kh", "Cambodia-Thailand")["line"] and block("id", "Indonesian Papua")["line"].startswith("all the provinces of Indonesian Papua, except"),
                  "Cambodia's Thai border and Indonesian Papua are kept too, Papua with its Raja Ampat and Sorong exception"))
results.append(ok(not OUT["bs"]["regional"] and not OUT["ci"]["regional"][0]["t"].startswith("Côte"),
                  "the country-wide block is left out where its heading spells the name otherwise (The Bahamas on 'Bahamas', Côte d’Ivoire)"))
# Canada's Ebola border measures (no call, no area: its re-entry rules for
# Canadians) read as a 📍 place line. Every block the parser leaves out of
# the fixtures, besides the country-wide one, must be exactly those three.
H3 = re.compile(r"<h3[^>]*>(.*?)</h3>(.*?)(?=<h3|$)", re.S)
gone = []
for iso in ALL:
    eng = feed(iso)["data"]["eng"]
    kept = [r["t"] for r in OUT[iso]["regional"]]
    for m in H3.finditer(eng.get("advisories") or ""):
        t = re.sub(r"\s+", " ", W._txt(m.group(1)))
        if t[:120] not in kept and not W._country_wide(t.split(" - ")[0], (eng.get("name") or "").strip()):
            B = W._analyze(t, m.group(2))
            gone.append((iso, t[:60], B["notice"] and not B["L"] and W._rank(B["call"]) < 0))
results.append(ok(sorted(g[:2] for g in gone) == [
    ("cd", "Canadian border measures related to Ebola for travellers fro"), ("ss", "Canadian border measures related to Ebola for travellers fro"),
    ("ug", "Canadian border measures related to Ebola for travellers fro")] and all(g[2] for g in gone),
                  "only the Ebola border-measure notices (no call, no area) are left out — the Congo's, South Sudan's, Uganda's (got %s)" % gone))
results.append(ok([r["t"] for r in OUT["ug"]["regional"]] == ["Border with South Sudan - Avoid all travel"],
                  "Uganda keeps its South Sudan border block; only its notice goes"))
kept_later = W.regional_blocks("<h3>Northern zone</h3><p>The situation is volatile.</p><p>Avoid all travel to the northern zone.</p>"
                               "<h3>Health measures for travellers</h3><p>Until 2027, travellers must quarantine.</p>", "Nowhere")
results.append(ok([r["t"] for r in kept_later] == ["Northern zone"],
                  "a block with no call in its heading or first sentence is kept when its text names one further on; one naming none goes (got %s)"
                  % [r["t"] for r in kept_later]))

# --- exceptions and inclusions from later sentences --------------------------------
SECOND = [
    ("ke", "Border with Somalia", "Mandera, Wajir, Garissa and Lamu counties bordering Somalia, except Lamu Island and Manda Island"),
    ("ug", "Border with South Sudan", "areas within 50 km of the border with South Sudan, except visits to national parks when accompanied by a reputable guide"),
    ("mz", "Cabo Delgado", "Cabo Delgado Province, except Pemba City to which you should avoid non-essential travel"),
    ("az", "Border with Armenia", "except the border between Armenia and the Azerbaijani Autonomous Republic of Nakhchivan, where you should exercise a high degree of caution"),
    ("bj", "Border areas with Burkina Faso", "This advisory includes the W National Park and the Pendjari National Park"),
    ("tz", "Portion of Mtwara", "This advisory excludes the areas within 10 km from the border with Mozambique, where you should avoid all travel. "
                             "This advisory also excludes Mtwara City"),
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
tzf = block("tz", "Portion of Mtwara")["full"]
results.append(ok(tzf.endswith(", where you should avoid all travel. This advisory also excludes Mtwara City where you should exercise a high degree of caution"),
                  "Tanzania's full: Canada's two sentences, each with its own call — the city never in the avoid-all band's list (got %r)" % tzf))
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
    ("mx", "Regional Advisory", "Chiapas (except the city and ruins of Palenque (and highway 186 leading there); the city of Tuxtla Gutiérrez (and its "
                                "airport and the main road leading there); the city of San Cristobal de las Casas (and toll highway 190D between this "
                                "city and Tuxtla Gutiérrez))"),
    ("gt", "Regional advisories", "Within Guatemala City: Zone 1, Zone 3, Zones 5–7, Zone 18, Zone 21. Municipalities: in Guatemala Department (San Pedro Ayampuc"),
    ("hn", "Regional advisory", "within 20 km of the border with Guatemala (except Copán Ruinas"),
    ("hn", "Regional advisory", "within 20 km of the border with El Salvador (except CA-1 Highway"),
    ("hn", "Regional advisory", "in the departments of: Choluteca: the city of Choluteca; Colón (except the city of Trujillo); Cortés (the eastern"),
    ("co", "Border areas", "Chocó (except the towns of Bahía Solano, Capurganá, Nuquí)"),
    ("ec", "Esmeraldas province", "in the province of El Oro (Machala, Huaquillas); in the province of Guayas (Durán"),
    ("mr", "Northern and eastern", "especially all of the following regions (Tiris Zemmour, Hodh El Gharbi, Hodh Ech Chargui)"),
    ("pe", "VRAEM", "in the Department of Apurímac (Province of Abancay, Province of Andahuaylas, Province of Chincheros)"),
    ("et", "Central regions", "zones in the Oromia region (North Shewa"),
    ("tn", "Avoid all travel", "following tourist towns, where you should exercise a high degree of caution: Aïn Draham, Chebika, Mides, Tabarka, Tamerza"),
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
# The sub-lists folded in, as the uncut form (full) says them, in Canada's
# words — asides and calls kept: a line short of room says a place at its
# shortest (Chocó "(parts excepted)").
for iso, h, want in NESTED:
    got = block(iso, h)["full"]
    results.append(ok(want in got, "%s %s: %r (got %r)" % (iso.upper(), h, want, got)))
mx = block("mx", "Regional Advisory")["items"]
co = block("co", "Border areas")["items"]
results.append(ok(len(mx) == 14 and len(mx[0].get("items", [])) == 3 and len(mx[5].get("items", [])) == 2
                  and len([x for x in co if x["t"].startswith("Chocó")][0].get("items", [])) == 3,
                  "items: Mexico's 14 states, Chiapas's 3 exclusions in its <li>, Jalisco's 2 and Chocó's 3 in a sibling <ul> after theirs"))
ka, kaf = block("pk", "Karachi")["line"], block("pk", "Karachi")["full"]
results.append(ok(ka == "the city of Karachi, except the following areas: parts of District of Karachi (formerly Karachi South); "
                        "DHA Phase 7 Extension in the District of Korangi; Lalazar, Naval Officers Residential Estate 1 and Port Tower Complex "
                        "in the District of Keamari; and 1 more",
                  "Karachi: three of its four exceptions named, not the first one's own list — that one, which carries an exclusion of its own, "
                  "as 'parts of' it (said whole without the exclusion it would except more than Canada); Canada's 'the following areas:' "
                  "says where the exceptions end (got %r)" % ka))
results.append(ok("District of Karachi (formerly Karachi South) (including Clifton area; Defence Housing Authorities (DHA) Phases 1, 2, 4, 5, 6, 7 and 8 "
                  "(except the areas northwest of Muhammad Ali Jinnah Road" in kaf and kaf.endswith("Jinnah International Airport and Shahrah-e-Faisal Road "
                  "between the airport and the city, in the District of Gulshan"),
                  "Karachi's full: every exception, the first with its exclusion whole, '(formerly Karachi South)' and '(DHA)' kept (got %r)" % kaf))
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


def analyzed(iso, r):
    """The parser's reading of one served block (its _analyze)."""
    return W._analyze(r["t"], next(m.group(2) for m in H3.finditer(feed(iso)["data"]["eng"]["advisories"])
                                    if re.sub(r"\s+", " ", W._txt(m.group(1)))[:120] == r["t"]))


def places(items):
    """How many places a list is to "and N more" (W._count)."""
    return sum(W._count(it) for it in items)


# "and N more" counts the places it hides, a heading over places counting
# its places: Guatemala's "Municipalities: … (San Pedro Ayampuc, and 1
# more); and 1 more" hid Escuintla Department's three as one, its border
# crossings' "and 7 more" nine crossings.
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
        its = [it for g in analyzed(iso, r)["groups"] for it in g["items"]]
        counts.append((iso, r["t"][:30], places(its[:shown]), int(m.group(1)), places(its)))
bad = [c for c in counts if c[2] + c[3] != c[4]]
results.append(ok(counts and not bad, "'and N more': places shown + N = Canada's places, on every cut single-list line (%d lines; wrong: %s)" % (len(counts), bad)))
# Lines that hid most of their places behind "and N more" while their room
# went to the first ones' detail (Mexico's 9 of 14 states, Colombia's 14 of
# 16, Peru's VRAEM three of five departments) name every one now.
WANT_ALL = {("mx", "Regional Advisory"): 14, ("co", "Regional advisory"): 16, ("pe", "VRAEM"): 5}
for (iso, h), n in WANT_ALL.items():
    got = block(iso, h)["line"]
    body = got.split(": ", 1)[1] if iso == "pe" else got
    results.append(ok(not re.search(r"and \d+ more$", got) and len(top_split(body, "; ")) == n == len(block(iso, h)["items"])
                      and len(got) <= W.LINE_MAX,
                      "%s %s: all %d places named (got %d: %r)" % (iso.upper(), h, n, len(got), got)))
results.append(ok(places([it for g in analyzed("co", block("co", "Regional advisory"))["groups"] for it in g["items"]]) == 18,
                  "Colombia: its 16 items are 18 places to 'and N more' — 'the following towns in Chocó' is three"))
# Several lists: each keeps its own words and its own count (Guatemala's
# border crossings once read as "and 8 more" municipalities).
multi = []
for iso in ALL:
    for r in OUT[iso]["regional"]:
        gs = [g for g in analyzed(iso, r)["groups"] if g["items"]]
        if len(gs) < 2:
            continue
        parts = top_split(r["line"], ". ")
        for g, part in zip(gs, parts):
            lab = g["intro"][:1].upper() + g["intro"][1:]
            body = part[len(lab) + 2:] if part.startswith(lab) else None
            m = body is not None and re.search(r"[;,] and (\d+) more$", body)
            shown = len(top_split(body[:m.start()] if m else body, "; " if "; " in (body or "") else ", ")) if body is not None else -1
            multi.append((iso, g["intro"][:20], len(parts) == len(gs) and shown >= 1
                          and places(g["items"][:shown]) + (int(m.group(1)) if m else 0) == places(g["items"])))
results.append(ok(multi and all(c for _, _, c in multi), "several lists: each under its own words, places shown + its own N = its own places (%s)" % multi))
gtl = block("gt", "Regional advisories")["line"]
results.append(ok("Municipalities: parts of Guatemala Department; parts of Escuintla Department. " in gtl
                  and "Border crossings on the following highways: CA-01 (La Mesilla border with Mexico, and 1 more); and 9 more" in gtl
                  and gtl.endswith("; and 9 more"),
                  "Guatemala: both departments' municipalities named as 'parts of' them (Escuintla's three hid behind 'and 3 more'), "
                  "the crossings left out nine, not the seven headings over them (got %r)" % gtl))
gtb = block("gt", "Regional advisories")["brief"]
results.append(ok(gtb.endswith("; CA-10: Agua Caliente border with Honduras; and 5 more"),
                  "brief Guatemala: its 'and N more' counts crossings too (got %r)" % gtb[-80:]))

# --- every place before any detail ----------------------------------------------------
# A line short of room names every place of its lists at its shortest honest
# form first, past LINE_CAP up to LINE_MAX if that is what it takes, and only
# then spends what is left on detail; places are hidden behind "and N more"
# only where they can't all be said by LINE_MAX.
hnl = block("hn", "Regional advisory")["line"]
results.append(ok(hnl == "within 20 km of the border with Guatemala (parts excepted), El Salvador (parts excepted); in the departments of: "
                         "Choluteca: the city of Choluteca; Colón (parts excepted); parts of Cortés; Francisco Morazán: the city of Comayagüela "
                         "(parts excepted); Gracias a Dios; Olancho; Yoro",
                  "Honduras: both bands and all seven departments named (six hid behind 'and 6 more'), each at its shortest — Cortés as "
                  "'parts of', the bands' exceptions as '(parts excepted)'; the departments after a colon, not in brackets after 'of' (got %r)" % hnl))
pkl = block("pk", "Regional advisory")["line"]
PK_PLACES = ["Pakistan-administered Kashmir", "the province of Balochistan", "Khyber Pakhtunkhwa",
             "the area within 50 km of the border with Afghanistan", "the areas within 10 km of the borders with China, India and Iran",
             "the areas within 10 km of the Line of Control with India", "the section of the Karakoram Highway from Mansehra to Chilas"]
results.append(ok(pkl == "; ".join(PK_PLACES) and W.LINE_CAP < len(pkl) <= W.LINE_MAX,
                  "Pakistan: all seven places named — the 10 km strips and the Karakoram Highway from Mansehra to Chilas hid behind "
                  "'and 3 more' — 'the province of' said once, their exceptions cut to fit (stricter, never looser; full has them) "
                  "(got %d: %r)" % (len(pkl), pkl)))
bjl, bjf = block("bj", "Border areas with Burkina")["line"], block("bj", "Border areas with Burkina")["full"]
results.append(ok(bjl == "along the border with Togo in the Atacora Department west of the Boukoumbé-Tanguiéta axis; within 50 km of the border with "
                         "Burkina Faso; and 2 more. This advisory includes the W National Park and the Pendjari National Park"
                  and bjf.endswith(" — including the W National Park and the Pendjari National Park"),
                  "Benin: the parks stay on the line (what a block includes is a place to avoid, never cut): its four bands and the parks "
                  "are 347 characters, past the ceiling, so two bands are counted, not the parks dropped (got %r)" % bjl))
# The breadth form never says a place wider or narrower than Canada: a place
# with exceptions is "(parts excepted)" or bare (its exceptions cut), one
# whose list names parts of it "parts of", an exception with an exclusion of
# its own "parts of" too.
least = {"Colón, excluding the city of Trujillo": "Colón (parts excepted)", "Cortés:": "parts of Cortés",
         "District of San Miguelito, especially the following areas:": "District of San Miguelito"}
hn_items = {it["t"]: it for it in W._walk([it for g in analyzed("hn", block("hn", "Regional advisory"))["groups"] for it in g["items"]])}
pa_items = {it["t"]: it for it in W._walk([it for g in analyzed("pa", block("pa", "High-crime"))["groups"] for it in g["items"]])}
cx = {"rank": 2, "floor": 1}
got_least = {t: W._least(dict(hn_items, **pa_items)[t], "compact", cx, 0, t == "Cortés:" or t.startswith("Colón")) for t in least}
ka_items = analyzed("pk", block("pk", "Karachi"))["extras"][0]["items"]
got_ka = W._least(ka_items[0], "compact", cx, 1)
results.append(ok(got_least == least and got_ka == "parts of District of Karachi (formerly Karachi South)",
                  "the shortest honest forms: %s; Karachi's first exception %r" % (got_least, got_ka)))
co1 = block("co", "Border areas")["line"]
coB = W._derepeat(analyzed("co", block("co", "Border areas")))
co_marked = W._compose(coB, "compact", 80, False)
results.append(ok(co1 == "Arauca; Caquetá; Cauca; parts of Cesar; Chocó; within 50 km of the border with Venezuela; within 100 km of the border "
                         "with Panama; within 50 km of the border with Ecuador; Norte de Santander; the Port of Tumaco and the city of Buenaventura"
                  and len(co_marked) > W.LINE_MAX and co_marked.count("(parts excepted)") == 6,
                  "Colombia: its ten areas named; with all six '(parts excepted)' the line is %d, past the ceiling, so none is flagged — "
                  "never three flagged and three bare, which read as if Canada excepted nothing from Cúcuta or Ipiales (got %r)" % (len(co_marked), co1)))
# A list flags every place Canada lets parts off ("(parts excepted)" or its
# exceptions named) or none: some flagged and others bare reads as if
# Canada excepted nothing from those.
mixed = []
for iso, r in [(iso, r) for iso in ALL for r in OUT[iso]["regional"]]:
    B = W._derepeat(analyzed(iso, r))
    shown = {"flag": [], "bare": []}
    for it in W._marked(B):
        place = W._heading(W._split_exc(it["t"])[0]).rstrip(" ,")
        if W._qualified(W._split_exc(it["t"])[0]):
            continue                        # "parts of Jalisco": no flag needed
        for m in re.finditer(re.escape(place), r["line"]):
            rest = r["line"][m.end():]
            if rest.startswith(" ("):
                shown["flag"].append(place)       # "(parts excepted)" or its exceptions named
            elif re.match(r"(?:; |, |\. |$)", rest):
                shown["bare"].append(place)
    if shown["flag"] and shown["bare"]:
        mixed.append((iso, r["t"][:30], shown))
results.append(ok(not mixed, "no line flags some excepted places and says others bare (got %s)" % mixed))
egl = block("eg", "Western desert")["line"]
results.append(ok(egl == "within 50 kilometres of the border with Libya; the Western Desert, west of the Giza-Luxor-Aswan-Abu Simbel road, including the "
                         "oasis of Dakhla. This advisory excludes Marsa Matruh via the Marsa Matruh Road only; and 3 more",
                  "Egypt's Western desert: both places, then Canada's sentence of exceptions, 'The oases of:' counting its two (got %r)" % egl))
results.append(ok(line("ma", "Western Sahara border") == "Avoid all travel: Western Sahara border regions: within 30 km west of the militarized zone of the Berm; "
                  "between the Berm and neighbouring countries on the eastern and southern sides",
                  "Morocco: two areas Canada lists apart, joined by '; ' — a comma read the second as describing the first (got %r)" % line("ma", "Western Sahara border")))

# --- several exceptions read as exceptions -------------------------------------------------
# "— except A; B; and 1 more" after places joined by "; " read B as one more
# place to avoid (Egypt's White and Black deserts). Several exceptions are
# said in Canada's own sentence ("This advisory excludes …") or after its
# "the following areas:"; one may stay "except A".
egs = block("eg", "Northern part of the Governorate")["line"]
results.append(ok(egs == "the northern part of the Governorate of South Sinai, north of St. Catherine – Nuweiba – El Tor Road. This advisory excludes "
                         "the Dahab – Nuweiba – Taba road; the towns of Nuweiba and Taba; and 2 more",
                  "Egypt's South Sinai: its four exceptions in Canada's own sentence, 'the towns of' kept (got %r)" % egs))
several = []
for iso, r in [(iso, r) for iso in ALL for r in OUT[iso]["regional"]]:
    B = analyzed(iso, r)
    excs = [e for e in B["extras"] if e["k"] == "except"]
    if len(excs) > 1 or any(len(e["items"]) > 1 for e in excs):
        for f in ("line", "full"):
            x = r[f]
            several.append((iso, r["t"][:30], f, "This advisory excludes " in x or bool(re.search(r"except the following \w+[^:;]*:", x))
                            or not re.search(r"\bexcept\b", x)))
results.append(ok(len(several) >= 8 and all(c for *_, c in several),
                  "every block with several exceptions says them under words that end the places (%s)" % [c for c in several if not c[-1]]))

# --- caps, stars, qualifiers -----------------------------------------------------------
lines = [(iso, r) for iso in ALL for r in OUT[iso]["regional"]]


def top_hidden(line_):
    """Whether a line hides places of its lists' own level: a list (or an
    'of' heading's, after its colon) ending in 'and N more' outside brackets."""
    return any(re.fullmatch(r"and \d+ more", top_split(part, sep)[-1]) for part in top_split(line_, ". ") for sep in ("; ", ", "))


# Past LINE_CAP only to name every place (Honduras, Pakistan, Benin), or
# where nothing can be cut (northern Sinai, whole): never with a place of
# its lists' level hidden, never past LINE_MAX.
over = [(iso, len(r["line"])) for iso, r in lines
        if len(r["line"]) > W.LINE_MAX or (len(r["line"]) > W.LINE_CAP and top_hidden(r["line"]) and r["line"] != r["full"])]
results.append(ok(not over and any(len(r["line"]) > W.LINE_CAP for _, r in lines) and W.LINE_MAX <= 340,
                  "no line past %d characters, none past %d with a place hidden (%d lines; over: %s; past %d: %s)"
                  % (W.LINE_MAX, W.LINE_CAP, len(lines), over, W.LINE_CAP, sorted((iso, len(r["line"])) for iso, r in lines if len(r["line"]) > W.LINE_CAP))))
results.append(ok(top_hidden("A; B; and 2 more") and top_hidden("X: in the departments of: A; and 6 more") and not top_hidden("A; B (C, and 2 more); D")
                  and top_hidden("Zones: A, B. Municipalities: C (D, and 1 more); and 3 more. Crossings: E"),
                  "top_hidden: reads a list's own 'and N more', not one in brackets"))
generic = lambda r: W._GENERIC.match(r["t"].split(" - ")[0].strip())
long_b = [(iso, len(r["brief"])) for iso, r in lines if len(r["brief"]) > (W.BRIEF_NAMES if generic(r) else W.BRIEF_CAP)]
results.append(ok(not long_b, "no brief past %d characters, a generic heading's list of names past %d (got %s)" % (W.BRIEF_CAP, W.BRIEF_NAMES, long_b)))
results.append(ok(not [r["line"] for _, r in lines if "*" in r["line"]], "no line marks exceptions with a bare star: they are named"))
results.append(ok(all(r["line"] and r["call"] for _, r in lines), "every block has a call and a line"))
co2 = block("co", "Regional advisory")
results.append(ok(co2["line"].startswith("parts of Amazonas; parts of Antioquia; parts of Córdoba;")
                  and co2["full"].startswith("Amazonas, within 20 km of the border with Peru, west of Puerto Narino;")
                  and not any("Peru" in x for x in co2["excepts"]),
                  "Colombia: 'Amazonas, within 20 km of the border with Peru' is a strip of Amazonas — 'parts of Amazonas' at its shortest, "
                  "never Amazonas with parts excepted (got %r)" % co2["line"][:80]))
mxl = block("mx", "Regional Advisory")["line"]
results.append(ok("Guanajuato, in all areas south of and including highways 43D and 45D" in mxl and "Guanajuato (except" not in mxl
                  and not any("Michoacán state" in x or "Sinaloa and Durango" in x for x in block("mx", "Regional Advisory")["excepts"]),
                  "Mexico: Guanajuato's highways, Jalisco's 50 km and Nayarit's 20 km are where the advice applies, never exceptions"))
# An exception is never said wider than Canada wrote it: "the city of
# Trujillo" excepted is not "Trujillo" (Honduras's "Colón (except
# Trujillo)" read as the municipality); "the towns of Nuweiba and Taba".
CITY = re.compile(r"^(?:the )?(?:city and ruins|cities|city|towns?|municipalit(?:y|ies)) of\s+(.+)$", re.I)
named_city, widened = [], []
for iso, r in lines:
    B = analyzed(iso, r)
    # A place Canada names that is also its excepted city's name ("Zacatecas,
    # excluding the city of Zacatecas"): bare in a list, it is the state.
    own = {W._split_exc(it["t"])[0].strip(" ,:").lower() for it in W._walk([it for g in B["groups"] for it in g["items"]])}
    xs = [_x for it in W._walk([it for g in B["groups"] for it in g["items"]]) for _x in
          ([W._split_exc(it["t"])[1] or ""] + ([k["t"] for k in it["items"]] if W._split_exc(it["t"])[1] is not None else []))]
    xs += [k["t"] for e in B["extras"] if e["k"] == "except" for k in e["items"]] + [e["t"] for e in B["extras"] if e["k"] == "except"]
    for x in xs:
        m = CITY.match(x)
        if not m:
            continue
        named_city.append(x)
        y = re.split(r"\s*\(", m.group(1))[0]
        if not W._shorten(x, B["cx"]).lower().startswith(x[:m.start(1)].lower()):
            widened.append((iso, x, W._shorten(x, B["cx"])))
        for f in ("line", "full"):
            lead = r"\(except " if y.lower() in own else r"(?:\(except |; |, )"
            if re.search(lead + re.escape(y) + r"\b", r[f]) and not re.search(r"\bof " + re.escape(y), r[f]):
                widened.append((iso, f, y))
results.append(ok(len(named_city) >= 15 and not widened and "Colón (except the city of Trujillo)" in block("hn", "Regional advisory")["full"]
                  and "Caquetá (except the city of Florencia)" in block("co", "Border areas")["full"],
                  "'the city of' / 'the towns of' stay in every exception (%d of them; widened: %s)" % (len(named_city), widened)))
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
                  and "Nayarit, within 20 km of the border with the states of Sinaloa and Durango; Nuevo León*" in mxb
                  and mxb.endswith("; Sinaloa*; Sonora*; Tamaulipas*; Zacatecas*") and len(mxb) <= W.BRIEF_NAMES,
                  "brief Mexico: all 14 states (Sinaloa, Sonora, Tamaulipas and Zacatecas hid behind 'and 4 more' with room for them), "
                  "starred where parts are excepted, the qualifiers kept (got %r)" % mxb))
cob = block("co", "Regional advisory")["brief"]
results.append(ok(cob.startswith("Amazonas, within 20 km of the border with Peru") and cob.endswith("; Vaupés; Vichada") and len(cob) <= W.BRIEF_NAMES,
                  "brief Colombia: all 16 (Nariño, Putumayo, Valle del Cauca … hid behind 'and 8 more'), each in Canada's words while they fit (got %r)" % cob[-90:]))
for h in ("Upper Huallaga", "VRAEM"):
    results.append(ok(block("pe", h)["brief"].endswith(" and surroundings"),
                      "brief Peru %s: Canada's own 'and surroundings', not the bare heading (got %r)" % (h, block("pe", h)["brief"])))
gtb = block("gt", "Regional advisories")["brief"]
results.append(ok("Municipalities: in Guatemala Department (San Pedro Ayampuc, Villa Canales)" in gtb and "Border crossings on the following highways: CA-01" in gtb
                  and gtb.endswith("; and 5 more"), "brief Guatemala: each list under its own words, the crossings counted as crossings (got %r)" % gtb))
results.append(ok(len(W._regional("A very long named heading that keeps going on and on about places " * 3 + "- Avoid all travel",
                                  "<p>Avoid all travel to the following areas due to x:</p><ul>" + "".join(
                                      "<li>Place %d, excluding the town of T%d which is long</li>" % (i, i) for i in range(8)) + "</ul>")["brief"]) <= W.BRIEF_CAP,
                  "brief: a named heading too long for the cap is cut at a word, '(parts excepted)' kept"))
gen = [(iso, r["brief"]) for iso, r in lines if W._GENERIC.match(r["t"].split(" - ")[0].strip()) and W._GENERIC.match(r["brief"].strip())]
results.append(ok(not gen, "a generic heading ('Border areas', 'Regional advisory') never stands for its list (got %s)" % gen))
hnb = block("hn", "Regional advisory")["brief"]
results.append(ok(hnb == "within 20 km of the border with Guatemala*; within 20 km of the border with El Salvador*; in the departments of: Choluteca: "
                         "the city of Choluteca; Colón*; parts of Cortés; Francisco Morazán: the city of Comayagüela*; Gracias a Dios; Olancho; Yoro",
                  "brief Honduras: 'parts of Cortés', never 'Cortés' bare, where Canada lists parts of it (got %r)" % hnb))
# No line, full or brief says a place bare where its own list names only
# parts of it (a place under an "of" heading over a list of its parts).
bare = []
for iso, r in lines:
    def walk(items, under_of=False):
        for it in items:
            k = W._kind(it, under_of)
            if k == "part":
                yield W._place(it["t"])
            yield from walk(it["items"], k == "of")
    for name in walk([it for g in analyzed(iso, r)["groups"] for it in g["items"]]):
        for f in ("line", "full", "brief"):
            for m in re.finditer(re.escape(name), r[f]):
                if not (r[f][:m.start()].endswith("parts of ") or r[f][m.end():].startswith(" (")):
                    bare.append((iso, f, name))
results.append(ok(not bare and any(W._kind(it, True) == "part" for it in W._walk(analyzed("hn", block("hn", "Regional advisory"))["groups"][0]["items"])),
                  "no line, full or brief says a place bare whose own list names parts of it (got %s)" % bare))
two = W.regional_blocks("<h3>Regional advisory - Avoid all travel</h3><p>Avoid all travel to the following areas due to x:</p><ul>"
                        "<li>in the regions of:<ul><li>Alpha:<ul><li>the city of A1</li><li>the town of A2</li></ul></li><li>Beta</li>"
                        "<li>Gamma:<ul><li>G1</li><li>G2</li></ul></li><li>in Delta:<ul><li>D1</li><li>D2</li><li>D3</li></ul></li></ul></li>"
                        + "".join("<li>a long place number %d with words enough to need a brief of names</li>" % i for i in range(3)) + "</ul>", "Nowhere", 1)[0]
results.append(ok(two["brief"].startswith("in the regions of (parts of Alpha; Beta; parts of Gamma; in Delta (D1, and 2 more)); a long place")
                  and two["line"].startswith("in the regions of (parts of Alpha; Beta; Gamma (G1, G2); parts of Delta); a long place"),
                  "brief and line: a place two levels down whose list names its parts is 'parts of' it, a heading over places its first and "
                  "'and N more' or 'parts of' its place ('in Delta'), never bare (got %r / %r)" % (two["brief"][:120], two["line"][:120])))

# --- room goes to places before detail, never the other way --------------------------------
# More room never names fewer places: the breadth pass once gave a place its
# exceptions whole while a heading's places stayed hidden (Mexico named 5 of
# its 14 states, Colombia 2 of 16).
syn5 = W._analyze("Regional advisory - Avoid all travel", "<p>Avoid all travel to the following areas due to crime:</p><ul>"
                  "<li>Alphaland province, excluding the city of Alpha Town and its airport road</li><li>in Beta Department:<ul>"
                  + "".join("<li>Beta municipality number %d</li>" % i for i in range(6)) + "</ul></li>"
                  "<li>a long trailing place that pads the line out to the cap of the line here and there and more</li></ul>", 1)
named = []
for room in range(150, 300, 4):
    x = W._compose(syn5, "compact", room)
    top = sum(int(n) for n in re.findall(r"and (\d+) more", " ".join(p for p in top_split(x, "; ") if not p.startswith("in Beta"))))
    named.append((room, top, len(re.findall(r"Beta municipality number \d", x)), x))
# Top-level places hidden never rise with room, and at the same number the
# municipalities named never fall; no place has its exceptions while one of
# the municipalities could have been named instead.
mono = all(b[1] < a[1] or (b[1] == a[1] and b[2] >= a[2]) for a, b in zip(named, named[1:]))
detail_last = all("(except the city" not in x or n == 6 for _, _, n, x in named)
results.append(ok(mono and detail_last,
                  "breadth first: more room never hides more places or names fewer, no place's exceptions before every place is named "
                  "(room, top-level hidden, municipalities named: %s)" % [(r, t, n) for r, t, n, _ in named]))
# A stricter exception never goes and what a block includes never goes, on
# any of the over-ceiling paths: a place whose exception is stricter is
# never said bare, a stricter "This advisory excludes …" sentence and a
# "This advisory includes …" one stay on the line.
far = ["the northern province of Alphaland along the whole of the eastern frontier road",
       "the southern province of Betaland along the whole of the western frontier road",
       "the central province of Gammaland between the two great rivers of the plateau",
       "the coastal province of Deltaland including all of its offshore island chain"]
bands = ["within 50 km of the border with Alphaland north of the great eastern motorway",
         "within 50 km of the border with Betaland west of the great southern motorway axis",
         "within 50 km of the border with Gammaland, north of the town of Somewhere in Department",
         "along the border with Deltaland in the Department west of the long named highway axis"]
ul = lambda xs: "<ul>" + "".join("<li>%s</li>" % x for x in xs) + "</ul>"
sa = W._regional("Regional advisory - Avoid non-essential travel", "<p>Avoid non-essential travel to the following areas due to crime:</p>"
                 + ul(far + ["Esmeraldas, excluding within 20 km of the border with Colombia where you should avoid all travel"]), 1)["line"]
sb = W._regional("Border areas - Avoid non-essential travel", "<p>Avoid non-essential travel to the following areas due to crime:</p>" + ul(bands)
                 + "<p>This advisory excludes the areas within 10 km from the border with Gammaland, where you should avoid all travel.</p>", 1)["line"]
sc = W._regional("Border areas - Avoid all travel", "<p>Avoid all travel to the following areas due to crime:</p>" + ul(bands)
                 + "<p>This advisory includes the Big National Park and the Other Long National Park.</p>", 1)["line"]
results.append(ok(not re.search(r"Esmeraldas(?:;|$)", sa) and "within 10 km from the border with Gammaland, where you should avoid all travel" in sb
                  and "This advisory includes the Big National Park and the Other Long National Park" in sc
                  and all(len(x) <= W.LINE_MAX for x in (sa, sb, sc)),
                  "over the ceiling: a place with a stricter exception is never bare, a stricter exception sentence and an include stay "
                  "(got %r / %r / %r)" % (sa[-60:], sb[-110:], sc[-90:])))
# One exception keeping its call ("where you should avoid all travel") and
# the next said bare after "; " read as one more avoid-all place: a list
# keeps every call or none, Canada's sentences stay sentences.
STRICT = re.compile(r"(?:where|on which|to which|in which) (?:you should|we advise) (?:avoid all travel|against all travel|avoid non-essential travel); ([^;.)]*)")
after = [(iso, f, m.group(1)[:40]) for iso, r in lines for f in ("line", "full") for m in STRICT.finditer(r[f])
         if W._rank(re.search(r"(avoid all travel|against all travel|avoid non-essential travel)", m.group(0)).group(1)) > W._rank(r["call"])
         and not W._WHERE.search(", " + m.group(1)) and not re.match(r"and \d+ more", m.group(1))]
mixed_x = W._fill([{"t": "the town of A where you should exercise a high degree of caution", "items": []},
                   {"t": "the band B where you should avoid all travel", "items": []},
                   {"t": "the town of C where you should exercise a high degree of caution", "items": []}], "compact",
                  {"rank": 2, "floor": 1}, 1, None)[0]
results.append(ok(not after and mixed_x.count("where you should") == 3,
                  "no exception said bare right after a stricter one's call in a '; ' list (got %s; a mixed list: %r)" % (after, mixed_x)))

# --- shapes the 2026-10-15 feed has: Mauritania, Ecuador's Guayaquil, Peru ------------------------
mrr = block("mr", "Northern and eastern")
results.append(ok(not mrr["line"].endswith(".") and mrr["full"].startswith("northern and eastern Mauritania, especially all of the following regions"),
                  "Mauritania: no full stop left mid-line, no heading said twice in full (got %r / %r)" % (mrr["line"][-30:], mrr["full"][:60])))
ecl = block("ec", "Esmeraldas province")["line"]
results.append(ok("in Guayas (Durán; Milagro; areas of northern Guayaquil; areas of southern Guayaquil)" in ecl and ecl.startswith("the province of Esmeraldas; in El Oro (")
                  and ecl.endswith(" — except within 20 km of the border with Colombia where we advise against all travel") and len(ecl) <= W.LINE_CAP,
                  "Ecuador: Guayaquil named (it hid in Guayas's 'and 15 more'), 'the province of' said once, the stricter exception kept (got %r)" % ecl))
der = W._derepeat({"groups": [{"intro": "", "items": [
    {"t": "the province of Alpha", "items": []},
    {"t": "the province of Beta, excluding the province of Gamma", "items": []},
    {"t": "the province of Delta, excluding:", "items": [{"t": "the province of Epsilon", "items": []}, {"t": "the province of Zeta", "items": []}]},
    {"t": "the city of Eta", "items": []}, {"t": "the city of Theta", "items": []}]}]})
results.append(ok([it["t"] for it in der["groups"][0]["items"]] == ["the province of Alpha", "Beta, excluding the province of Gamma",
                                                                    "Delta, excluding:", "the city of Eta", "the city of Theta"]
                  and [k["t"] for k in der["groups"][0]["items"][2]["items"]] == ["the province of Epsilon", "the province of Zeta"],
                  "a repeated 'the province of' is said once among places, never in an exception, never 'the city of' (got %s)"
                  % [it["t"] for it in der["groups"][0]["items"]]))
results.append(ok(W._qualified("Amazonas, within 20 km of the border with Peru, west of Puerto Narino") == "Amazonas"
                  and W._qualified("Cesar, in the municipalities of González and Río de Oro") == "Cesar"
                  and W._qualified("within 50 km of the border with Nigeria, north of the town of Nikki in Borgou Department") is None
                  and W._qualified("areas within 25 km of the northern borders, west of the line") is None
                  and W._qualified("the Western Desert, west of the Giza-Luxor-Aswan-Abu Simbel road, including the oasis of Dakhla") is None
                  and W._qualified("Kosovo, in particular the north") is None,
                  "'parts of' a place only where the item names the place first, then the part of it"))
# Canada's calls however the feed spells them: kept, never a notice to drop.
loose = {k: W.regional_blocks(h, "Nowhere", 1) for k, h in {
    "nb-hyphen": "<h3>Northern region - Avoid non&#8209;essential travel</h3><p>Avoid non&#8209;essential travel to the northern region due to crime.</p>",
    "nbsp": "<h3>Northern region - Avoid all&nbsp;travel</h3><p>Avoid all&nbsp;travel to the northern region due to crime.</p>",
    "no-hyphen": "<h3>Northern region - Avoid non essential travel</h3><p>Avoid non essential travel to the northern region due to crime.</p>",
    "unknown call": "<h3>Northern region - Steer clear</h3><p>Until 2027, travellers must quarantine.</p>"}.items()}
results.append(ok([(k, [x["call"] for x in v]) for k, v in loose.items()] == [
    ("nb-hyphen", ["Avoid non-essential travel"]), ("nbsp", ["Avoid all travel"]), ("no-hyphen", ["Avoid non-essential travel"]),
    ("unknown call", ["Steer clear"])],
                  "a call spelled with a non-breaking hyphen or space, or 'non essential', is that call; a heading with a ' - ' segment "
                  "is never a notice (got %s)" % [(k, [x["call"] for x in v]) for k, v in loose.items()]))

# --- text ----------------------------------------------------------------------------
ugn = next(m.group(2) for m in H3.finditer(feed("ug")["data"]["eng"]["advisories"]) if "Ebola" in m.group(1))
ugt = W._plain_text(W._body(ugn))
results.append(ok("Useful links" not in ugt and "quarantine for 21 days" in ugt,
                  "text: a block's 'Useful links' list is navigation, left out (Uganda's Ebola notice)"))
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
f5h = ("<h3>Foo - Avoid all travel</h3><p>Avoid all travel to Foo, with the exception of the following areas where you should exercise a high degree of caution:</p><ul>"
       "<li>District of Bar, excluding the town of Baz (and the coastal road leading there)</li>%s</ul>")
f5 = [W.regional_blocks(f5h % "".join("<li>Some long excepted place number %d with a long name here</li>" % i for i in range(n)), "Nowhere", 1)[0]["line"]
      for n in (6, 2)]
results.append(ok("parts of District of Bar;" in f5[0] and "District of Bar (except the town of Baz (and the coastal road leading there))" in f5[1]
                  and not any("Baz)" in x for x in f5),
                  "an exclusion from an exception is never shortened: short of room the exception is 'parts of' it, else said with "
                  "its exclusion whole (got %r / %r)" % (f5[0][:90], f5[1][:150])))
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
# full is the block uncut: no "and N more" and none of the line's shortest
# forms ("(parts excepted)", "parts of" an exception), and the line itself
# wherever the line is the whole block.
uncut = [(iso, r["t"][:30]) for iso, r in lines if r["call"].lower().startswith("avoid") and (
         re.search(r"and \d+ more|\(parts excepted\)|except (?:the following \w+: )?parts of\b", r["full"])
         or (analyzed(iso, r)["L"] and r["full"] != W._compose(analyzed(iso, r), "full")))]
pkf = block("pk", "Regional advisory")["full"]
results.append(ok(not uncut and block("et", "Border areas")["full"] != block("et", "Border areas")["line"]
                  and "Wagah (which is currently closed) and the Grand Trunk Road" in pkf and "the Kartarpur Corridor (which is intermittently open)" in pkf
                  and "Haripur and Abbottabad districts where you should exercise a high degree of caution" in pkf,
                  "full: the block uncut for the guide's AI prompt, in Canada's words — no aside or call shortened away (Pakistan's Wagah "
                  "'(which is currently closed)') (wrong: %s)" % uncut))
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
results.append(ok("Avoid all travel: Palestine. This advisory excludes the following roads" in il_js and "Highway 1; Route 90" in il_js
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
