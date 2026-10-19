"""Distinct destinations first: how scripts/gen_stay_spots.py fills a guide's
"Where to stay" slots when places sit close together, without the network.

    /usr/bin/python3 scripts/test_stay_near.py

  * a neighbourhood (within DUP_KM of a chip) keeps its slot while nothing
    distinct can have it (Singapore's Clarke Quay and Gardens by the Bay) and
    loses it to a destination FAR_KM or more from every chip (Sweden's Gamla
    stan to the Stockholm Archipelago and Visby);
  * slots go to distinct destinations first, in the guide's order; then to
    places in a chip's city, the guide's things to do before its gallery
    (a gallery neighbourhood never gets in ahead of the guide's own place
    across town and so lifts the list past 4: Singapore's Buddha Tooth Relic
    Temple), and in each the place that is a chip already first (Budapest's
    Parliament over Heroes' Square, Baku's Flame Towers over the Heydar
    Aliyev Center, Tallinn's Alexander Nevsky Cathedral over Kadriorg
    Palace), then neighbourhoods, then places across town; the chips come out
    in the guide's order, and a rebuild of a rebuild changes nothing;
  * the same point (within SAME_KM: Souq Waqif, 80 m from Doha's), the same
    place by name and the country's centre are still always left out, even
    with slots free; a name inside another is its own place only on a
    hand-set point FAR_KM away (the Stockholm Archipelago is not Stockholm,
    Prague Castle is Prague);
  * --check lists a neighbourhood chip only when a rebuild from the file
    would drop it, and says so when it can't judge;
  * Singapore, Sweden, Cuba, Azerbaijan, Estonia, Kuwait and Qatar, rebuilt
    from their guides and main's chips with Wikipedia's points of 2026-10-19
    stubbed, give exactly the chips in public/stay-coords.json, and every
    guide place without a point is listed;
  * Wikipedia's batched answers map each asked title through normalisation
    and redirects, and Gotland (Visby) counts as Sweden.
"""
import importlib.util
import io
import json
import os
import sys
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
spec = importlib.util.spec_from_file_location("gen_stay_spots", os.path.join(ROOT, "scripts", "gen_stay_spots.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

KM = 1 / 111.2                                   # degrees of latitude per km


def c(n, km, cap=5, cur=False, east=0.0):
    """A synthetic candidate `km` north of (10, 20), in no real country."""
    return {"n": n, "ll": [round(10 + km * KM, 6), round(20 + east * KM, 6)], "cap": cap, "cur": cur}


def names(spots):
    return [s["n"] for s in spots]


def pick(cands, iso="ZZ", prev=None):
    with redirect_stdout(io.StringIO()):
        return names(g.pick(iso, cands, prev))


results.append(ok(g.DUP_KM == 3 and g.FAR_KM == 10 and g.GALLERY_SPOTS == 4 and g.MAX_SPOTS == 5 and g.SAME_KM == 0.25,
                  "one point within 0.25 km, a neighbourhood within 3 km, a destination of its own 10 km or more;"
                  " gallery tops up to 4 of 5"))

# A neighbourhood keeps its slot while nothing distinct can have it.
A, N = c("Alpha", 0), c("Nook", 1)
results.append(ok(pick([A, N]) == ["Alpha", "Nook"],
                  "a neighbourhood 1 km off beats an empty slot (%s)" % pick([A, N])))
C = c("Crosstown", 5, cap=2)
results.append(ok(pick([A, C, dict(N, cap=2)]) == ["Alpha", "Nook"],
                  "a place across town, though first in the guide, never takes a neighbourhood's slot"
                  " (Heroes' Square / Parliament: %s)" % pick([A, C, dict(N, cap=2)])))
results.append(ok(pick([A, dict(C, cap=3), dict(N, cap=3)]) == ["Alpha", "Crosstown", "Nook"],
                  "and fills a slot nothing else wants, in the guide's order (%s)" % pick([A, dict(C, cap=3), dict(N, cap=3)])))

# ... and loses it to a distinct destination.
F = c("Faraway", 50, cap=2)
results.append(ok(pick([A, dict(N, cap=2), F]) == ["Alpha", "Faraway"],
                  "a destination 50 km off takes the neighbourhood's slot (%s)" % pick([A, dict(N, cap=2), F])))
results.append(ok(pick([A, dict(N, cap=3), dict(F, cap=3)]) == ["Alpha", "Nook", "Faraway"],
                  "and with room for both, both stay, in the guide's order"))
F9 = c("Ninekm", 9.5, cap=2)
results.append(ok(pick([A, dict(N, cap=2), F9]) == ["Alpha", "Nook"],
                  "a place 9.5 km off is across town, not distinct: the neighbourhood stays (%s)" % pick([A, dict(N, cap=2), F9])))

# Distinct destinations first, in the guide's order; across town after.
X = c("Uptown", 6)
G1, G2, G3 = c("Gal one", 100, cap=4), c("Gal two", 200, cap=4), c("Gal three", 300, cap=4)
results.append(ok(pick([A, dict(X, cap=2), dict(F, cap=2)]) == ["Alpha", "Faraway"],
                  "the last slot goes to the distinct place, not the one across town ahead of it"))
results.append(ok(pick([A, X, G1, G2, G3]) == ["Alpha", "Uptown", "Gal one", "Gal two", "Gal three"],
                  "Korea's shape: three gallery destinations fill to 4, the in-city activity place takes the 5th"
                  " (Hongdae after Donggung): %s" % pick([A, X, G1, G2, G3])))
results.append(ok(pick([A, dict(X, cap=4), dict(N, cap=4), G1, G2, G3]) == ["Alpha", "Gal one", "Gal two", "Gal three"],
                  "distinct destinations take every slot before a neighbourhood or a place across town"))
N2 = c("Corner", 1.5, east=1)
results.append(ok(pick([A, dict(X, cap=3), dict(N, cap=3), dict(N2, cap=3)]) == ["Alpha", "Nook", "Corner"],
                  "with no chip in the city yet, neighbourhoods before a place across town"))

# The guide's things to do before its gallery, in a chip's city.
GN, GN2 = c("Shrine", 1, cap=4, east=1), c("Garden", 1.5, cap=4, east=-1)
sg = [A, N, X, GN, GN2]
results.append(ok(pick(sg) == ["Alpha", "Nook", "Uptown", "Shrine"],
                  "a gallery neighbourhood waits for the guide's own place across town, so the gallery stops at 4"
                  " (Singapore: Clarke Quay, Sentosa, then Gardens by the Bay, not Buddha Tooth as a 5th): %s" % pick(sg)))
results.append(ok(pick([A, N, GN, GN2]) == ["Alpha", "Nook", "Shrine", "Garden"],
                  "and tops a thin list up to 4 with neighbourhoods (%s)" % pick([A, N, GN, GN2])))

# In a city, the place that is a chip already keeps its slot.
P_A, P_C, P_N = ({"n": x["n"], "ll": x["ll"]} for x in (A, C, N))
results.append(ok(pick([A, dict(C, cap=2), dict(N, cap=2)], prev=[P_A, P_C]) == ["Alpha", "Crosstown"]
                  and pick([A, dict(C, cap=2), dict(N, cap=2)], prev=[P_A, P_N]) == ["Alpha", "Nook"],
                  "the chip already in the file keeps its slot over another place in its city, across town or not"
                  " (Kuwait's Grand Mosque; Tallinn's Alexander Nevsky Cathedral over Kadriorg Palace)"))
results.append(ok(pick([A, dict(N, cap=2), F], prev=[P_A, P_N]) == ["Alpha", "Faraway"],
                  "but still gives it to a distinct destination (Gamla stan to the Stockholm Archipelago)"))
S, M, T = c("Souq", 0.6, east=0.3), c("Mosque", 0.5, east=-0.3), c("Towers", 3.3, cap=4)
kw = [A, S, M, F, T]
kw_prev = [{"n": x["n"], "ll": x["ll"]} for x in (A, M, F, T)]
results.append(ok(pick(kw, prev=kw_prev) == ["Alpha", "Souq", "Mosque", "Faraway"],
                  "and the guide's things to do still come before a gallery chip in the city: four of them leave the"
                  " gallery no slot (Kuwait's souq over Kuwait Towers, which had its slot only while the souq had no"
                  " point): %s" % pick(kw, prev=kw_prev)))

# One point within SAME_KM, whatever the names.
souq, church = c("Souq", 0.08, east=0.02), c("Cathedral", 0.37, east=-0.05)
results.append(ok(pick([A, souq, church]) == ["Alpha", "Cathedral"],
                  "a place 80 m from a chip is its point, left out with slots free; 0.37 km off is a neighbourhood"
                  " (%s)" % pick([A, souq, church])))

# Exact duplicates are always out, even with slots free.
same_pt = dict(c("Other name", 0))
same_nm = c("Alpha Old Town", 0.2)
results.append(ok(pick([A, same_pt, same_nm]) == ["Alpha"],
                  "the same point under another name and the same place by name are left out (Old Havana / Havana)"))
cen = g._centroids()["TT"]
mid = {"n": "Middle", "ll": [cen[1], cen[0]], "cap": 5}
results.append(ok(pick([{"n": "Trinidad", "ll": [10.5, -61.3], "cap": 5}, mid], iso="TT") == ["Trinidad"],
                  "the country's centre is left out"))
sto = {"n": "Stockholm", "ll": [59.32944, 18.06861], "cap": 5}
arch = {"n": "Stockholm Archipelago", "ll": [59.38778, 18.73581], "cap": 5}
pra = {"n": "Prague", "ll": [50.0875, 14.42139], "cap": 5}
castle = {"n": "Prague Castle", "ll": [50.09, 14.4], "cap": 5, "cur": True}
results.append(ok(pick([sto, dict(arch, cur=True)], "SE") == ["Stockholm", "Stockholm Archipelago"]
                  and pick([sto, arch], "SE") == ["Stockholm"] and pick([pra, castle], "CZ") == ["Prague"],
                  "a name inside another is one place, unless its point is set by hand FAR_KM away"
                  " (the Stockholm Archipelago, 38 km out, yes; Prague Castle, 1.5 km, no)"))
out = io.StringIO()
with redirect_stdout(out):
    g.pick("AE", [{"n": "Dubai", "ll": [25.20472, 55.27083], "cap": 5}, {"n": "Dubai", "ll": [25.20472, 55.27083], "cap": 5},
                  {"n": "Dubai Marina", "ll": [25.08135, 55.14408], "cap": 4}])
said = out.getvalue()
results.append(ok("Dubai Marina" in said and "19 km off" in said and said.count("left out") == 1,
                  "a repeated name goes quietly; a name inside another 19 km off is said (%r)" % said.strip()[:80]))

# --check: a neighbourhood chip is a note only when a rebuild drops it.
data = {"ZZ": [{"n": "Alpha", "ll": A["ll"]}, {"n": "Nook", "ll": N["ll"]}]}
rows = g.check(data)
near = [r for r in rows if r[3].startswith("within")]
results.append(ok(near == [("ZZ", "Nook", N["ll"], "within 3 km of Alpha")], "check() still finds the neighbourhood (%s)" % rows))
keep = g.near_notes(rows, build=lambda iso: data[iso])
drop = g.near_notes(rows, build=lambda iso: [{"n": "Alpha", "ll": A["ll"]}, {"n": "Faraway", "ll": F["ll"]}])
unknown = g.near_notes(rows, build=lambda iso: None)
results.append(ok(keep == [] and len(drop) == 1 and drop[0][:2] == ("ZZ", "Nook") and "a rebuild drops it" in drop[0][3]
                  and len(unknown) == 1 and "not judged" in unknown[0][3],
                  "--check: no note for a neighbourhood the rule keeps; a note for one a rebuild drops, or can't judge"))
results.append(ok(g.near_notes([("ZZ", "Far", [0, 0], "outside its country")], build=lambda iso: 1 / 0) == [],
                  "and it asks nothing for a file without neighbourhoods"))

# Seven countries, rebuilt from their guides and main's chips (as main()
# rebuilds the file) with Wikipedia stubbed by the points it gave on
# 2026-10-19 (stay-aliases.json points are the file's own).
WIKI = {
    "SG": {"Marina Bay": [1.28444, 103.85583], "hawker centres": None, "Clarke Quay": [1.29002, 103.84609],
           "Sentosa": [1.248, 103.83], "Marina Bay Sands": [1.2825, 103.86], "Gardens by the Bay": [1.28472, 103.865],
           "Sri Mariamman Temple, Singapore": [1.28261, 103.84528], "Esplanade – Theatres on the Bay": [1.28972, 103.85528],
           "Merlion": [1.28681, 103.8545]},
    "SE": {"Stockholm": [59.32944, 18.06861], "Lapland": [65.929, 16.743], "Stockholm City Hall": [59.3275, 18.055],
           "Gamla stan": [59.325, 18.07083], "Visby": [57.63472, 18.29917], "Vasa Museum": [59.32794, 18.09139]},
    "CU": {"Old Havana": [23.13594, -82.35833], "Varadero": [23.13944, -81.28611], "Havana": [23.13667, -82.35889],
           "Viñales": [22.61528, -83.71583], "Trinidad, Cuba": [21.80417, -79.98306], "Viñales Valley": [22.61667, -83.71667],
           "Castillo de San Pedro de la Roca": [19.96871, -75.8703], "El Capitolio": [23.13528, -82.35944]},
    "AZ": {"Baku": [40.37556, 49.8325], "Gobustan State Historical and Cultural Reserve": [40.125, 49.375],
           "Sheki": [41.19194, 47.17056], "Caspian seafront": None, "Flame Towers": [40.35944, 49.82667],
           "Maiden Tower (Baku)": [40.3661, 49.8372], "Palace of the Shirvanshahs": [40.36615, 49.83344],
           "Heydar Aliyev Center": [40.39528, 49.86694]},
    "EE": {"Tallinn": [59.43722, 24.74528], "Saaremaa": [58.41667, 22.5], "Forests & bogs": None,
           "Kadriorg Palace": [59.43851, 24.79084], "Alexander Nevsky Cathedral, Tallinn": [59.43583, 24.73936],
           "Tallinn Town Hall": [59.43709, 24.74547], "Lahemaa National Park": [59.57111, 25.80028]},
    "KW": {"Kuwait City": [29.36972, 47.97833], "Grand Mosque": [29.37889, 47.97472], "Failaka": [29.43889, 48.33333],
           "Kuwait Towers": [29.39, 48.00306], "Al Hamra Tower": [29.379, 47.9932]},
    "QA": {"Doha": [25.28667, 51.53333], "Khor Al Adaid": [24.63, 51.296], "Barzan Towers": [25.41802, 51.41309],
           "Katara (cultural village)": [25.36033, 51.52636]},
}
MAIN = {    # main 787e351's chips, the file these were rebuilt from
    "SG": [["Marina Bay", [1.28444, 103.85583]], ["Clarke Quay", [1.29002, 103.84609]], ["Sentosa", [1.248, 103.83]], ["Gardens by the Bay", [1.28472, 103.865]]],
    "SE": [["Stockholm", [59.32944, 18.06861]], ["Lapland", [65.929, 16.743]], ["Gamla stan", [59.325, 18.07083]], ["Vasa Museum", [59.32794, 18.09139]]],
    "CU": [["Old Havana", [23.13594, -82.35833]], ["Varadero", [23.13944, -81.28611]], ["Viñales", [22.61528, -83.71583]], ["Malecón", [23.14167, -82.36806]]],
    "AZ": [["Baku", [40.37556, 49.8325]], ["Gobustan", [40.125, 49.375]], ["Sheki", [41.19194, 47.17056]], ["Flame Towers", [40.35944, 49.82667]]],
    "EE": [["Tallinn", [59.43722, 24.74528]], ["Saaremaa", [58.41667, 22.5]], ["Alexander Nevsky Cathedral", [59.43583, 24.73936]], ["Lahemaa National Park", [59.57111, 25.80028]]],
    "KW": [["Kuwait City", [29.36972, 47.97833]], ["Grand Mosque", [29.37889, 47.97472]], ["Failaka", [29.43889, 48.33333]], ["Kuwait Towers", [29.39, 48.00306]]],
    "QA": [["Doha", [25.28667, 51.53333]], ["Khor Al Adaid", [24.63, 51.296]], ["Museum of Islamic Art", [25.29502, 51.53927]], ["The Pearl-Qatar", [25.36861, 51.55194]]],
}
MAIN = {iso: [{"n": n, "ll": ll} for n, ll in v] for iso, v in MAIN.items()}
WANT = {
    "SG": [("Marina Bay", [1.28444, 103.85583]), ("Clarke Quay", [1.29002, 103.84609]), ("Sentosa", [1.248, 103.83]),
           ("Gardens by the Bay", [1.28472, 103.865])],
    "SE": [("Stockholm", [59.32944, 18.06861]), ("Stockholm Archipelago", [59.38778, 18.73581]),
           ("Lapland", [65.929, 16.743]), ("Visby", [57.63472, 18.29917])],
    "CU": [("Old Havana", [23.13594, -82.35833]), ("Varadero", [23.13944, -81.28611]), ("Viñales", [22.61528, -83.71583]),
           ("Trinidad", [21.80417, -79.98306])],
    "AZ": [("Baku", [40.37556, 49.8325]), ("Gobustan", [40.125, 49.375]), ("Sheki", [41.19194, 47.17056]),
           ("Flame Towers", [40.35944, 49.82667])],
    "EE": [("Tallinn", [59.43722, 24.74528]), ("Saaremaa", [58.41667, 22.5]),
           ("Alexander Nevsky Cathedral", [59.43583, 24.73936]), ("Lahemaa National Park", [59.57111, 25.80028])],
    "KW": [("Kuwait City", [29.36972, 47.97833]), ("Souq Al-Mubarakiya", [29.37388, 47.97363]),
           ("Grand Mosque", [29.37889, 47.97472]), ("Failaka", [29.43889, 48.33333])],
    "QA": [("Doha", [25.28667, 51.53333]), ("Khor Al Adaid", [24.63, 51.296]),
           ("National Museum of Qatar", [25.28847, 51.54926]), ("Barzan Towers", [25.41802, 51.41309])],
}
with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
    acts = json.load(f)
with open(os.path.join(ROOT, "public", "country-names.json"), encoding="utf-8") as f:
    cnames = json.load(f)
with open(os.path.join(ROOT, "public", "stay-coords.json"), encoding="utf-8") as f:
    stays = json.load(f)
real = g.coords_with_fallback
asked = []


def stub(subject, country, iso):
    asked.append(subject)
    return WIKI[iso].get(subject)


g.coords_with_fallback = stub
said = {}
try:
    built, again, bare = {}, {}, {}
    for iso in WANT:
        buf = io.StringIO()
        with redirect_stdout(buf):
            built[iso] = g._build_country((iso, acts[iso], cnames, MAIN[iso]))[1]
        said[iso] = buf.getvalue()
        with redirect_stdout(io.StringIO()):
            again[iso] = g._build_country((iso, acts[iso], cnames, built[iso]))[1]
            bare[iso] = g._build_country((iso, acts[iso], cnames))[1]
finally:
    g.coords_with_fallback = real
for iso, want in WANT.items():
    have = [(s["n"], s["ll"]) for s in stays.get(iso, [])]
    results.append(ok(have == want and [(s["n"], s["ll"]) for s in built[iso]] == want,
                      "%s is exactly %s, in the file and in a rebuild from its guide and main's chips (file %s)"
                      % (iso, ", ".join(n for n, _ in want), [n for n, _ in have])))
results.append(ok(again == built, "a rebuild of the rebuilt file changes nothing (%s)"
                  % [iso for iso in WANT if again[iso] != built[iso]]))
results.append(ok({iso for iso in WANT if bare[iso] != built[iso]} == {"EE"}
                  and [s["n"] for s in bare["EE"]][2] == "Kadriorg Palace",
                  "with no file to keep from, only Tallinn differs: a neighbourhood new to the list (Kadriorg Palace,"
                  " gallery place #1) over one further down (%s)" % [iso for iso in WANT if bare[iso] != built[iso]]))
results.append(ok("Souq Waqif [25.28738, 51.53321] left out — same point as Doha" in said["QA"],
                  "Qatar's Souq Waqif, 80 m from Doha's point, is left out as that point, and said (%r)"
                  % said["QA"].strip()[:120]))
results.append(ok(set(asked) <= set().union(*WIKI.values()),
                  "the stub holds every title the build asked (%s)" % sorted(set(asked) - set().union(*WIKI.values()))))
results.append(ok(g.UNRESOLVED["SG"] == [("hawker centres", "no coordinates on Wikipedia")]
                  and g.UNRESOLVED["AZ"] == [("Caspian seafront", "no coordinates on Wikipedia")]
                  and g.UNRESOLVED["EE"] == [("Forests & bogs", "no coordinates on Wikipedia")]
                  and g.UNRESOLVED["SE"] == g.UNRESOLVED["CU"] == g.UNRESOLVED["KW"] == g.UNRESOLVED["QA"] == [],
                  "every guide place without a point is listed per country, and Sweden's Visby and archipelago have"
                  " theirs (%s)" % {k: g.UNRESOLVED[k] for k in WANT}))
g._COORDS["Atlantis, Sweden"] = [0.0, 0.0]
try:
    why = g.why_unresolved("Atlantis", "Sweden", "SE")
finally:
    del g._COORDS["Atlantis, Sweden"]
results.append(ok(why == "Wikipedia's [0.0, 0.0] is outside Sweden on the map" and g.why_unresolved("Nowhere", "Sweden", "SE")
                  == "no coordinates on Wikipedia", "and says why: no coordinates, or a point outside the country (%s)" % why))
results.append(ok(g.in_country([57.63472, 18.29917], "SE") and not g.in_country([56.95, 24.1], "SE"),
                  "Gotland (Visby, off the coarse map) counts as Sweden; Riga does not"))

# The judged file: every neighbourhood chip in the seven countries is one the
# rule keeps, so --check lists none of them; main's file had Sweden's two
# and Havana's Malecón, which a rebuild drops, and Qatar's museum, which the
# guide no longer names.
rows7 = g.check({iso: stays[iso] for iso in WANT})
results.append(ok(not [r for r in rows7 if not r[3].startswith("within")]
                  and g.near_notes(rows7, build=lambda iso: built[iso]) == []
                  and {(r[0], r[1]) for r in rows7} == {("SG", "Clarke Quay"), ("SG", "Gardens by the Bay"), ("AZ", "Flame Towers"),
                                                         ("EE", "Alexander Nevsky Cathedral"), ("KW", "Souq Al-Mubarakiya"),
                                                         ("KW", "Grand Mosque"), ("QA", "National Museum of Qatar")},
                  "Singapore's two neighbourhoods, Baku's, Tallinn's, Kuwait City's and Doha's are the rule's, no"
                  " --check note (%s)" % sorted((r[0], r[1]) for r in rows7)))
rows_main = g.check(MAIN)
notes_main = g.near_notes(rows_main, build=lambda iso: built[iso])
results.append(ok({(r[0], r[1]) for r in notes_main} == {("SE", "Gamla stan"), ("SE", "Vasa Museum"), ("CU", "Malecón"),
                                                         ("QA", "Museum of Islamic Art")}
                  and ("SG", "Clarke Quay") in {(r[0], r[1]) for r in rows_main},
                  "on main's file --check lists what a rebuild drops (Sweden's two, Havana's Malecón, Qatar's museum)"
                  " and not what it"
                  " keeps (Singapore's, Tallinn's, Kuwait's Grand Mosque): %s" % sorted((r[0], r[1]) for r in notes_main)))
# Sweden's chip for the archipelago is its hand-set point, 38 km out, and
# check() takes it as its own place by that point.
results.append(ok(g._curated("SE", [59.38778, 18.73581]) and not any(r[0] == "SE" for r in g.check({"SE": stays["SE"]})),
                  "the Stockholm Archipelago's point is stay-aliases.json's, its own place in --check"))

# Wikipedia asked in batches: each title followed through normalisation and
# redirects to its page.
canned = {"batchcomplete": "", "query": {
    "normalized": [{"from": "maiden Tower (Baku)", "to": "Maiden Tower (Baku)"}],
    "redirects": [{"from": "Paektu Mountain", "to": "Mount Paektu"}],
    "pages": {"1": {"title": "Mount Paektu", "coordinates": [{"lat": 41.993333, "lon": 128.0775}]},
              "2": {"title": "Maiden Tower (Baku)", "coordinates": [{"lat": 40.3661, "lon": 49.8372}]},
              "-1": {"title": "Desert safari", "missing": ""}}}}
real_open = g.urllib.request.urlopen
g.urllib.request.urlopen = lambda req, timeout=None: io.BytesIO(json.dumps(canned).encode())
try:
    got = g._wiki(["Paektu Mountain", "maiden Tower (Baku)", "Desert safari"])
finally:
    g.urllib.request.urlopen = real_open
results.append(ok(got == {"Paektu Mountain": [41.99333, 128.0775], "maiden Tower (Baku)": [40.3661, 49.8372], "Desert safari": None},
                  "a batched answer maps each title through redirects and normalisation (%s)" % got))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
