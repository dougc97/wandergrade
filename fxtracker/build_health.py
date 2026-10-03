#!/usr/bin/env python3
"""Per-country disease risks for travellers -> public/health.json.

Source: the Government of Canada's travel advice pages (travel.gc.ca), whose
Health tab is written by the Public Health Agency of Canada and published as
data in the same feed the Canadian advisory levels and the safety notes come
from (data.international.gc.ca). Each disease is its own headed block, and the
block opens with a templated risk sentence — "In Mexico, dengue is a risk to
travellers" vs "In France, risk of dengue is sporadic" — so the grade below is
Canada's own, read off its wording, never ours. This site doesn't author safety
or health claims; it sorts what a government says and links to it.

Grades per disease:
  risk  — Canada says it is a risk to travellers here (a chip on the Safety
          table and the guide);
  areas — a risk, but only "in certain areas", "in parts", "in some areas",
          or (yellow fever) with vaccination "depending on your itinerary"
          (still a chip, marked, ranked after the country-wide ones);
  low   — listed, but Canada calls it sporadic, or low for most travellers —
          whatever the disease, the same words give the same grade (named in
          the tip only);
  (none)— not listed, listed as "no risk" (yellow fever's entry block is on
          every page and usually says so), or rabies "in some wildlife".
Left out because Canada lists them for nearly every country, so they tell no
country apart: COVID-19, hepatitis A (197 of 230 pages) and B, influenza,
measles, travellers' diarrhea. The site says so wherever a country has none of
the rest ("only the usual"). Canada's own pages say not every risk is listed —
West Nile virus, for one, is on none of them.

Current travel health notices (time-limited alerts, e.g. "Dengue: Advice for
travellers") mark a disease as having a notice; the global measles notice is on
every page and is skipped.

The same pages carry Canada's reason for its advisory level (r, rq — see
reasons() below), so they ride along in the same document.

Run (re-run to refresh):   python3 -m fxtracker.build_health
Only some countries:       python3 -m fxtracker.build_health MX TH
                           (the file keeps its date and its West Nile)
From a local mirror:       python3 -m fxtracker.build_health --dir /path/to/cta-files
It writes the static file the website ships with. The server keeps it fresh
on its own (fxtracker/health.py runs build() once the copy it serves is a
week old), so a visitor's request never waits on Canada's API.
"""

import datetime
import html
import json
import os
import re
import sys
import time
import unicodedata

from . import advisories, rates

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "public", "health.json")
INDEX = "https://data.international.gc.ca/travel-voyage/index-alpha-eng.json"
PAGE = "https://data.international.gc.ca/travel-voyage/cta-cap-{iso}.json"

# Canada's heading -> (display name, rule). A rule is a list of
# (regex on the block's text, grade); the first match wins, no match = skip.
# Order here is display priority: the diseases most likely to change a trip
# (prophylaxis, a vaccine, a warning for pregnancy) come first.
RISK, LOW, AREAS = "risk", "low", "areas"
# Canada's "low for most travellers" wording, whichever disease it's about:
# cholera, schistosomiasis, Crimean-Congo fever and others say it as plainly
# as typhoid does, and were chips while typhoid went to the tip.
LOW_ANY = r"low for most|generally low|most travell?ers are at (?:very )?low risk"
DISEASES = [
    ("Malaria", "Malaria", [(r"very low", LOW), (r"in certain areas", AREAS),
                            (r"risk of malaria|malaria is a risk", RISK)]),
    ("Yellow Fever - Country Entry Requirements", "Yellow fever",
     [(r"there is no risk of yellow fever", None), (r"low potential", LOW),
      (r"recommended depending on your itinerary", AREAS),
      (r"there is a risk of yellow fever", RISK)]),
    ("Dengue", "Dengue", [(r"sporadic", LOW), (r"is a risk", RISK)]),
    ("Zika virus", "Zika", [(r"may be a risk in some areas", LOW), (r"is a risk", RISK)]),
    ("Chikungunya", "Chikungunya", [(r"risk is low", LOW), (r"risk of chikungunya", RISK)]),
    ("Cholera", "Cholera", [(r"is a risk in parts", AREAS), (r"is a risk", RISK)]),
    ("Oropouche virus disease", "Oropouche", [(r"is a risk", RISK)]),
    ("Schistosomiasis", "Schistosomiasis", [(r"risk of schistosomiasis", RISK)]),
    ("Tick-borne encephalitis", "Tick-borne encephalitis", [(r"in some areas", AREAS), (r"is a risk", RISK)]),
    ("Lassa fever", "Lassa fever", [(r"is a risk", RISK)]),
    ("Crimean-Congo haemorrhagic fever", "Crimean-Congo fever", [(r"risk of crimean", RISK)]),
    ("Nipah virus", "Nipah virus", [(r"risk of nipah", RISK)]),
    ("Typhoid fever", "Typhoid", [(r"low for most", LOW), (r"risk of typhoid", RISK)]),
    # "common", or "present… carried by dogs" (with a vaccination talk
    # advised) — a street-dog risk; "may be present in some wildlife" is not.
    ("Rabies", "Rabies", [(r"rabies is common|present in this (?:country|destination) and is carried by dogs", RISK)]),
    ("Salmonellosis", "Salmonella", [(r"common illness among travell?ers", RISK)]),
    ("Cyclosporiasis", "Cyclospora", [(r"common illness among travell?ers", RISK)]),
    ("American trypanosomiasis", "Chagas", [(r"is a risk", RISK)]),
    ("Mpox", "Mpox", [(r"is a risk", RISK)]),
    ("Meningococcal disease", "Meningitis", [(r"meningitis belt", RISK)]),
    ("Japanese encephalitis", "Japanese encephalitis", [(r"very low|low for most", LOW), (r"risk", RISK)]),
    ("Leishmaniasis - Visceral", "Leishmaniasis", [(r"low for most", LOW), (r"risk", RISK)]),
    ("Leishmaniasis – Cutaneous and mucocutaneous", "Leishmaniasis", [(r"low for most", LOW), (r"risk", RISK)]),
    ("Rift Valley fever", "Rift Valley fever", [(r".", LOW)]),
    ("Onchocerciasis", "River blindness", [(r".", LOW)]),
    ("Lymphatic filariasis", "Filariasis", [(r".", LOW)]),
    ("African trypanosomiasis", "Sleeping sickness", [(r".", LOW)]),
    ("Marburg virus disease", "Marburg", [(r".", LOW)]),
    ("Ebola disease", "Ebola", [(r".", LOW)]),
    ("Middle East respiratory syndrome (MERS)", "MERS", [(r".", LOW)]),
    ("Plague", "Plague", [(r".", LOW)]),
    ("Avian Influenza", "Bird flu", [(r".", LOW)]),
    ("Tuberculosis", "Tuberculosis", [(r".", LOW)]),
]
_ORDER = {name: i for i, (_, name, _) in enumerate(DISEASES)}
# ISO -> (the page it is on, that page's label, the place's own block heading)
SHARED = {"PS": ("IL", "Israel and Palestine", "Palestine")}
_RULES = {head.lower(): (name, rules) for head, name, rules in DISEASES}
# Notices name their disease first ("Dengue: Advice for travellers", "Ebola
# disease in Democratic Republic of the Congo"). Only notices for a disease
# the chips can show are kept; polio and diphtheria notices are vaccination
# advice (the polio one covers wastewater finds in Germany and the UK), and
# measles is on every page.
_NOTICE = [(r"^avian influenza", "Bird flu"), (r"^dengue", "Dengue"), (r"^chikungunya", "Chikungunya"), (r"^zika", "Zika"),
           (r"^yellow fever", "Yellow fever"), (r"^ebola", "Ebola"), (r"^marburg", "Marburg"),
           (r"^cholera", "Cholera"), (r"^oropouche", "Oropouche"), (r"^mpox", "Mpox"),
           (r"^malaria", "Malaria")]


def _txt(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment or "")
    return html.unescape(re.sub(r"\s+", " ", s)).strip()


def parse(eng):
    """{h: [risk names…], a: [the area-limited ones among h], l: [low names…],
    n: [names with a current notice], s: slug} — or None without a Health tab."""
    h = eng.get("health") or ""
    if not h:
        return None
    risk, low, areas, notices = {}, {}, {}, set()
    parts = re.split(r"<h3[^>]*>(.*?)</h3>", h, flags=re.S)
    for i in range(1, len(parts), 2):
        section, body = _txt(parts[i]), parts[i + 1]
        if section.lower().startswith("relevant travel health notices"):
            for a in re.findall(r"<a [^>]*>(.*?)</a>", body, re.S):
                t = _txt(a).lower()
                for pat, name in _NOTICE:
                    if re.search(pat, t):
                        notices.add(name)
            continue
        for m in re.finditer(r"<summary[^>]*>(.*?)</summary>(.*?)(?=<summary|</details>)", body, re.S):
            head = _txt(m.group(1)).lower()
            if head not in _RULES:
                continue
            name, rules = _RULES[head]
            text = _txt(m.group(2)).lower()
            if re.search(LOW_ANY, text):
                rules = [(r".", LOW)]
            for pat, grade in rules:
                if re.search(pat, text):
                    if grade in (RISK, AREAS):
                        risk[name] = 1
                        if grade == AREAS:
                            areas[name] = 1
                    elif grade == LOW and name not in risk:
                        low[name] = 1
                    break
    for name in risk:
        low.pop(name, None)
    # A notice for a disease the page only calls low (or doesn't list) still
    # counts: the notice IS the current risk.
    for name in notices:
        if name not in risk:
            risk[name] = 1
            low.pop(name, None)
        areas.pop(name, None)
    # Country-wide first, then the area-limited ones, each in priority order.
    by = lambda n: (n in areas, _ORDER.get(n, 99))
    out = {"h": sorted(risk, key=by)}
    if areas:
        out["a"] = sorted(areas, key=by)
    if low:
        out["l"] = sorted(low, key=by)
    if notices:
        out["n"] = sorted(notices, key=by)
    if eng.get("url-slug"):
        out["s"] = eng["url-slug"]
    return out


# ---- Canada's own reasons for its level --------------------------------------
# The Safety table says WHY a government rates a country as it does. The US
# reasons come from its feed's "due to" clause (advisories._risks); Canada's
# are on the same page as its health advice, in the advisories tab. Its first
# block is the country-wide one, headed with the country's name ("Mexico -
# Exercise a high degree of caution" — the block watchouts.py skips, since
# the rest are regional), and its lead sentence carries the reason: "Exercise
# a high degree of caution in Mexico due to high levels of criminal activity
# and kidnapping." The sentence is quoted verbatim (rq) and its "due to"
# clause labelled with the US vocabulary (r), so the chips read the same
# whichever government the traveller follows.
RQ_MAX = 240


def _fold(text):
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


def _adv_blocks(adv):
    """[(container class, heading, body html)] for each h3-headed block."""
    adv = adv or ""
    heads = list(re.finditer(r"<h3[^>]*>(.*?)</h3>", adv, re.S))
    out = []
    for k, m in enumerate(heads):
        cls = re.findall(r'class="AdvisoryContainer ([^"]*)"', adv[:m.start()])
        end = heads[k + 1].start() if k + 1 < len(heads) else len(adv)
        out.append((cls[-1] if cls else "", _txt(m.group(1)), adv[m.end():end]))
    return out


def _lead_block(eng, place=None):
    """Body of the country-wide block — or, with `place`, of the block for a
    place advised on inside another country's page ("PALESTINE - AVOID ALL
    TRAVEL" on "Israel and Palestine")."""
    blocks = _adv_blocks(eng.get("advisories"))
    want = _fold(place or eng.get("name") or "")
    for _cls, head, body in blocks:
        if want and _fold(head).startswith(want):
            return body
    if place:
        return None
    # 11 of 230 headings don't repeat the page's name ("The Bahamas" on
    # "Bahamas", "DEMOCRATIC REPUBLIC OF THE CONGO" on "Democratic Republic of
    # Congo (Kinshasa)", "ISRAEL" on "Israel and Palestine"): the country-wide
    # block is then the first one that isn't a regional advisory.
    for cls, _head, body in blocks:
        if "regional" not in cls.lower():
            return body
    return None


def _lead(body):
    """The block's lead paragraph as text. A list it opens is kept, its items
    joined with semicolons: Myanmar's reads "…due to the risk of:" and then
    five <li>s."""
    m = re.search(r"<p[^>]*>(.*?)(?=<p[\s>]|</p>|<div|\Z)", body or "", re.S)
    if not m:
        return ""
    t = _txt(re.sub(r"</li>\s*<li[^>]*>", "; ", m.group(1))).replace("\xa0", " ")
    return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s+", " ", t)).strip()


def reasons(eng, place=None):
    """{r: [labels…], rq: Canada's lead sentence} for the country-wide level —
    or {} when the lead names no reason ("Take normal security precautions in
    Uruguay.", "Exercise a high degree of caution in China.")."""
    body = _lead_block(eng, place)
    sents = re.split(r"(?<=[.!?])\s+(?=[A-Z“\"'])", _lead(body) if body else "")
    due = re.search(r"\bdue to\b:?\s*(.+)", sents[0], re.I | re.S)
    if not due:
        return {}
    quote, clauses = sents[0], [due.group(1).rstrip(" .")]
    # Pakistan's lead carries on in a second sentence: "…due to the
    # unpredictable security situation. There is also a threat of terrorism,
    # regional violence, civil unrest, sectarian violence and kidnapping."
    if len(sents) > 1 and re.match(r"there (?:is|are) also\b", sents[1], re.I):
        quote += " " + sents[1]
        clauses.append(re.sub(r"^there (?:is|are) also\s+", "", sents[1], flags=re.I).rstrip(" ."))
    # A clause whose only reason is one word no label knows still has a
    # reason: "Other", so the row never looks complete when it isn't.
    labels = advisories.label_reasons("; ".join(clauses)) or ["Other"]
    if len(quote) > RQ_MAX:
        quote = quote[:RQ_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return {"r": labels, "rq": quote}


# ---- the build ----------------------------------------------------------------
class Outage(RuntimeError):
    """Too many pages failed for the run to be an answer."""


def _load(iso, local_dir):
    if local_dir:
        with open(os.path.join(local_dir, "cta-%s.json" % iso.lower()), encoding="utf-8") as f:
            return json.load(f)
    return rates.fetch_json(PAGE.format(iso=iso.lower()))


MAX_FAILED = 5


def build(prev=None, only=None, local_dir=None, pause=0.3, prev_built=None):
    """(doc, failed) — the document the site serves as /health.json:
    {built, source, url, c: {ISO: row}} — and the pages that failed.

    One page at a time (`pause` seconds apart: an open-data API, no need to
    hurry it). `prev` is the last good document's "c": a page that fails keeps
    its previous entry, rather than vanishing and reading as "not covered" on
    the site. `only` refreshes just those ISOs on top of `prev`, and the
    document keeps `prev_built` (prev's date): a few pages refreshed are not
    the document refreshed, and dating it today would hold off the full
    refresh for a week. Raises Outage as soon as more than MAX_FAILED pages
    fail — that is an outage, not an answer, and whoever called keeps the
    document they have. Used by the CLI below and by health.py's refresher on
    the server."""
    prev = prev or {}
    if local_dir and os.path.exists(os.path.join(local_dir, "index.json")):
        with open(os.path.join(local_dir, "index.json"), encoding="utf-8") as f:
            isos = sorted((json.load(f).get("data") or {}).keys())
        # A mirror is as fresh as the day it was fetched, not the day it is
        # read: stamping today would hold off the server's refresh for a week.
        built = time.strftime("%Y-%m-%d", time.localtime(
            os.path.getmtime(os.path.join(local_dir, "index.json"))))
    else:
        isos = sorted((rates.fetch_json(INDEX).get("data") or {}).keys())
        built = time.strftime("%Y-%m-%d")
    if only and prev_built:
        built = prev_built
    out = dict(prev) if only else {}
    hosts = {spec[0] for spec in SHARED.values()}
    engs = {}        # the hosts' pages, for the places they advise on
    own = set()      # ISOs whose own page was read this run
    failed = []
    for iso in isos:
        if only and iso not in only:
            continue
        try:
            eng = ((_load(iso, local_dir) or {}).get("data") or {}).get("eng") or {}
            row = parse(eng)
            if row is not None:
                row.update(reasons(eng))
                out[iso] = row
                own.add(iso)
            if iso in hosts:
                engs[iso] = eng
        except Exception as e:     # one bad page must not sink the build
            failed.append("%s (%s)" % (iso, e))
            if iso in prev:
                out[iso] = prev[iso]
            # Declared at once rather than after the last page: when the API
            # hangs, each page costs ~65s (20s timeout x 3 tries, plus
            # backoff), and 230 of them took ~4 hours to call an outage.
            if len(failed) > MAX_FAILED:
                raise Outage("%d pages failed, stopping at %s (the first: %s)"
                             % (len(failed), iso, failed[0]))
        if pause and not local_dir:
            time.sleep(pause)
    # Places Canada advises on inside another country's page: Palestine is
    # on its "Israel and Palestine" page (the row said "not covered"). The
    # health advice is the page's; the reasons are the place's own block
    # ("PALESTINE - AVOID ALL TRAVEL"), never Israel's. The copy fills in
    # only: should Canada publish a PS page of its own, that row stands —
    # whether read this run (own) or kept from the last one (a row with no
    # "v" is a country's own page, so a failed PS page or a run of only=IL
    # doesn't swap it for Israel's either). A copy made last time is
    # refreshed when the host page loaded, else kept.
    for iso, (host, label, place) in SHARED.items():
        have = out.get(iso)
        if iso in own or host not in out:
            continue
        if have is not None and ("v" not in have or host not in engs):
            continue
        row = {k: v for k, v in out[host].items() if k not in ("r", "rq")}
        row["v"] = label
        if host in engs:
            row.update(reasons(engs[host], place))
        else:
            row.update({k: v for k, v in prev.get(iso, {}).items() if k in ("r", "rq")})
        out[iso] = row
    if len(failed) > MAX_FAILED or (not only and len(out) < 150):
        raise Outage("%d pages failed, %d countries parsed" % (len(failed), len(out)))
    doc = {"built": built,
           "source": "Government of Canada — travel health advice (Public Health Agency of Canada)",
           "url": "https://travel.gc.ca/destinations/",
           "c": dict(sorted(out.items()))}
    return doc, failed


# ---- West Nile ("w") ------------------------------------------------------------
# Canada's pages list West Nile for no country, so it comes from ECDC's and
# CDC's case reports (fxtracker/westnile.py, when that module is deployed).
# A new w never replaces a newer one: ECDC's live page drops some networks'
# connections and the module then reads the Internet Archive's newest capture,
# which can be weeks older than the last live read. How current each agency's
# data is, is in its own sentences — "ECDC: 319 locally acquired human cases,
# 21 affected areas, in 2026 so far (as of 10 Sep)", "CDC: … in the 2025
# season" — plus w.asof, ECDC's own data date, which survives when the
# sentences drop theirs ("in the 2026 season" once ECDC concludes, and from
# January). That is what's compared, agency by agency: this week's CDC read
# is kept even when ECDC fell back to an older copy than the one served.
_W_AGENCY = re.compile(r"^\s*([A-Z]{2,})\s*:")
_W_WHEN = re.compile(r"\bin (?:the )?(\d{4})(?: season| so far)"
                     r"(?:\s*\(as of (\d{1,2}) ([A-Za-z]{3})[a-z]*\.?\))?")
_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
_W_ORDER = {"ECDC": 0, "CDC": 1}     # westnile.build's order: ECDC's entries first


def _w_parts(w):
    """{agency: {c: {ISO: entry}, season, asof, w}} for a usable w, else {}.
    Every agency the w says it read (its "source", "ECDC · CDC") is there,
    even with no entries: read and no cases is an answer, not a failure."""
    if not (isinstance(w, dict) and isinstance(w.get("c"), dict)):
        return {}
    parts = {}

    def part(a):
        return parts.setdefault(a, {"c": {}, "season": None, "asof": None, "w": w})
    for a in str(w.get("source") or "").split("·"):
        if a.strip():
            part(a.strip())
    for iso, e in w["c"].items():
        t = str(e.get("t") or "") if isinstance(e, dict) else ""
        m = _W_AGENCY.match(t)
        p = part(m.group(1) if m else "")
        p["c"][iso] = e
        when = _W_WHEN.search(t)
        if not when:
            continue
        season, asof = when.group(1), None
        if when.group(2) and when.group(3).lower() in _MONTHS:
            try:
                asof = "%s-%02d-%02d" % (season, _MONTHS[when.group(3).lower()], int(when.group(2)))
                datetime.date.fromisoformat(asof)
            except ValueError:
                asof = None
        if (season, asof or "") > (p["season"] or "", p["asof"] or ""):
            p["season"], p["asof"] = season, asof
    ea = str(w.get("asof") or "")
    if "ECDC" in parts and re.fullmatch(r"\d{4}-\d\d-\d\d", ea):
        parts["ECDC"]["asof"] = ea
        parts["ECDC"]["season"] = parts["ECDC"]["season"] or ea[:4]
    for p in parts.values():
        p["season"] = p["season"] or (str(w.get("season") or "") or None)
    return parts


def _w_older(new, old):
    """True when `new` (a _w_parts part) is provably older data than `old`:
    an earlier season, or the same season "as of" an earlier date. Anything
    it can't tell apart goes to the later build — new, in practice."""
    if new["season"] and old["season"] and new["season"] != old["season"]:
        return new["season"] < old["season"]
    if new["asof"] and old["asof"] and new["asof"] != old["asof"]:
        return new["asof"] < old["asof"]
    return str(new["w"].get("built") or "") < str(old["w"].get("built") or "")


def merge_w(new, old, notes=None, log=print):
    """The w to serve, from this build's (`new`) and the last document's
    (`old`): per agency, the newer data. An agency this build couldn't read
    keeps the last document's entries — unless they are from an earlier
    season than the rest, which would read as this season's. `notes` maps a
    frozenset of agencies to the note for that coverage, for a mix that
    neither w had."""
    np, op = _w_parts(new), _w_parts(old)
    if not np:
        if op:
            log("[health] West Nile: nothing new; keeping the w built %s" % old.get("built"))
        return old if op else None
    if not op:
        return new
    chosen = {}
    for a, p in np.items():
        if a in op and _w_older(p, op[a]):
            o = op[a]
            log("[health] West Nile: kept %s from the w built %s (%s, as of %s) over this "
                "build's (%s, as of %s)" % (a or "unattributed entries", o["w"].get("built"),
                                             o["season"], o["asof"], p["season"], p["asof"]))
            chosen[a] = o
        else:
            chosen[a] = p
    newest = max((p["season"] or "" for p in chosen.values()), default="")
    for a, o in op.items():
        if a in np or not a:
            continue
        if o["season"] and newest and o["season"] < newest:
            log("[health] West Nile: %s unread this build; its %s entries dropped beside %s data"
                % (a, o["season"], newest))
            continue
        log("[health] West Nile: %s unread this build; kept its entries from the w built %s"
            % (a, o["w"].get("built")))
        chosen[a] = o
    if all(p["w"] is new for p in chosen.values()):
        return new
    if all(p["w"] is old for p in chosen.values()) and set(chosen) == set(op):
        return old
    order = sorted(chosen, key=lambda a: (_W_ORDER.get(a, 2 if a else 3), a))
    c = {}
    for a in order:            # an ISO two agencies report: the first listed
        for iso, e in chosen[a]["c"].items():
            c.setdefault(iso, e)
    agencies = [a for a in order if a]
    have = frozenset(agencies)
    note = next((w.get("note") for w in (new, old) if frozenset(a for a in _w_parts(w) if a) == have), None)
    note = note or (notes or {}).get(have) or new.get("note")
    out = {"source": " · ".join(agencies),
           "url": chosen[order[0]]["w"].get("url") or new.get("url") or old.get("url"),
           "season": max([p["season"] for p in chosen.values() if p["season"]] or [new.get("season")]),
           "built": new.get("built")}
    if "ECDC" in chosen and chosen["ECDC"]["asof"]:
        out["asof"] = chosen["ECDC"]["asof"]
    if note:
        out["note"] = note
    out["c"] = dict(sorted(c.items()))
    return out


def _w_routes(info):
    """One log line: where each agency's data came from this build."""
    def one(k):
        v = str(info.get(k) or "not tried")
        if v == "archive":
            v = "from the Internet Archive's copy (the live page failed)"
        return "%s %s" % (k.upper(), v[:200])
    line = "[health] West Nile: %s; %s" % (one("ecdc"), one("cdc"))
    asof = [k.split("_")[0].upper() + " as of " + str(info[k]) for k in ("ecdc_asof", "cdc_asof") if info.get(k)]
    if asof:
        line += " (" + ", ".join(asof) + ")"
    if info.get("ecdc_errors"):
        line += " — " + "; ".join(map(str, info["ecdc_errors"]))[:240]
    if info.get("unmapped"):
        line += "; unmapped: " + ", ".join(map(str, info["unmapped"]))
    if info.get("build"):
        line += "; " + str(info["build"])[:200]
    return line


def with_westnile(doc, prev_doc=None, log=print):
    """Adds West Nile (the top-level "w") from fxtracker.westnile when that
    module exists, merged with the last document's (merge_w): an agency that
    fails, or comes back with older data, keeps what was served."""
    try:
        from . import westnile
    except ImportError:
        return doc
    info = {}
    try:
        w = westnile.get(info=info)
    except Exception as e:
        log("[health] West Nile not refreshed: %s" % e)
        w = None
    log(_w_routes(info))
    notes = {frozenset(k): getattr(westnile, name, None) for k, name in (
        (("ECDC", "CDC"), "NOTE_ALL"), (("ECDC",), "NOTE_NO_CDC"), (("CDC",), "NOTE_NO_ECDC"))}
    w = merge_w(w, (prev_doc or {}).get("w"), notes, log)
    if w:
        doc["w"] = w
    return doc


def main(argv):
    local_dir = None
    if "--dir" in argv:
        k = argv.index("--dir")
        local_dir = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    only = {a.upper() for a in argv if re.fullmatch(r"[A-Za-z]{2}", a)}
    prev_doc = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            prev_doc = json.load(f)
    try:
        doc, failed = build(prev_doc.get("c", {}), only, local_dir,
                            prev_built=prev_doc.get("built"))
    except Outage as e:
        # Non-zero exit, for a scheduled job.
        sys.exit("%s — keeping the existing %s" % (e, OUT))
    if only:                   # a few pages: West Nile is the full run's
        if prev_doc.get("w"):
            doc["w"] = prev_doc["w"]
    else:
        doc = with_westnile(doc, prev_doc)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    out = doc["c"]
    print("wrote %s: %d countries, %d with a risk listed, %d with Canada's reasons%s" % (
        OUT, len(out), sum(1 for r in out.values() if r.get("h")),
        sum(1 for r in out.values() if r.get("r")),
        ("; failed: " + ", ".join(failed)) if failed else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
