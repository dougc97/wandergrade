#!/usr/bin/env python3
"""The digest's home-currency editions, rendered offline from frozen inputs
(scripts/digest_snapshot.py; nothing leaves this machine):

  1. USD is byte-for-byte what 4788fd2 renders, but for one deliberate
     change: the cost line now uses the site's ±10% "about the same" band on
     the two printed decimals (newsletter._pl_band). The 12 months' sha256
     match scripts/digest_golden/usd_sha256.json, and the USD edition built
     the per-currency way (gather + build_variant) is the same text. The
     band is checked against JavaScript's own toFixed under jsc.
  2. Each of the ten editions, every month: its own subject, wording, footer,
     banknote, no home country in its picks, balanced markup, and FX measured
     in its own currency.
  3. pricelevel.real_fx_pct's home-side guard (high inflation at home that
     can't be dated: no direction), with the US unaffected.

    /usr/bin/python3 scripts/test_digest_variants.py [--against <rev>]

--against <rev> also extracts that tree with `git archive` and diffs its USD
text against this tree's in full, then again with only this tree's cost line
grafted into it (digest_snapshot --graft-cost-line): that must be identical
for all 12 months, which proves the cost line is the only USD change.
"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import digest_snapshot as ds  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
GOLDEN = os.path.join(HERE, "digest_golden", "usd_sha256.json")


JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def _snapshot_in_child(root, variants="USD", graft=None):
    """A tree's snapshot in a fresh interpreter (module isolation)."""
    out = tempfile.mktemp(suffix=".json")
    p = subprocess.run([sys.executable, os.path.join(HERE, "digest_snapshot.py"), "--root", root,
                        "--out", out, "--variants", variants]
                       + (["--graft-cost-line", graft] if graft else []),
                       capture_output=True, text=True, timeout=55)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)
    with open(out, encoding="utf-8") as f:
        snap = json.load(f)
    os.unlink(out)
    return snap


def main():
    results = []
    against = sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv else None
    raw_diff = None

    print("1. USD byte-identity")
    usd_only = _snapshot_in_child(ROOT, "USD")
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)["sha256"]
    mine = ds.digest_hashes(usd_only)["USD"]
    bad = [m for m in golden if golden[m] != mine.get(m)]
    results.append(ok(len(golden) == 12 and not bad,
                      "12 months match the golden hashes (4788fd2's text + the cost band)%s"
                      % (" (differ: %s)" % bad if bad else "")))
    if against:
        tmp = tempfile.mkdtemp(prefix="digest-old-")
        try:
            subprocess.check_call("git -C '%s' archive '%s' fxtracker public | tar -x -C '%s'"
                                  % (ROOT, against, tmp), shell=True, timeout=50)
            old = _snapshot_in_child(tmp, "USD")
            diffs = [m for m in old["USD"] if old["USD"][m] != usd_only["USD"].get(m)]
            raw_diff = sorted(int(m) for m in diffs)          # checked in 2c
            grafted = _snapshot_in_child(tmp, "USD", graft=ROOT)
            gdiffs = [m for m in grafted["USD"] if grafted["USD"][m] != usd_only["USD"].get(m)]
            results.append(ok(not gdiffs and len(grafted["USD"]) == 12,
                              "%s with only this tree's cost line grafted in renders this tree's USD "
                              "text for all 12 months (the cost band is the only USD change)%s"
                              % (against, gdiffs or "")))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    picks, newsletter, dv = ds.install(ROOT)
    snap, datas = ds.snapshot(ROOT, tuple(dv.PICKER_ORDER), keep_data=True)
    results.append(ok(snap["USD"] == usd_only["USD"],
                      "the USD edition built per-currency (gather + build_variant) is the same text"))

    print("2. the ten editions x 12 months")
    V = dv.VARIANTS
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
    results.append(ok(not problems, "subjects unique per month; wording, footer, emoji, home exclusion, "
                      "markup all right (%d renders)%s" % (12 * len(V), "" if not problems else
                                                             " -> %r" % problems[:4])))
    # Wording samples from the spec.
    eur1 = snap["EUR"]["1"]
    results.append(ok(eur1[0] == "\U0001f9ed Where your euro goes furthest this January"
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
    inr_hero = [datas["INR"][m]["picks"][0] for m in range(1, 13)]
    inr_lines = [newsletter._cost_line(h, False, V["INR"]) for h in inr_hero]
    results.append(ok(not worth and any("pricier than India.</div>" in x for x in inr_lines),
                      "non-USD 'pricier than …, but graded worth it' only at B or better (INR heroes: "
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

    print("2c. the cost line's band (the one deliberate USD change)")
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
    if raw_diff is not None:
        # Where a cost line is printed: always on the hero, on a compact card
        # only when it has no FX line, never on a gem line.
        def prints_cost(i, s_):
            return i == 0 or not newsletter._fx_line(s_, True, U)
        expect = sorted(m for m in range(1, 13)
                        if any(s_["iso"] in moved and prints_cost(i, s_)
                               for i, s_ in enumerate(usd_d[m]["picks"])))
        results.append(ok(raw_diff == expect,
                          "%s's raw USD text differs exactly in the months a pick changes band: %s"
                          % (against, raw_diff or "none")))

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

    print("\n%d/%d passed" % (sum(1 for r in results if r), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
