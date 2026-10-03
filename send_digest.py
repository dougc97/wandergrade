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

Exit codes: 0 every edition sent, already out, covered or skipped for having no
readers; 1 something failed (a re-run is safe); 2 usage error.

Schedule monthly (GitHub Actions / cron). Distinct from check.py, which is the
currency-favorability alert to your personal inbox.
"""

import os
import sys
import traceback

from fxtracker import newsletter, picks
from fxtracker.digest_variants import (SEND_ORDER, VARIANTS, draft_codes, send_codes,
                                       stage)


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
    """Codes whose tag the USD issue `rec` excluded (its not_contains filters).
    When the tag ids can't be read, any exclusion counts as all of them: each
    is then checked on its own instead of assumed covered."""
    f = rec.get("filters")
    rows = (f.get("filters") or []) if isinstance(f, dict) else []
    vals = {str(x.get("value")) for x in rows
            if isinstance(x, dict) and x.get("operator") == "not_contains"}
    if not vals:
        return set()
    if tag_ids is None:
        return set(VARIANTS) - {"USD"}
    return {c for c, ids in tag_ids.items() if any(str(i) in vals for i in ids)}


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
                    print("%s: skipped — no readers" % c)
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
                eid = newsletter.send_variant(usd["subject"], usd["body"],
                                              newsletter.audience("USD", tag_ids, drafted),
                                              draft=True, headers=hdr)
                print("USD: draft %s for %s" % (eid, newsletter.describe_audience("USD", drafted)))
        except Exception as e:
            usd_error = True
            print("USD: draft failed — %s" % e)
        print("Drafts only: nothing was published.")
        return 1 if (failed or usd_error) else 0

    try:
        usd_rec = newsletter.find_sent(usd["subject"], headers=hdr, expected="USD")
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
            rec = newsletter.find_sent(subjects[c], headers=hdr, expected=c)
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
            print("%s: skipped — no readers" % c)
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
                went = newsletter.find_sent(subjects[c], headers=hdr, expected=c)
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
                eid = newsletter.send_variant(usd["subject"], usd["body"],
                                              newsletter.audience("USD", tag_ids, ex), headers=hdr)
                print("USD: sent (excluding %s), id %s" % (", ".join(c for c in SEND_ORDER if c in ex),
                                                           eid))
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
    dry, month, draft = _parse_args(argv)
    variant = _opt(argv, "--variant")
    out = _opt(argv, "--out")
    try:
        codes = select_codes(variant, dry_run=dry, draft=draft)
    except ValueError as e:
        print(e)
        return 2
    if codes == ("USD",) and out is None:
        # USD only: today's run, unchanged — same calls, same output.
        return run(dry_run=dry, month=month, draft=draft)
    return run_variants(codes, dry_run=dry, month=month, draft=draft, out=out)


def _opt(argv, name):
    if name not in argv:
        return None
    i = argv.index(name)
    if i + 1 >= len(argv) or argv[i + 1].startswith("--"):
        print("%s needs a value" % name)
        sys.exit(2)
    return argv[i + 1]


def _parse_args(argv):
    dry = "--dry-run" in argv
    draft = "--draft" in argv
    month = None
    if "--month" in argv:
        try:
            month = int(argv[argv.index("--month") + 1])
        except (ValueError, IndexError):
            print("--month needs a number 1-12")
            sys.exit(2)
    return dry, month, draft


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
