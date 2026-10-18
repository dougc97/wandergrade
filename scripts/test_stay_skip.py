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
    "Limbe");
  * a point of its own: a whole-degree point near a border is not trusted
    (the Fann Mountains' (39, 68) is in Uzbekistan) unless curated; a spot on
    another spot's very point (Maracas Bay on Trinidad's), within 3 km of
    one, or on the country's centre is left out, at build and in --check;
    the file has no such spot left but the listed pre-rule landmarks;
  * a fingerprint ignores layout (bullets, spacing, punctuation) and sees a
    changed word; --check's review, on Benin's feed fixture, passes the
    blocks as reviewed and flags one that is new, gone or reworded; the US
    feed's "Do not travel" words are read from its RSS (level 4 left to
    app.js) and reviewed the same way.
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
          ("TG", "Koutammakou", "Koutammakou"), ("VE", "Canaima", "Canaima National Park"), ("VE", "Roraima", "Mount Roraima")]
for iso, place, alias in NEW_CANADA:
    results.append(ok(g.skipped(iso, place, skip=canada_only) == place and g.skipped(iso, alias) == place,
                      "%s %s is in Canada's avoid-all zone (also as \"%s\")" % (iso, place, alias)))
for iso, place, alias in NEW_US:
    results.append(ok(g.skipped(iso, place, skip=canada_only) is None and g.skipped(iso, place, skip=us_only) == place
                      and g.skipped(iso, alias) == place,
                      "%s %s is in a US \"Do not travel\" area, not Canada's (also as \"%s\")" % (iso, place, alias)))
keep = [("ET", "Bale Mountains National Park"), ("ET", "Sanetti Plateau"), ("CM", "Foumban"), ("CM", "Bandjoun"),
        ("MR", "Terjit"), ("MR", "Amojjar Pass"), ("BJ", "Porto-Novo"), ("PG", "Mount Hagen"), ("RW", "Kigali"),
        ("RW", "Lake Burera"), ("RW", "Nyungwe"), ("BI", "Bujumbura"), ("BR", "Iguazú Falls"), ("TG", "Fazao-Malfakassa National Park"),
        ("VE", "Los Roques"), ("VE", "Médanos de Coro"), ("KE", "Ruins of Gedi"), ("IL", "Masada"), ("DZ", "Djémila")]
left_in = [(iso, n) for iso, n in keep if g.skipped(iso, n)]
results.append(ok(not left_in, "and the places beside them stay: the US exempts Bale Mountains and the town of Mount Hagen;"
                               " Foumban, Terjit, Porto-Novo, Nyungwe... are clear of both (%s)" % left_in))

# The generator itself, with Wikipedia stubbed: every candidate gets its own
# in-country point, so only the skip list can keep one out.
real = g.coords_with_fallback
pts = {}
g.coords_with_fallback = lambda subject, country, iso: pts.setdefault(subject, [1.0 + len(pts), 1.0])
try:
    with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
        acts = json.load(f)
    built = {iso: g._build_country((iso, acts[iso], {}))[1]
             for iso in ("BJ", "CM", "ET", "TD", "MZ", "MR", "NG", "RW", "PG", "TG", "VE", "DZ", "KE", "TN", "CO", "IL")}
finally:
    g.coords_with_fallback = real
bad = [(iso, s["n"]) for iso, spots in built.items() for s in spots if g.skipped(iso, s["n"])]
results.append(ok(not bad, "the generator adds no skipped place (%s)" % bad[:3]))
results.append(ok(all(built[iso] for iso in built), "and still finds places outside the zones (%s)"
                  % {iso: [s["n"] for s in spots] for iso, spots in built.items()}))

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

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
