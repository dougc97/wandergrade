"""The stays skip list (scripts/stay-skip.json) and the spots it guards,
without the network.

    /usr/bin/python3 scripts/test_stay_skip.py

  * stay-skip.json is dated and holds, per country, Canada's "Avoid all
    travel" blocks by heading, each with a fingerprint of its words; every
    skipped place says where it falls and quotes Canada's words for it;
  * no anchor in public/stay-coords.json is a skipped place, and the guide's
    served stays stand-in follows (Ethiopia none, Cameroon near Kribi alone,
    Benin without Pendjari);
  * the generator never adds a skipped place, under any of its names (an
    activity's "Pendjari" is the chip "Pendjari National Park"; "Limbé" is
    "Limbe"), and skips nothing else: Kribi, Zakouma, Chinguetti and
    Tanougou Falls (in Atacora's non-essential band, not its avoid-all one)
    stay;
  * a fingerprint ignores layout (bullets, spacing, punctuation) and sees a
    changed word; --check's review, on Benin's feed fixture, passes the
    blocks as reviewed and flags one that is new, gone or reworded.
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

with open(os.path.join(ROOT, "public", "stay-coords.json"), encoding="utf-8") as f:
    stays = json.load(f)
left = g.skipped_present(stays)
results.append(ok(not left, "no stay anchor is a skipped place (%s)" % left[:3]))
results.append(ok(guide_sizers.stay("ET") == "", "Ethiopia serves no stays stand-in (all four spots are in Amhara or Afar)"))
cm = guide_sizers.stay("CM")
results.append(ok("near Kribi" in cm and "staychip" not in cm, "Cameroon's stand-in is Kribi alone, no chips"))
bj = guide_sizers.stay("BJ")
results.append(ok("Pendjari" not in bj and "Ganvié" in bj, "Benin's stand-in keeps Ganvié, Ouidah, Abomey, not Pendjari"))

results.append(ok(g.skipped("BJ", "Pendjari") == "Pendjari National Park", "an activity's short name is the skipped chip"))
results.append(ok(g.skipped("CM", "Limbé") == "Limbe", "accents don't hide a skipped place"))
results.append(ok(g.skipped("BJ", "Ganvié") is None and g.skipped("CM", "Kribi") is None
                  and g.skipped("TD", "Zakouma") is None and g.skipped("MR", "Chinguetti") is None
                  and g.skipped("BJ", "Tanougou Falls") is None, "nothing outside the zones is skipped"))
results.append(ok(g.skipped("KE", "Lalibela") is None, "a skip is for its own country only"))

# The generator itself, with Wikipedia stubbed: every candidate gets its own
# in-country point, so only the skip list can keep one out.
real = g.coords_with_fallback
pts = {}
g.coords_with_fallback = lambda subject, country, iso: pts.setdefault(subject, [1.0 + len(pts), 1.0])
try:
    with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
        acts = json.load(f)
    built = {iso: g._build_country((iso, acts[iso], {}))[1] for iso in ("BJ", "CM", "ET", "TD", "MZ", "MR")}
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

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
