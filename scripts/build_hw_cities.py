#!/usr/bin/env python3
"""Build public/hw-cities.json: for each guide's stay spots (public/stay-coords.json,
the "Where to stay" chips), the Hostelworld city page the Hostelworld button
opens when that chip is chosen. A spot with no Hostelworld city page of its
own gets none, and the button keeps the country page (app.js hostelworldURL).

    {"JP": {"Kyoto": "asia/japan/kyoto", "Tokyo": "asia/japan/tokyo", ...}, ...}

The value is the page's path under https://www.hostelworld.com/hostels/.

The source is Hostelworld's own list of city pages, its public sitemap
(robots.txt names the index; the HW_COUNTRY slugs in app.js came from it
too). Its city pages are /hostels/<continent>/<country>/<city>/; the
/r/ and /a/ pages beside them are Hostelworld's regions and areas (Japan's
r/hokkaido, Austria's a/tyrol) and are never used. The city pages read from
it are kept in scripts/hw-city-pages.txt, so a rebuild needs no network.

A spot maps only to a city page of its own country (app.js HW_COUNTRY; the
UK's guide also looks in Scotland, Wales and Northern Ireland), when:
  * its name is the city's, once both are folded (accents, case, "&",
    apostrophes, punctuation) and plain qualifiers are dropped: a
    parenthesis, a leading "Old", a trailing "City", "Old Town" or "Old
    City" (QUALIFIERS: "Ho Chi Minh City" is Hostelworld's ho-chi-minh); or
  * ALIASES below names the city, each with its reason: the same city
    spelt another way (Marrakesh, Odesa); a district or landmark inside it
    or at its edge (Prague's Charles Bridge, Sintra's Pena Palace);
    Hostelworld's page carrying the place's own name (Kruger, Glencoe at
    the foot of Glen Coe); a territory Hostelworld lists as one city
    (Singapore, Hong Kong); an island whose one town it is (Ambergris
    Caye's San Pedro).
A region, an island group, a national park, a mountain or a coast never
maps to a city picked from it (Hokkaido, Ha Long Bay, Bale Mountains): when
in doubt a spot gets nothing and the country page stays.

Run from the repo root with /usr/bin/python3:
  /usr/bin/python3 scripts/build_hw_cities.py               # rebuild public/hw-cities.json (offline)
  /usr/bin/python3 scripts/build_hw_cities.py --check       # the file is a rebuild's, byte for byte (offline)
  /usr/bin/python3 scripts/build_hw_cities.py --report      # every spot: mapped how, or why not
  /usr/bin/python3 scripts/build_hw_cities.py --pages DIR   # first re-read scripts/hw-city-pages.txt from
                                                            # saved sitemap copies in DIR (offline)
  /usr/bin/python3 scripts/build_hw_cities.py --fetch DIR   # download robots.txt, the sitemap index and the
                                                            # sitemaps holding the hostel city pages into DIR
                                                            # (one at a time, a pause between), then as --pages
Re-run (offline) when stay-coords.json or ALIASES change; --fetch only when
Hostelworld's cities may have changed. app.js keeps the file's countries
(HW_ANY, for the empty block's hold before the file lands): every run says
when that list no longer matches and prints the one to paste (--check fails
on it; then rebuild app.min.js with scripts/build_min_js.py).
"""

import gzip
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
OUT = os.path.join(PUBLIC, "hw-cities.json")
PAGES = os.path.join(ROOT, "scripts", "hw-city-pages.txt")
SITE = "https://www.hostelworld.com"
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
PAUSE_S = 3
MAX_SITEMAPS = 14
CONTINENTS = ("europe", "asia", "africa", "north-america", "south-america", "oceania")
# A hostel city page: /hostels/<continent>/<country>/<city>/ (not r/ or a/,
# Hostelworld's regions and areas, nor a city's f/ filter or d/ district pages).
CITY_RE = re.compile(r"^%s/hostels/(%s)/([a-z0-9-]+)/([a-z0-9-]+)/$" % (re.escape(SITE), "|".join(CONTINENTS)))
LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")


# --- the sitemap ---------------------------------------------------------------------------
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read()


def _locs(raw):
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return [html.unescape(u) for u in LOC_RE.findall(raw.decode("utf-8", "replace"))]


def _name(url):
    return url.rstrip("/").rsplit("/", 1)[-1]


def fetch(folder):
    """robots.txt -> its Sitemap index -> the sitemaps in the index's order,
    one at a time with PAUSE_S between, saved as served. The index lists
    every page by level (countries, regions, then cities, then hostels), so
    it stops at the first sitemap after the hostel city pages end."""
    os.makedirs(folder, exist_ok=True)
    robots = _get(SITE + "/robots.txt")
    open(os.path.join(folder, "robots.txt"), "wb").write(robots)
    index = [l.split(":", 1)[1].strip() for l in robots.decode("utf-8", "replace").splitlines()
             if l.lower().startswith("sitemap:")]
    if not index:
        sys.exit("robots.txt names no sitemap")
    time.sleep(PAUSE_S)
    raw = _get(index[0])
    open(os.path.join(folder, _name(index[0])), "wb").write(raw)
    seen_city = False
    for n, url in enumerate(_locs(raw)[:MAX_SITEMAPS]):
        time.sleep(PAUSE_S)
        body = _get(url)
        open(os.path.join(folder, _name(url)), "wb").write(body)
        locs = _locs(body)
        cities = sum(1 for u in locs if CITY_RE.match(u))
        print("  %s: %d pages, %d hostel city pages" % (_name(url), len(locs), cities), flush=True)
        if cities:
            seen_city = True
        # Done once a sitemap moves past them: hotels' city pages, or the hostels.
        past = any(re.match(r"^%s/(hotels|bed-and-breakfasts)/[^/]+/[^/]+/(?!r/|a/)[^/]+/$" % re.escape(SITE), u)
                   or "/hostels/p/" in u for u in locs)
        if seen_city and (not cities or past):
            break


def read_pages(folder):
    """The hostel city pages in the saved sitemaps, in the index's order."""
    names = sorted(os.listdir(folder))
    index = next((n for n in names if n.endswith("-index.xml") or n == "sitemap-index.xml"), None)
    order = [_name(u) for u in _locs(open(os.path.join(folder, index), "rb").read())] if index else names
    out = []
    for n in order:
        p = os.path.join(folder, n)
        if os.path.exists(p):
            out += [m.group(1) + "/" + m.group(2) + "/" + m.group(3)
                    for m in map(CITY_RE.match, _locs(open(p, "rb").read())) if m]
    return out


def write_pages(pages, folder):
    pages = sorted(set(pages))
    with open(PAGES, "w", encoding="utf-8") as f:
        f.write("# Hostelworld's hostel city pages (/hostels/<path>/), from its sitemap\n"
                "# (robots.txt -> %s), read by scripts/build_hw_cities.py --pages.\n"
                "# %d pages. Regenerated, never edited by hand.\n" % (_name(SITE + "/sitemap-index.xml"), len(pages)))
        f.write("".join(p + "\n" for p in pages))
    print("%s: %d city pages from %s" % (os.path.relpath(PAGES, ROOT), len(pages), folder))


# --- matching ------------------------------------------------------------------------------
# Hostelworld countries a guide looks in besides app.js HW_COUNTRY's: the UK
# guide's places can be in Scotland, Wales or Northern Ireland (Hostelworld
# files them apart from England), and Hostelworld lists East Timor's towns
# under Asia and Oceania alike.
EXTRA_COUNTRIES = {
    "GB": ["europe/scotland", "europe/wales", "europe/northern-ireland"],
    "TL": ["asia/east-timor"],
}
# Folds for letters NFKD leaves whole.
_LETTERS = str.maketrans({"ø": "o", "æ": "ae", "œ": "oe", "ß": "ss", "ł": "l", "đ": "d", "ð": "d",
                          "þ": "th", "ı": "i", "ħ": "h"})
# A place's plain qualifiers, tried off only when the whole name finds no page.
QUALIFIERS = [(r"^old ", ""), (r" old (?:town|city)$", ""), (r" city$", "")]
# Hostelworld's own qualifiers on a page's name: "boracay-island" is Boracay.
PAGE_SUFFIXES = ("-island", "-city")


def fold(s):
    """A name as a Hostelworld path segment: "Český Krumlov" -> cesky-krumlov,
    "Cox's Bazar" -> coxs-bazar, "Ha Long" -> ha-long."""
    s = unicodedata.normalize("NFKD", str(s or "").casefold().translate(_LETTERS))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ")
    s = re.sub(r"['’ʻ`]", "", s)
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def plain(name):
    """A spot's name less any parenthesis: "Tara (Drina)" -> "Tara"."""
    return re.sub(r"\s*\([^)]*\)", "", str(name or "")).strip()


def name_keys(name):
    """The keys a spot's name is looked up by, best first."""
    base = plain(name).casefold()
    keys = [fold(base)]
    for pat, rep in QUALIFIERS:
        k = fold(re.sub(pat, rep, base))
        if k and k not in keys:
            keys.append(k)
    return keys


def hw_country(app_js=None):
    """app.js HW_COUNTRY: {iso: "<continent>/<country>[/<city>]"}, read from
    its add("<continent>", "ISO:slug ...") lines."""
    if app_js is None:
        with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
            app_js = f.read()
    m = re.search(r"^const HW_COUNTRY = \(\(\) => \{(.*?)^\}\)\(\);", app_js, re.M | re.S)
    if not m:
        sys.exit("app.js: no HW_COUNTRY block")
    out = {}
    for cont, body in re.findall(r'add\("([a-z-]+)",\s*((?:"[^"]*"\s*\+?\s*)+)\)', m.group(1)):
        for pair in "".join(re.findall(r'"([^"]*)"', body)).split():
            iso, slug = pair.split(":")
            out[iso] = cont + "/" + slug
    return out


def read_city_pages(path=PAGES):
    with open(path, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def page_index(pages, countries):
    """{key: page} for the city pages in `countries` (continent/country
    paths): each page by its own city name, then (where no page has that
    name) by its name less Hostelworld's -island / -city."""
    own = [p for p in pages if p.rsplit("/", 1)[0] in countries]
    idx = {p.rsplit("/", 1)[1]: p for p in own}
    trimmed = {}
    for p in own:
        city = p.rsplit("/", 1)[1]
        for suf in PAGE_SUFFIXES:
            if city.endswith(suf):
                trimmed.setdefault(city[: -len(suf)], []).append(p)
    for k, ps in trimmed.items():
        if k not in idx and len(ps) == 1:
            idx[k] = ps[0]
    return idx


def spots_of(coords, iso):
    s = coords.get(iso)
    if isinstance(s, dict):
        s = [{"n": s.get("near"), "ll": s.get("ll")}]
    return [x for x in s or [] if isinstance(x, dict) and x.get("n") and x.get("ll")]


def build(coords, pages, hw, aliases=None):
    """({iso: {spot name: page path}}, [(iso, name, page or None, how)])."""
    aliases = ALIASES if aliases is None else aliases
    pageset = set(pages)
    out, rows = {}, []
    for iso in sorted(coords):
        spots = spots_of(coords, iso)
        if not spots:
            continue
        home = hw.get(iso)
        if not home:
            rows += [(iso, s["n"], None, "no Hostelworld country page") for s in spots]
            continue
        if home.count("/") != 1:
            # Guernsey, Jersey, the Isle of Man and Curaçao: their "country" is
            # itself a city page (england/guernsey), so the button already opens it.
            rows += [(iso, s["n"], None, "the country page is already a city page (%s)" % home) for s in spots]
            continue
        countries = [home] + EXTRA_COUNTRIES.get(iso, [])
        idx = page_index(pages, countries)
        for s in spots:
            name, page, how = s["n"], None, None
            al = (aliases.get(iso) or {}).get(name)
            if name in NOT_THE_CITY.get(iso, {}):
                how = "not the city of that name: " + NOT_THE_CITY[iso][name]
            elif al:
                target = al[0] if "/" in al[0] else home + "/" + al[0]
                if target not in pageset or target.rsplit("/", 1)[0] not in countries:
                    sys.exit("alias %s %r -> %s: not a city page of %s" % (iso, name, target, countries))
                page, how = target, "alias: " + al[1]
            else:
                keys = name_keys(name)
                k = next((k for k in keys if k in idx), None)
                if k:
                    page, city = idx[k], idx[k].rsplit("/", 1)[1]
                    how = ("same name" if k == keys[0] and city == k
                           else "same name, Hostelworld's page adds \"%s\"" % city[len(k):] if city != k
                           else "same name less a qualifier (%s -> %s)" % (name, k))
            if page:
                out.setdefault(iso, {})[name] = page
            rows.append((iso, name, page, how or "no city page by that name"))
    return out, rows


def dump(data):
    """The file's bytes: one country a line, so a diff reads by country."""
    lines = ["{"]
    items = sorted(data.items())
    for n, (iso, m) in enumerate(items):
        lines.append("%s: %s%s" % (json.dumps(iso), json.dumps(m, ensure_ascii=False, sort_keys=True,
                                                              separators=(",", ":")), "," if n < len(items) - 1 else ""))
    lines.append("}")
    return "\n".join(lines) + "\n"


def hw_any_js(data):
    """app.js's HW_ANY block for these countries, as it is to be pasted."""
    lines, cur = [], []
    for iso in sorted(data):
        cur.append(iso)
        if len(" ".join(cur)) > 88:
            lines.append(" ".join(cur))
            cur = []
    if cur:
        lines.append(" ".join(cur))
    body = " +\n    ".join('"%s%s"' % (l, " " if n < len(lines) - 1 else "") for n, l in enumerate(lines))
    return 'const HW_ANY = (() => {\n  return new Set((' + body + ').split(" "));\n})();'


def app_hw_any(app_js=None):
    """The countries in app.js's HW_ANY, or None without the block."""
    if app_js is None:
        with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
            app_js = f.read()
    m = re.search(r"^const HW_ANY = \(\(\) => \{\n(.*?)^\}\)\(\);$", app_js, re.M | re.S)
    return set("".join(re.findall(r'"([^"]*)"', m.group(1))).split()) if m else None


def load_inputs():
    with open(os.path.join(PUBLIC, "stay-coords.json"), encoding="utf-8") as f:
        coords = json.load(f)
    return coords, read_city_pages(), hw_country()


def main(argv):
    args = list(argv)
    if "--fetch" in args:
        folder = args[args.index("--fetch") + 1]
        fetch(folder)
        write_pages(read_pages(folder), folder)
    elif "--pages" in args:
        folder = args[args.index("--pages") + 1]
        write_pages(read_pages(folder), folder)
    coords, pages, hw = load_inputs()
    data, rows = build(coords, pages, hw)
    text = dump(data)
    if "--report" in args:
        for iso, name, page, how in rows:
            print("%-6s %-45s %-50s %s" % (iso, name, page or "-", how))
    mapped = sum(len(v) for v in data.values())
    print("%d of %d spots map to a Hostelworld city page, in %d of %d countries with spots"
          % (mapped, len(rows), len(data), len({r[0] for r in rows})))
    in_app = app_hw_any()
    app_ok = in_app == set(data)
    if not app_ok:
        print("public/app.js HW_ANY is not this file's countries (only in app.js: %s; missing: %s). Paste:\n%s"
              % (sorted((in_app or set()) - set(data)), sorted(set(data) - (in_app or set())), hw_any_js(data)))
    if "--check" in args:
        if not app_ok:
            sys.exit("public/app.js HW_ANY: paste the block above, then /usr/bin/python3 scripts/build_min_js.py")
        try:
            with open(OUT, encoding="utf-8") as f:
                cur = f.read()
        except OSError:
            cur = None
        if cur != text:
            sys.exit("public/hw-cities.json is not a rebuild's: run /usr/bin/python3 scripts/build_hw_cities.py")
        print("public/hw-cities.json matches a rebuild")
        return
    if "--report" not in args:
        with open(OUT, "w", encoding="utf-8") as f:
            f.write(text)
        print("wrote", os.path.relpath(OUT, ROOT))


# A spot named differently from its Hostelworld city, by country: the
# city page (its last segment, or a full path under /hostels/ for another
# Hostelworld country) and why it is that city.
ALIASES = {
    # The same city under another spelling or short name.
    "MA": {"Marrakesh": ("marrakech", "Hostelworld spells Marrakesh the French way, Marrakech")},
    "KR": {"Gyeongju": ("gyeong-ju", "Hostelworld writes Gyeongju with a hyphen"),
           "Hongdae": ("seoul", "a district of Seoul (Mapo-gu), around Hongik University")},
    "UA": {"Odesa": ("odessa", "Hostelworld uses the older spelling, Odessa"),
           "Kamianets-Podilskyi Castle": ("kamyanets-podilski", "the castle is in the old town of Kamianets-Podilskyi,"
                                          " which Hostelworld spells Kamyanets-Podilski")},
    "US": {"NYC": ("new-york", "New York City's short name"),
           "Golden Gate Bridge": ("san-francisco", "the bridge's south end is in San Francisco's Presidio")},
    # A district or landmark inside the city's built-up area.
    "AE": {"Dubai Marina": ("dubai", "a district of Dubai"),
           "Burj Al Arab": ("dubai", "on Jumeirah Beach, in Dubai"),
           "Sheikh Zayed Grand Mosque": ("abu-dhabi", "in Abu Dhabi city")},
    "AZ": {"Flame Towers": ("baku", "towers above central Baku")},
    "BN": {"Kampong Ayer": ("bandar-seri-begawan", "the water village in the centre of Bandar Seri Begawan")},
    "CZ": {"Charles Bridge": ("prague", "the bridge in Prague's old town")},
    "DK": {"Nyhavn": ("copenhagen", "the harbour in central Copenhagen")},
    "EE": {"Alexander Nevsky Cathedral": ("tallinn", "on Toompea, Tallinn's old town")},
    "GR": {"Meteora": ("kalambaka", "the monasteries' rocks rise from the edge of Kalambaka, about 1 km from its"
                       " centre")},
    "HU": {"Hungarian Parliament Building": ("budapest", "on the Danube in central Budapest")},
    "MN": {"Erdene Zuu Monastery": ("kharkhorin", "the monastery's walls adjoin Kharkhorin (old Karakorum), under 2 km"
                                    " from its centre"),
           # (the last kind below: Hostelworld's page by the place's own name)
           "Lake Khövsgöl": ("khovsgol", "Hostelworld's page for the same lake (Mörön, the province's capital, has a"
                             " page of its own)")},
    "PA": {"Casco Viejo": ("panama-city", "the old quarter of Panama City")},
    "PL": {"Wawel Castle": ("krakow", "the castle in Kraków's old town")},
    "PT": {"Pena Palace": ("sintra", "the palace on the hill above Sintra's centre, about 1 km off")},
    "RS": {"Skadarlija": ("belgrade", "a street quarter of central Belgrade")},
    "SA": {"Kingdom Centre": ("riyadh", "a tower in central Riyadh")},
    "TW": {"Xinyi District": ("taipei", "a district of Taipei"),
           "Dragon and Tiger Pagodas": ("kaohsiung", "on Lotus Pond, in Kaohsiung's Zuoying district")},
    # A territory Hostelworld lists as one city: its only page there.
    "SG": {"Marina Bay": ("singapore", "Singapore is one city, and Hostelworld lists it as one"),
           "Clarke Quay": ("singapore", "Singapore is one city, and Hostelworld lists it as one"),
           "Sentosa": ("singapore", "Singapore is one city, and Hostelworld lists it as one (Sentosa is joined to"
                       " it by road and monorail)"),
           "Gardens by the Bay": ("singapore", "Singapore is one city, and Hostelworld lists it as one")},
    "HK": {"Victoria Peak": ("hong-kong", "the hill above Central, on Hong Kong Island"),
           "Lantau": ("hong-kong", "Hostelworld lists all of Hong Kong as one city, its only page there (Lantau is"
                      " the territory's biggest island, by MTR from Central)"),
           "Dragon's Back": ("hong-kong", "Hostelworld lists all of Hong Kong as one city, its only page there (a"
                             " ridge walk on Hong Kong Island)"),
           "The Big Buddha": ("hong-kong", "Hostelworld lists all of Hong Kong as one city, its only page there (at"
                              " Ngong Ping, on Lantau)")},
    # An island whose one town is the Hostelworld city.
    "BZ": {"Ambergris Caye": ("san-pedro", "San Pedro is the island's one town (Belize's only San Pedro)")},
    # Hostelworld's page carries the place's own name: the park itself, or
    # the village of that name inside it or at its gate.
    "GB-WLS": {"Snowdonia": ("snowdonia-national-park", "Hostelworld's page for the same national park")},
    "GB-SCT": {"Glen Coe": ("glencoe", "Glencoe, the village of the same name at the foot of the glen")},
    "ZA": {"Kruger National Park": ("kruger-park", "Hostelworld's page for the same park")},
    "FJ": {"Yasawa": ("yasawa-islands", "Hostelworld's page for the same islands")},
    "CR": {"Manuel Antonio National Park": ("manuel-antonio", "Manuel Antonio, the village of the same name at the"
                                            " park's gate")},
    "MK": {"Mavrovo National Park": ("mavrovo", "Mavrovo, the village of the same name inside the park")},
    "HN": {"Copán": ("copan-ruinas", "Copán Ruinas, the town of the same name beside the ruins")},
    "MW": {"Mount Mulanje": ("mulanje", "Mulanje, the town of the same name at the mountain's foot, where its climbs"
                             " start")},
}
# A spot whose name is a Hostelworld city's but whose place is not that
# city: kept out, with why.
NOT_THE_CITY = {
    "BG": {"Rila": "the spot is the Rila mountains (42.1, 23.55); Hostelworld's Rila is the town of Rila, 35 km west"},
}


if __name__ == "__main__":
    main(sys.argv[1:])
