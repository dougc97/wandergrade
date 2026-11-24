"""/data's worked examples come from the download itself (server._data_example),
offline: no network.

    /usr/bin/python3 scripts/test_data_page.py

The page said "Vietnam 0.28 / Germany 0.81 = 0.35, about a third" and "Vietnam
sits near US$360", typed in by hand, and the download moved under them
(Germany 0.78 once prices went on household spending). What it holds:
  * the example's two price levels are the CSV's Vietnam and Germany rows to
    two decimals, its ratio is those two divided, and its words are that
    ratio's nearest plain fraction (_fraction_words);
  * the "US$100 buys" sentence is the CSV's Vietnam usd100_buys to the
    nearest US$10;
  * with no dataset (rates down, no copy) the page still renders: no
    numbers, no "Vietnam sits near", no placeholder left.
"""
import csv, io, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import server  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or bool(c)
results = []

PPP = json.load(open(os.path.join(ROOT, "public", "ppp.json"), encoding="utf-8"))
RATES = json.load(open(os.path.join(ROOT, "scripts", "fixtures", "strength", "rates_2026-10-23.json"),
                       encoding="utf-8"))

# ---- the words ------------------------------------------------------------------
fw = server._fraction_words
results.append(ok(fw(0.36) == "about a third of" and fw(0.35) == "about a third of" and fw(0.27) == "about a quarter of"
                  and fw(0.5) == "about half" and fw(0.41) == "about two fifths of" and fw(0.12) == "about a tenth of"
                  and fw(0.97) == "about the same as" and fw(1.6) == "about 1.6 times",
                  "_fraction_words: the nearest plain fraction (0.36 a third, 0.27 a quarter, 0.5 half, 0.97 the same "
                  "as), and \"1.6 times\" above 1.1"))

# ---- the page against the CSV it serves -----------------------------------------
saved = (server.build_dataset.rates.compute_favorability, dict(server._ppp_cache), dict(server._dataset_cache))
server.build_dataset.rates.compute_favorability = lambda: {"as_of": RATES.get("as_of"), "rows": RATES["rows"]}
server._ppp_cache.update(at=time.time(), data=PPP)          # no background World Bank refresh
try:
    server._dataset_cache.update(at=0, payload=None, csv=None, retry_at=0, error="")
    body = server._data_page_body()
    served_csv = server._dataset()["csv"]
    server._dataset_cache.update(at=0, payload=None, csv=None, retry_at=time.time() + 600, error="rates down")
    down = server._data_page_body()
finally:
    server.build_dataset.rates.compute_favorability = saved[0]
    server._ppp_cache.clear()
    server._ppp_cache.update(saved[1])
    server._dataset_cache.clear()
    server._dataset_cache.update(saved[2])

rows = {r["iso"]: r for r in csv.DictReader(io.StringIO(served_csv))}
vn, de = rows["VN"], rows["DE"]
want_a, want_b = "%.2f" % float(vn["price_level"]), "%.2f" % float(de["price_level"])
want_r = "%.2f" % (float(want_a) / float(want_b))
m = re.search(r"Vietnam (\d\.\d\d) &divide; Germany (\d\.\d\d) &asymp; (\d\.\d\d), so prices are ([a-z0-9. ]+) "
              r"Germany's\.", body)
results.append(ok(bool(m) and m.groups()[:3] == (want_a, want_b, want_r),
                  "the worked example is the CSV's own figures: Vietnam %s / Germany %s = %s (page: %s)"
                  % (want_a, want_b, want_r, m.groups()[:3] if m else "no example")))
results.append(ok(bool(m) and m.group(4) == fw(float(want_r)),
                  "its words follow the ratio: \"%s\"" % (m.group(4) if m else "")))
results.append(ok("0.81" not in body or de["price_level"].startswith("0.81"),
                  "the old typed-in Germany 0.81 is gone (the CSV says %s)" % de["price_level"]))
buys = server.picks.js_round(float(vn["usd100_buys"]) / 10.0) * 10
results.append(ok(" Vietnam sits near US$%d.</li>" % buys in body,
                  "US$100 buys: Vietnam near US$%d, the CSV's %s to the nearest US$10" % (buys, vn["usd100_buys"])))
results.append(ok("__" not in body and "__" not in down, "no placeholder is left on the page, with or without the data"))
results.append(ok("Vietnam's &divide; Germany's is Vietnam's prices as a share of Germany's." in down
                  and "sits near" not in down and not re.search(r"Germany \d", down),
                  "with no dataset the example uses no numbers and the US$100 sentence is left out"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
