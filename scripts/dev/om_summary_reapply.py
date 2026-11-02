"""Re-apply Oman's guide summary, Doug's wording of 2026-11-01, after a merge
took another branch's one-line public/activities.json (or guide-facts.json)
and brought back "Wadis, dunes, forts and a dramatic fjord-like coast." (that
coast is Musandam, which the US advisory reissued 2026-10-23 says not to
visit). scripts/test_guide_meta.py's Oman check fails until this is run.

    /usr/bin/python3 scripts/dev/om_summary_reapply.py [<tree>]

<tree> defaults to this checkout.
1. activities.json: OM "summary" -> NEW (a no-op if it already is). Loads the
   file, changes that one field, asserts nothing else changed, writes it back
   as json.dumps(obj, separators=(",", ":"), ensure_ascii=False,
   sort_keys=True) with no trailing newline. Any summary other than OLD or
   NEW stops it: look before overwriting.
2. guide-facts.json: OM "dn" -> render_guide.meta_numberfree("OM") computed in
   a fresh process from the tree (a no-op if it already is). Only that field
   of the OM line may change; nothing else in the file is touched.
Then run scripts/test_guide_meta.py: its Oman check and its t/d/dn check
must both pass.
"""
import copy
import json
import os
import subprocess
import sys

root = os.path.realpath(sys.argv[1] if len(sys.argv) > 1 else
                        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OLD = "Wadis, dunes, forts and a dramatic fjord-like coast."
NEW = "Wadis, dunes, desert forts and turtle beaches."
dump = lambda o: json.dumps(o, separators=(",", ":"), ensure_ascii=False, sort_keys=True)

# --- 1. activities.json ---------------------------------------------------------
ap = os.path.join(root, "public", "activities.json")
raw = open(ap, encoding="utf-8").read()
obj = json.loads(raw)
assert dump(obj) == raw, "activities.json is not in its canonical format to begin with"
cur = obj["OM"]["summary"]
if cur == NEW:
    print("activities.json: OM summary already the new one; unchanged")
else:
    assert cur == OLD, "unexpected OM summary %r: look before overwriting it" % cur
    before = copy.deepcopy(obj)
    obj["OM"]["summary"] = NEW
    assert set(obj) == set(before) and all(obj[k] == before[k] for k in obj if k != "OM")
    assert {k: v for k, v in obj["OM"].items() if k != "summary"} == \
           {k: v for k, v in before["OM"].items() if k != "summary"}
    out = dump(obj)
    assert out.replace(json.dumps(NEW, ensure_ascii=False), json.dumps(OLD, ensure_ascii=False), 1) == raw
    with open(ap, "w", encoding="utf-8") as f:
        f.write(out)
    print("activities.json: OM summary set (%d -> %d bytes)" % (len(raw.encode()), len(out.encode())))

# --- 2. guide-facts.json OM dn ----------------------------------------------------
dn = subprocess.run([sys.executable, "-c",
                     "import os, sys; sys.path.insert(0, %r)\n"
                     "from fxtracker import render_guide as rg\n"
                     "assert os.path.realpath(rg.__file__).startswith(%r)\n"
                     "print(rg.meta_numberfree('OM'))" % (root, root)],
                    capture_output=True, text=True, check=True, cwd=root).stdout.rstrip("\n")
assert dn.endswith(" " + NEW), dn
sys.path.insert(0, root)
from fxtracker import guide_facts as GF  # noqa: E402

assert os.path.realpath(GF.__file__).startswith(root), GF.__file__
gp = os.path.join(root, "public", "guide-facts.json")
graw = open(gp, encoding="utf-8").read()
doc = json.loads(graw)
assert GF.dump(doc) == graw, "guide-facts.json does not round-trip through guide_facts.dump"
if doc["OM"].get("dn") == dn:
    print("guide-facts.json: OM dn already %r; unchanged" % dn)
else:
    before = copy.deepcopy(doc)
    doc["OM"]["dn"] = dn
    assert all(doc[k] == before[k] for k in doc if k != "OM")
    assert {k: v for k, v in doc["OM"].items() if k != "dn"} == \
           {k: v for k, v in before["OM"].items() if k != "dn"}
    gout = GF.dump(doc)
    a, b = graw.split("\n"), gout.split("\n")
    diff = [i for i in range(len(a)) if a[i] != b[i]]
    assert len(a) == len(b) and len(diff) == 1 and a[diff[0]].startswith('"OM":'), diff
    with open(gp, "w", encoding="utf-8") as f:
        f.write(gout)
    print("guide-facts.json: only line %d (OM) changed\n- %s\n+ %s" % (diff[0] + 1, a[diff[0]], b[diff[0]]))
