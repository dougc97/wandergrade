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

Run (re-run to refresh):   python3 -m fxtracker.build_health
Only some countries:       python3 -m fxtracker.build_health MX TH
From a local mirror:       python3 -m fxtracker.build_health --dir /path/to/cta-files
It writes a static file the website reads, so there are no live calls.
"""

import html
import json
import os
import re
import sys
import time

from . import rates

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
SHARED = {"PS": ("IL", "Israel and Palestine")}
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


def _load(iso, local_dir):
    if local_dir:
        with open(os.path.join(local_dir, "cta-%s.json" % iso.lower()), encoding="utf-8") as f:
            return json.load(f)
    return rates.fetch_json(PAGE.format(iso=iso.lower()))


def main(argv):
    local_dir = None
    if "--dir" in argv:
        k = argv.index("--dir")
        local_dir = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    only = {a.upper() for a in argv if re.fullmatch(r"[A-Za-z]{2}", a)}
    if local_dir and os.path.exists(os.path.join(local_dir, "index.json")):
        with open(os.path.join(local_dir, "index.json"), encoding="utf-8") as f:
            isos = sorted((json.load(f).get("data") or {}).keys())
    else:
        isos = sorted((rates.fetch_json(INDEX).get("data") or {}).keys())
    # The last good file backs every country this run can't read: a page that
    # fails keeps its previous entry, rather than vanishing and reading as
    # "not covered" on the site.
    prev = {}
    if os.path.exists(OUT):
        with open(OUT, encoding="utf-8") as f:
            prev = json.load(f).get("c", {})
    out = dict(prev) if only else {}
    failed = []
    for iso in isos:
        if only and iso not in only:
            continue
        try:
            eng = ((_load(iso, local_dir) or {}).get("data") or {}).get("eng") or {}
            row = parse(eng)
            if row is not None:
                out[iso] = row
        except Exception as e:     # one bad page must not sink the build
            failed.append("%s (%s)" % (iso, e))
            if iso in prev:
                out[iso] = prev[iso]
        if not local_dir:
            time.sleep(0.3)        # an open-data API; no need to hurry it
    # Places Canada advises on inside another country's page: Palestine is
    # on its "Israel and Palestine" page (the row said "not covered").
    for iso, (host, label) in SHARED.items():
        if iso not in out and host in out:
            out[iso] = dict(out[host], v=label)
    # A run with more than a handful of failures is an outage, not an answer:
    # keep the existing file and say so (non-zero exit, for a scheduled job).
    if len(failed) > 5 or (not only and len(out) < 150):
        sys.exit("%d pages failed, %d countries parsed — keeping the existing %s"
                 % (len(failed), len(out), OUT))
    doc = {"built": time.strftime("%Y-%m-%d"),
           "source": "Government of Canada — travel health advice (Public Health Agency of Canada)",
           "url": "https://travel.gc.ca/destinations/",
           "c": dict(sorted(out.items()))}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote %s: %d countries, %d with a risk listed%s" % (
        OUT, len(out), sum(1 for r in out.values() if r.get("h")),
        ("; failed: " + ", ".join(failed)) if failed else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
