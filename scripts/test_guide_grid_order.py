"""The guide's two-column grid and the crawler block's hand-off, as far as
layout shift goes (index.html .guidegrid, styles.css, app.js renderGuide):

  - the grid's blocks stay in the phone's (and a screen reader's) order —
    visa, safety, AI, chart, month table, fare column, rule, stays — and from
    900px the stays are placed in row 2, above blocks the HTML sends first;
  - so until anything follows the grid (all of it has arrived), styles.css
    keeps every row under the first unseen in its place, and the grid is
    followed by an element in index.html, or the rule would never let go;
  - nothing in styles.css or app.js un-hides those rows before that;
  - renderGuide's hand-off of #ssrGuide, run under jsc as written: its height
    is pinned and it leaves scroll anchoring before its words go, the room
    gives up what the activities take as they grow (never taking any back),
    measured as the span under the rule over them, so the margins the
    crawler block's words lent through its edges stay in it, and
    releaseSsrRoom gets it two frames after the activities settle, once;
  - releaseSsrRoom (run under jsc) keeps the newsletter box where a reader
    at, over or past the leftover room sees it, scrolling only by what it
    measures, and moves nothing for a reader above the room.

    /usr/bin/python3 scripts/test_guide_grid_order.py
"""
import json, os, re, subprocess
from html.parser import HTMLParser

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Tree(HTMLParser):
    """Elements as [tag, attrs, children]; text kept only where it is a {{TOKEN}}."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = ["#root", {}, []]
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        el = [tag, dict(attrs), []]
        self.stack[-1][2].append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        for t in re.findall(r"\{\{[A-Z_]+\}\}", data):
            self.stack[-1][2].append(["#token", {"name": t}, []])


def find(el, pred, parent=None):
    if pred(el):
        return el, parent
    for c in el[2]:
        r = find(c, pred, el)
        if r:
            return r
    return None


def label(el):
    if el[0] == "#token":
        return el[1]["name"]
    a = el[1]
    return "#" + a["id"] if a.get("id") else el[0] + "." + (a.get("class") or "").split(" ")[0]


t = Tree()
t.feed(HTML)
hit = find(t.root, lambda e: e[0] == "div" and (e[1].get("class") or "").split(" ")[0] == "guidegrid")
grid, card = hit if hit else (None, None)
order = [label(c) for c in grid[2]] if grid else []
# {{GUIDE_VISA_ALT}}: the visa line's stand-ins for other passports, a <template>
# and a script (guide_sizers.visa_passports); {{FM_PICK}}: a script that sets
# the fares strip's room for the reader's From (server.py _FM_PICK) — nothing
# that lays out.
results.append(ok(order == ["#guideVisa", "{{GUIDE_VISA_ALT}}", "#guideSafety", "#guideAI", "#bestDetail",
                            "{{GUIDE_MONTHS}}", "{{FM_PICK}}", "div.farecol", "hr.softrule", "div.staycol"],
                  "the grid's blocks are in the phone's reading order: %s" % order))
after = []
if card:
    i = next(k for k, c in enumerate(card[2]) if c is grid)
    after = [label(c) for c in card[2][i + 1:] if c[0] != "#token"]
results.append(ok(len(after) > 0 and after[0] == "hr.softrule" and "#actDetail" in after,
                  "an element follows the grid in its card (what lets styles.css show it): %s" % after[:3]))

# styles.css: from 900px the stays sit in row 2, the chart and fare column in
# row 3 — so the rows under the first wait for the whole grid.
m900 = [b for b in re.findall(r"@media \(min-width: 900px\) \{(.*?)\n\}", CSS, re.S) if ".guidegrid" in b]
blk = m900[0] if m900 else ""
results.append(ok(re.search(r"\.guidegrid \.staycol \{ grid-row: 2; grid-column: 2; \}", blk)
                  and re.search(r"#bestDetail \{ grid-row: 3; grid-column: 1; \}", blk)
                  and re.search(r"\.guidegrid \.farecol \{ grid-row: 3; grid-column: 2; \}", blk),
                  "from 900px: stays in row 2, chart and fare column in row 3"))
results.append(ok(".guidegrid:not(:has(+ *)) > :not(#guideVisa, #guideAI) { visibility: hidden; }" in blk,
                  "from 900px, until anything follows the grid, its rows under the first are unseen"))
results.append(ok(CSS.count(".guidegrid:not(:has(+ *))") == 1,
                  "that rule exists once, in the 900px block only (below it the grid is a plain block in DOM order)"))

# Nothing un-hides the grid's rows early: no rule sets them visible again and
# app.js never sets an element's visibility.
results.append(ok(not re.search(r"visibility\s*:\s*visible", CSS) and "style.visibility" not in APP,
                  "nothing un-hides those rows early (no visibility: visible in styles.css, no style.visibility in app.js)"))

# A fares strip or FX line renderGuideFares / renderGuideFx hid is hidden once
# the fare column settles: their display: block outranks the browser's [hidden],
# so the last guide's strip stayed on screen after an in-app switch, and an
# empty one's margin came back as .loading went (everything under it 4px down).
# While the column loads, .farecol.loading's rule (more specific) still holds them.
results.append(ok(re.search(r"^\.guidefares\[hidden\], \.guidefx\[hidden\] \{ display: none; \}$", CSS, re.M) is not None
                  and re.search(r"^\.farecol\.loading > \[hidden\] \{ display: block; visibility: hidden; \}$", CSS, re.M) is not None
                  and "#tab-guide:not([data-fm]) .farecol.loading > #guideFares[hidden] { display: none; }" in CSS
                  and "#tab-guide[data-fx] .farecol.loading > #guideFx[hidden] { display: none; }" in CSS,
                  "a hidden fares strip or FX line is display: none once the column settles, and the same while it "
                  "loads unless held (.farecol.loading)"))

# Wherever that hidden strip is display: none (the column settled, or loading
# with no room held), the FX line keeps the strip's own top gap: the strip's
# 14px margin, not the line's 10. With the line's 10, a held strip given back
# as the column settled (a German reader the server has no fares for yet, on
# a guide the US strip holds room on) also lifted the column 4px in the
# frame everything under it rose 196px, and Chrome scored the column's move
# too (Japan 0.149 against 0.125, 390, slow, scrolled 2000). A general
# sibling (~): _GUIDE_HOLD's <script> can sit between the two.
fares_top = re.search(r"^\.guidefares \{ display: block; margin: (\d+)px 0 \d+px; \}$", CSS, re.M)
fx_gap = re.search(r"^#tab-guide\[data-fm\] \.farecol:not\(\.loading\) > #guideFares\[hidden\] ~ #guideFx "
                   r"\{ margin-top: (\d+)px; \}$", CSS, re.M)
# Only there: with no room held (no data-fm) the line keeps its own 10px from
# the first paint to the settled page. Giving it 14 while loading too made its
# held room 4px taller, so where the FX line never came (a German reader on a
# euro guide, Croatia at 390) everything under the column fell 100px, not 96.
results.append(ok("#tab-guide:not([data-fm]) .farecol.loading > #guideFares[hidden] ~ #guideFx" not in CSS
                  and ".farecol:not(.loading) > .guidefares[hidden] ~ .guidefx" not in CSS,
                  "the FX line's 14px gap applies only where a room was held (data-fm), never while loading"))
results.append(ok(fares_top is not None and fx_gap is not None and fx_gap.group(1) == fares_top.group(1),
                  "the FX line under a display: none fares strip keeps the strip's top gap (%s px; the strip's %s)"
                  % (fx_gap and fx_gap.group(1), fares_top and fares_top.group(1))))

# renderGuide's hand-off of the crawler block, run under jsc as written: its
# first lines (find, measure, pin, empty) and the block after renderActivity.
pin = re.search(r'^  const ssr = \$\("ssrGuide"\)[^\n]*\n  const span0[^\n]*\n  if \(ssr\) \{[^\n]*\}\n', APP, re.M)
span_fn = re.search(r"^function ssrSpan\(ssr\) \{.*?^\}\n", APP, re.M | re.S)
hand = re.search(r"^  if \(ssr\) \{\n    // Only what.*?^  \}\n(?=  renderGuideStay\(iso\);)", APP, re.M | re.S)
results.append(ok(pin and hand and span_fn, "found renderGuide's crawler-block lines and ssrSpan"))
HAND = r"""
var log = [], released = [], rafQ = [], moCb = null, moOn = null, moOff = 0, resolveActs;
// The card from the rule over the activities down: the activities, the crawler
// block (1103px with its words, then its pinned height) and the margins between
// them; LENT of those go with the crawler's words (its first h2's, its last
// list's, collapsing through its edges), 8px stay (the activities' own).
var LENT = LENT_PX;
var ssrEl = { offsetHeight: 1103, style: {}, id: "ssrGuide", _w: "words", setAttribute: function (k, v) { this[k] = v; } };
Object.defineProperty(ssrEl, "innerHTML", { get: function () { return this._w; },
  set: function (v) { log.push([this.style.height, this.style.overflowAnchor]); this._w = v; } });
var actEl = { offsetHeight: 40, previousElementSibling: { getBoundingClientRect: function () { return { bottom: 500 }; } } };
ssrEl.parentElement = { getBoundingClientRect: function () {
  var room = ssrEl._w ? 1103 + LENT : parseFloat(ssrEl.style.height);
  return { bottom: 500 + actEl.offsetHeight + room + 8 }; } };
function $(id) { return id === "ssrGuide" ? ssrEl : id === "actDetail" ? actEl : null; }
SPANFN
function MutationObserver(cb) { moCb = cb; this.observe = function (t) { moOn = t; }; this.disconnect = function () { moOff++; }; }
function requestAnimationFrame(f) { rafQ.push(f); }
function frame() { var q = rafQ; rafQ = []; q.forEach(function (f) { f(); }); }
function setTimeout() {}   // the 8 s cap: not reached here
function releaseSsrRoom(s) { released.push([s === ssrEl, s.style.height, moOff]); }
function ensureAdvisories() { return Promise.resolve(); }
var acts = new Promise(function (r) { resolveActs = r; });
var out = {};
(function () {
PIN
  actEl.offsetHeight = 805;   // renderActivity drew the rows: +765
HAND
  out.pinned = log;
  out.room = [ssrEl.style.height, moOn === actEl];
  actEl.offsetHeight = 824; moCb(); out.grew = ssrEl.style.height;     // a photo lands: +19
  actEl.offsetHeight = 810; moCb(); out.shrank = ssrEl.style.height;   // shorter again: nothing taken back
})();
resolveActs();
var p = Promise.resolve();
for (var i = 0; i < 12; i++) p = p.then(function () {});
p.then(function () {
  out.settled = released.length; frame();
  out.oneFrame = released.length; actEl.offsetHeight = 830; frame();   // grew once more before the release
  out.release = released; frame(); out.after = released.length;
  print(JSON.stringify(out));
});
"""
def hand_off(lent):
    try:
        prog = (HAND.replace("PIN", pin.group(0)).replace("HAND", hand.group(0)).replace("SPANFN", span_fn.group(0))
                .replace("LENT_PX", str(lent)))
        return json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
    except Exception:
        return None


h = hand_off(0)
h18 = hand_off(18)
results.append(ok(h and h["pinned"] == [["1103px", "none"]],
                  "the crawler block's height is pinned and it leaves scroll anchoring before its words go (%s)" % (h and h["pinned"])))
results.append(ok(h and h["room"] == ["338px", True],
                  "what the activities didn't take is left as room, and the activities are watched (%s)" % (h and h["room"])))
results.append(ok(h and h["grew"] == "319px" and h["shrank"] == "319px",
                  "the room gives up what the activities take as they grow, never taking any back (%s, %s)"
                  % (h and h["grew"], h and h["shrank"])))
results.append(ok(h and h["settled"] == 0 and h["oneFrame"] == 0,
                  "nothing is released in the frame the activities settle in, nor the next one's callbacks"))
results.append(ok(h and h["release"] == [[True, "313px", 1]] and h["after"] == 1,
                  "two frames on: the watch stops, the room fits once more, releaseSsrRoom gets it once (%s)"
                  % (h and h["release"])))
# The margins the crawler's first and last lines lent through its edges (18px)
# go with its words: the room keeps them, so the newsletter box doesn't rise.
results.append(ok(h18 and h18["pinned"] == [["1103px", "none"]] and h18["room"] == ["356px", True]
                  and h18["grew"] == "337px" and h18["shrank"] == "337px" and h18["release"] == [[True, "331px", 1]],
                  "the margins the crawler block's words lent (18px) stay in the room: 356px left, then 337 and 331 "
                  "as the activities grow, the span under the rule unchanged (%s)"
                  % (h18 and [h18["room"], h18["grew"], h18["shrank"], h18["release"]])))

fn = re.search(r"^function releaseSsrRoom\(ssr\) \{.*?^\}", APP, re.M | re.S)
results.append(ok(fn, "found releaseSsrRoom"))
# A page as releaseSsrRoom sees it: the room's rect, the newsletter box's top
# before and after the room goes (anchoring may already have held it), and the
# scrolls it asks for.
STUB = r"""
var calls = [], gone = false, R, B0, B1;
var ssr = { getBoundingClientRect: function () { return R; }, remove: function () { gone = true; } };
var sub = { getBoundingClientRect: function () { return { top: gone ? B1 : B0 }; } };
var window = { innerHeight: 844, scrollBy: function (x, y) { calls.push(y); } };
var document = { querySelector: function () { return null; } };
function $(id) { return id === "subscribe" ? sub : null; }
function run(r, b0, b1) { calls = []; gone = false; R = r; B0 = b0; B1 = b1; releaseSsrRoom(ssr); return { gone: gone, scrolls: calls }; }
"""
CASES = [
    # (what, room rect, box top before, box top after removal, expected scrolls)
    ("room below the screen: removed, no scroll", {"top": 900, "bottom": 1188}, 1200, 912, []),
    ("room above the screen, no anchoring: the box is held", {"top": -400, "bottom": -112}, 300, 12, [-288]),
    ("room above the screen, anchoring held it: no scroll", {"top": -400, "bottom": -112}, 300, 300, []),
    ("reader at the bottom, a sliver of activities above the room: the box is held",
     {"top": 6, "bottom": 294}, 294, 6, [-288]),
    ("box half on screen under activities: the box is held (the activities slide down)",
     {"top": 321, "bottom": 640}, 677, 358, [-319]),
    ("box below the screen that would come up into view: held (the activities slide down)",
     {"top": 600, "bottom": 888}, 927, 639, [-288]),
    ("room only peeking in at the screen's foot, the box would stay below it: nothing held",
     {"top": 830, "bottom": 1118}, 1157, 869, []),
    ("guide tab hidden (all zeros): no scroll", {"top": 0, "bottom": 0}, 0, 0, []),
]
prog = STUB + (fn.group(0) if fn else "") + "\nprint(JSON.stringify([" + ",".join(
    "run(%s,%d,%d)" % (json.dumps(r), b0, b1) for _w, r, b0, b1, _e in CASES) + "]));"
try:
    out = json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
except Exception:
    out = None
for k, (what, _r, _b0, _b1, exp) in enumerate(CASES):
    got = out[k] if out else None
    results.append(ok(got is not None and got["gone"] and got["scrolls"] == exp,
                      "%s (scrolls %s)" % (what, got and got["scrolls"])))

print("%d/%d passed" % (sum(bool(r) for r in results), len(results)))
raise SystemExit(0 if all(results) else 1)
