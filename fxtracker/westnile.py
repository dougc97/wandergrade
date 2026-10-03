"""West Nile virus: where it is reaching people this season -> health.json "w".

Canada's travel health pages (build_health.py's source) list West Nile for none
of their 230 countries, yet it is the mosquito-borne virus a summer trip to
Italy, Greece or Texas is most likely to meet. Two agencies publish, as data and
during the season, where people are catching it; this module reads both and
says only what they say, attributed ("ECDC: …", "CDC: …"). Countries neither
agency covers are simply absent — w.note says so, because no entry must not
read as "no West Nile here".

Sources
  ECDC weekly report — human West Nile infections in the EU/EEA and the
    EU-neighbouring countries ECDC follows (Albania, Bosnia and Herzegovina,
    Kosovo, Montenegro, North Macedonia, Serbia, Türkiye). Published Fridays,
    June to November; the last weekly report of a season stays up until the
    next season's first (Week 50, 2025 was still the live page in March 2026).
      Page/data: https://wnv-weekly.ecdc.europa.eu/  (one self-contained page)
      Link for people: https://www.ecdc.europa.eu/en/west-nile-fever/surveillance-and-disease-data/disease-data-ecdc
    The page's "Download the data" button carries the table as a base64
    data.csv — one row per affected NUTS3/GAUL1 area with probable, confirmed
    and total locally acquired cases and the ISO week. That CSV is what's
    parsed (the DataTables widget holding the same table is the fallback). A
    country's case total comes from the page's own summary sentence when it
    gives one, because the areas don't always add up to it: Week 37, 2026 says
    "Greece (319 cases, of which 9 had an unknown place of infection)" while
    Greece's 21 areas sum to 310.
    Licence: ECDC content is CC BY 4.0; for the data ECDC asks for "Dataset
    provided by ECDC based on data provided by public health authorities,
    scientific institutes or health care providers in the relevant reporting
    countries and/or by WHO." Per-country sums and a top-10 area list are an
    adaptation, which CC BY asks us to say where it's shown.
  CDC ArboNET "Current Year Data" — West Nile human disease cases by state of
    residence, updated every one to two weeks June to December.
      Page: https://www.cdc.gov/west-nile-virus/data-maps/current-year-data.html
      Data: https://www.cdc.gov/wcms/vizdata/live/ncezid_dvbd/WNV/wnv_hum_current_CountbyState.csv
    The page's map reads that CSV; its URL and the year it covers are taken
    from the map's own config (current-data.json) so a renamed file or a new
    year doesn't need a code change. US federal work, public domain; credit
    "CDC ArboNET". Cases are counted where people live, not where they were
    bitten (CDC's own caveat), so the states are "reported from".

Failure modes
  - wnv-weekly.ecdc.europa.eu is on ECDC's own network (88.131.255.x), not the
    CloudFront CDN that serves www.ecdc.europa.eu. On 2026-10-03 it dropped
    connections from this machine and refused Anthropic's fetcher while
    answering probe nodes in the US, UK, Germany and Asia. When the live page
    can't be had, the newest Internet Archive capture of the same page is
    parsed instead (ECDC_ARCHIVE; set it to None to turn that off). It is the
    same ECDC table, just older — which is why every t carries the data's own
    "as of" date. That day the newest capture was Week 37 (data to 10 Sep)
    while ECDC's Week 40 threats report already said 1 765 cases in 16
    countries.
  - ECDC changes the page between seasons and even mid-season: Week 22, 2026
    still had the 2025 columns ("Affected region", "Total cases"); Week 50,
    2025 had no total column at all and said "no totals are provided" — then
    t gives the area count and no case count rather than adding up what ECDC
    chose not to. Columns are matched by keyword, not position.
  - A country name that maps to no ISO is skipped and listed in info["unmapped"]
    (the CLI prints it); every name in the 2025 and 2026 reports maps.
  - Either agency failing leaves the other's countries and a note saying which
    is missing; both failing returns None (contract: w may be absent).

Run:   /usr/bin/python3 -m fxtracker.westnile             summary
       /usr/bin/python3 -m fxtracker.westnile --json      the "w" dict
       ... --built 2026-10-03   --ecdc-file page.html   --no-cdc   --no-ecdc
"""

import base64
import csv
import datetime
import email.utils
import gzip
import html
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request

from . import rates
from .advisories import _name_to_iso, _norm

ECDC_LIVE = "https://wnv-weekly.ecdc.europa.eu/"
# "2id_": the Wayback Machine's newest capture, served byte-for-byte as ECDC
# sent it (gzip included) instead of wrapped in the archive's toolbar.
ECDC_ARCHIVE = "https://web.archive.org/web/2id_/" + ECDC_LIVE
ECDC_URL = "https://www.ecdc.europa.eu/en/west-nile-fever/surveillance-and-disease-data/disease-data-ecdc"
CDC_URL = "https://www.cdc.gov/west-nile-virus/data-maps/current-year-data.html"
CDC_CONFIG = "https://www.cdc.gov/west-nile-virus/data-maps/current-data.json"
CDC_STATES = "https://www.cdc.gov/wcms/vizdata/live/ncezid_dvbd/WNV/wnv_hum_current_CountbyState.csv"

MAX_AREAS = 10
UA = "Mozilla/5.0 (compatible; WanderGrade/1.0; +https://wandergrade.com)"

# ECDC spellings the site's geojson names don't carry.
ALIASES = {"turkiye": "TR", "kosovo": "XK"}

# CDC's postal codes. Territories are their own countries on the site, so
# their cases go on their own ISO, not the US's.
STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}
TERRITORIES = {"PR": "PR", "GU": "GU", "VI": "VI", "AS": "AS", "MP": "MP"}

MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), 1)}


# --- fetching ------------------------------------------------------------------

def _fetch(url, retries=2, timeout=rates.TIMEOUT):
    """GET -> (bytes, headers), gunzipped when the body is gzip (the archive
    serves ECDC's original gzip bytes whatever we ask for)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=rates._SSL) as resp:
                body = resp.read()
                if body[:2] == b"\x1f\x8b":
                    body = gzip.decompress(body)
                return body, resp.headers
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as e:
            last = e
            code = getattr(e, "code", None)
            if code is not None and 400 <= code < 500:
                raise
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise last


def _text(fragment):
    s = re.sub(r"<(script|style)\b.*?</\1>", " ", fragment or "", flags=re.S | re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _int(s):
    digits = re.sub(r"\D", "", str(s or ""))
    return int(digits) if digits else None


def _col(header, *needles, avoid=()):
    """Index of the first column whose name contains every needle and no
    avoid-word (ECDC renames columns between seasons)."""
    for i, h in enumerate(header):
        low = h.lower()
        if all(n in low for n in needles) and not any(a in low for a in avoid):
            return i
    return None


# --- ECDC ------------------------------------------------------------------------

def _ecdc_table(page):
    """The report's table as a list of rows (header first)."""
    m = re.search(r"data:text/csv;base64,([A-Za-z0-9+/=]+)", page)
    if m:
        raw = base64.b64decode(m.group(1)).decode("utf-8-sig")
        return list(csv.reader(io.StringIO(raw)))
    # Same table as a DataTables widget: column-major data, names in <th>.
    for m in re.finditer(r'<script type="application/json"[^>]*>(.*?)</script>', page, re.S):
        try:
            x = json.loads(m.group(1)).get("x") or {}
        except ValueError:
            continue
        heads = [_text(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", x.get("container") or "", re.S)]
        cols = x.get("data") or []
        if heads and "Country" in heads and cols and len(heads) == len(cols):
            return [heads] + [list(map(str, r)) for r in zip(*cols)]
    raise ValueError("no data.csv or table widget in the ECDC page")


def _ecdc_totals(text, name_iso):
    """{ISO: cases} from the summary sentence's "Italy (590 cases), Greece (319
    cases, of which …)" list. Early-season weeks spell numbers out ("Italy has
    reported six") — those give nothing here and the table's sums stand."""
    m = re.search(r"human cases? of (?:WNV|West Nile virus) infection:(.{0,2500})", text)
    if not m:
        return {}
    seg = re.split(r"Basis and purpose|This week,|The affected areas", m.group(1))[0]
    out = {}
    for name, n in re.findall(r"([A-Z][^(),:;]*?)\s*\*?\s*\((\d[\d\s,.\u00a0\u202f]*?)\s*cases?\b", seg):
        name = re.sub(r"^(?:and|the)\s+", "", name.strip())
        iso = name_iso.get(_norm(name)) or ALIASES.get(_norm(name))
        if iso:
            out[iso] = _int(n)
    return out


def parse_ecdc(page):
    """ECDC weekly report page -> {season, asof, done, countries: {ISO: {name,
    cases (None when ECDC gives no total), areas: [(name, cases)]}}, unmapped}."""
    rows = _ecdc_table(page)
    header, body = rows[0], [r for r in rows[1:] if r and any(c.strip() for c in r)]
    ci = _col(header, "country")
    ai = _col(header, "affected", avoid=("first", "newly", "code"))
    ti = _col(header, "total")
    pi = _col(header, "probable")
    fi = _col(header, "confirmed")
    wi = _col(header, "data as of")
    if ci is None or ai is None:
        raise ValueError("ECDC table without country/area columns: %r" % header)
    text = _text(page[page.find("<body"):] if "<body" in page else page)

    season = None
    for r in body:
        if wi is not None and wi < len(r):
            m = re.match(r"(\d{4})-W\d+", r[wi].strip())
            if m:
                season = m.group(1)
                break
    if not season:
        m = re.search(r"Week \d+, (\d{4})", text) or re.search(r"(\d{4}) transmission season", text)
        season = m.group(1) if m else None
    if not season:
        raise ValueError("no season year in the ECDC page")

    # "based on data submitted up until and including 10 September 2026" (2026)
    # / "based on data submitted up to 10 December 2025" (2025).
    asof = None
    m = re.search(r"data submitted up (?:until and including|to) (\d{1,2}) ([A-Za-z]+) (\d{4})", text)
    if m and m.group(2).lower() in MONTHS:
        asof = datetime.date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()
    # The season's last weekly report says so ("ECDC concludes its weekly
    # reports for the 2025 season"): it's a finished season, not "so far".
    done = bool(re.search(r"concludes? its weekly report", text))

    name_iso = _name_to_iso()
    countries, unmapped = {}, []
    for r in body:
        name = r[ci].strip()
        iso = name_iso.get(_norm(name)) or ALIASES.get(_norm(name))
        if not iso:
            if name not in unmapped:
                unmapped.append(name)
            continue
        e = countries.setdefault(iso, {"name": name, "cases": None, "areas": [], "_rank": []})
        cell = lambda i: _int(r[i]) if i is not None and i < len(r) else None
        n = cell(ti)
        e["areas"].append((r[ai].strip(), n))
        # Busiest areas first. Without a total column (2025) probable +
        # confirmed only orders the list — it is never shown as a count —
        # else Italy's ten were the alphabetically first of 64.
        e["_rank"].append(n if n is not None else (cell(pi) or 0) + (cell(fi) or 0))
    for e in countries.values():
        if ti is not None:
            e["cases"] = sum(n or 0 for _, n in e["areas"])
        rank = e.pop("_rank")
        order = sorted(range(len(rank)), key=lambda i: -rank[i])   # stable: ties keep ECDC's order
        e["areas"] = [e["areas"][i] for i in order]
    for iso, n in _ecdc_totals(text, name_iso).items():
        if iso in countries and n:
            countries[iso]["cases"] = n
    return {"season": season, "asof": asof, "done": done,
            "countries": countries, "unmapped": unmapped}


# --- CDC -------------------------------------------------------------------------

def _cdc_map(config):
    """The config's state map: (CSV url, year) — e.g. "West Nile virus human
    disease cases reported by state of residence, 2026"."""
    for v in (config or {}).get("visualizations", {}).values():
        key = v.get("dataKey") or ""
        title = ((v.get("general") or {}).get("title")) or ""
        if "countbystate" in key.lower() and "west nile" in title.lower():
            m = re.search(r"\b(20\d\d)\b", title)
            return key, (m.group(1) if m else None)
    return None, None


def parse_cdc(states_csv, config, page=None, last_modified=None):
    """CDC current-year files -> {season, asof, states: [(code, cases)]}."""
    _, season = _cdc_map(config)
    if not season:
        raise ValueError("no West Nile state map with a year in CDC's config")
    rows = list(csv.reader(io.StringIO(states_csv.lstrip("\ufeff"))))
    si = _col(rows[0], "state")
    ni = _col(rows[0], "case")
    if si is None or ni is None:
        raise ValueError("CDC state CSV without state/case columns: %r" % rows[0])
    states = []
    for r in rows[1:]:
        if len(r) > max(si, ni):
            n = _int(r[ni])
            if n:
                states.append((r[si].strip().upper(), n))
    states.sort(key=lambda s: -s[1])
    asof = None
    # "Data are current as of September 29, 2026." — split over several tags.
    m = re.search(r"current as of\s*([A-Za-z]+)\.?\s*(\d{1,2})\s*,?\s*(\d{4})", _text(page or ""))
    if m and m.group(1).lower() in MONTHS:
        asof = datetime.date(int(m.group(3)), MONTHS[m.group(1).lower()], int(m.group(2))).isoformat()
    elif last_modified:
        try:
            asof = email.utils.parsedate_to_datetime(last_modified).date().isoformat()
        except (TypeError, ValueError):
            pass
    return {"season": season, "asof": asof, "states": states}


# --- the contract's entries ------------------------------------------------------

def _plural(n, word):
    return "%s %s%s" % ("{:,}".format(n), word, "" if n == 1 else "s")


def _when(season, asof, done, built):
    """"in 2026 so far (as of 10 Sep)", or "in the 2025 season" once it's over
    (or the report says it concluded) — January still shows last summer."""
    if done or season < built[:4]:
        return "in the %s season" % season
    out = "in %s so far" % season
    if asof:
        d = datetime.date.fromisoformat(asof)
        out += " (as of %d %s)" % (d.day, d.strftime("%b"))
    return out


def ecdc_entries(e, built):
    when = _when(e["season"], e["asof"], e["done"], built)
    out = {}
    for iso, c in e["countries"].items():
        areas = c["areas"]
        where = "in " + _plural(len(areas), "area")
        if c["cases"]:
            t = "ECDC: %s %s %s" % (_plural(c["cases"], "locally acquired human case"), where, when)
        else:
            t = "ECDC: locally acquired human cases %s %s" % (where, when)
        # Names stay ECDC's, commas included: "Karditsa, Trikala" is one Greek
        # area (EL611) but "Aschaffenburg, Landkreis" is one German district,
        # so no rewrite fits both — join them with something other than ", ".
        out[iso] = {"a": [a for a, _ in areas[:MAX_AREAS]], "t": t}
    return out


def cdc_entries(d, built):
    when = _when(d["season"], d["asof"], False, built)
    out, us = {}, []
    for code, n in d["states"]:
        if code in TERRITORIES:
            out[TERRITORIES[code]] = {"t": "CDC: %s reported %s" % (_plural(n, "human disease case"), when)}
        elif code in STATES:
            us.append((code, n))
    if us:
        total = sum(n for _, n in us)
        k = sum(1 for c, _ in us if c != "DC")
        where = _plural(k, "state") + (" and DC" if any(c == "DC" for c, _ in us) else "")
        out["US"] = {"a": [STATES[c] for c, _ in us[:MAX_AREAS]],
                     "t": "CDC: %s reported from %s %s" % (_plural(total, "human disease case"), where, when)}
    return out


# --- fetch + assemble ------------------------------------------------------------

def fetch_ecdc(info=None):
    """Parsed ECDC report: the live page, else the newest archived copy."""
    errors = []
    # One try at the live page: a dropped connection (see Failure modes)
    # costs the whole timeout and a second try has never got through.
    for via, url, retries in (("live", ECDC_LIVE, 1), ("archive", ECDC_ARCHIVE, 2)):
        if not url:
            continue
        try:
            body, _ = _fetch(url, retries=retries)
            parsed = parse_ecdc(body.decode("utf-8", "replace"))
            if info is not None:
                info["ecdc"] = via
                if errors:
                    info["ecdc_errors"] = errors
            return parsed
        except Exception as e:  # noqa: BLE001 — any failure moves to the next route
            errors.append("%s: %s" % (via, e))
    raise RuntimeError("; ".join(errors))


def fetch_cdc(info=None):
    config = json.loads(_fetch(CDC_CONFIG)[0].decode("utf-8"))
    url = _cdc_map(config)[0] or CDC_STATES
    body, headers = _fetch(url.replace(" ", "%20"))
    try:
        page = _fetch(CDC_URL)[0].decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 — only the "as of" date comes from here
        page = None
    if info is not None:
        info["cdc"] = "live"
    return parse_cdc(body.decode("utf-8", "replace"), config, page, headers.get("Last-Modified"))


NOTE_ALL = ("Europe (ECDC: EU/EEA and neighbouring countries) and the US (CDC) only; "
            "elsewhere, no entry doesn't mean no West Nile.")
NOTE_NO_CDC = ("Europe (ECDC: EU/EEA and neighbouring countries) only, US data (CDC) "
               "unavailable this build; elsewhere, no entry doesn't mean no West Nile.")
NOTE_NO_ECDC = ("US (CDC) only, Europe's data (ECDC) unavailable this build; "
                "elsewhere, no entry doesn't mean no West Nile.")


def build(ecdc=None, cdc=None, built=None):
    """Contract C1's "w" from already-parsed reports (either may be None)."""
    built = built or datetime.date.today().isoformat()
    c, src, seasons = {}, [], []
    if ecdc:
        c.update(ecdc_entries(ecdc, built))
        src.append("ECDC")
        seasons.append(ecdc["season"])
    if cdc:
        for iso, v in cdc_entries(cdc, built).items():
            c.setdefault(iso, v)
        src.append("CDC")
        seasons.append(cdc["season"])
    if not c:
        return None
    return {
        "source": " · ".join(src),
        "url": ECDC_URL if ecdc else CDC_URL,
        "season": max(seasons),
        "built": built,
        "note": NOTE_ALL if ecdc and cdc else NOTE_NO_CDC if ecdc else NOTE_NO_ECDC,
        "c": dict(sorted(c.items())),
    }


def get(built=None, info=None, ecdc=True, cdc=True):
    """Contract C1's "w" dict, or None when neither agency could be read.
    Pass info={} to get which route each source took and what failed."""
    info = {} if info is None else info
    e = d = None
    if ecdc:
        try:
            e = fetch_ecdc(info)
            info["unmapped"] = e["unmapped"]
        except Exception as ex:  # noqa: BLE001
            info["ecdc"] = "failed: %s" % ex
    if cdc:
        try:
            d = fetch_cdc(info)
        except Exception as ex:  # noqa: BLE001
            info["cdc"] = "failed: %s" % ex
    try:
        return build(e, d, built)
    except Exception as ex:  # noqa: BLE001 — never take the health build down
        info["build"] = "failed: %s" % ex
        return None


def main(argv):
    built = None
    if "--built" in argv:
        built = argv[argv.index("--built") + 1]
    info = {}
    if "--ecdc-file" in argv:
        with open(argv[argv.index("--ecdc-file") + 1], encoding="utf-8") as f:
            e = parse_ecdc(f.read())
        info["ecdc"] = "file"
        d = None
        if "--no-cdc" not in argv:
            try:
                d = fetch_cdc(info)
            except Exception as ex:  # noqa: BLE001
                info["cdc"] = "failed: %s" % ex
        w = build(e, d, built)
    else:
        w = get(built, info, ecdc="--no-ecdc" not in argv, cdc="--no-cdc" not in argv)
    if "--json" in argv:
        print(json.dumps(w, ensure_ascii=False, indent=1))
        return 0 if w else 1
    for k in ("ecdc", "ecdc_errors", "cdc", "unmapped", "build"):
        if info.get(k):
            print("%-12s %s" % (k + ":", info[k]), file=sys.stderr)
    if not w:
        print("no West Nile data (both sources failed)")
        return 1
    print("%s · season %s · built %s · %d countries" % (w["source"], w["season"], w["built"], len(w["c"])))
    print("note: " + w["note"])
    for iso, v in w["c"].items():
        print("  %s  %s" % (iso, v["t"]))
        if v.get("a"):
            print("      " + ", ".join(v["a"]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
