"""/guide-facts.json — the per-guide price level and advisory snapshot behind
every guide's <title>, meta description, FAQ answers, server-rendered 💰/🛡️
lines and sitemap <lastmod> — served from the freshest copy the server has,
and kept fresh by the server itself (the pattern of fxtracker/health.py).

Why: the snapshot was a committed file rebuilt by hand each month
(scripts/build_guide_facts.py), and a monthly chore is one nobody reliably
does — past render_guide.STALE_DAYS every figure drops out of all 190 guides.
Yet the server already holds every input: the rates /api/rates serves and the
advisory list /api/advisories serves, each in its own cache, and the PPP table
/ppp.json serves. So once a day a background thread recomputes the document
from those (never over HTTP to itself, never on a request), keeps it in
memory, and stores it in Upstash so a restart or redeploy starts from it
rather than from the committed file. render_guide only ever calls get_doc(),
which is a few dict lookups and a stat.

Three copies; the freshest by (_asof, _built) wins:
  memory   — what this process computed;
  Upstash  — what any process computed (key "guidefacts:doc"), read at start
             and before each check, never on a request;
  static   — public/guide-facts.json as committed, built from the parity
             fixtures: the fallback, and what a fresh deploy serves until its
             first check.
_asof is the rates' own date (what "As of Oct 2026" prints); _built, the day a
server computed the copy, breaks ties so the day's recompute (a changed
advisory on an unchanged rate date) outranks yesterday's. The committed file
has no _built: it loses every tie and is due a recompute at once. On an exact
tie memory wins, then Upstash.

Both computed copies are tagged with CODE, a hash of what turns the inputs
into the document's strings — this module, render_guide.py (the title and
description rules), pricelevel.py, the currency map, and the content files
meta() reads (names, best months, summaries). A copy computed by other code
is ignored: its t/d/dn, which app.js sets on in-app navigation, would
contradict a deploy that changed a title rule or a best month until the next
day's recompute. (The committed file can't be in that state:
scripts/test_guide_meta.py holds its t/d/dn equal to meta().) The ignored
copy is still the record of what was served before the deploy, so new
documents are dated ("m") against it: a deploy doesn't re-date every guide
whose figure moved since the committed file was built.

A check (every CHECK_EVERY; RETRY_EVERY after one that kept the old copy)
recomputes once the freshest copy wasn't built today. The previous copy stays
— nothing is computed — when an input failed or is missing, when the server's
cache marks it stale (the upstream's last refresh failed), when the rates'
date is older than the served copy's, or when the result looks built from a
truncated feed (vet()). A guide's "m" moves only when its own entry changed
(CHANGE_KEYS): the rates' date moving every day re-dates nothing.

Env:
  RENDER                      — set by Render: the refresher runs there only;
  GUIDE_FACTS_REFRESH=1       — run it anyway (local testing);
  GUIDE_FACTS_REFRESH_DELAY   — seconds after boot before the first check (120).
"""

import datetime
import hashlib
import json
import os
import threading
import time
from decimal import Decimal, ROUND_HALF_UP

from . import accounts, picks, pricelevel

HERE = os.path.dirname(os.path.abspath(__file__))
PUBLIC = os.path.join(os.path.dirname(HERE), "public")
OUT = os.path.join(PUBLIC, "guide-facts.json")

# app.js GUIDE_PARENT (price level, always) and ADV_PARENT (advisory, only when
# the place has no row of its own).
GUIDE_PARENT = {"GB-ENG": "GB", "GB-SCT": "GB", "GB-WLS": "GB"}
ADV_PARENT = dict(GUIDE_PARENT, GG="GB", IM="GB", JE="GB", FO="DK")
# What a guide's page says: a change to any of these is a change to the page,
# and moves that guide's "m" (its sitemap <lastmod>). _asof is not here — the
# rates' date moves daily, and "As of Oct 2026" moving monthly is already in d.
CHANGE_KEYS = ("t", "d", "dn", "pct", "adv")
# A truncated feed would publish number-free pages and re-date every guide for
# it: below these shares of guides with a figure, the inputs are broken.
MIN_PCT_SHARE, MIN_ADV_SHARE = 0.75, 0.9
# More guides than this losing a figure they had is a partial feed (a missing
# EUR or XCD row strips 6-25 guides at once), not news: the previous copy
# stays. Up to PARTIAL_GRACE_DAYS — after that a lasting loss is a real
# change, and holding out would only let every figure age out at STALE_DAYS.
MAX_LOST = 3
PARTIAL_GRACE_DAYS = 14

KEY = "guidefacts:doc"
BOOT_DELAY = 120          # after health's first check (90s) and the warm-ups
CHECK_EVERY = 6 * 3600    # so "daily" lands within a few hours of midnight
RETRY_EVERY = 3600        # after a kept copy: a 429 or a feed blip passes


class InputError(Exception):
    """These inputs can't make a document worth serving; the previous stays."""


# ---- computing a document (scripts/build_guide_facts.py and the refresher) ----

def band(pl):
    """app.js plWord(pl) against the US: banded on toFixed(2), the digits the
    page prints. Decimal(pl) is the exact binary value, and HALF_UP on it is
    toFixed's rounding."""
    r = float(Decimal(pl).quantize(Decimal("0.01"), ROUND_HALF_UP))
    if r <= 1 - 0.1:
        return "very cheap" if r < 0.55 else "cheap"
    return "about the same" if r <= 1 + 0.1 else "pricey"


def all_guides():
    from . import render_guide   # here: render_guide imports this module
    return [iso for _slug, iso in render_guide.all_slugs()]


def compute(rates, advisories, ppp, guides):
    """The document's entries (no "m" yet) from an /api/rates payload, an
    /api/advisories?source=us payload and the PPP table. The price level is
    pricelevel.price_level with the income plausibility fit, which parity.py
    proves equal to app.js priceLevel; inflation is carried forward to the
    rates' own date, so the same inputs always give the same figures."""
    from . import render_guide
    asof = datetime.date.fromisoformat(str(rates["as_of"])[:10])
    now_y = pricelevel.now_year(asof)
    rate_by_code = {r["code"]: r["rate_now"] for r in rates["rows"] if "code" in r and "rate_now" in r}
    fit = pricelevel.plausibility_fit(ppp, rate_by_code, picks.CUR_BY_ISO, now_y)
    us = pricelevel.price_level("US", ppp, rate_by_code, picks.CUR_BY_ISO, fit, now_y) or 1
    meta = {}
    for it in advisories["items"]:              # app.js advisoryMetaByIso: last wins
        if it.get("iso"):
            meta[it["iso"]] = it
    default_src = advisories.get("source") or "us"

    out = {"_asof": asof.isoformat()}
    for iso in sorted(guides):
        f = {}
        pl_iso = GUIDE_PARENT.get(iso, iso)
        pl = pricelevel.price_level(pl_iso, ppp, rate_by_code, picks.CUR_BY_ISO, fit, now_y)
        if pl and iso != "US":
            rel = pl / us
            f["pct"] = pricelevel.js_round(100 * rel)
            f["band"] = band(rel)
            if pl_iso != iso:
                f["plof"] = pl_iso
        parent = ADV_PARENT.get(iso) if iso not in meta and ADV_PARENT.get(iso) in meta else None
        it = meta.get(iso) or (parent and meta[parent])
        if it and it.get("level"):
            f["adv"] = it["level"]
            f["src"] = it.get("via") or default_src
            if parent:
                f["advof"] = parent
        m = render_guide.meta(iso, f, asof)
        f["t"], f["d"] = m["title"], m["desc"]
        dn = render_guide.meta_numberfree(iso)
        if dn != f["d"]:
            f["dn"] = dn
        out[iso] = f
    return out


def _date(doc):
    try:
        return datetime.date.fromisoformat(str((doc or {}).get("_asof") or "")[:10])
    except ValueError:
        return None


def vet(data, prev, guides):
    """Raise InputError when `data` looks computed from a broken or partial
    feed (see MIN_*_SHARE, MAX_LOST); else the guides that lost a figure."""
    n = len(guides)
    n_pct = sum(1 for i in guides if data[i].get("pct") is not None)
    n_adv = sum(1 for i in guides if data[i].get("adv"))
    if n_pct < MIN_PCT_SHARE * n or n_adv < MIN_ADV_SHARE * n:
        raise InputError("only %d price levels / %d advisories for %d guides — inputs look broken"
                         % (n_pct, n_adv, n))
    lost = [i for i in guides
            if ((prev.get(i) or {}).get("pct") is not None and data[i].get("pct") is None)
            or ((prev.get(i) or {}).get("adv") and not data[i].get("adv"))]
    a, b = _date(data), _date(prev)
    if len(lost) > MAX_LOST and a and b and (a - b).days <= PARTIAL_GRACE_DAYS:
        raise InputError("partial inputs: %d guides would lose a figure they have (%s)"
                         % (len(lost), ", ".join(lost[:10]) + (" …" if len(lost) > 10 else "")))
    return lost


def date_entries(data, prev, guides, today):
    """Set each guide's "m": `today` where its entry changed against `prev`
    (or was never dated), else prev's. The changed guides, in order."""
    changed = [iso for iso in guides
               if not (prev.get(iso) or {}).get("m")
               or any((prev.get(iso) or {}).get(k) != data[iso].get(k) for k in CHANGE_KEYS)]
    for iso in guides:
        data[iso]["m"] = today if iso in changed else prev[iso]["m"]
    return changed


def _utc_today():
    """The day the refresher works in. Render runs in UTC; a laptop may not,
    and "once a day" and the sitemap dates mean the UTC day either way."""
    return datetime.datetime.now(datetime.timezone.utc).date()


def hold_home_levels(data, prev, advisories, guides):
    """The US feed drops rows between fetches (CO, KP and BM for ~10 minutes
    on 2026-10-04, and Canada's fill rated Colombia Level 2 where the US says
    Level 3). Live, that lasts one cache cycle; frozen into the daily document
    it sat in titles ("Is Colombia Cheap…" lost its "Safe"), snippets and FAQ
    answers for a day, and re-dated the guide twice. So a guide whose previous
    copy had the home source's own level keeps it while the feed omits it, up
    to PARTIAL_GRACE_DAYS ("held" records since when); after that the fill
    stands. Returns the held guides."""
    from . import render_guide
    home = (advisories or {}).get("source") or "us"
    asof = _date(data)
    held = []
    for iso in guides:
        p, f = prev.get(iso) or {}, data[iso]
        if not (p.get("adv") and p.get("src") == home) or f.get("src") == home:
            continue
        since = p.get("held") or data["_asof"]
        try:
            if (asof - datetime.date.fromisoformat(str(since)[:10])).days > PARTIAL_GRACE_DAYS:
                continue
        except ValueError:
            continue
        for k in ("adv", "src", "advof"):
            f.pop(k, None)
        f.update(adv=p["adv"], src=home, held=since)
        if p.get("advof"):
            f["advof"] = p["advof"]
        m = render_guide.meta(iso, f, asof)
        f["t"], f["d"] = m["title"], m["desc"]
        dn = render_guide.meta_numberfree(iso)
        if dn != f["d"]:
            f["dn"] = dn
        else:
            f.pop("dn", None)
        held.append(iso)
    return held


def build(rates, advisories, ppp, prev=None, guides=None, today=None):
    """compute() + vet() + date_entries(): (document, changed guides, guides
    that lost a figure). The one implementation the CLI and the refresher
    share; raises InputError (and builds nothing) on broken inputs."""
    guides = guides or all_guides()
    prev = prev or {}
    data = compute(rates, advisories, ppp, guides)
    # vet() first, on the feed as it came: a truncated feed must still be
    # refused as truncated, not quietly held for two weeks.
    lost = vet(data, prev, guides)
    hold_home_levels(data, prev, advisories, guides)
    changed = date_entries(data, prev, guides, (today or _utc_today()).isoformat())
    return data, changed, lost


def dump(data):
    """The committed file's layout: one country per line, so a rebuild's diff
    reads country by country."""
    keys = sorted(k for k in data if k.startswith("_")) + sorted(k for k in data if not k.startswith("_"))
    return "{\n" + ",\n".join(
        "%s:%s" % (json.dumps(k), json.dumps(data[k], ensure_ascii=False, separators=(",", ":")))
        for k in keys) + "\n}\n"


# ---- which copy is served -----------------------------------------------------

# Hashed rather than versioned by hand: forgetting to bump a version would
# serve yesterday's titles under today's rules. Content files are here too —
# a deploy that changes a best month changes every description that names it.
CODE_FILES = [os.path.join(HERE, n) for n in ("guide_facts.py", "render_guide.py", "pricelevel.py")] + \
             [os.path.join(PUBLIC, n) for n in ("slugs.json", "country-names.json", "climate.json",
                                                "activities.json")]


def _code(files=None):
    h = hashlib.sha1()
    for path in files or CODE_FILES:
        try:
            with open(path, "rb") as f:
                h.update(os.path.basename(path).encode() + b"\0" + f.read())
        except OSError:
            h.update(os.path.basename(path).encode() + b"\0-")
    # Only the currency map from picks.py: the rest of it is scoring, which
    # changes often and never reaches this document.
    h.update(json.dumps(sorted(picks.CUR_BY_ISO.items())).encode())
    return h.hexdigest()[:10]


CODE = _code()

_mem = {"doc": None, "code": None}
_kv = {"doc": None, "other": None, "ignored": None}
_static = {"doc": None, "mtime": None}
_body = {"doc": None, "bytes": b""}
_running = threading.Lock()


def _usable(doc):
    return isinstance(doc, dict) and _date(doc) is not None


def _key(doc):
    return (str(doc.get("_asof")), str(doc.get("_built") or ""))


def _static_doc():
    try:
        mtime = os.path.getmtime(OUT)
        if mtime != _static["mtime"]:
            with open(OUT, encoding="utf-8") as f:
                _static.update(doc=json.load(f), mtime=mtime)
    except (OSError, ValueError) as e:
        if _static["mtime"] != "unreadable":      # once, not on every request
            print("[guide-facts] committed copy unreadable: %s" % e, flush=True)
            _static["mtime"] = "unreadable"
    return _static["doc"]


def _load_stored():
    """Re-read the Upstash copy (refresher thread only). Only a copy computed
    by this code is served; one from other code is kept aside as the dating
    baseline (see the module docstring)."""
    if not accounts.storage_configured():
        return
    try:
        raw = accounts._kv_get(KEY)
        env = json.loads(raw) if raw else None
    except Exception as e:     # unreachable: keep what was read last time
        print("[guide-facts] stored copy unreadable: %s" % e, flush=True)
        return
    if isinstance(env, dict) and env.get("code") == CODE and _usable(env.get("doc")):
        _kv.update(doc=env["doc"], other=None)
        return
    other_doc = env["doc"] if isinstance(env, dict) and _usable(env.get("doc")) else None
    _kv["other"] = other_doc
    # A deploy that changes CODE used to serve the committed file (which may
    # be weeks older) until the first check — pages went from "As of Oct" back
    # to "As of Sep". Only t/d/dn depend on the code, so re-word the stored
    # figures with this code and serve that; the first check still recomputes
    # (no _built). Memoized per stored copy, so a later reload re-dates nothing.
    _kv["doc"] = None
    if other_doc is not None:
        memo = (other_doc.get("_asof"), other_doc.get("_built"))
        if _kv.get("restrung_from") != memo:
            try:
                _kv["restrung"] = _restring(other_doc)
                _kv["restrung_from"] = memo
            except Exception as e:
                print("[guide-facts] couldn't re-word the stored copy (%s)" % e, flush=True)
                _kv["restrung"], _kv["restrung_from"] = None, None
        _kv["doc"] = _kv.get("restrung")
    if env is not None:
        other = env.get("code") if isinstance(env, dict) else None
        if _kv["ignored"] != (other or "untagged"):
            _kv["ignored"] = other or "untagged"
            print("[guide-facts] stored copy ignored: computed by other code (%s, this is %s)"
                  % (_kv["ignored"], CODE), flush=True)


def _restring(doc):
    """`doc`'s figures, with titles and descriptions worded by this code."""
    from . import render_guide
    guides, asof = all_guides(), _date(doc)
    out = {"_asof": doc["_asof"]}
    for iso in guides:
        f = {k: v for k, v in (doc.get(iso) or {}).items() if k not in ("t", "d", "dn", "m")}
        m = render_guide.meta(iso, f, asof)
        f["t"], f["d"] = m["title"], m["desc"]
        dn = render_guide.meta_numberfree(iso)
        if dn != f["d"]:
            f["dn"] = dn
        out[iso] = f
    date_entries(out, doc, guides, _utc_today().isoformat())
    return out


def get_doc():
    """The freshest document by (_asof, _built) — on a tie, memory, then
    Upstash, then the committed file. None only if there is no copy at all
    (render_guide then serves number-free pages, as before the snapshot)."""
    best, best_key = None, None
    cands = (_mem["doc"] if _mem["code"] == CODE else None, _kv["doc"], _static_doc())
    for rank, doc in zip((2, 1, 0), cands):
        if _usable(doc):
            key = _key(doc) + (rank,)
            if best_key is None or key > best_key:
                best, best_key = doc, key
    return best


def get_json_bytes():
    """get_doc() serialized, once per document rather than once per request."""
    doc = get_doc()
    if doc is None:
        return None
    if _body["doc"] is not doc:
        _body.update(doc=doc, bytes=json.dumps(doc, ensure_ascii=False,
                                               separators=(",", ":")).encode("utf-8"))
    return _body["bytes"]


def _baseline():
    """What a new document is dated and vetted against: the freshest copy,
    counting a stored one from other code (what was served before this
    deploy)."""
    cands = [d for d in (get_doc(), _kv["other"]) if _usable(d)]
    return max(cands, key=_key) if cands else {}


# ---- the refresher ------------------------------------------------------------

def _input_problem(rates, advisories, ppp, served):
    """Why these inputs mustn't replace the served copy, or ""."""
    if not isinstance(rates, dict) or not rates.get("rows"):
        return "no rates"
    try:
        asof = datetime.date.fromisoformat(str(rates.get("as_of") or "")[:10])
    except ValueError:
        return "rates without a date (%r)" % rates.get("as_of")
    if rates.get("stale"):
        return "the rates are a stale copy (the provider's last refresh failed)"
    if served and asof < served:
        return "rates as of %s are older than the served copy's %s" % (asof, served)
    if not isinstance(advisories, dict) or not advisories.get("items"):
        return "no advisories"
    if advisories.get("stale"):
        return "the advisories are a stale copy (the feed's last refresh failed)"
    if not ppp:
        return "no PPP table"
    return ""


def refresh(get_rates, get_advisories, get_ppp, force=False, today=None):
    """One check: "fresh" (today's copy is in hand), "built" (a new copy is
    served and stored) or "kept" (the inputs couldn't make one; the served
    copy stays and the next check comes sooner). The getters are the
    server's own cache helpers — the copies /api/rates, /api/advisories and
    /ppp.json serve."""
    if not _running.acquire(blocking=False):
        return "busy"          # one recompute at a time
    try:
        today = today or _utc_today()
        cur = get_doc() or {}
        if not force and str(cur.get("_built") or "") >= today.isoformat():
            return "fresh"
        try:
            rates, advisories, ppp = get_rates(), get_advisories(), get_ppp()
        except Exception as e:     # an upstream down with nothing cached
            print("[guide-facts] inputs failed (%s); keeping the copy as of %s"
                  % (e, cur.get("_asof")), flush=True)
            return "kept"
        problem = _input_problem(rates, advisories, ppp, _date(cur))
        if problem:
            print("[guide-facts] %s; keeping the copy as of %s" % (problem, cur.get("_asof")), flush=True)
            return "kept"
        t0 = time.time()
        try:
            doc, changed, lost = build(rates, advisories, ppp, _baseline(), today=today)
        except InputError as e:
            print("[guide-facts] %s; keeping the copy as of %s" % (e, cur.get("_asof")), flush=True)
            return "kept"
        doc["_built"] = today.isoformat()
        _mem.update(doc=doc, code=CODE)
        if accounts.storage_configured():
            try:
                accounts._kv_set(KEY, json.dumps({"code": CODE, "doc": doc},
                                                 ensure_ascii=False, separators=(",", ":")))
            except Exception as e:
                print("[guide-facts] not stored (%s); memory only until the next recompute" % e,
                      flush=True)
        guides = [k for k in doc if not k.startswith("_")]
        print("[guide-facts] recomputed in %.2fs: as of %s, %d guides, %d with a price level, "
              "%d with an advisory; %d changed%s%s" % (
                  time.time() - t0, doc["_asof"], len(guides),
                  sum(1 for i in guides if doc[i].get("pct") is not None),
                  sum(1 for i in guides if doc[i].get("adv")), len(changed),
                  (" (" + ", ".join(changed[:8]) + (" …" if len(changed) > 8 else "") + ")") if changed else "",
                  ("; lost a figure: " + ", ".join(lost)) if lost else ""), flush=True)
        held = [i for i in guides if doc[i].get("held")]
        if held:
            print("[guide-facts] home-source level held while the feed omits it: %s" % ", ".join(held),
                  flush=True)
        return "built"
    finally:
        _running.release()


def start_refresher(get_rates, get_advisories, get_ppp):
    """Start the daily recompute — on Render, or with GUIDE_FACTS_REFRESH=1;
    never on a laptop by accident. True when started."""
    if not (os.environ.get("RENDER") or os.environ.get("GUIDE_FACTS_REFRESH") == "1"):
        return False
    # A typo here ("90s") must not stop the server booting: main() calls
    # this before it starts serving.
    try:
        delay = float(os.environ.get("GUIDE_FACTS_REFRESH_DELAY") or BOOT_DELAY)
        if not 0 <= delay < 10 ** 7:       # "inf" would kill the thread in sleep()
            raise ValueError
    except ValueError:
        print("[guide-facts] GUIDE_FACTS_REFRESH_DELAY=%r isn't a delay in seconds; using %ds"
              % (os.environ.get("GUIDE_FACTS_REFRESH_DELAY"), BOOT_DELAY), flush=True)
        delay = BOOT_DELAY

    def loop():
        _load_stored()             # a restart serves the last recompute at once
        time.sleep(delay)          # after the warm-ups have filled the caches
        while True:
            result = None
            try:
                _load_stored()
                result = refresh(get_rates, get_advisories, get_ppp)
            except Exception as e:  # the thread must outlive any one bad check
                print("[guide-facts] check failed: %s" % e, flush=True)
            time.sleep(CHECK_EVERY if result in ("fresh", "built") else RETRY_EVERY)

    threading.Thread(target=loop, daemon=True, name="guide-facts-refresh").start()
    print("[guide-facts] refresher started (first check in %ds)" % delay, flush=True)
    return True
