#!/usr/bin/env python3
"""The digest's home-currency editions, rendered offline from frozen inputs
(scripts/digest_snapshot.py; nothing leaves this machine):

  1. USD is byte-for-byte what 4788fd2 renders: the 12 months' sha256 match
     scripts/digest_golden/usd_sha256.json, and the USD edition built the
     per-currency way (gather + build_variant) is the same text.
  2. Each of the ten editions, every month: its own subject, wording, footer,
     banknote, no home country in its picks, balanced markup, and FX measured
     in its own currency.
  3. pricelevel.real_fx_pct's home-side guard (high inflation at home that
     can't be dated: no direction), with the US unaffected.

    /usr/bin/python3 scripts/test_digest_variants.py [--against <rev>]

--against <rev> also extracts that tree with `git archive` and diffs its USD
text against this tree's in full (default: hashes only).
"""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import digest_snapshot as ds  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
GOLDEN = os.path.join(HERE, "digest_golden", "usd_sha256.json")


def _snapshot_in_child(root, variants="USD"):
    """A tree's snapshot in a fresh interpreter (module isolation)."""
    out = tempfile.mktemp(suffix=".json")
    p = subprocess.run([sys.executable, os.path.join(HERE, "digest_snapshot.py"), "--root", root,
                        "--out", out, "--variants", variants], capture_output=True, text=True, timeout=55)
    if p.returncode != 0:
        raise RuntimeError(p.stdout + p.stderr)
    with open(out, encoding="utf-8") as f:
        snap = json.load(f)
    os.unlink(out)
    return snap


def main():
    results = []
    against = sys.argv[sys.argv.index("--against") + 1] if "--against" in sys.argv else None

    print("1. USD byte-identity")
    usd_only = _snapshot_in_child(ROOT, "USD")
    with open(GOLDEN, encoding="utf-8") as f:
        golden = json.load(f)["sha256"]
    mine = ds.digest_hashes(usd_only)["USD"]
    bad = [m for m in golden if golden[m] != mine.get(m)]
    results.append(ok(len(golden) == 12 and not bad,
                      "12 months match the 4788fd2 golden hashes%s" % (" (differ: %s)" % bad if bad else "")))
    if against:
        tmp = tempfile.mkdtemp(prefix="digest-old-")
        try:
            subprocess.check_call("git -C '%s' archive '%s' fxtracker public | tar -x -C '%s'"
                                  % (ROOT, against, tmp), shell=True, timeout=50)
            old = _snapshot_in_child(tmp, "USD")
            diffs = [m for m in old["USD"] if old["USD"][m] != usd_only["USD"].get(m)]
            results.append(ok(not diffs and len(old["USD"]) == 12,
                              "full text equals %s's for all 12 months%s" % (against, diffs or "")))
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
