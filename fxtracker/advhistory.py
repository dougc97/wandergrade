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
                   listing later). When the US feed itself says the level
                   changed, since is the item's own "updated" date instead:
                   the State Department's date, not the day we first fetched
                   it, which can be days later (the client shows `changed`
                   ahead of `updated`, so ours would read as the later one).
  advchg:<source>  [{iso, from, to, date}], oldest first, the last 300.

Items are annotated (contract with the client):
  changed — the date the current level arrived, when we saw it change (the
            feed's own "updated" when it reports that change, else the day
            we saw it);
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
import re
import threading
import time

from . import accounts

KEEP = 300
WINDOW_DAYS = 180

_lock = threading.Lock()
_mem = {}


def _load(key):
    if accounts.storage_configured():
        raw = accounts._kv_get(key)
        return json.loads(raw) if raw else None
    v = _mem.get(key)
    return json.loads(v) if v else None


def _save(key, obj):
    raw = json.dumps(obj, separators=(",", ":"))
    if accounts.storage_configured():
        accounts._kv_set(key, raw)
    else:
        _mem[key] = raw


def _rec(rec):
    """A stored record as (level, since, before|None), or None when it isn't
    one: a record written by hand or by older code — [2, "2026-01-01", null],
    say — must read as "never seen", not raise mid-list (rec[0] > rec[2] on a
    None took the whole stamping down with a TypeError)."""
    if (isinstance(rec, list) and len(rec) >= 2 and type(rec[0]) is int
            and isinstance(rec[1], str)):
        before = rec[2] if len(rec) >= 3 and type(rec[2]) is int else None
        return rec[0], rec[1], before
    return None


def _since(item, prev_since, today):
    """The date a level we just saw change arrived: the feed's own `updated`
    when the feed itself reports the change (only the US does: "The advisory
    level was increased to 3", advisories._change), else today. Only a date
    between the previous level's since and today is believed — an earlier one
    would put the new level before the old one arrived."""
    upd = item.get("updated") if item and item.get("change") else None
    if isinstance(upd, str) and re.fullmatch(r"\d{4}-\d\d-\d\d", upd) and prev_since <= upd <= today:
        return upd
    return today


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
    seen, at = {}, {}
    for it in own:
        seen[it["iso"]] = max(seen.get(it["iso"], it["level"]), it["level"])
    for it in own:                      # the row that carries that level
        if it["level"] == seen[it["iso"]]:
            at.setdefault(it["iso"], it)
    try:
        with _lock:
            levels = _load("advlvl:" + source)
            dirty = levels is None          # the first-ever run is the baseline
            levels = levels if isinstance(levels, dict) else {}
            changes = []
            for iso, lvl in seen.items():
                rec = _rec(levels.get(iso))
                if not rec:                 # unseen, or unreadable: a baseline
                    levels[iso] = [lvl, today]
                    dirty = True
                elif rec[0] != lvl:
                    since = _since(at.get(iso), rec[1], today)
                    changes.append({"iso": iso, "from": rec[0], "to": lvl, "date": since})
                    levels[iso] = [lvl, since, rec[0]]
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
        rec = _rec(levels.get(it["iso"]))
        if not rec or rec[2] is None or rec[0] != it["level"]:
            continue                        # never seen it change
        it["changed"] = rec[1]
        if not it.get("change") and _days(rec[1], today) <= WINDOW_DAYS:
            it["change"] = "up" if rec[0] > rec[2] else "down"
    return payload
