"""Gallery entries (public/activities.json[iso].gallery) for the scripts.

An entry is a Wikipedia page TITLE, and the guide hero shows that page's lead
image; or, where no page leads with a good photo of a place,
{"file": "<Commons file name, no File: prefix>", "label": "<place name>"}:
one Commons photo pinned by name. The site reads entries in public/app.js
(wikiIconic, commonsPhoto); these helpers keep the scripts (photo_sweep,
gen_og_images, gen_stay_spots, test_photo_skip) reading them the same way.
"""
import json
import re
import urllib.parse
import urllib.request

# Mirrors PHOTO_LICENCE_OK in app.js: CC BY and CC BY-SA in any version or
# port (the credit line gives the author, licence and link they ask for), CC0
# and public domain; tested against extmetadata's short name and its code.
LICENCE_OK = re.compile(
    r"^(?:cc[- ]by(?:-sa)?(?:[- ]\d(?:\.\d)?(?:[- ](?:[a-z]{2}|igo))?)?|cc0(?:[- ]1\.0)?"
    r"|pd(?:[- ][a-z0-9.-]+)?|public domain(?: mark(?: 1\.0)?)?)$", re.I)


def is_file(entry):
    return isinstance(entry, dict)


def label(entry):
    """The place an entry shows: the title itself, or a file entry's label."""
    return (entry.get("label") or "") if isinstance(entry, dict) else (entry or "")


def file_key(name):
    """A Commons file name as page.pageimage and the skip list spell it:
    no File: prefix, underscores, first letter capitalised."""
    n = re.sub(r"^file:", "", (name or "").strip(), flags=re.I).replace(" ", "_")
    return n[:1].upper() + n[1:]


def key(entry):
    """What makes two entries the same subject (galleries list each once)."""
    return "File:" + file_key(entry.get("file")) if isinstance(entry, dict) else entry


def licence_ok(short, code):
    return bool(LICENCE_OK.match((short or "").strip()) or LICENCE_OK.match((code or "").strip()))


def _plain(v):
    """Tag-free text, as app.js _plainText() prints a credit: a wiki-username
    link's raw "c:User:" prefix dropped, so the name alone credits."""
    t = re.sub(r"\b(?:(?:c|commons|w|en):)?User:(?=\S)", "", re.sub(r"<[^>]+>", "", str(v or "")), flags=re.I)
    return re.sub(r"\s+", " ", t).strip()


def commons_file(name, width, ua):
    """Commons imageinfo for one pinned file, the record commonsPhoto() gates
    on: thumb (width px), its size, the original, the credit fields."""
    api = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
           "&iiprop=url|size|extmetadata&iiurlwidth=%d"
           "&iiextmetadatafilter=Artist|LicenseShortName|LicenseUrl|License&titles=%s"
           % (width, urllib.parse.quote("File:" + (name or "").strip())))
    req = urllib.request.Request(api, headers={"User-Agent": ua})
    page = next(iter(json.load(urllib.request.urlopen(req, timeout=30))["query"]["pages"].values()))
    ii = (page.get("imageinfo") or [{}])[0]
    md = ii.get("extmetadata") or {}
    val = lambda k: _plain((md.get(k) or {}).get("value"))
    return {"title": page.get("title"), "file": file_key(page.get("title") or name),
            # The API tacks utm_* params onto thumb URLs; keep them clean.
            "thumb": (ii.get("thumburl") or "").split("?")[0],
            # thumbwidth is the size ASKED for (1600 even for a 448px original,
            # served unscaled): the real thumb is capped by the original.
            "tw": min(ii.get("thumbwidth") or 0, ii.get("width") or 0),
            "th": min(ii.get("thumbheight") or 0, ii.get("height") or 0),
            "url": ii.get("url"), "ow": ii.get("width"), "oh": ii.get("height"),
            "artist": val("Artist"), "lic": val("LicenseShortName"), "code": val("License"),
            "page": ii.get("descriptionurl")}
