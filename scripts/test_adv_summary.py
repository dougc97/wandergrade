"""The US advisory summary never quotes another level's lead beside a row's pill.

    /usr/bin/python3 scripts/test_adv_summary.py

No network: a small feed in the State Department's RSS shape goes through
fxtracker/advisories._us_advisories. The cases are real ones:
  * Rwanda (Level 3, Oct 2026) whose description still opened with the Level 2
    "Exercise increased caution in Rwanda due to crime and unrest": the Safety
    tip, the pill tip, the guide and the governments panel all quoted it as the
    reason beside "Reconsider travel". Quoted now: nothing (the rest is a
    bookkeeping note and a 31-character fragment). Its risk chips still come
    from that sentence's "due to" clause;
  * Comoros (Level 2), whose own lead has the feed's typo "Exercise increase
    caution": still its own level's lead, so still quoted;
  * Mexico (Level 2): an ordinary lead, unchanged.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import advisories as A  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c


def item(country, level, slug, desc):
    return ("<item><title>%s - Level %d: x</title><link>https://travel.state.gov/%s-travel-advisory.html</link>"
            "<description><![CDATA[%s]]></description><pubDate>Mon, 11 May 2026 00:00:00 GMT</pubDate></item>"
            % (country, level, slug, desc))


FEED = "<rss><channel>%s</channel></rss>" % "".join([
    item("Rwanda", 3, "rwanda",
         "<p>Exercise increased caution in Rwanda due to crime and unrest.</p>"
         "<p>The 3 areas of increased risk were combined into 1.</p><p>Some areas have increased risk.</p>"),
    item("Comoros", 2, "comoros",
         "<p>Exercise increase caution in Comoros due to crime, unrest, and health.</p>"
         "<p>There is no full-time official U.S. presence in Comoros.</p>"),
    item("Mexico", 2, "mexico",
         "<p>Exercise increased caution in Mexico due to terrorism, crime, and kidnapping.</p>"
         "<p>Some areas have increased risk.</p>"),
])
A._fetch_text = lambda url, retries=3: FEED
got = {i["iso"]: i for i in A._us_advisories()["items"]}
results = []
rw, km, mx = got.get("RW", {}), got.get("KM", {}), got.get("MX", {})
results.append(ok(rw.get("level") == 3 and rw.get("summary") == "",
                  "Rwanda (Level 3) quotes nothing, not its Level 2 lead: %r" % rw.get("summary")))
results.append(ok(rw.get("risks") == ["Crime", "Unrest"],
                  "...and keeps its reasons as chips: %r" % rw.get("risks")))
results.append(ok(km.get("summary", "").startswith("Exercise increase caution in Comoros due to crime"),
                  "Comoros's own lead, typo and all, is still quoted: %r" % km.get("summary", "")[:60]))
results.append(ok(mx.get("summary") == "Exercise increased caution in Mexico due to terrorism, crime, and kidnapping."
                  " Some areas have increased risk.",
                  "Mexico's ordinary two-sentence summary is unchanged"))
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
