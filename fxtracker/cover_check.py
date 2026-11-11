"""The send-time photo check. Before an issue goes out, send_digest.py asks
the image service for each cover at the exact address the email will use,
and passes over a photo that definitely does not load for the country's next
approved one.

Why: the October 2026 issue went out with a broken Vietnam photo. The image
service (images.weserv.nl, picks._banner) answered 404 for that cover,
nothing looked, and a sent email can't be recalled.

Only a send asks for it: send_digest.py hands a CoverCheck to picks.build /
picks.build_variant for a real send, a --draft and a --dry-run. No other
caller does, so the tests, the snapshots and the golden hashes make no
request and read as they always did.

One address gets one of three answers (verdict):

  LOADS    HTTP 200 with an image content type and a body that is not empty.
  BROKEN   the image service's own answer that this is not an image: HTTP
           4xx (a 404 above all) other than the three below, or a 200 with
           another content type or an empty body.
  UNKNOWN  everything else: a timeout, no connection, HTTP 5xx, and the
           three 4xx that are about the asker and not the photo (403
           refused, 408 timed out, 429 slow down: NOT_ABOUT_THE_PHOTO).

Only BROKEN twice in a row (one more look, after a short pause) drops a
photo. UNKNOWN keeps it: an image service that does not answer, or that
itself answers 5xx, 403, 408 or 429, never strips the pictures from an
email. A dropped photo's place is taken by the country's next approved photo
(picks.cover_for: the same site checks, then this one), with that photo's
credit. When none is left the card goes out without a photo and without a
credit, which newsletter.py already handles.

What a 404 does and does not prove. A 404 counts as BROKEN whatever is
behind it, and the image service also answers 404 when the trouble is
upstream of it: October's broken cover was a 404 that stood for Wikimedia
refusing the service's own fetch with a 429 (picks._banner's note). The
check reads the status only, never the error's text, and that refusal
lasted for weeks, so a passing upstream refusal and a lasting one look the
same here. So "a down image service keeps every photo" holds for a service
that does not answer or answers 5xx, 403, 408 or 429 itself. It does not
hold on a day when the service answers but cannot fetch from Wikimedia: then
every first-choice photo can be passed over in one run (each for the
country's next approved photo, or for none), where before this check the
addresses went out as they were and could have loaded later. The email is
still complete and right, without those pictures.

The second look comes RETRY_PAUSE later, at the same address. It guards
against a glitch in one answer. It is not known to be a fresh fetch
upstream: the image service answers through Cloudflare, the one 404 on
record came back "cf-cache-status: MISS" with no Cache-Control, and nobody
has asked the same address twice to see whether the second answer is the
edge's stored copy of the first. Not measured.

The check can never stop a send. Whatever goes wrong inside it is caught and
the photo is kept, with one line in the log. TIMEOUT is urllib's socket
timeout: each network wait of a request (connecting, the handshake, each
read) is cut off after TIMEOUT seconds, which is not a limit on the request
as a whole, so a connection that stalls in stages can take several times
that. A run has BUDGET seconds from its first request: once they are spent
no new request starts, the photos not yet asked for go out unchecked, and
one line says so. A request that started inside the budget is left to
finish, and a wait near the end is cut to the time left (1 second at
least). So a run's requests end about a minute after the first one, a
little more when the last one waits its full time, and more than that only
if a connection stalls in stages. picks' own lookups for a replacement photo
(picks.cover, after a BROKEN) have their own 15 second timeouts and are
outside the budget. None of this can cut a send short: the workflow sets no
time limit on the job. An address is asked once a run, however many editions
share it.

Which address: the top card shows the 1024x420 banner (a cover's "url"),
every other card the 220x168 small copy ("thumb"), as newsletter._hero_card
and _compact_card read them. A country that leads one edition and not
another is asked for at both sizes. scripts/test_cover_check.py holds the
addresses asked to the <img> addresses in the email.

What the service answers, measured on 2026-11-10 with this module's UA: the
five covers of the Nov 1 issue were each 200 image/jpeg (0.1 to 0.2 s, from
its cache); a made-up file was 404 application/json,
{"status":"error","code":404,"message":"The requested URL returned error: 404"}
(0.6 s), the answer October's Vietnam cover got.

Standard library only: the monthly workflow installs nothing.
"""

import socket
import time
import urllib.error
import urllib.request

from . import rates

LOADS, BROKEN, UNKNOWN = "loads", "broken", "unknown"

TIMEOUT = 8        # seconds each network wait of a request may take (the socket timeout)
BUDGET = 60        # seconds from a run's first request in which a new request may start
RETRY_PAUSE = 1    # seconds between a BROKEN answer and the second look, at the same address
# Generic on purpose: it names no site and carries no address. It is the
# agent the answers measured above were given to (the service answers
# through Cloudflare; urllib's own "Python-urllib/3.x" was not tried).
UA = "Mozilla/5.0 (compatible; cover-check/1.0)"
# 4xx that say something about who is asking, or how often, and nothing about
# the photo. A mail app fetching the same address may well get the image, so
# these keep the photo, as a 5xx does.
NOT_ABOUT_THE_PHOTO = (403, 408, 429)


def fetch(url, timeout=TIMEOUT):
    """One GET of `url`: (HTTP status, content type, the body's first byte).
    An HTTP error status is an answer, returned like any other; whatever
    else urlopen raises (a timeout, no connection) is raised. Looked up on
    the module at call time, so a test swaps a fake in here and nothing in
    a test touches the network."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=rates._SSL) as r:
            return r.status, r.headers.get("Content-Type") or "", r.read(1)
    except urllib.error.HTTPError as e:
        return e.code, "", b""


def verdict(status, ctype, head):
    """(LOADS | BROKEN | UNKNOWN, why in a few plain words) for one answer."""
    if status == 200:
        if not ctype.lower().startswith("image/"):
            return BROKEN, "not an image: %s" % (ctype.split(";")[0].strip() or "no content type")
        if not head:
            return BROKEN, "an empty file"
        return LOADS, ""
    if 400 <= status < 500 and status not in NOT_ABOUT_THE_PHOTO:
        return BROKEN, "HTTP %d" % status
    return UNKNOWN, "HTTP %d" % status


def _why(e):
    """An exception in a few words for the log."""
    r = getattr(e, "reason", None) or e
    if isinstance(r, (socket.timeout, TimeoutError)) or "timed out" in str(r):
        return "timed out"
    return "%s: %s" % (type(e).__name__, r)


def _label(entry):
    """A cover candidate as the log names it: a page's title, or a pinned
    file's label (picks.cover_candidates)."""
    if isinstance(entry, dict):
        return entry.get("label") or entry.get("file") or "a pinned photo"
    return str(entry)


class CoverCheck(object):
    """One run's check: its answers (an address is asked once), its clock
    and its log lines, each of which starts "cover check:". `budget`,
    `clock`, `sleep` and `out` are there for the tests."""

    def __init__(self, budget=None, clock=time.monotonic, sleep=time.sleep, out=print):
        self.budget = BUDGET if budget is None else budget
        self._clock, self._sleep, self._out = clock, sleep, out
        self._seen = {}       # address -> (verdict, why)
        self._said = set()    # a line is printed once, however many editions meet it
        self._start = None    # the budget runs from the first request

    def _say(self, line):
        try:
            if line not in self._said:
                self._said.add(line)
                self._out("cover check: " + line)
        except Exception:
            pass              # a log line must not stop a send either

    def _get(self, url):
        """One request inside the budget, as (verdict, why). Never raises."""
        try:
            now = self._clock()
            if self._start is None:
                self._start = now
            left = self.budget - (now - self._start)
            if left <= 0:
                self._say("out of time after %d seconds, so the photos not yet checked go out as they are"
                          % self.budget)
                return UNKNOWN, ""
            return verdict(*fetch(url, max(1, min(TIMEOUT, left))))
        except Exception as e:
            return UNKNOWN, _why(e)

    def _ask(self, url):
        """(verdict, why) for one address, asked once a run. BROKEN only
        when two looks in a row say so (the second may be answered from
        the image service's edge cache: the module's note)."""
        if url not in self._seen:
            v, why = self._get(url)
            if v == BROKEN:
                self._sleep(RETRY_PAUSE)
                v2, why2 = self._get(url)
                if v2 == LOADS:
                    v, why = LOADS, "second try, first answer " + why
                elif v2 == UNKNOWN:
                    v, why = UNKNOWN, why2 and "%s, then %s" % (why, why2)
            self._seen[url] = (v, why)
        return self._seen[url]

    def choose(self, name, top, walk):
        """The cover for one card of the country `name`: the top card when
        `top`, else a compact one. `walk(loads)` is picks.cover_for, which
        asks `loads(candidate, cover)` about each approved photo in turn and
        takes the first it says True to. A photo is passed over only when
        its address for this card is BROKEN."""
        dropped, used = [], []

        def loads(entry, c):
            label = "a photo"
            try:
                label = _label(entry)
                v, why = self._ask(c["url"] if top else c.get("thumb") or c["url"])
                if v == BROKEN:
                    dropped.append("%s did not load (%s)" % (label, why))
                    return False
                if v == LOADS and why:
                    self._say("%s: %s loaded on the %s" % (name, label, why))
                elif v == UNKNOWN and why:
                    self._say("%s: could not check %s (%s), keeping it" % (name, label, why))
            except Exception as e:
                self._say("%s: the check of %s failed (%s), keeping it" % (name, label, _why(e)))
            used[:] = [label]
            return True

        c = walk(loads)
        try:
            if dropped:
                then = ("using " + used[0]) if (c and used) else (
                    "no other approved photo, so the card goes out without one")
                self._say("%s: %s, %s" % (name, ", ".join(dropped), then))
        except Exception:
            pass
        return c

    def report(self):
        """The run's summary, one line, once every edition is built. A photo
        asked for at two sizes counts twice."""
        try:
            got = [v for v, _why_ in self._seen.values()]
            n, loaded, broken = len(got), got.count(LOADS), got.count(BROKEN)
            if not n:
                self._say("no card has a photo to check")
            elif loaded == n:
                self._say("all %d photos loaded" % n if n > 1 else "the 1 photo loaded")
            else:
                self._say("%d of %d photos loaded, %d did not load, %d could not be checked"
                          % (loaded, n, broken, n - loaded - broken))
        except Exception as e:
            self._say("the summary failed (%s)" % _why(e))
