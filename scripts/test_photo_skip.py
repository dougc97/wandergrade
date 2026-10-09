"""The hero-photo skip list and the galleries it guards, without the network.

    /usr/bin/python3 scripts/test_photo_skip.py

  * public/photo-skip.json parses, is dated, and lists unique Commons file
    names (no paths, no URLs, no blanks);
  * every country's gallery is 1-6 unique Wikipedia titles; fewer than 4 is
    reported (the 2026-10 sweep could not find four good photos for a few
    small countries), none is a failure;
  * app.js consults the list inside wikiIconic (the hero and the activity
    thumbs both go through it) and gen_og_images.py reads it too.
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC = os.path.join(ROOT, "public")
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []

with open(os.path.join(PUBLIC, "photo-skip.json"), encoding="utf-8") as f:
    skip = json.load(f)
files = skip.get("files") or []
results.append(ok(re.fullmatch(r"\d{4}-\d{2}-\d{2}", skip.get("asof", "")) is not None, "photo-skip.json carries an as-of date"))
results.append(ok(len(files) == len(set(files)) and len(files) > 100, "%d unique rejected files" % len(files)))
bad = [x for x in files if not x or "/" in x or x.startswith("http") or x != x.strip()]
results.append(ok(not bad, "every entry is a bare Commons file name (%d odd: %s)" % (len(bad), bad[:3])))

with open(os.path.join(PUBLIC, "activities.json"), encoding="utf-8") as f:
    acts = json.load(f)
thin, broken = [], []
for iso, a in sorted(acts.items()):
    g = a.get("gallery") or []
    if not (1 <= len(g) <= 6) or len(g) != len(set(g)) or any(not isinstance(s, str) or not s.strip() for s in g):
        broken.append(iso)
    elif len(g) < 4:
        thin.append("%s:%d" % (iso, len(g)))
results.append(ok(not broken, "every gallery is 1-6 unique titles (%s)" % (", ".join(broken) or "all %d" % len(acts))))
print("  note  galleries under 4 subjects: %s" % (", ".join(thin) or "none"))

with open(os.path.join(PUBLIC, "app.js"), encoding="utf-8") as f:
    app = f.read()
results.append(ok("photo-skip.json" in app and "photoSkip()" in app and "(await skipP).has(page.pageimage)" in app,
                  "app.js wikiIconic consults the skip list"))
with open(os.path.join(ROOT, "scripts", "gen_og_images.py"), encoding="utf-8") as f:
    og = f.read()
results.append(ok("photo-skip.json" in og and "in SKIP" in og, "gen_og_images.py reads the skip list"))
results.append(ok(acts["PH"]["gallery"][0] == "El Nido, Palawan" and acts["PH"]["gallery"][1] == "Mayon",
                  "the Philippines keeps Doug's order: El Nido, then Mayon"))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
