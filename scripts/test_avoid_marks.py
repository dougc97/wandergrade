#!/usr/bin/env python3
"""The guide's avoid-zone markers: Global Affairs Canada's own words in an ⓘ
beside a place inside one of its "Avoid all travel" zones
(fxtracker/avoid_marks.py), without the network or a server process.

    /usr/bin/python3 scripts/test_avoid_marks.py

  * the table (scripts/stay-skip.json "marks") against its own blocks: every
    mark names a block the table holds, under that country, and carries that
    block's fingerprint; every mark is a place in an avoid-all block, class A
    or A~ (Zuma Rock's A* is Doug's call), on an item activities.json has
    once, dated, with Canada's words; none in the 22 guides Canada says to
    avoid entirely; Ethiopia, Chad, Cameroon and Tajikistan are marked; no
    summary line is;
  * the words are Canada's: each mark's words are in its block, verbatim and
    in order, in Canada's feed of the day they were checked
    (scripts/fixtures/gac-2026-10-30), at the fingerprint the mark carries;
    and watchouts.from_feed gives every block that fingerprint ("fp", what
    /api/watchouts serves for the page's own check);
  * public/avoid-marks.json is exactly what the table builds;
  * the wording: always "Global Affairs Canada: “…” (travel.gc.ca, checked
    YYYY-MM-DD)", Saudi Arabia's two blocks in one marker;
  * the markup: render_guide's crawler block and app.js renderActivity (run
    under jsc, scripts/appjs_harness.js) write the same markers, character
    for character, for every marked guide — with no Canada answer, with
    Canada's real answer of 2026-10-30, a failed answer, and answers showing
    the blocks reworded or gone (each marker then stays, invisible), Saudi
    Arabia with one of its two blocks reworded; each marker after its
    item's label, none in an unmarked guide; the crawler block's copy is
    unseen (display: none, its no-break space inside), so that block is
    exactly as long as before; the ⓘ is the guide's
    (.muted[data-tip], title=""), so app.js gives it its Tab stop, name and
    tap; app.js loads the marks with the guide's own data and the server
    hands its render Canada's cached notes;
  * gen_stay_spots.py --check: its marks review passes the table on the
    2026-10-30 feed and flags a mark whose block is reworded or gone, whose
    words left the block, or whose fp is not its block's; its Canada review
    covers the marked guides whatever the stays.
"""
import copy
import html
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from fxtracker import avoid_marks as AM, render_guide as rg, watchouts  # noqa: E402

spec = importlib.util.spec_from_file_location("gen_stay_spots", os.path.join(ROOT, "scripts", "gen_stay_spots.py"))
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
load = lambda *a: json.load(open(P(*a), encoding="utf-8"))
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()
FIXDIR = P("scripts", "fixtures", "gac-2026-10-30")

table = load("scripts", "stay-skip.json")
acts = load("public", "activities.json")
blocks = table.get("countries") or {}
rows = AM.rows(table)
marked = sorted({iso for iso, _ in rows})
lab = lambda x: x.get("t") if isinstance(x, dict) else x

# --- the table against its own blocks ------------------------------------------------
results.append(ok(len(rows) >= 20 and (table.get("marks") or {}).get("about"),
                  "stay-skip.json holds %d marks in %d guides, with what they are" % (len(rows), len(marked))))
nofp = [(iso, r.get("item")) for iso, r in rows if (blocks.get(iso) or {}).get(r.get("block"), {}).get("fp") is None]
results.append(ok(not nofp, "every mark's block is in the table under its country (missing: %s)" % nofp))
fpbad = [(iso, r.get("item"), r.get("fp")) for iso, r in rows
         if r.get("fp") != (blocks.get(iso) or {}).get(r.get("block"), {}).get("fp")]
all_fps = {b["fp"] for bs in blocks.values() for b in bs.values()}
results.append(ok(not fpbad and all(r.get("fp") in all_fps for _, r in rows),
                  "every mark's fp is its block's fingerprint in the table's block list (wrong: %s)" % fpbad))
results.append(ok(all(r["block"].lower().endswith(" - avoid all travel") for _, r in rows),
                  "every mark is under a Canada \"Avoid all travel\" block"))
results.append(ok(all(r.get("cls") in AM.CLASSES for _, r in rows),
                  "only class A and A~ rows are marked (%s)" % sorted({r.get("cls") for _, r in rows})))
results.append(ok(not set(marked) & set(AM.WHOLE_COUNTRY) and len(AM.WHOLE_COUNTRY) == 22,
                  "none in the 22 guides Canada says to avoid entirely (%s)" % sorted(set(marked) & set(AM.WHOLE_COUNTRY))))
results.append(ok({"ET", "TD", "CM", "TJ"} <= set(marked), "Ethiopia, Chad, Cameroon and Tajikistan keep their places, marked"))
results.append(ok("NG" not in marked and not any("zuma" in (r.get("place", "") + r["item"]).lower() for _, r in rows),
                  "Zuma Rock (A*, Doug's call) is not marked"))
results.append(ok(all(r.get("surface") in AM.SURFACES for _, r in rows), "no summary line is marked: activities and season rows only"))


def items(iso, surface):
    a = acts.get(iso) or {}
    return [lab(x) for x in a.get("activities") or []] if surface == "activity" else [s.get("what") for s in a.get("seasonal") or []]


missing = [(iso, r["surface"], r["item"]) for iso, r in rows if items(iso, r["surface"]).count(r["item"]) != 1]
results.append(ok(not missing, "every marked item is in activities.json once, as labelled (missing: %s)" % missing))
results.append(ok(all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", r.get("checked") or "") and r.get("words") and r.get("place")
                      and re.fullmatch(r"[0-9a-f]{12}", r.get("fp") or "") for _, r in rows),
                  "every mark has its place, Canada's words, a fingerprint and the day it was checked"))
dups = [k for k in {(iso, r["surface"], r["item"], r["block"]) for iso, r in rows}
        if sum((i, r["surface"], r["item"], r["block"]) == k for i, r in rows) > 1]
results.append(ok(not dups, "no mark twice (%s)" % dups))

# --- the words are Canada's --------------------------------------------------------------
fix_blocks = {}
for iso in marked:
    with open(os.path.join(FIXDIR, iso.lower() + ".json"), encoding="utf-8") as f:
        fix_blocks[iso] = watchouts.from_feed(iso, json.load(f))["regional"]
et_north = next(b["text"] for b in fix_blocks["ET"] if b["t"] == "Northern regions - Avoid all travel")
results.append(ok(all(b.get("fp") == watchouts.fingerprint(b["text"]) for bs in fix_blocks.values() for b in bs)
                  and watchouts.fingerprint(et_north) == blocks["ET"]["Northern regions - Avoid all travel"]["fp"]
                  and g.fingerprint(et_north) == watchouts.fingerprint(et_north)
                  and g.fingerprint("a • b") == watchouts.fingerprint("a\n- b."),
                  "watchouts.from_feed gives every block its fingerprint (gen_stay_spots' own, one implementation)"))
# A row checked on the fixtures' day is held to them; one re-checked later
# (against a block reworded since) is --check's, on the live feed.
FIXDAY = "2026-10-30"
verbatim, later, wrong = [], [], []
for iso, r in rows:
    b = next((x for x in fix_blocks[iso] if x["t"] == r["block"]), None)
    if r["checked"] > FIXDAY:
        later.append((iso, r["item"]))
    elif b and b["fp"] == r["fp"] and g.quoted(r["words"], b["text"]):
        verbatim.append((iso, r["item"]))
    else:
        wrong.append((iso, r["item"]))
results.append(ok(not wrong and verbatim,
                  "%d of %d marks' words are in their block verbatim, in order, in Canada's feed of %s at the"
                  " fingerprint they carry (checked since: %s; wrong: %s)" % (len(verbatim), len(rows), FIXDAY, later, wrong)))

# --- the client's copy ---------------------------------------------------------------------
with open(AM.OUT, encoding="utf-8") as f:
    shipped = f.read()
data = AM.build(table)
results.append(ok(shipped == AM.dump(data), "public/avoid-marks.json is what stay-skip.json builds"
                  " (else: /usr/bin/python3 -m fxtracker.avoid_marks)"))
results.append(ok(sum(len(v) for v in data["countries"].values()) == len(rows) - 1
                  and [len(e["q"]) for e in data["countries"]["SA"]] == [2],
                  "%d markers: one per item, Saudi Arabia's Empty Quarter one marker for its two blocks"
                  % sum(len(v) for v in data["countries"].values())))

# --- the notes the markers are drawn with ---------------------------------------------------
LIVE = {iso: {"iso": iso, "source": "Global Affairs Canada", "link": "https://travel.gc.ca/destinations/x",
              "watchouts": [], "regional": bs} for iso, bs in fix_blocks.items()}


def changed(notes, drop=False, only=None):
    """Canada's answer with each marked block (or only `only`) reworded, or gone."""
    n = copy.deepcopy(notes)
    heads = {r["block"] for i, r in rows if i == n["iso"]}
    keep = []
    for b in n["regional"]:
        if b["t"] in heads and (only is None or b["t"] == only):
            if drop:
                continue
            b["text"] += " Updated."
            b["fp"] = watchouts.fingerprint(b["text"])
        keep.append(b)
    n["regional"] = keep
    return n


STATES = {
    "cold": {iso: None for iso in marked},
    "live": LIVE,
    "failed": {iso: {"iso": iso, "watchouts": [], "regional": [], "link": ""} for iso in marked},
    "reworded": {iso: changed(LIVE[iso]) for iso in marked},
    "gone": {iso: changed(LIVE[iso], drop=True) for iso in marked},
    "sa-yemen": dict(LIVE, SA=changed(LIVE["SA"], only="Border with Yemen - Avoid all travel")),
}
FRESH = ("cold", "live", "failed")
results.append(ok(all(AM.live(q, LIVE[iso]) for iso in marked for e in data["countries"][iso] for q in e["q"])
                  and not any(AM.live(q, STATES[s][iso]) for s in ("reworded", "gone")
                              for iso in marked for e in data["countries"][iso] for q in e["q"])
                  and AM.live({"b": "x", "fp": "0"}, None) and AM.live({"b": "x", "fp": "0"}, STATES["failed"]["ET"])
                  and AM.live({"b": "x", "fp": "0"}, {"link": "y", "regional": [{"t": "x"}]}),
                  "a quote stands with no answer, a failed one or a block without an fp, and with Canada's real"
                  " 2026-10-30 answer; it drops where the answer shows its block reworded or gone"))

# --- the wording --------------------------------------------------------------------------------
TIP = re.compile(r'data-tip="([^"]*)"')
WORDS = re.compile(r"^Global Affairs Canada: “.+” \(travel\.gc\.ca, checked (\d{4}-\d{2}-\d{2})\)$", re.S)
tips = {(iso, k): html.unescape(TIP.search(AM.span(iso, k, None, data)).group(1))
        for iso in marked for k in range(len(data["countries"][iso]))}
results.append(ok(all(WORDS.match(t) for t in tips.values()),
                  "every marker reads \"Global Affairs Canada: “…” (travel.gc.ca, checked YYYY-MM-DD)\" (%s)"
                  % [k for k, t in tips.items() if not WORDS.match(t)]))
results.append(ok(all(r["words"] in tips[(iso, next(k for k, e in enumerate(data["countries"][iso])
                                                     if e["s"] == r["surface"] and e["i"] == r["item"]))]
                      for iso, r in rows),
                  "each marker holds its marks' words whole"))
sa = tips[("SA", 0)]
results.append(ok(sa.count("“") == 2 and "Asir, Jazan and Najran" in sa and "30 km of the border with Yemen" in sa,
                  "Saudi Arabia's Empty Quarter quotes both of its blocks in one marker"))
sa_one = html.unescape(TIP.search(AM.span("SA", 0, STATES["sa-yemen"]["SA"], data)).group(1))
results.append(ok(sa_one.count("“") == 1 and "Asir" in sa_one and "Yemen" not in sa_one,
                  "with its Yemen block reworded, it quotes only the Asir block"))
st = AM.span("ET", 0, STATES["reworded"]["ET"], data)
results.append(ok(st == '<span class="muted zonemark stale" data-zm="0" aria-hidden="true">&nbsp;ⓘ</span>',
                  "a marker whose every quote is stale stays in place, unseen, with nothing to say"))
mk = AM.html("ET", "activity", "Rock churches (Lalibela)", None, data)
results.append(ok(mk.startswith('<span class="muted zonemark" data-zm="0" data-tip="Global Affairs Canada: “Avoid all')
                  and mk.endswith('(travel.gc.ca, checked 2026-10-30)" title="">&nbsp;ⓘ</span>')
                  and not re.search(r'class="[^"]*\badv', mk),
                  "the guide's ⓘ: .muted[data-tip], title=\"\", held to the label's last word; no adv* class"))
results.append(ok(all(x in APP for x in ('".muted[data-tip]"', 'closest(".hzmark, .muted[data-tip]'))
                  and 'el.setAttribute("aria-label", "More info")' in APP,
                  "app.js makes such an ⓘ a Tab stop named \"More info\" and shows its tip on a tap"))

# --- the crawler block and the client draw the same markers ----------------------------------------
MARK = re.compile(r'<span class="muted zonemark[^"]*" data-zm="\d+"[^>]*>&nbsp;ⓘ</span>')


def ssr(iso, notes):
    return rg.render(iso, notes=notes)["body"]


DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
activities = FIX.acts; avoidMarks = FIX.marks;
const out = { snip: {}, act: {}, plain: "" };
for (const s in FIX.states) {
  out.snip[s] = {}; out.act[s] = {};
  for (const iso of FIX.isos) {
    const w = FIX.states[s][iso];
    if (w) _watchoutCache[iso] = w; else delete _watchoutCache[iso];
    out.snip[s][iso] = avoidMarks.countries[iso].map((e) => zoneMarkHTML(iso, e.s, e.i, w));
    ccGuideIso = iso;
    renderActivity(iso);
    out.act[s][iso] = $("actDetail").innerHTML;
  }
}
renderActivity("JP"); out.plain = $("actDetail").innerHTML;
print(JSON.stringify(out));
"""


def run_jsc():
    fix = {"acts": {k: acts[k] for k in marked + ["JP"]}, "marks": data, "isos": marked, "states": STATES}
    with tempfile.TemporaryDirectory() as d:
        fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
        json.dump(fix, open(fp, "w"))
        open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("FIX_PATH", json.dumps(fp)))
        try:
            r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout.strip().splitlines()[-1]), None
        except Exception as e:
            return None, "%s %s" % (e, (r.stderr or "")[:300] if "r" in locals() else "")


js, err = run_jsc()
results.append(ok(js is not None, "app.js runs under jsc with the harness (%s)" % ("ok" if js else err)))
js = js or {"snip": {}, "act": {}, "plain": ""}
same_snip, same_page, placed = [], [], []
for s, notes in STATES.items():
    for iso in marked:
        py = [AM.html(iso, e["s"], e["i"], notes[iso], data) for e in data["countries"][iso]]
        same_snip.append(py == (js["snip"].get(s) or {}).get(iso))
        body, page = ssr(iso, notes[iso]), (js["act"].get(s) or {}).get(iso) or ""
        same_page.append(MARK.findall(body) == MARK.findall(page) == py)
        for e, m in zip(data["countries"][iso], py):
            if e["s"] == "activity":
                placed.append("<strong>%s</strong>%s" % (html.escape(e["i"]), m) in body
                              and '<span class="actlabel">%s%s</span>' % (AM.esc(e["i"]), m) in page)
            else:
                placed.append("<strong>%s</strong>%s" % (html.escape(e["i"]), m) in body
                              and "<span>%s%s</span>" % (AM.esc(e["i"]), m) in page)
results.append(ok(same_snip and all(same_snip),
                  "app.js zoneMarkHTML and avoid_marks.html write the same marker for every mark in every state"
                  " (%d of %d)" % (sum(same_snip), len(same_snip))))
results.append(ok(same_page and all(same_page),
                  "the crawler block (render_guide) and renderActivity carry exactly those markers, in order, for all %d"
                  " marked guides with no answer, the real one, a failed one, and the blocks reworded or gone"
                  % len(marked)))
results.append(ok(placed and all(placed), "each marker sits right after its item's label on both (%d of %d)"
                  % (sum(placed), len(placed))))
fresh = all("stale" not in m for s in FRESH for iso in marked for m in js["snip"].get(s, {}).get(iso, [""]))
stale = all('stale" data-zm' in m for s in ("reworded", "gone") for iso in marked for m in js["snip"].get(s, {}).get(iso, [""]))
results.append(ok(fresh and stale, "every marker shows with no answer, the real one or a failed one, and every one stays,"
                                   " unseen, when its blocks are reworded or gone"))
unmarked = [iso for iso in ("JP", "NG", "KE", "TN", "CO") if "zonemark" in ssr(iso, None)]
results.append(ok(not unmarked and "zonemark" not in js["plain"] and "actlabel" in js["plain"],
                  "no marker in an unmarked guide (Japan, Nigeria, Kenya, Tunisia, Colombia) (%s)" % unmarked))

# --- the page's wiring ------------------------------------------------------------------------------------
guide_build = re.search(r'buildTabOnce\("guide", async \(\) => \{.*?buildBestPickers', APP, re.S)
results.append(ok(bool(guide_build) and "ensureAvoidMarks()" in guide_build.group(0) and "ensureActivities()" in guide_build.group(0),
                  "app.js loads the marks with the guide's own data, before the list draws"))
results.append(ok(re.search(r"const paint = \(w\) => \{\s*syncZoneMarks\(iso\);", APP) is not None,
                  "Canada's answer, when it lands, brings the drawn markers to it (renderWatchouts)"))
css = open(P("public", "styles.css"), encoding="utf-8").read()
results.append(ok(re.search(r"\.zonemark\.stale\s*\{\s*visibility:\s*hidden;\s*\}", css) is not None,
                  "a stale marker keeps its box (visibility: hidden), so nothing moves"))
results.append(ok(re.search(r"\.ssrguide \.zonemark\s*\{\s*display:\s*none;\s*\}", css) is not None
                  and all(m.endswith(">&nbsp;ⓘ</span>") for m in MARK.findall(ssr("ET", None))),
                  "the crawler block's copy is unseen and takes no room, its no-break space inside it (its tip needs"
                  " app.js, which draws the working list above)"))
srv = open(P("server.py"), encoding="utf-8").read()
results.append(ok("render_guide.render(gc_iso, fv, fares_at, no_book, watchouts.cached(gc_iso))" in srv,
                  "the server renders a guide with Canada's notes as it caches them"))

# --- gen_stay_spots.py --check ------------------------------------------------------------------------------
g._BLOCKS.clear()
lines = g.marks_review(FIXDIR)
results.append(ok(lines == [], "--check's marks review passes the table on Canada's feed of 2026-10-30 (%s)" % lines[:3]))
with tempfile.TemporaryDirectory() as d:
    for iso in marked:
        raw = json.load(open(os.path.join(FIXDIR, iso.lower() + ".json"), encoding="utf-8"))
        a = raw["data"]["eng"]["advisories"]
        if iso == "ET":       # Canada lifts Amhara: the Lalibela quote is no longer its words
            a = a.replace("<li>Amhara</li>", "")
        if iso == "BJ":       # a reword that keeps the quoted sentence
            a = a.replace("Pendjari National Park.", "Pendjari National Park. Updated.")
        if iso == "MZ":       # the block's heading changes: the quoted block is gone
            a = a.replace("Cabo Delgado Province - Avoid all travel", "Cabo Delgado - Avoid all travel")
        raw["data"]["eng"]["advisories"] = a
        json.dump(raw, open(os.path.join(d, iso.lower() + ".json"), "w"))
    g._BLOCKS.clear()
    lines = g.marks_review(d)
    bad_table = copy.deepcopy(table)
    bad_table["marks"]["countries"]["TJ"][0]["fp"] = "000000000000"
    g._BLOCKS.clear()
    fp_lines = g.marks_review(FIXDIR, skip=bad_table)
    g._BLOCKS.clear()
    words_table = copy.deepcopy(table)
    words_table["marks"]["countries"]["CM"][0]["words"] = "Avoid all travel to the whole country."
    words_lines = g.marks_review(FIXDIR, skip=words_table)
et_lines = [x for x in lines if x.startswith("ET ")]
results.append(ok(len(et_lines) == 5 and all("reworded since 2026-10-30" in x for x in et_lines)
                  and any("BJ mark" in x and "reworded" in x for x in lines)
                  and any("MZ mark" in x and "gone" in x for x in lines)
                  and not any(x.startswith(("CM ", "TD ", "PK ", "SA ")) for x in lines),
                  "--check flags every mark on a reworded block (Ethiopia's five, Benin's) and on a gone one"
                  " (Mozambique's), and only those (%d lines)" % len(lines)))
results.append(ok(any("TJ mark" in x and "not the table's" in x for x in fp_lines)
                  and any("CM mark" in x and "not in Canada's block" in x for x in words_lines),
                  "and a mark whose fp is not its block's in the table, or whose words are not Canada's"))
with tempfile.TemporaryDirectory() as d:
    g._BLOCKS.clear()
    cov = g.canada_review({}, d)
results.append(ok(all(any(x.startswith(iso + " ") and "gone" in x for x in cov) for iso in marked),
                  "--check's Canada review covers every marked guide, stays or none"))
g._BLOCKS.clear()

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
