#!/usr/bin/env python3
"""The send's photo check (fxtracker/cover_check.py), offline: before an
issue goes out each cover is asked for at the address the email will use,
and a photo that definitely does not load gives way to the country's next
approved one. Nothing here touches the network: the digest's inputs are
digest_snapshot.py's frozen fixtures (urlopen raises), the image service is
a fake swapped in at cover_check.fetch, and Buttondown is test_send_digest's
FakeButtondown.

    /usr/bin/python3 scripts/test_cover_check.py

  1. one answer: which are LOADS, BROKEN and UNKNOWN (the two answers
     measured on 2026-11-10 among them), and the request itself: one GET, a
     User-Agent that names nobody, a wait of 8 seconds at most, the body's
     first byte and no more;
  2. every cover loads: the payload and the email are those of a run that
     never asked (all 12 months, the golden hashes; all ten editions), the
     addresses asked are the <img> addresses in the email, the top card's
     banner and every other card's small copy, each once, and the log is
     one line;
  3. a photo that does not load, twice in a row: the next approved photo
     takes its place in the card and in the credits block, with its own
     credit (the top card and a compact one); a photo the site's checks
     refuse is never asked for; the email still says what its payload says
     (digest_check);
  4. what keeps a photo: a second look that loads, and every answer that is
     not a definite no (a timeout, no connection, 5xx, 403, 408, 429, a
     whole service that is down);
  5. no approved photo left: the card has no photo and no credit, and the
     email still renders, with every country at once too;
  6. the check can't stop a send: the service, the clock, the pause and the
     log line each raising leave the photo where it was;
  7. the 60 seconds: requests stop when they are used up, the rest go out
     unchecked, one line says so, and a wait is cut to what is left;
  8. several editions: an address is asked once a run, a country that leads
     one edition and not another is asked at both sizes, and a line is
     printed once;
  9. through send_digest.py with a fake Buttondown: a send, a --draft and a
     --dry-run all ask; a replaced photo, no photo at all, a raising check,
     a dead network (the real fetch on the frozen urlopen) and a spent
     budget all still send, exit 0;
 10. nobody else asks: picks.build without the check makes no request, and
     the monthly workflow needs nothing new (standard library only, no
     environment variable, a worst case far inside the job's time).
"""
import ast
import hashlib
import importlib
import json
import os
import re
import socket
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import digest_check as dc  # noqa: E402
import digest_snapshot as ds  # noqa: E402
import test_send_digest as tsd  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

H = tsd.Harness()                       # frozen inputs; imports send_digest
picks, nl, sd = H.picks, H.newsletter, H.sd
# The harness left a fake where every cover loads; reloading puts the
# module's own fetch back (send_digest holds this same module object).
cc = importlib.reload(sd.cover_check)
REAL_FETCH = cc.fetch
V = H.dv.VARIANTS
with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
    ACTS = json.load(f)
with open(os.path.join(HERE, "digest_golden", "usd_sha256.json"), encoding="utf-8") as f:
    GOLDEN = json.load(f)["sha256"]

OKAY = (200, "image/jpeg", b"\xff")     # a cover of the Nov 1 issue, as measured
E404 = (404, "", b"")                   # what fetch() makes of the service's 404


class Service(object):
    """The image service, faked. `answers` maps an address to what it
    answers, in order, the last one repeating; every other address gives
    `default`. An answer is (status, content type, first byte) or an
    exception, which is raised. `tick` runs at each request (a clock)."""

    def __init__(self, answers=None, default=OKAY, tick=None):
        self.answers = {u: list(a) for u, a in (answers or {}).items()}
        self.default, self.tick = default, tick
        self.asked, self.timeouts = [], []

    def __call__(self, url, timeout=None):
        self.asked.append(url)
        self.timeouts.append(timeout)
        if self.tick:
            self.tick()
        q = self.answers.get(url)
        a = (q.pop(0) if len(q) > 1 else q[0]) if q else self.default
        if isinstance(a, BaseException):
            raise a
        return a


def checked(month, svc, variant="USD", shared=None, check=None, **kw):
    """Build and render one issue with the check on, against `svc`.
    Returns (payload, [subject, body], the check's lines, its pauses)."""
    lines, pauses = [], []
    chk = check or cc.CoverCheck(sleep=pauses.append, out=lines.append, **kw)
    cc.fetch = svc
    try:
        if shared is None:
            data = picks.build(month=month, cover_check=chk)
        else:
            data = picks.build_variant(shared, V[variant], cover_check=chk)
        if check is None:
            chk.report()
    finally:
        cc.fetch = REAL_FETCH
    return data, list(nl.render_digest(data)), lines, pauses


def approved(iso):
    """A country's approved photos under the fakes, in the rule's order, as
    (label, cover): worked out here, not by the code under test (`photo`
    first, then the gallery's first six, each once)."""
    a, seen, out = ACTS[iso], [], []
    for e in ([a["photo"]] if a.get("photo") else []) + list(a.get("gallery") or [])[:6]:
        if e in seen:
            continue
        seen.append(e)
        c = ds.fake_cover_file(e["file"]) if isinstance(e, dict) else ds.fake_cover(e)
        if c:
            out.append((e["label"] if isinstance(e, dict) else e, c))
    return out


def card_photos(body):
    """{country: its card's <img> address} for the cards that show a photo,
    and the same addresses in card order."""
    found = re.findall(r"<img src='([^']+)' width='(?:560|194' height='148)' alt='([^']+)'", body)
    assert [u for u, _n in found] == tsd.photos_in(body), "a cover <img> this reader can't read"
    return {n: u for u, n in found}, [u for u, _n in found]


def credit_names(body):
    """The countries the credits block names, in order ([] with no block)."""
    m = re.search(r"Photos \(cropped\) via Wikimedia Commons\. (.*?)</div>", body, re.S)
    return re.findall(r"(?:^|&nbsp;&middot; )([^:<]+): <a ", m.group(1)) if m else []


def sha(sb):
    return hashlib.sha256((sb[0] + "\n" + sb[1]).encode("utf-8")).hexdigest()


def says_its_payload(data, sb, variant="USD"):
    return dc.check(nl, picks, V[variant], data, sb[0], sb[1]) + dc.proofing(sb[1])


def same_but(data, base, changed):
    """`data` is `base` in everything but the photo fields of the picks
    named in `changed` (ISO codes)."""
    a, b = json.loads(json.dumps(data)), json.loads(json.dumps(base))
    for d in (a, b):
        for s in d["picks"]:
            if s["iso"] in changed:
                for k in ("photo", "photo_thumb", "photo_credit"):
                    s.pop(k)
    return a == b


# A run that never asked, every month: what "nothing changed" means below.
PLAIN = {m: picks.build(month=m) for m in range(1, 13)}
PLAIN_SB = {m: list(nl.render_digest(PLAIN[m])) for m in PLAIN}
FEB = PLAIN[2]
ISOS = [s["iso"] for s in FEB["picks"]]
TOP, SECOND = FEB["picks"][0], FEB["picks"][1]
FEB_ASKED = [TOP["photo"]] + [s["photo_thumb"] for s in FEB["picks"][1:]]

print("1. one answer: LOADS, BROKEN or UNKNOWN; the request")
L, B, U = cc.LOADS, cc.BROKEN, cc.UNKNOWN
table = [
    (OKAY, L), ((200, "IMAGE/WebP; q=1", b"R"), L), ((200, "image/png", b"\x89"), L),
    (E404, B), ((400, "", b""), B), ((410, "", b""), B), ((422, "", b""), B),
    ((200, "text/html; charset=utf-8", b"<"), B), ((200, "application/json", b"{"), B),
    ((200, "", b"\xff"), B), ((200, "image/jpeg", b""), B),
    ((500, "", b""), U), ((502, "", b""), U), ((503, "", b""), U), ((504, "", b""), U),
    ((403, "", b""), U), ((408, "", b""), U), ((429, "", b""), U),
    ((204, "image/jpeg", b""), U), ((206, "image/jpeg", b"\xff"), U), ((304, "", b""), U),
]
wrong = [(a, cc.verdict(*a)[0]) for a, want in table if cc.verdict(*a)[0] != want]
results.append(ok(not wrong,
                  "%d answers sorted: 200 with an image type and a body loads; 400, 404, 410, 422 and a 200 that "
                  "is HTML, JSON, untyped or empty are broken; 5xx, 403, 408, 429 and any other status are unknown%s"
                  % (len(table), "" if not wrong else " -> %r" % wrong)))
results.append(ok(cc.verdict(*OKAY) == (L, "") and cc.verdict(*E404) == (B, "HTTP 404")
                  and cc.verdict(200, "text/html; charset=utf-8", b"<") == (B, "not an image: text/html")
                  and cc.verdict(200, "image/jpeg", b"") == (B, "an empty file")
                  and cc.verdict(503, "", b"") == (U, "HTTP 503"),
                  "each answer comes with its reason in plain words (HTTP 404, not an image: text/html, an empty "
                  "file, HTTP 503)"))


class Resp(object):
    def __init__(self, status, ctype, body):
        self.status, self.headers, self.body, self.reads = status, {"Content-Type": ctype}, body, []

    def read(self, n=-1):
        self.reads.append(n)
        return self.body[:n] if n >= 0 else self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


frozen_urlopen = urllib.request.urlopen
seen = []
resp = Resp(200, "image/jpeg", b"\xff\xd8\xff\xdb" * 2000)


def urlopen(req, timeout=None, context=None):
    seen.append((req, timeout, context))
    if "gone" in req.full_url:
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {"Content-Type": "application/json"}, None)
    if "down" in req.full_url:
        raise urllib.error.URLError(socket.timeout("timed out"))
    return resp


urllib.request.urlopen = urlopen
try:
    addr = TOP["photo"]
    got = REAL_FETCH(addr)
    req, timeout, context = seen[-1]
    ua = req.get_header("User-agent") or ""
    results.append(ok(got == (200, "image/jpeg", b"\xff") and req.full_url == addr and req.get_method() == "GET"
                      and req.data is None and resp.reads == [1] and len(seen) == 1,
                      "fetch: one GET of the address as given, the body's first byte read and no more"))
    results.append(ok(ua == cc.UA and list(req.headers) == ["User-agent"] and "@" not in ua
                      and not re.search(r"wander|grade|doug|fx-?tracker|https?:|\.com|python", ua, re.I),
                      "its one header is a generic User-Agent, no address and no name in it: %r" % ua))
    results.append(ok(timeout == cc.TIMEOUT and 0 < cc.TIMEOUT <= 8 and context is cc.rates._SSL
                      and REAL_FETCH(addr, 3) and seen[-1][1] == 3,
                      "each network wait of a request is cut off after %d seconds (less when told; it is the "
                      "socket timeout, not a limit on the whole request), certificates checked as the other "
                      "fetches' are" % cc.TIMEOUT))
    gone = REAL_FETCH(addr + "&gone")
    try:
        REAL_FETCH(addr + "&down")
        raised = None
    except Exception as e:
        raised = e
    results.append(ok(gone == (404, "", b"") and cc.verdict(*gone)[0] == B
                      and isinstance(raised, urllib.error.URLError) and cc._why(raised) == "timed out",
                      "an HTTP error status comes back as an answer (404 -> broken); a timeout is raised, and reads "
                      "'timed out' in the log"))
finally:
    urllib.request.urlopen = frozen_urlopen

print("2. every cover loads: nothing changes, and what was asked")
moved, logs, asks = [], set(), 0
for m in range(1, 13):
    svc = Service()
    data, sb, lines, pauses = checked(m, svc)
    by_card, in_order = card_photos(sb[1])
    asks += len(svc.asked)
    if not (data == PLAIN[m] and sb == PLAIN_SB[m] and sha(sb) == GOLDEN[str(m)] and svc.asked == in_order
            and len(set(svc.asked)) == len(svc.asked) and not pauses
            and lines == ["cover check: all %d photos loaded" % len(in_order)]
            and all(t == cc.TIMEOUT for t in svc.timeouts)):
        moved.append(m)
    logs.update(lines)
results.append(ok(not moved and asks >= 48,
                  "USD, all 12 months: the payload and the email are those of a run that never asked, the 12 "
                  "golden hashes hold, %d addresses asked once each with no second look, one log line (%s)%s"
                  % (asks, " / ".join(sorted(logs)), "" if not moved else " -> months %r differ" % moved)))
svc = Service()
data, sb, lines, _p = checked(2, svc)
by_card, in_order = card_photos(sb[1])
# The "440x336" below comes from digest_snapshot.fake_cover's stand-in name
# (the covers here are its fakes), so on its own it can't see picks.THUMB_W x
# THUMB_H move. test_digest_variants 8 (fake_cover's name against
# picks.THUMB_W/H, and each compact card's photo against its pick's small
# copy) and test_cover_rule (picks._banner's &w=440&h=336) tie it to them.
results.append(ok(svc.asked == FEB_ASKED == in_order and len(in_order) == 5
                  and "1024x420" in svc.asked[0] and all("440x336" in u for u in svc.asked[1:])
                  and by_card[TOP["name"]] == TOP["photo"]
                  and all(by_card[s["name"]] == s["photo_thumb"] != s["photo"] for s in FEB["picks"][1:]),
                  "February: the addresses asked are the email's own <img> addresses, in card order: the top "
                  "card's 1024x420 banner (%s) and the four other cards' 440x336 copies; no banner of theirs, "
                  "no small copy of the top card's" % TOP["name"]))
# A cover that carries no small copy shows its banner in a compact card
# (newsletter._compact_card), so that is the address asked.
svc, lines = Service(), []
cc.fetch = svc
try:
    chk = cc.CoverCheck(sleep=lambda s: None, out=lines.append)
    memo = {("title", "A1"): {"url": "T:A1", "credit": {"page": "A1"}}}
    s = picks._enrich({"iso": "AA", "name": "Aland"}, {"AA": {"gallery": ["A1"]}}, True, memo, check=chk, top=False)
finally:
    cc.fetch = REAL_FETCH
results.append(ok(svc.asked == ["T:A1"] and (s["photo"], s["photo_thumb"]) == ("T:A1", None),
                  "a cover with no small copy is asked for at its banner address, the one a compact card then shows"))

print("3. a photo that does not load, twice in a row, gives way to the next approved one")
vn, th = approved(TOP["iso"]), approved(SECOND["iso"])
refused = [e for e in picks.cover_candidates(ACTS[SECOND["iso"]]) if isinstance(e, str) and not ds.fake_cover(e)]
svc = Service({vn[0][1]["url"]: [E404], th[0][1]["thumb"]: [E404]})
data, sb, lines, pauses = checked(2, svc)
p0, p1 = data["picks"][0], data["picks"][1]
by_card, in_order = card_photos(sb[1])
results.append(ok(len(vn) > 1 and len(th) > 1 and (TOP["photo"], SECOND["photo_thumb"]) == (vn[0][1]["url"], th[0][1]["thumb"])
                  and (p0["photo"], p0["photo_thumb"], p0["photo_credit"]) == (vn[1][1]["url"], vn[1][1]["thumb"], vn[1][1]["credit"])
                  and (p1["photo"], p1["photo_thumb"], p1["photo_credit"]) == (th[1][1]["url"], th[1][1]["thumb"], th[1][1]["credit"])
                  and same_but(data, FEB, {TOP["iso"], SECOND["iso"]}) and not same_but(data, FEB, {TOP["iso"]}),
                  "the payload: %s (top card) moves from %s to %s and %s (a compact card) from %s to %s, each with "
                  "the new photo's banner, small copy and credit; nothing else in the payload moves"
                  % (TOP["name"], vn[0][0], vn[1][0], SECOND["name"], th[0][0], th[1][0])))
old_pages = [vn[0][1]["credit"]["page"], th[0][1]["credit"]["page"]]
new_pages = [vn[1][1]["credit"]["page"], th[1][1]["credit"]["page"]]
results.append(ok(by_card[TOP["name"]] == vn[1][1]["url"] and by_card[SECOND["name"]] == th[1][1]["thumb"]
                  and credit_names(sb[1]) == [s["name"] for s in data["picks"]]
                  and all(sb[1].count(nl._esc(p)) == 1 for p in new_pages)
                  and all(vn[1][1]["credit"]["artist"] != c["credit"]["artist"] for c in (vn[0][1],))
                  and not any(x in sb[1] for x in old_pages + [vn[0][1]["url"], vn[0][1]["thumb"], th[0][1]["url"],
                                                              th[0][1]["thumb"], vn[0][1]["credit"]["artist"],
                                                              th[0][1]["credit"]["artist"]])
                  and not says_its_payload(data, sb),
                  "the email: each card shows the new photo and the credits block credits it (its photographer, its "
                  "file page); the photo that did not load, its address and its credit are nowhere; the email "
                  "still says what its payload says (digest_check)"))
results.append(ok(svc.asked == [vn[0][1]["url"]] * 2 + [vn[1][1]["url"]] + [th[0][1]["thumb"]] * 2 + [th[1][1]["thumb"]]
                  + FEB_ASKED[2:] and pauses == [cc.RETRY_PAUSE] * 2 and cc.RETRY_PAUSE > 0
                  and refused and svc.asked == in_order[:0] + svc.asked and sorted(set(svc.asked) - set(in_order))
                  == sorted([vn[0][1]["url"], th[0][1]["thumb"]]),
                  "the requests: two looks at each broken address, a pause between them, then the next approved "
                  "photo at this card's size; %s's %s, which the site's checks refuse, is never asked for"
                  % (SECOND["name"], " and ".join(refused[-1:]))))
want = ["cover check: %s: %s did not load (HTTP 404), using %s" % (TOP["name"], vn[0][0], vn[1][0]),
        "cover check: %s: %s did not load (HTTP 404), using %s" % (SECOND["name"], th[0][0], th[1][0]),
        "cover check: 5 of 7 photos loaded, 2 did not load, 0 could not be checked"]
results.append(ok(lines == want, "the log, in plain words: %s%s"
                  % (" | ".join(want), "" if lines == want else " -> got %r" % lines)))
# A 200 that is not an image, and one with nothing in it, are broken too.
svc = Service({vn[0][1]["url"]: [(200, "text/html; charset=utf-8", b"<")], th[0][1]["thumb"]: [(200, "image/jpeg", b"")]})
data2, sb2, lines2, _p = checked(2, svc)
results.append(ok(data2 == data and sb2 == sb
                  and lines2[:2] == ["cover check: %s: %s did not load (not an image: text/html), using %s"
                                     % (TOP["name"], vn[0][0], vn[1][0]),
                                     "cover check: %s: %s did not load (an empty file), using %s"
                                     % (SECOND["name"], th[0][0], th[1][0])],
                  "a 200 that is an HTML page, and a 200 image with an empty body, are replaced the same way"))
# A pinned file is named by its label.
svc, lines = Service({"f:P.jpg": [E404]}), []
cc.fetch = svc
try:
    chk = cc.CoverCheck(sleep=lambda s: None, out=lines.append)
    memo = {("file", "P.jpg"): {"url": "F:P.jpg", "thumb": "f:P.jpg", "credit": {"page": "P"}},
            ("title", "G2"): {"url": "T:G2", "thumb": "t:G2", "credit": {"page": "G2"}}}
    s = picks._enrich({"iso": "AA", "name": "Aland"},
                      {"AA": {"gallery": [{"file": "P.jpg", "label": "Place 3"}, "G2"]}}, True, memo, check=chk)
finally:
    cc.fetch = REAL_FETCH
results.append(ok((s["photo"], s["photo_thumb"], s["photo_credit"]) == ("T:G2", "t:G2", {"page": "G2"})
                  and lines == ["cover check: Aland: Place 3 did not load (HTTP 404), using G2"]
                  and memo[("file", "P.jpg")]["url"] == "F:P.jpg",
                  "a pinned file is named in the log by its label; the lookup memo keeps the photo (it passed the "
                  "site's checks; only this run's check passed it over)"))

print("4. what keeps a photo")
svc = Service({TOP["photo"]: [E404, OKAY]})
data, sb, lines, pauses = checked(2, svc)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and svc.asked == [TOP["photo"]] * 2 + FEB_ASKED[1:] and pauses == [cc.RETRY_PAUSE]
                  and lines == ["cover check: %s: %s loaded on the second try, first answer HTTP 404" % (TOP["name"], vn[0][0]),
                                "cover check: all 5 photos loaded"],
                  "broken once, then it loads: kept, the email unchanged, two requests, and the log says so"))
kept = {}
for name, answer, why in (
        ("a timeout", socket.timeout("timed out"), "timed out"),
        ("a timeout inside urlopen", urllib.error.URLError(socket.timeout("timed out")), "timed out"),
        ("no connection", urllib.error.URLError(ConnectionRefusedError(61, "Connection refused")),
         "URLError: [Errno 61] Connection refused"),
        ("HTTP 500", (500, "", b""), "HTTP 500"), ("HTTP 503", (503, "", b""), "HTTP 503"),
        ("HTTP 429", (429, "", b""), "HTTP 429"), ("HTTP 403", (403, "", b""), "HTTP 403"),
        ("HTTP 408", (408, "", b""), "HTTP 408"), ("HTTP 204", (204, "", b""), "HTTP 204")):
    svc = Service({SECOND["photo_thumb"]: [answer]})
    data, sb, lines, pauses = checked(2, svc)
    kept[name] = (data == FEB and sb == PLAIN_SB[2] and svc.asked == FEB_ASKED and not pauses
                  and lines == ["cover check: %s: could not check %s (%s), keeping it" % (SECOND["name"], th[0][0], why),
                                "cover check: 4 of 5 photos loaded, 0 did not load, 1 could not be checked"])
results.append(ok(all(kept.values()) and len(kept) == 9,
                  "an answer that is not a definite no keeps the photo, with one request and one line: %s%s"
                  % (", ".join(kept), "" if all(kept.values()) else " -> not: %r" % [k for k in kept if not kept[k]])))
svc = Service({SECOND["photo_thumb"]: [E404, (503, "", b"")]})
data, sb, lines, _p = checked(2, svc)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and svc.asked.count(SECOND["photo_thumb"]) == 2
                  and lines[0] == "cover check: %s: could not check %s (HTTP 404, then HTTP 503), keeping it"
                  % (SECOND["name"], th[0][0]),
                  "broken once, then unknown: kept (a photo goes only on two definite answers in a row)"))
for name, default in (("times out", socket.timeout("timed out")), ("answers 503", (503, "", b""))):
    svc = Service(default=default)
    data, sb, lines, pauses = checked(2, svc)
    results.append(ok(data == FEB and sb == PLAIN_SB[2] and svc.asked == FEB_ASKED and len(lines) == 6
                      and all(": could not check " in l and l.endswith(", keeping it") for l in lines[:5])
                      and lines[5] == "cover check: 0 of 5 photos loaded, 0 did not load, 5 could not be checked",
                      "a service that %s for every address strips nothing: all five photos kept, the email "
                      "unchanged, five requests" % name))

print("5. no approved photo left")
fourth = FEB["picks"][3]
cl = approved(fourth["iso"])
svc = Service({c["thumb"]: [E404] for _l, c in cl})
data, sb, lines, _p = checked(2, svc)
by_card, in_order = card_photos(sb[1])
p3 = data["picks"][3]
gone = "cover check: %s: %s, no other approved photo, so the card goes out without one" % (
    fourth["name"], ", ".join("%s did not load (HTTP 404)" % l for l, _c in cl))
results.append(ok(len(cl) >= 2 and (p3["photo"], p3["photo_thumb"], p3["photo_credit"]) == (None, None, None)
                  and same_but(data, FEB, {fourth["iso"]}) and fourth["name"] not in by_card and len(by_card) == 4
                  and credit_names(sb[1]) == [s["name"] for s in FEB["picks"] if s["iso"] != fourth["iso"]]
                  and not any(c["credit"]["page"] in sb[1] or c["thumb"] in sb[1] for _l, c in cl)
                  and ">%s<" % fourth["name"] in sb[1] and not says_its_payload(data, sb)
                  and lines[0] == gone and svc.asked.count(cl[-1][1]["thumb"]) == 2,
                  "all %d of %s's approved photos broken: its card has no photo and the credits block no entry for "
                  "it, the card and the other four are whole, and the log reads: %s" % (len(cl), fourth["name"], lines[0])))
svc = Service(default=E404)
data, sb, lines, _p = checked(2, svc)
results.append(ok(all(s["photo"] is None and s["photo_credit"] is None for s in data["picks"])
                  and "<img src='https://images." not in sb[1] and "Photos (cropped)" not in sb[1]
                  and card_photos(sb[1]) == ({}, []) and same_but(data, FEB, set(ISOS))
                  and all(">%s<" % s["name"] in sb[1] for s in FEB["picks"]) and not says_its_payload(data, sb)
                  and len(svc.asked) == 2 * sum(len(approved(i)) for i in ISOS)
                  and lines[-1] == "cover check: 0 of %d photos loaded, %d did not load, 0 could not be checked"
                  % (len(svc.asked) // 2, len(svc.asked) // 2),
                  "every address a definite 404: no card has a photo, there is no credits block, and the email "
                  "still renders with all five cards and says what its payload says (%d requests)" % len(svc.asked)))

print("6. the check can't stop a send")
svc = Service(default=RuntimeError("boom"))
data, sb, lines, _p = checked(2, svc)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and svc.asked == FEB_ASKED
                  and lines[0] == "cover check: %s: could not check %s (RuntimeError: boom), keeping it" % (TOP["name"], vn[0][0])
                  and len(lines) == 6,
                  "the service raising at every request: every photo kept, the email unchanged, one line each: %s"
                  % lines[0]))


def boom(*a, **k):
    raise RuntimeError("boom")


svc = Service(default=None)                          # an answer that is no answer at all
data, sb, lines, _p = checked(2, svc)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and len(lines) == 6 and "could not check" in lines[0],
                  "the service answering nonsense: kept, counted as could-not-check"))
svc = Service()
data, sb, lines, _p = checked(2, svc, clock=boom)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and not svc.asked and len(lines) == 6
                  and lines[0].endswith("(RuntimeError: boom), keeping it"),
                  "the clock raising: kept, nothing asked, one line each"))
svc, lines = Service({TOP["photo"]: [E404]}), []
cc.fetch = svc
try:
    chk = cc.CoverCheck(sleep=boom, out=lines.append)
    data = picks.build(month=2, cover_check=chk)
    chk.report()
finally:
    cc.fetch = REAL_FETCH
results.append(ok(data == FEB and lines[0] == "cover check: %s: the check of %s failed (RuntimeError: boom), keeping it"
                  % (TOP["name"], vn[0][0]),
                  "the pause before the second look raising: the photo is kept (%s)" % lines[0]))
svc = Service(default=E404)
cc.fetch = svc
try:
    chk = cc.CoverCheck(sleep=lambda s: None, out=boom)
    data = picks.build(month=2, cover_check=chk)
    chk.report()
    quiet = True
except Exception as e:
    quiet = False
finally:
    cc.fetch = REAL_FETCH
results.append(ok(quiet and all(s["photo"] is None for s in data["picks"]),
                  "a log line that can't be printed raises nothing: the check goes on"))


class Broken(object):
    """A check whose answers are lost: _ask raises, whatever it is asked."""

    def __init__(self):
        self.real = cc.CoverCheck(out=lambda l: lines.append(l))
        self.real._ask = boom

    def choose(self, *a):
        return self.real.choose(*a)

    def report(self):
        return self.real.report()


lines = []
data = picks.build(month=2, cover_check=Broken())
results.append(ok(data == FEB and len(lines) == 5 and all(" failed (RuntimeError: boom), keeping it" in l for l in lines),
                  "the check's own code raising: every photo kept, one line each"))

print("7. the 60 seconds")


class Clock(object):
    def __init__(self, start=1000.0):
        self.t = start

    def __call__(self):
        return self.t

    def tick(self, by):
        return lambda: setattr(self, "t", self.t + by)


clock = Clock()
svc = Service(tick=clock.tick(25))
data, sb, lines, _p = checked(2, svc, clock=clock)
spent = "cover check: out of time after 60 seconds, so the photos not yet checked go out as they are"
results.append(ok(cc.BUDGET == 60 and data == FEB and sb == PLAIN_SB[2] and svc.asked == FEB_ASKED[:3]
                  and lines == [spent, "cover check: 3 of 5 photos loaded, 0 did not load, 2 could not be checked"],
                  "requests of 25 s each: three fit in the 60 s, counted from the first request; the last two "
                  "photos go out unchecked, kept, and one line says so: %s" % spent))
clock = Clock()
svc = Service(tick=clock.tick(27))
data, sb, lines, _p = checked(2, svc, clock=clock)
results.append(ok(data == FEB and svc.timeouts == [8, 8, 6] and lines[0] == spent,
                  "a request never waits past the budget: with 6 s left it is given 6, not 8 (%r)" % svc.timeouts))
clock = Clock()
svc = Service({TOP["photo"]: [E404]}, tick=clock.tick(61))
data, sb, lines, _p = checked(2, svc, clock=clock)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and svc.asked == [TOP["photo"]] and lines[0] == spent
                  and lines.count(spent) == 1 and len(lines) == 2,
                  "broken once, and the time is up before the second look: kept, and the line is printed once"))
svc = Service(default=E404)
data, sb, lines, _p = checked(2, svc, budget=0)
results.append(ok(data == FEB and sb == PLAIN_SB[2] and not svc.asked and lines[0] == spent.replace("60", "0"),
                  "with no time at all nothing is asked and nothing is dropped"))
worst = cc.BUDGET + cc.RETRY_PAUSE + cc.TIMEOUT
results.append(ok(0 < cc.TIMEOUT <= 8 and 45 <= cc.BUDGET <= 75 and worst < 90,
                  "the limits: %d s for each network wait of a request, %d s in which a run may start one; the "
                  "last request can start just inside the budget, so a run's requests end about %d s after the "
                  "first, more only if a connection stalls in stages" % (cc.TIMEOUT, cc.BUDGET, worst)))

print("8. several editions share one check")
codes = tuple(tsd.ALL_SEND)
shared0 = picks.gather(2)
plain10 = {c: picks.build_variant(shared0, V[c]) for c in codes}
plain10_sb = {c: list(nl.render_digest(plain10[c])) for c in codes}
svc, lines = Service(), []
chk = cc.CoverCheck(sleep=lambda s: None, out=lines.append)
shared1 = picks.gather(2)
got10 = {c: checked(2, svc, c, shared1, chk) for c in codes}
chk.report()
in_emails = sorted({u for c in codes for u in tsd.photos_in(got10[c][1][1])})
tops = {plain10[c]["picks"][0]["iso"] for c in codes}
both = sorted(i for i in tops if any(i in [s["iso"] for s in plain10[c]["picks"][1:]] for c in codes))
banner = {s["iso"]: s["photo"] for c in codes for s in plain10[c]["picks"]}
small = {s["iso"]: s["photo_thumb"] for c in codes for s in plain10[c]["picks"]}
results.append(ok(all(got10[c][0] == plain10[c] and got10[c][1] == plain10_sb[c] for c in codes)
                  and sorted(svc.asked) == in_emails and len(in_emails) > 5
                  and lines == ["cover check: all %d photos loaded" % len(in_emails)],
                  "all ten February editions through one check: each payload and email is the unchecked one, and "
                  "the %d different <img> addresses in the ten emails were asked once each (%d cards)"
                  % (len(in_emails), sum(len(plain10[c]["picks"]) for c in codes))))
results.append(ok(both and all(banner[i] in svc.asked and small[i] in svc.asked for i in both),
                  "a country that leads one edition and sits lower in another is asked at both sizes (%s)"
                  % ", ".join(both)))
# One broken address that several editions' cards use: two looks in all,
# one line, and every edition gets the next photo.
users = [c for c in codes if SECOND["iso"] in [s["iso"] for s in plain10[c]["picks"][1:]]]
svc, lines = Service({th[0][1]["thumb"]: [E404]}), []
chk = cc.CoverCheck(sleep=lambda s: None, out=lines.append)
shared2 = picks.gather(2)
got = {c: checked(2, svc, c, shared2, chk) for c in codes}
moved_to = {c: [s["photo_thumb"] for s in got[c][0]["picks"][1:] if s["iso"] == SECOND["iso"]] for c in users}
results.append(ok(len(users) > 1 and svc.asked.count(th[0][1]["thumb"]) == 2 and svc.asked.count(th[1][1]["thumb"]) == 1
                  and all(moved_to[c] == [th[1][1]["thumb"]] for c in users)
                  and lines == ["cover check: %s: %s did not load (HTTP 404), using %s" % (SECOND["name"], th[0][0], th[1][0])]
                  and all(not says_its_payload(got[c][0], got[c][1], c) for c in codes),
                  "one broken address in %d editions' cards: two looks in the whole run, one log line, and each "
                  "of those editions shows the next photo" % len(users)))

print("9. through send_digest.py, with a fake Buttondown")
tags10 = ["currency-" + c.lower() for c in tsd.ALL_SEND] + ["cadence-monthly", "vip"]
readers = lambda: tsd.FakeButtondown(tsd.subs({"a@x.test": "", "b@x.test": "cadence-monthly"}), tags10)


def send(argv, svc, fetch=None, f=None, **kw):
    """One send_digest run against the image service `svc` (or `fetch`).
    send_digest builds its own check, with the real pause before a second
    look: that second is taken out here so the run doesn't wait it out."""
    f = f or readers()
    pause, cc.RETRY_PAUSE, cc.fetch = cc.RETRY_PAUSE, 0, fetch or svc
    try:
        code, out = H.run(argv, f, **kw)
    finally:
        cc.RETRY_PAUSE, cc.fetch = pause, REAL_FETCH
    return code, out, f


asks = {}
for name, argv in (("a send", ["--month", "2"]), ("a --draft", ["--draft", "--month", "2"]),
                   ("a --dry-run", ["--dry-run", "--month", "2"])):
    svc = Service()
    code, out, f = send(argv, svc)
    bodies = [c[2]["body"] for c in f.creates()] or [PLAIN_SB[2][1]] * out.count("\n" + PLAIN_SB[2][1] + "\n")
    asks[name] = (code == 0 and svc.asked == FEB_ASKED and bodies == [PLAIN_SB[2][1]]
                  and out.count("cover check:") == 1 and "cover check: all 5 photos loaded\nDigest for February" in out)
results.append(ok(all(asks.values()) and len(asks) == 3,
                  "a send, a --draft and a --dry-run each ask for the five addresses before the issue is built, "
                  "print the one line and carry the unchanged email%s"
                  % ("" if all(asks.values()) else " -> not: %r" % [k for k in asks if not asks[k]])))
svc = Service(dict({vn[0][1]["url"]: [E404]}, **{c["thumb"]: [E404] for _l, c in cl}))
want_data, want_sb, want_lines, _p = checked(2, Service(dict(svc.answers)))
code, out, f = send(["--month", "2"], svc)
cr = f.creates()
results.append(ok(code == 0 and len(cr) == 1 and [cr[0][2]["subject"], cr[0][2]["body"]] == want_sb
                  and want_data["picks"][0]["photo"] == vn[1][1]["url"] and want_data["picks"][3]["photo"] is None
                  and len(f.publishes()) == 1 and f.received() == {"a@x.test": ["USD"], "b@x.test": ["USD"]}
                  and [l for l in out.splitlines() if l.startswith("cover check:")] == want_lines and len(want_lines) == 3
                  and "Sent digest to Buttondown subscribers." in out,
                  "a send with %s's photo replaced and %s's gone: the email sent is that one, to every reader, "
                  "exit 0, with the three lines in the log" % (TOP["name"], fourth["name"])))
svc = Service(default=E404)
code, out, f = send(["--month", "2"], svc)
body = f.creates()[0][2]["body"] if f.creates() else ""
results.append(ok(code == 0 and len(f.publishes()) == 1 and len(f.received()) == 2 and body
                  and tsd.photos_in(body) == [] and "Photos (cropped)" not in body,
                  "every candidate broken: the issue still sends, without photos or credits, exit 0"))
for name, kw, n_asked in (("the image service raising at every request", {"svc": Service(default=RuntimeError("boom"))}, 5),
                          ("the network dead (the real fetch, on the frozen urlopen)", {"svc": None, "fetch": REAL_FETCH}, 0)):
    code, out, f = send(["--month", "2"], **kw)
    cr = f.creates()
    results.append(ok(code == 0 and len(cr) == 1 and cr[0][2]["body"] == PLAIN_SB[2][1] and len(f.publishes()) == 1
                      and len(f.received()) == 2 and out.count(": could not check ") == 5
                      and out.count(", keeping it\n") == 5 and (kw["svc"] is None or len(kw["svc"].asked) == n_asked)
                      and "cover check: 0 of 5 photos loaded, 0 did not load, 5 could not be checked\n" in out,
                      "%s: all five photos kept, the unchanged email sent to every reader, exit 0" % name))
saved_budget, cc.BUDGET = cc.BUDGET, 0
try:
    svc = Service(default=E404)
    code, out, f = send(["--month", "2"], svc)
finally:
    cc.BUDGET = saved_budget
results.append(ok(code == 0 and not svc.asked and f.creates()[0][2]["body"] == PLAIN_SB[2][1] and len(f.publishes()) == 1
                  and out.count("cover check: out of time after 0 seconds") == 1,
                  "the budget spent: nothing asked, the unchanged email sent, the line printed once, exit 0"))
svc = Service({th[0][1]["thumb"]: [E404]})
code, out, f = send(["--month", "2"], svc, f=tsd.FakeButtondown(tsd.subs({"e@x": "currency-eur", "u@x": ""}), tags10),
                    rollout={"USD": "send", "EUR": "send"})
sent = {tsd.edition_of(c): c[2]["body"] for c in f.creates()}
in_sent = sorted({u for b in sent.values() for u in tsd.photos_in(b)})
results.append(ok(code == 0 and sorted(sent) == ["EUR", "USD"] and f.received() == {"e@x": ["EUR"], "u@x": ["USD"]}
                  and len(set(svc.asked)) == len(svc.asked) - 1 and svc.asked.count(th[0][1]["thumb"]) == 2
                  and sorted(set(svc.asked) - {th[0][1]["thumb"]}) == in_sent
                  and th[0][1]["thumb"] not in "".join(sent.values())
                  and out.count("cover check:") == 2 and out.count("did not load (HTTP 404), using") == 1,
                  "USD and EUR switched on: one check for the run (%d addresses, each asked once, the broken one "
                  "twice), neither email carries the broken photo, both go out" % len(set(svc.asked))))

print("10. nobody else asks; the workflow needs nothing new")
cc.fetch = boom
try:
    quiet = picks.build(month=2) == FEB and list(nl.render_digest(picks.build(month=2))) == PLAIN_SB[2]
    shared3 = picks.gather(2)
    quiet = quiet and all(picks.build_variant(shared3, V[c]) == plain10[c] for c in codes)
except Exception as e:
    quiet = False
finally:
    cc.fetch = REAL_FETCH
results.append(ok(quiet and sha(PLAIN_SB[2]) == GOLDEN["2"],
                  "picks.build and build_variant without the check never reach the image service (a fetch would "
                  "have raised), and the payloads are the golden ones"))
with open(os.path.join(ROOT, "fxtracker", "cover_check.py"), encoding="utf-8") as f:
    SRC = f.read()
mods = set()
for node in ast.walk(ast.parse(SRC)):
    if isinstance(node, ast.Import):
        mods.update(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom):
        mods.add("." * node.level + (node.module or "") + ":" + ",".join(a.name for a in node.names))
with open(os.path.join(ROOT, ".github", "workflows", "monthly-check.yml"), encoding="utf-8") as f:
    WF = f.read()
step = WF[WF.index("- name: Monthly graded travel digest"):]
step = step[:step.index("\n\n")]
results.append(ok(mods == {"socket", "time", "urllib.error", "urllib.request", ".:rates"} and "environ" not in SRC
                  and "pip install" not in WF and "timeout-minutes" not in WF
                  and re.findall(r"^\s+([A-Z_]+): ", step, re.M) == ["BUTTONDOWN_API_KEY"]
                  and "run: python3 send_digest.py " in step,
                  "cover_check.py imports the standard library and fxtracker.rates only and reads no environment "
                  "variable; the workflow's digest step still installs nothing and sets only BUTTONDOWN_API_KEY"))

print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
sys.exit(0 if all(results) else 1)
