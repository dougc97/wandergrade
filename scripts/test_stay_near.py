"""Distinct destinations first: how scripts/gen_stay_spots.py fills a guide's
"Where to stay" slots when places sit close together, without the network.

    /usr/bin/python3 scripts/test_stay_near.py

  * a neighbourhood (within DUP_KM of a chip) keeps its slot while nothing
    distinct can have it (Singapore's Clarke Quay and Gardens by the Bay) and
    loses it to a destination FAR_KM or more from every chip (Sweden's Gamla
    stan to the Stockholm Archipelago and Visby);
  * slots go to distinct destinations first, in the guide's order, then to
    neighbourhoods, then to places across town; a place across town never
    takes a neighbourhood's slot (Budapest's Parliament over Heroes' Square,
    Baku's Flame Towers over the Heydar Aliyev Center), and the chips come out
    in the guide's order;
  * the same point, the same place by name and the country's centre are
    still always left out, even with slots free; a name inside another is
    its own place only on a hand-set point FAR_KM away (the Stockholm
    Archipelago is not Stockholm, Prague Castle is Prague);
  * --check lists a neighbourhood chip only when a rebuild would drop it, and
    says so when it can't judge;
  * Singapore, Sweden, Cuba and Azerbaijan, built from their guides with
    Wikipedia's points of 2026-10-19 stubbed, give exactly the chips in
    public/stay-coords.json, and every guide place without a point is listed;
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


def pick(cands, iso="ZZ"):
    with redirect_stdout(io.StringIO()):
        return names(g.pick(iso, cands))


results.append(ok(g.DUP_KM == 3 and g.FAR_KM == 10 and g.GALLERY_SPOTS == 4 and g.MAX_SPOTS == 5,
                  "a neighbourhood is within 3 km, a destination of its own 10 km or more; gallery tops up to 4 of 5"))

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
                  "neighbourhoods before a place across town (Kuwait's souq and mosque before Kuwait Towers)"))

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

# The four countries, built from their guides with Wikipedia stubbed by the
# points it gave on 2026-10-19 (stay-aliases.json points are the file's own).
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
}
WANT = {
    "SG": [("Marina Bay", [1.28444, 103.85583]), ("Clarke Quay", [1.29002, 103.84609]), ("Sentosa", [1.248, 103.83]),
           ("Gardens by the Bay", [1.28472, 103.865]), ("Buddha Tooth Relic Temple and Museum", [1.28155, 103.844])],
    "SE": [("Stockholm", [59.32944, 18.06861]), ("Stockholm Archipelago", [59.38778, 18.73581]),
           ("Lapland", [65.929, 16.743]), ("Visby", [57.63472, 18.29917])],
    "CU": [("Old Havana", [23.13594, -82.35833]), ("Varadero", [23.13944, -81.28611]), ("Viñales", [22.61528, -83.71583]),
           ("Trinidad", [21.80417, -79.98306])],
    "AZ": [("Baku", [40.37556, 49.8325]), ("Gobustan", [40.125, 49.375]), ("Sheki", [41.19194, 47.17056]),
           ("Flame Towers", [40.35944, 49.82667])],
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
try:
    with redirect_stdout(io.StringIO()):
        built = {iso: g._build_country((iso, acts[iso], cnames))[1] for iso in WANT}
finally:
    g.coords_with_fallback = real
for iso, want in WANT.items():
    have = [(s["n"], s["ll"]) for s in stays.get(iso, [])]
    results.append(ok(have == want and [(s["n"], s["ll"]) for s in built[iso]] == want,
                      "%s is exactly %s, in the file and in a rebuild from its guide (file %s)"
                      % (iso, ", ".join(n for n, _ in want), [n for n, _ in have])))
results.append(ok(set(asked) <= set().union(*WIKI.values()),
                  "the stub holds every title the build asked (%s)" % sorted(set(asked) - set().union(*WIKI.values()))))
results.append(ok(g.UNRESOLVED["SG"] == [("hawker centres", "no coordinates on Wikipedia")]
                  and g.UNRESOLVED["AZ"] == [("Caspian seafront", "no coordinates on Wikipedia")]
                  and g.UNRESOLVED["SE"] == [] and g.UNRESOLVED["CU"] == [],
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

# The judged file: every neighbourhood chip in the four countries is one the
# rule keeps, so --check lists none of them.
rows4 = g.check({iso: stays[iso] for iso in WANT})
results.append(ok(not [r for r in rows4 if not r[3].startswith("within")]
                  and g.near_notes(rows4, build=lambda iso: built[iso]) == []
                  and {(r[0], r[1]) for r in rows4} == {("SG", "Clarke Quay"), ("SG", "Gardens by the Bay"),
                                                         ("SG", "Buddha Tooth Relic Temple and Museum"), ("AZ", "Flame Towers")},
                  "Singapore's three neighbourhoods and Baku's Flame Towers are the rule's, no --check note (%s)" % rows4))
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
