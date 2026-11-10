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
     in its own currency; the 2026-11 wording, each piece naming the month.
  3. pricelevel.real_fx_pct's home-side guard (high inflation at home that
     can't be dated: no direction), with the US unaffected.
  6. Every email says what its payload says (scripts/digest_check.py): each
     visible line, link, image and photo credit, every edition and month,
     is the one worked out from the payload, and the checks report each of
     a list of deliberate faults.
  7. Buttondown, the sender, can't restyle it (digest_check.proofing): the
     intro is the only <p>, every link's words sit in two spans with the
     colour on the inner one, nothing is under 12px but the hidden
     preheader, no #888 is left, and every block of text has its own colour
     and font-size.

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
                got = {"url": s_["photo"], "credit": s_["photo_credit"]} if s_.get("photo") else None
                if got != want or (not want and s_.get("photo_credit")):
                    wrong.append((c, m, s_["iso"], got, want))
                n_cov += bool(want)
                n_none += not want
            wrong += [(c, m, s_["iso"], "a gem with a cover") for s_ in datas[c][m]["gems"]
                      if s_.get("photo") or s_.get("photo_credit")]
    results.append(ok(not wrong and n_cov > 0,
                      "every edition's covers and credits, all 12 months, are the rule's picks under the fakes "
                      "(%d covers, %d picks the fakes give none)%s"
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
        if (not b or b[0] != snap[c][m][0] or any(s_.get("photo") or s_.get("photo_credit") for s_ in d["picks"])
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
    line = newsletter._gem_line(dict(datas["USD"][1]["gems"][0], advBy=by["CI"]), 1)
    results.append(ok(by == {"TH": "US State Dept", "CI": "Global Affairs Canada", "PS": "German Foreign Office"}
                      and "per Global Affairs Canada</span>" in line,
                      "a 🛡️ grade names the government whose level it is, the gap-filler where one filled it (%s)" % by))

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
            if ("goes about" in body and "%s After inflation, your %s goes about" % (v.fx_emoji, v.noun)
                    not in body):
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
    # Every edition's issue names its month's next occurrence (render_cheapest.year_for,
    # the /cheapest page's own year) and the quote for that year; 4788fd2 printed
    # the default month's year for an explicit month (January 2026 on 2026-10-03).
    import fxtracker.render_cheapest as RCH
    for c in V:
        for m in range(1, 13):
            y = RCH.year_for(m, ds.TODAY)
            body = snap[c][str(m)][1]
            if "<b>%s %d</b>" % (picks.MONTHS[m - 1], y) not in body or newsletter._quote_for(y, m) not in body:
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
                "</b>. %s’s standouts \U0001f447</p>" % mn in body,
                ("\U0001f4c5 <b>%s</b> picks, sent two months ahead so there’s time to plan and book. "
                 "Going a different time? <a href=" % mn) in body,
                body.count(" vs the route’s usual)") == month_fare
                and (not month_fare or "(%s vs the route’s usual)" % mn in body),
                "this month" not in body.lower() and "sweet spot" not in body,
            ]
            if not all(want):
                worded.append((c, m, want))
    results.append(ok(not worded and n_basis > 0,
                      "the 2026-11 wording in all %d renders: subject '{Month} trips: where your {noun} goes "
                      "furthest', preheader 'Plan ahead: …' naming the month (FX-strong and plain forms), "
                      "'{Month}’s standouts', the 📅 sentence, the hero fare '({Month} vs the route’s usual)' "
                      "(%d heroes), no 'this month' or 'sweet spot' left%s"
                      % (12 * len(V), n_basis, "" if not worded else " -> %r" % worded[:3])))
    # Wording samples from the spec.
    eur1 = snap["EUR"]["1"]
    results.append(ok(eur1[0] == "\U0001f9ed January trips: where your euro goes furthest"
                      and "below German levels." in eur1[1]
                      and "Grades are for a traveler from Germany (paying in euros) planning January travel;"
                      in eur1[1], "EUR: spec's subject, 'below German levels', footer"))
    results.append(ok("your Canadian dollar is unusually strong" in snap["CAD"]["1"][1]
                      and "\U0001f4b4" in "".join(b for _, b in snap["JPY"].values()),
                      "CAD intro names the Canadian dollar; JPY uses the yen banknote"))

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
    worth = []
    for c in V:
        for m in range(1, 13):
            d = datas[c][m]
            for s_ in d["picks"]:
                line = newsletter._cost_line(s_, False, V[c])
                if "graded worth it" in line and c != "USD" and s_["value"] < 68:
                    worth.append((c, m, s_["iso"], s_["value"]))
    # Since the default priorities went even (2026-10-14) every INR hero
    # grades B or better on these fixtures, so the plain wording is looked
    # for among all INR picks (Philippines 67 in January, Greece 67 in April).
    inr_picks = [s_ for m in range(1, 13) for s_ in datas["INR"][m]["picks"]]
    inr_lines = [newsletter._cost_line(s_, False, V["INR"]) for s_ in inr_picks]
    results.append(ok(not worth and any("pricier than India.</div>" in x for x in inr_lines),
                      "non-USD 'pricier than …, but graded worth it' only at B or better (INR picks below B: "
                      "'Everyday pricier than India.')%s" % ("" if not worth else " -> %r" % worth[:3])))
    U, INR = V["USD"], V["INR"]
    cl = newsletter._cost_line
    results.append(ok("pricier than the US, but graded worth it" in cl({"pl": 1.5, "value": 40}, False, U)
                      and "pricier than India, but graded worth it" in cl({"pl": 1.5, "value": 68}, False, INR)
                      and "pricier than India.</div>" in cl({"pl": 1.5, "value": 67}, False, INR)
                      and "Pricier than India</div>" in cl({"pl": 1.5, "value": 55}, True, INR),
                      "USD keeps 'but graded worth it' at any grade; INR drops it below 68 (hero and compact)"))
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
    ex = {0.93: "prices about on par with the US", 0.904: "prices run about 10% below US levels",
          0.95: "prices about on par with the US", 1.104: "prices about on par with the US",
          1.105: "prices about on par with the US", 1.106: "pricier than the US, but graded worth it",
          0.6: "prices run about 40% below US levels"}
    got = {x: cl({"pl": x, "value": 80}) for x in ex}
    results.append(ok(all("Everyday %s." % ex[x] in got[x] for x in ex),
                      "edges: 0.93 and 0.95 on par (were '7%'/'5% below'), 0.904 '10% below', "
                      "1.104/1.105 on par (1.104 was 'pricier'), 1.106 pricier"))
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
    said, n = [], {"lines": 0, "links": 0, "images": 0, "credits": 0}
    for c, m in cells:
        subj, body = snap[c][m]
        probs = dc.check(newsletter, picks, V[c], datas[c][int(m)], subj, body)
        if probs:
            said.append((c, m, probs[:2]))
        want = dc.expected(newsletter, picks, V[c], datas[c][int(m)])
        for k in n:
            n[k] += len(want[k])
    results.append(ok(not said and n["credits"] == n_cov,
                      "all %d renders: every visible line (%d), every link's address, words, colour and "
                      "underline (%d), every image's address, alt text and the guide it links to (%d) and "
                      "every photo credit's country, photographer, file page, licence and licence link (%d, "
                      "one for each card with a photo, in card order) are the payload's; the credits sit "
                      "right under the quote and above the footer's border; the small print is <div>s at "
                      "their own sizes%s"
                      % (len(cells), n["lines"], n["links"], n["images"], n["credits"],
                         "" if not said else " -> %r" % said[:3])))
    # Credits the frozen months don't have: a top card with no photo (no
    # entry, and the others keep their order), a licence with no link (plain
    # text), and a photographer's name with markup in it (printed as given,
    # escaped, never tidied).
    d = copy.deepcopy(datas["USD"][2])
    P = d["picks"]
    odd = 'Ana "Nia" <b>O\u2019Neil</b> & S\u00f8n, Jr. \u00b7 flickr'
    P[0]["photo"] = P[0]["photo_credit"] = None
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
    # The controls: each deliberate fault below must be reported, or the two
    # checks above prove nothing.
    subj, body = snap["USD"]["2"]
    d, v = datas["USD"][2], V["USD"]
    a1, a2 = (cr(s_) for s_ in d["picks"][:2])
    swap = lambda x, y: body.replace(x, "\0").replace(y, x).replace("\0", y)
    faults = [
        ("a word added to a card", "check", body.replace("See the guide \u2192", "See the guide now \u2192", 1)),
        ("a grade letter changed", "check", re.sub(r"(\u2014 Overall )(A\+|A|B\+|B|C|D|F)<",
                                                   lambda mm: mm.group(1) + ("B<" if mm.group(2) != "B" else "C<"), body, 1)),
        ("two photographers swapped", "check", swap(">%s<" % a1["artist"], ">%s<" % a2["artist"])),
        ("a credit linked to another photo's page", "check", swap(a1["page"], a2["page"])),
        ("a credit dropped", "check", re.sub(r"(Wikimedia Commons\. ).*?&middot; ", r"\1", body, 1)),
        ("a cover swapped for another's", "check", swap(d["picks"][0]["photo"], d["picks"][1]["photo"])),
        ("a guide link pointing at another country", "check",
         body.replace("gc=%s&" % d["picks"][0]["iso"], "gc=%s&" % d["picks"][1]["iso"], 1)),
        ("a green link turned blue", "check", body.replace('<span style="color:#0a7d28">', '<span style="color:#0069FF">', 1)),
        ("the credits moved under the footer", "check",
         (lambda mm: body.replace(mm.group(0), "").replace("\n</div>", mm.group(0) + "\n</div>"))(
             re.search(r'<div style="[^"]*">Photos \(cropped\).*?</div>', body))),
        ("the credits tucked inside the quote block", "check",
         (lambda mm: body.replace(mm.group(0), "").replace("</i></div></div>", "</i></div>" + mm.group(0) + "</div>"))(
             re.search(r'<div style="[^"]*">Photos \(cropped\).*?</div>', body))),
        ("the footer back in a <p>", "both", re.sub(r'<div (style="[^"]*border-top[^"]*">Grades are for.*?)</div>',
                                                    r"<p \1</p>", body, 1)),
        ("a link's words out of their spans", "proofing",
         body.replace('<span><span style="color:#666;text-decoration:underline">unsubscribe</span></span>', "unsubscribe")),
        ("11px small print", "both", body.replace("font-size:12px", "font-size:11px", 1)),
        ("a #888 left", "proofing", body.replace("color:#666", "color:#888", 1)),
        ("a block with no colour of its own", "both", body.replace(";color:#444;margin:16px 0 0\">", ";margin:16px 0 0\">", 1)),
        ("a block with no font-size of its own", "both", body.replace("font-size:14px;line-height:21px;color:#444;", "line-height:21px;color:#444;", 1)),
        ("a <div> never closed", "both", body[::-1].replace(">vid/<", "", 1)[::-1]),
    ]
    missed = []
    for name, by, mutant in faults:
        found = {"check": bool(dc.check(newsletter, picks, v, d, subj, mutant)), "proofing": bool(dc.proofing(mutant))}
        if mutant == body or not all(found[k] for k in (("check", "proofing") if by == "both" else (by,))):
            missed.append((name, found, mutant == body))
    results.append(ok(not missed and not dc.check(newsletter, picks, v, d, subj, body) and not dc.proofing(body),
                      "controls: each of %d deliberate faults is reported (%s)%s"
                      % (len(faults), "; ".join(f[0] for f in faults), "" if not missed else " -> MISSED %r" % missed)))

    print("7. Buttondown can't restyle it (digest_check.proofing)")
    unproof = [(c, m, dc.proofing(snap[c][m][1])[:2]) for c, m in cells if dc.proofing(snap[c][m][1])]
    results.append(ok(not unproof,
                      "all %d renders: the intro is the only <p> (and no list markup); every link's words sit in "
                      "two spans with a colour on the inner one and text-decoration:none on the <a>; no "
                      "font-size under %dpx but the hidden preheader's; no #888; every block that shows words "
                      "has its own colour and its own font-size; the markup nests%s"
                      % (len(cells), dc.MIN_PX, "" if not unproof else " -> %r" % unproof[:3])))
    # A control: the email as it was before the redesign fails this, in the
    # ways the delivered Nov 1 2026 issue showed (blue links, 16px small
    # print, 11px credits, #888).
    was = " | ".join(dc.proofing(old_snap["USD"]["2"][1]))
    results.append(ok(all(x in was for x in ("<p> (the intro is the only one allowed)", "two spans",
                                               "font-size 11px", "#888 is still in the body")),
                      "control: %s's February email fails it on its <p>s, its bare links, its 11px credits "
                      "and its #888" % base))

    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
