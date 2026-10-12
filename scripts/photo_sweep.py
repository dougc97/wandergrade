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

A gallery entry can also be {"file": <Commons name>, "label": <place>}, a
Commons photo pinned by name (scripts/gallery_entry.py): it resolves through
Commons imageinfo as app.js commonsPhoto() does, with the same metrics and
800px copy, and its row carries the licence (licence_ok false = the site
leaves it out). On the command line a file entry is "File:<name>" or the
entry's JSON.

    /usr/bin/python3 scripts/photo_sweep.py resolve "Galle Fort" "Sigiriya" "File:Lumley Beach Freetown.JPG"
        one JSON line per title or file: status, file, original size and
        aspect (portrait flagged), lapvar, img path and its hero-strip crop
        (and licence for a file)
    /usr/bin/python3 scripts/photo_sweep.py sweep [--out DIR] [--shard k/n] [ISO ...]
        every gallery subject (or the given ISOs); writes DIR/index<k>.json;
        run the shards in parallel from separate shells (4 at 0.25s between
        requests drew HTTP 429s from Wikimedia; 3 at 0.5s did not)
    /usr/bin/python3 scripts/photo_sweep.py batches [--out DIR] [--n 8]
        merge DIR/index*.json into DIR/index.json and DIR/batches/batch<k>.json
        (countries + photos, the manifests a reviewer rates from; rate each
        photo's full frame AND its 1158x300 hero strip, the "hero" file)
    /usr/bin/python3 scripts/photo_sweep.py sweep --changed [--out DIR] [ISO ...]
        the incremental re-run: resolve every subject but download and index
        only lead images absent from scripts/photo_verdicts.json (keep + skip),
        i.e. the ones Wikipedia's editors have changed since the last review;
        a subject now resolving to a rejected file is printed as KNOWN-SKIP
        (give that country a new subject). A pinned file is asked of Commons
        too (one imageinfo request) and printed as no-image / bad-licence /
        too-small when the site would now leave it out (deleted, relicensed,
        shrunk). Then `batches` as usual, rate the photos, and record the
        verdicts:
    /usr/bin/python3 scripts/photo_sweep.py record --keep F... --skip F...
        add verdicts to scripts/photo_verdicts.json and regenerate
        public/photo-skip.json (the list the site reads) from its skip side
    /usr/bin/python3 scripts/photo_sweep.py skip-check [ISO ...]
        list gallery subjects whose CURRENT lead image is on public/photo-skip.json:
        a gallery that now resolves to a rejected photo and needs a new subject;
        and pinned files the site would now leave out (PINNED FILE <status>)

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

import gallery_entry

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
    # Wikimedia now serves thumbs in fixed steps (a 1600px ask comes back
    # 1920px from thumb.wikimedia.org), so resolve()'s /800px- rewrite misses:
    # scale here, keeping the copy and its metrics 800px wide like the 2026-10
    # sweep's.
    if im.width > 800:
        im = im.resize((800, round(im.height * 800 / im.width)), Image.LANCZOS)
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


def _file_image(entry):
    """A pinned file's imageinfo in page_image()'s shape, plus its licence."""
    info = gallery_entry.commons_file(entry.get("file"), 1600, UA["User-Agent"])
    return {"title": info["title"], "pageimage": info["file"] if info["thumb"] else None,
            "thumbnail": {"source": info["thumb"], "width": info["tw"], "height": info["th"]},
            "original": {"source": info["url"], "width": info["ow"], "height": info["oh"]},
            "licence": info["lic"] or info["code"], "licence_ok": gallery_entry.licence_ok(info["lic"], info["code"])}


def _gate(page, pinned):
    """Why the site would leave this image out, in wikiIconic's order, or None."""
    t = page.get("thumbnail") or {}
    thumb = (t.get("source") or "").split("?")[0]
    if not thumb:
        return "no-image"
    if PHOTO_BAD.search(thumb):
        return "filtered"
    if pinned and not page["licence_ok"]:
        return "bad-licence"
    if (t.get("width") or 0) < 800 and (t.get("height") or 0) < 1000:
        return "too-small"
    return None


# The desktop hero is a 1158x300 strip from a 1280px window up (styles.css
# .heroimg, object-fit: cover, centred), so a portrait or busy photo can pass
# as a full frame and fail as the strip readers see: the 2026-10 Kambadaga
# (branch across the falls) and Ureca (portrait, the strip all haze) rejects
# did. Raters get that strip beside each copy.
HERO_ASPECT = 1158 / 300


def hero_crop(im):
    w, h = im.size
    if w / h > HERO_ASPECT:
        cw = round(h * HERO_ASPECT)
        return im.crop(((w - cw) // 2, 0, (w - cw) // 2 + cw, h))
    ch = round(w / HERO_ASPECT)
    return im.crop((0, (h - ch) // 2, w, (h - ch) // 2 + ch))


def resolve(subject, img_path=None):
    """status + the fields the reviewer needs; saves an 800px JPEG (and its
    hero-strip crop beside it, <name>_hero.jpg) when asked.
    subject is a gallery entry: a page title or a pinned {file, label}."""
    pinned = gallery_entry.is_file(subject)
    if pinned and PHOTO_BAD.search(subject.get("file") or ""):
        return {"subject": gallery_entry.label(subject), "file": gallery_entry.file_key(subject.get("file")),
                "status": "filtered"}
    page = _file_image(subject) if pinned else page_image(subject)
    t = page.get("thumbnail") or {}
    thumb = (t.get("source") or "").split("?")[0]
    orig = page.get("original") or {}
    row = {"subject": gallery_entry.label(subject), "title": page.get("title"), "file": page.get("pageimage"),
           "ow": orig.get("width"), "oh": orig.get("height")}
    if orig.get("width") and orig.get("height"):
        row["aspect"] = round(orig["width"] / orig["height"], 2)
        row["portrait"] = orig["height"] > orig["width"]
    if pinned:
        row["licence"], row["licence_ok"] = page["licence"], page["licence_ok"]
    status = _gate(page, pinned)
    if status:
        row["status"] = status
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
            row["hero"] = os.path.splitext(img_path)[0] + "_hero.jpg"
            hero_crop(im).save(row["hero"], "JPEG", quality=88)
    return row


def _acts():
    with open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8") as f:
        return json.load(f)


def _names():
    with open(os.path.join(PUBLIC, "country-names.json"), encoding="utf-8") as f:
        return json.load(f)


def _entry_arg(a):
    """A command-line subject: a title, "File:<name>", or an entry's JSON."""
    if a.startswith("{"):
        return json.loads(a)
    if a[:5].lower() == "file:":
        return {"file": a[5:], "label": re.sub(r"\.[A-Za-z]+$", "", a[5:])}
    return a


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
    used = set()
    for s in [a for a in argv if not a.startswith("--") and a != _opt(argv, "--out", None)]:
        try:
            e = _entry_arg(s)
            name = e["file"] if gallery_entry.is_file(e) else e
            base = re.sub(r"[^A-Za-z0-9]+", "_", name)[:60]
            # "Pont Faidherbe Saint-Louis.jpg" and "...Saint Louis.jpg" share a
            # base: number the second rather than overwrite the first's copy.
            path, k = os.path.join(out, base + ".jpg"), 2
            while path in used:
                path, k = os.path.join(out, "%s_%d.jpg" % (base, k)), k + 1
            used.add(path)
            print(json.dumps(resolve(e, path), ensure_ascii=False), flush=True)
        except Exception as e:  # one bad title must not stop the list
            print(json.dumps({"subject": s, "status": "error", "error": str(e)[:120]}), flush=True)
        time.sleep(PAUSE)


def _opt(argv, flag, default):
    if flag in argv:
        return argv[argv.index(flag) + 1]
    return default


VERDICTS = os.path.join(ROOT, "scripts", "photo_verdicts.json")


def _verdicts():
    try:
        with open(VERDICTS, encoding="utf-8") as f:
            v = json.load(f)
        return set(v.get("keep") or []), set(v.get("skip") or [])
    except (OSError, ValueError):
        return set(), set()


def _pinned_gone(subject, row=None):
    """Why the site would now leave a pinned file out (no-image, filtered,
    bad-licence, too-small), or None; one imageinfo request. Records the
    licence on row when given."""
    page = _file_image(subject)
    if row is not None:
        row["licence"], row["licence_ok"] = page["licence"], page["licence_ok"]
    return _gate(page, True)


def cmd_sweep(argv):
    out = _opt(argv, "--out", os.path.join("/tmp", "photo-sweep"))
    shard = _opt(argv, "--shard", "0/1")
    k, n = (int(x) for x in shard.split("/"))
    changed = "--changed" in argv
    keep, skip = _verdicts() if changed else (set(), set())
    os.makedirs(os.path.join(out, "img"), exist_ok=True)
    acts, names = _acts(), _names()
    isos = sorted(acts)
    only = set(a.upper() for a in argv if re.fullmatch(r"[A-Za-z]{2}(-[A-Za-z]+)?", a))
    isos = [i for i in isos if (not only or i in only)][k::n]
    rows = []
    for iso in isos:
        for i, subject in enumerate((acts[iso].get("gallery") or [])[:6]):
            row = {"iso": iso, "country": names.get(iso, iso), "idx": i, "subject": gallery_entry.label(subject)}
            if gallery_entry.is_file(subject):
                row["pinned"] = subject.get("file")
            try:
                if changed:
                    # One API call decides: a file already judged needs no
                    # download. A pinned file names itself, but Commons can
                    # still delete, shrink or relicense it, and the site then
                    # drops it with nothing logged, so a kept one is asked
                    # too (resolve() below asks for one not yet judged).
                    gone = None
                    if gallery_entry.is_file(subject):
                        f = gallery_entry.file_key(subject["file"])
                        gone = _pinned_gone(subject, row) if f in keep else None
                    else:
                        f = page_image(subject).get("pageimage")
                    row["file"] = f
                    if gone:
                        row["status"] = gone
                    elif f in keep:
                        row["status"] = "known-keep"
                    elif f in skip:
                        row["status"] = "known-skip"
                    else:
                        row.update(resolve(subject, os.path.join(out, "img", "%s_%d.jpg" % (iso, i))))
                else:
                    row.update(resolve(subject, os.path.join(out, "img", "%s_%d.jpg" % (iso, i))))
            except Exception as e:
                row["status"] = "error"
                row["error"] = str(e)[:120]
            rows.append(row)
            # Loud: a verdict reused, or a pinned file the site would drop.
            st = row.get("status") or ""
            loud = st.startswith("known") or (row.get("pinned") and st not in ("ok", "error"))
            print(iso, i, st.upper() if loud else st,
                  row.get("file"), row.get("lapvar"), *(["licence:", row.get("licence")] if "licence" in row else []),
                  flush=True)
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
        # g: each gallery entry's label (a title is its own); pinned: the
        # Commons files a gallery names directly, which the reviewer may
        # want to tell apart from editors' lead images.
        countries = [{"iso": iso, "n": names.get(iso, iso),
                      "g": [gallery_entry.label(e) for e in (acts[iso].get("gallery") or [])[:6]],
                      "pinned": [e.get("file") for e in (acts[iso].get("gallery") or [])[:6]
                                 if gallery_entry.is_file(e)],
                      "p": _places(acts[iso]),
                      "unresolved": [{"idx": r["idx"], "subject": r["subject"], "status": r["status"]}
                                     for r in by[iso] if r["status"] != "ok"]} for iso in part]
        # hero: the 1158x300 strip the desktop hero shows of this photo (rate
        # both; a portrait is flagged because its strip loses the most).
        photos = [{"iso": r["iso"], "country": r["country"], "idx": r["idx"], "subject": r["subject"],
                   "label": r["subject"], "file": r.get("file"), "img": r["img"], "hero": r.get("hero"),
                   "orig": "%sx%s" % (r.get("ow"), r.get("oh")), "aspect": r.get("aspect"),
                   "portrait": r.get("portrait"),
                   "lapvar": r.get("lapvar"), "sat": r.get("sat"), "licence": r.get("licence")}
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
    hits = gone_n = 0
    for iso in sorted(acts):
        if only and iso not in only:
            continue
        for subject in (acts[iso].get("gallery") or [])[:6]:
            name = gallery_entry.label(subject)
            gone = None
            try:
                if gallery_entry.is_file(subject):
                    # A pinned file keeps its name, but Commons can delete,
                    # shrink or relicense it under that name.
                    f = gallery_entry.file_key(subject.get("file"))
                    gone = _pinned_gone(subject)
                else:
                    f = page_image(subject).get("pageimage")
            except Exception as e:
                print(iso, name, "error", str(e)[:80])
                time.sleep(PAUSE)
                continue
            time.sleep(PAUSE)
            if f in skip:
                hits += 1
                print(iso, name, "-> SKIPPED FILE", f)
            elif gone:
                gone_n += 1
                print(iso, name, "-> PINNED FILE", gone.upper(), f)
    print(hits, "gallery subjects resolve to a skipped file;", gone_n, "pinned files the site would now leave out")


def cmd_record(argv):
    """Fold new verdicts into photo_verdicts.json; the site's skip list follows."""
    keep, skip = _verdicts()
    mode = None
    for a in argv:
        if a in ("--keep", "--skip"):
            mode = a
        elif mode == "--keep":
            keep.add(a); skip.discard(a)
        elif mode == "--skip":
            skip.add(a); keep.discard(a)
    today = time.strftime("%Y-%m-%d", time.gmtime())
    with open(VERDICTS, "w", encoding="utf-8") as f:
        json.dump({"asof": today, "note": "Every lead image a reviewer has judged: keep = fine for the hero, skip = rejected "
                   "(mirrored to public/photo-skip.json, which the site reads). scripts/photo_sweep.py sweep --changed "
                   "rates only files absent from both lists.", "keep": sorted(keep), "skip": sorted(skip)},
                  f, ensure_ascii=False, indent=0)
    with open(os.path.join(PUBLIC, "photo-skip.json"), "w", encoding="utf-8") as f:
        json.dump({"asof": today, "files": sorted(skip)}, f, ensure_ascii=False, indent=0)
    print("verdicts: %d keep, %d skip; public/photo-skip.json rewritten" % (len(keep), len(skip)))


if __name__ == "__main__":
    cmds = {"resolve": cmd_resolve, "sweep": cmd_sweep, "batches": cmd_batches, "skip-check": cmd_skip_check,
            "record": cmd_record}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        print(__doc__)
        sys.exit(2)
    cmds[sys.argv[1]](sys.argv[2:])
