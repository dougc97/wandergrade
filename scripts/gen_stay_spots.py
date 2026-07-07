#!/usr/bin/env python3
"""Build public/stay-coords.json: ISO -> up to 5 stay-search anchor spots
(name + lat/lng), one per curated gallery subject that has Wikipedia
coordinates. The Travel Guide's "Where to stay" chips let the user pick a
spot; the Booking/Hostelworld buttons target it.

Run from the repo root with /usr/bin/python3; re-run when galleries change.
"""

import json
import os
import re
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
MAX_SPOTS = 5


def coords(subject):
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
           "&prop=coordinates&redirects=1&titles=" + urllib.parse.quote(subject))
    try:
        req = urllib.request.Request(
            api, headers={"User-Agent": "wandergrade-spots/1.0 (291570524+dougc97@users.noreply.github.com)"})
        j = json.load(urllib.request.urlopen(req, timeout=20))
        page = next(iter(j.get("query", {}).get("pages", {}).values()))
        c = page.get("coordinates")
        if c:
            return [round(c[0]["lat"], 5), round(c[0]["lon"], 5)]
    except Exception:
        return "err"
    return None


def label(subject):
    """Chip label: strip the disambiguation tail ('Ella, Sri Lanka' -> 'Ella',
    'Blue Lagoon (geothermal spa)' -> 'Blue Lagoon')."""
    return re.sub(r"\s*\(.*\)", "", subject.split(",")[0]).strip()


def main():
    acts = json.load(open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8"))
    out = {}
    for iso in sorted(acts):
        spots, seen = [], set()
        for subject in (acts[iso].get("gallery") or []):
            if len(spots) >= MAX_SPOTS:
                break
            ll = coords(subject)
            if ll == "err":
                time.sleep(1)
                ll = coords(subject)
            if not ll or ll == "err":
                continue
            name = label(subject)
            if name.lower() in seen:
                continue
            seen.add(name.lower())
            spots.append({"n": name, "ll": ll})
        if spots:
            out[iso] = spots
        print("%s:%d" % (iso, len(spots)), end=" ", flush=True)
    with open(os.path.join(PUBLIC, "stay-coords.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    counts = [len(v) for v in out.values()]
    print("\n%d/%d countries; avg %.1f spots" % (len(out), len(acts), sum(counts) / len(counts)))


if __name__ == "__main__":
    main()
