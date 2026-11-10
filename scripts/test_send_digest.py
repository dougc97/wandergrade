#!/usr/bin/env python3
"""send_digest.py against a FAKE Buttondown: who gets which home-currency
edition, what a re-run does, and that this tree sends exactly as the code the
Dec 2026 redesign started from sends (digest_snapshot.BASE). Nothing leaves
this machine: the digest's inputs are digest_snapshot.py's frozen fixtures
(urlopen raises), and newsletter._call — the one function every Buttondown
request goes through — is replaced by FakeButtondown, which records each call
and keeps emails, tags and subscribers in memory. It echoes `filters` on
create (unless told to drop them, like an old API pin) and works out each
published email's recipients from them.

    /usr/bin/python3 scripts/test_send_digest.py [--against <rev>]

--against <rev> (default digest_snapshot.BASE) is the commit 1 compares with;
its code is extracted with `git archive` and run on this tree's data
(digest_snapshot.extract_code). 1 puts both trees through the same runs
against the same fake: USD-only (a send, a send for a named month, a draft, a
send whose issue is already out, a dry run) and with editions switched on (a
send to two currencies' readers, a send of all ten, a draft run, a dry run).
Every Buttondown call (method, URL with the duplicate check's ?subject=
needle and statuses, subject, status, audience filters, metadata, archival
mode, headers, order), every printed line and the exit code must be
identical once each email body, in a call or printed, is swapped for a token
naming the edition it was rendered for. The bodies themselves are not
compared with the base's (the redesign changes them): each body this tree
sends or prints must instead be exactly what digest_snapshot renders for
that edition and month, the text the golden hashes pin and
test_digest_variants reads back against its payload. Until the redesign 1
compared bodies with commit 4788fd2's, less a list of stripped pieces
(digest_snapshot's docstring). 22 checks that every edition's subject, every
month, is found by its own duplicate check (plain ASCII after the emoji).
"""
import contextlib, io, json, os, random, shutil, subprocess, sys, tempfile, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import digest_snapshot as ds  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c


class FakeButtondown:
    """Enough of Buttondown's API for send_digest: emails (list / create /
    publish), tags (list, paginated) and a subscriber count by tag."""

    V1 = "https://api.buttondown.email/v1"

    def __init__(self, subscribers=None, tag_names=(), drop_filters=False, publish_fail=None,
                 break_list_after_publish_fail=False, tag_page=3, emails=None, today="2026-10-03",
                 list_omits_filters=False, patch_fail=False, delete_fail=False, count_zero=()):
        self.calls, self.subs = [], dict(subscribers or {})
        # The email list's records lacking `filters` (nothing shows Buttondown
        # returns them); PATCH/DELETE of an email failing; tags whose reader
        # count comes back 0 although readers hold them.
        self.list_omits_filters = list_omits_filters
        self.patch_fail, self.delete_fail = patch_fail, delete_fail
        self.count_zero = set(count_zero)
        self.tags = [{"id": "tag%02d" % i, "name": n} for i, n in enumerate(tag_names)]
        self.emails = list(emails or [])
        self.drop_filters = drop_filters
        self.publish_fail = dict(publish_fail or {})     # edition -> "before" | "after"
        self.break_list = break_list_after_publish_fail
        self.broken = False
        self.tag_page = tag_page
        self.today = today

    # --- helpers -------------------------------------------------------------
    def edition(self, e):
        return ((e.get("metadata") or {}).get("wg_variant")) or "USD"

    def matches(self, sub, filters):
        if not filters or not filters.get("filters"):
            return True
        ids = {t["id"] for t in self.tags if t["name"] in sub["tags"]}
        res = []
        for f in filters["filters"]:
            assert f["field"] == "subscriber.tags", f
            assert f["operator"] in ("contains", "not_contains"), f
            res.append((f["value"] in ids) == (f["operator"] == "contains"))
        return all(res) if filters.get("predicate") == "and" else any(res)

    def received(self):
        """address -> [edition, ...] over every email that went out."""
        got = {}
        for e in self.emails:
            for a in e.get("recipients") or []:
                got.setdefault(a, []).append(self.edition(e))
        return got

    def creates(self):
        return [c for c in self.calls if c[0] == "POST" and c[1] == self.V1 + "/emails"]

    def publishes(self):
        return [c for c in self.calls if c[0] == "POST" and c[1].endswith("/publish")]

    # --- the API ---------------------------------------------------------------
    def call(self, method, url, payload=None, headers=None):
        self.calls.append([method, url, payload, headers])
        u = urllib.parse.urlsplit(url)
        q = urllib.parse.parse_qs(u.query)
        path = u.path.replace("/v1", "", 1)
        if method == "GET" and path == "/emails":
            if self.broken:
                raise RuntimeError("Buttondown 503: list unavailable")
            sts, needle = q.get("status", []), q.get("subject", [""])[0]
            start = q.get("creation_date__start", ["0000"])[0]
            keys = ("id", "subject", "status", "metadata", "creation_date") + (
                () if self.list_omits_filters else ("filters",))
            res = [{k: e.get(k) for k in keys}
                   for e in self.emails if e["status"] in sts and needle in e["subject"]
                   and e["creation_date"] >= start]
            return 200, {"results": res, "count": len(res)}
        if method == "PATCH" and path.startswith("/emails/"):
            if self.patch_fail:
                raise RuntimeError("Buttondown 500: update failed")
            e = next(x for x in self.emails if x["id"] == path.split("/")[2])
            e.update(payload)
            return 200, {k: v for k, v in e.items() if k != "body"}
        if method == "DELETE" and path.startswith("/emails/"):
            if self.delete_fail:
                raise RuntimeError("Buttondown 500: delete failed")
            self.emails = [x for x in self.emails if x["id"] != path.split("/")[2]]
            return 204, {}
        if method == "POST" and path == "/emails":
            eid = "em%03d" % (len(self.emails) + 1)
            e = {"id": eid, "subject": payload["subject"], "body": payload["body"],
                 "status": payload["status"], "creation_date": self.today,
                 "filters": None if self.drop_filters else payload.get("filters"),
                 "metadata": payload.get("metadata"), "archival_mode": payload.get("archival_mode")}
            self.emails.append(e)
            out = {k: v for k, v in e.items() if k != "body"}
            if self.drop_filters:
                out.pop("filters")
            return 201, out
        if method == "POST" and path.startswith("/emails/") and path.endswith("/publish"):
            eid = path.split("/")[2]
            e = next(x for x in self.emails if x["id"] == eid)
            mode = self.publish_fail.pop(self.edition(e), None)
            if mode == "before":
                if self.break_list:
                    self.broken = True
                raise RuntimeError("Buttondown publish timed out (not sent)")
            e["status"] = "sent"
            e["recipients"] = sorted(a for a, s in self.subs.items()
                                     if s["type"] == "regular" and self.matches(s, e["filters"]))
            if mode == "after":
                if self.break_list:
                    self.broken = True
                raise RuntimeError("Buttondown publish timed out (but it went)")
            return 200, {}
        if method == "GET" and path == "/tags":
            start = int(q.get("_o", ["0"])[0])
            chunk = self.tags[start:start + self.tag_page]
            nxt = (self.V1 + "/tags?page_size=1000&_o=%d" % (start + self.tag_page)
                   if start + self.tag_page < len(self.tags) else None)
            return 200, {"results": chunk, "next": nxt, "count": len(self.tags)}
        if method == "GET" and path == "/subscribers":
            name, typ = q["tag"][0], q.get("type", [""])[0]
            n = 0 if name in self.count_zero else sum(
                1 for s in self.subs.values() if name in s["tags"] and s["type"] == typ)
            return 200, {"results": [], "count": n}
        raise AssertionError("fake Buttondown: unexpected %s %s" % (method, url))


# What stands in for an email body when two trees' runs are compared.
TOKEN = "[[the %s edition's body]]"
NO_TOKEN = "[[a body render_digest never returned]]"


def tokenised(run):
    """A run (_child's dict) with each email body, in a call's payload or in
    the printed output, swapped for TOKEN naming the edition render_digest
    built it for; a call's body that no render returned gets NO_TOKEN. What
    is left is everything about the run but the bodies' own text."""
    token = {}
    for code, _month, _subject, body in run["renders"]:
        token[body] = TOKEN % code
    calls = []
    for c in run["calls"]:
        p = c[2]
        if isinstance(p, dict) and "body" in p:
            p = dict(p, body=token.get(p["body"], NO_TOKEN))
        calls.append([c[0], c[1], p] + list(c[3:]))
    out = run["out"]
    for body, tok in token.items():
        out = out.replace(body, tok)
    return {"code": run["code"], "calls": calls, "out": out}


def edition_of(call):
    """The edition a create call's email is: its wg_variant metadata, or USD
    for the USD-only call, which carries none."""
    return ((call[2] or {}).get("metadata") or {}).get("wg_variant") or "USD"


# ---- running a tree against the fake -----------------------------------------

def _child(root, scenario):
    """Run one scenario in THIS process for the tree at `root`; return a dict."""
    picks, newsletter, dv = ds.install(root)
    newsletter.datetime = ds.DATETIME_SHIM
    os.environ["BUTTONDOWN_API_KEY"] = "test-key-not-real"
    import send_digest as sd
    assert os.path.realpath(sd.__file__).startswith(os.path.realpath(root))
    if scenario.get("rollout"):
        # The editions switched on for this run (the committed ROLLOUT is USD only).
        dv.ROLLOUT.clear()
        dv.ROLLOUT.update(scenario["rollout"])
    # Every body render_digest hands send_digest, with the edition and month
    # it was built for: tokenised() swaps these, and main() holds each to
    # digest_snapshot's own render.
    renders, render = [], newsletter.render_digest

    def render_digest(data):
        subject, body = render(data)
        renders.append([data.get("variant", "USD"), data["month"], subject, body])
        return subject, body
    newsletter.render_digest = render_digest
    fake = FakeButtondown(**scenario.get("fake", {}))
    newsletter._call = fake.call
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = sd.main(scenario["argv"])
    return {"code": code, "out": buf.getvalue(), "calls": fake.calls, "renders": renders}


def run_tree(root, scenario):
    """The scenario in a fresh interpreter (module state can't leak between trees)."""
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--child", root],
                       input=json.dumps(scenario), capture_output=True, text=True, timeout=55)
    if p.returncode != 0:
        raise RuntimeError("child failed:\n" + p.stdout[-2000:] + p.stderr[-3000:])
    return json.loads(p.stdout.strip().splitlines()[-1])


class Harness:
    """The working tree, imported once, with ROLLOUT / build hooks per case."""

    def __init__(self):
        self.picks, self.newsletter, self.dv = ds.install(ROOT)
        self.newsletter.datetime = ds.DATETIME_SHIM
        os.environ["BUTTONDOWN_API_KEY"] = "test-key-not-real"
        import send_digest
        self.sd = send_digest
        self._build_variant = self.picks.build_variant
        self._variants = dict(self.dv.VARIANTS)

    def run(self, argv, fake, rollout=None, fail_render=(), variants=None):
        dv = self.dv
        saved = dict(dv.ROLLOUT)
        dv.ROLLOUT.clear()
        dv.ROLLOUT.update(rollout or {"USD": "send"})
        if variants:
            dv.VARIANTS.update(variants)
        bv = self._build_variant

        def build_variant(shared, v, *a, **k):
            if v.code in fail_render:
                raise RuntimeError("simulated %s render failure" % v.code)
            return bv(shared, v, *a, **k)
        self.picks.build_variant = build_variant
        self.newsletter._call = fake.call
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                code = self.sd.main(argv)
        finally:
            dv.ROLLOUT.clear()
            dv.ROLLOUT.update(saved)
            dv.VARIANTS.update(self._variants)
            self.picks.build_variant = bv
        return code, buf.getvalue()


ALL_SEND = {c: "send" for c in ("USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CNY", "INR", "KRW", "CHF")}


def subs(spec):
    """{'a@x': 'currency-eur,currency-gbp', 'b@x': '', 'c@x': ('unsubscribed', 'currency-eur')}"""
    out = {}
    for a, t in spec.items():
        typ, tags = t if isinstance(t, tuple) else ("regular", t)
        out[a] = {"type": typ, "tags": [x for x in tags.split(",") if x]}
    return out


def filt(call):
    return (call[2] or {}).get("filters")


def is_usd(call):
    """A create of the USD edition: the legacy call (no metadata) or a
    variant-mode one (wg_variant USD, with wg_excluded)."""
    return ((call[2] or {}).get("metadata") or {}).get("wg_variant") in (None, "USD")


def ops(calls):
    """The filter operators of the first call in `calls` ([] when none)."""
    return [x.get("operator") for x in ((filt(calls[0]) or {}).get("filters") or [])] if calls else []


def main():
    against = ds.BASE
    if "--against" in sys.argv:
        against = sys.argv[sys.argv.index("--against") + 1]
    results = []
    tmp = tempfile.mkdtemp(prefix="digest-base-")
    try:
        try:
            ds.extract_code(ROOT, against, tmp)
        except RuntimeError as e:
            print(e)
            return 1
        tags10 = ["currency-" + c.lower() for c in ALL_SEND] + ["cadence-monthly", "vip"]
        # What digest_snapshot renders on this tree for each edition, for the
        # two months the runs below feature (December by default on the
        # frozen 2026-10-03, and --month 3): every body sent or printed must
        # be one of these, exactly.
        rendered = ds.snapshot(ROOT, tuple(ALL_SEND), months=(12, 3))

        # 1. The same calls, output and exit code as the base's code, bodies
        #    apart, USD-only and with editions switched on.
        print("1. this tree's runs == %s's, call for call and line for line, each body swapped for a token"
              % against)
        base_subs = subs({"a@x.test": "", "b@x.test": "currency-eur", "c@x.test": "cadence-monthly"})
        sent_before = [{"id": "em900", "subject": "\U0001f9ed December trips: where your dollar goes furthest",
                        "status": "sent", "creation_date": "2026-10-01", "metadata": {},
                        "filters": {"predicate": "and", "groups": [], "filters": []}}]
        two = subs({"e1@x": "currency-eur", "e2@x": "currency-eur,vip", "g1@x": ("unsubscribed", "currency-gbp"),
                    "u1@x": "", "u2@x": "currency-usd"})
        every = subs(dict({"%s@x" % c.lower(): "currency-" + c.lower() for c in ALL_SEND}, **{"none@x": ""}))
        usd_only = []
        # (name, argv, the fake's set-up, ROLLOUT or None for the committed USD-only one, month,
        #  the editions whose emails are created, the editions whose bodies are printed)
        for name, argv, fake, rollout, month, created, printed in (
                ("send", [], {"subscribers": base_subs}, None, 12, ["USD"], []),
                ("send --month 3", ["--month", "3"], {"subscribers": base_subs}, None, 3, ["USD"], []),
                ("--draft", ["--draft"], {"subscribers": base_subs}, None, 12, ["USD"], []),
                ("already sent", [], {"subscribers": base_subs, "emails": sent_before}, None, 12, [], []),
                ("--dry-run", ["--dry-run"], {"subscribers": base_subs}, None, 12, [], ["USD"]),
                ("send, EUR and GBP switched on (EUR 2 readers, GBP none)", [],
                 {"subscribers": two, "tag_names": tags10}, {"USD": "send", "EUR": "send", "GBP": "send"}, 12,
                 ["EUR", "USD"], []),
                ("send --month 3, all ten switched on, a reader on each", ["--month", "3"],
                 {"subscribers": every, "tag_names": tags10}, dict(ALL_SEND), 3,
                 ["EUR", "GBP", "CAD", "AUD", "JPY", "CNY", "INR", "KRW", "CHF", "USD"], []),
                ("--draft, EUR at draft and JPY at send", ["--draft"],
                 {"subscribers": subs({"e@x": "currency-eur", "j@x": "currency-jpy", "u@x": ""}),
                  "tag_names": tags10}, {"USD": "send", "EUR": "draft", "JPY": "send"}, 12, ["EUR", "JPY", "USD"], []),
                ("--dry-run --variant EUR,JPY", ["--dry-run", "--variant", "EUR,JPY"],
                 {"subscribers": base_subs, "tag_names": tags10}, None, 12, [], ["EUR", "JPY"])):
            sc = {"argv": argv, "fake": fake}
            if rollout:
                sc["rollout"] = rollout
            new, old = run_tree(ROOT, sc), run_tree(tmp, sc)
            if rollout is None and "--variant" not in argv:
                usd_only.append(new)
            new_t, old_t = tokenised(new), tokenised(old)
            if len(created) == 10:
                ten, ten_old = new, old_t
            creates = [c for c in new["calls"] if c[0] == "POST" and c[1].endswith("/emails")]
            # Each body is digest_snapshot's render for its edition and month:
            # the ones render_digest returned, the ones sent, the ones printed.
            mine = lambda code: rendered[code][str(month)]
            exact = (all(r[1] == month and r[2:] == mine(r[0]) for r in new["renders"])
                     and [edition_of(c) for c in creates] == created
                     and all([c[2]["subject"], c[2]["body"]] == mine(edition_of(c)) for c in creates)
                     and all(new["out"].count("\n" + mine(code)[1] + "\n") == 1 for code in printed)
                     and new_t["out"].count("edition's body]]") == len(printed)
                     and NO_TOKEN not in json.dumps(new_t["calls"]))
            # 'already sent' must be the duplicate check finding this tree's
            # own subject: one list call, nothing created.
            deduped = name != "already sent" or (
                [c[0] for c in new["calls"]] == ["GET"] and "already went out; nothing sent" in new["out"]
                and urllib.parse.parse_qs(urllib.parse.urlsplit(new["calls"][0][1]).query)["subject"]
                == ["December trips: where your dollar goes furthest"])
            same = new_t == old_t
            n_bodies = len(creates) + len(printed)
            results.append(ok(same and exact and deduped and (new["calls"] or printed),
                              "%s: %d identical call%s, identical output (%d lines), exit %s; %s"
                              % (name, len(new["calls"]), "" if len(new["calls"]) == 1 else "s",
                                 len(new_t["out"].splitlines()), new["code"],
                                 "found its own subject, nothing created" if name == "already sent" else
                                 "the %d %s %s digest_snapshot's render%s, exactly"
                                 % (n_bodies, ("body" if n_bodies == 1 else "bodies") + (" printed" if printed else " in the calls"),
                                    "is" if n_bodies == 1 else "are", "" if n_bodies == 1 else "s"))))
            if not same:
                for k in ("code", "out", "calls"):
                    if new_t[k] != old_t[k]:
                        print("    %s, this tree: %s" % (k, json.dumps(new_t[k])[:700]))
                        print("    %s, %s: %s" % (k, against, json.dumps(old_t[k])[:700]))
        # Controls, on the last run with several editions: the token
        # comparison must notice two editions' bodies changing places
        # between their calls, and a body that is no longer a render.
        swapped, edited = json.loads(json.dumps(ten)), json.loads(json.dumps(ten))
        cs = [c for c in swapped["calls"] if c[0] == "POST" and c[1].endswith("/emails")]
        cs[0][2]["body"], cs[1][2]["body"] = cs[1][2]["body"], cs[0][2]["body"]
        ce = [c for c in edited["calls"] if c[0] == "POST" and c[1].endswith("/emails")]
        ce[-1][2]["body"] += " "
        results.append(ok(len(cs) == 10 and tokenised(ten) == ten_old and tokenised(swapped) != ten_old
                          and tokenised(edited) != ten_old and NO_TOKEN in json.dumps(tokenised(edited)["calls"])
                          and NO_TOKEN not in json.dumps(tokenised(swapped)["calls"]),
                          "controls: with two editions' bodies swapped between their calls, or one body a character "
                          "longer, the all-ten run no longer matches %s's" % against))
        results.append(ok(len(usd_only) == 5 and all(not (c[3] or {}).get("X-API-Version") and "filters" not in (c[2] or {})
                                                     for r in usd_only for c in r["calls"]),
                          "USD-only sends no X-API-Version header and no filters (all five USD-only runs)"))

        H = Harness()

        # 2. EUR with readers, GBP with none: EUR goes to its tag first,
        #    GBP is skipped, USD excludes EUR.
        print("2. USD,EUR,GBP with EUR at 2 readers and GBP at 0")
        f = FakeButtondown(subs({"e1@x": "currency-eur", "e2@x": "currency-eur,vip",
                                 "g1@x": ("unsubscribed", "currency-gbp"), "u1@x": "",
                                 "u2@x": "currency-usd"}), tags10)
        code, out = H.run([], f, {"USD": "send", "EUR": "send", "GBP": "send"})
        cr = f.creates()
        eur = [c for c in cr if (c[2].get("metadata") or {}).get("wg_variant") == "EUR"]
        usd = [c for c in cr if is_usd(c)]
        tid = {t["name"]: t["id"] for t in f.tags}
        results.append(ok(code == 0 and len(cr) == 2 and len(eur) == 1 and len(usd) == 1,
                          "exit 0, two issues created (EUR, USD) -> %s" % code))
        results.append(ok(eur and filt(eur[0]) == {"predicate": "and", "groups": [], "filters": [
            {"field": "subscriber.tags", "operator": "contains", "value": tid["currency-eur"]}]}
            and eur[0][2].get("archival_mode") == "disabled"
            and eur[0][3].get("X-API-Version") == H.newsletter.API_VERSION,
            "EUR: contains(currency-eur), archival disabled, wg_variant metadata, version header"))
        results.append(ok("GBP: skipped" in out and not any(
            (c[2].get("metadata") or {}).get("wg_variant") == "GBP" for c in cr), "GBP skipped: no readers"))
        results.append(ok(usd and filt(usd[0])["filters"] == [
            {"field": "subscriber.tags", "operator": "not_contains", "value": tid["currency-eur"]}]
            and cr.index(eur[0]) < cr.index(usd[0]),
            "USD: not_contains(currency-eur), created after EUR"))
        got = f.received()
        results.append(ok(got == {"e1@x": ["EUR"], "e2@x": ["EUR"], "u1@x": ["USD"], "u2@x": ["USD"]},
                          "recipients: each reader exactly one issue -> %s" % got))
        state_after_2 = f

        # 3. No currency tags in Buttondown at all: USD is the exact legacy call.
        print("3. no currency tags exist")
        f = FakeButtondown(subs({"a@x": "", "b@x": "cadence-monthly"}), ["cadence-monthly"])
        code, out = H.run([], f, ALL_SEND)
        cr = f.creates()
        results.append(ok(code == 0 and len(cr) == 1 and set(cr[0][2]) == {"subject", "body", "status"}
                          and cr[0][3] is None and f.received() == {"a@x": ["USD"], "b@x": ["USD"]},
                          "one legacy create (no filters, no headers), everyone gets USD"))

        # 4. EUR fails to render: USD has no EUR exclusion, run exits 1.
        print("4. EUR render failure")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"}, fail_render=("EUR",))
        cr = f.creates()
        results.append(ok(code == 1 and len(cr) == 1 and "filters" not in cr[0][2]
                          and f.received() == {"e@x": ["USD"], "u@x": ["USD"]}
                          and "EUR: render failed" in out,
                          "EUR readers get USD (legacy call), exit 1"))

        # 5. EUR publish errors but it went: the re-check finds it, USD excludes EUR.
        print("5. EUR publish raises, re-check finds it out")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, publish_fail={"EUR": "after"})
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        usd = [c for c in f.creates() if is_usd(c)]
        results.append(ok(code == 0 and ops(usd) == ["not_contains"] and f.received() == {"e@x": ["EUR"], "u@x": ["USD"]},
                          "USD excludes EUR, each reader one issue, exit %s" % code))

        # 6. EUR publish errors and the re-check fails too: EUR is unknown,
        #    held out of USD, exit 1; a later re-run delivers it.
        print("6. EUR publish raises, re-check fails")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, publish_fail={"EUR": "before"},
                           break_list_after_publish_fail=True)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        usd = [c for c in f.creates() if is_usd(c)]
        results.append(ok(code == 1 and ops(usd) == ["not_contains"]
                          and f.received() == {"u@x": ["USD"]},
                          "EUR unknown: excluded from USD (nobody gets two), exit 1"))
        f.broken = False
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 0 and f.received() == {"e@x": ["EUR"], "u@x": ["USD"]},
                          "the re-run sends EUR to the readers held out"))

        # 7. Buttondown drops `filters` (old pin / plan without segmentation):
        #    EUR is never published, USD goes as the legacy call, exit 1.
        print("7. filters dropped by Buttondown")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, drop_filters=True)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        pubs = f.publishes()
        results.append(ok(code == 1 and len(pubs) == 1 and f.received() == {"e@x": ["USD"], "u@x": ["USD"]}
                          and "filter dropped/changed" in out,
                          "EUR draft kept unpublished, USD legacy to everyone, exit 1"))

        # 8. Re-run after full success (case 2's state): no creates.
        print("8. re-run after full success")
        f = state_after_2
        n0 = len(f.creates())
        code, out = H.run([], f, {"USD": "send", "EUR": "send", "GBP": "send"})
        results.append(ok(code == 0 and len(f.creates()) == n0
                          and "EUR: already out" in out and "USD: already out" in out,
                          "nothing created, exit 0"))

        # 9. Re-run after a legacy USD send to everyone: all editions covered.
        print("9. re-run after a legacy USD send")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10)
        H.run([], f, {"USD": "send"})
        code, out = H.run([], f, ALL_SEND)
        results.append(ok(code == 0 and len(f.creates()) == 1 and out.count("covered by the USD issue") == 9,
                          "every edition 'covered', no creates"))

        # 10. Re-run where USD excluded EUR but EUR isn't out: EUR is sent.
        print("10. USD out excluding EUR, EUR not out")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10)
        eur_id = next(t["id"] for t in f.tags if t["name"] == "currency-eur")
        f.emails.append({"id": "em500", "subject": "\U0001f9ed December trips: where your dollar goes furthest",
                         "status": "sent", "creation_date": "2026-10-02", "metadata": None,
                         "filters": {"predicate": "and", "groups": [], "filters": [
                             {"field": "subscriber.tags", "operator": "not_contains", "value": eur_id}]},
                         "recipients": ["u@x"]})
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 0 and f.received() == {"u@x": ["USD"], "e@x": ["EUR"]},
                          "EUR goes out now; USD not resent"))

        # 11. Property: random readers, random tag sets (two-tag readers
        #     included), random failures. In every run nobody gets two; after
        #     a clean re-run everybody has exactly one.
        print("11. property test: 200 readers x 12 seeds")
        codes = list(ALL_SEND)
        bad = []
        for seed in range(12):
            rnd = random.Random(seed)
            sp = {}
            for i in range(200):
                k = rnd.choice([0, 0, 1, 1, 1, 2])
                t = rnd.sample(["currency-" + c.lower() for c in codes], k) + rnd.sample(["vip", "cadence-monthly"], rnd.randint(0, 1))
                sp["r%03d@x" % i] = (rnd.choice(["regular"] * 9 + ["unsubscribed"]), ",".join(t))
            on = {c: "send" for c in codes if c == "USD" or rnd.random() < 0.7}
            fails = {c: rnd.choice(["before", "after"]) for c in codes if c != "USD" and rnd.random() < 0.25}
            f = FakeButtondown(subs(sp), rnd.sample(tags10, len(tags10)), publish_fail=fails,
                               break_list_after_publish_fail=rnd.random() < 0.5)
            H.run([], f, on, fail_render=tuple(c for c in codes if c != "USD" and rnd.random() < 0.1))
            first = f.received()
            f.broken, f.publish_fail = False, {}
            H.run([], f, on)
            second = f.received()
            n_before = len(f.creates())
            H.run([], f, on)
            regular = {a for a, s in f.subs.items() if s["type"] == "regular"}
            for a in regular:
                if len(first.get(a, [])) > 1 or len(second.get(a, [])) != 1:
                    bad.append((seed, a, first.get(a), second.get(a), f.subs[a]["tags"]))
            if any(a not in regular for a in second) or len(f.creates()) != n_before:
                bad.append((seed, "unsubscribed reached or third run created", n_before))
        results.append(ok(not bad, "every regular reader gets exactly one issue; a third run adds none%s"
                          % ("" if not bad else " -> %r" % bad[:3])))

        # 12. Two tags for one currency (case differs): EUR fails closed.
        print("12. currency-eur and Currency-EUR both exist")
        f = FakeButtondown(subs({"e1@x": "currency-eur", "e2@x": "Currency-EUR", "u@x": ""}),
                           tags10 + ["Currency-EUR"])
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 1 and f.received() == {"e1@x": ["USD"], "e2@x": ["USD"], "u@x": ["USD"]}
                          and not any((c[2].get("metadata") or {}).get("wg_variant") for c in f.creates()),
                          "no EUR issue; its readers get USD; exit 1"))

        # 13. --variant must be switched on for a send; a dry run takes any.
        print("13. --variant gating")
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        code, out = H.run(["--variant", "EUR"], f)
        results.append(ok(code == 2 and f.calls == [] and "EUR isn't switched on" in out,
                          "send --variant EUR while off: exit 2, no calls"))
        code, out = H.run(["--draft", "--variant", "EUR"], f, {"USD": "send", "EUR": "draft"})
        results.append(ok(code == 0 and all(c[0] != "POST" or not c[1].endswith("publish") for c in f.calls),
                          "--draft --variant EUR at 'draft' stage works -> %s" % code))
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        d = tempfile.mkdtemp(prefix="digest-out-")
        code, out = H.run(["--dry-run", "--variant", "EUR,JPY", "--out", d], f)
        results.append(ok(code == 0 and f.calls == [] and "=== EUR · home DE" in out
                          and "--- AUDIENCE ---" in out and sorted(os.listdir(d)) == ["EUR.html", "JPY.html"],
                          "--dry-run --variant EUR,JPY --out: no calls, pages written"))
        shutil.rmtree(d, ignore_errors=True)
        code, out = H.run(["--variant", "XYZ", "--dry-run"], f)
        results.append(ok(code == 2 and "unknown currency XYZ" in out, "unknown code: exit 2"))

        # 14. Two editions with one subject: abort before any call.
        print("14. duplicate subject")
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        cad = H.dv.VARIANTS["CAD"]._replace(noun="euro")
        code, out = H.run([], f, {"USD": "send", "EUR": "send", "CAD": "send"}, variants={"CAD": cad})
        results.append(ok(code == 1 and f.calls == [] and "share a subject" in out,
                          "aborted, no Buttondown call"))

        # 15. --draft: drafts only; no publish. One read-only duplicate-check
        # GET (with partially_sent), so the owner's draft run proves the check
        # a real send starts with.
        print("15. --draft with editions")
        f = FakeButtondown(subs({"e@x": "currency-eur", "j@x": "currency-jpy", "u@x": ""}), tags10)
        code, out = H.run(["--draft"], f, {"USD": "send", "EUR": "draft", "JPY": "send"})
        lists = [c for c in f.calls if c[0] == "GET" and urllib.parse.urlsplit(c[1]).path.endswith("/emails")]
        usd = [c for c in f.creates() if is_usd(c)]
        results.append(ok(code == 0 and not f.publishes() and len(lists) == 1
                          and "partially_sent" in urllib.parse.parse_qs(urllib.parse.urlsplit(lists[0][1]).query).get("status", [])
                          and "duplicate check OK" in out and len(f.creates()) == 3
                          and ops(usd) == ["not_contains", "not_contains"]
                          and all(e["status"] == "draft" for e in f.emails),
                          "3 drafts (EUR, JPY, USD excluding both), no publish, one read-only duplicate check"))

        # 16. The USD issue records whom it left out (wg_excluded), and a
        #     re-run reads that even when the list response has no `filters`:
        #     Review 0's S13, where GBP's readers silently got nothing.
        print("16. USD out excluding GBP; the list response omits filters")
        f = FakeButtondown(subs({"g@x": "currency-gbp", "u@x": ""}), tags10,
                           publish_fail={"GBP": "before"}, break_list_after_publish_fail=True,
                           list_omits_filters=True)
        code, out = H.run([], f, {"USD": "send", "GBP": "send"})
        usd = [c for c in f.creates() if is_usd(c)]
        md = (usd[0][2].get("metadata") if usd else None) or {}
        results.append(ok(code == 1 and md == {"wg_variant": "USD", "wg_excluded": "GBP"}
                          and f.received() == {"u@x": ["USD"]},
                          "GBP unknown: USD sent excluding it, metadata %s" % md))
        f.broken = False
        code, out = H.run([], f, {"USD": "send", "GBP": "send"})
        results.append(ok(code == 0 and f.received() == {"u@x": ["USD"], "g@x": ["GBP"]}
                          and "covered by the USD issue" not in out,
                          "the re-run sends GBP (not 'covered'), USD not resent"))
        f = FakeButtondown(subs({"g@x": "currency-gbp", "u@x": ""}), tags10, list_omits_filters=True)
        H.run([], f, {"USD": "send"})
        code, out = H.run([], f, {"USD": "send", "GBP": "send"})
        results.append(ok(code == 0 and len(f.creates()) == 1 and "GBP: covered by the USD issue" in out,
                          "a legacy USD issue (no wg_ metadata) still covers every edition"))

        # 17. partially_sent counts as out in variant mode only.
        print("17. an edition partially_sent")
        eur_subj = "\U0001f9ed December trips: where your euro goes furthest"
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, emails=[
            {"id": "em700", "subject": eur_subj, "status": "partially_sent", "creation_date": "2026-10-02",
             "metadata": {"wg_variant": "EUR"}, "filters": None, "recipients": ["e@x"]}])
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        lists = [urllib.parse.parse_qs(urllib.parse.urlsplit(c[1]).query)["status"]
                 for c in f.calls if c[0] == "GET" and urllib.parse.urlsplit(c[1]).path.endswith("/emails")]
        results.append(ok(code == 0 and "EUR: already out (em700)" in out
                          and f.received() == {"e@x": ["EUR"], "u@x": ["USD"]}
                          and all("partially_sent" in st for st in lists) and lists,
                          "EUR found out (partially_sent), not re-sent; USD excludes it"))
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        H.run([], f)
        lists = [urllib.parse.parse_qs(urllib.parse.urlsplit(c[1]).query)["status"]
                 for c in f.calls if c[0] == "GET"]
        results.append(ok(lists and all("partially_sent" not in st for st in lists),
                          "the USD-only send's duplicate check keeps today's status list"))

        # 18. A draft whose audience filter Buttondown dropped is defused.
        print("18. dropped filter: the kept draft")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, drop_filters=True)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        eur_e = [e for e in f.emails if (e.get("metadata") or {}).get("wg_variant") == "EUR"]
        results.append(ok(code == 1 and len(eur_e) == 1 and eur_e[0]["status"] == "draft"
                          and eur_e[0]["subject"] == "[DO NOT SEND — audience dropped] " + eur_subj
                          and "renamed" in out,
                          "EUR draft renamed '[DO NOT SEND — audience dropped] …', never published"))
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, drop_filters=True,
                           patch_fail=True)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 1 and not any((e.get("metadata") or {}).get("wg_variant") == "EUR"
                                                for e in f.emails) and "deleted" in out,
                          "rename fails: the draft is deleted instead"))
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, drop_filters=True,
                           patch_fail=True, delete_fail=True)
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 1 and "DELETE IT IN BUTTONDOWN" in out,
                          "both fail: the log says to delete it by hand"))

        # 19. A tag that exists but counts 0 readers is skipped LOUDLY.
        print("19. tag exists, reader count 0")
        f = FakeButtondown(subs({"e@x": "currency-eur", "u@x": ""}), tags10, count_zero=("currency-eur",))
        code, out = H.run([], f, {"USD": "send", "EUR": "send"})
        results.append(ok(code == 0 and "EUR: skipped — no readers. WARNING: the currency-eur tag exists" in out
                          and f.received() == {"e@x": ["USD"], "u@x": ["USD"]},
                          "warning logged; its readers get USD"))
        code, out = H.run(["--draft"], FakeButtondown(subs({"e@x": "currency-eur"}), tags10,
                                                      count_zero=("currency-eur",)),
                          {"USD": "send", "EUR": "draft"})
        results.append(ok("WARNING: the currency-eur tag exists" in out, "the draft run warns too"))

        # 20. A ROLLOUT typo: the site ignores it, and so does the send —
        # the valid entries go out (USD always) and the run ends red, so
        # a typo never costs readers the month.
        print("20. ROLLOUT typo")
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        code, out = H.run([], f, {"USD": "send", "EUR": "Send"})
        results.append(ok(code == 1 and "the stage must be" in out and "valid ROLLOUT entries only" in out
                          and f.received() == {"u@x": ["USD"]},
                          "typo: USD still goes out, the run ends red (exit 1)"))

        # 21. Malformed arguments are usage errors, never a send with defaults.
        print("21. argument errors")
        bad = []
        for argv in (["--variant=EUR"], ["--out", "/tmp/x"], ["--foo"], ["--month", "13"],
                     ["--month"], ["--month", "x"], ["extra"], ["--dry-run", "--dry-run"],
                     ["--variant"], ["--variant", "--dry-run"]):
            f = FakeButtondown(subs({"u@x": ""}), tags10)
            code, out = H.run(argv, f, ALL_SEND)
            if code != 2 or f.calls:
                bad.append((argv, code, out[-80:]))
        results.append(ok(not bad, "10 malformed command lines: exit 2, no Buttondown call%s"
                          % ("" if not bad else " -> %r" % bad[:2])))
        f = FakeButtondown(subs({"u@x": ""}), tags10)
        code, out = H.run(["--month", "x"], f)
        results.append(ok(code == 2 and out.strip() == "--month needs a number 1-12",
                          "a bad --month says what it always said"))

        # 22. Every edition's subject, every month, is found by its own
        #     duplicate check. find_sent asks Buttondown for the subject with
        #     its non-ASCII taken out (a contains-match), then insists on the
        #     exact subject, so that needle must sit inside the real subject:
        #     a ’ or — in the middle ("Januarys", "now  where") would never be
        #     found, and every re-run would mail the list again.
        print("22. every subject is found by its own duplicate check")
        nl = H.newsletter
        missed = []
        # Each fake goes in here, outside H.run: put _call back after, so no
        # later case talks to this case's last fake (the trap) by mistake.
        saved_call = nl._call
        try:
            for v in H.dv.VARIANTS.values():
                for mn in H.picks.MONTHS:
                    subj = nl.digest_subject(v, mn)
                    needle = subj.encode("ascii", "ignore").decode("ascii").strip()
                    f = FakeButtondown(emails=[{"id": "em1", "subject": subj, "status": "sent",
                                                "creation_date": "2026-10-01", "metadata": None, "filters": None}])
                    nl._call = f.call
                    rec = nl.find_sent(subj)
                    asked = [urllib.parse.parse_qs(urllib.parse.urlsplit(c[1]).query)["subject"] for c in f.calls]
                    if not (needle and needle in subj and asked == [[needle]] and (rec or {}).get("id") == "em1"
                            and mn in needle and "your %s " % v.noun in needle):
                        missed.append((v.code, mn, subj, needle))
            # The trap this guards, as a control: a ’ inside is never found.
            trap = "\U0001f9ed January’s trips: where your dollar goes furthest"
            f = FakeButtondown(emails=[{"id": "em1", "subject": trap, "status": "sent",
                                        "creation_date": "2026-10-01", "metadata": None, "filters": None}])
            nl._call = f.call
            trap_found = nl.find_sent(trap)
        finally:
            nl._call = saved_call
        results.append(ok(not missed and trap_found is None,
                          "all %d editions x 12 months: the ASCII needle is inside the subject, names the month "
                          "and 'your <noun> ', and find_sent finds the issue (a subject with ’ inside is not "
                          "found: the trap)%s" % (len(H.dv.VARIANTS), "" if not missed else " -> %r" % missed[:3])))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        res = _child(sys.argv[2], json.loads(sys.stdin.read()))
        sys.stdout.write("\n" + json.dumps(res) + "\n")
        sys.exit(0)
    sys.exit(main())
