#!/usr/bin/env python3
"""Re-word the titles (t) in public/guide-facts.json from render_guide.meta(),
each from the entry's own stored figures, and nothing else: no figure,
description, date or other entry changes, so the file is not rebuilt.

For a title switch such as render_guide.TITLE_BEST_TIME: turn it on, run this,
commit both (scripts/test_guide_meta.py holds every t equal to meta()).

    python3 scripts/retitle_guide_facts.py           # rewrite the file
    python3 scripts/retitle_guide_facts.py --check   # list what would change
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from fxtracker import render_guide  # noqa: E402

PATH = os.path.join(ROOT, "public", "guide-facts.json")


def retitle(raw):
    """(new file text, [(iso, old, new)]) — each entry's "t" replaced in place."""
    doc = json.loads(raw)
    asof = render_guide.snapshot_asof(doc)
    changed = []
    for iso, f in doc.items():
        if not isinstance(f, dict) or "t" not in f:
            continue
        new = render_guide.meta(iso, f, asof)["title"]
        if new == f["t"]:
            continue
        old = '"%s":{' % iso
        a = raw.index(old)
        b = raw.index("\n", a)
        line = raw[a:b]
        was = '"t":%s' % json.dumps(f["t"], ensure_ascii=False)
        if line.count(was) != 1:
            raise SystemExit("%s: its title isn't where this script expects it" % iso)
        raw = raw[:a] + line.replace(was, '"t":%s' % json.dumps(new, ensure_ascii=False)) + raw[b:]
        changed.append((iso, f["t"], new))
    return raw, changed


if __name__ == "__main__":
    with open(PATH, encoding="utf-8") as fh:
        raw = fh.read()
    out, changed = retitle(raw)
    for iso, old, new in changed:
        print("%-6s %s\n       -> %s" % (iso, old, new))
    print("%d title(s) %s" % (len(changed), "would change" if "--check" in sys.argv else "changed"))
    if changed and "--check" not in sys.argv:
        with open(PATH, "w", encoding="utf-8") as fh:
            fh.write(out)
