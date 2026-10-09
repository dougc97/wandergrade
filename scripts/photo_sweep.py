#!/usr/bin/env python3
"""Hero-photo quality tooling: resolve gallery subjects to the Wikipedia lead
image the guide shows, keep an 800px copy, and print focus/size metrics.

The guide hero (public/app.js loadHeroPhotos) shows each gallery subject's
Wikipedia lead image, chosen by Wikipedia's editors, so a gallery can quietly
acquire a soft phone snapshot. This script resolves subjects exactly as
wikiIconic() does (pageimages API, 1600px thumbnail, PHOTO_BAD, the size gate)
so a reviewer can look at what readers see, and prints a Laplacian-variance
focus hint (higher = more edge energy; texture inflates it, so it is a hint,
not a verdict — the 2026-10 sweep's rejects sat below ~900, keepers mostly
above ~1200, with overlap both ways).

    /usr/bin/python3 scripts/photo_sweep.py resolve "Galle Fort" "Sigiriya"
        one JSON line per title: status, file, original size, lapvar, img path
    /usr/bin/python3 scripts/photo_sweep.py sweep [--out DIR] [--shard k/n] [ISO ...]
        every gallery subject (or the given ISOs); writes DIR/index<k>.json;
        run the shards in parallel from separate shells (4 at 0.25s between
        requests drew HTTP 429s from Wikimedia; 3 at 0.5s did not)
    /usr/bin/python3 scripts/photo_sweep.py batches [--out DIR] [--n 8]
        merge DIR/index*.json into DIR/index.json and DIR/batches/batch<k>.json
        (countries + photos, the manifests a reviewer rates from)
    /usr/bin/python3 scripts/photo_sweep.py skip-check [ISO ...]
        list gallery subjects whose CURRENT lead image is on public/photo-skip.json:
        a gallery that now resolves to a rejected photo and needs a new subject

PIL only (ships with /usr/bin/python3); no numpy. Network: one API call plus
one thumbnail download per subject, 0.5s apart.
"""
import io
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

from PIL import Image, ImageFilter, ImageStat

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
UA = {"User-Agent": "wandergrade-photo-sweep/1.0 (+https://wandergrade.com)"}
# Mirrors PHOTO_BAD in app.js: never a map, flag, seal, montage...
PHOTO_BAD = re.compile(
    r"map|flag|locator|coat|orthographic|projection|seal|logo|icon|diagram"
    r"|\.svg|location|adm[_ ]|administrative|emblem|wikidata|collage|montage", re.I)
PAUSE = 0.5


def _json(url):
    req = urllib.request.Request(url, headers=UA)
    return json.load(urllib.request.urlopen(req, timeout=30))


def page_image(subject):
    """The pageimages record app.js reads: thumbnail (1600px), original, name."""
    api = ("https://en.wikipedia.org/w/api.php?action=query&format=json&prop=pageimages"
           "&piprop=thumbnail|original|name&pithumbsize=1600&redirects=1&titles="
           + urllib.parse.quote(subject))
    return next(iter(_json(api)["query"]["pages"].values()))


def metrics(data):
    im = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = im.size
    g = im.convert("L")
    g.thumbnail((512, 512))
    lap = g.filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    hsv = im.copy()
    hsv.thumbnail((256, 256))
    sat = ImageStat.Stat(hsv.convert("HSV")).mean[1]
    return im, {"w": w, "h": h, "lapvar": round(ImageStat.Stat(lap).var[0], 1),
                "sat": round(sat, 1), "bright": round(ImageStat.Stat(g).mean[0], 1),
                "bytes": len(data)}


def resolve(subject, img_path=None):
    """status + the fields the reviewer needs; saves an 800px JPEG when asked."""
    page = page_image(subject)
    t = page.get("thumbnail") or {}
    thumb = (t.get("source") or "").split("?")[0]
    orig = page.get("original") or {}
    row = {"subject": subject, "title": page.get("title"), "file": page.get("pageimage"),
           "ow": orig.get("width"), "oh": orig.get("height")}
    if not thumb:
        row["status"] = "no-image"
    elif PHOTO_BAD.search(thumb):
        row["status"] = "filtered"
    elif (t.get("width") or 0) < 800 and (t.get("height") or 0) < 1000:
        row["status"] = "too-small"
    else:
        small = re.sub(r"/1600px-", "/800px-", thumb)
        data = urllib.request.urlopen(urllib.request.Request(small, headers=UA), timeout=40).read()
        im, m = metrics(data)
        row.update(m)
        row["status"] = "ok"
        row["thumb"] = thumb
        if img_path:
            im.save(img_path, "JPEG", quality=88)
            row["img"] = img_path
    return row


def _acts():
    with open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8") as f:
        return json.load(f)


def _names():
    with open(os.path.join(PUBLIC, "country-names.json"), encoding="utf-8") as f:
        return json.load(f)


def _places(a):
    """The activity places the hero de-duplicates against (app.js photoSubjects)."""
    out = []
    for x in a.get("activities") or []:
        label = x if isinstance(x, str) else x.get("t", "")
        m = re.search(r"\(([^),]+)", label)
        out.append(m.group(1).strip() if m else re.sub(r"\s*\([^)]*\)", "", label).strip())
    return [p for p in out if p]


def cmd_resolve(argv):
    out = os.path.join(_opt(argv, "--out", os.path.join("/tmp", "photo-sweep")), "cand")
    os.makedirs(out, exist_ok=True)
    for s in [a for a in argv if not a.startswith("--") and a != _opt(argv, "--out", None)]:
        try:
            path = os.path.join(out, re.sub(r"[^A-Za-z0-9]+", "_", s)[:60] + ".jpg")
            print(json.dumps(resolve(s, path), ensure_ascii=False), flush=True)
        except Exception as e:  # one bad title must not stop the list
            print(json.dumps({"subject": s, "status": "error", "error": str(e)[:120]}), flush=True)
        time.sleep(PAUSE)


def _opt(argv, flag, default):
    if flag in argv:
        return argv[argv.index(flag) + 1]
    return default


def cmd_sweep(argv):
    out = _opt(argv, "--out", os.path.join("/tmp", "photo-sweep"))
    shard = _opt(argv, "--shard", "0/1")
    k, n = (int(x) for x in shard.split("/"))
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    acts, names = _acts(), _names()
    isos = sorted(acts)
    only = set(a.upper() for a in argv if re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]+)?", a))
    isos = [i for i in isos if (not only or i in only)][k::n]
    rows = []
    for iso in isos:
        for i, subject in enumerate((acts[iso].get("gallery") or [])[:6]):
            row = {"iso": iso, "country": names.get(iso, iso), "idx": i, "subject": subject}
            try:
                row.update(resolve(subject, os.path.join(out, "img", "%s_%d.jpg" % (iso, i))))
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e)[:120]
            rows.append(row)
            print(iso, i, row.get("status"), row.get("file"), row.get("lapvar"), flush=True)
            time.sleep(PAUSE)
    with open(os.path.join(out, "index%d.json" % k), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=0, ensure_ascii=False)
    print("wrote", len(rows), "rows for shard", shard)


def cmd_batches(argv):
    import glob
    from collections import defaultdict
    out = _opt(argv, "--out", os.path.join("/tmp", "photo-sweep"))
    n = int(_opt(argv, "--n", "8"))
    best = {}
    for f in sorted(glob.glob(os.path.join(out, "index[0-9]*.json"))):
        for r in json.load(open(f, encoding="utf-8")):
            key = (r["iso"], r["idx"])
            if key not in best or (r["status"] == "ok" and best[key]["status"] != "ok"):
                best[key] = r
    rows = sorted(best.values(), key=lambda r: (r["iso"], r["idx"]))
    with open(os.path.join(out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=0, ensure_ascii=False)
    acts, names = _acts(), _names()
    by = defaultdict(list)
    for r in rows:
        by[r["iso"]].append(r)
    isos = sorted(by)
    os.makedirs(os.path.join(out, "batches"), exist_ok=True)
    for k in range(n):
        part = isos[k::n]
        countries = [{"iso": iso, "n": names.get(iso, iso), "g": (acts[iso].get("gallery") or [])[:6],
                      "p": _places(acts[iso]),
                      "unresolved": [{"idx": r["idx"], "subject": r["subject"], "status": r["status"]}
                                     for r in by[iso] if r["status"] != "ok"]} for iso in part]
        photos = [{"iso": r["iso"], "country": r["country"], "idx": r["idx"], "subject": r["subject"],
                   "file": r.get("file"), "img": r["img"], "orig": "%sx%s" % (r.get("ow"), r.get("oh")),
                   "lapvar": r.get("lapvar"), "sat": r.get("sat")}
                  for iso in part for r in by[iso] if r["status"] == "ok"]
        with open(os.path.join(out, "batches", "batch%d.json" % k), "w", encoding="utf-8") as f:
            json.dump({"countries": countries, "photos": photos}, f, indent=0, ensure_ascii=False)
        print("batch", k, len(part), "countries", len(photos), "photos")
    from collections import Counter
    print(len(rows), "rows", dict(Counter(r["status"] for r in rows)))


def cmd_skip_check(argv):
    try:
        with open(os.path.join(PUBLIC, "photo-skip.json"), encoding="utf-8") as f:
            skip = set(json.load(f).get("files") or [])
    except OSError:
        skip = set()
    acts = _acts()
    only = set(a.upper() for a in argv if re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]+)?", a))
    hits = 0
    for iso in sorted(acts):
        if only and iso not in only:
            continue
        for subject in (acts[iso].get("gallery") or [])[:6]:
            try:
                f = page_image(subject).get("pageimage")
            except Exception as e:
                print(iso, subject, "error", str(e)[:80])
                continue
            if f in skip:
                hits += 1
                print(iso, subject, "-> SKIPPED FILE", f)
            time.sleep(PAUSE)
    print(hits, "gallery subjects resolve to a skipped file")


if __name__ == "__main__":
    cmds = {"resolve": cmd_resolve, "sweep": cmd_sweep, "batches": cmd_batches, "skip-check": cmd_skip_check}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])
