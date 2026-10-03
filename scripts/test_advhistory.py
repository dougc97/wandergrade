"""Exercise fxtracker/advhistory.py — the advisory-level record behind the
`changed` / `change` stamps on /api/advisories items — first in memory, then
against scripts/mock_upstash.py, so nothing leaves this machine.

    python3 scripts/test_advhistory.py
    (the mock is started in-process on MOCK_UPSTASH_PORT, default 8931; if
     something already listens there it is used as the mock instead)
"""
import json, os, sys, threading
from http.server import HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
for k in ("UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(k, None)     # memory first; never the real store

from fxtracker import accounts, advhistory as H

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def item(iso, level, **kw):
    return dict({"iso": iso, "country": iso, "level": level, "level_text": "", "link": ""}, **kw)


def run(source, rows, today):
    return {it["iso"]: it for it in H.record_and_annotate(source, {"items": rows}, today)["items"]
            if it.get("iso")}


def fresh():
    H._mem.clear()


# --- memory ---------------------------------------------------------------------
print("memory (no Upstash configured):", not accounts.storage_configured())
fresh()
out = run("ca", [item("MX", 2), item("FR", 2), item("JP", 1)], "2026-10-01")
results.append(ok(not any("changed" in r or "change" in r for r in out.values()),
                  "first-ever run is a baseline: nothing stamped"))
results.append(ok(json.loads(H._mem["advlvl:ca"]) == {"MX": [2, "2026-10-01"], "FR": [2, "2026-10-01"],
                                                         "JP": [1, "2026-10-01"]},
                  "baseline recorded as {iso: [level, since]}"))
results.append(ok("advchg:ca" not in H._mem, "baseline logs no changes"))

out = run("ca", [item("MX", 3), item("FR", 2), item("JP", 1)], "2026-10-05")
results.append(ok(out["MX"].get("changed") == "2026-10-05" and out["MX"].get("change") == "up",
                  "a raised level: changed = the day seen, change = up"))
results.append(ok("changed" not in out["FR"] and "change" not in out["FR"],
                  "an unchanged level stays unstamped"))
results.append(ok(json.loads(H._mem["advchg:ca"]) == [{"iso": "MX", "from": 2, "to": 3, "date": "2026-10-05"}],
                  "the change is logged {iso, from, to, date}"))

out = run("ca", [item("MX", 3), item("FR", 1), item("JP", 1)], "2026-10-09")
results.append(ok(out["FR"].get("change") == "down" and out["FR"].get("changed") == "2026-10-09",
                  "a lowered level: change = down"))
results.append(ok(out["MX"].get("changed") == "2026-10-05" and out["MX"].get("change") == "up",
                  "an earlier change keeps its date on later fetches"))

# Disappearing ISO: the US feed drops countries between fetches.
out = run("ca", [item("MX", 3), item("FR", 1)], "2026-10-10")
lv = json.loads(H._mem["advlvl:ca"])
results.append(ok(lv.get("JP") == [1, "2026-10-01"], "a country missing from a fetch keeps its record"))
out = run("ca", [item("MX", 3), item("FR", 1), item("JP", 1)], "2026-10-11")
results.append(ok("changed" not in out["JP"], "...and its return at the same level is no change"))
out = run("ca", [item("MX", 3), item("FR", 1), item("JP", 2)], "2026-10-12")
results.append(ok(out["JP"].get("change") == "up", "...while a return at another level is one"))

# A country the feed starts listing after the baseline is not a change.
out = run("ca", [item("MX", 3), item("FR", 1), item("JP", 2), item("BR", 2)], "2026-10-13")
results.append(ok("changed" not in out["BR"] and json.loads(H._mem["advlvl:ca"])["BR"] == [2, "2026-10-13"],
                  "a newly listed country is recorded, not stamped"))

# Gap-fills from another government are not this source's levels.
out = run("ca", [item("MX", 3), item("PS", 4, via="us", via_name="U.S. State Department")], "2026-10-14")
results.append(ok("PS" not in json.loads(H._mem["advlvl:ca"]) and "changed" not in out["PS"],
                  "via items are neither recorded nor stamped"))
out = run("ca", [item("MX", 3), item("PS", 2, via="de", via_name="German Federal Foreign Office")], "2026-10-15")
results.append(ok("change" not in out["PS"], "...even when their level moves"))
results.append(ok(all(it.get("iso") != "PS" for it in json.loads(H._mem["advchg:ca"])),
                  "...and never reach the change log"))

# Unmatched items (no ISO) are skipped.
r = H.record_and_annotate("ca", {"items": [item(None, 4), item("MX", 3)]}, "2026-10-16")
results.append(ok(r["items"][0].get("iso") is None and "changed" not in r["items"][0],
                  "an item without an ISO is left alone"))

# 180-day window: `changed` stays, `change` only while the change is recent.
fresh()
run("us", [item("TH", 1)], "2026-01-01")
run("us", [item("TH", 2)], "2026-01-10")
out = run("us", [item("TH", 2)], "2026-07-09")        # day 180
results.append(ok(out["TH"].get("change") == "up", "change shown at 180 days"))
out = run("us", [item("TH", 2)], "2026-07-10")        # day 181
results.append(ok(out["TH"].get("changed") == "2026-01-10" and "change" not in out["TH"],
                  "after 180 days: changed kept, change dropped"))

# The feed's own change wins (the US words: "the level was decreased").
out = run("us", [item("TH", 2, change="down", updated="2026-07-01")], "2026-07-11")
results.append(ok(out["TH"].get("change") == "down" and out["TH"].get("updated") == "2026-07-01",
                  "a feed-provided change and `updated` are untouched"))
out = run("us", [item("TH", 3, change=None)], "2026-07-12")
results.append(ok(out["TH"].get("change") == "up" and out["TH"].get("changed") == "2026-07-12",
                  "a feed change of None is filled from the record"))

# Two rows for one ISO: the most cautious is the level; no flip-flop.
fresh()
run("us", [item("PS", 4), item("PS", 3)], "2026-08-01")
out = run("us", [item("PS", 3), item("PS", 4)], "2026-08-02")
results.append(ok(json.loads(H._mem["advlvl:us"])["PS"] == [4, "2026-08-01"] and "advchg:us" not in H._mem,
                  "duplicate ISO rows: most cautious level, no change logged"))

# The US feed's own change: the since-date is its "updated", not the day seen.
fresh()
run("us", [item("MX", 2), item("KE", 2), item("NE", 3)], "2026-09-01")
out = run("us", [item("MX", 3, change="up", updated="2026-09-28"),
                 item("KE", 3, change=None, updated="2026-09-28"),
                 item("NE", 4, change="up", updated="2026-08-15")], "2026-10-02")
lv = json.loads(H._mem["advlvl:us"])
results.append(ok(out["MX"].get("changed") == "2026-09-28" and lv["MX"] == [3, "2026-09-28", 2],
                  "a change the feed reports: since = the feed's updated (2026-09-28, seen 10-02)"))
results.append(ok(out["MX"].get("change") == "up", "...and the feed's own change stays"))
results.append(ok(out["KE"].get("changed") == "2026-10-02",
                  "a change only we saw (no feed change): since = the day seen"))
results.append(ok(out["NE"].get("changed") == "2026-10-02",
                  "a feed date before the old level's since (08-15 < 09-01) isn't believed"))
results.append(ok({"iso": "MX", "from": 2, "to": 3, "date": "2026-09-28"} in json.loads(H._mem["advchg:us"]),
                  "the change log carries the same date"))
fresh()
run("us", [item("CO", 2)], "2026-09-01")
out = run("us", [item("CO", 3, change="up", updated="2026-10-09")], "2026-10-02")
results.append(ok(out["CO"].get("changed") == "2026-10-02", "a feed date after today isn't believed"))
fresh()
run("us", [item("PE", 2)], "2026-09-01")
out = run("us", [item("PE", 3, change="up", updated="Fri, 2 Oct")], "2026-10-02")
results.append(ok(out["PE"].get("changed") == "2026-10-02", "an unparseable feed date: the day seen"))

# Malformed stored records never fail the list (S5): they read as unseen.
fresh()
H._mem["advlvl:ca"] = json.dumps({"MX": [2, "2026-01-01", None], "FR": "2", "JP": [None, None],
                                  "TH": [1], "BR": {"level": 2}, "IT": [2, "2026-01-01", 1]})
try:
    out = run("ca", [item(i, 2) for i in ("MX", "FR", "JP", "TH", "BR", "IT")], "2026-10-02")
    lv = json.loads(H._mem["advlvl:ca"])
    results.append(ok(not any("change" in r for k, r in out.items() if k != "IT"),
                      "malformed records: no exception, nothing stamped from them"))
    results.append(ok(out["IT"].get("changed") == "2026-01-01" and "change" not in out["IT"],
                      "...a well-formed neighbour still stamped (changed kept, change past 180 days)"))
    results.append(ok(lv["FR"] == [2, "2026-10-02"] and lv["JP"] == [2, "2026-10-02"]
                      and lv["TH"] == [2, "2026-10-02"] and lv["BR"] == [2, "2026-10-02"],
                      "...unreadable ones re-baselined as [level, today]"))
    results.append(ok(lv["MX"] == [2, "2026-01-01", None] and "changed" not in out["MX"],
                      "...[2, date, null] at the same level is left as is, unstamped"))
    out = run("ca", [item("MX", 3)], "2026-10-03")
    results.append(ok(out["MX"].get("change") == "up" and json.loads(H._mem["advlvl:ca"])["MX"] == [3, "2026-10-03", 2],
                      "...and its next change is recorded normally"))
except Exception as e:
    results.append(ok(False, "malformed stored record raised %r" % e))

# The log keeps the last 300.
fresh()
run("de", [item("XX", 1)], "2026-01-01")
H._mem["advchg:de"] = json.dumps([{"iso": "XX", "from": 1, "to": 2, "date": "2025-%03d" % i} for i in range(300)])
run("de", [item("XX", 2)], "2026-01-02")
log = json.loads(H._mem["advchg:de"])
results.append(ok(len(log) == 300 and log[-1]["date"] == "2026-01-02" and log[0]["date"] == "2025-001",
                  "change log capped at 300, oldest dropped"))

# --- Upstash (mock) ---------------------------------------------------------------
port = int(os.environ.get("MOCK_UPSTASH_PORT", "8931"))
try:
    import mock_upstash
    srv = HTTPServer(("127.0.0.1", port), mock_upstash.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    print("mock Upstash started on", port)
except OSError:
    print("mock Upstash already listening on", port)
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
os.environ["UPSTASH_REDIS_REST_TOKEN"] = "mock"
for k in ("advlvl:ca", "advchg:ca"):
    accounts._kv_del(k)
fresh()
results.append(ok(accounts.storage_configured(), "storage configured -> Upstash"))
run("ca", [item("MX", 2), item("TH", 1)], "2026-10-01")
results.append(ok(json.loads(accounts._kv_get("advlvl:ca")) == {"MX": [2, "2026-10-01"], "TH": [1, "2026-10-01"]},
                  "baseline stored under advlvl:ca"))
results.append(ok(not H._mem, "...and nothing kept in memory"))
out = run("ca", [item("MX", 4), item("TH", 1)], "2026-10-03")
results.append(ok(out["MX"].get("change") == "up" and out["MX"].get("changed") == "2026-10-03",
                  "a change read back from Upstash is stamped"))
results.append(ok(json.loads(accounts._kv_get("advchg:ca")) == [{"iso": "MX", "from": 2, "to": 4, "date": "2026-10-03"}],
                  "change logged under advchg:ca"))
results.append(ok(json.loads(accounts._kv_get("advlvl:ca"))["MX"][:2] == [4, "2026-10-03"],
                  "advlvl keeps [level, since] first"))
# A second process overlapping a deploy sees the same change: logged once.
accounts._kv_set("advlvl:ca", json.dumps({"MX": [2, "2026-10-01"], "TH": [1, "2026-10-01"]}))
run("ca", [item("MX", 4), item("TH", 1)], "2026-10-03")
results.append(ok(len(json.loads(accounts._kv_get("advchg:ca"))) == 1, "a change seen twice is logged once"))

# A storage error never breaks the list.
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:9"
payload = {"items": [item("MX", 1)]}
try:
    r = H.record_and_annotate("ca", payload, "2026-10-04")
    results.append(ok(r is payload and "changed" not in r["items"][0],
                      "storage down: payload returned unstamped, no exception"))
except Exception as e:
    results.append(ok(False, "storage down raised %r" % e))
os.environ["UPSTASH_REDIS_REST_URL"] = "http://127.0.0.1:%d" % port
for k in ("advlvl:ca", "advchg:ca"):
    accounts._kv_del(k)

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
