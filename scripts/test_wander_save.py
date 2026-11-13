"""The Wander List's "👤 Save this map" button: ONE element (#visitedSaveRow,
class .vsave) that styles.css puts over the map's top-right corner from 561px
up and on a line of its own just above the map on phones, never back in the
stats column — and the line a phone reserves for it at first paint follows
the same rule the button shows by. No network, no server process.

    /usr/bin/python3 scripts/test_wander_save.py

What it holds the code to:
  * index.html: exactly one .vsave, served empty, the first child of
    .vmapwrap with #visitedMap right after it (drawMap rewrites the map's own
    innerHTML on every render, so the button can't live inside it); the
    homepage and a guide each serve exactly one, still empty;
  * app.js: one `id="visitedSave"` template; renderVisitedStats, run under
    jsc for accounts on/off x signed in/out x every been/want-to-go mix,
    writes the button into #visitedSaveRow exactly when
    ACCT_ON && !acctSignedIn() && (been || want to go), with the same label
    and ⓘ words as before, never anything into #visitedStats, and empties the
    row when the rule stops holding (clear all, sign-in);
  * server.py VISITED_HOLD, run under jsc: html[data-vis] carries "s" exactly
    when the button will show (accounts on, data-acct not "in", any mark),
    which is the button's rule with the head script's sign-in flag standing
    in for acctSignedIn();
  * styles.css: the stats floor no longer grows for "s" (that was the old
    box under the stats); the phone line is reserved only for "s" (inside the
    max-width: 560px block) and an empty .vsave is otherwise display:none;
    from 561px up .vsave is absolute, top 10px, right 50px, 32px tall (the
    map's zoom column: top 10px, right 10px, 32px buttons, 8px gap).
"""
import json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
HTML = open(os.path.join(ROOT, "public", "index.html"), encoding="utf-8").read()
CSS = open(os.path.join(ROOT, "public", "styles.css"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_fn_const(name):
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def jsc(prog):
    try:
        out = subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout)
    except Exception:
        return None


# --- index.html ------------------------------------------------------------------
results.append(ok(len(re.findall(r'class="vsave"', HTML)) == 1 and HTML.count('id="visitedSaveRow"') == 1,
                  "index.html has exactly one .vsave (#visitedSaveRow)"))
wrap = re.search(r'<div class="vrow">\s*<div class="vmapwrap">\s*'
                 r'<div id="visitedSaveRow" class="vsave"></div>\s*'
                 r'<div id="visitedMap" class="map">Loading…</div>\s*</div>\s*'
                 r'<div id="visitedStats" class="visitedstats">\{\{VISITED_STATS\}\}</div>\s*</div>', HTML)
results.append(ok(bool(wrap), ".vrow = .vmapwrap (empty #visitedSaveRow, then #visitedMap) + #visitedStats"))

import server  # noqa: E402
for label, gc in (("homepage", None), ("a guide (TH)", "TH")):
    page = server._render_index(gc).decode("utf-8")
    rows = re.findall(r'<div id="visitedSaveRow" class="vsave">(.*?)</div>', page, re.S)
    results.append(ok(len(rows) == 1 and rows[0] == "" and page.count('class="vsave"') == 1
                      and "visitedSave\"" not in page,
                      "%s serves one empty #visitedSaveRow and no button" % label))

# --- app.js: the button and its rule ---------------------------------------------
results.append(ok(APP.count('id="visitedSave"') == 1, 'app.js has one id="visitedSave" template'))
results.append(ok("vsave" not in re.sub(r"//[^\n]*", "", js_fn("renderVisitedStats")).split("host.innerHTML", 1)[-1]
                  .split("host.onclick", 1)[0],
                  "nothing .vsave is appended to #visitedStats's innerHTML"))
tiers = re.search(r"^const MILESTONE_TIERS = \[.*?\];", APP, re.M | re.S)
HARNESS = r"""
const hosts = {};
// document.getElementById as far as renderVisitedStats sees it: the two hosts
// always exist; the button only once some host's markup holds it.
const $ = (id) => {
  if (id !== "visitedSave") return hosts[id] || (hosts[id] = { innerHTML: "", onclick: null });
  const there = Object.keys(hosts).some((k) => k !== "visitedSave" && /id="visitedSave"/.test(hosts[k].innerHTML || ""));
  return there ? (hosts.visitedSave || (hosts.visitedSave = { onclick: null })) : null;
};
const visited = new Set(%(v)s), wishlist = new Set(%(w)s);
const ACCT_ON = %(acct)s;
const acctSignedIn = () => %(signed)s;
let signInOpened = 0;
const openSignIn = () => { signInOpened++; };
const contFilter = null, WORLD_PCT_TIP = "tip";
const visitedContinents = () => 1, worldPct = () => 2, continentProgress = () => [];
const milestoneInfo = () => ({ earned: null, next: null });
const setContFilter = () => {};
%(esc)s
%(tiers)s
%(fn)s
hosts.visitedSaveRow = { innerHTML: "<b>stale</b>" };   // a previous render's button
renderVisitedStats();
const btn = hosts.visitedSave;
if (btn && btn.onclick) btn.onclick();
print(JSON.stringify({ stats: hosts.visitedStats.innerHTML, save: hosts.visitedSaveRow.innerHTML,
                       opened: signInOpened }));
"""
bad = []
cases = 0
for acct in (True, False):
    for signed in (True, False):
        for v, w in (([], []), (["FR", "DE", "IT"], []), ([], ["JP", "PE"]), (["FR", "DE", "IT"], ["JP", "PE"]),
                     (["FR"], ["FR"])):
            cases += 1
            r = jsc(HARNESS % {"v": json.dumps(v), "w": json.dumps(w), "acct": str(acct).lower(),
                               "signed": str(signed).lower(), "esc": js_fn_const("esc"),
                               "tiers": tiers.group(0) if tiers else "", "fn": js_fn("renderVisitedStats")})
            shows = acct and not signed and bool(v or w)
            n, m = len(v), len(w)
            words = ("Saved in this browser only. Sign in to keep your "
                     + ("%d been" % n if n else "") + (" + " if n and m else "")
                     + ("%d want to go" % m if m else "") + " on every device.")
            want = ('<button type="button" id="visitedSave">👤 Save this map</button>'
                    '<span class="muted" data-tip="%s" title="">ⓘ</span>' % words) if shows else ""
            if (not r or "visitedSave" in r["stats"] or "vsave" in r["stats"] or r["save"] != want
                    or r["opened"] != (1 if shows else 0)):
                bad.append(((acct, signed, n, m), r))
results.append(ok(cases == 20 and not bad,
                  "renderVisitedStats: button in #visitedSaveRow iff ACCT_ON && !signed in && (been || want), "
                  "same label and ⓘ words, opens sign-in, never in #visitedStats (%d cases)%s"
                  % (cases, "" if not bad else " %s" % bad[:3])))

# --- server.py VISITED_HOLD: the first-paint "s" ---------------------------------
hold = server._HTML_DEFAULTS["VISITED_HOLD"]
body = re.fullmatch(r"<script>(.*)</script>", hold, re.S)
flag = re.findall(r"\((true|false)&&d\.getAttribute\(\"data-acct\"\)!==\"in\"", hold)
results.append(ok(bool(body) and len(flag) == 1, "VISITED_HOLD is one script with one accounts-on flag"))
bad = []
cases = 0
for acct in (True, False):
    script = re.sub(r"\((?:true|false)&&d\.getAttribute", "(%s&&d.getAttribute" % str(acct).lower(),
                    body.group(1)) if body else ""
    for signed in (True, False):
        for v, w in (([], []), (["FR"], []), ([], ["JP"]), (["FR"], ["JP"])):
            cases += 1
            prog = ("var attrs = %s; var store = %s;\n"
                    "var document = { documentElement: { getAttribute: function (k) { return k in attrs ? attrs[k] : null; },"
                    " setAttribute: function (k, x) { attrs[k] = String(x); } } };\n"
                    "var localStorage = { getItem: function (k) { return k in store ? store[k] : null; } };\n"
                    "%s\nprint(JSON.stringify(attrs['data-vis'] || ''));"
                    % (json.dumps({"data-acct": "in"} if signed else {}),
                       json.dumps({"fx_visited": json.dumps(v), "fx_wishlist": json.dumps(w)}), script))
            got = jsc(prog)
            shows = acct and not signed and bool(v or w)
            if got is None or ("s" in got) != shows or (bool(got) != bool(v or w)):
                bad.append(((acct, signed, v, w), got))
results.append(ok(cases == 16 and not bad,
                  'VISITED_HOLD sets "s" exactly when the button will show (%d cases)%s'
                  % (cases, "" if not bad else " %s" % bad[:3])))


# --- styles.css --------------------------------------------------------------------
def css_rules(text):
    """(media prelude or "", selector, body) for every rule, one level of @media."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out, i, media = [], 0, [""]
    depth_media = []
    buf = ""
    while i < len(text):
        c = text[i]
        if c == "{":
            sel = buf.strip()
            buf = ""
            if sel.startswith("@media"):
                media.append(sel)
                depth_media.append(True)
            else:
                j = text.index("}", i)
                out.append((media[-1], sel, text[i + 1:j]))
                i = j
        elif c == "}":
            buf = ""
            if depth_media:
                depth_media.pop()
                media.pop()
        else:
            buf += c
        i += 1
    return out


RULES = css_rules(CSS)
stats_s = [(m, s) for m, s, b in RULES if "#visitedStats" in s and 'data-vis*="s"' in s]
results.append(ok(not stats_s, 'no #visitedStats floor grows for "s" any more %s' % (stats_s or "")))
reserve = [(m, s, b) for m, s, b in RULES if re.search(r'html\[data-vis\*="s"\] \.vsave:empty', s)]
results.append(ok(len(reserve) == 1 and "max-width: 560px" in reserve[0][0] and "min-width" not in reserve[0][0]
                  and re.search(r"display:\s*flex", reserve[0][2]),
                  'the phone line is reserved for "s" only, inside max-width: 560px'))
empty = [(m, b) for m, s, b in RULES if re.fullmatch(r"\.vsave:empty", s)]
results.append(ok(len(empty) == 1 and empty[0][0] == "" and re.search(r"display:\s*none", empty[0][1]),
                  ".vsave:empty is display:none everywhere else"))
base = [b for m, s, b in RULES if s == ".vsave" and m == ""]
decl = dict((k.strip(), v.strip()) for k, v in (d.split(":", 1) for d in (base[0] if base else "").split(";") if ":" in d))
results.append(ok(decl.get("position") == "absolute" and decl.get("top") == "10px" and decl.get("right") == "50px"
                  and decl.get("height") == "32px",
                  ".vsave from 561px up: absolute, top 10px, right 50px, 32px tall %s" % decl))
phone = [b for m, s, b in RULES if s == ".vsave" and "max-width: 560px" in m]
results.append(ok(phone and re.search(r"position:\s*static", phone[0]) and re.search(r"margin:\s*0 0 8px", phone[0]),
                  ".vsave on phones: in the flow, 8px above the map"))
wrapr = [b for m, s, b in RULES if s == ".vmapwrap" and m == ""]
results.append(ok(wrapr and re.search(r"position:\s*relative", wrapr[0])
                  and not [s for m, s, b in RULES if re.search(r"\.vrow\s*>\s*\.map", s)],
                  ".vmapwrap is the positioned box; no rule still expects the map as .vrow's child"))

passed = sum(1 for r in results if r)
print("\n%d/%d passed" % (passed, len(results)))
sys.exit(0 if passed == len(results) else 1)
