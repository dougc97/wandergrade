"""The stays skip list (scripts/stay-skip.json), the spots it guards and the
generator's rules for a sound point, without the network.

    /usr/bin/python3 scripts/test_stay_skip.py

  * stay-skip.json is dated and holds, per country, Canada's "Avoid all
    travel" blocks by heading, each with a fingerprint of its words; every
    skipped place says where it falls and quotes Canada's words for it.
    Under "us" the same for the US's regional "Do not travel" words, each
    skipped place quoting the US;
  * no anchor in public/stay-coords.json is a skipped place, and the guide's
    served stays stand-in follows: the freed slots refilled from each
    guide's own places (Ethiopia near Bale Mountains National Park, Cameroon
    near Kribi with Foumban, Benin with Porto-Novo), never a skipped one;
  * each place skipped since the first list is skipped under its own
    government's list and under its other names (Tiya, clear of Canada's
    zones, is in the US's Oromia; Tanougou Falls, outside Canada's avoid-all
    band, borders Burkina Faso for the US), and nothing beside them is
    (Bale Mountains, which the US exempts; Mount Hagen, a town the US
    exempts; Kribi, Zakouma, Chinguetti, Terjit, Porto-Novo...);
  * the generator never adds a skipped place, under any of its names (an
    activity's "Pendjari" is the chip "Pendjari National Park"; "Limbé" is
    "Limbe"; "Gonder" is Gondar, "Gisenyi" the Lake Kivu chip) or on its
    point (any label within 5 km of a skipped place's point); and, judged by
    a list of names and points kept here apart from stay-skip.json, no chip
    in the file or in a stubbed build is in a zone;
  * a point of its own: a whole-degree point near a border is not trusted
    (the Fann Mountains' (39, 68) is in Uzbekistan) unless curated; a spot on
    another spot's very point (Maracas Bay on Trinidad's), within 3 km of
    one, or on the country's centre is left out, at build and in --check;
    the file has no such spot left but the listed pre-rule landmarks;
  * a fingerprint ignores layout (bullets, spacing, punctuation) and sees a
    changed word; --check's review, on Benin's feed fixture, passes the
    blocks as reviewed and flags one that is new, gone or reworded; the US
    feed's "Do not travel" words are read from its RSS (level 4 left to
    app.js) and reviewed the same way; a row that says some areas have
    increased risk but names none (Mexico, India) is reviewed by hand on
    travel.state.gov and re-flagged at any reissue; a row whose title maps to
    no country is reported, and "Côte d’Ivoire" and "Republic of Congo" map;
  * Brazil's Iguazú Falls is out under the US's "International land borders"
    (the Foz exception is the staff rules'), Mauritania's Amojjar Pass and
    Togo's Fazao-Malfakassa chips sit on their OSM points.
"""
import importlib.util
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
spec = importlib.util.spec_from_file_location("gen_stay_spots", os.path.join(ROOT, "scripts", "gen_stay_spots.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
from fxtracker import guide_sizers, watchouts  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

skip = g.SKIP
countries = skip.get("countries") or {}
results.append(ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", skip.get("asof", "")) is not None, "stay-skip.json carries an as-of date"))
blocks = [(iso, t, b) for iso, bs in countries.items() for t, b in bs.items()]
results.append(ok(blocks and all(t.lower().endswith(" - avoid all travel") for _, t, b in blocks),
                  "%d blocks, every one a Canada \"Avoid all travel\" heading" % len(blocks)))
results.append(ok(all(re.fullmatch(r"[0-9a-f]{12}", b.get("fp") or "") for _, t, b in blocks), "every block has a fingerprint"))
places = [(iso, n, v) for iso, t, b in blocks for n, v in (b.get("skip") or {}).items()]
results.append(ok(all(v.get("where") and v.get("canada") for _, n, v in places),
                  "%d skipped places, each with where it falls and Canada's words" % len(places)))
us = skip.get("us") or {}
us_countries = us.get("countries") or {}
results.append(ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", us.get("asof", "")) is not None and len(us_countries) >= 30
                  and all(re.fullmatch(r"[0-9a-f]{12}", e.get("fp") or "") for e in us_countries.values()),
                  "the US list is dated, %d countries' \"Do not travel\" words each fingerprinted" % len(us_countries)))
us_places = [(iso, n, v) for iso, e in us_countries.items() for n, v in (e.get("skip") or {}).items()]
results.append(ok(us_places and all(v.get("where") and v.get("us") for _, n, v in us_places),
                  "%d US-skipped places, each with where it falls and the US's words" % len(us_places)))

with open(os.path.join(ROOT, "public", "stay-coords.json"), encoding="utf-8") as f:
    stays = json.load(f)
left = g.skipped_present(stays)
results.append(ok(not left, "no stay anchor is a skipped place (%s)" % left[:3]))
et = guide_sizers.stay("ET")
results.append(ok("near Bale Mountains National Park" in et and "staychip" not in et
                  and not any(x in et for x in ("Lalibela", "Gondar", "Simien", "Danakil", "Tiya")),
                  "Ethiopia's stand-in is Bale Mountains National Park alone (Amhara, Afar and the US's Oromia left out)"))
cm = guide_sizers.stay("CM")
results.append(ok("near Kribi" in cm and "Foumban" in cm
                  and not any(x in cm for x in ("Mount Cameroon", "Limbe", "Waza", "Bafut", "Mokolo", "Korup")),
                  "Cameroon's stand-in is near Kribi, with Foumban; nothing in the North-West, South-West or Far North"))
bj = guide_sizers.stay("BJ")
results.append(ok("Pendjari" not in bj and "Tanougou" not in bj and "Ganvié" in bj and "Porto-Novo" in bj,
                  "Benin's stand-in keeps Ganvié, Ouidah, Abomey and adds Porto-Novo, not Pendjari"))

results.append(ok(g.skipped("BJ", "Pendjari") == "Pendjari National Park", "an activity's short name is the skipped chip"))
results.append(ok(g.skipped("CM", "Limbé") == "Limbe", "accents don't hide a skipped place"))
results.append(ok(g.skipped("BJ", "Ganvié") is None and g.skipped("CM", "Kribi") is None
                  and g.skipped("TD", "Zakouma") is None and g.skipped("MR", "Chinguetti") is None,
                  "nothing outside the zones is skipped"))
results.append(ok(g.skipped("KE", "Lalibela") is None, "a skip is for its own country only"))

# Every place skipped since the first list, under the government whose words
# cover it, and under its other names.
canada_only = {"countries": countries}
us_only = {"us": us}
NEW_CANADA = [("NG", "Gashaka Gumti National Park", "Gashaka Gumti"), ("NG", "Agbokim Waterfalls", "Agbokim Waterfalls"),
              ("NG", "Obudu Mountain Resort", "Obudu Mountain Resort"), ("TN", "Sbeitla", "Sbeitla"),
              ("CO", "Las Lajas Sanctuary", "Las Lajas"), ("IL", "Rosh HaNikra grottoes", "Rosh HaNikra")]
NEW_US = [("ET", "Tiya", "Tiya"), ("BJ", "Tanougou Falls", "Tanougou Falls"), ("DZ", "Tassili n'Ajjer", "Tassili n'Ajjer"),
          ("KE", "Lamu Island", "Lamu"), ("PG", "Mount Wilhelm", "Mount Wilhelm"), ("PG", "Highlands", "Highlands"),
          ("RW", "Volcanoes National Park", "Volcanoes National Park"), ("RW", "Lake Kivu", "Lake Kivu"),
          ("TG", "Koutammakou", "Koutammakou"), ("VE", "Canaima", "Canaima National Park"), ("VE", "Roraima", "Mount Roraima"),
          ("BR", "Iguazú Falls", "Iguaçu Falls")]
for iso, place, alias in NEW_CANADA:
    results.append(ok(g.skipped(iso, place, skip=canada_only) == place and g.skipped(iso, alias) == place,
                      "%s %s is in Canada's avoid-all zone (also as \"%s\")" % (iso, place, alias)))
for iso, place, alias in NEW_US:
    results.append(ok(g.skipped(iso, place, skip=canada_only) is None and g.skipped(iso, place, skip=us_only) == place
                      and g.skipped(iso, alias) == place,
                      "%s %s is in a US \"Do not travel\" area, not Canada's (also as \"%s\")" % (iso, place, alias)))
keep = [("ET", "Bale Mountains National Park"), ("ET", "Sanetti Plateau"), ("CM", "Foumban"), ("CM", "Bandjoun"),
        ("MR", "Terjit"), ("MR", "Amojjar Pass"), ("BJ", "Porto-Novo"), ("PG", "Mount Hagen"), ("RW", "Kigali"),
        ("RW", "Lake Burera"), ("RW", "Nyungwe"), ("BI", "Bujumbura"), ("BR", "Christ the Redeemer"), ("BR", "Salvador"),
        ("TG", "Fazao-Malfakassa National Park"), ("RW", "Musanze"),
        ("VE", "Los Roques"), ("VE", "Médanos de Coro"), ("KE", "Ruins of Gedi"), ("IL", "Masada"), ("DZ", "Djémila")]
left_in = [(iso, n) for iso, n in keep if g.skipped(iso, n)]
results.append(ok(not left_in, "and the places beside them stay: the US exempts Bale Mountains and the town of Mount Hagen;"
                               " Foumban, Terjit, Porto-Novo, Nyungwe... are clear of both (%s)" % left_in))

# Other names and points. A skipped place's "aka" names and its point ("ll")
# keep it out under a label the list doesn't hold.
AKA = [("ET", "Gonder", "Gondar"), ("ET", "Aksum", "Obelisk of Axum"), ("ET", "Danakil Depression", "Danakil Desert"),
       ("RW", "Gisenyi", "Lake Kivu"), ("RW", "Kinigi", "Volcanoes National Park"), ("KE", "Lamu Old Town", "Lamu Island"),
       ("KE", "Shela", "Lamu Island"), ("VE", "Angel Falls", "Canaima"), ("BR", "Foz do Iguaçu", "Iguazú Falls")]
missed = [(iso, n, g.skipped(iso, n)) for iso, n, want in AKA if g.skipped(iso, n) != want]
results.append(ok(not missed, "a skipped place's other names are skipped: Gonder, Aksum, Gisenyi, Kinigi, Lamu Old Town,"
                              " Angel Falls, Foz do Iguaçu (%s)" % missed))
all_skips = [(iso, n, v) for iso, n, v in places + us_places]
with_ll = [(iso, n, v["ll"]) for iso, n, v in all_skips if v.get("ll")]
results.append(ok(len(with_ll) >= len(all_skips) - 3
                  and all(isinstance(ll, list) and len(ll) == 2 and -90 <= ll[0] <= 90 and -180 <= ll[1] <= 180
                          for _, _, ll in with_ll),
                  "%d of %d skipped places carry their point" % (len(with_ll), len(all_skips))))
kivu = g.SKIP["us"]["countries"]["RW"]["skip"]["Lake Kivu"]["ll"]
results.append(ok(g.skipped_near("RW", [kivu[0] + 0.01, kivu[1] + 0.01]) == "Lake Kivu"
                  and g.skipped_near("RW", [-1.9525, 30.115]) is None and g.skipped_near("BJ", kivu) is None
                  and g.skip_hit("RW", {"n": "Rubavu Beach Hotel", "ll": kivu}) == "Lake Kivu",
                  "a label on a skipped place's ground is that place (Gisenyi's beach, 1.6 km off); Kigali is not"))
p2 = g.prune({"RW": [{"n": "Kigali", "ll": [-1.9525, 30.115]}, {"n": "Lakeside", "ll": kivu}]})
results.append(ok(p2 == {"RW": [{"n": "Kigali", "ll": [-1.9525, 30.115]}]}
                  and g.skipped_present({"RW": [{"n": "Lakeside", "ll": kivu}]}) == [("RW", "Lakeside", "Lake Kivu")],
                  "--prune and --check catch a skipped place by its point"))
real = g.coords_with_fallback
g.coords_with_fallback = lambda subject, country, iso: list(kivu) if subject == "Lakeside beaches" else [-1.9525, 30.115]
try:
    rw = [s["n"] for s in g._build_country(("RW", {"activities": [{"t": "Lakeside beaches"}, {"t": "Kigali"}]}, {}))[1]]
finally:
    g.coords_with_fallback = real
results.append(ok(rw == ["Kigali"], "the build leaves out a label on a skipped point (Rwanda: %s)" % rw))

# The generator itself, with Wikipedia stubbed: every candidate gets its own
# in-country point, so only the skip list can keep one out.
real = g.coords_with_fallback
pts = {}
g.coords_with_fallback = lambda subject, country, iso: pts.setdefault(subject, [1.0 + len(pts), 1.0])
try:
    with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
        acts = json.load(f)
    built = {iso: g._build_country((iso, acts[iso], {}))[1]
             for iso in ("BJ", "CM", "ET", "TD", "MZ", "MR", "NG", "RW", "PG", "TG", "VE", "DZ", "KE", "TN", "CO", "IL", "BR")}
finally:
    g.coords_with_fallback = real
bad = [(iso, s["n"]) for iso, spots in built.items() for s in spots if g.skipped(iso, s["n"])]
results.append(ok(not bad, "the generator adds no skipped place (%s)" % bad[:3]))
results.append(ok(all(built[iso] for iso in built), "and still finds places outside the zones (%s)"
                  % {iso: [s["n"] for s in spots] for iso, spots in built.items()}))

# Judged apart from stay-skip.json and g.skipped: the places the audits put
# in a zone, by words in their names and by their ground (5 km round each).
ZONE_WORDS = {"ET": ["lalibela", "gondar", "gonder", "fasil", "simien", "semien", "danakil", "axum", "aksum", "tiya"],
              "CM": ["mount cameroon", "limbe", "waza", "mokolo", "bafut", "korup", "ring road"],
              "BJ": ["pendjari", "tanougou"], "BI": ["kibira"], "MZ": ["quirimbas", "ibo"],
              "MR": ["adrar", "richat", "tichit"], "PK": ["k2"],
              "TD": ["tibesti", "ennedi", "ounianga", "toussid", "aloba", "yoa"], "TJ": ["wakhan"],
              "NG": ["zuma", "gashaka", "agbokim", "obudu"], "TN": ["sbeitla"], "CO": ["lajas"], "IL": ["hanikra"],
              "DZ": ["tassili"], "KE": ["lamu", "shela"], "PG": ["wilhelm", "highlands"],
              "RW": ["volcanoes", "kivu", "gisenyi", "kinigi"], "TG": ["koutammakou"],
              "VE": ["canaima", "roraima", "angel falls"], "BR": ["iguaz", "iguac", "iguass"]}
ZONE_POINTS = [("RW", -1.70, 29.26, "Gisenyi, on the DRC border"), ("RW", -1.43, 29.59, "Kinigi, Volcanoes National Park"),
               ("KE", -2.27, 40.90, "Lamu"), ("BR", -25.687, -54.445, "Iguazú Falls"), ("ET", 12.6075, 37.46, "Gondar"),
               ("ET", 14.13, 38.72, "Axum"), ("ET", 8.43, 38.62, "Tiya"), ("VE", 5.97, -62.54, "Angel Falls"),
               ("TG", 10.07, 1.13, "Koutammakou"), ("BJ", 10.81, 1.44, "Tanougou Falls")]
fold = g._fold


def in_zone(iso, spot):
    name = " %s " % re.sub(r"[^a-z0-9]+", " ", fold(spot["n"]))
    if any(re.search(r"\b%s" % re.escape(w), name) for w in ZONE_WORDS.get(iso, [])):
        return True
    return any(i == iso and g.geo.dist_km((spot["ll"][1], spot["ll"][0]), (lng, lat)) < 5
               for i, lat, lng, _ in ZONE_POINTS)


zoned = [(iso, s["n"]) for iso, spots in stays.items() for s in spots if in_zone(iso, s)]
results.append(ok(not zoned, "judged apart from the skip list, no chip in the file is in a zone (%s)" % zoned))
zoned = [(iso, s["n"]) for iso, spots in built.items() for s in spots if in_zone(iso, s)]
results.append(ok(not zoned, "nor any in a stubbed build of the zoned countries (%s)" % zoned))
results.append(ok(in_zone("RW", {"n": "Gisenyi Beach", "ll": [0, 0]}) and in_zone("BR", {"n": "x", "ll": [-25.69, -54.44]})
                  and not in_zone("RW", {"n": "Kigali", "ll": [-1.9525, 30.115]}), "and that judge works"))

p = g.prune({"ET": [{"n": "Lalibela", "ll": [12, 39]}],
             "BJ": [{"n": "Ouidah", "ll": [6.4, 2.1]}, {"n": "Pendjari National Park", "ll": [11, 1.5]}]})
results.append(ok(p == {"BJ": [{"n": "Ouidah", "ll": [6.4, 2.1]}]}, "--prune drops skipped places, and a country left with none"))

fp = g.fingerprint("Avoid all travel to the following areas: • Afar • Amhara")
results.append(ok(fp == g.fingerprint("Avoid all travel to the following areas:\n- Afar\n- Amhara.")
                  and fp != g.fingerprint("Avoid all travel to the following areas: • Afar • Tigray"),
                  "a fingerprint ignores layout and sees a changed word"))

# --check's review, on Benin's feed fixture (scripts/fixtures/gac, 2026-10-14)
# reviewed as it stands: the real list follows Canada's live feed, so it is
# not compared with a fixture's date.
with open(os.path.join(ROOT, "scripts", "fixtures", "gac", "bj.json"), encoding="utf-8") as fh:
    bj_blocks = watchouts.from_feed("BJ", json.load(fh))["regional"]
avoid = [b for b in bj_blocks if b["call"] == "Avoid all travel"]
seen = {"countries": {"BJ": {b["t"]: {"fp": g.fingerprint(b["text"]), "skip": {"Pendjari National Park": {}}} for b in avoid}}}
reworded = [dict(b, text=b["text"].replace("Pendjari", "Pendjari and Atacora")) for b in bj_blocks]
new = bj_blocks + [{"t": "Cotonou - Avoid all travel", "call": "Avoid all travel", "text": "Avoid all travel to Cotonou."}]
gone = [b for b in bj_blocks if b not in avoid]
results.append(ok(avoid and not g.review_problems("BJ", bj_blocks, skip=seen)
                  and any("reworded" in x for x in g.review_problems("BJ", reworded, skip=seen))
                  and any("new avoid-all block" in x and "Cotonou" in x for x in g.review_problems("BJ", new, skip=seen))
                  and any("gone" in x and "may be fine now" in x for x in g.review_problems("BJ", gone, skip=seen))
                  and not any("Avoid non-essential" in x for x in g.review_problems("BJ", bj_blocks, skip=seen)),
                  "--check passes the blocks as reviewed and flags a reworded, a new and a vanished avoid-all block"))

# A point of its own. A whole-degree point is a region's rough centre: within
# NEAR_KM of a border it may be either side (OSM puts (39, 68) in Uzbekistan's
# Surxondaryo), unless set by hand in stay-aliases.json.
results.append(ok(g.rough([39, 68]) and g.rough([-34, -58.28333]) and not g.rough([39.18333, 68.18333])
                  and not g.rough([10.5, -61.3]), "whole degrees are a rough centre; a decimal is not"))
results.append(ok(not g.in_country([39, 68], "TJ") and g.near_neighbour([39, 68], "TJ") == "UZ"
                  and g.in_country([39.18333, 68.18333], "TJ") and g.in_country([39, 68], "TJ", curated=True),
                  "the Fann Mountains' (39, 68) is not trusted in Tajikistan, its alias point is"))
results.append(ok(not g.in_country([-12, 34.5], "MW") and g.in_country([-24, 31.5], "ZA") and g.in_country([-51, -73], "CL"),
                  "Lake Malawi's (-12, 34.5) (Mozambican waters) is not trusted; Kruger's and Torres del Paine's, 28 km in, are"))
fann = next((s["ll"] for s in stays.get("TJ", []) if s["n"] == "Fann Mountains"), None)
results.append(ok(fann == g.ALIASES["TJ"]["Fann Mountains"]["ll"] and g.in_country(fann, "TJ"),
                  "Tajikistan's Fann Mountains chip is its alias point in Sughd (%s)" % fann))

trin = {"n": "Trinidad", "ll": [10.5, -61.3]}
cen = g._centroids()["TT"]
results.append(ok("same point as Trinidad" in (g.placeholder("TT", "Maracas Bay", [10.5, -61.3], [trin]) or "")
                  and "within 3 km of Trinidad" in (g.placeholder("TT", "Somewhere", [10.51, -61.31], [trin]) or "")
                  and "same place as Dahlak Islands" in (g.placeholder("ER", "Dahlak Islands Marine Park", [16.2, 40.0],
                                                                        [{"n": "Dahlak Islands", "ll": [15.83333, 40.2]}]) or "")
                  and "centre of the country" in (g.placeholder("TT", "Middle", [cen[1], cen[0]], []) or "")
                  and g.placeholder("TT", "Maracas Bay", [10.7658, -61.4345], [trin]) is None,
                  "a spot on another's point, within 3 km of one, the same place by name, or on the country's centre is left out"))

# The build, with Wikipedia stubbed: Maracas Bay's own lookup gives Trinidad's
# point, so without its alias it is left out; with it, it keeps its own.
real = g.coords_with_fallback
g.coords_with_fallback = lambda subject, country, iso: [10.5, -61.3] if subject in ("Trinidad", "Maracas Bay") else None
saved = g.ALIASES.get("TT")
try:
    with_alias = [s["n"] for s in g._build_country(("TT", acts["TT"], {}))[1]]
    g.ALIASES["TT"] = {k: v for k, v in saved.items() if k != "Maracas Bay"}
    without = [s["n"] for s in g._build_country(("TT", acts["TT"], {}))[1]]
finally:
    g.coords_with_fallback = real
    g.ALIASES["TT"] = saved
results.append(ok("Maracas Bay" in with_alias and "Maracas Bay" not in without and "Trinidad" in without,
                  "the build leaves out a borrowed point (Maracas Bay without its alias: %s)" % without))
real = g.coords_with_fallback
g.coords_with_fallback = lambda subject, country, iso: [15.83333, 40.2]
try:
    er = [s["n"] for s in g._build_country(("ER", {"activities": [{"t": "Diving (Dahlak Islands)"}],
                                                   "gallery": ["Dahlak Archipelago"]}, {}))[1]]
finally:
    g.coords_with_fallback = real
results.append(ok(er == ["Dahlak Islands"], "two names on one point are one chip (Eritrea: %s)" % er))

rows = g.check(stays)
hard = [r for r in rows if not r[3].startswith("within")]
results.append(ok(not hard, "every chip in the file is a sound point of its own country (%s)" % hard[:3]))
results.append(ok(not any(r[0] in ("TJ", "TT", "ER", "MW") for r in rows)
                  and len([s for s in stays["ER"] if "Dahlak" in s["n"]]) == 1
                  and [s["ll"] for s in stays["TT"] if s["n"] == "Maracas Bay"] != [[10.5, -61.3]],
                  "Fann Mountains, Maracas Bay, Dahlak and Lake Malawi are fixed"))
synthetic = {"TJ": [{"n": "Fann Mountains", "ll": [39, 68]}],
             "TT": [trin, {"n": "Maracas Bay", "ll": [10.5, -61.3]}],
             "ER": [{"n": "Dahlak Islands", "ll": [15.83333, 40.2]}, {"n": "Dahlak Archipelago", "ll": [15.83333, 40.2]}]}
whys = {(r[0], r[1]): r[3] for r in g.check(synthetic)}
results.append(ok("within 25 km of UZ" in whys.get(("TJ", "Fann Mountains"), "")
                  and "same point as Trinidad" in whys.get(("TT", "Maracas Bay"), "")
                  and "same point as Dahlak Islands" in whys.get(("ER", "Dahlak Archipelago"), "")
                  and ("TT", "Trinidad") not in whys and ("ER", "Dahlak Islands") not in whys,
                  "--check names each of the three as the audit found them (%s)" % whys))

# The US feed: its RSS, a level-2/3 row's regional "Do not travel" words up
# to the next tier or the staff rules; a level-4 row is the whole country.
rss = """<rss><channel>
<item><title>Rwanda - Level 3: Reconsider Travel</title><description><![CDATA[<p>Reconsider travel in Rwanda due to crime.</p>
<p><b>Do not travel</b> within 10 kilometers of Rwanda&rsquo;s border with the Democratic Republic of the Congo due to unrest .</p>]]></description></item>
<item><title>Chad - Level 4: Do Not Travel</title><description>Do not travel to Chad for any reason.</description></item>
<item><title>Benin - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in Benin. Do Not Travel to areas of Benin bordering Burkina Faso . U.S. government employee travel restrictions apply.</description></item>
<item><title>Cambodia - Level 2: Exercise Increased Caution</title><description>Do Not Travel to Areas along the Cambodian and Thai border due to unrest . Exercise Increased Caution in Phnom Penh due to crime .</description></item>
<item><title>Japan - Level 1: Exercise Normal Precautions</title><description>Exercise normal precautions in Japan.</description></item>
</channel></rss>"""
w = g.us_passages(rss)
results.append(ok(w == {"RW": "Do not travel within 10 kilometers of Rwanda\u2019s border with the Democratic Republic of the Congo due to unrest .",
                        "BJ": "Do Not Travel to areas of Benin bordering Burkina Faso .",
                        "KH": "Do Not Travel to Areas along the Cambodian and Thai border due to unrest ."},
                  "the US feed's \"Do not travel\" words, cut at the next tier or the staff rules; level 4 left out (%s)" % w))
seen_us = {"us": {"countries": {"RW": {"fp": g.fingerprint(w["RW"]), "skip": {"Lake Kivu": {}}},
                                "TD": {"fp": "000000000000"}}}}
results.append(ok(not g.us_review_problems("RW", w["RW"], skip=seen_us)
                  and any("reworded" in x for x in g.us_review_problems("RW", w["RW"].replace("10 kilometers", "20 kilometers"), skip=seen_us))
                  and any("new US" in x for x in g.us_review_problems("BJ", w["BJ"], skip=seen_us))
                  and any("gone" in x and "may be fine now" in x for x in g.us_review_problems("RW", "", skip=seen_us))
                  and not g.us_review_problems("JP", "", skip=seen_us),
                  "--check passes the US words as reviewed and flags new, reworded and gone ones"))

# A row that says some areas have increased risk and names none in the feed
# (Mexico's, India's) is reviewed by hand on travel.state.gov: its whole text
# is fingerprinted, so a reissue asks again. A row naming its areas at a lower
# tier only (Tanzania's "Reconsider travel to") has no "Do not travel" list. A
# title the name map misses is reported, not dropped.
rss2 = """<rss><channel>
<item><title>Mexico Travel Advisory - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in Mexico due to terrorism, crime, and kidnapping. Some areas have increased risk. Read the entire Travel Advisory. Check the maps of restricted areas .</description></item>
<item><title>Tanzania - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in Tanzania due to crime. Some areas have increased risk. Reconsider travel to the border between Tanzania and Mozambique in the Mtwara Region due to terrorism.</description></item>
<item><title>C&#244;te d&#8217;Ivoire - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in C&#244;te d&#8217;Ivoire due to crime. Some areas have increased risk. Read the entire Travel Advisory.</description></item>
<item><title>Republic of Congo - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in the Republic of the Congo due to crime. Do not travel within 50 km of the border with the Central African Republic.</description></item>
<item><title>Atlantis - Level 2: Exercise Increased Caution</title><description>Exercise increased caution in Atlantis. Do not travel to the northern reefs.</description></item>
<item><title>Japan - Level 1: Exercise Normal Precautions</title><description>Exercise normal precautions in Japan.</description></item>
</channel></rss>"""
w2 = g.us_passages(rss2)
results.append(ok(sorted(w2) == ["CG", "CI", "MX"] and w2["MX"].startswith(g.US_UNLISTED) and w2["CI"].startswith(g.US_UNLISTED)
                  and w2["CG"].startswith("Do not travel within 50 km") and g.us_unmapped(rss2) == ["Atlantis"],
                  "a row naming no area is kept for review, Tanzania's lower tier is not a list, \"Côte d’Ivoire\" and"
                  " \"Republic of Congo\" map, and an unknown title is reported (%s; %s)" % (sorted(w2), g.us_unmapped(rss2))))
seen_mx = {"us": {"countries": {"MX": {"fp": g.fingerprint(w2["MX"]), "note": "reviewed"}}}}
results.append(ok(not g.us_review_problems("MX", w2["MX"], skip=seen_mx)
                  and any("reissued" in x for x in g.us_review_problems("MX", w2["MX"].replace("terrorism, ", ""), skip=seen_mx))
                  and any("not reviewed" in x and "travel.state.gov" in x
                          for x in g.us_review_problems("MX", w2["MX"], skip={"us": {"countries": {}}})),
                  "--check asks for travel.state.gov on an unreviewed unlisted row, passes it reviewed, asks again at a reissue"))
unlisted_rows = ("MX", "IN", "CI", "MA", "MG", "CY", "KG", "CV")
results.append(ok(all(us_countries.get(iso, {}).get("note") and re.fullmatch(r"[0-9a-f]{12}", us_countries[iso].get("fp", ""))
                      for iso in unlisted_rows)
                  and "Guerrero" in us_countries["MX"]["note"] and "Kashmir" in us_countries["IN"]["note"],
                  "Mexico's, India's and the other unlisted rows with chips are reviewed, each with a note"))
br = us_countries.get("BR") or {}
results.append(ok("Iguazú Falls" in (br.get("skip") or {}) and "International land borders" in br["skip"]["Iguazú Falls"]["us"]
                  and "staff" in br.get("note", "") and not any("Igua" in s["n"] for s in stays["BR"])
                  and [s["n"] for s in stays["BR"]][:3] == ["Rio de Janeiro", "Salvador", "Manaus"],
                  "Brazil's Iguazú Falls is out under the US's land borders, the staff-only Foz exception noted (%s)"
                  % [s["n"] for s in stays["BR"]]))
amo = next((s["ll"] for s in stays["MR"] if s["n"] == "Amojjar Pass"), None)
faz = next((s["ll"] for s in stays["TG"] if s["n"] == "Fazao-Malfakassa National Park"), None)
results.append(ok(amo == [20.53933, -12.79186] and faz == [8.76571, 0.76086],
                  "Amojjar Pass is OSM's Passe d'Amogjar and Fazao-Malfakassa the park's OSM centre (%s, %s)" % (amo, faz)))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
