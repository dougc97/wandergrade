"""The hero-photo skip list and the galleries it guards, without the network.

    /usr/bin/python3 scripts/test_photo_skip.py

  * public/photo-skip.json parses, is dated, and lists unique Commons file
    names (no paths, no URLs, no blanks);
  * every country's gallery is 1-6 unique entries, each a Wikipedia title or
    a pinned Commons file {"file", "label"} (scripts/gallery_entry.py): a
    bare file name app.js's PHOTO_BAD passes and the skip list doesn't hold,
    and a label. The licence rule needs the network, so only the shape is
    checked here. Fewer than 4 entries is reported (the 2026-10 sweep could
    not find four good photos for a few small countries), none is a failure;
  * app.js consults the list inside wikiIconic (the hero and the activity
    thumbs both go through it) and gen_og_images.py reads it too;
  * app.js's handling of a file entry, run under jsc on a fixture: the
    Commons imageinfo lookup, the size gate, the skip list, the licence rule
    (one console.info per refused file), the credit it brings along (an
    uploader linked by username credits the name, not "c:User:<name>"), and
    a title still going through pageimages; PHOTO_LICENCE_OK and
    gallery_entry.LICENCE_OK agree on a table of licence names;
  * photo_sweep.py, offline: a kept pinned file Commons has since deleted,
    relicensed or shrunk is flagged, and the hero strip it saves for raters
    is the desktop hero's 1158x300 centre crop.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import gallery_entry  # noqa: E402

ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"

with open(os.path.join(PUBLIC, "photo-skip.json"), encoding="utf-8") as f:
    skip = json.load(f)
files = skip.get("files") or []
results.append(ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", skip.get("asof", "")) is not None, "photo-skip.json carries an as-of date"))
results.append(ok(len(files) == len(set(files)) and len(files) > 100, "%d unique rejected files" % len(files)))
bad = [x for x in files if not x or "/" in x or x.startswith("http") or x != x.strip()]
results.append(ok(not bad, "every entry is a bare Commons file name (%d odd: %s)" % (len(bad), bad[:3])))

with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
    app = f.read()
# The site's own filter, so a pinned name it would drop fails here first.
PHOTO_BAD = re.compile(re.search(r"^const PHOTO_BAD = /(.*)/i;$", app, re.M).group(1), re.I)


def entry_problem(e):
    """Why a gallery entry is malformed, or None."""
    if isinstance(e, str):
        return None if e.strip() else "blank title"
    if not isinstance(e, dict) or set(e) != {"file", "label"}:
        return "not a title or {file, label}: %r" % (e,)
    name, lab = e.get("file"), e.get("label")
    if not isinstance(lab, str) or not lab.strip():
        return "file entry without a label: %r" % (e,)
    if (not isinstance(name, str) or name != name.strip() or not name or name.lower().startswith("file:")
            or "/" in name or name.startswith("http")
            or not re.search(r"\.(jpe?g|png|tiff?|webp)$", name, re.I)):
        return "not a bare Commons photo name: %r" % (name,)
    if PHOTO_BAD.search(name):
        return "PHOTO_BAD drops it: %r" % (name,)
    if gallery_entry.file_key(name) in files:
        return "on the skip list: %r" % (name,)
    return None


with open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8") as f:
    acts = json.load(f)
thin, broken, pinned = [], [], []
for iso, a in sorted(acts.items()):
    g = a.get("gallery") or []
    probs = [p for p in (entry_problem(e) for e in g) if p]
    keys = [gallery_entry.key(e) for e in g if not entry_problem(e)]
    pinned += ["%s:%s" % (iso, e["file"]) for e in g if isinstance(e, dict)]
    if not (1 <= len(g) <= 6) or probs or len(keys) != len(set(keys)):
        broken.append("%s %s" % (iso, probs[:1] or "(count/duplicates)"))
    elif len(g) < 4:
        thin.append("%s:%d" % (iso, len(g)))
results.append(ok(not broken, "every gallery is 1-6 unique titles or pinned files (%s)" % (", ".join(broken) or "all %d" % len(acts))))
print("  note  galleries under 4 subjects: %s" % (", ".join(thin) or "none"))
print("  note  pinned Commons files: %s" % (", ".join(pinned) or "none"))
# The validator itself, on entries no gallery holds today.
CASES = [("Galle Fort", None), ("  ", "blank"), ({"file": "Lumley Beach Freetown.JPG", "label": "Lumley Beach"}, None),
         ({"file": "File:Lumley Beach Freetown.JPG", "label": "Lumley Beach"}, "bare"),
         ({"file": "https://upload.wikimedia.org/x/Lumley.jpg", "label": "Lumley"}, "bare"),
         ({"file": "Lumley Beach Freetown.JPG", "label": ""}, "label"), ({"file": "Lumley.jpg"}, "title or"),
         ({"file": "Sierra Leone location map.jpg", "label": "x"}, "PHOTO_BAD"),
         ({"file": files[0].replace("_", " "), "label": "x"}, "skip list")]
miss = [(e, want, entry_problem(e)) for e, want in CASES
        if (want is None) != (entry_problem(e) is None) or (want and want not in entry_problem(e))]
results.append(ok(not miss, "the entry validator accepts a title and a {file, label}, refuses the malformed (%s)" % (miss[:1] or "%d cases" % len(CASES))))

results.append(ok("photo-skip.json" in app and "photoSkip()" in app and "(await skipP).has(page.pageimage)" in app,
                  "app.js wikiIconic consults the skip list"))


def js_block(head):
    """A top-level function of app.js, by the start of its first line."""
    m = re.search(r"^%s.*?^\}" % re.escape(head), app, re.M | re.S)
    return m.group(0) if m else ""


def js_line(head):   # a one-line top-level statement
    m = re.search(r"^%s.*$" % re.escape(head), app, re.M)
    return m.group(0) if m else ""


wiki = js_block("async function wikiIconic(")
results.append(ok(re.search(r'typeof subject === "object"\) return commonsPhoto\(subject\.file, minW, minH\)', wiki) is not None,
                  "wikiIconic hands a {file, label} entry to commonsPhoto with its size bar"))
results.append(ok(app.count('val("LicenseShortName")') == 1 and "_creditFrom(ii)" in js_block("async function _fetchPhotoCredits("),
                  "one extmetadata credit parser (_creditFrom), shared by the credit batch and commonsPhoto"))

# --- app.js on a fixture, under jsc ---------------------------------------------------
UP = "https://upload.wikimedia.org/wikipedia/commons/"


USER_ARTIST = ('<p>photo <a href="https://commons.wikimedia.org/wiki/User:Aboubacarkhoraa" class="extiw" '
               'title="c:User:Aboubacarkhoraa">c:User:Aboubacarkhoraa</a>, correction de perspective '
               '<a href="https://commons.wikimedia.org/wiki/User:GrandEscogriffe" class="extiw" '
               'title="c:User:GrandEscogriffe">c:User:GrandEscogriffe</a>\n</p>')


def ii(title, w, h, lic, code, artist='<a href="//commons.wikimedia.org/wiki/User:Jane">Jane <b>Doe</b></a>'):
    """What Commons answers today: thumbwidth/height are the size ASKED for
    (1600, even past a smaller original, which then comes back unscaled), the
    thumb itself is the next fixed step (1920px), utm_* tags on both URLs."""
    n = title[5:].replace(" ", "_")
    utm = "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content="
    return {"title": title, "imageinfo": [{
        "thumburl": (UP + "thumb/a/ab/%s/1920px-%s" % (n, n) + utm + "thumbnail") if w > 1600
        else UP + "a/ab/" + n + utm + "thumbnail_unscaled",
        "thumbwidth": 1600, "thumbheight": round(h * 1600 / w), "url": UP + "a/ab/" + n + utm + "original",
        "width": w, "height": h,
        "descriptionurl": "https://commons.wikimedia.org/wiki/File:" + n,
        "extmetadata": {"Artist": {"value": artist}, "LicenseShortName": {"value": lic},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by/2.0"}, "License": {"value": code}}}]}


FIX = {t.lower(): v for t, v in {
    "File:Beach in Freetown.jpg": ii("File:Beach in Freetown.jpg", 4000, 2248, "CC BY 2.0", "cc-by-2.0"),
    "File:Gfdl only.jpg": ii("File:Gfdl only.jpg", 3000, 2000, "GFDL 1.2", "gfdl"),
    "File:Skipped beach.jpg": ii("File:Skipped beach.jpg", 3000, 2000, "CC BY-SA 4.0", "cc-by-sa-4.0"),
    "File:Small beach.jpg": ii("File:Small beach.jpg", 640, 427, "CC BY-SA 3.0", "cc-by-sa-3.0"),
    "File:Old Freetown.jpg": ii("File:Old Freetown.jpg", 1827, 1095, "Public domain", "pd"),
    # Guinea's Grand Mosque credits its uploaders by interwiki user link.
    "File:Grand mosque.jpg": ii("File:Grand mosque.jpg", 1358, 1024, "CC-BY-SA-4.0", "cc-by-sa-4.0", USER_ARTIST),
}.items()}
GALLERY = ["Mount Bintumani", {"file": "beach in Freetown.jpg", "label": "Lumley Beach"}]
prog = r"""
const FIX = %s, SKIP = ["Skipped_beach.jpg"], calls = [], logs = [];
globalThis.console = { info: (...a) => logs.push(a.join(" ")) };
class DOMParser { parseFromString(s) { return { body: { textContent: String(s).replace(/<[^>]*>/g, "") } }; } }
const answer = (j) => Promise.resolve({ ok: true, json: () => Promise.resolve(j) });
function fetch(url) {
  calls.push(url);
  if (url === "/photo-skip.json") return answer({ files: SKIP });
  const t = decodeURIComponent((url.match(/[?&]titles=([^&]*)/) || [])[1] || "");
  if (url.startsWith("https://commons.wikimedia.org/w/api.php"))
    return answer({ query: { pages: { "-1": FIX[t.toLowerCase()] || { title: t, missing: "" } } } });
  if (url.includes("prop=pageimages"))
    return answer({ query: { pages: { "7": { title: t, pageimage: "Bintumani_lead.jpg",
      thumbnail: { source: "%sthumb/c/cd/Bintumani_lead.jpg/1600px-Bintumani_lead.jpg", width: 1600, height: 1067 },
      original: { source: "%sc/cd/Bintumani_lead.jpg", width: 4000, height: 2667 } } } } });
  return answer({});
}
let activities = { SL: { gallery: %s } };
%s
(async () => {
  const o = {};
  o.subjects = photoSubjects("SL");
  o.title = await wikiIconic("Mount Bintumani");
  o.titleUrl = calls.find((u) => u.includes("prop=pageimages")) || "";
  o.ok = await wikiIconic(o.subjects[1]);
  o.okUrl = calls.find((u) => u.startsWith("https://commons.wikimedia.org/")) || "";
  o.credit = photoCreditHTML(o.ok);
  const n = calls.length; await loadPhotoCredits([o.ok]); o.creditCalls = calls.length - n;
  o.gfdl = await wikiIconic({ file: "Gfdl only.jpg", label: "x" });
  o.gfdl2 = await wikiIconic({ file: "Gfdl only.jpg", label: "x" });
  o.skipped = await wikiIconic({ file: "Skipped beach.jpg", label: "x" });
  o.small = await wikiIconic({ file: "Small beach.jpg", label: "x" });
  o.smallThumb = await wikiIconic({ file: "Small beach.jpg", label: "x" }, 600, 400);
  const before = calls.length;
  o.bad = await wikiIconic({ file: "Freetown location map.jpg", label: "x" });
  o.badCalls = calls.length - before;
  o.missing = await wikiIconic({ file: "No such file.jpg", label: "x" });
  o.pd = await wikiIconic({ file: "Old Freetown.jpg", label: "x" });
  o.userCredit = photoCreditHTML(await wikiIconic({ file: "Grand mosque.jpg", label: "x" }));
  o.logs = logs;
  o.lic = %s.map((s) => PHOTO_LICENCE_OK.test(s));
  o.keys = [o.ok.thumb, o.ok.full, o.title.full.replace("en.wikipedia.org", "commons.wikimedia.org"),
            "%sthumb/a/ab/Beach_in_Freetown.jpg/1920px-Beach_in_Freetown.jpg?utm_source=en.wikipedia.org"].map(fileKey);
  print(JSON.stringify(o));
})().catch((e) => print(JSON.stringify({ error: String(e) })));
"""
LICENCES = {"CC BY-SA 4.0": True, "cc-by-sa-4.0": True, "CC BY 2.0": True, "cc-by-2.0": True, "CC BY 4.0": True,
            "CC BY-SA 3.0 IGO": True, "cc-by-sa-3.0-de": True, "CC BY-SA 2.5 es": True, "CC BY-SA 2.0 uk": True,
            "CC0": True, "cc0": True, "CC0 1.0": True, "Public domain": True, "pd": True, "Public Domain Mark 1.0": True,
            "CC BY-NC 2.0": False, "cc-by-nc-sa-2.0": False, "CC BY-ND 4.0": False, "cc-by-nd": False,
            "CC BY-NC-SA 4.0": False, "GFDL": False, "GFDL 1.2": False, "FAL": False, "Attribution": False,
            "": False, "CC BY-SA 4.0 or GFDL": False, "Copyrighted free use": False}
parts = [js_line("const esc = ") + "\n" + js_line('  (c) => ({ "&": "&amp;"'),
         js_line("const PHOTO_BAD = "), js_line("const PHOTO_LICENCE_OK = "), js_line("let _photoSkip = "),
         js_block("function photoSkip("), js_block("function photoSubjects("), js_block("async function wikiIconic("),
         js_line("const _licenceRefused = "), js_block("async function commonsPhoto("), js_line("const _photoCredit = "),
         js_block("function _plainText("), js_line("const _photoCreditP = "), js_block("function loadPhotoCredits("),
         js_block("async function _fetchPhotoCredits("), js_block("function _creditFrom("), js_block("function photoCreditHTML("),
         js_block("const fileKey = ")]
cut_ok = all(parts)
o = None
if cut_ok:
    src = prog % (json.dumps(FIX), UP, UP, json.dumps(GALLERY), "\n".join(parts), json.dumps(list(LICENCES)), UP)
    try:
        o = json.loads(subprocess.run([JSC, "-e", src], capture_output=True, text=True, timeout=30).stdout)
    except Exception as e:
        o = {"error": str(e)[:200]}
results.append(ok(cut_ok and o is not None and "error" not in o, "the photo functions run under jsc on the fixture (%s)"
                  % ((o or {}).get("error") or ("cut %d/%d" % (sum(map(bool, parts)), len(parts))))))
o = o if isinstance(o, dict) and "error" not in o else {}
results.append(ok(o.get("subjects") == GALLERY, "photoSubjects hands the gallery's entries over as they are"))
results.append(ok((o.get("title") or {}).get("file") == "Bintumani_lead.jpg" and "titles=Mount%20Bintumani" in o.get("titleUrl", ""),
                  "a title still resolves through pageimages"))
UTM = "?utm_source=commons.wikimedia.org&utm_campaign=imageinfo&utm_content="
want = {"thumb": UP + "thumb/a/ab/Beach_in_Freetown.jpg/1920px-Beach_in_Freetown.jpg" + UTM + "thumbnail",
        "full": UP + "a/ab/Beach_in_Freetown.jpg" + UTM + "original", "file": "Beach_in_Freetown.jpg"}
results.append(ok(o.get("ok") == want, "a file entry gives {thumb, full original, file canonical} (%s)" % o.get("ok")))
results.append(ok(o.get("keys") == ["Beach_in_Freetown.jpg", "Beach_in_Freetown.jpg", "Bintumani_lead.jpg", "Beach_in_Freetown.jpg"],
                  "fileKey names the file from a thumb or an original, whatever utm tail (the hero/activity de-dupe) (%s)" % o.get("keys")))
u = o.get("okUrl", "")
results.append(ok("prop=imageinfo" in u and "iiprop=url|size|extmetadata" in u and "iiurlwidth=1600" in u
                  and "titles=File%3Abeach%20in%20Freetown.jpg" in u, "it asks Commons imageinfo for File:<name> at 1600px"))
cr = o.get("credit", "")
results.append(ok('href="https://commons.wikimedia.org/wiki/File:Beach_in_Freetown.jpg"' in cr and ">Jane Doe</a>" in cr
                  and ">CC BY 2.0</a>" in cr and o.get("creditCalls") == 0,
                  "its credit line prints author + licence from the same answer, no second request (%s)" % cr))
results.append(ok(o.get("gfdl") is None and o.get("gfdl2") is None and len(o.get("logs") or []) == 1
                  and "File:Gfdl_only.jpg" in (o.get("logs") or [""])[0],
                  "a GFDL-only file is left out with one console.info naming it (%s)" % (o.get("logs") or [""])[:1]))
results.append(ok("skipped" in o and o["skipped"] is None, "the skip list applies to a pinned file"))
results.append(ok("small" in o and o["small"] is None and (o.get("smallThumb") or {}).get("file") == "Small_beach.jpg",
                  "the size gate reads the real thumb (a 640px original asked at 1600 fails the hero's 800, passes 600x400)"))
results.append(ok("bad" in o and o["bad"] is None and o.get("badCalls") == 0, "PHOTO_BAD drops a pinned name before any request"))
results.append(ok("missing" in o and o["missing"] is None and (o.get("pd") or {}).get("file") == "Old_Freetown.jpg",
                  "a missing file is null; a public-domain file shows"))
uc = o.get("userCredit", "")
results.append(ok(">photo Aboubacarkhoraa, correction de perspective GrandEsco…</a>" in uc and "User:" not in uc
                  and gallery_entry._plain(USER_ARTIST) == "photo Aboubacarkhoraa, correction de perspective GrandEscogriffe",
                  "a credit linking uploaders by username prints the names, not raw c:User: text (%s)" % re.sub(r"<[^>]+>", "", uc)))
py_lic = [bool(gallery_entry.LICENCE_OK.match(s)) for s in LICENCES]
results.append(ok(o.get("lic") == list(LICENCES.values()) and py_lic == list(LICENCES.values()),
                  "PHOTO_LICENCE_OK and gallery_entry.LICENCE_OK: CC BY / BY-SA (any version, port), CC0, PD in; NC, ND, GFDL, FAL out"
                  + ("" if py_lic == list(LICENCES.values()) == o.get("lic") else " js %s py %s" % (o.get("lic"), py_lic))))

# photo_sweep's drift check on a kept pinned file (sweep --changed, skip-check),
# offline: Commons' answer for a deleted, relicensed or shrunk file.
import photo_sweep  # noqa: E402
FAKE = {"Fine.jpg": ("u/1920px-Fine.jpg", 1600, 1067, "CC BY 2.0"), "Deleted.jpg": ("", 0, 0, ""),
        "Relicensed.jpg": ("u/1920px-Relicensed.jpg", 1600, 1067, "GFDL 1.2"),
        "Shrunk.jpg": ("u/Shrunk.jpg", 640, 427, "CC BY-SA 4.0")}
_real = gallery_entry.commons_file
gallery_entry.commons_file = lambda name, w, ua: dict(zip(("thumb", "tw", "th", "lic"), FAKE[name]), title="File:" + name,
                                                      file=name, url="", ow=FAKE[name][1], oh=FAKE[name][2], code="")
try:
    drift = {n: photo_sweep._pinned_gone({"file": n, "label": "x"}) for n in FAKE}
finally:
    gallery_entry.commons_file = _real
results.append(ok(drift == {"Fine.jpg": None, "Deleted.jpg": "no-image", "Relicensed.jpg": "bad-licence", "Shrunk.jpg": "too-small"},
                  "photo_sweep flags a kept pinned file Commons deleted, relicensed or shrank (%s)" % drift))
from PIL import Image  # noqa: E402
strips = [photo_sweep.hero_crop(Image.new("RGB", wh)).size for wh in ((800, 930), (800, 535), (800, 150))]
results.append(ok(all(abs(w / h - 1158 / 300) < 0.03 for w, h in strips) and strips[0][0] == 800 and strips[2][1] == 150,
                  "photo_sweep's hero strip is the desktop hero's 1158x300 centre crop (%s)" % strips))

with open(os.path.join(ROOT, "scripts", "gen_og_images.py"), encoding="utf-8") as f:
    og = f.read()
results.append(ok("photo-skip.json" in og and "in SKIP" in og, "gen_og_images.py reads the skip list"))
results.append(ok(acts["PH"]["gallery"][0] == "El Nido, Palawan" and acts["PH"]["gallery"][1] == "Mayon",
                  "the Philippines keeps Doug's order: El Nido, then Mayon"))

with open(os.path.join(ROOT, "scripts", "photo_verdicts.json"), encoding="utf-8") as f:
    verdicts = json.load(f)
results.append(ok(sorted(verdicts.get("skip") or []) == sorted(files) and not (set(verdicts.get("keep") or []) & set(files)),
                  "photo_verdicts.json mirrors the skip list and keeps nothing it rejects (%d keep)" % len(verdicts.get("keep") or [])))
print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
