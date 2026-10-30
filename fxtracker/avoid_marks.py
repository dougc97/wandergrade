"""Global Affairs Canada's own words beside a guide place inside one of its
"Avoid all travel" zones: an ⓘ after the place's label in the guide's "Top
things to do" or "What's in season", whose tip reads

    Global Affairs Canada: “Avoid all travel to … • Amhara” (travel.gc.ca, checked 2026-10-30)

The site never says anything of its own about safety. The guide's 📍 lines
already print Canada's regional blocks; what was missing is the link from a
recommended place (Lalibela, Mount Cameroon) to the block that covers it, and
the marker is that link in Canada's words, attributed and dated.

ONE table: the "marks" section of scripts/stay-skip.json, the file that
already holds Canada's avoid-all blocks with a fingerprint of each one's
words and the places kept out of the stay chips. Per marked place: its
surface ("activity" or "seasonal") and item (the activity's label, the
season row's "what" — exactly as activities.json has them), its class in the
2026-10 audit (A: inside; A~: partly inside — the A* thin-margin rows are
Doug's call, never marked here), the block's heading, the fingerprint of the
block it was checked against (it must equal the block's own fp in the same
file), Canada's words for it verbatim (" … " where words are left out; the
bullets are Canada's), and the day they were checked. Doug's rule
(2026-10-30): avoid-all blocks only, never the 22 guides Canada says to
avoid entirely, and Ethiopia, Chad, Cameroon and Tajikistan keep their
places, marked.

public/avoid-marks.json is generated from that table (build(); run
`/usr/bin/python3 -m fxtracker.avoid_marks` after editing it, and
scripts/test_avoid_marks.py fails until the two agree). The server's crawler
block (render_guide) and app.js (renderActivity, zoneMarkHTML) both read
that file and write the same markup for it, character for character.

Staleness, two ways:
  * gen_stay_spots.py --check (the monthly task's command) flags every marked
    row whose block is new, gone or reworded on Canada's live page, or whose
    words are no longer in it;
  * between a change and that review, the marker stops quoting a block whose
    live fingerprint no longer matches: where Canada's answer is in hand (the
    server's watchouts cache for its render, /api/watchouts in the browser),
    a quote from a block that is gone or reworded drops out, and a marker left
    with none keeps its place invisible (.zonemark.stale: visibility hidden),
    so nothing around it moves when the answer lands after the list drew.
"""

import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
TABLE = os.path.join(ROOT, "scripts", "stay-skip.json")
OUT = os.path.join(PUBLIC, "avoid-marks.json")

ATTRIBUTION = "Global Affairs Canada"
SOURCE = "travel.gc.ca"
SURFACES = ("activity", "seasonal")
CLASSES = ("A", "A~")
# Canada's "Avoid all travel" for the whole country (2026-10-30): out of scope
# for place-level marks (Doug, 2026-10-30) — the guide's advisory already says it.
WHOLE_COUNTRY = ("AF", "BF", "BY", "CD", "CF", "HT", "IQ", "IR", "KP", "LB", "LY", "ML", "MM", "NE", "RU",
                 "SD", "SO", "SS", "SY", "UA", "VE", "YE")

_data = None


def rows(table):
    """[(iso, row)] in the table's order."""
    marks = ((table or {}).get("marks") or {}).get("countries") or {}
    return [(iso, r) for iso, rs in marks.items() for r in rs]


def build(table):
    """The client's copy of the table: per country, one entry per marked
    item in table order, its quotes (block heading, fingerprint, words,
    checked) in table order — two rows on one item (Saudi Arabia's Empty
    Quarter, under two blocks) are one marker."""
    out = {}
    for iso, r in rows(table):
        items = out.setdefault(iso, [])
        e = next((x for x in items if x["s"] == r["surface"] and x["i"] == r["item"]), None)
        if e is None:
            e = {"s": r["surface"], "i": r["item"], "q": []}
            items.append(e)
        e["q"].append({"b": r["block"], "fp": r["fp"], "w": r["words"], "c": r["checked"]})
    return {"about": "Generated from scripts/stay-skip.json (\"marks\") by /usr/bin/python3 -m "
                     "fxtracker.avoid_marks; fxtracker/avoid_marks.py says what it is. Do not edit by hand.",
            "countries": out}


def dump(payload):
    """The file's exact text (compact: stay-skip.json is the readable copy)."""
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"


def write():
    with open(TABLE, encoding="utf-8") as f:
        payload = build(json.load(f))
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(dump(payload))
    return payload


def load():
    """public/avoid-marks.json, read once per process ({} if unreadable:
    no markers, never no page)."""
    global _data
    if _data is None:
        try:
            with open(OUT, encoding="utf-8") as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def esc(s):
    """app.js esc(), exactly: the markup must be the browser's own."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def live(q, notes):
    """False only when Canada's answer in hand shows the quoted block gone
    or reworded: notes is watchouts.from_feed's answer (the server's cache,
    /api/watchouts), each block with its "fp". No answer, a failed one (no
    link to Canada's page) or a block without an fp says nothing. app.js
    zoneLive is the same test."""
    if not notes or not notes.get("link"):
        return True
    for r in notes.get("regional") or []:
        if r.get("t") == q["b"]:
            return r.get("fp") is None or r.get("fp") == q["fp"]
    return False


def tip(quotes):
    """The marker's words: the attribution, each quote whole, the source and
    the check date (the oldest, if two quotes were checked apart)."""
    return "%s: %s (%s, checked %s)" % (ATTRIBUTION, "\n".join("“%s”" % q["w"] for q in quotes),
                                        SOURCE, min(q["c"] for q in quotes))


def span(iso, k, notes=None, data=None):
    """The ⓘ for entry k of a country's marks (app.js zoneSpan): the guide's
    ⓘ pattern (.muted[data-tip], title="" — app.js gives it its Tab stop,
    role and "More info" name, and its tap on touch), or its invisible
    stand-in once every quote it had is stale. The no-break space that holds
    it to the label's last word is inside it, so hidden (the crawler block's
    copy, styles.css) it takes no room at all."""
    e = ((data or load()).get("countries") or {}).get(iso, [])[k]
    qs = [q for q in e["q"] if live(q, notes)]
    if not qs:
        return '<span class="muted zonemark stale" data-zm="%d" aria-hidden="true">&nbsp;ⓘ</span>' % k
    return '<span class="muted zonemark" data-zm="%d" data-tip="%s" title="">&nbsp;ⓘ</span>' % (k, esc(tip(qs)))


def html(iso, surface, item, notes=None, data=None):
    """The marker after an item's label, "" for an unmarked one (app.js
    zoneMarkHTML)."""
    for k, e in enumerate(((data or load()).get("countries") or {}).get(iso) or []):
        if e["s"] == surface and e["i"] == item:
            return span(iso, k, notes, data)
    return ""


if __name__ == "__main__":
    p = write()
    n = sum(len(v) for v in p["countries"].values())
    print("wrote %s: %d markers in %d guides" % (os.path.relpath(OUT, ROOT), n, len(p["countries"])))
