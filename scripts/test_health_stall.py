#!/usr/bin/env python3
"""The /healthz stall fixes (Render "health check timed out", 2026-11-10 and
2026-11-16) — offline, no server process, a few seconds.

    /usr/bin/python3 scripts/test_health_stall.py

What it holds the code to:
  * fxtracker/advisories.py FEED_MEMO_TTL: with the memo on, refreshing the
    three lists (get_advisories for us, ca and de, each reading the other two
    as gap-fills) parses each feed exactly once, and concurrent callers wait
    for the one parse in flight; the lists come out equal to the memo-off
    ones; every caller gets its own copy (mutating one list leaves the next
    untouched); a parse that raises is not kept; an expired memo parses
    again; at 0 (the default, what the newsletter build gets) every call
    parses, as before.
"""
import copy
import inspect
import os
import re
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories as A  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def item(iso, level, **kw):
    return dict({"iso": iso, "country": iso, "level": level, "level_text": "", "link": "https://x/" + iso}, **kw)


ROWS = {
    "us": [item("BF", 4), item("JP", 1), item("SA", 3, risks=["terrorism"])],
    "ca": [item("BF", 4), item("JP", 1), item("SA", 3), item("VE", 4), item("PS", 4)],
    "de": [item("BF", 2), item("SA", 4), item("VE", 2), item("MO", 1)],
}
calls = {"us": 0, "ca": 0, "de": 0}
gate = {"delay": 0.0, "fail": set()}


def parser(src):
    def run():
        calls[src] += 1
        if gate["delay"]:
            time.sleep(gate["delay"])
        if src in gate["fail"]:
            gate["fail"].discard(src)
            raise RuntimeError("feed %s down" % src)
        rows = copy.deepcopy(ROWS[src])
        return {"items": rows, "count": len(rows), "matched": len(rows), "source": src,
                "source_name": A.SOURCES[src], "source_url": "https://x/" + src}
    return run


A._us_advisories, A._canadian_advisories, A._german_advisories = parser("us"), parser("ca"), parser("de")


def reset(ttl):
    A.FEED_MEMO_TTL = ttl
    A._feed_memo.clear()
    for k in calls:
        calls[k] = 0


def refresh_all():
    return {s: A.get_advisories(s) for s in ("us", "ca", "de")}


# --- advisories.py: one parse per feed, shared -------------------------------------
results.append(ok(A.FEED_MEMO_TTL == 0, "the memo is off by default (the newsletter build never imports server)"))
for f in ("check.py", "send_digest.py", os.path.join("fxtracker", "picks.py")):
    src = open(os.path.join(ROOT, f), encoding="utf-8").read()
    results.append(ok("import server" not in src and "FEED_MEMO_TTL" not in src,
                      "%s neither imports server nor turns the memo on" % f))

reset(0)
off = refresh_all()
results.append(ok(calls == {"us": 3, "ca": 3, "de": 3},
                  "memo off: a refresh of the three lists parses each feed three times, as before (%s)" % calls))
off2 = refresh_all()
results.append(ok(calls == {"us": 6, "ca": 6, "de": 6}, "memo off: every call parses (%s)" % calls))

reset(120)
on = refresh_all()
results.append(ok(calls == {"us": 1, "ca": 1, "de": 1},
                  "memo on: a refresh of the three lists parses each feed once (%s)" % calls))
results.append(ok(on == off and off == off2 and [on[x]["filled"] for x in ("us", "ca", "de")] == [3, 1, 2],
                  "memo on: the three lists are equal to the memo-off ones"))
on["us"]["items"][0]["level"] = 1
on["us"]["items"].append(item("XX", 4))
on["us"]["items"][-2].setdefault("risks", []).append("mutated")
again = refresh_all()
results.append(ok(again == off and calls == {"us": 1, "ca": 1, "de": 1},
                  "mutating one list leaves the next untouched (still one parse each)"))
a, b = A._from_shared("us"), A._from_shared("us")
results.append(ok(a == b and a is not b and a["items"] is not b["items"] and a["items"][0] is not b["items"][0],
                  "each caller gets its own deep copy"))

reset(120)
gate["fail"] = {"us"}
try:
    A.get_advisories("us")
    raised = False
except RuntimeError:
    raised = True
first = calls["us"]
got = A.get_advisories("us")
results.append(ok(raised and first == 1 and calls["us"] == 2 and got == off["us"],
                  "a parse that raises is not kept: the next caller parses again (%s)" % calls))
reset(120)
gate["fail"] = {"ca"}
us = A.get_advisories("us")
results.append(ok(us["filled"] == 2 and calls["ca"] == 1 and A.get_advisories("ca") == off["ca"] and calls["ca"] == 2,
                  "a gap-fill feed that raises is skipped as before and parsed again next time (%s)" % calls))

reset(120)
A.get_advisories("us")
for s in list(A._feed_memo):
    at, data = A._feed_memo[s]
    A._feed_memo[s] = (at - 121, data)
A.get_advisories("us")
results.append(ok(calls == {"us": 2, "ca": 2, "de": 2}, "an expired memo parses again (%s)" % calls))

reset(120)
gate["delay"] = 0.3
out, ths = [], [threading.Thread(target=lambda: out.append(A.get_advisories("us"))) for _ in range(8)]
t0 = time.time()
for t in ths:
    t.start()
for t in ths:
    t.join(10)
took = time.time() - t0
gate["delay"] = 0.0
results.append(ok(len(out) == 8 and all(o == off["us"] for o in out) and calls == {"us": 1, "ca": 1, "de": 1}
                  and took < 2.0,
                  "8 concurrent callers wait for the one parse in flight: one parse each, same lists (%.2fs, %s)"
                  % (took, calls)))
reset(0)
import server  # noqa: E402
m = re.search(r"advisories\.FEED_MEMO_TTL = (\d+)", inspect.getsource(server.main))
results.append(ok(bool(m) and int(m.group(1)) > 0 and A.FEED_MEMO_TTL == 0,
                  "server.main() turns the memo on (%s s); importing server leaves it off" % (m and m.group(1))))

print("\n%d/%d passed" % (sum(bool(r) for r in results), len(results)))
sys.exit(0 if all(results) else 1)
