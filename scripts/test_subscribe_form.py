#!/usr/bin/env python3
"""The newsletter signup forms in public/app.js (review #8), run under jsc
from the app's own functions — no browser, no network.

    /usr/bin/python3 scripts/test_subscribe_form.py

What it holds the code to:
  * both of subscribeFormHTML's forms (the USD-only box and the currency
    picker's) post straight to Buttondown's embed endpoint in a new tab
    (method post, target _blank, embed=1), with no window.open popup and no
    "popupwindow" target: an in-app browser that blocks a scripted popup
    (Instagram's on iOS) left the signup going nowhere;
  * submitting no longer marks the visitor subscribed for good: it snoozes
    the automatic invite for 60 days (wg_sub_sent, a timestamp), after which
    the invite may come again; a dismissal still re-arms after 30 days;
  * the old permanent mark (wg_sub_done = "1") is read once and becomes a
    snooze from that day, then removed;
  * site data blocked (localStorage throwing): nothing is counted as sent;
  * the list pages' server-rendered box is the same form (render_lists).
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts", "parity"))
import build_js  # noqa: E402  (scripts/parity: lifts declarations out of app.js)
from fxtracker import render_lists as RL  # noqa: E402

JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()

DAY = 24 * 60 * 60 * 1000
DECLS = ["const BUTTONDOWN_USER", "const SUB_SENT_KEY", "const SUB_SNOOZE_MS", "const SUB_DONE_KEY",
         "const SUB_DISMISS_KEY", "const SUB_REARM_MS", "function subSentAt", "function subDone",
         "function snoozeAfterSignup", "function markDismissed", "function shouldAutoPrompt"]


def _fn(src, name, nxt):
    """A top-level function by its text, from its line to the next
    declaration's (build_js._cut stops short of this one's nested template
    strings)."""
    i = src.index("\nfunction %s(" % name) + 1
    return src[i:src.index("\n" + nxt, i)]


FORM_FN = _fn(APP, "subscribeFormHTML", "function renderSubscribe")


def jsc(body):
    """Run `body` after the lifted declarations, with a stand-in
    localStorage and clock; the last printed line is JSON."""
    prelude = r"""
let NOW = 1795000000000;
Date.now = () => NOW;
let STORE = {}, BLOCKED = false;
const localStorage = {
  getItem: (k) => { if (BLOCKED) throw new Error("blocked"); return k in STORE ? STORE[k] : null; },
  setItem: (k, v) => { if (BLOCKED) throw new Error("blocked"); STORE[k] = String(v); },
  removeItem: (k) => { if (BLOCKED) throw new Error("blocked"); delete STORE[k]; },
};
const window = {};
let CURS = ["USD"];
const digestCurs = () => CURS;
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
const subCurOptions = () => '<option value="USD">USD</option>';
const subCurDefault = () => "USD";
"""
    src = prelude + "\n".join(build_js._cut(APP, d) for d in DECLS) + "\n" + FORM_FN + "\n" + body
    fd, path = tempfile.mkstemp(suffix=".js")   # a file: jsc reading stdin echoes each statement's value
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        out = subprocess.run([JSC, path], capture_output=True, text=True, timeout=30)
    finally:
        os.remove(path)
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit("jsc failed:\n%s\n%s" % (out.stdout[-2000:], out.stderr[-2000:]))
    return json.loads(out.stdout.strip().splitlines()[-1])


r = jsc(r"""
const usd = subscribeFormHTML();
CURS = ["USD", "EUR"];
const cur = subscribeFormHTML();
const res = {usd, cur};
// A fresh visitor: invited.
STORE = {}; res.fresh = shouldAutoPrompt();
// Submit: snoozed now, and still at 59 days; invited again at 61.
snoozeAfterSignup(); res.sent = STORE.wg_sub_sent; res.d0 = shouldAutoPrompt(); res.done0 = subDone();
NOW += 59 * 86400000; res.d59 = shouldAutoPrompt();
NOW += 2 * 86400000; res.d61 = shouldAutoPrompt(); res.done61 = subDone();
// A dismissal still re-arms after 30 days.
STORE = {}; markDismissed(); NOW += 29 * 86400000; res.dis29 = shouldAutoPrompt();
NOW += 2 * 86400000; res.dis31 = shouldAutoPrompt();
// The old permanent mark: a snooze from today, the old key gone.
STORE = {wg_sub_done: "1"}; const t0 = NOW;
res.legacy0 = shouldAutoPrompt(); res.legacyKeys = Object.keys(STORE).sort(); res.legacySent = +STORE.wg_sub_sent === t0;
NOW += 61 * 86400000; res.legacy61 = shouldAutoPrompt();
// Site data blocked: never counted as sent (and no throw).
BLOCKED = true; res.blockedDone = subDone(); snoozeAfterSignup(); BLOCKED = false;
print(JSON.stringify(res));
""")

forms = re.findall(r"<form\b[^>]*>", r["usd"]) + re.findall(r"<form\b[^>]*>", r["cur"])
want_action = 'action="https://buttondown.com/api/emails/embed-subscribe/%s"' % RL.BUTTONDOWN_USER
results.append(ok(len(forms) == 2 and all(want_action in f and 'method="post"' in f and 'target="_blank"' in f
                                          and "onsubmit" not in f and "popupwindow" not in f for f in forms),
                  "both forms post to Buttondown's embed endpoint in a new tab, no onsubmit popup: %s"
                  % [re.sub(r"\s+", " ", f) for f in forms]))
results.append(ok(all('<input type="hidden" name="embed" value="1">' in h for h in (r["usd"], r["cur"]))
                  and "window.open" not in r["usd"] + r["cur"]
                  and 'name="tag"' in r["cur"] and 'name="tag"' not in r["usd"],
                  "embed=1 on both, the currency picker only on the multi-edition form, no window.open"))
fn = FORM_FN
results.append(ok("window.open" not in fn and "popupwindow" not in fn and "popupwindow" not in APP,
                  "no popup anywhere in app.js's signup code"))
results.append(ok(r["fresh"] and not r["d0"] and r["done0"] and not r["d59"] and r["d61"] and not r["done61"]
                  and r["sent"] == "1795000000000",
                  "a submit snoozes the invite 60 days (a timestamp), not for good: off at 0 and 59 days, back at 61"))
results.append(ok(not r["dis29"] and r["dis31"], "a dismissal still re-arms after 30 days"))
results.append(ok(not r["legacy0"] and r["legacyKeys"] == ["wg_sub_sent"] and r["legacySent"] and r["legacy61"],
                  "the old permanent wg_sub_done=1 becomes a snooze from today and is removed; invited again after 60 days"))
results.append(ok(r["blockedDone"] is False, "site data blocked: nothing counted as sent, no exception"))
results.append(ok("const SUB_SNOOZE_MS = 60 * 24 * 60 * 60 * 1000;" in APP
                  and 'f.addEventListener("submit", snoozeAfterSignup)' in APP and "markSubscribed" not in APP,
                  "the forms' submit handler is the 60-day snooze"))
box = RL.subscribe_html()
results.append(ok(re.search(r"<form\b[^>]*>", box).group(0)
                  == '<form action="https://buttondown.com/api/emails/embed-subscribe/%s" method="post" '
                     'target="_blank" class="subform">' % RL.BUTTONDOWN_USER,
                  "the list pages' box is the same form (render_lists.subscribe_html)"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
