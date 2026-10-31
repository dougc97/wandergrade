"""The guide's "Top things to do" photo subjects, without the network.

    /usr/bin/python3 scripts/test_activity_subjects.py

Each activity row's thumbnail is the Wikipedia lead image of its subject
(public/app.js activitySubject -> actPhoto -> wikiIconic): the row's "p" if
set, else the first parenthesised name in its title (text before a comma),
else the title without brackets, NP -> National Park, Mt -> Mount. A bare
name can land on the wrong page: the 2026-10-31 audit
(scripts/dev/activity_thumb_audit.py) found Colombia's Salento showing Italy's
Salento, Côte d'Ivoire's Man a portrait of a man, Tajikistan's Wakhan a map
of the Afghan side, and 33 more (wrong country, a person, the space
station Mir, a map, a diagram, a collage), and gave each a precise "p". Ten
more wrong rows are left for Doug: their titles have no parenthetical, so
scripts/gen_stay_spots.py takes their "p" as a "Where to stay" place too, and
a new one would change those countries' stay chips at the next rebuild.

  1. public/activities.json keeps its format: one line, compact separators,
     unescaped UTF-8, no trailing newline, keys in sorted order (an activity
     is d, p, t), every activity a {d, t[, p]} object;
  2. every "p" is a non-empty string with no stray whitespace;
  3. the Python mirror of activitySubject below gives app.js's own answer,
     run under jsc, for every row and for an edge-case table, so neither can
     drift silently (and scripts/dev/activity_thumb_audit.py's copy agrees),
     and actPhoto still tries subject, "subject, Country", "subject
     (Country)" at the 700x500 gate the audit assumes;
  4. the 36 rows the audit fixed keep their subjects (pinned with their
     titles, so a reordered list fails here rather than moving a photo);
  5. no subject equals a title in its country's gallery[:6] (the hero would
     lose that photo to the row) beyond the 139 pairs that already did on
     2026-10-31, frozen below; a fixed row matches no gallery entry at all.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts", "parity"))
sys.path.insert(0, os.path.join(ROOT, "scripts", "dev"))
import build_js  # noqa: E402  (scripts/parity: lifts declarations out of app.js)

JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

ACTS = os.path.join(ROOT, "public", "activities.json")
with open(ACTS, encoding="utf-8") as f:
    RAW = f.read()
acts = json.loads(RAW)
with open(os.path.join(ROOT, "public", "app.js"), encoding="utf-8") as f:
    APP = f.read()


def act_label(x):
    return (x if isinstance(x, str) else (x or {}).get("t")) or ""


def activity_subject(x):
    """app.js activitySubject(). \\b is ASCII in a JS regex without /u, so re.A."""
    label = act_label(x)
    if isinstance(x, dict) and x.get("p"):
        return x["p"]
    m = re.search(r"\(([^),]+)", label)
    subj = (m.group(1) if m else re.sub(r"\s*\([^)]*\)", "", label)).strip()
    subj = re.sub(r"\bNP\b", "National Park", subj, count=1, flags=re.A)
    return re.sub(r"\bMt\b", "Mount", subj, count=1, flags=re.A)


# Row -> (its title, the subject the 2026-10-31 audit gave it). Before: what
# the live site showed.
FIXED = {
    "AF:3": ("Remote valleys (Wakhan Corridor)", "Wakhan River"),           # Wakhan.png, a relief map
    "AL:0": ("Beaches (Albanian Riviera)", "Dhërmi"),                       # Karte_Albanische_Riviera.png, a map
    "AM:2": ("Alpine lake (Sevan)", "Sevan National Park"),                 # Sevan, Armenia: a six-photo collage
    "AW:3": ("Colourful capital (Oranjestad)", "Paardenbaai"),              # a collage ("I love Aruba")
    "BY:1": ("Castles (Mir, Nesvizh)", "Nesvizh Castle"),                   # Mir: the space station
    "BY:2": ("Bison forest (Białowieża)", "Belovezhskaya Pushcha National Park"),  # Białowieża: a village in Poland
    "CI:3": ("Mountains & bridges (Man)", "Man, Ivory Coast"),              # Man: a portrait of a man
    "CL:2": ("Wine country (Casablanca)", "Casablanca, Chile"),             # Casablanca, Morocco
    "CM:3": ("Highlands (Ring Road)", "Lake Oku"),                          # Ring road: a map of London's M25
    "CO:2": ("Coffee region (Salento)", "Salento, Quindío"),                # Salento, Italy (satellite view)
    "DJ:1": ("Whale sharks (Gulf of Tadjoura)", "Arta, Djibouti"),          # a labelled map of the gulf
    "EG:0": ("Pyramids (Giza)", "Great Pyramid of Giza"),                   # Giza: the Grand Egyptian Museum
    "ET:2": ("Danakil Depression", "Dallol (hydrothermal system)"),         # The_Danakil_Desert.png, a map
    "GQ:1": ("Rainforest & beaches (Bioko)", "Riaba"),                      # Bioko.png, a map
    "GQ:2": ("Turtle nesting (south Bioko)", "Leatherback sea turtle"),     # Bioko.png (hidden behind GQ:1)
    "GR:0": ("Island beaches (Santorini, Mykonos)", "Fira"),                # a locator map
    "GR:2": ("Nightlife (Mykonos)", "Church of Panagia Paraportiani"),      # a locator map
    "HN:1": ("Maya ruins (Copán)", "Copán Ruinas"),                         # Santa Rosa de Copán's church (the gallery's photo)
    "HT:3": ("Northern beaches", "Cap-Haïtien"),                            # Northern Beaches, Sydney
    "LU:3": ("Wine villages (Moselle)", "Wormeldange"),                     # Moselle: Schweich, Germany
    "MW:3": ("Treks (Mt Mulanje)", "Chambe Peak"),                          # a rendered Landsat terrain model
    "MZ:3": ("Safari (Gorongosa)", "Gorongosa National Park"),              # Gorongosa town's council building
    "NI:0": ("Colonial cities (Granada, León)", "León Viejo"),              # Granada, Spain
    "NP:3": ("Safari (Chitwan)", "Chitwan National Park"),                  # Chitwan District: Gaindakot town
    "PA:1": ("Old town nightlife (Casco Viejo)", "San Felipe, Panama"),     # Casco Viejo, Bilbao
    "PK:0": ("Karakoram Highway (Hunza)", "Hunza Valley"),                  # KKH.png, a route map
    "RO:0": ("Castles (Bran, Transylvania)", "Bran, Brașov"),               # Bran: a diagram of wheat bran
    "RO:2": ("Mountains (Carpathians)", "Retezat National Park"),           # Carpathians: Morskie Oko, Poland
    "SR:2": ("Turtles (Galibi)", "Leatherback sea turtle"),                 # Galibi -> Kalina people: schoolchildren
    "TJ:2": ("Valley homestays (Wakhan)", "Ishkoshim, Tajikistan"),         # Wakhan.png, a map of the Afghan side
    "TL:1": ("Whales & dolphins (season)", "Spinner dolphin"),              # Season: a diagram of the seasons
    "TW:3": ("Hot springs", "Thermal Valley"),                              # Hot spring: Yellowstone's Grand Prismatic
    "UY:2": ("Wine country (Carmelo)", "Carmelo, Uruguay"),                 # Carmelo: an Italian architect's portrait
    "VN:0": ("Bays & islands (Ha Long)", "Bai Tu Long Bay"),                # Hạ Long city: a museum facade
    "YE:0": ("Dragon-blood trees (Socotra)", "Socotra Governorate"),        # Socotra_satview.jpg, a satellite view
    "YE:3": ("Beaches & dunes (Socotra)", "Qulensya"),                      # the same satellite view (hidden)
}

# Country|subject pairs that already equalled a gallery[:6] title on
# 2026-10-31 (the row shows the photo and the hero leaves it out). Frozen so
# that a new one fails; whether these should stay is Doug's call.
GALLERY_OVERLAP_2026_10_31 = {
    "AF|Kabul", "AL|Berat", "AM|Geghard", "AO|Luanda", "AQ|Chinstrap penguin", "AQ|Neko Harbour",
    "AQ|Paradise Harbour", "AR|Iguazú Falls", "AT|Salzburg", "AU|Uluru", "AW|Eagle Beach", "AZ|Flame Towers",
    "BA|Sarajevo", "BB|Bathsheba, Barbados", "BB|St Nicholas Abbey", "BD|Cox's Bazar", "BE|Bruges",
    "BH|Bab Al Bahrain", "BH|Qal'at al-Bahrain", "BH|Tree of Life (Bahrain)", "BN|Kampong Ayer",
    "BW|Chobe National Park", "BW|Okavango Delta", "BY|Brest Fortress", "BY|Minsk", "CA|Niagara Falls",
    "CD|Congo River", "CL|Easter Island", "CM|Kribi", "CN|Great Wall of China", "CO|Tayrona National Natural Park",
    "CV|Pico do Fogo", "CV|Ponta do Sol, Cape Verde", "CW|Grote Knip", "CW|Klein Curaçao", "CW|Willemstad",
    "CY|Kourion", "DZ|Timgad", "EC|Galápagos Islands", "EC|Quito", "ER|Massawa", "ES|Seville", "ET|Lalibela",
    "FK|King penguin", "FO|Gásadalur", "FO|Sørvágsvatn", "GA|Libreville", "GB-ENG|Lake District",
    "GB-WLS|Conwy Castle", "GB-WLS|Snowdon", "GE|Tbilisi", "GE|Vardzia", "GH|Mole National Park", "GT|Tikal",
    "HN|Pico Bonito", "HR|Dubrovnik", "HT|Citadelle Laferrière", "HU|Hungarian Parliament Building",
    "IE|Cliffs of Moher", "IE|Ring of Kerry", "IL|Masada", "IM|Laxey Wheel", "IM|Peel Castle", "IN|Kerala",
    "IN|Taj Mahal", "IQ|Babylon", "IS|Blue Lagoon (geothermal spa)", "JO|Jerash", "JO|Petra", "JO|Wadi Rum",
    "KE|Masai Mara", "KH|Angkor Wat", "KZ|Charyn Canyon", "LB|Baalbek", "LK|Sigiriya", "LR|Monrovia",
    "LS|Maletsunyane Falls", "LT|Curonian Spit", "LT|Hill of Crosses", "LV|Riga", "LY|Leptis Magna",
    "MA|Marrakesh", "MD|Chișinău", "MD|Orheiul Vechi", "ME|Budva", "ME|Kotor",
    "MG|Tsingy de Bemaraha Strict Nature Reserve", "MK|Matka Canyon", "MK|Ohrid", "MK|Skopje", "ML|Timbuktu",
    "MM|Bagan", "MM|Inle Lake", "MX|Chichen Itza", "MY|George Town, Penang", "NA|Fish River Canyon",
    "NC|Nouméa", "NE|Aïr Mountains", "NO|Lofoten", "NP|Pokhara", "NZ|Milford Sound", "PE|Lima",
    "PE|Machu Picchu", "PK|Fairy Meadows", "PS|Hebron", "QA|Souq Waqif", "RU|Red Square",
    "RW|Volcanoes National Park", "SA|AlUla", "SB|Guadalcanal", "SD|Khartoum", "SI|Triglav",
    "SR|Central Suriname Nature Reserve", "SY|Krak des Chevaliers", "TD|Lakes of Ounianga", "TJ|Fann Mountains",
    "TL|Dili", "TM|Ashgabat", "TR|Cappadocia", "TR|Ephesus", "TW|Taroko National Park", "TZ|Mount Kilimanjaro",
    "UA|Lviv", "UY|Montevideo", "UZ|Khiva", "VE|Canaima National Park", "VE|Los Roques", "VE|Mount Roraima",
    "VN|Hanoi", "VN|Ho Chi Minh City", "VU|Mount Yasur", "XK|Pristina", "XK|Rugova Canyon", "YE|Shibam",
    "ZA|Kruger National Park", "ZM|South Luangwa National Park", "ZM|Victoria Falls", "ZW|Great Zimbabwe",
    "ZW|Victoria Falls",
}

rows = [(iso, i, x) for iso in acts for i, x in enumerate(acts[iso].get("activities") or [])]

# ---- 1. the file's format --------------------------------------------------------------------
print("1. public/activities.json format")
results.append(ok("\n" not in RAW and RAW == json.dumps(acts, separators=(",", ":"), ensure_ascii=False),
                  "one line, compact separators, unescaped UTF-8, no trailing newline"))
results.append(ok(RAW == json.dumps(acts, separators=(",", ":"), ensure_ascii=False, sort_keys=True),
                  "every object's keys are in sorted order (an activity is d, p, t)"))
odd = ["%s:%d" % (iso, i) for iso, i, x in rows
       if not isinstance(x, dict) or not {"d", "t"} <= set(x) <= {"d", "p", "t"}
       or not isinstance(x.get("t"), str) or not x["t"].strip()]
results.append(ok(not odd and len(acts) == 190, "%d activities in %d guides, each a {d, t[, p]} object (odd: %s)"
                  % (len(rows), len(acts), odd[:5])))

# ---- 2. "p" ------------------------------------------------------------------------------------
print("2. every \"p\" is a usable title")
ps = [(iso, i, x["p"]) for iso, i, x in rows if isinstance(x, dict) and "p" in x]
bad_p = [(iso, i, p) for iso, i, p in ps if not isinstance(p, str) or not p.strip() or p != p.strip()
         or "  " in p or "|" in p or "#" in p]
results.append(ok(not bad_p and len(ps) >= 214,          # 183 before the audit, +31 new (5 more replaced)
                  "%d rows carry a \"p\": non-empty strings, trimmed, no '|' or '#' (bad: %s)" % (len(ps), bad_p[:5])))

# ---- 3. the mirror is app.js's own rule ----------------------------------------------------------
print("3. activitySubject: Python mirror vs app.js under jsc")
EDGE = [
    {"d": "", "t": "Safari (Kissama)"},
    {"d": "", "t": "Waterfalls (Kalandula, Malanje)"},
    {"d": "", "t": "Desert scenery (Iona NP)"},
    {"d": "", "t": "Treks (Mt Mulanje)"},
    {"d": "", "t": "Mt Kenya trek"},
    {"d": "", "t": "NPR NP lodge"},
    {"d": "", "t": "Lakes (Mt Ölgii NP)"},
    {"d": "", "t": "Treks (Mt Elgon Mt trail, NP NP)"},
    {"d": "", "t": "Parks (NP and NP)"},
    {"d": "", "t": "Old town nightlife"},
    {"d": "", "t": "Beaches (Ayia Napa) and more (Paphos)"},
    {"d": "", "t": "Trailing (  Spaced  )"},
    {"d": "", "t": "Nested (a (b) c)"},
    {"d": "", "t": "Unclosed (paren"},
    {"d": "", "t": "Empty () parens"},
    {"d": "", "p": "", "t": "Empty p (Falls Back)"},
    {"d": "", "p": "Pinned Title", "t": "Pinned (Ignored)"},
    "Bare string row (Place)",
]
inputs = [x for _, _, x in rows] + EDGE
prog = "\n".join([build_js._cut(APP, "function actLabel"), build_js._cut(APP, "function activitySubject"),
                  "const ROWS = %s;" % json.dumps(inputs, ensure_ascii=False),
                  "print(JSON.stringify(ROWS.map(activitySubject)));"])
with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
    f.write(prog)
try:
    run = subprocess.run([JSC, f.name], capture_output=True, text=True, timeout=30)
finally:
    os.remove(f.name)
js = json.loads(run.stdout.strip().splitlines()[-1]) if run.returncode == 0 and run.stdout.strip() else None
py = [activity_subject(x) for x in inputs]
if js is None:
    results.append(ok(False, "jsc ran app.js activitySubject (stderr: %s)" % run.stderr[-300:]))
else:
    diff = [(inputs[k], js[k], py[k]) for k in range(len(inputs)) if js[k] != py[k]]
    results.append(ok(not diff and len(js) == len(inputs),
                      "app.js and the mirror agree on all %d rows and %d edge cases (first diff: %s)"
                      % (len(rows), len(EDGE), diff[:1])))
    expect_edge = ["Kissama", "Kalandula", "Iona National Park", "Mount Mulanje", "Mount Kenya trek",
                   "NPR National Park lodge", "Mount Ölgii National Park", "Mount Elgon Mt trail", "National Park and NP", "Old town nightlife", "Ayia Napa",
                   "Spaced", "a (b", "paren", "Empty parens", "Falls Back", "Pinned Title", "Place"]
    results.append(ok(js[len(rows):] == expect_edge,
                      "the edge table reads as written (comma cut, NP/Mt once, ASCII \\b, empty p falls back)"))
import activity_thumb_audit  # noqa: E402  (import-safe: it fetches nothing until a command runs)
results.append(ok(all(activity_thumb_audit.activity_subject(x) == s for x, s in zip(inputs, py)),
                  "scripts/dev/activity_thumb_audit.py's activity_subject is the same rule"))
ap = build_js._cut(APP, "async function actPhoto")
asks = ['wikiIconic(subject, 700, 500)', 'wikiIconic(subject + ", " + country, 700, 500)',
        'wikiIconic(subject + " (" + country + ")", 700, 500)']
results.append(ok(all(a in ap for a in asks) and ap.index(asks[0]) < ap.index(asks[1]) < ap.index(asks[2]),
                  "actPhoto still asks subject, \"subject, Country\", \"subject (Country)\" at 700x500"))

# ---- 4. the fixed rows ---------------------------------------------------------------------------
print("4. the 36 rows fixed on 2026-10-31 keep their subjects")
by = {"%s:%d" % (iso, i): x for iso, i, x in rows}
moved = [(k, act_label(by.get(k)), activity_subject(by[k]) if k in by else None) for k, (t, s) in FIXED.items()
         if k not in by or act_label(by[k]) != t or activity_subject(by[k]) != s]
results.append(ok(len(FIXED) == 36 and not moved, "%d rows: title and subject as pinned (moved: %s)"
                  % (len(FIXED), moved[:3])))
results.append(ok(all(by[k].get("p") == s for k, (_, s) in FIXED.items() if k in by),
                  "each gets its subject from its own \"p\" (not from the title)"))

# ---- 5. hero galleries ---------------------------------------------------------------------------
print("5. no subject is a title the country's hero gallery shows")
now = set()
for iso, i, x in rows:
    g = [e for e in (acts[iso].get("gallery") or [])[:6] if isinstance(e, str)]
    if activity_subject(x) in g:
        now.add("%s|%s" % (iso, activity_subject(x)))
new = sorted(now - GALLERY_OVERLAP_2026_10_31)
results.append(ok(not new, "no subject equals a gallery[:6] title beyond the %d frozen pairs (%d still hold; new: %s)"
                  % (len(GALLERY_OVERLAP_2026_10_31), len(now & GALLERY_OVERLAP_2026_10_31), new[:5])))
clash = []
for k, (_, s) in FIXED.items():
    iso = k.split(":")[0]
    labels = [e if isinstance(e, str) else e.get("label") for e in (acts[iso].get("gallery") or [])]
    if s in labels:
        clash.append(k)
results.append(ok(not clash, "no fixed row's subject is any gallery entry of its country (%s)" % clash))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
