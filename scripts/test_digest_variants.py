#!/usr/bin/env python3
"""The digest's home-currency editions, rendered offline from frozen inputs
(scripts/digest_snapshot.py; nothing leaves this machine):

  1. The USD email's 12 months hash to scripts/digest_golden/usd_sha256.json,
     and the USD edition built the per-currency way (gather + build_variant)
     is the same text. Against the code the Dec 2026 redesign started from
     (digest_snapshot.BASE, run on this tree's data), every edition's
     payload, every month, is equal field for field but for
     digest_snapshot.ADDED_FIELDS, and its subject and hidden preheader are
     the same text: the redesign changes wording and layout, not which
     countries, grades, links or numbers go out. Every pick's cover and
     credit are the ones digest_snapshot.fake_rule_cover works out under the
     fakes (the cover rule, picks.cover_for; activities.json `photo` is an
     optional override), and with every cover lookup failing each email is
     its covered self less the covers and the credits block, nothing in
     their place. The cost line's band is checked against JavaScript's own
     toFixed under jsc (2c).
  2. Each of the ten editions, every month: its own subject, wording, footer,
     banknote, no home country in its picks, balanced markup, and FX measured
     in its own currency; the 2026-11 wording, each piece naming the month;
     the Dec 2026 first screen (one brand line, one paragraph, the top card).
  3. pricelevel.real_fx_pct's home-side guard (high inflation at home that
     can't be dated: no direction), with the US unaffected.
  6. Every email says what its payload says (scripts/digest_check.py): each
     visible line, link, image, Overall badge and photo credit, every
     edition and month, is the one worked out from the payload (the
     non-breaking spaces that hold a flag's gap, an icon to its letter and
     an arrow to its word included). So do payload shapes the frozen months
     don't have (four picks, one pick, no advisory source, no fare grade on
     some cards or on any, a credit with no photo, an estimated fare on the
     top card, a gem graded on another government's level), and the checks
     report each of a list of deliberate faults; a fault whose piece is not
     in the body is a FAIL line, not a crash.
  7. Buttondown, the sender, can't restyle it in either of its templates
     (digest_check.proofing): the intro is the only <p>, it and the heading
     have their own margin, every link's words sit in two spans with the
     colour on the inner one, nothing is under 12px but the hidden
     preheader, no #888 is left, no image has a side margin, every block of
     text has its own colour, font-size and line-height, and the brand line
     is there once, first in the panel.
  8. The Overall badge's colours are the site's (public/styles.css), the
     compact cards' small photo is the banner's photo at 220x168 (and a
     payload without one falls back to the banner), the side padding that
     gives a compact card's words their room on a 360px phone is held, and
     the facts the footer's grade key states are the scoring code's ("~"
     on every estimated fare and on no other among them).

    /usr/bin/python3 scripts/test_digest_variants.py [--against <rev>]

--against <rev> names the commit 1 compares with (default
digest_snapshot.BASE). Its code is extracted with `git archive`
(digest_snapshot.extract_code), so the repository must have that commit.

Until the redesign 1 proved the USD text was commit 4788fd2's less a list of
stripped pieces. digest_snapshot's docstring says what replaced that and
why; the golden file's note has the history.
"""
import copy, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import digest_check as dc  # noqa: E402
import digest_snapshot as ds  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
GOLDEN = os.path.join(HERE, "digest_golden", "usd_sha256.json")


JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def _snapshot_in_child(root, variants="USD"):
    """A tree's snapshot and its payloads, (snap, datas), from a fresh
    interpreter (module isolation). Both as JSON gives them back: months are
    the strings "1" to "12"."""
    out, dout = tempfile.mktemp(suffix=".json"), tempfile.mktemp(suffix=".json")
    p = subprocess.run([sys.executable, os.path.join(HERE, "digest_snapshot.py"), "--root", root,
                        "--out", out, "--variants", variants, "--data-out", dout],
                       capture_output=True, text=True, timeout=55)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)
    res = []
    for path in (out, dout):
        with open(path, encoding="utf-8") as f:
            res.append(json.load(f))
        os.unlink(path)
    return tuple(res)


def _payloads(datas):
    """{edition: {"1".."12": payload}} as JSON gives it back, less the fields
    this tree adds on purpose (digest_snapshot.ADDED_FIELDS)."""
    out = json.loads(json.dumps(datas))
    for per in out.values():
        for d in per.values():
            for s_ in d["picks"] + d["gems"]:
                for k in ds.ADDED_FIELDS:
                    s_.pop(k, None)
    return out


def _where(a, b, path=""):
    """Where two payloads first differ, for the failure line."""
    if type(a) is not type(b):
        return "%s: %r vs %r" % (path, a, b)
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if a.get(k, KeyError) != b.get(k, KeyError):
                return _where(a.get(k), b.get(k), "%s.%s" % (path, k)) if k in a and k in b else (
                    "%s.%s only in %s" % (path, k, "this tree" if k in a else "the base"))
    if isinstance(a, list):
        if len(a) != len(b):
            return "%s: %d vs %d items" % (path, len(a), len(b))
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                return _where(x, y, "%s[%d]" % (path, i))
    return "%s: %r vs %r" % (path, a, b)


def main():
    results = []
    base = sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv else ds.BASE

    print("1. USD golden hashes; the same picks, grades, links and numbers as %s" % base)
    usd_only, usd_data = _snapshot_in_child(ROOT, "USD")
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)["sha256"]
    mine = ds.digest_hashes(usd_only)["USD"]
    bad = [m for m in golden if golden[m] != mine.get(m)]
    results.append(ok(len(golden) == 12 and not bad,
                      "12 months match the golden hashes%s" % (" (differ: %s)" % bad if bad else "")))

    picks, newsletter, dv = ds.install(ROOT)
    snap, datas = ds.snapshot(ROOT, tuple(dv.PICKER_ORDER), keep_data=True)
    V = dv.VARIANTS
    results.append(ok(snap["USD"] == usd_only["USD"],
                      "the USD edition built per-currency (gather + build_variant) is the same text"))

    # What goes out is what went out before the redesign: the base's code on
    # this tree's data builds the same payload for every edition and month
    # (and for the USD-only entry point, picks.build), and renders the same
    # subject (the duplicate-send key) and the same hidden preheader (the
    # body's first line). The bodies are not compared: check() in 6 holds
    # each to its payload instead.
    tmp = tempfile.mkdtemp(prefix="digest-base-")
    try:
        ds.extract_code(ROOT, base, tmp)
        old_snap, old_data = _snapshot_in_child(tmp, "all")
        old_usd, old_usd_data = _snapshot_in_child(tmp, "USD")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    new_data = _payloads(datas)
    cells = [(c, str(m)) for c in V for m in range(1, 13)]
    diffs = [(c, m, _where(new_data[c][m], old_data.get(c, {}).get(m))) for c, m in cells
             if new_data[c][m] != old_data.get(c, {}).get(m)]
    diffs += [("USD via picks.build", m, _where(d, old_usd_data["USD"].get(m)))
              for m, d in _payloads(usd_data)["USD"].items() if d != old_usd_data["USD"].get(m)]
    claimed = [k for k in ds.ADDED_FIELDS
               if any(k in s_ for per in old_data.values() for d in per.values() for s_ in d["picks"] + d["gems"])]
    results.append(ok(not diffs and not claimed and sorted(old_data) == sorted(V) and len(usd_data["USD"]) == 12
                      and all(len(old_data[c]) == 12 for c in old_data),
                      "%s's code builds the same payload as this tree for all %d editions x 12 months and for "
                      "picks.build's 12 (countries, order, scores, levels, sources, prices, FX, fares, activities, "
                      "covers, credits, dates), fields added on purpose: %s%s"
                      % (base, len(V), ", ".join(ds.ADDED_FIELDS) or "none",
                         "" if not (diffs or claimed) else " -> %r %r" % (diffs[:3], claimed))))
    first = lambda body: body.split("\n", 1)[0]
    changed = [(c, m) for c, m in cells
               if snap[c][m][0] != old_snap[c][m][0] or first(snap[c][m][1]) != first(old_snap[c][m][1])
               or not first(snap[c][m][1]).startswith('<div style="display:none;')
               or not first(snap[c][m][1]).endswith("</div>")]
    changed += [("USD via picks.build", m) for m in usd_only["USD"] if usd_only["USD"][m][0] != old_usd["USD"][m][0]]
    results.append(ok(not changed, "the subject and the hidden preheader are %s's, byte for byte, in all %d renders%s"
                      % (base, len(cells), "" if not changed else " -> %r" % changed[:4])))

    # The cover rule, under the fakes: each pick's cover and credit in the
    # payload are the first of `photo` + the gallery's first six that
    # answers, in every edition and month; a gem has none. (6 checks each
    # card shows that cover, linked to its guide with the country's name as
    # alt text, and that the credits block carries that credit.)
    with open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8") as f:
        acts = json.load(f)
    wrong, n_cov, n_none = [], 0, 0
    for c in snap:
        for m in range(1, 13):
            for s_ in datas[c][m]["picks"]:
                want = ds.fake_rule_cover(acts.get(s_["iso"], {}))
                got = ({"url": s_["photo"], "thumb": s_["photo_thumb"], "credit": s_["photo_credit"]}
                       if s_.get("photo") else None)
                if got != want or (not want and (s_.get("photo_credit") or s_.get("photo_thumb"))):
                    wrong.append((c, m, s_["iso"], got, want))
                n_cov += bool(want)
                n_none += not want
            wrong += [(c, m, s_["iso"], "a gem with a cover") for s_ in datas[c][m]["gems"]
                      if s_.get("photo") or s_.get("photo_credit") or s_.get("photo_thumb")]
    results.append(ok(not wrong and n_cov > 0,
                      "every edition's covers, their small copies and credits, all 12 months, are the rule's "
                      "picks under the fakes (%d covers, %d picks the fakes give none)%s"
                      % (n_cov, n_none, "" if not wrong else " -> %r" % (wrong[:2],))))
    # No cover: the fakes give every frozen pick one, so the no-photo cards
    # are checked here, every lookup failing (Wikipedia or Commons down, a
    # 429) through the tree's own cover() and cover_file(): no pick has a
    # photo or a credit, and each edition's email, each month, is its covered
    # self less each cover (the link that held the photo, and the table cell
    # that held only that) and less the credits block, nothing left in their
    # place (digest_check.canon), and still says what its payload says.
    bare, bare_data = ds.snapshot(ROOT, tuple(dv.PICKER_ORDER), keep_data=True, offline_covers=True)
    off = []
    for c, m in cells:
        b, d = (bare.get(c) or {}).get(m), (bare_data.get(c) or {}).get(int(m))
        if (not b or b[0] != snap[c][m][0]
                or any(s_.get("photo") or s_.get("photo_credit") or s_.get("photo_thumb") for s_ in d["picks"])
                or dc.canon(b[1]) != dc.canon(snap[c][m][1], covers=False)
                # (a control: the covered render does differ wherever a pick has a cover)
                or (dc.canon(b[1]) == dc.canon(snap[c][m][1])) == any(s_.get("photo") for s_ in datas[c][int(m)]["picks"])
                or "images.example" in b[1] or "Wikimedia" in b[1]
                or dc.check(newsletter, picks, V[c], d, b[0], b[1]) or dc.proofing(b[1])):
            off.append((c, m))
    results.append(ok(not off and sorted(bare) == sorted(snap) and all(len(bare[c]) == 12 for c in bare),
                      "with every cover lookup failing, all %d renders are their covered selves less the covers "
                      "and the credits block, nothing in their place%s"
                      % (sum(len(v) for v in bare.values()), "" if not off else " -> %r" % off[:4])))

    # A grade's source is the list's own government, or the one that filled its gap.
    by = picks.advisory_sources([{"iso": "TH", "level": 1}, {"iso": "CI", "level": 2, "via": "ca"},
                                 {"iso": "PS", "level": 3}, {"iso": "PS", "level": 4, "via": "de"}], "us")
    gem = datas["USD"][1]["gems"][0]
    line = newsletter._gem_line(dict(gem, advBy=by["CI"]), 1)
    card = newsletter._compact_card(dict(datas["USD"][1]["picks"][1], advBy=by["PS"]), 1)
    top = newsletter._hero_card(dict(datas["USD"][1]["picks"][0], advBy=by["CI"]), 1)
    # The edition's main source (the one the footer's grade key names) is not
    # repeated on a compact card or a gem; another government's always is;
    # the top card names its own source in full either way.
    own = (newsletter._gem_line(dict(gem, advBy=by["TH"]), 1)
           + newsletter._compact_card(dict(datas["USD"][1]["picks"][1], advBy=by["TH"]), 1))
    results.append(ok(by == {"TH": "US State Dept", "CI": "Global Affairs Canada", "PS": "German Foreign Office"}
                      and "per Global Affairs Canada</span>" in line and "per German Foreign Office</span>" in card
                      and ">Safety grade from Global Affairs Canada advisories</div>" in top
                      and " per " not in top and " per " not in own and "State Dept" not in own
                      and ">Safety grade from US State Dept advisories</div>"
                      in newsletter._hero_card(datas["USD"][1]["picks"][0], 1)
                      and all(picks.ADV_SRC_SHORT[v.adv_source] == newsletter._adv_main(v) for v in V.values()),
                      "a 🛡️ grade names the government whose level it is: the top card in full, a compact card "
                      "or gem only where it isn't the edition's main source, the gap-filler where one filled "
                      "it (%s)" % by))

    print("2. the ten editions x 12 months")
    problems = []
    for m in range(1, 13):
        subjects = [snap[c][str(m)][0] for c in V]
        if len(set(subjects)) != len(subjects):
            problems.append((m, "subjects not unique", subjects))
    for c, v in V.items():
        for m in range(1, 13):
            subj, body = snap[c][str(m)]
            d = datas[c][m]
            if "your %s " % v.noun not in subj:
                problems.append((c, m, "subject", subj))
            if "Grades are for %s planning" % v.traveler not in body:
                problems.append((c, m, "footer"))
            if body.count("<div") != body.count("</div>") or body.count("<table") != body.count("</table>"):
                problems.append((c, m, "unbalanced markup"))
            if c != "USD":
                for bad_s in ("your dollar ", "US levels", "the US,", "US traveler", "vs the US"):
                    if bad_s in body or bad_s in subj:
                        problems.append((c, m, "US wording", bad_s))
                if any(s["iso"] == v.home_iso for s in d["picks"] + d["gems"]):
                    problems.append((c, m, "home country in picks"))
                if v.fx_emoji != "\U0001f4b5" and "\U0001f4b5" in body:
                    problems.append((c, m, "dollar banknote in a non-dollar edition"))
            # The dollar line, in the edition's money and with its banknote.
            if body.count(" goes ~") != body.count("%s %s goes ~" % (v.fx_emoji, v.noun_cap)):
                problems.append((c, m, "FX line wording/emoji"))
            if re.search(r"Dollar goes ~|dollar goes ~", body) and c not in ("USD", "CAD", "AUD"):
                problems.append((c, m, "compact FX line says dollar"))
            if d.get("variant") != c or d.get("home_iso") != v.home_iso:
                problems.append((c, m, "payload variant/home"))
    # The USD issue links its month's /cheapest page once (US-origin, so no other edition does).
    for c in V:
        for m in range(1, 13):
            n_links = snap[c][str(m)][1].count("https://wandergrade.com/cheapest/")
            want = 'href="https://wandergrade.com/cheapest/%s"' % newsletter._MONTH_SLUGS[m - 1]
            if n_links != (1 if c == "USD" else 0) or (c == "USD" and want not in snap[c][str(m)][1]):
                problems.append((c, m, "cheapest link", n_links))
    # Every edition's issue is for its month's next occurrence (render_cheapest.year_for,
    # the /cheapest page's own year): the payload carries that year and the
    # quote is the one for it. (Until Dec 2026 the intro printed the year,
    # "February 2027"; the one-paragraph intro names the month alone.)
    import fxtracker.render_cheapest as RCH
    for c in V:
        for m in range(1, 13):
            y = RCH.year_for(m, ds.TODAY)
            body = snap[c][str(m)][1]
            if datas[c][m]["year"] != y or newsletter._quote_for(y, m) not in body:
                problems.append((c, m, "year", y))
    results.append(ok(not problems, "subjects unique per month; wording, footer, emoji, home exclusion, year, "
                      "markup all right (%d renders)%s" % (12 * len(V), "" if not problems else
                                                             " -> %r" % problems[:4])))
    # The 2026-11 wording (Doug, 2026-11-03): an issue sent on the 1st
    # features the month two ahead, so each piece names that month instead
    # of "this month" (which read as the month it arrived in).
    import html as _html
    worded = []
    n_basis = 0
    for c, v in V.items():
        for m in range(1, 13):
            subj, body = snap[c][str(m)]
            d = datas[c][m]
            mn = picks.MONTHS[m - 1]
            nstrong = sum(1 for s_ in d["picks"] if (s_.get("fx") or 0) >= 3)
            pre = ("Plan ahead: after inflation, your %s goes further than usual in %d of %s’s picks."
                   % (v.noun, nstrong, mn) if nstrong else
                   "Plan ahead: %d destinations graded A+ to F on value, safety, weather and flights for %s."
                   % (len(d["picks"]), mn))
            hero = d["picks"][0]
            month_fare = hero.get("fly") is not None and hero.get("fly_basis") == "month"
            n_basis += month_fare
            want = [
                subj == "\U0001f9ed %s trips: where your %s goes furthest" % (mn, v.noun),
                body.startswith('<div style="display:none;') and body.count("&#847;") == 10
                and ('overflow:hidden">%s&#847;' % _html.escape(pre)) in body,
                body.count(" vs the route’s usual)") == month_fare
                and (not month_fare or "(%s vs the route’s usual)" % mn in body),
                "this month" not in body.lower() and "sweet spot" not in body,
            ]
            if not all(want):
                worded.append((c, m, want))
    results.append(ok(not worded and n_basis > 0,
                      "the 2026-11 wording in all %d renders: subject '{Month} trips: where your {noun} goes "
                      "furthest', preheader 'Plan ahead: …' naming the month (FX-strong and plain forms), "
                      "the hero fare '({Month} vs the route’s usual)' (%d heroes), no 'this month' or 'sweet "
                      "spot' left%s" % (12 * len(V), n_basis, "" if not worded else " -> %r" % worded[:3])))
    # The Dec 2026 first screen (Doug, 2026-11-09): one brand line, then one
    # paragraph that counts the picks and names the month, then the top card.
    # The tagline, the long intro with "{Month}’s standouts", the 📅 box and
    # the "Top picks" heading are gone (the two checks of them went with
    # them); the banknote sentence is there exactly when a pick has the
    # dollar line, in the edition's money, its banknote held to "marks". The
    # paragraph opens "N top picks" (the orchestrator's ruling on the
    # 2026-11-10 review: "N best-value trips" claimed too much, the gems
    # often grade higher).
    screen, n_plain = [], 0
    for c, v in V.items():
        for m in range(1, 13):
            body = snap[c][str(m)][1]
            d = datas[c][m]
            mn = picks.MONTHS[m - 1]
            nstrong = sum(1 for s_ in d["picks"] if (s_.get("fx") or 0) >= 3)
            n_plain += not nstrong
            marks = "%s&nbsp;marks where your %s goes further than usual right now." % (v.fx_emoji, v.noun)
            opens = ('<p style="font-size:16px;line-height:24px;color:#111;margin:0 0 16px"><b>%d top picks '
                     'for %s</b>, graded A+ to F on money, safety, weather and flights.' % (len(d["picks"]), mn))
            panel = body.split("\n", 2)[2].lstrip() if body.count("\n") > 1 else ""
            want = [
                panel.startswith('<div style="font-size:20px;line-height:26px;font-weight:800;color:#111;'
                                 'text-align:center;margin:0 0 10px">\U0001f30d WanderGrade</div>\n  ' + opens),
                (" " + marks in body) == bool(nstrong) and ("marks where " in body) == bool(nstrong),
                " Going another month? <a href=" in body and body.count("<p") == 1,
                # ... straight above the top card
                re.search(r"</a></p>\s*<div style=\"background:#ffffff;border:1px solid #e6e6e6", body) is not None,
                not any(x in body for x in ("Where Should I Travel Next?", "standouts", "\U0001f4c5", "Top picks",
                                            "two months ahead", "Where’s worth it", "unusually strong",
                                            "best-value")),
                "<b>WanderGrade</b> grades every country A+ to F&nbsp;· once a month, no spam&nbsp;· " in body,
            ]
            if not all(want):
                screen.append((c, m, want))
    results.append(ok(not screen and 0 < n_plain < len(cells),
                      "the first screen in all %d renders: the brand line '🌍 WanderGrade' opens the panel, then "
                      "one paragraph '<b>N top picks for {Month}</b>, graded A+ to F on money, safety, "
                      "weather and flights.' with the real number of picks, '{banknote} marks where your {noun} "
                      "goes further than usual right now.' exactly when a pick has the dollar line (%d renders "
                      "have none), 'Going another month?' and its link, then the top card; no tagline, old "
                      "intro, 📅 box, 'Top picks' heading or 'best-value'; the footer's brand line says what "
                      "WanderGrade is%s"
                      % (len(cells), n_plain, "" if not screen else " -> %r" % screen[:3])))
    # Wording samples from the spec.
    eur1 = snap["EUR"]["1"]
    results.append(ok(eur1[0] == "\U0001f9ed January trips: where your euro goes furthest"
                      and re.search(r">Prices ~\d+% below German&nbsp;levels</div>", eur1[1])
                      and "Grades are for a traveler from Germany (paying in euros) planning January travel;"
                      in eur1[1], "EUR: spec's subject, 'below German levels', footer"))
    cad = "".join(b for _, b in snap["CAD"].values())
    results.append(ok("\U0001f4b5&nbsp;marks where your Canadian dollar goes further than usual right now." in cad
                      and re.search(r">\U0001f4b5 Canadian dollar goes ~\d+% further than&nbsp;usual</div>", cad)
                      and "partly whether your Canadian dollar goes further than usual" in snap["CAD"]["1"][1]
                      and "local prices against Canada," in snap["CAD"]["1"][1]
                      and "\U0001f4b4" in "".join(b for _, b in snap["JPY"].values()),
                      "CAD: the intro, the dollar line and the grade key name the Canadian dollar and Canada; "
                      "JPY uses the yen banknote"))

    # FX is measured in the edition's own currency.
    eur_rows = {r["code"]: r["strength_pct"] for r in ds._fixture("rates_EUR.json")["rows"]}
    usd_rows = {r["code"]: r["strength_pct"] for r in ds._fixture("rates_USD.json")["rows"]}
    wrong = []
    for m in range(1, 13):
        for s in datas["EUR"][m]["picks"] + datas["EUR"][m]["gems"]:
            cur = picks.CUR_BY_ISO.get(s["iso"])
            want = None if cur == "EUR" else eur_rows.get(cur)
            if s["fx_nominal"] != want:
                wrong.append((m, s["iso"], s["fx_nominal"], want))
    results.append(ok(not wrong, "EUR picks' FX strength comes from the EUR-based rows%s"
                      % ("" if not wrong else " -> %r" % wrong[:3])))
    shared = picks.gather(1)
    fav_eur = picks._fav_for(shared, "EUR")
    strength = {r["code"]: r["strength_pct"] for r in fav_eur["rows"]}
    anchor = picks._price_level("DE", shared["ppp"], shared["rate_by_code"], shared["fit"]) or 1
    fares = picks.fares_for(shared, "DE")
    args = (1, shared["ppp"], shared["climate"], shared["rate_by_code"], strength, shared["adv"]["us"],
            shared["fit"], fares, anchor)
    fr = picks._score("FR", *args, home_iso="DE", home_cur="EUR")
    us = picks._score("US", *args, home_iso="DE", home_cur="EUR")
    results.append(ok(fr is not None and fr["fx"] is None and fr["fx_nominal"] is None,
                      "EUR edition: France (same currency) has no FX move"))
    results.append(ok(us is not None and us["fx_nominal"] == eur_rows["USD"] != usd_rows.get("USD"),
                      "EUR edition: the US's strength is the EUR-based USD row (%s)" % (us or {}).get("fx_nominal")))
    de = picks.fare_context(ds._fixture("flights_DE.json"))
    us_f = picks.fare_context(ds._fixture("flights_US.json"))
    results.append(ok(fares and de and fares["prices"] == de["prices"] != us_f["prices"]
                      and fares["fv"] == ds._fixture("flight_value_DE.json"),
                      "EUR edition prices fares (and month values) from DE, not the US"))

    print("2b. links, switching, INR wording, CNY flights")
    bad_links = []
    for c, v in V.items():
        for m in range(1, 13):
            body = snap[c][str(m)][1]
            links = re.findall(r"href=['\"](https://wandergrade\.com/\?[^'\"]*)['\"]", body)
            guide = [u for u in links if "tab=guide" in u]
            if c == "USD":
                if any("vo=" in u for u in links):
                    bad_links.append((c, m, "USD link carries vo"))
            else:
                want = "&vo=" + v.home_iso
                if not guide or any(not u.endswith(want) for u in guide):
                    bad_links.append((c, m, "guide link without " + want))
                if "%s/?vmn=%d%s" % (newsletter.SITE, m, want) not in body:
                    bad_links.append((c, m, "month link without " + want))
                if "%s/?vo=%s" % (newsletter.SITE, v.home_iso) not in body:
                    bad_links.append((c, m, "pick-your-month link without vo"))
    results.append(ok(not bad_links, "non-USD editions link with vo=<home> (guides, month, Top Picks); "
                      "USD links unchanged%s" % ("" if not bad_links else " -> %r" % bad_links[:3])))
    sw = "Want another currency’s edition? Reply and say which"
    results.append(ok(all((sw in snap[c][str(m)][1]) == (c != "USD") for c in V for m in range(1, 13)),
                      "every non-USD footer says how to switch editions; USD's doesn't"))
    # A pricier place says so and no more. Until Dec 2026 the line added ", but
    # graded worth it" (USD at any grade, other editions only at B or better,
    # after the INR edition read "pricier than India, but graded worth it"
    # over a C); the Overall badge beside the name says that now, so the
    # phrase is in no render and the line is the same at every grade.
    ct = newsletter._cost_text
    pricier = [(c, m, s_["iso"]) for c in V for m in range(1, 13) for s_ in datas[c][m]["picks"]
               if newsletter._pl_band(s_["pl"]) > 0]
    off = [x for x in pricier
           if ">Pricier than %s</div>" % V[x[0]].vs_place not in snap[x[0]][str(x[1])][1]]
    results.append(ok(pricier and not off and not any("worth it" in snap[c][str(m)][1] for c in V for m in range(1, 13))
                      and ct({"pl": 1.5, "value": 40}, V["USD"]) == "Pricier than the US"
                      and ct({"pl": 1.5, "value": 95}, V["INR"]) == ct({"pl": 1.5, "value": 40}, V["INR"])
                      == "Pricier than India",
                      "a pricier pick reads 'Pricier than {home}' at any grade (%d picks in the frozen months, "
                      "INR's among them); no render says 'graded worth it'%s"
                      % (len(pricier), "" if not off else " -> %r" % off[:3])))
    # CNY: estimated fares grade the neutral 70 (site and digest alike), so
    # the 1.4x-max cap no longer reads as an A+ deal for the far side of the world.
    shared = picks.gather(12)
    cn = picks.fares_for(shared, "CN")
    est_fly = []
    for iso in sorted(cn["est"]):
        sc = picks._score(iso, 12, shared["ppp"], shared["climate"], shared["rate_by_code"], {},
                          shared["adv"]["us"], shared["fit"], cn, 1.0, home_iso="CN", home_cur="CNY")
        if sc and sc["fly_basis"] == "distance" and sc["fly"] != 70:
            est_fly.append((iso, sc["fly"]))
    a_plus = [(m, s_["iso"]) for m in range(1, 13) for s_ in datas["CNY"][m]["picks"] + datas["CNY"][m]["gems"]
              if s_.get("fareEst") and (s_.get("fly") or 0) >= 93]
    results.append(ok(len(cn["est"]) > 150 and not est_fly and not a_plus,
                      "CNY: all %d estimated-fare countries grade Flights 70 (none A+ in any month's picks)"
                      % len(cn["est"])))

    print("2c. the cost line's band")
    # The site (app.js, 2026-10): PL_SAME 0.1, plShown = +rel.toFixed(2),
    # plBand on that. Ask JavaScript itself, so a binary edge (1.105 is stored
    # just under and prints "1.10") can't be wrong on one side only.
    grid = sorted(set([round(0.5 + i / 10000.0, 4) for i in range(11001)]
                      + [k / 1000.0 + 0.0005 for k in range(500, 1600)]
                      + [0.904, 0.905, 0.93, 0.95, 1.1, 1.104, 1.105, 1.1048, 1.106, 0.9049999999999999]))
    js = ("const PL_SAME = 0.1; const plShown = (rel) => +rel.toFixed(2);"
          "function plBand(rel) { const r = plShown(rel); return r <= 1 - PL_SAME ? -1 : r <= 1 + PL_SAME ? 0 : 1; }"
          "const xs = %s; print(JSON.stringify(xs.map((x) => [plShown(x), plBand(x), Math.round((1 - x) * 100)])));"
          % json.dumps(grid))
    jsf = tempfile.mktemp(suffix=".js")
    with open(jsf, "w") as f:
        f.write(js)
    try:
        site = json.loads(subprocess.run([JSC, jsf], capture_output=True, text=True, timeout=50).stdout)
    finally:
        os.unlink(jsf)
    off = [(x, w, (newsletter._pl_shown(x), newsletter._pl_band(x), newsletter.js_round((1 - x) * 100)))
           for x, w in zip(grid, site)
           if [newsletter._pl_shown(x), newsletter._pl_band(x), newsletter.js_round((1 - x) * 100)] != w]
    results.append(ok(len(site) == len(grid) and not off,
                      "printed decimals, band and percent equal JavaScript's for %d price levels%s"
                      % (len(grid), "" if not off else " -> %r" % off[:3])))
    ex = {0.93: "Prices about on par with the US", 0.904: "Prices ~10% below US&nbsp;levels",
          0.95: "Prices about on par with the US", 1.104: "Prices about on par with the US",
          1.105: "Prices about on par with the US", 1.106: "Pricier than the US",
          0.6: "Prices ~40% below US&nbsp;levels"}
    got = {x: ct({"pl": x, "value": 80}) for x in ex}
    money = newsletter._money_lines
    results.append(ok(got == ex and ct({"value": 80}) == "" and ct({"pl": 0.6}, V["EUR"]) == "Prices ~40% below German&nbsp;levels"
                      and ct({"pl": 1.0}, V["EUR"]) == "Prices about on par with Germany",
                      "edges: 0.93 and 0.95 on par (were '7%'/'5% below'), 0.904 '~10% below', "
                      "1.104/1.105 on par (1.104 was 'pricier'), 1.106 pricier; no price level, no line"))
    # The two money lines, price first, on the top card and a compact card
    # alike; the dollar line from 3% (the site's Math.round), no 💰 on either.
    both = [money({"pl": 0.6, "fx": fx_}, V["USD"], top=t) for fx_ in (2.99, 3, 4.5, 5.49) for t in (True, False)]
    results.append(ok(all("Prices ~40% below US&nbsp;levels</div>" in x and "\U0001f4b0" not in x for x in both)
                      and ["further than&nbsp;usual" in x for x in both] == [False, False] + [True] * 6
                      and [re.findall(r"goes ~(\d+)%", x) for x in both[2:]] == [["3"]] * 2 + [["5"]] * 4
                      and all(x.index("Prices") < x.index("\U0001f4b5 Dollar goes ~") for x in both[2:])
                      and ">\U0001f4b6 Euro goes ~4% further than&nbsp;usual</div>" in money({"pl": 0.6, "fx": 3.6}, V["EUR"])
                      and money({"fx": 6}, V["USD"]).count("<div") == 1 and money({}, V["USD"]) == "",
                      "the money lines: 'Prices …' first, then '{banknote} {Money} goes ~N% further than usual' "
                      "only from 3% (2.99 none, 3 -> 3, 4.5 -> 5), the same on the top card and a compact card"))
    old_band = lambda x: -1 if x < 0.95 else 1 if x > 1.1 else 0
    usd_d = datas["USD"]
    moved = sorted(i for i in shared["ppp"]
                   if (lambda x: x is not None and old_band(x) != newsletter._pl_band(x))(
                       picks._price_level(i, shared["ppp"], shared["rate_by_code"], shared["fit"])))
    shown = sorted({s_["iso"] for m in range(1, 13) for s_ in usd_d[m]["picks"] + usd_d[m]["gems"]})
    results.append(ok(moved and not set(moved) & set(shown),
                      "frozen data: %s change band, none is a USD pick or gem in any month, so the "
                      "golden USD text is unchanged" % ", ".join(moved)))
    print("2d. ROLLOUT typos can't take the site down")
    results.append(ok(dv.rollout_problems() == [], "the committed ROLLOUT has no problems"))
    saved = dict(dv.ROLLOUT)
    typo_cases = ({"USD": "send", "EUR": "Send"}, {"USD": "send", "eur": "send", "XYZ": "draft"},
                  {"EUR": "send"}, {"USD": "draft", "GBP": "draft"})
    lists = []
    try:
        for t in typo_cases:
            dv.ROLLOUT.clear(); dv.ROLLOUT.update(t)
            lists.append((dv.rollout_problems(), dv.send_codes(), dv.draft_codes(), dv.picker_codes(),
                          dv.stage("USD")))
    finally:
        dv.ROLLOUT.clear(); dv.ROLLOUT.update(saved)
    results.append(ok(all(p and sc[-1] == "USD" and "USD" in dc and pc[0] == "USD" and st == "send"
                          for p, sc, dc, pc, st in lists)
                      and lists[0][1] == ("USD",) and lists[1][3] == ("USD",)
                      and lists[2][1] == ("EUR", "USD") and lists[3][2] == ("GBP", "USD"),
                      "typos are reported, ignored by the code lists, and USD always stays 'send'"))
    src = open(os.path.join(ROOT, "fxtracker", "digest_variants.py"), encoding="utf-8").read()
    assert 'ROLLOUT = {"USD": "send"}' in src
    crash = None
    try:
        exec(compile(src.replace('ROLLOUT = {"USD": "send"}', 'ROLLOUT = {"USD": "send", "EUR": "Send"}'),
                     "digest_variants_typo", "exec"), {"__name__": "digest_variants_typo"})
    except Exception as e:
        crash = e
    results.append(ok(crash is None, "a module whose ROLLOUT has a typo still imports (server.py, "
                      "accounts.py import it) -> %r" % (crash,)))

    print("3. real_fx_pct home-side guard")
    pl = picks.pricelevel
    ppp = json.load(open(os.path.join(ROOT, "public", "ppp.json"), encoding="utf-8"))
    fake = dict(ppp)
    fake["ZZ"] = {"ppp": 1.0, "year": 2024, "infl": 50.0, "infl_year": 2022}
    th = pl.real_fx_pct(5.0, "TH", "ZZ", fake)
    results.append(ok(th is None, "a home with stale high inflation claims no direction (None)"))
    fake["ZZ"] = {"ppp": 1.0, "year": 2024, "infl": 50.0, "infl_year": 2024}
    results.append(ok(pl.real_fx_pct(5.0, "TH", "ZZ", fake) is not None,
                      "the same home with a current figure still gets a real move"))
    # US home: identical to the formula without the guard, for every country.
    def unguarded(nominal_pct, iso, home_iso, ppp):
        r_b = pl.infl_rate(home_iso, ppp)
        if r_b is None:
            r_b = pl.us_infl(ppp)
        r_l = pl.infl_rate(iso, ppp)
        if r_l is None:
            if (ppp.get(iso) or {}).get("infl") is not None and ppp[iso]["infl"] >= 10:
                return None
            r_l = r_b
        return pl.js_round(((1 + nominal_pct / 100.0) * ((1 + r_b) / (1 + r_l)) ** 0.5 - 1) * 10000) / 100
    diff = [i for i in ppp for n in (-7.5, 0.0, 4.2) if pl.real_fx_pct(n, i, "US", ppp) != unguarded(n, i, "US", ppp)]
    results.append(ok(not diff and not pl.high_infl_unknown("US", ppp),
                      "US home unaffected for all %d countries" % len(ppp)))

    print("4. one provider fetch for every non-USD base")
    import copy, importlib
    from fxtracker import picks as P, rates as R   # the modules digest_snapshot last installed
    rates = importlib.reload(R)                     # the real compute_favorability again
    assert P.rates is rates
    calls = []
    ts = {"2026-01-%02d" % d: {"EUR": 0.9 + d / 1000, "GBP": 0.8 - d / 1000, "JPY": 150.0 + d, "CAD": 1.37,
                                "AUD": 1.5, "CNY": 7.1, "INR": 88.0, "KRW": 1390.0 + d, "CHF": 0.8}
          for d in range(1, 29)}
    rates.get_currencies = lambda: (calls.append("currencies"), {k: {"name": k} for k in ts["2026-01-01"]})[1]
    rates.get_latest = lambda: (calls.append("latest"), ("2026-01-28", dict(ts["2026-01-28"])))[1]
    rates.get_timeseries = lambda a, b: (calls.append("timeseries"), copy.deepcopy(ts))[1]
    rates.is_known_base = lambda b: True
    bases = [c for c in dv.SEND_ORDER if c != "USD"]
    shared_m = {"fav_by_base": {}}
    memo = {c: P._fav_for(shared_m, c) for c in bases}
    n_memo = len(calls)
    calls.clear()
    direct = {c: rates.compute_favorability(base=c) for c in bases}
    same = json.dumps(direct, sort_keys=True) == json.dumps(memo, sort_keys=True)
    results.append(ok(n_memo == 3 and len(calls) == 27 and same and rates.get_latest.__name__ == "<lambda>",
                      "9 bases: %d provider fetches (27 without the memo), identical results, "
                      "functions restored" % n_memo))

    print("5. cover photos go to weserv as thumbnails (Wikimedia 429s weserv's fetches of originals)")
    up = "upload.wikimedia.org/wikipedia/commons/7/79/Ha_Long_Bay_in_2019.jpg"
    cases = [
        ((up, 3251), "thumb.wikimedia.org/wikipedia/commons/thumb/7/79/Ha_Long_Bay_in_2019.jpg/"
                     "1280px-Ha_Long_Bay_in_2019.jpg"),
        ((up, 1100), "thumb.wikimedia.org/wikipedia/commons/thumb/7/79/Ha_Long_Bay_in_2019.jpg/"
                     "960px-Ha_Long_Bay_in_2019.jpg"),
        (("upload.wikimedia.org/wikipedia/commons/a/ab/Flag.PNG", 600),
         "thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/Flag.PNG/500px-Flag.PNG"),
        ((up, 400), up),                                   # under the smallest step
        ((up, None), up),                                  # width unknown
        (("upload.wikimedia.org/wikipedia/commons/a/ab/Map.svg", 2000),
         "upload.wikimedia.org/wikipedia/commons/a/ab/Map.svg"),   # thumbnail renamed (.svg.png)
        (("thumb.wikimedia.org/wikipedia/commons/thumb/2/2a/X.jpg/3840px-X.jpg", 3840),
         "thumb.wikimedia.org/wikipedia/commons/thumb/2/2a/X.jpg/3840px-X.jpg"),
        (("upload.wikimedia.org/wikipedia/en/a/ab/Poster.jpg", 2000),
         "upload.wikimedia.org/wikipedia/en/a/ab/Poster.jpg"),     # not Commons
    ]
    bad = [(a, P._thumb(*a)) for a, want in cases if P._thumb(*a) != want]
    results.append(ok(not bad, "_thumb: a Commons original becomes the widest step its width allows; "
                      "anything else is left alone (%d cases)%s" % (len(cases), bad or "")))

    print("6. every email says what its payload says (digest_check)")
    said, n = [], {"lines": 0, "links": 0, "images": 0, "badges": 0, "credits": 0}
    for c, m in cells:
        subj, body = snap[c][m]
        probs = dc.check(newsletter, picks, V[c], datas[c][int(m)], subj, body)
        if probs:
            said.append((c, m, probs[:2]))
        want = dc.expected(newsletter, picks, V[c], datas[c][int(m)])
        for k in n:
            n[k] += len(want[k])
    results.append(ok(not said and n["credits"] == n_cov and n["badges"] == 8 * len(cells),
                      "all %d renders: every visible line with its non-breaking spaces (%d: the intro's count "
                      "and banknote sentence, each card's and gem's name, four letters, source and money "
                      "lines, the grade key, the footer), every link's address, words, colour and underline "
                      "(%d), every image's address, alt text and the guide it links to (%d: the top card's "
                      "banner, the compact cards' small copies, the flags), every Overall badge's letter and "
                      "its fill and letter colour as the site's stylesheet has them (%d, each right after "
                      "its name's link and outside it, unable to wrap, the top card's the biggest) and every "
                      "photo credit's country, photographer, file page, licence and licence link (%d, one "
                      "for each card with a photo, in card order) are the payload's; the credits sit right "
                      "under the quote and above the footer, which is the grade key, the grades-for line and "
                      "the brand line; every line is a block with its own size and line height%s"
                      % (len(cells), n["lines"], n["links"], n["images"], n["badges"], n["credits"],
                         "" if not said else " -> %r" % said[:3])))
    # Credits the frozen months don't have: a top card with no photo (no
    # entry, and the others keep their order), a licence with no link (plain
    # text), and a photographer's name with markup in it (printed as given,
    # escaped, never tidied).
    d = copy.deepcopy(datas["USD"][2])
    P = d["picks"]
    odd = 'Ana "Nia" <b>O\u2019Neil</b> & S\u00f8n, Jr. \u00b7 flickr'
    P[0]["photo"] = P[0]["photo_thumb"] = P[0]["photo_credit"] = None
    P[1]["photo_credit"] = dict(P[1]["photo_credit"], license="Public domain", license_url="")
    P[2]["photo_credit"] = dict(P[2]["photo_credit"], artist=odd)
    subj, body = newsletter.render_digest(d)
    e = dc.Email(body)
    cr = lambda s_: s_["photo_credit"]
    want = [(P[1]["name"], cr(P[1])["artist"], cr(P[1])["page"], "Public domain", None),
            (P[2]["name"], odd, cr(P[2])["page"], cr(P[2])["license"], cr(P[2])["license_url"])] + [
            (s_["name"], cr(s_)["artist"], cr(s_)["page"], cr(s_)["license"], cr(s_)["license_url"]) for s_ in P[3:]]
    probs = dc.check(newsletter, picks, V["USD"], d, subj, body) + dc.proofing(body)
    results.append(ok(not probs and e.credits == want and len(want) == 4
                      and [x["kind"] for x in e.images if x["kind"] != "flag"] == ["thumb"] * 4
                      and newsletter._credits([]) == "" and newsletter._credits([P[0]]) == "",
                      "a card without a photo has no credit and the rest keep their order; a licence with no "
                      "link is plain text; a photographer's name with markup in it is printed as given; no "
                      "photos, no block%s" % ("" if not probs else " -> %r" % probs[:3])))
    # Payload shapes the frozen months don't have. Every frozen payload has
    # five picks, a fare grade on every card, a top card graded on US State
    # Dept advisories and a credit only where there is a photo, so (the
    # 2026-11-10 review, with five mutants to show it) a renderer that
    # hard-coded the "5", always wrote the plural, printed a source line for
    # no source, a Flights unit for no fare, or a credit for no photo passed
    # every test. Each shape below is rendered and read back against its own
    # payload; the literal checks say what a reader would see.
    def shaped(change):
        dd = copy.deepcopy(datas["USD"][2])
        change(dd)
        sj, bd = newsletter.render_digest(dd)
        return dd, bd, dc.check(newsletter, picks, V["USD"], dd, sj, bd) + dc.proofing(bd)

    def no_fare(*cards):
        def change(dd):
            for s_ in (cards and [(dd["picks"] + dd["gems"])[i] for i in cards]) or dd["picks"] + dd["gems"]:
                s_.update(fly=None, fly_basis=None, fare=None, fareEst=False)
        return change

    def keep(dd, k):
        dd["picks"] = dd["picks"][:k]

    def no_photo(dd):
        dd["picks"][1]["photo"] = dd["picks"][1]["photo_thumb"] = None   # ... its credit left in place

    def top_estimate(dd):
        dd["picks"][0].update(fly=70, fly_basis="distance", fareEst=True)

    plane = "\u2708\ufe0f"
    n_plane = snap["USD"]["2"][1].count(plane)       # one on each card and gem, one in the grade key
    n_cards = len(datas["USD"][2]["picks"]) + len(datas["USD"][2]["gems"])
    d4, b4, p4 = shaped(lambda dd: keep(dd, 4))
    d1, b1, p1 = shaped(lambda dd: keep(dd, 1))
    dn, bn_, pn = shaped(lambda dd: dd["picks"][0].update(advBy=None) or dd["picks"][1].update(advBy=None))
    df, bf, pf = shaped(no_fare(0, 1, 5))            # the top card, a compact card and the first gem
    da, ba, pa = shaped(no_fare())                   # no fare data at all
    dp, bp, pp = shaped(no_photo)
    de_, be, pe = shaped(top_estimate)
    dg, bg, pg = shaped(lambda dd: dd["gems"][1].update(advBy="Global Affairs Canada"))
    group = "<span style='display:inline-block'>"
    forced = re.sub(r"(&nbsp; )(\U0001f4b0&nbsp;<b>[^<]*</b>&nbsp;&middot; \U0001f6e1️&nbsp;<b>[^<]*</b> <span style='color:#666'>per "
                    r"Global Affairs Canada</span>.*?)(</div>)", lambda mm: mm.group(1) + group + mm.group(2) + "</span>" + mm.group(3),
                    bg, 1)
    intro_of = lambda bd: re.search(r"<p [^>]*>(.*?)</p>", bd, re.S).group(1)
    results.append(ok(not (p4 or p1) and intro_of(b4).startswith("<b>4 top picks for February</b>, graded")
                      and intro_of(b1).startswith("<b>1 top pick for February</b>, graded")
                      and "picks for" not in b1 and b1.count("See the guide&nbsp;→") == 0
                      and b4.count("See the guide&nbsp;→") == 3,
                      "four picks read '4 top picks for February', one reads '1 top pick for February' (no "
                      "plural, no compact card), and each email says what its payload says%s"
                      % ("" if not (p4 or p1) else " -> %r" % (p4 + p1)[:3])))
    results.append(ok(not pn and "Safety grade from" not in bn_ and " per " not in bn_ and "None" not in bn_
                      and "Safety grade from US State Dept advisories" in snap["USD"]["2"][1],
                      "a top card whose payload names no advisory source has no 'Safety grade from …' line "
                      "(and a compact card no 'per …'), never 'from None'%s" % ("" if not pn else " -> %r" % pn[:3])))
    results.append(ok(not pf and n_plane == n_cards + 1 and bf.count(plane) == n_plane - 3 and "Flights" not in bf
                      and "for the distance" not in bf and "route’s usual" not in bf
                      and "weather and flights." in intro_of(bf) and "(~&nbsp;=&nbsp;estimated)." in bf,
                      "a card or gem with no fare grade shows no ✈️ (the top card no 'Flights' and no basis); "
                      "the others keep theirs, and the intro and the key still speak of flights%s"
                      % ("" if not pf else " -> %r" % pf[:3])))
    results.append(ok(not pa and plane not in ba and "flights" not in intro_of(ba)
                      and intro_of(ba).startswith("<b>5 top picks for February</b>, graded A+ to F on money, "
                                                  "safety and weather.")
                      and "usual weather.</div>" in ba and "estimated" not in ba and "the fare against" not in ba,
                      "with no fare data at all (picks leaves Flights out of every grade) no row shows ✈️, the "
                      "intro reads 'graded A+ to F on money, safety and weather.' and the grade key ends at "
                      "the weather%s" % ("" if not pa else " -> %r" % pa[:3])))
    results.append(ok(not pp and dp["picks"][1]["photo_credit"] and dp["picks"][1]["name"] + ":" not in bp
                      and [x[0] for x in dc.Email(bp).credits] == [s_["name"] for i, s_ in enumerate(dp["picks"]) if i != 1]
                      and len([x for x in dc.Email(bp).images if x["kind"] == "thumb"]) == 3,
                      "a card whose payload has a credit but no photo shows neither: no entry in the credits "
                      "block, no picture%s" % ("" if not pp else " -> %r" % pp[:3])))
    results.append(ok(not pg and snap["USD"]["2"][1].count(group) == 3 and bg.count(group) == 2
                      and "per Global Affairs Canada</span>&nbsp;&middot; " in bg and forced != bg
                      and forced.count(group) == 3 and dc.check(newsletter, picks, V["USD"], dg, snap["USD"]["2"][0], forced),
                      "a gem's four grades are one group that moves to the next line together, except on a "
                      "row that names another government, which flows freely (as one group it is wider than "
                      "a 360px phone's line: three lines, the last grade alone); forcing that row into a "
                      "group is reported%s" % ("" if not pg else " -> %r" % pg[:3])))
    results.append(ok(not pe and "Flights&nbsp;<b>~B</b> <span style='color:#6b7681'>(estimated, no fare yet)</span>" in be
                      and "for the distance" not in be and "route’s usual" not in be,
                      "a top card whose fare is an estimate reads '✈️ Flights ~B (estimated, no fare yet)'%s"
                      % ("" if not pe else " -> %r" % pe[:3])))

    # The controls: each deliberate fault below must be reported, or the
    # checks above prove nothing. A fault is built from the payload where it
    # names a number or a colour, and one built on a piece the body no
    # longer has is a FAIL line ("not planted" below), never a crash that
    # stops sections 7 and 8 from running: piece() then gives words that
    # are in no body, and cut() leaves the body as it is.
    subj, body = snap["USD"]["2"]
    d, v = datas["USD"][2], V["USD"]
    a1, a2 = (cr(s_) for s_ in d["picks"][:2])
    swap = lambda x, y: body.replace(x, "\0").replace(y, x).replace("\0", y)
    piece = lambda mm, g=0: mm.group(g) if mm else "\0not in the body\0"
    cut = lambda mm: body.replace(mm.group(0), "") if mm else body
    credits_div = piece(re.search(r'<div style="[^"]*">Photos \(cropped\).*?</div>', body))
    brand_div = piece(re.search(r'<div style="[^"]*">\U0001f30d WanderGrade</div>', body))
    badge1 = piece(re.search(r" (<span style='display:inline-block;[^>]*>[^<]*</span>)", body))
    fx_div = "<div style='font-size:14px;line-height:21px;color:#0a7d28;font-weight:600;margin:2px 0 0'>%s</div>"
    # From the payload: a card priced below home and its percent, a card
    # with no dollar line, the top card's badge colours, a compact card's
    # safety letter, and the issue's quote.
    cols = dc.site_grade_colours(os.path.join(ROOT, "public", "styles.css"))
    low = next((s_ for s_ in d["picks"] if newsletter._pl_band(s_["pl"]) < 0), d["picks"][0])
    pct = picks.js_round((1 - low["pl"]) * 100)
    weak = next((s_ for s_ in d["picks"] if not (s_.get("fx") or 0) >= 3), d["picks"][0])
    weak_cost = "%s</div>" % newsletter._cost_text(weak, v)
    fill0, ink0 = cols[picks.grade(d["picks"][0]["value"])]
    fill_x = next(c[0] for c in cols.values() if c[0] != fill0 and c[1] == ink0)
    ink_x = "#000000" if ink0 == "#ffffff" else "#ffffff"
    shield = "\U0001f6e1️&nbsp;<b>%s</b>" % picks.SAFE_GRADE[d["picks"][1]["advLvl"]]
    n_picks = len(d["picks"])
    quote_src = dc.QUOTES[(d["year"] * 12 + d["month"]) % len(dc.QUOTES)][2]
    faults = [
        # -- what the cards say
        ("a word added to a card", "check", body.replace("See the guide&nbsp;→", "See the guide now&nbsp;→", 1)),
        ("an Overall letter changed", "check", re.sub(r"(white-space:nowrap'>)(A\+|A|B\+|B|C|D|F)<",
                                                      lambda mm: mm.group(1) + ("B<" if mm.group(2) != "B" else "C<"), body, 1)),
        ("a badge in another grade's colour", "check",
         body.replace("background:%s;color:%s" % (fill0, ink0), "background:%s;color:%s" % (fill_x, ink0), 1)),
        ("a badge's letter in the wrong colour for its fill", "check",
         body.replace("background:%s;color:%s" % (fill0, ink0), "background:%s;color:%s" % (fill0, ink_x), 1)),
        ("a badge moved inside its name's link", "check",
         body.replace("</a>" + badge1, badge1 + "</a>", 1)),
        ("a badge that can wrap", "check", body.replace(";white-space:nowrap", "", 1)),
        ("a compact card's badge as big as the top card's", "check",
         body.replace("font-size:13px;line-height:18px;font-weight:800", "font-size:16px;line-height:22px;font-weight:800", 1)),
        ("one of a card's four letters changed", "check",
         body.replace(shield, shield.replace("<b>A<", "<b>C<").replace("<b>B<", "<b>A<"), 1)),
        ("an estimated fare without its ~", "check", body.replace("<b>~", "<b>", 1)),
        ("a ~ on a fare that is not an estimate", "check",
         re.sub(r"(\u2708\ufe0f&nbsp;(?:Flights&nbsp;)?<b>)(?!~)", r"\1~", body, 1)),
        ("an icon parted from its letter by a plain space", "check", body.replace("\U0001f4b0&nbsp;<b>", "\U0001f4b0 <b>", 1)),
        ("a row that can break before a dot", "check", body.replace("</b>&nbsp;&middot; ", "</b> &middot; ", 1)),
        ("a flag's gap as a plain space", "check", body.replace("border-radius:2px'>&nbsp;<a", "border-radius:2px'> <a", 1)),
        ("an arrow that can drop to its own line", "check", body.replace("See the guide&nbsp;→", "See the guide →", 1)),
        ("the top card's source line naming another government", "check",
         body.replace("Safety grade from US State Dept advisories", "Safety grade from Global Affairs Canada advisories", 1)),
        ("the top card's source line dropped", "check",
         cut(re.search(r"<div style='[^']*'>Safety grade from [^<]*</div>", body))),
        ("the main source repeated on a compact row", "check",
         body.replace(shield + "&nbsp;&middot;",
                      shield + " <span style='color:#666'>per US State Dept</span>&nbsp;&middot;", 1)),
        ("a price line's number changed", "check",
         body.replace("Prices ~%d%% below" % pct, "Prices ~%d%% below" % (pct + 1), 1)),
        ("a price line dropped", "check",
         cut(re.search(r"<div style='[^']*'>Prices ~%d%% below US&nbsp;levels</div>" % pct, body))),
        ("a dollar line's number changed", "check",
         re.sub(r"(Dollar goes ~)(\d+)%", lambda mm: "%s%d%%" % (mm.group(1), int(mm.group(2)) + 1), body, 1)),
        ("a dollar line dropped", "check",
         cut(re.search(r"<div style='[^']*'>\U0001f4b5 Dollar goes ~\d+% further than&nbsp;usual</div>", body))),
        ("a dollar line on a card under 3%", "check",
         body.replace(weak_cost, weak_cost + fx_div % "\U0001f4b5 Dollar goes ~3% further than&nbsp;usual", 1)),
        ("the dollar line above the price line", "check",
         re.sub(r"(<div style='[^']*'>Prices ~\d+% below US&nbsp;levels</div>)(<div style='[^']*'>\U0001f4b5 [^<]*</div>)",
                r"\2\1", body, 1)),
        ("a compact card loading the banner, not its small copy", "check",
         body.replace(d["picks"][1]["photo_thumb"], d["picks"][1]["photo"], 1)),
        ("a cover swapped for another's", "check", swap(d["picks"][0]["photo"], d["picks"][1]["photo"])),
        ("a guide link pointing at another country", "check",
         body.replace("gc=%s&" % d["picks"][0]["iso"], "gc=%s&" % d["picks"][1]["iso"], 1)),
        ("a green link turned blue", "check", body.replace('<span style="color:#0a7d28">', '<span style="color:#0069FF">', 1)),
        # -- the gems
        ("a gem's four grades out of their group", "check",
         body.replace("<span style='display:inline-block'>", "<span>", 1)),
        ("a gem's grades in a group that can't wrap inside", "check",
         body.replace("<span style='display:inline-block'>", "<span style='display:inline-block;white-space:nowrap'>", 1)),
        ("a gem's badge one plain space from its first icon", "check",
         body.replace("&nbsp; <span style='display:inline-block'>", " <span style='display:inline-block'>", 1)),
        # -- the first screen and the footer
        ("the intro counting one pick too many", "check",
         body.replace("<b>%d top picks" % n_picks, "<b>%d top picks" % (n_picks + 1), 1)),
        ("'best-value trips' back in the intro", "check", body.replace(" top picks for ", " best-value trips for ", 1)),
        ("the banknote sentence dropped from the intro", "check",
         body.replace(" \U0001f4b5&nbsp;marks where your dollar goes further than usual right now.", "", 1)),
        ("the intro's banknote free to end a line alone", "check", body.replace("\U0001f4b5&nbsp;marks", "\U0001f4b5 marks", 1)),
        ("the brand line twice", "both", body.replace("</p>", "</p>" + brand_div, 1)),
        ("the brand line under the intro", "both", body.replace(brand_div, "", 1).replace("</p>", "</p>" + brand_div, 1)),
        ("the old tagline back under the brand line", "check",
         body.replace(brand_div, brand_div + '<div style="font-size:14px;line-height:20px;'
                      'color:#555;text-align:center">Where Should I Travel Next?</div>', 1)),
        ("the 💰 back on the budget line", "check",
         body.replace("<b>On a budget?</b>", "\U0001f4b0 <b>On a budget?</b>", 1)),
        ("the grade key naming another government", "check",
         body.replace("is the US State Dept advisory level", "is the Global Affairs Canada advisory level", 1)),
        ("the grade key dropped", "check", cut(re.search(r'<div style="[^"]*border-top[^"]*"><b>Reading the.*?</div>', body))),
        ("the footer's border on its second line", "check",
         body.replace('margin:8px 0 0">Grades are for', 'border-top:1px solid #e0e0e0;margin:8px 0 0">Grades are for', 1)),
        ("the grade key without what ~ means", "check", body.replace(" (~&nbsp;=&nbsp;estimated)", "", 1)),
        ("'1-year' free to break at its hyphen", "check",
         body.replace('<span style="white-space:nowrap">1-year</span>', "1-year", 1)),
        ("'re-grade' free to break at its hyphen", "check",
         body.replace('<span style="white-space:nowrap">re-grade</span>', "re-grade", 1)),
        ("the date free to break at a hyphen", "check",
         body.replace('<span style="white-space:nowrap">%s</span>' % d["as_of"].replace("-", "‑"),
                      d["as_of"].replace("-", "‑"), 1)),
        ("the date with plain hyphens, which a mail app turns into a blue calendar link", "check",
         body.replace(d["as_of"].replace("-", "‑"), d["as_of"], 1)),
        ("a dot free to start a line of the brand line", "check", body.replace("A+ to F&nbsp;· once", "A+ to F · once", 1)),
        ("the unsubscribe token mistyped", "check", body.replace("{{ unsubscribe_url }}", "{{ unsubscribe }}", 1)),
        ("the quote cited to another work", "check", body.replace(quote_src, "Roughing It, 1872", 1)),
        # -- the credits
        ("two photographers swapped", "check", swap(">%s<" % a1["artist"], ">%s<" % a2["artist"])),
        ("a credit linked to another photo's page", "check", swap(a1["page"], a2["page"])),
        ("a credit dropped", "check", re.sub(r"(Wikimedia Commons\. ).*?&middot; ", r"\1", body, 1)),
        ("a dot free to start a line of the credits", "check",
         re.sub(r"(Wikimedia Commons\. .*?)&nbsp;&middot; ", r"\1 &middot; ", body, 1)),
        ("a licence name free to split across lines", "check",
         body.replace('text-decoration:none;white-space:nowrap"><span><span style="color:#6f6f6f">',
                      'text-decoration:none"><span><span style="color:#6f6f6f">', 1)),
        ("a photographer's name that can't wrap", "check",
         body.replace('<a href="%s" style="color:#6f6f6f;text-decoration:none">' % a1["page"],
                      '<a href="%s" style="color:#6f6f6f;text-decoration:none;white-space:nowrap">' % a1["page"], 1)),
        ("the credits moved under the footer", "check",
         body.replace(credits_div, "", 1).replace("\n</div>", credits_div + "\n</div>")),
        ("the credits tucked inside the quote block", "check",
         body.replace(credits_div, "", 1).replace("</i></div></div>", "</i></div>" + credits_div + "</div>")),
        # -- what Buttondown would restyle
        ("the grade key back in a <p>", "both", re.sub(r'<div (style="[^"]*border-top[^"]*"><b>Reading the.*?)</div>',
                                                      r"<p \1</p>", body, 1)),
        ("a link's words out of their spans", "proofing",
         body.replace('<span><span style="color:#666;text-decoration:underline">unsubscribe</span></span>', "unsubscribe")),
        ("11px small print", "both", body.replace("font-size:12px", "font-size:11px", 1)),
        ("a #888 left", "proofing", body.replace("color:#666", "color:#888", 1)),
        ("a block with no colour of its own", "both", body.replace(";color:#444;margin:16px 0 0\">", ";margin:16px 0 0\">", 1)),
        ("a block with no font-size of its own", "both", body.replace("font-size:14px;line-height:21px;color:#444;", "line-height:21px;color:#444;", 1)),
        ("a row with no line-height of its own", "both",
         body.replace("font-size:13px;line-height:20px;color:#555;margin:3px 0 0", "font-size:13px;color:#555;margin:3px 0 0", 1)),
        ("a button with no line-height of its own", "proofing",
         body.replace("font-size:14px;line-height:20px;padding:10px 18px", "font-size:14px;padding:10px 18px", 1)),
        ("a button's wrapper with no size of its own", "both",
         body.replace('<div style="font-size:14px;line-height:20px;margin:14px 0 0"><a', '<div style="margin:14px 0 0"><a', 1)),
        ("a flag with a right margin", "proofing",
         body.replace("vertical-align:-2px;border-radius:2px'", "vertical-align:-2px;border-radius:2px;margin-right:7px'", 1)),
        ("the intro with no margin of its own", "both", body.replace('color:#111;margin:0 0 16px"><b>', 'color:#111"><b>', 1)),
        ("the heading with no margin of its own", "both",
         body.replace("line-height:24px;margin:20px 0 4px;color:#111'>", "line-height:24px;color:#111'>", 1)),
        ("a <div> never closed", "both", body[::-1].replace(">vid/<", "", 1)[::-1]),
    ]
    missed = []
    for name, by, mutant in faults:
        if mutant == body:
            missed.append((name, "not planted: the piece it changes is not in the body"))
            continue
        found = {"check": bool(dc.check(newsletter, picks, v, d, subj, mutant)), "proofing": bool(dc.proofing(mutant))}
        if not all(found[k] for k in (("check", "proofing") if by == "both" else (by,))):
            missed.append((name, found))
    results.append(ok(not missed and not dc.check(newsletter, picks, v, d, subj, body) and not dc.proofing(body),
                      "controls: each of %d deliberate faults is reported (%s)%s"
                      % (len(faults), "; ".join(f[0] for f in faults), "" if not missed else " -> MISSED %r" % missed)))
    # ... and the control list itself: a fault built on a piece the body
    # doesn't have is a line here, not a crash (it used to stop the run at
    # the first changed fixture number, with sections 7 and 8 never run).
    results.append(ok(cut(None) == body and piece(None) not in body and body.replace(piece(None), "x") == body,
                      "a fault whose piece is missing from the body leaves the body as it is and is counted "
                      "as not planted, so the run goes on to sections 7 and 8"))

    print("7. Buttondown can't restyle it (digest_check.proofing)")
    unproof = [(c, m, dc.proofing(snap[c][m][1])[:2]) for c, m in cells if dc.proofing(snap[c][m][1])]
    results.append(ok(not unproof,
                      "all %d renders: the intro is the only <p> (and no list markup), and it and the one "
                      "heading have their own margin; every link's words sit in two spans with a colour on "
                      "the inner one and text-decoration:none on the <a>; no font-size under %dpx but the "
                      "hidden preheader's; no #888; no image has a side margin; every block that shows words "
                      "has its own colour, font-size and line-height (a button's link too); the brand line is "
                      "there once, first in the panel; the markup nests%s"
                      % (len(cells), dc.MIN_PX, "" if not unproof else " -> %r" % unproof[:3])))
    # A control: the email as it was before the redesign fails this, in the
    # ways the delivered Nov 1 2026 issue showed (blue links, 16px small
    # print, 11px credits, #888).
    was = " | ".join(dc.proofing(old_snap["USD"]["2"][1]))
    results.append(ok(all(x in was for x in ("<p> (the intro is the only one allowed)", "two spans",
                                               "font-size 11px", "#888 is still in the body",
                                               "has a side margin", "has no line-height of its own",
                                               "has no margin of its own", "the brand line")),
                      "control: %s's February email fails it on its <p>s, its bare links, its 11px credits, "
                      "its #888, its flags' side margins, its rows with no line height, its <p>s and headings "
                      "with no margin, and its brand line not being first in the panel" % base))

    print("8. the badge's colours, the small photos, and what the grade key says")
    # The badge is in the site's own grade colours: the tables newsletter.py
    # holds are what public/styles.css says (.grAp ... .grF, and the letter
    # colour rule under them), for every letter the grade curve can give.
    site = dc.site_grade_colours(os.path.join(ROOT, "public", "styles.css"))
    curve = sorted(set(picks.grade(x) for x in range(0, 101)))
    results.append(ok(newsletter.GRADE_FILL == {g: c[0] for g, c in site.items()}
                      and newsletter.GRADE_INK == {g: c[1] for g, c in site.items()}
                      and curve == sorted(site) and all(newsletter._grade(x) == picks.grade(x) for x in range(0, 101))
                      and [g for g in site if site[g][1] == "#ffffff"] == ["A+", "F"]
                      and site["A+"][0] == "#067a23" and all(site[g][1] == "#000000" for g in ("A", "B+", "B", "C", "D")),
                      "the badge's fills and letter colours are styles.css's for all %d letters (%s): A+ and F "
                      "white on the two darkest fills, the rest black" % (len(site), " ".join(
                          "%s %s/%s" % (g, site[g][0], site[g][1]) for g in ("A+", "A", "B+", "B", "C", "D", "F")))))
    # Every letter, on a payload the frozen months don't have (they grade A+ to C).
    d7 = copy.deepcopy(datas["USD"][2])
    for s_, val in zip(d7["picks"] + d7["gems"], (95, 88, 80, 70, 60, 45, 30, 93)):
        s_["value"] = val
    subj7, body7 = newsletter.render_digest(d7)
    seen = [(dc.norm(b.text()), b.style.get("background"), b.style.get("color")) for b in dc.Email(body7).badges]
    probs = dc.check(newsletter, picks, V["USD"], d7, subj7, body7) + dc.proofing(body7)
    results.append(ok(not probs and seen == [(g,) + site[g] for g in ("A+", "A", "B+", "B", "C", "D", "F", "A+")],
                      "a payload graded A+ A B+ B C D F A+ shows those eight badges in those colours%s"
                      % ("" if not probs else " -> %r" % probs[:3])))

    # The small photos. picks._banner makes the compact cards' copy from the
    # banner's own source: the same service and parameters, 220x168, twice
    # the 110x84 box the card shows it in.
    bn = picks._banner("thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/X y.jpg/1280px-X y.jpg", {"artist": "x"}, 1024, 420)
    tail = "&w=%d&h=%d&fit=cover&a=attention&output=jpg&q=80"
    src = "https://images.weserv.nl/?url=ssl%3Athumb.wikimedia.org%2Fwikipedia%2Fcommons%2Fthumb%2Fa%2Fab%2FX%20y.jpg%2F1280px-X%20y.jpg"
    card = newsletter._compact_card(datas["USD"][2]["picks"][1], 2)
    results.append(ok(bn == {"url": src + tail % (1024, 420), "thumb": src + tail % (220, 168), "credit": {"artist": "x"}}
                      and (picks.THUMB_W, picks.THUMB_H) == (220, 168) == (2 * 110, 2 * 84)
                      and "width='110'" in card and "width:110px;height:84px;" in card,
                      "picks._banner: the small copy is the banner's address with w=220&h=168 (the same service, "
                      "source, crop and quality), twice the 110x84 a compact card shows"))
    # Room for a compact card's words on a small phone: the panel's side
    # padding and the card's (newsletter.PANEL_PAD, CARD_PAD). At 14 and 10
    # the words beside the 110px photo have 184px on a 360px phone in the
    # Classic template, and the price line (about 176px) and a grade row
    # with two plus letters (about 166px) each fit on one line; at the 20
    # and 14 they were, both took two lines on every card (164px). A browser
    # measured that, not this test: it only stops either growing back
    # unnoticed, and the photo box changing size with them.
    pads = [(c, m) for c, m in cells
            if snap[c][m][1].count("background:#f4f5f6;padding:20px %dpx\">" % newsletter.PANEL_PAD) != 1
            or snap[c][m][1].count("<td valign=\"top\" style=\"padding:11px %dpx\">" % newsletter.CARD_PAD)
            != len(datas[c][int(m)]["picks"]) - 1]
    results.append(ok(not pads and newsletter.PANEL_PAD <= 14 and newsletter.CARD_PAD <= 10
                      and 360 - 16 - 2 * newsletter.PANEL_PAD - 2 - 110 - 2 * newsletter.CARD_PAD >= 184,
                      "the panel's side padding is %dpx and a compact card's words' %dpx in all %d renders, "
                      "which leaves those words 184px beside the 110px photo on a 360px phone in the Classic "
                      "template (8px page margin, 1px card border): room for the price line and a grade row "
                      "on one line each%s" % (newsletter.PANEL_PAD, newsletter.CARD_PAD, len(cells),
                                              "" if not pads else " -> %r" % pads[:3])))
    n_thumb = n_same = 0
    for c, m in cells:
        e = dc.Email(snap[c][m][1])
        P = datas[c][int(m)]["picks"]
        got = [x["src"] for x in e.images if x["kind"] == "thumb"]
        n_thumb += len(got)
        n_same += (got != [s_["photo_thumb"] for s_ in P[1:] if s_.get("photo")]
                   or any(s_["photo_thumb"] == s_["photo"] or "_220x168." not in s_["photo_thumb"]
                          for s_ in P if s_.get("photo"))
                   or [x["src"] for x in e.images if x["kind"] == "hero"] != [P[0]["photo"]] * bool(P[0].get("photo")))
    results.append(ok(n_thumb > 0 and not n_same,
                      "all %d renders: each compact card's photo is its pick's small copy (%d), the top card's "
                      "the 1024x420 banner" % (len(cells), n_thumb)))
    # A payload without the small copy (one built before Dec 2026, or a cover
    # that carries none) falls back to the banner on its compact cards.
    old = copy.deepcopy(datas["USD"][2])
    del old["picks"][1]["photo_thumb"]
    old["picks"][2]["photo_thumb"] = None
    subj_o, body_o = newsletter.render_digest(old)
    got = [x["src"] for x in dc.Email(body_o).images if x["kind"] == "thumb"]
    probs = dc.check(newsletter, picks, V["USD"], old, subj_o, body_o) + dc.proofing(body_o)
    results.append(ok(not probs and got == [old["picks"][1]["photo"], old["picks"][2]["photo"]]
                      + [s_["photo_thumb"] for s_ in old["picks"][3:]],
                      "a pick with no small copy shows the banner in its compact card; the others keep theirs%s"
                      % ("" if not probs else " -> %r" % probs[:3])))

    # The grade key (newsletter._grade_key). Each fact it states, held to the
    # scoring code and to every pick and gem of every frozen render.
    import inspect
    climate = picks._load("climate.json")
    every = [(c, int(m), s_) for c, m in cells for s_ in datas[c][int(m)]["picks"] + datas[c][int(m)]["gems"]]
    comps = lambda s_: [s_[k] for k in ("afford", "safe", "wx", "fly") if s_.get(k) is not None]
    off = [(c, m, s_["iso"]) for c, m, s_ in every
           if picks.clamp100(sum(comps(s_)) / float(len(comps(s_)))) != s_["value"]]
    results.append(ok(len(set(picks.WEIGHTS.values())) == 1 and sorted(picks.WEIGHTS) == ["afford", "fly", "safe", "wx"]
                      and not off and any(len(comps(s_)) == 3 for _c, _m, s_ in every),
                      "'the badge is the Overall grade, an equal mix of the others': picks.WEIGHTS are equal, and "
                      "every one of %d picks and gems has an Overall that is the plain mean of the grades it "
                      "has (some have three: no weather data)%s" % (len(every), "" if not off else " -> %r" % off[:3])))

    def afford(s_):
        price = picks.clamp100(((1.3 - s_["pl"]) / 0.95) * 100)
        move = picks.clamp100(50 + s_["fx"] * 6.25) if s_["fx"] is not None else 50
        return picks.clamp100(price * 0.7 + move * 0.3)
    off = [(c, m, s_["iso"]) for c, m, s_ in every
           if afford(s_) != s_["afford"]
           or s_["fx"] != pl.real_fx_pct(s_["fx_nominal"], s_["iso"], V[c].home_iso, ppp)]
    results.append(ok(not off and inspect.signature(rates.compute_favorability).parameters["baseline_days"].default == 365
                      and abs(rates.MAX_HISTORY_DAYS - 365) <= 7 and newsletter._span_words(rates.MAX_HISTORY_DAYS) == "1-year",
                      "'mostly local prices against {home}, partly whether your {money} goes further than usual "
                      "(against its 1-year average, after inflation)': every Affordability is 0.7 x the price "
                      "level's score + 0.3 x the currency move's, the move being pricelevel.real_fx_pct of the "
                      "nominal one, measured over %d days%s"
                      % (rates.MAX_HISTORY_DAYS, "" if not off else " -> %r" % off[:3])))
    off = [(c, m, s_["iso"], s_["advLvl"]) for c, m, s_ in every if s_["advLvl"] not in (1, 2)]
    named = [(c, m) for c, m in cells
             if ("is the %s advisory level (Level&nbsp;1&nbsp;=&nbsp;A, Level&nbsp;2&nbsp;=&nbsp;B) unless "
                 "another government is named." % picks.ADV_SRC_SHORT[V[c].adv_source]) not in snap[c][m][1]]
    results.append(ok(not off and not named and newsletter._FLAG == picks.SAFE_GRADE
                      and (picks.SAFE_GRADE[1], picks.SAFE_GRADE[2]) == ("A", "B"),
                      "'the {source} advisory level (Level 1 = A, Level 2 = B) unless another government "
                      "is named': every edition's key names its own main source (picks.ADV_SRC_SHORT of its "
                      "adv_source), and no pick or gem in any render is above Level 2%s"
                      % ("" if not (off or named) else " -> %r %r" % (off[:3], named[:3]))))
    wx = lambda iso, m: ((climate.get(iso) or {}).get("scores") or [None] * 12)[m - 1]
    off = [(c, m, s_["iso"]) for c, m, s_ in every
           if s_["wx"] != wx(s_["iso"], m) or (s_["fly"] is None) != (s_["fly_basis"] is None)
           or s_["fly_basis"] not in ("month", "distance", None)]
    bases = sorted(set(str(s_["fly_basis"]) for _c, _m, s_ in every))
    results.append(ok(not off and bases == ["distance", "month"],
                      "'{Month}’s usual weather' and 'the fare against the usual for that route or distance': "
                      "every weather grade is climate.json's score for the issue's month, and every fare grade "
                      "is on one of the two bases (%s)%s"
                      % (", ".join(bases), "" if not off else " -> %r" % off[:3])))
    # "(~ = estimated)". A route with no cached fare is counted as a typical
    # fare for its distance: picks gives it a fixed 70 on the distance basis
    # and sets fareEst. Each such card shows "~" before its Flights letter,
    # as the site does, and no other card does; a top card says "(estimated,
    # no fare yet)" where the others name the fare they compared. (Until
    # this check the letter stood bare and the key called it a fare
    # comparison: 17 of the 96 USD cards, 78 of CNY's 96.)
    est = [(c, m, s_) for c, m, s_ in every if s_.get("fareEst")]
    off = [(c, m, s_["iso"]) for c, m, s_ in est if s_["fly"] != 70 or s_["fly_basis"] != "distance"]
    count = lambda c, m: sum(1 for s_ in datas[c][int(m)]["picks"] + datas[c][int(m)]["gems"] if s_.get("fareEst"))
    marks = [(c, m) for c, m in cells
             if snap[c][m][1].count("<b>~") != count(c, m) or snap[c][m][1].count("~B</b>") != count(c, m)
             or snap[c][m][1].count("for that route or distance (~&nbsp;=&nbsp;estimated).</div>") != 1]
    est_tops = [(c, m) for c, m in cells if datas[c][int(m)]["picks"][0].get("fareEst")]
    tops = [(c, m) for c, m in cells
            if snap[c][m][1].count("(estimated, no fare yet)") != ((c, m) in est_tops)
            or ("year-round, for the distance" in snap[c][m][1]) != (
                (c, m) not in est_tops and datas[c][int(m)]["picks"][0].get("fly_basis") == "distance")]
    n_usd = sum(1 for c, _m, _s in est if c == "USD")
    results.append(ok(est and est_tops and n_usd and not (off or marks or tops),
                      "'(~ = estimated)': every card whose fare is an estimate (%d of %d, %d of them in the USD "
                      "edition; each a fixed 70 on the distance basis) shows '~B', no other card shows a '~' "
                      "letter, and a top card with one (%d) reads '(estimated, no fare yet)', never "
                      "'year-round, for the distance'%s"
                      % (len(est), len(every), n_usd, len(est_tops),
                         "" if not (off or marks or tops) else " -> %r %r %r" % (off[:3], marks[:3], tops[:3]))))
    key = piece(re.search(r"<b>Reading the grades:</b>.*?</div>", snap["USD"]["2"][1]))
    words = [w for w in re.sub(r"<[^>]+>", " ", key.replace("&nbsp;", " ")).split() if re.search(r"[A-Za-z0-9]", w)]
    results.append(ok(40 < len(words) <= 70, "the grade key is one short paragraph (%d words in the USD edition)" % len(words)))

    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
