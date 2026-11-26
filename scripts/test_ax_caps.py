"""Control names that the CSS capitals garbled. Chrome builds an accessible
name from the text as it is drawn, text-transform included, and some labels
are drawn in capitals (styles.css: th, which .sortbtn inherits; .picklabel;
.gqlabel), so its accessibility tree named controls "DESTINATION", "PRICE
LEVEL", "VS 1-YR AVG Ⓘ" (the ⓘ capitalised too), "🛡️ SAFETY AT LEAST",
"WHEN ARE YOU GOING?" (checked 2026-11-26 with Accessibility.getFullAXTree,
names read with and without text-transform; scripts/dev/ax_caps_check.mjs
repeats it on a local server). Each now carries its words as written in
aria-label; nothing on screen changed. app.js runs under jsc
(scripts/appjs_harness.js) on the markup itself.

    /usr/bin/python3 scripts/test_ax_caps.py

What it holds the code to:
  * every sort button (th.sortable .sortbtn) in public/index.html and in the
    served Top Picks table (fxtracker/home_picks.py, which
    test_home_picks.py holds to the grade tables app.js draws) is named by
    app.js nameSortBtn: its words in their written case, no emoji
    (aria-hidden), no ⓘ ([data-tip]) and, of a long/short pair (.lbl-lg /
    .lbl-sm), only the half on screen (computed display) — index.html's
    pinned word for word at desktop width and at phone width, where the
    two "vs avg" headers drop their "1-yr"/"10-yr" (WCAG 2.5.3: the name
    holds the words on screen);
  * the width crossing 600/601 or 374/375 (matchMedia change) renames every
    sort button, so a turned phone or a resized window gets the other half;
  * markSort names a button it wraps and one already there, wireSort names
    the page's at boot (and restoreShellText once a guide's words, served as
    comments, are back), and a header whose words change is renamed ("1 EUR
    =", "€100 buys", "Risks · US"); nameSortBtn(null) is a no-op;
  * every place app.js rewrites a sort button's words calls nameSortBtn
    next (source check);
  * no control is named by a label drawn in capitals: no aria-labelledby
    points at, and no <label> (for= or wrapping) of a class styles.css draws
    uppercase names, a control without its own aria-label; the Top Picks
    filters (Safety at least, Been-to, Show) and Help me choose's two
    questions say their words as written; its days box is named like Top
    Picks' (not by its placeholder "10").
"""
import html.parser, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import home_picks  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
read = lambda *a: open(P(*a), encoding="utf-8").read()
APP, INDEX, CSS = read("public", "app.js"), read("public", "index.html"), read("public", "styles.css")
HARNESS = read("scripts", "appjs_harness.js")

# index.html's sort buttons, by table and column, as a screen reader should hear them.
WANT = {
    "valueTable": {"country": "Country", "afford": "Affordability", "safety": "Safety", "weather": "Weather",
                   "flight": "Flights", "value": "Overall"},
    "rates": {"code": "Currency", "rate": "1 USD =", "vsavg": "vs 1-yr avg", "price": "Price level",
              "range": "Range position"},
    "affTable": {"name": "Country", "pl": "Price level", "vs": "vs 10-yr avg", "buys": "100 buys",
                 "range": "10-yr range"},
    "advTable": {"country": "Country", "level": "Level", "risks": "Risks", "health": "Health"},
    "flightTable": {"dest": "Destination country", "vs": "vs typical", "mfare": "Month fare",
                    "avg": "Avg round-trip", "min": "Cheapest", "dur": "Flight time", "stops": "Stops"},
}
SERVED_WANT = {"dest": "Destination", "afford": "Affordability", "safety": "Safety", "weather": "Weather",
               "flights": "Flights", "overall": "Overall"}


class Tree(html.parser.HTMLParser):
    """Markup → {"t":"e","tag","a","k"} / {"t":"x","v"} nodes, entities decoded."""
    VOID = {"br", "img", "input", "meta", "link", "hr", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"t": "e", "tag": "root", "a": {}, "k": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        n = {"t": "e", "tag": tag, "a": {k: (v if v is not None else "") for k, v in attrs}, "k": []}
        self.stack[-1]["k"].append(n)
        if tag not in self.VOID:
            self.stack.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, d):
        self.stack[-1]["k"].append({"t": "x", "v": d})


def parse(h):
    t = Tree()
    t.feed(h)
    t.close()
    return t.root


def walk(n):
    yield n
    for k in n.get("k", []):
        yield from walk(k)


def sort_ths(markup):
    """[(table id, data-sk, th node)] for every th.sortable, its table found by the nearest
    <table id=…> before it."""
    out = []
    for m in re.finditer(r'<th class="[^"]*\bsortable\b[^"]*"[^>]*>.*?</th>', markup, re.S):
        tid = re.findall(r'<table[^>]*\bid="([^"]+)"', markup[:m.start()])
        th = parse(m.group(0))["k"][0]
        out.append((tid[-1] if tid else "", th["a"].get("data-sk", ""), th))
    return out


IDX = sort_ths(INDEX)
SERVED = [("served", sk, th) for _, sk, th in sort_ths(home_picks._HEAD)]

# Before app.js: a matchMedia that keeps its change listeners, so the driver can cross a width.
PRE = r"""
var __mq = [];
window.matchMedia = function (q) {
  var o = { q: q, matches: false, fns: [], addEventListener: function (t, f) { if (t === "change") o.fns.push(f); },
            addListener: function (f) { o.fns.push(f); } };
  __mq.push(o); return o;
};
"""

DRIVER = r"""
const FIX = JSON.parse(read(FIX_PATH));
// The width, as styles.css draws the .lbl pairs: desktop shows .lbl-lg, a phone (375-600, or any
// width up to 600 inside #tab-data, where these headers live) shows .lbl-sm.
let narrow = false;
window.getComputedStyle = (el) => ({ getPropertyValue: () => "",
  display: el.classList && (narrow ? el.classList.contains("lbl-lg") : el.classList.contains("lbl-sm")) ? "none" : "inline" });
// A tiny DOM of real nodes (the harness's stubs have no tree): enough for nameSortBtn, markSort
// and wireSort.
function mk(spec, parent) {
  if (spec.t === "x") return { nodeType: 3, nodeValue: spec.v, parentNode: parent || null };
  const n = {
    nodeType: 1, tagName: spec.tag.toUpperCase(), a: Object.assign({}, spec.a), childNodes: [], parentNode: parent || null,
    dataset: {}, type: "",
    getAttribute(k) { return k in this.a ? this.a[k] : null; }, hasAttribute(k) { return k in this.a; },
    setAttribute(k, v) { this.a[k] = String(v); }, removeAttribute(k) { delete this.a[k]; },
    get className() { return this.a["class"] || ""; }, set className(v) { this.a["class"] = v; },
    get classList() { const self = this; return { contains: (c) => (self.a["class"] || "").split(/\s+/).includes(c) }; },
    get firstChild() { return this.childNodes[0] || null; },
    get textContent() { return this.childNodes.map((c) => c.nodeType === 3 ? c.nodeValue : c.textContent).join(""); },
    set textContent(v) { this.childNodes = [{ nodeType: 3, nodeValue: String(v), parentNode: this }]; },
    appendChild(c) { if (c.parentNode && c.parentNode.childNodes) { const i = c.parentNode.childNodes.indexOf(c); if (i >= 0) c.parentNode.childNodes.splice(i, 1); }
                     c.parentNode = this; this.childNodes.push(c); return c; },
    all() { const o = []; const w = (x) => x.childNodes.forEach((c) => { if (c.nodeType === 1) { o.push(c); w(c); } }); w(this); return o; },
    querySelector(sel) { const cls = sel.replace(/^\./, ""); return this.all().find((e) => e.classList.contains(cls)) || null; },
    closest(sel) { const cls = sel.replace(/^\./, ""); for (let e = this; e && e.nodeType === 1; e = e.parentNode) if (e.classList.contains(cls)) return e; return null; },
  };
  for (const k in n.a) if (k.startsWith("data-")) n.dataset[k.slice(5).replace(/-(\w)/g, (x, c) => c.toUpperCase())] = n.a[k];
  (spec.k || []).forEach((c) => n.childNodes.push(mk(c, n)));
  return n;
}
const label = (b) => b ? b.getAttribute("aria-label") : "(no button)";
const out = { buttons: [], phone: [], wrap: null, existing: null, boot: null, rewrite: {}, nullOk: null, width: {} };
const all = [];
for (const th of FIX.ths) {
  const t = mk(th.node); const b = t.querySelector(".sortbtn");
  nameSortBtn(b); all.push(b);
  out.buttons.push({ table: th.table, sk: th.sk, label: label(b), text: b ? b.textContent : null });
}
for (const [i, th] of FIX.ths.entries()) {   // the same buttons at phone width
  const b = mk(th.node).querySelector(".sortbtn");
  narrow = true; nameSortBtn(b); narrow = false;
  out.phone.push({ table: th.table, sk: th.sk, label: label(b) });
}
// Crossing a width: each query's change listeners alone, on the page's buttons plus a pair of each half.
const pair = mk(FIX.pairTh).querySelector(".sortbtn"); nameSortBtn(pair); all.push(pair);
const qsa0 = document.querySelectorAll;
document.querySelectorAll = (sel) => sel === "th.sortable .sortbtn" ? all : [];
const names = () => all.map(label);
for (const q of ["(max-width: 600px)", "(max-width: 374px)"]) {
  const fns = [].concat(...__mq.filter((m) => m.q === q).map((m) => m.fns));
  narrow = true; fns.forEach((f) => f({ matches: true })); const ph = names();
  narrow = false; fns.forEach((f) => f({ matches: false })); const dk = names();
  out.width[q] = { listeners: fns.length, phone: ph, desktop: dk };
}
document.querySelectorAll = qsa0;
// markSort: one th without a button (a grade table's, as renderGradeTable writes it), one with.
const bare = mk(FIX.bareTh), withBtn = mk(FIX.btnTh);
const qsa = document.querySelectorAll, ce = document.createElement;
document.createElement = (tag) => mk({ t: "e", tag: tag, a: {}, k: [] });
document.querySelectorAll = (sel) => sel === "#t th.sortable" ? [bare, withBtn] : sel === "#t th.sortable .sortbtn" ? [withBtn.querySelector(".sortbtn")] : [];
markSort("#t", { key: "afford", asc: false });
out.wrap = { label: label(bare.querySelector(".sortbtn")), sort: bare.getAttribute("aria-sort"), kids: bare.childNodes.length };
out.existing = { label: label(withBtn.querySelector(".sortbtn")), sort: withBtn.getAttribute("aria-sort") };
// wireSort at boot names what is already on the page.
withBtn.querySelector(".sortbtn").removeAttribute("aria-label");
wireSort("#t", { key: "afford", asc: false }, {}, () => {});
out.boot = label(withBtn.querySelector(".sortbtn"));
document.querySelectorAll = qsa; document.createElement = ce;
// A header whose words change, renamed the way renderRates/renderAfford/renderAdvisories do it.
const rate = mk(FIX.rateTh).querySelector(".sortbtn"); rate.textContent = "1 EUR ="; nameSortBtn(rate); out.rewrite.rate = label(rate);
const buys = mk(FIX.buysTh).querySelector(".sortbtn"); buys.textContent = "€100 buys"; nameSortBtn(buys); out.rewrite.buys = label(buys);
const risks = mk(FIX.risksTh); const rk = risks.all().find((e) => e.a.id === "riskLabel");
rk.textContent = "Risks · US"; nameSortBtn(rk.closest(".sortbtn")); out.rewrite.risks = label(risks.querySelector(".sortbtn"));
try { nameSortBtn(null); out.nullOk = true; } catch (e) { out.nullOk = String(e); }
print(JSON.stringify(out));
"""


def th_of(table, sk):
    return next(th for t, s, th in IDX if t == table and s == sk)


def run_jsc():
    bare = parse('<th class="sortable" data-sk="afford" title="x"><span aria-hidden="true">💰</span> '
                 '<span class="thword">Affordability</span></th>')["k"][0]
    btn = parse('<th class="sortable" data-sk="safety"><button type="button" class="sortbtn">'
                '<span aria-hidden="true">🛡️</span> <span class="thword">Safety</span></button></th>')["k"][0]
    pair = parse('<th class="sortable" data-sk="x"><button type="button" class="sortbtn">Show <span class="lbl-lg">'
                 'every row</span><span class="lbl-sm">all</span></button></th>')["k"][0]
    fix = {"ths": [{"table": t, "sk": s, "node": th} for t, s, th in IDX + SERVED], "bareTh": bare, "btnTh": btn, "pairTh": pair,
           "rateTh": th_of("rates", "rate"), "buysTh": th_of("affTable", "buys"), "risksTh": th_of("advTable", "risks")}
    with tempfile.TemporaryDirectory() as d:
        fp, sp = os.path.join(d, "fix.json"), os.path.join(d, "run.js")
        json.dump(fix, open(fp, "w"))
        open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + PRE + "\n" + APP + "\n"
                                              + DRIVER.replace("FIX_PATH", json.dumps(fp)))
        try:
            r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
            return json.loads(r.stdout.strip().splitlines()[-1]), r
        except Exception as e:
            return None, e


js, err = run_jsc()
results.append(ok(js is not None, "app.js runs under jsc with the harness (%s)" % ("ok" if js else err)))
if js is None:
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    sys.exit(1)

# --- every sort button, named in its written case ------------------------------------------
got = {}
for b in js["buttons"]:
    got.setdefault(b["table"], {})[b["sk"]] = b["label"]
want = dict(WANT, served=SERVED_WANT)
results.append(ok(got == want, "every sort button's name is its words as written: %d in index.html, %d in the served "
                  "Top Picks table %s" % (sum(len(v) for v in WANT.values()), len(SERVED_WANT),
                                          "" if got == want else {k: v for k, v in got.items() if want.get(k) != v})))
bad = [b for b in js["buttons"] if not b["label"] or "ⓘ" in b["label"] or re.search(r"[\U0001F300-\U0001FAFF☀-➿]", b["label"])
       or (b["label"] == b["label"].upper() and b["label"] != b["label"].lower() and b["text"].upper() != b["text"])]
results.append(ok(not bad, "no sort button's name is empty, carries an ⓘ or an emoji, or is in capitals its words "
                  "aren't written in %s" % (bad or "")))
# At phone width the two "vs avg" headers show "VS AVG": their name follows the screen; nothing else differs.
gotp = {}
for b in js["phone"]:
    gotp.setdefault(b["table"], {})[b["sk"]] = b["label"]
wantp = json.loads(json.dumps(want))
wantp["rates"]["vsavg"] = wantp["affTable"]["vs"] = "vs avg"
results.append(ok(gotp == wantp, "at phone width each name holds the words on screen: 'vs avg' for the two headers that "
                  "drop their '1-yr'/'10-yr', the rest as on desktop %s"
                  % ("" if gotp == wantp else {k: v for k, v in gotp.items() if wantp.get(k) != v})))
n = len(js["buttons"])
dk_all = [b["label"] for b in js["buttons"]] + ["Show every row"]
ph_all = [b["label"] for b in js["phone"]] + ["Show all"]
wd = js["width"]
results.append(ok(all(wd[q]["listeners"] >= 1 and wd[q]["phone"] == ph_all and wd[q]["desktop"] == dk_all
                      for q in ("(max-width: 600px)", "(max-width: 374px)")),
                  "crossing 600/601 or 374/375 renames every sort button to the half on screen (%d buttons + a "
                  "long/short pair; listeners %s)" % (n, {q: v["listeners"] for q, v in wd.items()})))
vs = [b["text"] for b in js["buttons"] if b["sk"] in ("vsavg", "vs") and b["table"] in ("rates", "affTable")]
results.append(ok(len(vs) == 2 and all("ⓘ" in t for t in vs),
                  "the two 'vs avg' buttons hold an ⓘ in their markup, kept out of the name (%s)" % vs))

# --- markSort, wireSort, renamed headers ----------------------------------------------------
results.append(ok(js["wrap"] == {"label": "Affordability", "sort": "descending", "kids": 1},
                  "markSort wraps a bare th's words in a button and names it: %s" % js["wrap"]))
results.append(ok(js["existing"] == {"label": "Safety", "sort": "none"},
                  "markSort names a button already in the th: %s" % js["existing"]))
results.append(ok(js["boot"] == "Safety", "wireSort names the page's sort buttons at boot: %r" % js["boot"]))
results.append(ok(js["rewrite"] == {"rate": "1 EUR =", "buys": "€100 buys", "risks": "Risks · US"},
                  "a header whose words change is renamed: %s" % js["rewrite"]))
results.append(ok(js["nullOk"] is True, "nameSortBtn(null) does nothing (%s)" % js["nullOk"]))


# --- every rewrite of a sort button's words calls nameSortBtn next ---------------------------
def fn_body(name):
    m = re.search(r"\nfunction %s\(.*?\n\}\n" % name, APP, re.S)
    return m.group(0) if m else ""


results.append(ok("nameSortBtn(b);" in fn_body("markSort") and "nameSortBtn(b)" in fn_body("wireSort")
                  and "nameSortBtn(b)" in fn_body("restoreShellText"),
                  "markSort names every sort button it marks; wireSort names the page's at boot, restoreShellText "
                  "once a guide's words are back"))
lines = APP.split("\n")
inner_ids = sorted({n["a"]["id"] for _, _, th in IDX for b in walk(th) if b.get("tag") == "button"
                    for n in walk(b) if n is not b and n.get("a", {}).get("id")})
vars_ = set(re.findall(r"const (\w+) = [^;\n]*querySelector\([^;\n]*sortbtn[^;\n]*\);", APP))
for i in inner_ids:
    vars_ |= set(re.findall(r'const (\w+) = \$\("%s"\);' % re.escape(i), APP))
writes = []
for k, ln in enumerate(lines):
    direct = re.search(r'\.sortbtn"\)[^;]*\)\.(?:textContent|innerHTML)\s*=', ln)
    byvar = any(re.search(r"\b%s\.(?:textContent|innerHTML)\s*=" % re.escape(v), ln) for v in vars_)
    byid = any(re.search(r'\$\("%s"\)\.(?:textContent|innerHTML)\s*=' % re.escape(i), ln) for i in inner_ids)
    if direct or byvar or byid:
        writes.append((k + 1, "nameSortBtn(" in ln or (k + 1 < len(lines) and "nameSortBtn(" in lines[k + 1])))
results.append(ok(len(writes) >= 4 and all(w for _, w in writes),
                  "every place app.js rewrites a sort button's words (%d: lines %s; ids inside buttons %s) renames it "
                  "next %s" % (len(writes), [n for n, _ in writes], inner_ids, [n for n, w in writes if not w] or "")))

# --- no control named by a label drawn in capitals -------------------------------------------
upper = set()
for sel, body in re.findall(r"([^{}]+)\{([^{}]*)\}", re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)):
    if re.search(r"text-transform:\s*uppercase", body):
        for s in sel.split(","):
            last = s.strip().split()[-1] if s.strip() else ""
            upper |= set(re.findall(r"\.([\w-]+)", last.split("::")[0]))
results.append(ok({"picklabel", "gqlabel", "tbhdr"} <= upper,
                  "styles.css draws these label classes in capitals: %s" % sorted(upper)))


def upcls(attrs):
    """The classes in a tag's attributes that styles.css draws in capitals."""
    m = re.search(r'class="([^"]*)"', attrs)
    return set(m.group(1).split()) & upper if m else set()


SOURCES = {"index.html": INDEX, "app.js": APP}
problems, seen = [], {"labelledby": 0, "labelfor": 0, "wrap": 0}
for name, src in SOURCES.items():
    for ref in re.findall(r'aria-labelledby="([^"$]+)"', src):
        for one in ref.split():
            m = re.search(r'<\w+([^>]*\bid="%s"[^>]*)>' % re.escape(one), src)
            seen["labelledby"] += 1
            if m and upcls(m.group(1)):
                problems.append("%s: aria-labelledby=%s, a %s label" % (name, one, upcls(m.group(1))))
    for m in re.finditer(r'<label((?:\s+[\w-]+="[^"]*")*)\s*>(.*?)</label>', src, re.S):
        if not upcls(m.group(1)):
            continue
        f = re.search(r'\bfor="([^"]+)"', m.group(1))
        if f:
            seen["labelfor"] += 1
            c = re.search(r'<(?:input|select|textarea)\b[^>]*\bid="%s"[^>]*>' % re.escape(f.group(1)), src)
            if not c or "aria-label=" not in c.group(0):
                problems.append("%s: <label for=%s> of class %s names it" % (name, f.group(1), upcls(m.group(1))))
        for c in re.findall(r"<(?:input|select|textarea)\b[^>]*>", m.group(2)):
            seen["wrap"] += 1
            if "aria-label=" not in c:
                problems.append("%s: a %s label wraps %s" % (name, upcls(m.group(1)), c[:60]))
results.append(ok(not problems and seen["labelfor"] >= 2,
                  "no control takes its name from a label drawn in capitals (checked %s) %s" % (seen, problems or "")))


def attr(src, idv, a):
    m = re.search(r'<\w+[^>]*\bid="%s"[^>]*>' % re.escape(idv), src)
    v = m and re.search(r'\b%s="([^"]*)"' % a, m.group(0))
    return v.group(1) if v else None


pins = {i: attr(INDEX, i, "aria-label") for i in ("safeFloor", "beenFilter", "pickCount")}
results.append(ok(pins == {"safeFloor": "Safety at least", "beenFilter": "Been-to", "pickCount": "Show"}
                  and not any(attr(INDEX, i, "aria-labelledby") for i in pins),
                  "the Top Picks filters say their words as written, no emoji: %s" % pins))
q = {i: (attr(APP, i, "aria-label"), re.search(r'<label class="gqlabel" for="%s">([^<]*)</label>' % i, APP))
     for i in ("gqMonth", "gqBudget")}
results.append(ok(all(a and l and a == l.group(1) for a, l in q.values()),
                  "Help me choose's two questions are named by their label's words as written: %s"
                  % {i: a for i, (a, _) in q.items()}))
days = (attr(APP, "gqDays", "aria-label"), attr(INDEX, "budgetDays", "aria-label"))
results.append(ok(days[0] and days[0] == days[1] == "Trip length in days",
                  "Help me choose's days box is named like Top Picks' (not by its placeholder '10'): %s" % (days,)))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
