#!/usr/bin/env python3
"""Guide gallery photos of places inside a Global Affairs Canada "Avoid all
travel" zone, kept out of public/activities.json.

    /usr/bin/python3 scripts/gallery_drops.py           # apply (idempotent; nothing else in the file moves)
    /usr/bin/python3 scripts/gallery_drops.py --check   # report only; exit 1 until the drops hold

Doug's rule (2026-10-30): a gallery photo of a place inside one of Canada's
regional "Avoid all travel" blocks (class A, inside, or A~, partly inside,
in the 2026-10-18 audit, places-in-avoid-zones-audit-2026-10-18.md) is
dropped where the guide keeps enough other good photos. Ethiopia, Chad,
Cameroon and Tajikistan keep theirs (EXEMPT), and the 22 guides Canada says
to avoid entirely are out of scope (WHOLE_COUNTRY). The thin-margin A* rows
are Doug's call: Nigeria's Zuma Rock stays in its gallery until he decides
(PENDING). Where a drop left a hero short, places outside every Canada
avoid-all block and US "Do not travel" area were appended (ADD).

public/activities.json is one line, so merging a branch that also touches it
conflicts as a whole: take the other side, run this script, and
scripts/test_photo_skip.py (which fails while a dropped photo is back, or a
gallery outside the exempt guides shows a place scripts/stay-skip.json skips
under a Canada avoid-all block) says when it holds.
"""

import copy
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACTS = os.path.join(ROOT, "public", "activities.json")
SKIP = os.path.join(ROOT, "scripts", "stay-skip.json")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gallery_entry  # noqa: E402

DROP = {
    "CI": ["Comoé National Park"],            # A~: the park's northernmost 15-30 km in the 50 km Burkina Faso band
    "CO": ["Las Lajas Sanctuary"],
    "IL": ["Rosh HaNikra grottoes"],
    "MR": ["Richat Structure", "Tichit"],
    "MZ": ["Ibo Island", "Quirimbas National Park"],
    "NG": ["Agbokim Waterfalls", "Gashaka Gumti National Park", "Obudu Mountain Resort"],
    "PK": ["K2"],
    "TN": ["Sbeitla"],
}
ADD = {
    "CO": ["Ciudad Perdida", "Barichara"],
    "MR": ["Erg Amatlich", "Mhaïreth"],
    "MZ": ["Chimanimani Mountains", "Bilene"],
    "NG": ["Idanre", "Ile-Ife"],
}
EXEMPT = ("CM", "ET", "TD", "TJ")
WHOLE_COUNTRY = ("AF", "BF", "BY", "CD", "CF", "HT", "IQ", "IR", "KP", "LB", "LY", "ML", "MM", "NE", "RU",
                 "SD", "SO", "SS", "SY", "UA", "VE", "YE")
PENDING = {"NG": ["Zuma Rock"]}             # A*, Doug's call


def load(path=ACTS):
    """The file's dict, after checking it is in its own compact format."""
    with open(path, "rb") as f:
        raw = f.read()
    acts = json.loads(raw)
    if dump(acts) != raw:
        raise SystemExit("%s is not in its compact format (separators, UTF-8, no newline): not touched" % path)
    return acts


def dump(acts):
    return json.dumps(acts, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def apply(acts):
    """A copy with every DROP title out of its gallery and every ADD title at
    its end; nothing else changes."""
    out = copy.deepcopy(acts)
    for iso in sorted(set(DROP) | set(ADD)):
        assert iso not in EXEMPT + WHOLE_COUNTRY, iso
        g = out[iso]["gallery"]
        g[:] = [e for e in g if gallery_entry.label(e) not in DROP.get(iso, [])]
        g += [t for t in ADD.get(iso, []) if t not in [gallery_entry.label(e) for e in g]]
    return out


def skipped(skip):
    """{iso: places scripts/stay-skip.json skips under a Canada avoid-all block}."""
    return {iso: {p for b in blocks.values() for p in (b.get("skip") or {})}
            for iso, blocks in (skip.get("countries") or {}).items()}


def problems(acts, skip):
    """Why the galleries don't hold the rule, or []."""
    out = []
    for iso, titles in sorted(DROP.items()):
        labels = [gallery_entry.label(e) for e in acts[iso].get("gallery") or []]
        out += ["%s gallery shows %s again (dropped: inside a Canada avoid-all zone)" % (iso, t) for t in titles if t in labels]
    for iso, titles in sorted(ADD.items()):
        labels = [gallery_entry.label(e) for e in acts[iso].get("gallery") or []]
        out += ["%s gallery lost %s (added for a dropped photo)" % (iso, t) for t in titles if t not in labels]
    for iso, places in sorted(skipped(skip).items()):
        if iso in EXEMPT + WHOLE_COUNTRY or iso not in acts:
            continue
        for e in acts[iso].get("gallery") or []:
            p = gallery_entry.label(e)
            if p in places and p not in PENDING.get(iso, []):
                out.append("%s gallery shows %s, which scripts/stay-skip.json skips inside a Canada avoid-all block"
                           % (iso, p))
    return out


if __name__ == "__main__":
    acts = load()
    with open(SKIP, encoding="utf-8") as f:
        skip = json.load(f)
    if "--check" in sys.argv[1:]:
        lines = problems(acts, skip)
        for line in lines:
            print(line)
        print("%d gallery problem(s)" % len(lines))
        sys.exit(1 if lines else 0)
    new = apply(acts)
    if new == acts:
        print("public/activities.json already holds the drops")
    else:
        with open(ACTS, "wb") as f:
            f.write(dump(new))
        for iso in sorted(set(DROP) | set(ADD)):
            if new[iso]["gallery"] != acts[iso]["gallery"]:
                print("%s gallery: %s" % (iso, [gallery_entry.label(e) for e in new[iso]["gallery"]]))
    lines = problems(new, skip)
    for line in lines:
        print(line)
    sys.exit(1 if lines else 0)
