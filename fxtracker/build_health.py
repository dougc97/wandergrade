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
From a local mirror:       python3 -m fxtracker.build_health --dir /path/to/cta-files
It writes the static file the website ships with. The server keeps it fresh
on its own (fxtracker/health.py runs build() once the copy it serves is a
week old), so a visitor's request never waits on Canada's API.
"""

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
    # 13 of 230 headings don't repeat the page's name ("The Bahamas" on
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


def build(prev=None, only=None, local_dir=None, pause=0.3):
    """(doc, failed) — the document the site serves as /health.json:
    {built, source, url, c: {ISO: row}} — and the pages that failed.

    One page at a time (`pause` seconds apart: an open-data API, no need to
    hurry it). `prev` is the last good document's "c": a page that fails keeps
    its previous entry, rather than vanishing and reading as "not covered" on
    the site. `only` refreshes just those ISOs on top of `prev`. Raises Outage
    when more than a handful of pages fail — that is an outage, not an answer,
    and whoever called keeps the document they have. Used by the CLI below and
    by health.py's refresher on the server."""
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
    out = dict(prev) if only else {}
    hosts = {spec[0] for spec in SHARED.values()}
    engs = {}        # the hosts' pages, for the places they advise on
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
            if iso in hosts:
                engs[iso] = eng
        except Exception as e:     # one bad page must not sink the build
            failed.append("%s (%s)" % (iso, e))
            if iso in prev:
                out[iso] = prev[iso]
        if pause and not local_dir:
            time.sleep(pause)
    # Places Canada advises on inside another country's page: Palestine is
    # on its "Israel and Palestine" page (the row said "not covered"). The
    # health advice is the page's; the reasons are the place's own block
    # ("PALESTINE - AVOID ALL TRAVEL"), never Israel's.
    for iso, (host, label, place) in SHARED.items():
        if host not in out or (iso in out and host not in engs):
            continue
        row = {k: v for k, v in out[host].items() if k not in ("r", "rq")}
        row["v"] = label
        if host in engs:
            row.update(reasons(engs[host], place))
        else:
            row.update({k: v for k, v in prev.get(iso, {}).items() if k in ("r", "rq")})
        out[iso] = row
    if len(failed) > 5 or (not only and len(out) < 150):
        raise Outage("%d pages failed, %d countries parsed" % (len(failed), len(out)))
    doc = {"built": built,
           "source": "Government of Canada — travel health advice (Public Health Agency of Canada)",
           "url": "https://travel.gc.ca/destinations/",
           "c": dict(sorted(out.items()))}
    return doc, failed


def with_westnile(doc, prev_doc=None, log=print):
    """Adds West Nile (the top-level "w") from fxtracker.westnile when that
    module exists. Canada's pages list it for no country, so it comes from
    ECDC/CDC case reports. A source that fails keeps the last document's w
    rather than dropping the season's areas."""
    try:
        from . import westnile
    except ImportError:
        return doc
    try:
        w = westnile.get()
    except Exception as e:
        log("[health] West Nile not refreshed: %s" % e)
        w = (prev_doc or {}).get("w")
    if isinstance(w, dict) and isinstance(w.get("c"), dict):
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
        doc, failed = build(prev_doc.get("c", {}), only, local_dir)
    except Outage as e:
        # Non-zero exit, for a scheduled job.
        sys.exit("%s — keeping the existing %s" % (e, OUT))
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
