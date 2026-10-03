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
  static   — public/health.json as committed.
Ties go to memory, then Upstash: both are tagged with CODE, a hash of the
code that builds the document, and a copy built by other code is ignored. So
a stored copy can't outrank a deploy that changes what the document holds:
a refresh on Oct 7 by code without West Nile, stored, would otherwise beat a
deploy whose file (rebuilt from a mirror, dated Sep 30) has it, until Oct 14
— and hide any fix to the parsing rules the same way. The served document's
shape is unchanged; the tag is on the stored envelope {code, doc}.

Env:
  RENDER                — set by Render: the refresher runs there only;
  HEALTH_REFRESH=1      — run it anyway (local testing);
  HEALTH_REFRESH_DELAY  — seconds after boot before the first check (90);
  HEALTH_REFRESH_ISOS   — testing only: "MX,TH" makes the first check a short
                          run of just those pages on top of the current
                          document. It keeps that document's "built" and
                          West Nile, and stays in memory (never stored), so
                          it can't pass for the weekly refresh: later checks
                          are the normal ones.
"""

import datetime
import hashlib
import json
import os
import threading
import time

from . import accounts, build_health

HERE = os.path.dirname(os.path.abspath(__file__))


def _code():
    """What builds the document: the page parser, the reason labels it uses
    (advisories.label_reasons — the r chips), and West Nile once deployed."""
    h = hashlib.sha1()
    for name in ("build_health.py", "advisories.py", "westnile.py"):
        try:
            with open(os.path.join(HERE, name), "rb") as f:
                h.update(name.encode() + b"\0" + f.read())
        except OSError:
            pass               # westnile.py ships on its own branch
    return h.hexdigest()[:10]


CODE = _code()
KEY = "health:doc"
MAX_AGE_DAYS = 7
BOOT_DELAY = 90
CHECK_EVERY = 6 * 3600
PAUSE = 0.5          # between pages: an open-data API, never hurried

_mem = {"doc": None, "code": None}
_kv = {"doc": None, "ignored": None}
_static = {"doc": None, "mtime": None}
_body = {"doc": None, "bytes": b""}
_running = threading.Lock()


def _usable(doc):
    return isinstance(doc, dict) and isinstance(doc.get("c"), dict)


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
    """Re-read the Upstash copy (refresher thread only). Only a copy built by
    this code counts; one from older code (or from before the tag, a bare
    document) is ignored until this process's own refresh replaces it."""
    if not accounts.storage_configured():
        return
    try:
        raw = accounts._kv_get(KEY)
        env = json.loads(raw) if raw else None
    except Exception as e:     # unreachable: keep what was read last time
        print("[health] stored copy unreadable: %s" % e, flush=True)
        return
    if isinstance(env, dict) and env.get("code") == CODE and _usable(env.get("doc")):
        _kv["doc"] = env["doc"]
        return
    _kv["doc"] = None
    if env is not None:
        other = env.get("code") if isinstance(env, dict) else None
        if _kv["ignored"] != (other or "untagged"):
            _kv["ignored"] = other or "untagged"
            print("[health] stored copy ignored: built by other code (%s, this is %s)"
                  % (_kv["ignored"], CODE), flush=True)


def get_doc():
    """The freshest document by "built" — on a tie, memory, then Upstash,
    then static: the first two were built by this code (see CODE), and a
    HEALTH_REFRESH_ISOS run keeps its base copy's date yet is the one to
    serve."""
    best, best_key = None, None
    cands = (_mem["doc"] if _mem["code"] == CODE else None, _kv["doc"], _static_doc())
    for rank, doc in zip((2, 1, 0), cands):
        if _usable(doc):
            key = (str(doc.get("built", "")), rank)
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


def _age_days(doc):
    try:
        return (datetime.date.today() - datetime.date.fromisoformat(doc["built"])).days
    except (KeyError, TypeError, ValueError):
        return 10 ** 6


def refresh(force=False, only=None, pause=PAUSE):
    """Rebuild once the freshest copy is MAX_AGE_DAYS old (or when forced);
    True when a new document was built. A run where more than a handful of
    pages fail is an outage (build_health.Outage): the old document stays.
    With `only` (HEALTH_REFRESH_ISOS), just those pages: the document keeps
    its date and West Nile, and isn't stored — see the module docstring."""
    if not _running.acquire(blocking=False):
        return False           # one rebuild at a time
    try:
        cur = get_doc() or {}
        if not force and _age_days(cur) < MAX_AGE_DAYS:
            return False
        t0 = time.time()
        try:
            doc, failed = build_health.build(cur.get("c", {}), only=only, pause=pause,
                                             prev_built=cur.get("built"))
        except Exception as e:     # Outage, or the index itself didn't load
            print("[health] refresh failed (%s); keeping the copy built %s"
                  % (e, cur.get("built")), flush=True)
            return False
        if only:
            if cur.get("w"):
                doc["w"] = cur["w"]
        else:
            doc = build_health.with_westnile(
                doc, cur, log=lambda m: print(m, flush=True))
        _mem.update(doc=doc, code=CODE)
        if only:
            print("[health] partial run (%s): memory only, not stored, still dated %s"
                  % (",".join(sorted(only)), doc.get("built")), flush=True)
        elif accounts.storage_configured():
            try:
                accounts._kv_set(KEY, json.dumps({"code": CODE, "doc": doc},
                                                 ensure_ascii=False, separators=(",", ":")))
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
    # A typo here ("90s") must not stop the server booting: main() calls
    # this before it starts serving.
    try:
        delay = float(os.environ.get("HEALTH_REFRESH_DELAY") or BOOT_DELAY)
        if not 0 <= delay < 10 ** 7:       # "inf" would kill the thread in sleep()
            raise ValueError
    except ValueError:
        print("[health] HEALTH_REFRESH_DELAY=%r isn't a delay in seconds; using %ds"
              % (os.environ.get("HEALTH_REFRESH_DELAY"), BOOT_DELAY), flush=True)
        delay = BOOT_DELAY
    only = {s.strip().upper() for s in (os.environ.get("HEALTH_REFRESH_ISOS") or "").split(",") if s.strip()}

    def loop():
        _load_stored()             # a redeploy picks up the last refresh at once
        time.sleep(delay)          # after the first health checks and warm-ups
        short = bool(only)         # the test run is the first check only
        while True:
            try:
                _load_stored()
                if short:
                    short = False
                    refresh(force=True, only=only)
                else:
                    refresh()
            except Exception as e:  # the thread must outlive any one bad check
                print("[health] check failed: %s" % e, flush=True)
            time.sleep(CHECK_EVERY)

    threading.Thread(target=loop, daemon=True, name="health-refresh").start()
    print("[health] refresher started (first check in %ds%s)" % (
        delay, ", only " + ",".join(sorted(only)) if only else ""), flush=True)
    return True
