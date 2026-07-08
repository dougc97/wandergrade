#!/usr/bin/env python3
"""Build public/og-images.json: ISO -> a 1200px-wide hero photo URL for each
country's social-share preview (og:image on /guide/<slug> pages).

Uses the first curated gallery subject that resolves to a real photo via the
Wikipedia pageimages API (same source + PHOTO_BAD filter as the site's hero
carousel). Run from the repo root with /usr/bin/python3; re-run whenever
galleries change. Network: ~176 requests, a minute or two.
"""

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
PHOTO_BAD = re.compile(
    r"map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram"
    r"|\.svg|location|adm[_ ]|administrative|emblem|wikidata|collage|montage", re.I)


def thumb(subject):
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json"
           "&prop=pageimages&piprop=thumbnail&pithumbsize=1200&redirects=1"
           "&titles=" + urllib.parse.quote(subject))
    try:
        req = urllib.request.Request(
            api, headers={"User-Agent": "wandergrade-og/1.0 (291570524+dougc97@users.noreply.github.com)"})
        j = json.load(urllib.request.urlopen(req, timeout=20))
        page = next(iter(j.get("query", {}).get("pages", {}).values()))
        th = page.get("thumbnail", {})
        t = th.get("source")
        # size gate: a small delivered thumb means a tiny source file
        if t and not PHOTO_BAD.search(t) and (th.get("width", 0) >= 700 or th.get("height", 0) >= 500):
            return t
    except Exception:
        return None
    return None


def main():
    acts = json.load(open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8"))
    out, misses = {}, []
    for iso in sorted(acts):
        url = None
        for subject in (acts[iso].get("gallery") or [])[:3]:
            url = thumb(subject)
            if url is None:
                time.sleep(1)
                url = thumb(subject)   # one retry for transient errors
            if url:
                break
        if url:
            out[iso] = url
        else:
            misses.append(iso)
        sys.stdout.write(".")
        sys.stdout.flush()
    with open(os.path.join(PUBLIC, "og-images.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), ensure_ascii=False, sort_keys=True)
    print("\nwrote %d/%d og images; misses: %s" % (len(out), len(acts), misses))


if __name__ == "__main__":
    main()
