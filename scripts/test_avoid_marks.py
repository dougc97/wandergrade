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
  * the words are Canada's: each mark checked on 2026-10-30 has its words in
    its block, verbatim and in order, in Canada's feed of that day
    (scripts/fixtures/gac-2026-10-30), at the fingerprint the mark carries,
    each " … " over words left out (quoted(), tested on its own); a mark
    re-checked later (DEPLOY.md, "Re-check a row") is held to the table only
    and left to --check on the live feed, and a simulated re-check keeps
    this test green; watchouts.from_feed gives every block that fingerprint
    ("fp", what /api/watchouts serves for the page's own check);
  * public/avoid-marks.json is exactly what the table builds;
  * the wording: always "Global Affairs Canada: “…” (travel.gc.ca, checked
    YYYY-MM-DD)", Saudi Arabia's two blocks in one marker;
  * the markup: render_guide's crawler block and app.js renderActivity (run
    under jsc, scripts/appjs_harness.js) write the same markers, character
    for character, for every marked guide — with no Canada answer, with
    Canada's real answer of 2026-10-30, a failed answer, and answers showing
    the blocks reworded or gone (each marker then stays, invisible), Saudi
    Arabia with one of its two blocks reworded; when Canada's answer lands
    after the list drew (syncZoneMarks), each marker takes its tip in place,
    and only on the guide it was drawn for; a tip dates itself by its
    oldest quote; each marker after its
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
import datetime
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
# The fixtures are Canada's feed of the day the marks were checked; a mark
# re-checked later, against a block Canada has reworded since (DEPLOY.md, "Re-check
# a row"), is held to the table only here and left to --check on the live feed.
FIXDAY = "2026-10-30"
held = lambda r: r["checked"] <= FIXDAY
fix_blocks = {}
for iso in marked:
    with open(os.path.join(FIXDIR, iso.lower() + ".json"), encoding="utf-8") as f:
        fix_blocks[iso] = watchouts.from_feed(iso, json.load(f))["regional"]
et_north = next(b["text"] for b in fix_blocks["ET"] if b["t"] == "Northern regions - Avoid all travel")
fix_fp = {(iso, b["t"]): b["fp"] for iso, bs in fix_blocks.items() for b in bs}
results.append(ok(all(b.get("fp") == watchouts.fingerprint(b["text"]) for bs in fix_blocks.values() for b in bs)
                  and all(fix_fp.get((iso, r["block"])) == blocks[iso][r["block"]]["fp"] for iso, r in rows if held(r))
                  and g.fingerprint(et_north) == watchouts.fingerprint(et_north)
                  and g.fingerprint("a • b") == watchouts.fingerprint("a\n- b."),
                  "watchouts.from_feed gives every block its fingerprint (gen_stay_spots' own, one implementation)"))
# quoted() is the whole proof of "verbatim", here and in --check: it must
# miss a change of case or accent, a wrong order, an empty segment, a segment
# found only before the one ahead of it, and an omission mark over nothing
# (neighbouring lines are joined by Canada's own line break).
bi_text = next(b["text"] for b in fix_blocks["BI"] if b["t"] == "Regional Advisory - Avoid all travel")
mr_text = next(b["text"] for b in fix_blocks["MR"] if b["t"] == "Northern and eastern Mauritania - Avoid all travel")
lead = et_north.split("\n")[0]        # "Avoid all travel to the following northern regions … situation:"
QCASES = [
    (lead + " … • Amhara", et_north, True),               # the Lalibela quote: Afar's line left out
    (lead + "\n• Afar", et_north, True),                  # neighbouring lines, Canada's line break
    ("• Cibitoke province", bi_text, True),
    ("Kiffa-Sélibali line", mr_text, True),
    ("• Cibitoke Province", bi_text, False),              # case
    ("Kiffa-Selibali line", mr_text, False),              # accent
    ("• Amhara … • Afar", et_north, False),               # order
    ("• Tigray … • Amhara", et_north, False),             # a segment found only before the one ahead of it
    (lead + " … " + lead, et_north, False),               # the same words twice, once in the block
    (lead + " …  … • Amhara", et_north, False),           # an empty segment
    ("", et_north, False),
    (lead + " … • Afar", et_north, False),                # " … " over nothing: the lines are neighbours
    ("• Amhara", None, False),
]
qbad = [(wds[:40], want) for wds, txt, want in QCASES if g.quoted(wds, txt) is not want]
results.append(ok(not qbad, "quoted() takes Canada's words verbatim and in order, each \" … \" over words left out,"
                            " and nothing else (case, accent, order, empty or repeated segments) (wrong: %s)" % qbad))



def held_only(tbl):
    """tbl with only the marks the fixtures speak for: those checked on their day."""
    t = copy.deepcopy(tbl)
    ms = t["marks"]["countries"]
    t["marks"]["countries"] = {iso: [r for r in rs if held(r)] for iso, rs in ms.items() if any(held(r) for r in rs)}
    return t


def verbatim(tbl):
    """(marks whose words are in their block, verbatim and in order, in the fixtures,
    at the fp they carry; marks checked since; marks held to the fixtures that fail)"""
    yes, later, wrong = [], [], []
    for iso, r in AM.rows(tbl):
        b = next((x for x in fix_blocks.get(iso, []) if x["t"] == r["block"]), None)
        if not held(r):
            later.append((iso, r["item"]))
        elif b and b["fp"] == r["fp"] and g.quoted(r["words"], b["text"]):
            yes.append((iso, r["item"]))
        else:
            wrong.append((iso, r["item"]))
    return yes, later, wrong


v_yes, v_later, v_wrong = verbatim(table)
results.append(ok(not v_wrong and len(v_yes) + len(v_later) == len(rows),
                  "%d of %d marks' words are in their block verbatim, in order, each \" … \" over words left out, in"
                  " Canada's feed of %s at the fingerprint they carry (checked since, for --check: %s; wrong: %s)"
                  % (len(v_yes), len(rows), FIXDAY, v_later, v_wrong)))

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


def live_ok(d):
    """Canada's real answer of FIXDAY keeps every quote checked that day; an
    answer showing a quoted block reworded or gone drops the quote, whenever
    it was checked."""
    qs = [(iso, q) for iso, es in d["countries"].items() for e in es for q in e["q"]]
    return (all(AM.live(q, LIVE[iso]) for iso, q in qs if q["c"] <= FIXDAY)
            and not any(AM.live(q, changed(LIVE[iso])) or AM.live(q, changed(LIVE[iso], drop=True)) for iso, q in qs))


def fresh_py(d):
    """Every marker with a quote checked on FIXDAY shows with Canada's answer of that day."""
    return all("stale" not in AM.span(iso, k, LIVE[iso], d) for iso, es in d["countries"].items()
               for k, e in enumerate(es) if any(q["c"] <= FIXDAY for q in e["q"]))


results.append(ok(live_ok(data) and fresh_py(data)
                  and AM.live({"b": "x", "fp": "0"}, None) and AM.live({"b": "x", "fp": "0"}, STATES["failed"]["ET"])
                  and AM.live({"b": "x", "fp": "0"}, {"link": "y", "regional": [{"t": "x"}]}),
                  "a quote stands with no answer, a failed one or a block without an fp, and with Canada's real"
                  " 2026-10-30 answer (the quotes checked that day); it drops where the answer shows its block"
                  " reworded or gone"))

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


def agree(iso, off=()):
    """Canada's answer as the table has it (whatever day each mark was checked),
    the blocks in `off` reworded."""
    heads = list(dict.fromkeys(q["b"] for e in data["countries"][iso] for q in e["q"]))
    fps = {q["b"]: q["fp"] for e in data["countries"][iso] for q in e["q"]}
    return {"iso": iso, "source": "Global Affairs Canada", "link": "https://travel.gc.ca/destinations/x", "watchouts": [],
            "regional": [{"t": h, "text": "", "fp": "0" * 12 if h in off else fps[h]} for h in heads]}


sa_agree = agree("SA", off=("Border with Yemen - Avoid all travel",))
sa_one = html.unescape(TIP.search(AM.span("SA", 0, sa_agree, data)).group(1))
results.append(ok(sa_one.count("“") == 1 and "Asir" in sa_one and "Yemen" not in sa_one,
                  "with its Yemen block reworded, it quotes only the Asir block"))
# A marker's tip dates itself by its oldest quote, whichever comes first
# (app.js zoneTip the same, under jsc below).
QD = [{"w": "a", "c": "2099-12-31"}, {"w": "b", "c": FIXDAY}]
results.append(ok(AM.tip(QD).endswith("(travel.gc.ca, checked %s)" % FIXDAY)
                  and AM.tip(QD[::-1]).endswith("(travel.gc.ca, checked %s)" % FIXDAY),
                  "a marker with quotes checked on two days gives the older date"))
st = AM.span("ET", 0, STATES["reworded"]["ET"], data)
results.append(ok(st == '<span class="muted zonemark stale" data-zm="0" aria-hidden="true">&nbsp;ⓘ</span>',
                  "a marker whose every quote is stale stays in place, unseen, with nothing to say"))
mk = AM.html("ET", "activity", "Rock churches (Lalibela)", None, data)
results.append(ok(mk.startswith('<span class="muted zonemark" data-zm="0" data-tip="Global Affairs Canada: “Avoid all')
                  and re.search(r'\(travel\.gc\.ca, checked \d{4}-\d{2}-\d{2}\)" title="">&nbsp;ⓘ</span>$', mk)
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

// syncZoneMarks: Canada's answer lands after the list drew. The browser's view
// of the drawn markers: each "#actDetail .zonemark[data-zm]" in the list's
// markup, its data-zm and data-tip as the browser reads them (unescaped), and
// an outerHTML that rewrites that one marker where it stands.
const __qsa = document.querySelectorAll;
const __MK = () => /<span class="muted zonemark[^"]*" data-zm="(\d+)"[^>]*>&nbsp;ⓘ<\/span>/g;
const __unesc = (s) => s.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");
let __writes = 0;
document.querySelectorAll = function (q) {
  if (q !== "#actDetail .zonemark[data-zm]") return __qsa.call(document, q);
  const host = $("actDetail"), re = __MK(), els = [];
  let m, n = 0;
  while ((m = re.exec(host.innerHTML))) {
    const k = n++, tip = /data-tip="([^"]*)"/.exec(m[0]);
    els.push({ dataset: tip ? { zm: m[1], tip: __unesc(tip[1]) } : { zm: m[1] },
      set outerHTML(v) { __writes++; let i = 0; host.innerHTML = host.innerHTML.replace(__MK(), (x) => (i++ === k ? v : x)); } });
  }
  return els;
};
const draw = (iso, w) => {
  if (w) _watchoutCache[iso] = w; else delete _watchoutCache[iso];
  ccGuideIso = iso; renderActivity(iso); return $("actDetail").innerHTML;
};
const html = () => $("actDetail").innerHTML;
const syncs = (iso) => { __writes = 0; syncZoneMarks(iso); return [html(), __writes]; };
const S = FIX.states, sy = {};
// Ethiopia drawn before Canada's answer, which shows its northern block reworded;
// the same answer again; then one that agrees with the table.
sy.cold = draw("ET", null);
_watchoutCache.ET = S.reworded.ET; sy.toStale = syncs("ET");
sy.again = syncs("ET");
_watchoutCache.ET = FIX.agree.ET; sy.toLive = syncs("ET");
// Drawn for Ethiopia: a sync for another guide, with nothing drawn, or once
// the page shows another guide leaves it as it is; the last line is the control.
sy.cold2 = draw("ET", null); _watchoutCache.ET = S.reworded.ET;
sy.other = syncs("CM");
zoneDrawnIso = null; sy.undrawn = syncs("ET");
zoneDrawnIso = "ET"; ccGuideIso = "CM"; sy.away = syncs("ET");
ccGuideIso = "ET"; sy.control = syncs("ET");
// Saudi Arabia's one marker on two blocks, its Yemen block reworded (Asir as the table has it).
sy.saCold = draw("SA", null); _watchoutCache.SA = FIX.agree.SA; sy.saSync = syncs("SA");
// The same lists drawn from scratch with those answers.
sy.fresh = { reworded: draw("ET", S.reworded.ET), live: draw("ET", FIX.agree.ET), sa: draw("SA", FIX.agree.SA) };
out.sync = sy;
// A tip dates itself by its oldest quote.
out.dates = [zoneTip(FIX.dates), zoneTip(FIX.dates.slice().reverse())];
out.datedMarks = FIX.dated.map((d) => { avoidMarks = d; return zoneMarkHTML("SA", d.countries.SA[0].s, d.countries.SA[0].i, null); });
avoidMarks = FIX.marks;
print(JSON.stringify(out));
"""


# Saudi Arabia's marks with one quote, then the other, checked on a later day.
DATED = []
for j in range(len(data["countries"]["SA"][0]["q"])):
    d2 = copy.deepcopy(data)
    d2["countries"]["SA"][0]["q"][j]["c"] = "2099-12-31"
    DATED.append(d2)


def run_jsc():
    fix = {"acts": {k: acts[k] for k in marked + ["JP"]}, "marks": data, "isos": marked, "states": STATES,
           "dates": QD, "dated": DATED, "agree": {"ET": agree("ET"), "SA": sa_agree}}
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
# With Canada's answer of the fixtures' day, the markers it speaks for: those
# with a quote checked that day.
fresh = all("stale" not in m for s in FRESH for iso in marked
            for e, m in zip(data["countries"][iso], js["snip"].get(s, {}).get(iso, []))
            if s != "live" or any(q["c"] <= FIXDAY for q in e["q"]))
stale = all('stale" data-zm' in m for s in ("reworded", "gone") for iso in marked for m in js["snip"].get(s, {}).get(iso, [""]))
results.append(ok(fresh and stale, "every marker shows with no answer, the real one or a failed one, and every one stays,"
                                   " unseen, when its blocks are reworded or gone"))
sy = js.get("sync") or {}
fr = sy.get("fresh") or {}
n_et = len(data["countries"]["ET"])
unmark = lambda h: MARK.sub("", h or "")
results.append(ok(bool(sy) and sy["toStale"] == [fr["reworded"], n_et] and sy["toStale"][0] != sy["cold"]
                  and unmark(sy["toStale"][0]) == unmark(sy["cold"]) and len(MARK.findall(sy["toStale"][0])) == n_et
                  and sy["again"] == [sy["toStale"][0], 0] and sy["toLive"] == [fr["live"], n_et]
                  and sy["saSync"][0] == fr["sa"] and sy["saSync"][0] != sy["saCold"],
                  "when Canada's answer lands after the list drew (syncZoneMarks), each marker takes the tip a fresh"
                  " draw would give it, in place, rewriting only the markers that changed: Ethiopia's five go stale"
                  " and come back, Saudi Arabia's drops its reworded Yemen quote"))
results.append(ok(bool(sy) and all(sy[k] == [sy["cold2"], 0] for k in ("other", "undrawn", "away"))
                  and sy["control"][0] == fr["reworded"],
                  "and touches nothing for another guide, with no list drawn, or once the page shows another guide"))
dated_py = [AM.html("SA", d2["countries"]["SA"][0]["s"], d2["countries"]["SA"][0]["i"], None, d2) for d2 in DATED]
results.append(ok(js.get("dates") == [AM.tip(QD), AM.tip(QD[::-1])] and js.get("datedMarks") == dated_py
                  and len(DATED) == 2 and all("checked 2099" not in m for m in dated_py),
                  "app.js zoneTip dates a tip by its oldest quote too, as avoid_marks.tip does, whichever quote is"
                  " older"))
unmarked = [iso for iso in ("JP", "NG", "KE", "TN", "CO") if "zonemark" in ssr(iso, None)]
results.append(ok(not unmarked and "zonemark" not in js["plain"] and "actlabel" in js["plain"],
                  "no marker in an unmarked guide (Japan, Nigeria, Kenya, Tunisia, Colombia) (%s)" % unmarked))

# --- the page's wiring ------------------------------------------------------------------------------------
guide_build = re.search(r'buildTabOnce\("guide", async \(\) => \{.*?buildBestPickers', APP, re.S)
results.append(ok(bool(guide_build) and "ensureAvoidMarks()" in guide_build.group(0) and "ensureActivities()" in guide_build.group(0),
                  "app.js loads the marks with the guide's own data, before the list draws"))
results.append(ok(re.search(r"const paint = \(w\) => \{\s*syncZoneMarks\(iso\);", APP) is not None,
                  "Canada's answer, when it lands, brings the drawn markers to it (renderWatchouts)"))
# Tab to an ⓘ below the fold scrolls the page after focusin showed its tip: the
# scroll must not take Canada's words away from a keyboard user
# (scripts/dev/zonemark_kbd_check.mjs drives it in Chrome).
scroll_h = re.search(r'document\.addEventListener\("scroll", \(\) => \{(.*?)\n\}, true\);', APP, re.S)
results.append(ok('document.addEventListener("scroll", _hideTip, true)' not in APP and bool(scroll_h)
                  and all(x in scroll_h.group(1) for x in ("document.activeElement", "_kbdNav", "_placeTip(t)")),
                  "a scroll that focus makes keeps the focused ⓘ's tip up beside it (keyboard), and its words linked"))
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
# Canada's feed of the fixtures' day, as fetched, and with Canada lifting Amhara
# (Ethiopia: the Lalibela quote is no longer its words), rewording Benin's block
# around the quoted sentence, and renaming Mozambique's (the quoted block is gone).
EDITS = {"ET": ("<li>Amhara</li>", ""), "BJ": ("Pendjari National Park.", "Pendjari National Park. Updated."),
         "MZ": ("Cabo Delgado Province - Avoid all travel", "Cabo Delgado - Avoid all travel")}
EDITED = {"ET": ("Northern regions - Avoid all travel", "reworded"),
          "BJ": ("Border areas with Burkina Faso, Niger, Nigeria and Togo - Avoid all travel", "reworded"),
          "MZ": ("Cabo Delgado Province - Avoid all travel", "gone")}
head = lambda line: line.split(" — ")[0]


def flag(iso, r, kind):
    """The start of marks_review's line for a mark on a reworded or gone block."""
    return '%s mark "%s" (%s): block %s' % (iso, r["item"], r["block"], "reworded since " + r["checked"]
                                             if kind == "reworded" else "gone from Canada's page")


def review(tbl):
    """marks_review on the fixtures for tbl's marks checked on their day: (as
    fetched, with the edits above, and the marks the edits must flag — each by
    its own check date — and nothing else), and with every block they quote
    reworded or gone (each mark flagged, so this never tests nothing while one
    mark is held to the fixtures)."""
    H = held_only(tbl)
    hrows = AM.rows(H)
    g._BLOCKS.clear()
    clean = g.marks_review(FIXDIR, skip=H)
    with tempfile.TemporaryDirectory() as d:
        for iso in marked:
            raw = json.load(open(os.path.join(FIXDIR, iso.lower() + ".json"), encoding="utf-8"))
            if iso in EDITS:
                a = raw["data"]["eng"]["advisories"]
                assert EDITS[iso][0] in a, iso
                raw["data"]["eng"]["advisories"] = a.replace(*EDITS[iso])
            json.dump(raw, open(os.path.join(d, iso.lower() + ".json"), "w"))
        g._BLOCKS.clear()
        edited = sorted(head(x) for x in g.marks_review(d, skip=H))
    want = sorted(flag(iso, r, EDITED[iso][1]) for iso, r in hrows if iso in EDITED and r["block"] == EDITED[iso][0])
    every = {}
    for kind in ("reworded", "gone"):
        g._BLOCKS.clear()
        for iso in H["marks"]["countries"]:
            g._BLOCKS[(iso, "mem")] = changed(LIVE[iso], drop=kind == "gone")["regional"]
        every[kind] = (sorted(head(x) for x in g.marks_review("mem", skip=H)),
                       sorted(flag(iso, r, kind) for iso, r in hrows))
    g._BLOCKS.clear()
    return clean, edited, want, every


clean, edited, want, every = review(table)
results.append(ok(clean == [], "--check's marks review passes the table's marks checked on 2026-10-30 on Canada's feed"
                               " of that day (%s)" % clean[:3]))
results.append(ok(edited == want and all(a == b for a, b in every.values()),
                  "--check flags every mark on a reworded block (Ethiopia's Amhara lifted, Benin's block reworded) and"
                  " on a gone one (Mozambique's renamed), each by the day it was checked, and only those (%d lines);"
                  " and every mark when all its blocks are reworded or gone" % len(edited)))
H = held_only(table)
hrows = AM.rows(H)
# The checks below need a mark held to the fixtures; once every mark has been
# re-checked since, they have nothing to hold (the fixtures' README: refetch
# them as a new day).
if not hrows:
    results.append(ok(True, "no mark is on the fixtures' day any more: --check holds them all on the live feed"))
else:
    first = lambda: next(iter(H["marks"]["countries"]))      # the first country with a mark held to the fixtures
    bad_table, words_table, gap_table = copy.deepcopy(H), copy.deepcopy(H), copy.deepcopy(H)
    bad_table["marks"]["countries"][first()][0]["fp"] = "000000000000"
    words_table["marks"]["countries"][first()][0]["words"] = "Avoid all travel to the whole country."
    # Neighbouring lines quoted with an omission mark between them, where nothing is left out.
    nl = next(((iso, j) for iso, rs in H["marks"]["countries"].items() for j, r in enumerate(rs) if "\n" in r["words"]), None)
    if nl:
        r = gap_table["marks"]["countries"][nl[0]][nl[1]]
        r["words"] = r["words"].replace("\n", " … ", 1)
    g._BLOCKS.clear()
    fp_lines = g.marks_review(FIXDIR, skip=bad_table)
    g._BLOCKS.clear()
    words_lines = g.marks_review(FIXDIR, skip=words_table)
    g._BLOCKS.clear()
    gap_lines = g.marks_review(FIXDIR, skip=gap_table)
    item0 = H["marks"]["countries"][first()][0]["item"]
    gap_item = nl and gap_table["marks"]["countries"][nl[0]][nl[1]]["item"]
    gap_ok = nl is None or ([x for x in gap_lines if "not in Canada's block" in x]
                            == [x for x in gap_lines if x.startswith('%s mark "%s"' % (nl[0], gap_item))] != [])
    results.append(ok(any('%s mark "%s"' % (first(), item0) in x and "not the table's" in x for x in fp_lines)
                      and any('%s mark "%s"' % (first(), item0) in x and "not in Canada's block" in x for x in words_lines)
                      and gap_ok,
                      "and a mark whose fp is not its block's in the table, whose words are not Canada's, or whose"
                      " \" … \" stands over nothing"))

    # DEPLOY.md's "Re-check a row" keeps this test green: Canada rewords a marked
    # block, and the block's fp and its marks' fp and checked move on (their words
    # still Canada's). Those marks are then the table's and --check's; every other
    # mark is still held to the fixtures.
    sim = copy.deepcopy(table)
    iso0, r0 = next((iso, r) for iso, r in AM.rows(sim) if held(r))
    text0 = next(b["text"] for b in fix_blocks[iso0] if b["t"] == r0["block"])
    fp0 = watchouts.fingerprint(text0 + " Canada adds a sentence.")
    day0 = (datetime.date.fromisoformat(FIXDAY) + datetime.timedelta(days=16)).isoformat()
    sim["countries"][iso0][r0["block"]]["fp"] = fp0
    moved = []
    for r in sim["marks"]["countries"][iso0]:
        if r["block"] == r0["block"]:
            r["fp"], r["checked"] = fp0, day0
            moved.append((iso0, r["item"]))
    sd = AM.build(sim)
    s_yes, s_later, s_wrong = verbatim(sim)
    s_clean, s_edited, s_want, s_every = review(sim)
    results.append(ok(not s_wrong and sorted(s_later) == sorted(moved + v_later) and len(s_yes) == len(v_yes) - len(moved)
                      and all(r["fp"] == sim["countries"][i][r["block"]]["fp"] for i, r in AM.rows(sim))
                      and live_ok(sd) and fresh_py(sd) and s_clean == [] and s_edited == s_want
                      and all(a == b for a, b in s_every.values()),
                      "a mark re-checked as DEPLOY.md says (%s %s, block reworded, checked %s) leaves every check above"
                      " green, held to the table and left to --check, the other marks still to the fixtures"
                      % (iso0, r0["block"], day0)))
with tempfile.TemporaryDirectory() as d:
    g._BLOCKS.clear()
    cov = g.canada_review({}, d)
results.append(ok(all(any(x.startswith(iso + " ") and "gone" in x for x in cov) for iso in marked),
                  "--check's Canada review covers every marked guide, stays or none"))
g._BLOCKS.clear()

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
