"""The guide's two-column grid and the crawler block's hand-off, as far as
layout shift goes (index.html .guidegrid, styles.css, app.js renderGuide):

  - the grid's blocks stay in the phone's (and a screen reader's) order —
    visa, safety, AI, chart, month table, fare column, rule, stays — and from
    900px the stays are placed in row 2, above blocks the HTML sends first;
  - so until anything follows the grid (all of it has arrived), styles.css
    keeps every row under the first unseen in its place, and the grid is
    followed by an element in index.html, or the rule would never let go;
  - renderGuide pins #ssrGuide's height before it empties it, and
    releaseSsrRoom (run under jsc) keeps the newsletter box where a reader at
    or past the leftover room sees it, scrolling only by what it measures.

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
results.append(ok(order == ["#guideVisa", "#guideSafety", "#guideAI", "#bestDetail", "{{GUIDE_MONTHS}}",
                            "div.farecol", "hr.softrule", "div.staycol"],
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

# renderGuide: the crawler block's height is pinned in the same statement that
# empties it, before any layout the function forces.
results.append(ok(re.search(r'if \(ssr\) \{ ssr\.style\.height = ssrH \+ "px"; ssr\.innerHTML = "";', APP),
                  "renderGuide pins #ssrGuide's height before emptying it"))
results.append(ok("new MutationObserver(fit)" in APP and "releaseSsrRoom(ssr)" in APP,
                  "the leftover room gives up what the activities take (MutationObserver) and is released by releaseSsrRoom"))

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
    ("reader in the activities, the room low on screen: nothing held", {"top": 600, "bottom": 888}, 888, 600, []),
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
