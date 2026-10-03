"""WanderGrade's own record of advisory levels, so the site can say when a
government last changed its level for a country.

Only the US feed ever says so, in words ("The advisory level was increased
to 3", advisories._change), and only until the item is next reissued. Canada's
and Germany's feeds carry the current level and nothing else — Germany's
"lastModified" moves with every edit to the page, not with the level. So each
time a source's list is freshly fetched, its levels are compared with the last
ones recorded for it; a different level is a change we saw happen, dated the
day we saw it.

Storage, in Upstash when it is configured (memory otherwise, so local runs
start a fresh record each boot):
  advlvl:<source>  {ISO: [level, "YYYY-MM-DD since"]} — since = when the
                   current level was first seen. A third element, the level
                   before, marks a change we saw; without it the date is just
                   when we started watching (the first-ever run is a baseline,
                   not a wave of changes, and so is a country the feed starts
                   listing later).
  advchg:<source>  [{iso, from, to, date}], oldest first, the last 300.

Items are annotated (contract with the client):
  changed — the date we saw the current level arrive, when we saw it change;
  change  — "up"/"down" for that change when it is under 180 days old and
            the feed gives no change of its own (the US words win).

Only the source's own items: a gap-fill from another government ("via") is
that government's level and is recorded under its own source when that list
is fetched. A country missing from one fetch (the US feed drops some between
fetches) keeps its record untouched, so its return at the same level is no
change.
"""

import datetime
import json
import threading
import time

from . import accounts

KEEP = 300
WINDOW_DAYS = 180

_lock = threading.Lock()
_mem = {}


def _storage():
    return bool(accounts._env("UPSTASH_REDIS_REST_URL") and accounts._env("UPSTASH_REDIS_REST_TOKEN"))


def _load(key):
    if _storage():
        raw = accounts._kv_get(key)
        return json.loads(raw) if raw else None
    v = _mem.get(key)
    return json.loads(v) if v else None


def _save(key, obj):
    raw = json.dumps(obj, separators=(",", ":"))
    if _storage():
        accounts._kv_set(key, raw)
    else:
        _mem[key] = raw


def _days(since, today):
    try:
        return (datetime.date.fromisoformat(today) - datetime.date.fromisoformat(since)).days
    except (TypeError, ValueError):
        return 10 ** 6


def record_and_annotate(source, payload, today=None):
    """Record this fetch's levels for `source` and stamp its own items with
    `changed`/`change`. Returns the payload (annotated in place). Never
    raises over storage: a failure leaves the items unstamped."""
    today = today or time.strftime("%Y-%m-%d", time.gmtime())
    items = (payload or {}).get("items") or []
    own = [it for it in items if it.get("iso") and not it.get("via")
           and isinstance(it.get("level"), int)]
    if not own:
        return payload
    # One level per country, the most cautious: two rows for one ISO (Gaza
    # and the West Bank are both PS) must not read as a change on every fetch.
    seen = {}
    for it in own:
        seen[it["iso"]] = max(seen.get(it["iso"], it["level"]), it["level"])
    try:
        with _lock:
            levels = _load("advlvl:" + source)
            dirty = levels is None          # the first-ever run is the baseline
            levels = levels if isinstance(levels, dict) else {}
            changes = []
            for iso, lvl in seen.items():
                rec = levels.get(iso)
                if not rec:
                    levels[iso] = [lvl, today]
                    dirty = True
                elif rec[0] != lvl:
                    changes.append({"iso": iso, "from": rec[0], "to": lvl, "date": today})
                    levels[iso] = [lvl, today, rec[0]]
                    dirty = True
            if changes:
                log = _load("advchg:" + source)
                log = log if isinstance(log, list) else []
                # Two processes overlap during a deploy and can both see the
                # same change; it is logged once.
                for c in changes:
                    if c not in log[-50:]:
                        log.append(c)
                _save("advchg:" + source, log[-KEEP:])
            if dirty:
                _save("advlvl:" + source, levels)
    except Exception as e:
        print("[adv-history] %s not recorded: %s" % (source, e), flush=True)
        return payload
    for it in own:
        rec = levels.get(it["iso"])
        if not rec or len(rec) < 3 or rec[0] != it["level"]:
            continue                        # never seen it change
        it["changed"] = rec[1]
        if not it.get("change") and _days(rec[1], today) <= WINDOW_DAYS:
            it["change"] = "up" if rec[0] > rec[2] else "down"
    return payload
