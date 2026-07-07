#!/usr/bin/env python3
"""Build public/stay-coords.json: ISO -> up to 5 stay-search anchor spots
(name + lat/lng) for the Travel Guide's "Where to stay" chips.

Spots mirror the page's own recommendations: the places named in "top things
to do" come first (all comma-separated places in a label's parenthetical,
e.g. "Tea country & trains (Ella, Kandy)" -> Ella AND Kandy), then curated
gallery places fill any remaining room. Coordinates via Wikipedia, with the
same disambiguation fallbacks the photo pipeline uses ("Ella, Sri Lanka" /
"Ella (Sri Lanka)").

Run from the repo root with /usr/bin/python3; re-run when activities or
galleries change.
"""

import json
import os
import re
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

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
        pass
    return None


def coords_with_fallback(subject, country):
    for title in (subject, "%s, %s" % (subject, country), "%s (%s)" % (subject, country)):
        ll = coords(title)
        if ll:
            return ll
    return None


def act_places(x):
    """Every place an activity names: all parenthetical entries, else the
    photo-subject override, else the cleaned label."""
    label = x if isinstance(x, str) else x.get("t", "")
    m = re.search(r"\(([^)]*)\)", label)
    if m:
        return [s.strip() for s in m.group(1).split(",") if s.strip()]
    if isinstance(x, dict) and x.get("p"):
        return [x["p"]]
    clean = re.sub(r"\s*\([^)]*\)", "", label).strip()
    return [clean] if clean else []


def label(subject):
    return re.sub(r"\s*\(.*\)", "", subject.split(",")[0]).strip()


def build_country(args):
    iso, act, names = args
    country = names.get(iso, iso)
    candidates = [p for x in (act.get("activities") or []) for p in act_places(x)]
    candidates += act.get("gallery") or []
    spots, seen = [], set()
    for subject in candidates:
        if len(spots) >= MAX_SPOTS:
            break
        name = label(subject)
        if not name or name.lower() in seen:
            continue
        ll = coords_with_fallback(subject, country)
        if not ll:
            continue
        seen.add(name.lower())
        spots.append({"n": name, "ll": ll})
    return iso, spots


def main():
    acts = json.load(open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8"))
    names = json.load(open(os.path.join(PUBLIC, "country-names.json"), encoding="utf-8"))
    out = {}
    jobs = [(iso, acts[iso], names) for iso in sorted(acts)]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for iso, spots in ex.map(build_country, jobs):
            if spots:
                out[iso] = spots
            print("%s:%d" % (iso, len(spots)), end=" ", flush=True)
    with open(os.path.join(PUBLIC, "stay-coords.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    counts = [len(v) for v in out.values()]
    print("\n%d/%d countries; avg %.1f spots; thin(<2): %s"
          % (len(out), len(acts), sum(counts) / len(counts),
             [k for k in acts if len(out.get(k, [])) < 2]))


if __name__ == "__main__":
    main()
