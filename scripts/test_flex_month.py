"""Top Picks' "Any time" (the flexible month): the pure pieces of
public/app.js, cut out of the file by name and run under jsc.

  flexWindow        the next six months, starting next month once fewer than
                    10 days of this one remain (flightvalue.partial_month)
  travelMonth       a real month for every other reader: "0" is the window's
                    first, never parseInt("0") || curMonth()
  bestOfWindow      a country's best month: value, or comfort then value in
                    Best weather; a tie keeps the sooner month
  cheapestFareMonth the gated cheapest-flight month: banded routes only,
                    window keys only, the sooner month on an equal fare

    /usr/bin/python3 scripts/test_flex_month.py
"""
import calendar, datetime, json, os, re, subprocess, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import flightvalue   # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
APP = open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8").read()
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"


def js_fn(name):
    m = re.search(r"^function %s\(.*?^\}" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def js_const(name):   # `const name = …;` up to the statement's line-ending ";"
    m = re.search(r"^const %s = .*?;$" % name, APP, re.M | re.S)
    return m.group(0) if m else ""


def jsc(prog):
    try:
        return json.loads(subprocess.run([JSC, "-e", prog], capture_output=True, text=True, timeout=30).stdout)
    except Exception:
        return None


PIECES = "\n".join([js_const("MON_ABBR"), js_const("FLEX_MONTHS"), js_fn("flexWindow"), js_fn("flexSpan"),
                    js_fn("bestOfWindow"), js_fn("cheapestFareMonth")])
results.append(ok(all(x in PIECES for x in ("function flexWindow", "function bestOfWindow", "function cheapestFareMonth",
                                            "FLEX_PARTIAL_DAYS = 10", "function flexSpan")),
                  "flexWindow, bestOfWindow, cheapestFareMonth and FLEX_MONTHS found in app.js"))

# --- flexWindow ----------------------------------------------------------------
# The browser's local date; months are 1-12. Oct 22 has 10 days left counting
# today (keeps October); Oct 23 has 9 (starts November). Feb 20 has 10 left in
# a leap year (29 days) and 9 in a common one.
CASES = [((2026, 10, 1), [10, 11, 12, 1, 2, 3]), ((2026, 10, 22), [10, 11, 12, 1, 2, 3]),
         ((2026, 10, 23), [11, 12, 1, 2, 3, 4]), ((2028, 2, 20), [2, 3, 4, 5, 6, 7]),
         ((2027, 2, 20), [3, 4, 5, 6, 7, 8]), ((2026, 12, 25), [1, 2, 3, 4, 5, 6]),
         ((2026, 12, 1), [12, 1, 2, 3, 4, 5]), ((2026, 10, 31), [11, 12, 1, 2, 3, 4])]
got = jsc("%s\nprint(JSON.stringify(%s.map((d) => flexWindow(new Date(d[0], d[1] - 1, d[2])))));"
          % (PIECES, json.dumps([c[0] for c in CASES])))
for (d, want), g in zip(CASES, got or [None] * len(CASES)):
    results.append(ok(g == want, "flexWindow %04d-%02d-%02d -> %s (got %s)" % (d + (want, g))))
# The same cut-over as the server's partial month (flightvalue.partial_month):
# the window skips exactly the month the server calls partial.
agree = True
for y, m in ((2026, 2), (2028, 2), (2026, 4), (2026, 10), (2026, 12)):
    days = calendar.monthrange(y, m)[1]
    ds = [(y, m, d) for d in range(1, days + 1)]
    win = jsc("%s\nprint(JSON.stringify(%s.map((d) => flexWindow(new Date(d[0], d[1] - 1, d[2]))[0])));" % (PIECES, json.dumps(ds)))
    for (yy, mm, dd), first in zip(ds, win or []):
        partial = flightvalue.partial_month(datetime.date(yy, mm, dd)) is not None
        agree = agree and first == (mm % 12 + 1 if partial else mm)
    agree = agree and win is not None and len(win) == days
results.append(ok(agree, "flexWindow starts next month on exactly the days flightvalue.partial_month() calls this one partial"))
results.append(ok(jsc("%s\nprint(JSON.stringify([flexSpan([10,11,12,1,2,3]), flexSpan([2,3,4,5,6,7])]));" % PIECES)
                  == ["Oct–Mar", "Feb–Jul"], "flexSpan names the window: Oct–Mar, Feb–Jul"))

# --- travelMonth -----------------------------------------------------------------
# Every reader outside Top Picks' flexible branch gets a real month: "0" is the
# window's first month (not curMonth(), which parseInt("0") || curMonth() gave
# even after the 22nd), 1-12 is itself, an empty select is this month.
# A window that doesn't start this month (as on Oct 23), so the old reading
# would show: stubbed, with the select and the clock.
TM = js_fn("travelMonth")
prog = ("%s\nfunction flexWindow() { return [11, 12, 1, 2, 3, 4]; }\nlet SEL = null; const $ = () => SEL; const curMonth = () => 10;\n"
        "const out = []; for (const v of ['0', '11', '3', '', null]) { SEL = v === null ? null : { value: v }; out.push(travelMonth()); }\n"
        "print(JSON.stringify(out));" % TM)
got = jsc(prog)
results.append(ok(bool(TM) and got == [11, 11, 3, 10, 10],
                  "travelMonth on Oct 23: '0' -> 11 (the window's first), '11' -> 11, '3' -> 3, no value / no select -> 10 (got %s)" % got))

# --- bestOfWindow ----------------------------------------------------------------
WIN = [10, 11, 12, 1, 2, 3]
S = lambda value, wx: {"value": value, "wx": wx}
BY = {"10": S(80, 70), "11": S(84, 60), "12": S(84, 90), "1": S(84, 90), "2": S(70, 95), "3": S(83, 95)}
prog = ("%s\nconst by = %s, win = %s;\nprint(JSON.stringify([bestOfWindow(by, win, 'value').month, bestOfWindow(by, win, 'wx').month,"
        " bestOfWindow({}, win, 'value'), bestOfWindow({ '1': %s, '12': %s }, win, 'value').month,"
        " bestOfWindow({ '10': %s, '11': %s }, win, 'wx').month, bestOfWindow({ '10': %s, '11': %s }, win, 'wx').month]));"
        % (PIECES, json.dumps(BY), json.dumps(WIN), json.dumps(S(84, 1)), json.dumps(S(84, 1)),
           json.dumps(S(80, None)), json.dumps(S(90, None)), json.dumps(S(80, None)), json.dumps(S(70, 50))))
got = jsc(prog)
results.append(ok(got and got[0] == 11, "bestOfWindow by value: 84 in Nov, Dec and Jan -> Nov, the sooner (got %s)" % (got and got[0])))
results.append(ok(got and got[1] == 3, "bestOfWindow by weather: 95 in Feb and Mar -> Mar on value 83 > 70 (got %s)" % (got and got[1])))
results.append(ok(got and got[2] is None, "bestOfWindow with no scores -> null"))
results.append(ok(got and got[3] == 12, "bestOfWindow keeps window order, not calendar order: Dec before Jan on a tie (got %s)" % (got and got[3])))
results.append(ok(got and got[4] == 11, "bestOfWindow by weather with no comfort data falls back to value (got %s)" % (got and got[4])))
results.append(ok(got and got[5] == 11, "bestOfWindow by weather: a month with comfort beats one without (got %s)" % (got and got[5])))

# --- cheapestFareMonth --------------------------------------------------------------
KEYS = ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
BANDED = {"curve": {"2026-10": [610, "BKK"], "2026-11": [540, "BKK"], "2026-12": [700, "HKT"],
                    "2027-01": [540, "BKK"], "2027-05": [300, "BKK"], "2027-07": [310, "BKK"]},
          "median": 560, "lo": 530, "hi": 640, "n_months": 6}
UNBANDED = {"curve": {"2026-11": [200, "CUN"], "2026-12": [210, "CUN"]}, "n_months": 2}
prog = ("%s\nconst keys = %s;\nprint(JSON.stringify([cheapestFareMonth(%s, keys), cheapestFareMonth(%s, keys),"
        " cheapestFareMonth({ curve: {}, median: 500 }, keys), cheapestFareMonth(null, keys), cheapestFareMonth({ pending: true }, keys),"
        " cheapestFareMonth(%s, ['2027-02', '2027-03'])]));"
        % (PIECES, json.dumps(KEYS), json.dumps(BANDED), json.dumps(UNBANDED), json.dumps(BANDED)))
got = jsc(prog)
results.append(ok(got and got[0] == {"key": "2026-11", "month": 11, "price": 540, "city": "BKK"},
                  "cheapestFareMonth: Nov and Jan both 540 -> Nov, the sooner; May's 300 is outside the window (got %s)" % (got and got[0])))
results.append(ok(got and got[1] is None, "cheapestFareMonth: none on an unbanded route (2 months, no median), however cheap"))
results.append(ok(got and got[2] is None and got[3] is None and got[4] is None,
                  "cheapestFareMonth: none for an empty curve, no country, or a pending one"))
results.append(ok(got and got[5] is None, "cheapestFareMonth: none when the window holds no fare of the route's"))

n = sum(1 for r in results if r)
print("\n%d/%d passed" % (n, len(results)))
sys.exit(0 if n == len(results) else 1)
