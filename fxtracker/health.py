"""/health.json — Canada's per-country travel health advice (build_health.py)
— served from the freshest copy the server has, and kept fresh by the server
itself.

Why not a scheduled GitHub job: its cron fires hours late, its logs are 403
to us, and a commit per refresh would redeploy the site. The service is up
around the clock anyway (it keeps itself warm), and the source is an open-data
API with no key. So once the static file is a week old, a background thread
rebuilds the document page by page, keeps it in memory, and stores it in
Upstash so a restart or redeploy starts from it rather than from the
committed file.

Three copies, the freshest by "built" wins:
  memory   — what this process built;
  Upstash  — what any process built (key "health:doc"), read once at start
             and after each check, never on a request;
  static   — public/health.json as committed (ties go to it: it is the copy
             whose shape matches the code that ships with it).

Env:
  RENDER                — set by Render: the refresher runs there only;
  HEALTH_REFRESH=1      — run it anyway (local testing);
  HEALTH_REFRESH_DELAY  — seconds after boot before the first check (90);
  HEALTH_REFRESH_ISOS   — testing only: "MX,TH" forces a short run of just
                          those pages on top of the current document.
"""

import datetime
import json
import os
import threading
import time

from . import accounts, build_health

KEY = "health:doc"
MAX_AGE_DAYS = 7
BOOT_DELAY = 90
CHECK_EVERY = 6 * 3600
PAUSE = 0.5          # between pages: an open-data API, never hurried

_mem = {"doc": None}
_kv = {"doc": None}
_static = {"doc": None, "mtime": None}
_body = {"doc": None, "bytes": b""}
_running = threading.Lock()


def _storage():
    return bool(accounts._env("UPSTASH_REDIS_REST_URL") and accounts._env("UPSTASH_REDIS_REST_TOKEN"))


def _static_doc():
    try:
        mtime = os.path.getmtime(build_health.OUT)
        if mtime != _static["mtime"]:
            with open(build_health.OUT, encoding="utf-8") as f:
                _static.update(doc=json.load(f), mtime=mtime)
    except (OSError, ValueError) as e:
        print("[health] static copy unreadable: %s" % e, flush=True)
    return _static["doc"]


def _load_stored():
    """Re-read the Upstash copy (refresher thread only)."""
    if not _storage():
        return
    try:
        raw = accounts._kv_get(KEY)
        doc = json.loads(raw) if raw else None
        if isinstance(doc, dict) and isinstance(doc.get("c"), dict):
            _kv["doc"] = doc
    except Exception as e:
        print("[health] stored copy unreadable: %s" % e, flush=True)


def get_doc():
    """The freshest document: memory, Upstash, static — by "built", ties to
    the later in that list."""
    best = None
    for doc in (_mem["doc"], _kv["doc"], _static_doc()):
        if doc and (best is None or str(doc.get("built", "")) >= str(best.get("built", ""))):
            best = doc
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


def _age_days(doc):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(doc["built"])).days
    except (KeyError, TypeError, ValueError):
        return 10 ** 6


def refresh(force=False, only=None, pause=PAUSE):
    """Rebuild once the freshest copy is MAX_AGE_DAYS old (or when forced);
    True when a new document was built. A run where more than a handful of
    pages fail is an outage (build_health.Outage): the old document stays."""
    if not _running.acquire(blocking=False):
        return False           # one rebuild at a time
    try:
        cur = get_doc() or {}
        if not force and _age_days(cur) < MAX_AGE_DAYS:
            return False
        t0 = time.time()
        try:
            doc, failed = build_health.build(cur.get("c", {}), only=only, pause=pause)
        except Exception as e:     # Outage, or the index itself didn't load
            print("[health] refresh failed (%s); keeping the copy built %s"
                  % (e, cur.get("built")), flush=True)
            return False
        doc = build_health.with_westnile(
            doc, cur, log=lambda m: print(m, flush=True))
        _mem["doc"] = doc
        if _storage():
            try:
                accounts._kv_set(KEY, json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
            except Exception as e:
                print("[health] not stored (%s); memory only until the next refresh" % e, flush=True)
        print("[health] rebuilt in %ds: %d countries, %d with Canada's reasons%s" % (
            time.time() - t0, len(doc["c"]), sum(1 for r in doc["c"].values() if r.get("r")),
            ("; failed: " + ", ".join(failed)) if failed else ""), flush=True)
        return True
    finally:
        _running.release()


def start_refresher():
    """Start the background refresher — on Render, or with HEALTH_REFRESH=1;
    never on a laptop by accident. True when started."""
    if not (os.environ.get("RENDER") or os.environ.get("HEALTH_REFRESH") == "1"):
        return False
    delay = float(os.environ.get("HEALTH_REFRESH_DELAY") or BOOT_DELAY)
    only = {s.strip().upper() for s in (os.environ.get("HEALTH_REFRESH_ISOS") or "").split(",") if s.strip()}

    def loop():
        _load_stored()             # a redeploy picks up the last refresh at once
        time.sleep(delay)          # after the first health checks and warm-ups
        while True:
            try:
                _load_stored()
                refresh(force=bool(only), only=only or None)
            except Exception as e:  # the thread must outlive any one bad check
                print("[health] check failed: %s" % e, flush=True)
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True, name="health-refresh").start()
    print("[health] refresher started (first check in %ds%s)" % (
        delay, ", only " + ",".join(sorted(only)) if only else ""), flush=True)
    return True
