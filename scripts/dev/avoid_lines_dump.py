"""Every guide's 📍 lines as this checkout's parser writes them, from Global
Affairs Canada's live feed, for checking against travel.gc.ca by hand or by
a reviewer: one entry per guide in public/slugs.json that has regional
blocks, {iso, slug, link, blocks: [{t, line, brief, text}]}.

    /usr/bin/python3 scripts/dev/avoid_lines_dump.py [--out FILE] [--dir MIRROR]

One request per country, a second or more apart (GAC's feed is a public
service, not ours): the 190 guides take about ten minutes, so run it in the
background. --dir reads <iso>.json files saved from the same feed instead.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from fxtracker import watchouts  # noqa: E402

UA = "wandergrade-avoid-lines-dump/1.0 (+https://wandergrade.com)"
PACE = 1.1


def fetch(iso):
    req = urllib.request.Request(watchouts.API.format(iso=iso), headers={"User-Agent": UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None          # a country the feed lacks
            if e.code < 500 or attempt == 2:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(PACE * (attempt + 2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(os.path.dirname(ROOT), "avoid-lines-v2.json"))
    ap.add_argument("--dir", help="read <iso>.json from this folder instead of the live feed")
    a = ap.parse_args()
    with open(os.path.join(ROOT, "public", "slugs.json"), encoding="utf-8") as f:
        slugs = json.load(f)
    by_iso, out, last = {}, [], 0.0
    for slug, code in sorted(slugs.items(), key=lambda kv: kv[1]):
        iso = code[:2].lower()        # England, Scotland and Wales read the UK's
        if iso not in by_iso:
            raw = None
            if a.dir:
                p = os.path.join(a.dir, iso + ".json")
                if os.path.exists(p):
                    with open(p, encoding="utf-8") as f:
                        raw = json.load(f)
            else:
                time.sleep(max(0.0, PACE - (time.time() - last)))
                try:
                    raw = fetch(iso)
                except Exception as e:
                    print("%s: %s" % (iso.upper(), e), file=sys.stderr, flush=True)
                last = time.time()
            by_iso[iso] = watchouts.from_feed(iso, raw) if raw else None
            print(iso.upper(), len((by_iso[iso] or {}).get("regional") or []), flush=True)
        w = by_iso[iso]
        if not w or not w["regional"]:
            continue
        out.append({"iso": code, "slug": slug, "link": w["link"],
                    "blocks": [{k: r[k] for k in ("t", "line", "brief", "text")} for r in w["regional"]]})
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
        f.write("\n")
    print("%d guides with regional lines -> %s" % (len(out), a.out))


if __name__ == "__main__":
    main()
