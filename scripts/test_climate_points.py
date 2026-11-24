"""Where climate.json's weather is measured (fxtracker/build_climate.py
SAMPLE_POINTS), offline: no network.

    /usr/bin/python3 scripts/test_climate_points.py

What it holds the data to (review 2026-11-23 item 1, with the month tables on
every guide, item 19):
  * every country that can get a month table (render_guide.month_table: a
    full twelve months of scores, temps and rain, scores not flat) has a
    named point in SAMPLE_POINTS, or is in LEFT_ALONE with a reason (Costa
    Rica); each point carries a place and a short reason;
  * climate.json's "at" is that place for every named country, and absent
    for LEFT_ALONE ones (the caption then says "one representative point",
    never a guessed city);
  * every point sits on its own country's land (or within MAX_OFFSHORE_KM of
    the simplified coast; OFF_MAP_KM for the islands the map leaves out and
    Livingstone, which it draws inside Zimbabwe),
    so a typo'd coordinate can't sample the sea or a neighbour;
  * every month-table row carries its point's elevation ("elev"), and every
    row the build warns about (above HIGH_M or best month under LOW_BEST) is
    in REVIEWED with why it stands — and REVIEWED lists nothing else; no row
    warns about its rain (over RAIN_RATIO from the station's either way, or
    not the station's where STATION_RAIN gives one: those are fixed in
    STATION_RAIN, never excused, so no REVIEWED reason speaks of rain; the
    station table itself is scripts/test_station_rain.py's);
  * the points the review measured as wrong now read like the places
    visitors go: the Dominican Republic's January is beach-warm, not 18°C;
    Switzerland's July isn't 13°C; Timor-Leste is Dili-hot; Bhutan's best
    month, with Paro's own rain (2026-11-24), scores over 80, not 35 or 59;
  * the 2026-07 points re-judged by the same rule (review of batch B,
    2026-11-24): Indonesia at Bali, not Jakarta; Fiji at Nadi, not wet Suva;
    Croatia on the Dalmatian coast (Split), not Zagreb; Mexico at Cancún and
    Colombia at Cartagena, not at 2,200-2,600 m; Cabo Verde on Sal, not
    Praia; and no REVIEWED reason leans on curated best months, which don't
    take a point out of the Weather grade (picks._score and app.js
    valueScores read the scores either way).
"""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import build_climate as bc, geo  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
CLIM = json.load(open(os.path.join(ROOT, "public", "climate.json"), encoding="utf-8"))
WORLD = json.load(open(os.path.join(ROOT, "public", "world.geojson"), encoding="utf-8"))
FEATS = {f["properties"]["iso"]: f for f in WORLD["features"] if f["properties"].get("iso")
         and not (f["properties"].get("sub") and f["properties"]["sub"] == f["properties"]["iso"])}


def table_eligible(row):
    """render_guide.month_table's data rule (rain days may be absent: a
    station's rain without comparable days)."""
    cols = [row.get(k) or [] for k in ("scores", "temps", "rain_mm")]
    days = row.get("rain_days")
    return (all(len(x) == 12 and None not in x for x in cols) and len(set(cols[0])) >= 2
            and (days is None or (len(days) == 12 and None not in days)))


ELIGIBLE = sorted(iso for iso, r in CLIM.items() if table_eligible(r))
SP, LA = bc.SAMPLE_POINTS, bc.LEFT_ALONE

missing = [i for i in ELIGIBLE if i not in SP and i not in LA]
results.append(ok(not missing and len(ELIGIBLE) >= 180,
                  "all %d month-table countries have a named point or a LEFT_ALONE reason%s"
                  % (len(ELIGIBLE), (": missing " + " ".join(missing)) if missing else "")))
results.append(ok(set(LA) == {"CR"} and all(LA.values()),
                  "LEFT_ALONE is Costa Rica alone, with its reason (review 2026-11-23)"))
bad_shape = [i for i, v in SP.items() if len(v) != 4 or not isinstance(v[2], str) or not v[2].strip()
             or not isinstance(v[3], str) or len(v[3].strip()) < 5]
results.append(ok(not bad_shape, "every point is (lat, lon, place, reason) with both words filled in%s"
                  % (": " + " ".join(bad_shape) if bad_shape else "")))
both = sorted(set(SP) & set(LA))
results.append(ok(not both, "no country is both named and left alone"))

wrong_at = [i for i in SP if i in CLIM and table_eligible(CLIM[i]) and CLIM[i].get("at") != SP[i][2]]
results.append(ok(not wrong_at, "climate.json names each country's place (\"at\" = SAMPLE_POINTS place)%s"
                  % (": " + " ".join("%s=%r" % (i, CLIM[i].get("at")) for i in wrong_at) if wrong_at else "")))
results.append(ok(all("at" not in CLIM[i] for i in LA if i in CLIM),
                  "LEFT_ALONE rows name no place (the caption says one representative point)"))

off = []
for iso, (lat, lon, _p, _w) in SP.items():
    f = FEATS.get(iso)
    if not f:
        off.append(iso + " (not on the map)")
        continue
    if bc.sample_point(iso, f["geometry"]) != (lon, lat):
        off.append(iso)
results.append(ok(not off, "every named point is accepted as on its own land (sample_point keeps it)%s"
                  % (": " + " ".join(off) if off else "")))
results.append(ok(all(i in SP for i in bc.OFF_MAP) and all(bc.OFF_MAP.values()),
                  "OFF_MAP (places the simplified map leaves out or misdraws) only widens named points, each with why"))
# A typo that lands on another continent still fails, even with OFF_MAP's wider margin.
was = SP["HN"]
SP["HN"] = (was[0], was[1] + 20, was[2], was[3])
results.append(ok(bc.sample_point("HN", FEATS["HN"]["geometry"]) != (was[1] + 20, was[0]),
                  "a typo'd off-map point (Roatán 20° east, in the Atlantic) is rejected"))
SP["HN"] = was

no_elev = [i for i in ELIGIBLE if not isinstance(CLIM[i].get("elev"), int)]
results.append(ok(not no_elev, "every month-table row carries its point's elevation%s"
                  % (": " + " ".join(no_elev) if no_elev else "")))
warned = sorted(i for i in ELIGIBLE if bc.point_warnings(CLIM[i], i))
unreviewed = [i for i in warned if not bc.REVIEWED.get(i)]
results.append(ok(not unreviewed, "every warned point (over %d m, or best month under %d) is reviewed by hand%s"
                  % (bc.HIGH_M, bc.LOW_BEST, (": " + ", ".join(
                      "%s %s" % (i, "; ".join(bc.point_warnings(CLIM[i], i))) for i in unreviewed)) if unreviewed else "")))
stale = sorted(set(bc.REVIEWED) - set(warned))
results.append(ok(not stale, "REVIEWED lists only points the build still warns about%s"
                  % (": " + " ".join(stale) if stale else "")))
results.append(ok(bc.point_warnings({"elev": 801, "scores": [59] * 12}) == [
    "point at 801 m (over 800 m)", "best month scores 59 (under 60)"]
    and bc.point_warnings({"elev": 800, "scores": [60] + [0] * 11}) == [],
    "point_warnings: over 800 m and under 60 warn, 800 m and 60 don't"))
# Rain against the places' own records (2026-11-24): no row warns about it, a row
# that stops matching its station would, and REVIEWED never excuses rain.
rain_warned = sorted(i for i in ELIGIBLE if any(w.startswith("rain") for w in bc.point_warnings(CLIM[i], i)))
fake_bt = dict(CLIM["BT"]); fake_bt.pop("rain_src")
fr2 = dict(CLIM["FR"], rain_mm=[round(bc.RAIN_REF["FR"][0] * 1.6 / 12)] * 12)
fr1 = dict(CLIM["FR"], rain_mm=[round(bc.RAIN_REF["FR"][0] * 1.45 / 12)] * 12)
gone = dict(CLIM["FR"], rain_src="Paris station normals 1991–2020")
results.append(ok(not rain_warned
                  and any("STATION_RAIN" in w for w in bc.point_warnings(fake_bt, "BT"))
                  and any(w.startswith("rain %d mm a year, 1.6" % sum(fr2["rain_mm"])) for w in bc.point_warnings(fr2, "FR"))
                  and not bc.point_warnings(fr1, "FR")
                  and any("no longer lists" in w for w in bc.point_warnings(gone, "FR"))
                  and bc.point_warnings({"rain_mm": [400] * 12}) == []
                  and not [i for i, w in bc.REVIEWED.items() if "rain" in w.lower()]
                  and not hasattr(bc, "rain_doubtful"),
                  "no month-table row's rain is over %g times from its station's (%s); Paro without its station rain "
                  "warns, Paris at 1.6 times its record warns and at 1.45 doesn't, a station source STATION_RAIN "
                  "dropped warns; no REVIEWED reason excuses rain" % (bc.RAIN_RATIO, rain_warned or "none")))

# The readings the review called out (2026-11-23), now from the named places.
c = CLIM
results.append(ok(c["DO"]["at"] == "Punta Cana" and c["DO"]["temps"][0] >= 23,
                  "Dominican Republic: January %d°C at %s (was 18°C in the mountains)"
                  % (c["DO"]["temps"][0], c["DO"]["at"])))
results.append(ok(c["CH"]["temps"][6] >= 17, "Switzerland: July %d°C at %s (was 13°C in the Alps)"
                  % (c["CH"]["temps"][6], c["CH"]["at"])))
results.append(ok(min(c["TL"]["temps"]) >= 24, "Timor-Leste: coolest month %d°C at %s (was 18°C)"
                  % (min(c["TL"]["temps"]), c["TL"]["at"])))
results.append(ok(max(c["BT"]["scores"]) >= 80 and c["BT"]["rain_src"].startswith("Paro station")
                  and "BT" in bc.REVIEWED and not any(w.startswith("best") for w in bc.point_warnings(c["BT"], "BT")),
                  "Bhutan: best month scores %d at %s with Paro's own rain (was 35 at the old point, 59 with the "
                  "reanalysis rain), best %s; only its height warns" % (max(c["BT"]["scores"]), c["BT"]["at"],
                                                                       c["BT"]["best"])))
results.append(ok(max(c["TW"]["temps"]) >= 28 and c["SE"]["temps"][0] > -5,
                  "Taipei summers reach %d°C; Stockholm's January is %d°C (was −7°C)"
                  % (max(c["TW"]["temps"]), c["SE"]["temps"][0])))

# The 2026-07 points, re-judged by the rule (review of batch B, 2026-11-24).
moved = {"ID": "Denpasar, Bali", "FJ": "Nadi", "HR": "Split", "MX": "Cancún", "CO": "Cartagena",
         "CV": "Santa Maria, Sal"}
results.append(ok(all(c[i]["at"] == p and c[i]["elev"] < 100 for i, p in moved.items()),
                  "re-judged 2026-07 points sit where visitors go, near sea level: %s"
                  % ", ".join("%s %s (%d m)" % (i, c[i]["at"], c[i]["elev"]) for i in moved)))
results.append(ok(min(c["MX"]["temps"]) >= 22 and min(c["CO"]["temps"]) >= 25 and c["HR"]["temps"][6] >= 25
                  and max(c["ID"]["scores"][6:9]) >= 85 and max(c["FJ"]["scores"][5:9]) >= 85,
                  "Cancún's coolest month is %d°C (Mexico City read 15°C), Cartagena's %d°C (Bogotá 13°C); Split's "
                  "July %d°C; Bali's best dry-season month scores %d (Jakarta 75), Nadi's %d (Suva 82)"
                  % (min(c["MX"]["temps"]), min(c["CO"]["temps"]), c["HR"]["temps"][6],
                     max(c["ID"]["scores"][6:9]), max(c["FJ"]["scores"][5:9]))))
results.append(ok(not [i for i, w in bc.REVIEWED.items() if "curated" in w],
                  "no REVIEWED reason excuses a point by its curated best months (the scores still grade Weather)"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
