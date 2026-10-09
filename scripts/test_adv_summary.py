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
The risk labels themselves (RISK_WORDS / label_reasons, shared with Canada's
pages and the /do-not-travel lists): the medical-care reason is "Medical",
never "Health care" — in the Safety table the Risks column sits beside the
Health column, and a "Health care" chip read as that column's word twice —
and one word, not "Medical care", which was wide enough to fold Ghana's
fourth chip into a "+1" at 1280.
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

# Rwanda in the live feed's shape (Oct 2026): a bare "Read the entire" sits
# before the link to the Level 4 border area, and only the full "Read the
# entire Travel Advisory" was stripped, so the guide quoted "Some areas have
# increased risk. Read the entire Do not travel to within 10 kilometers...".
A._fetch_text = lambda url, retries=3: "<rss><channel>%s</channel></rss>" % item(
    "Rwanda", 3, "rwanda",
    "<p>Exercise increased caution in Rwanda due to crime and unrest.</p>"
    "<p>Some areas have increased risk. Read the entire Travel Advisory.</p>"
    "<p>Read the entire <a href=\"#x\">Do not travel</a> to within 10 kilometers of Rwanda\u2019s border"
    " with the Democratic Republic of the Congo due to unrest.</p>"
    "<p>Petty crime like pickpocketing is a risk in urban areas.</p>")
rw2 = {i["iso"]: i for i in A._us_advisories()["items"]}.get("RW", {})
results.append(ok("Read the entire" not in rw2.get("summary", ""),
                  "Rwanda's stray \"Read the entire\" is never quoted: %r" % rw2.get("summary")))
results.append(ok(rw2.get("risks") == ["Crime", "Unrest"],
                  "...and its chips stay Crime, Unrest: %r" % rw2.get("risks")))
# The labels: "Health" is the State Department's own indicator (disease,
# outbreaks); the care itself is "Medical". Comoros's US lead ("crime,
# unrest, and health") and Canada's ("the limited availability of emergency
# services and inadequate medical facilities") are the two real cases, and
# no label may begin with another one — that is what made the pair look
# alike beside the Health column.
results.append(ok(km.get("risks") == ["Crime", "Unrest", "Health"],
                  "Comoros's US reasons end in Health: %r" % km.get("risks")))
results.append(ok(A.label_reasons("the limited availability of emergency services and inadequate medical facilities")
                  == ["Limited help", "Medical"],
                  "Canada's Comoros lead labels the care as Medical"))
results.append(ok(A.label_reasons("the outbreak of Ebola disease and poor health care") == ["Health", "Medical"],
                  "...and a disease beside the care is Health, Medical"))
labels = [lab for lab, _ in A.RISK_WORDS]
results.append(ok("Health care" not in labels and "Medical care" not in labels
                  and not any(a != b and b.startswith(a) for a in labels for b in labels),
                  "no risk label begins with another (Health / Health care), none is \"Medical care\""))
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
