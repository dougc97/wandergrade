"""Carnival's months in public/activities.json follow Easter, which the data
can't: Carnival ends on Shrove Tuesday, 47 days before Easter Sunday. In
2027-2029 that falls in February (2027: 9 Feb); in 2030 it moves to 5 March.
The site has no Easter calculator (not worth one until then), so this test
fails the year the next Carnival leaves the months the data names.

    /usr/bin/python3 scripts/test_carnival_months.py

What it holds the data to:
  * every Carnival item (BR TT AW CW) ends in the month of the next Shrove
    Tuesday, and names no month after it (Brazil's "Best in Mar 🎉 Carnival"
    on the 2026-11 home page, for a Carnival that ends on 9 February 2027);
  * the Easter arithmetic itself, on known dates.
"""
import datetime, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []


def easter(y):
    """Gregorian Easter Sunday (the anonymous algorithm)."""
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return datetime.date(y, month, (h + l - 7 * m + 114) % 31 + 1)


def shrove_tuesday(y):
    return easter(y) - datetime.timedelta(days=47)


results.append(ok([easter(y) for y in (2027, 2028, 2029, 2030)]
                  == [datetime.date(2027, 3, 28), datetime.date(2028, 4, 16), datetime.date(2029, 4, 1),
                      datetime.date(2030, 4, 21)]
                  and shrove_tuesday(2027) == datetime.date(2027, 2, 9)
                  and shrove_tuesday(2030) == datetime.date(2030, 3, 5),
                  "Easter 2027-2030 and Shrove Tuesday 2027 (9 Feb) and 2030 (5 Mar)"))

today = datetime.date.today()
nxt = shrove_tuesday(today.year)
if nxt < today:
    nxt = shrove_tuesday(today.year + 1)
acts = json.load(open(os.path.join(ROOT, "public", "activities.json"), encoding="utf-8"))
items = {iso: s for iso, a in acts.items() for s in (a.get("seasonal") or [])
         if s.get("what", "").startswith("Carnival")}
results.append(ok(sorted(items) == ["AW", "BR", "CW", "TT"], "the Carnival items: %s" % " ".join(sorted(items))))
for iso, s in sorted(items.items()):
    m = s.get("months") or []
    results.append(ok(m and m[-1] == nxt.month and nxt.month in m,
                      "%s Carnival %s ends in the month of the next Shrove Tuesday (%s)" % (iso, m, nxt.isoformat())))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
