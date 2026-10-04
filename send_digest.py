#!/usr/bin/env python3
"""Monthly travel digest: score destinations the way the site does and email
the graded picks to the Buttondown newsletter list.

  python3 send_digest.py            # build + send to subscribers (needs BUTTONDOWN_API_KEY);
                                    # skips if this subject already went out in the last 25 days
  python3 send_digest.py --draft    # build + save as a Buttondown DRAFT (preview / test)
  python3 send_digest.py --dry-run  # build + print the email, send nothing
  python3 send_digest.py --month 8  # feature a specific month (1-12)
  python3 send_digest.py --dry-run --variant EUR,GBP --out DIR
                                    # preview home-currency editions; DIR/<CODE>.html to view

Home-currency editions (fxtracker/digest_variants.py): readers pick a
currency in the subscribe box or their account, stored as a Buttondown tag
(currency-eur, ...). Which editions exist is digest_variants.ROLLOUT, a
committed constant — the monthly workflow passes this script nothing else,
so turning one on is a reviewed commit, never a setting. With only USD
switched on (the default) this script does exactly what it always did: one
issue to the whole list. With more, it sends each edition to its tag's
readers first, then the USD edition to everyone holding none of the tags of
an edition that went out — so each reader gets one issue, and a currency
that fails, is off, or has no readers falls back to USD. Re-running is safe:
editions already out are skipped.

  --variant CODES   comma list or "all". A send may only name "send"-stage
                    currencies, a --draft "send"/"draft" ones, a --dry-run any.
                    Default: send -> the "send" stage; --draft/--dry-run ->
                    "send" + "draft".
  --out DIR         with --dry-run only: also write DIR/<CODE>.html previews.

Arguments are strict: anything unknown, "--variant=EUR" (write a space), a
repeated flag, --month outside 1-12, or --out without --dry-run is a usage
error, never a send with the defaults. So is a bad digest_variants.ROLLOUT
entry (the site ignores one; this script refuses to run until it is fixed).

Exit codes: 0 every edition sent, already out, covered or skipped for having no
readers; 1 something failed (a re-run is safe); 2 usage error or a ROLLOUT
problem (nothing was built or sent). The owner's rollout steps are the
RUNBOOK in fxtracker/digest_variants.py.

Schedule monthly (GitHub Actions / cron). Distinct from check.py, which is the
currency-favorability alert to your personal inbox.
"""

import os
import sys
import traceback

from fxtracker import newsletter, picks
from fxtracker.digest_variants import (SEND_ORDER, VARIANTS, draft_codes, rollout_problems,
                                       send_codes, stage)


def run(dry_run=False, month=None, draft=False):
    data = picks.build(month=month)
    subject, body = newsletter.render_digest(data)

    print("Digest for {0} {1} (rates as of {2}): {3} picks, {4} gems.".format(
        data["month_name"], data["year"], data["as_of"],
        len(data["picks"]), len(data["gems"])))

    if dry_run:
        print("\n--- SUBJECT ---\n" + subject)
        print("\n--- BODY (markdown) ---\n" + body)
        print("\n--dry-run: nothing sent.")
        return 0

    if not newsletter.is_configured():
        print("BUTTONDOWN_API_KEY not set — cannot send. Use --dry-run to preview.")
        return 1
    try:
        outcome = newsletter.send(subject, body, draft=draft)
    except Exception as e:
        print("Buttondown send failed:", e)
        return 1
    if outcome == "draft":
        print("Created Buttondown draft. Open it in Buttondown to preview or send a test.")
    elif outcome == "already-sent":
        # A late cron after a manual send, or a re-run: the issue is out, so
        # this run has nothing to do and is not a failure.
        print("This month's digest already went out; nothing sent.")
    else:
        print("Sent digest to Buttondown subscribers.")
    return 0


# ---- home-currency editions -------------------------------------------------

def _ordered(codes):
    return tuple(c for c in SEND_ORDER if c in codes)


def select_codes(arg, dry_run=False, draft=False):
    """The editions this run handles, in SEND_ORDER, or raises ValueError
    (a usage error) when a code is unknown or not switched on for this mode."""
    allowed = tuple(SEND_ORDER) if dry_run else draft_codes() if draft else send_codes()
    if arg is None:
        return draft_codes() if (dry_run or draft) else send_codes()
    if arg.strip().lower() == "all":
        return allowed
    want = [c.strip().upper() for c in arg.split(",") if c.strip()]
    if not want:
        raise ValueError("--variant needs a currency list or 'all'")
    for c in want:
        if c not in VARIANTS:
            raise ValueError("unknown currency %s (digest_variants.VARIANTS has %s)"
                             % (c, ", ".join(SEND_ORDER)))
        if c not in allowed:
            raise ValueError("%s isn't switched on%s (digest_variants.ROLLOUT: %s)"
                             % (c, " for drafts" if draft else "", stage(c) or "off"))
    return _ordered(want)


def _flight_counts(data):
    rows = data["picks"] + data["gems"]
    return (sum(1 for s in rows if s.get("fly_basis") == "month"),
            sum(1 for s in rows if s.get("fly_basis") == "distance"))


def build_editions(codes, month=None):
    """Build and render USD plus every code in `codes`. USD is always built:
    it is every other edition's fallback, and its subject is how a re-run
    learns what already went out. Returns (editions, failed): editions maps
    code -> {"data", "subject", "body"}; failed maps code -> reason."""
    shared = picks.gather(month)             # raises: the run fails, as it always has
    eds, failed = {}, {}
    data = picks.build_variant(shared, VARIANTS["USD"])
    subject, body = newsletter.render_digest(data)
    eds["USD"] = {"data": data, "subject": subject, "body": body}
    for c in codes:
        if c == "USD":
            continue
        try:
            data = picks.build_variant(shared, VARIANTS[c])
            subject, body = newsletter.render_digest(data)
            eds[c] = {"data": data, "subject": subject, "body": body}
        except Exception as e:
            print("%s: render failed (%s: %s) — its readers get the USD issue"
                  % (c, type(e).__name__, e))
            failed[c] = "render failed: %s" % e
    subjects = [e["subject"] for e in eds.values()]
    if len(set(subjects)) != len(subjects):
        raise RuntimeError("two editions share a subject; the duplicate check would mix them up: %r"
                           % subjects)
    return eds, failed


def _summary(code, ed):
    d = ed["data"]
    nm, nd = _flight_counts(d)
    return ("[{0}] Digest for {1} {2} (rates as of {3}): {4} picks, {5} gems · flights: "
            "{6} month-based, {7} by distance".format(
                code, d["month_name"], d["year"], d["as_of"], len(d["picks"]), len(d["gems"]),
                nm, nd))


def _picks_table(d):
    lines = ["  #  ISO  Overall Afford  FX %    Flights"]
    rows = [("pick", s) for s in d["picks"]] + [("gem", s) for s in d["gems"]]
    for i, (kind, s) in enumerate(rows, 1):
        fx = "—" if s.get("fx") is None else "%+.2f" % s["fx"]
        fly = "—" if s.get("fly") is None else "%s (%s)" % (picks.grade(s["fly"]), s.get("fly_basis"))
        lines.append("  %-2d %-4s %-7s %-7s %-7s %s%s" % (
            i, s["iso"], picks.grade(s["value"]), picks.grade(s["afford"]), fx, fly,
            "   [gem]" if kind == "gem" else ""))
    return "\n".join(lines)


def _page(subject, body):
    import html
    return ("<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            "<title>%s</title></head><body style=\"margin:0;background:#f4f5f6\">\n%s\n"
            "</body></html>\n" % (html.escape(subject), body))


def _dry_run(codes, eds, failed, out=None):
    for c in codes:
        if c not in eds:
            continue
        v, ed = VARIANTS[c], eds[c]
        print("\n=== %s · home %s · fares from %s · advisories %s · tag %s ===" % (
            c, v.home_iso, v.home_iso, v.adv_source, v.tag))
        print(_picks_table(ed["data"]))
        print("\n--- SUBJECT ---\n" + ed["subject"])
        pre = ed["body"].split(">", 1)[1].split("&#847;", 1)[0]
        print("\n--- PREHEADER ---\n" + pre)
        if c == "USD":
            aud = ("everyone, minus readers holding the tag of an edition already out this "
                   "cycle; sent last" if len(codes) > 1 else "everyone (today's single issue)")
        else:
            aud = "has %s; lacks tags of issues already out this cycle; sent before USD" % v.tag
        print("\n--- AUDIENCE ---\n" + aud)
        print("\n--- BODY ---\n" + ed["body"])
        if out:
            os.makedirs(out, exist_ok=True)
            path = os.path.join(out, c + ".html")
            with open(path, "w", encoding="utf-8") as f:
                f.write(_page(ed["subject"], ed["body"]))
            print("\n(wrote %s)" % path)
    print("\n--dry-run: nothing sent.%s" % (
        "" if not failed else " FAILED: " + "; ".join("%s %s" % kv for kv in failed.items())))
    return 1 if failed else 0


def _excluded_by(rec, tag_ids):
    """Codes whose readers the USD issue `rec` left out.

    A variant-mode USD send records them in its metadata (wg_excluded, a
    comma list of codes): that is our own data, so it comes back in the list
    response whatever Buttondown does with `filters`. Nothing here shows that
    the email list returns `filters` at all, and when it didn't, a re-run
    after "USD went out excluding GBP, whose own outcome was unknown" read
    "no exclusions", called GBP covered, exited 0, and GBP's readers got no
    issue. The filters are the fallback for a record without the metadata.
    A record with neither (today's single issue, sent to the whole list)
    excluded nobody: every edition is covered by it."""
    md = rec.get("metadata")
    if isinstance(md, dict) and isinstance(md.get("wg_excluded"), str):
        return {c.strip() for c in md["wg_excluded"].split(",")
                if c.strip() in VARIANTS and c.strip() != "USD"}
    f = rec.get("filters")
    rows = (f.get("filters") or []) if isinstance(f, dict) else []
    vals = {str(x.get("value")) for x in rows
            if isinstance(x, dict) and x.get("operator") == "not_contains"}
    if not vals:
        return set()
    if tag_ids is None:
        return set(VARIANTS) - {"USD"}
    return {c for c, ids in tag_ids.items() if any(str(i) in vals for i in ids)}


def _find(subject, code, hdr):
    """find_sent for one edition in variant mode. partially_sent counts as
    out here: Buttondown documents it (a paused send that then went to part
    of the list), and missing it would send that edition again to readers
    who already had it. The USD-only path keeps today's exact status list."""
    return newsletter.find_sent(subject, headers=hdr, expected=code,
                                statuses=newsletter.VARIANT_OUT_STATUSES)


def _no_readers(c, tag_ids):
    """The log line for an edition whose tag exists but Buttondown counts no
    regular reader holding it. That is normal after a test subscriber left;
    it is also what a reader count that doesn't match tags by name looks
    like (newsletter.tag_readers passes the name; Buttondown's docs show a
    name but don't say), and then real readers silently get USD. Loud, so
    the owner's draft run (digest_variants RUNBOOK step 3) catches it."""
    print("%s: skipped — no readers. WARNING: the %s tag exists (id %s) but Buttondown "
          "counts 0 regular subscribers holding it; if anyone picked %s, the reader count "
          "isn't matching the tag and they get the USD issue instead."
          % (c, VARIANTS[c].tag, (tag_ids.get(c) or ["?"])[0], c))


def _send(codes, eds, failed, draft=False):
    """The draft/send half of variant mode. Returns the exit code."""
    hdr = newsletter.VERSION_HDR
    usd = eds["USD"]
    others = [c for c in SEND_ORDER if c != "USD" and c in codes]
    subjects = {c: newsletter.digest_subject(VARIANTS[c], usd["data"]["month_name"]) for c in others}
    usd_error = False

    tag_ids = None
    if others:
        try:
            tag_ids = newsletter.currency_tags(hdr)
        except Exception as e:
            print("Buttondown tags unreadable (%s): every non-USD edition is skipped" % e)

    if draft:
        drafted = set()
        for c in others:
            if c in failed:
                continue
            if tag_ids is None:
                failed[c] = "skipped: tags unreadable"
                continue
            ids = tag_ids.get(c) or []
            if len(ids) > 1:
                failed[c] = "two Buttondown tags match %s; fix in Buttondown" % VARIANTS[c].tag
                print("%s: %s" % (c, failed[c]))
                continue
            if not ids:
                print("%s: skipped — no readers (no %s tag yet)" % (c, VARIANTS[c].tag))
                continue
            try:
                n = newsletter.tag_readers(VARIANTS[c].tag, hdr)
                if n == 0:
                    _no_readers(c, tag_ids)
                    continue
                eid = newsletter.send_variant(eds[c]["subject"], eds[c]["body"],
                                              newsletter.audience(c, tag_ids, drafted), draft=True,
                                              metadata={"wg_variant": c}, archival_mode="disabled",
                                              headers=hdr)
                drafted.add(c)
                print("%s: draft %s for %s (%s readers)" % (
                    c, eid, newsletter.describe_audience(c, drafted - {c}),
                    "?" if n is None else n))
            except Exception as e:
                failed[c] = str(e)
                print("%s: draft failed — %s" % (c, e))
        try:
            if "USD" not in codes:
                pass
            elif not drafted:
                newsletter.send(usd["subject"], usd["body"], draft=True)
                print("USD: draft created (everyone; today's single-issue draft)")
            else:
                # The same metadata as a real variant-mode USD send, so a
                # draft the owner sends by hand from the dashboard still
                # tells a later run whom it left out.
                eid = newsletter.send_variant(usd["subject"], usd["body"],
                                              newsletter.audience("USD", tag_ids, drafted),
                                              draft=True, headers=hdr,
                                              metadata={"wg_variant": "USD", "wg_excluded": ",".join(
                                                  c for c in SEND_ORDER if c in drafted)})
                print("USD: draft %s for %s" % (eid, newsletter.describe_audience("USD", drafted)))
        except Exception as e:
            usd_error = True
            print("USD: draft failed — %s" % e)
        print("Drafts only: nothing was published.")
        return 1 if (failed or usd_error) else 0

    try:
        usd_rec = _find(usd["subject"], "USD", hdr)
    except Exception as e:
        # Fails closed, as the single-issue send always has.
        print("Couldn't ask Buttondown what already went out (%s); nothing sent." % e)
        return 1
    covered = (set(others) - _excluded_by(usd_rec, tag_ids)) if usd_rec else set()

    delivered, unknown = set(), set()
    for c in others:
        v = VARIANTS[c]
        if c in covered:
            print("%s: covered by the USD issue already out (%s)" % (c, usd_rec.get("id") or "?"))
            continue
        try:
            rec = _find(subjects[c], c, hdr)
        except Exception as e:
            # Can't tell whether it went: keep its readers out of USD (nobody
            # gets two); the red run and a re-run sort it out.
            unknown.add(c)
            failed[c] = "couldn't check whether it already went out: %s" % e
            print("%s: %s" % (c, failed[c]))
            continue
        if rec:
            delivered.add(c)
            print("%s: already out (%s)" % (c, rec.get("id") or "?"))
            continue
        if c in failed:                       # render failed: its readers get USD
            continue
        if tag_ids is None:
            failed[c] = "skipped: tags unreadable"
            continue
        ids = tag_ids.get(c) or []
        if len(ids) > 1:
            failed[c] = "two Buttondown tags match %s; its readers get USD — fix in Buttondown" % v.tag
            print("%s: %s" % (c, failed[c]))
            continue
        if not ids:
            print("%s: skipped — no readers (no %s tag yet)" % (c, v.tag))
            continue
        try:
            n = newsletter.tag_readers(v.tag, hdr)
        except Exception as e:
            failed[c] = "reader count failed: %s" % e
            print("%s: %s — its readers get the USD issue" % (c, failed[c]))
            continue
        if n == 0:
            _no_readers(c, tag_ids)
            continue
        aud = newsletter.audience(c, tag_ids, delivered | unknown)
        try:
            eid = newsletter.send_variant(subjects[c], eds[c]["body"], aud,
                                          metadata={"wg_variant": c}, archival_mode="disabled",
                                          headers=hdr)
            delivered.add(c)
            print("%s: sent to %s (%s readers), id %s" % (
                c, newsletter.describe_audience(c, delivered | unknown), "?" if n is None else n, eid))
        except Exception as e:
            if not getattr(e, "at_publish", False):
                failed[c] = str(e)
                print("%s: not sent (%s) — its readers get the USD issue" % (c, e))
                continue
            # The publish call itself erred (a timeout, say): it may have gone.
            try:
                went = _find(subjects[c], c, hdr)
            except Exception as e2:
                unknown.add(c)
                failed[c] = "publish failed (%s); re-check failed (%s)" % (e, e2)
                print("%s: %s — its readers are held out of USD until a re-run" % (c, failed[c]))
                continue
            if went:
                delivered.add(c)
                print("%s: publish reported an error (%s), but the issue is out, id %s"
                      % (c, e, went.get("id") or "?"))
            else:
                failed[c] = "publish failed: %s" % e
                print("%s: %s — its readers get the USD issue" % (c, failed[c]))

    if "USD" in codes:
        ex = delivered | unknown
        if usd_rec:
            print("USD: already out (%s)" % (usd_rec.get("id") or "?"))
        elif not ex:
            try:
                outcome = newsletter.send(usd["subject"], usd["body"])   # exactly today's call
                print("USD: %s" % ("already out" if outcome == "already-sent"
                                   else "sent to everyone"))
            except Exception as e:
                usd_error = True
                print("USD: Buttondown send failed: %s" % e)
        else:
            try:
                if tag_ids is None:
                    raise RuntimeError("can't exclude %s without the tag ids" % ", ".join(sorted(ex)))
                left_out = ",".join(c for c in SEND_ORDER if c in ex)
                # wg_excluded: who this USD issue left out, in our own
                # metadata, so a re-run knows which editions it did NOT
                # cover even if the list response omits `filters`
                # (_excluded_by). Variant mode only: a USD issue to everyone
                # is still today's legacy call above.
                eid = newsletter.send_variant(usd["subject"], usd["body"],
                                              newsletter.audience("USD", tag_ids, ex), headers=hdr,
                                              metadata={"wg_variant": "USD", "wg_excluded": left_out})
                print("USD: sent (excluding %s), id %s" % (left_out.replace(",", ", "), eid))
            except Exception as e:
                usd_error = True
                print("USD: send failed: %s" % e)
    return 1 if (failed or usd_error) else 0


def run_variants(codes, dry_run=False, month=None, draft=False, out=None):
    try:
        eds, failed = build_editions(codes, month)
    except Exception as e:
        traceback.print_exc()
        print("Build failed before anything was sent: %s" % e)
        return 1
    for c in codes:
        if c in eds:
            print(_summary(c, eds[c]))
    if dry_run:
        return _dry_run(codes, eds, failed, out)
    if not newsletter.is_configured():
        print("BUTTONDOWN_API_KEY not set — cannot send. Use --dry-run to preview.")
        return 1
    return _send(codes, eds, failed, draft=draft)


def main(argv):
    # A typo in the owner's switch (fxtracker/digest_variants.ROLLOUT) is
    # ignored by the site, so it can't take the page down; here it stops the
    # run, red, before anything is built or sent, rather than quietly sending
    # fewer editions than the owner meant to.
    problems = rollout_problems()
    if problems:
        for p in problems:
            print(p)
        print("Fix digest_variants.ROLLOUT and re-run; nothing was sent.")
        return 2
    try:
        a = _parse_argv(argv)
    except UsageError as e:
        print(e)
        return 2
    try:
        codes = select_codes(a["variant"], dry_run=a["dry"], draft=a["draft"])
    except ValueError as e:
        print(e)
        return 2
    if codes == ("USD",) and a["out"] is None:
        # USD only: today's run, unchanged — same calls, same output.
        return run(dry_run=a["dry"], month=a["month"], draft=a["draft"])
    return run_variants(codes, dry_run=a["dry"], month=a["month"], draft=a["draft"], out=a["out"])


class UsageError(ValueError):
    pass


_FLAGS = ("--dry-run", "--draft")
_VALUED = ("--month", "--variant", "--out")


def _parse_argv(argv):
    """{"dry", "draft", "month", "variant", "out"}, or UsageError. Strict on
    purpose: `--variant=EUR` (with "=") used to be ignored, so a send meant
    for EUR alone went out with the default editions; `--out` without
    --dry-run was ignored on a real send. Anything unknown is an error now."""
    a = {"dry": False, "draft": False, "month": None, "variant": None, "out": None}
    seen = set()
    i = 0
    while i < len(argv):
        arg = argv[i]
        name = arg.split("=", 1)[0]
        if name in seen:
            raise UsageError("%s given twice" % name)
        if arg in _FLAGS:
            seen.add(arg)
            a["dry" if arg == "--dry-run" else "draft"] = True
            i += 1
            continue
        if arg in _VALUED:
            seen.add(arg)
            val = argv[i + 1] if i + 1 < len(argv) else None
            if arg == "--month":
                try:
                    a["month"] = int(val)
                except (TypeError, ValueError):
                    raise UsageError("--month needs a number 1-12")
                if not 1 <= a["month"] <= 12:
                    raise UsageError("--month needs a number 1-12")
            elif val is None or val.startswith("--"):
                raise UsageError("%s needs a value" % arg)
            else:
                a[arg[2:]] = val
            i += 2
            continue
        if name in _VALUED:
            raise UsageError("write %s %s (a space, not \"=\")" % (name, arg.split("=", 1)[1]))
        raise UsageError("unknown argument %r (see the top of send_digest.py)" % arg)
    if a["out"] is not None and not a["dry"]:
        raise UsageError("--out only writes preview pages: use it with --dry-run")
    return a


def _parse_args(argv):
    """(dry_run, month, draft), exiting 2 on a usage error. Kept for callers
    of the old interface; main() is the entry point."""
    try:
        a = _parse_argv(argv)
    except UsageError as e:
        print(e)
        sys.exit(2)
    return a["dry"], a["month"], a["draft"]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
