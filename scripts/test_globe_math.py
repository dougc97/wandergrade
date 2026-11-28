"""The small globes' maths (round 16): public/app.js globeProject /
globeInverse / gcPoints / globeMask / globeViewFor / globeRaster, run under
jsc (scripts/appjs_harness.js) on public/world.geojson.

    /usr/bin/python3 scripts/test_globe_math.py

What it holds the code to:
  * the orthographic projection and its inverse agree (50 random visible
    points, any centre), a point on the far side is not visible, and a
    screen point off the disc has no inverse;
  * gcPoints walks the great circle (the midpoint of 0,0 -> 90,0 is 45,0;
    every point on the sphere, the ends exact);
  * globeMask, rasterised once from world.geojson (1024x512, feature index
    + 1 per pixel, 0 = sea), puts Japan at Tokyo, France at Paris, the UK at
    London, the sea mid-Atlantic, and is built once;
  * globeViewFor centres on countryCentroids(), a guide-only place (Scotland)
    on its parent's (GB) via GUIDE_PARENT; a microstate gets a finite view;
  * the ring round a tiny highlighted place (Monaco, Singapore): a quarter
    of the radius on the 72px badge, never over 9px on the Trip globe;
  * globeRaster (the per-pixel pass, no canvas needed): the centre of
    France's own globe is the highlight green, the corners are transparent,
    open sea is ocean blue, an N. Cyprus (-99) highlight paints nothing,
    and England highlights the UK;
  * Doug's spin globe is untouched: drawMap, startGlobe, drawGlobe,
    sphereCache and landMask hash as on main, and the new code calls none
    of them.
"""
import hashlib, json, os, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ok = lambda c, m: print(("  PASS  " if c else "  FAIL  ") + m) or c
results = []
JSC = "/System/Library/Frameworks/JavaScriptCore.framework/Versions/Current/Helpers/jsc"
P = lambda *a: os.path.join(ROOT, *a)
APP = open(P("public", "app.js"), encoding="utf-8").read()
HARNESS = open(P("scripts", "appjs_harness.js"), encoding="utf-8").read()

DRIVER = r"""
worldGeo = JSON.parse(read(WORLD_PATH));
const out = {};
const T = (name, f) => { try { out[name] = f(); } catch (e) { out[name] = { error: String(e && e.stack || e) }; } };
let seed = 7;
const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
T("roundtrip", () => {
  const bad = []; let n = 0, tries = 0;
  while (n < 50 && tries < 5000) {
    tries++;
    const view = { lon: rnd() * 360 - 180, lat: rnd() * 160 - 80, r: 20 + rnd() * 200, cx: 50 + rnd() * 100, cy: 50 + rnd() * 100 };
    const p = [rnd() * 358 - 179, rnd() * 170 - 85];
    const q = globeProject(p[0], p[1], view);
    if (!q[2]) continue;
    // keep away from the very limb, where screen distance stops resolving latitude
    const dx = (q[0] - view.cx) / view.r, dy = (q[1] - view.cy) / view.r;
    if (dx * dx + dy * dy > 0.995) continue;
    n++;
    const b = globeInverse(q[0], q[1], view);
    const dlon = b ? Math.abs(((b[0] - p[0]) % 360 + 540) % 360 - 180) : 1e9;
    if (!b || dlon > 1e-6 || Math.abs(b[1] - p[1]) > 1e-6) bad.push([p, b, view]);
  }
  return { n, bad: bad.slice(0, 3) };
});
T("farside", () => {
  const v = { lon: 0, lat: 0, r: 100, cx: 100, cy: 100 };
  return [globeProject(0, 0, v), globeProject(180, 0, v), globeProject(100, 10, v), globeProject(30, 89, { lon: 0, lat: -60, r: 100, cx: 100, cy: 100 })];
});
T("offdisc", () => globeInverse(250, 100, { lon: 0, lat: 0, r: 100, cx: 100, cy: 100 }));
T("centre", () => globeProject(12, 34, { lon: 12, lat: 34, r: 50, cx: 60, cy: 70 }));
T("north", () => globeProject(12, 44, { lon: 12, lat: 34, r: 50, cx: 60, cy: 70 }));
T("gc", () => gcPoints([0, 0], [90, 0], 3));
T("gc2", () => {
  const pts = gcPoints([-74, 40.7], [139.7, 35.7], 17);
  return { n: pts.length, first: pts[0], last: pts[pts.length - 1],
           finite: pts.every((p) => isFinite(p[0]) && isFinite(p[1]) && Math.abs(p[1]) <= 90 && Math.abs(p[0]) <= 180),
           maxLat: Math.max(...pts.map((p) => p[1])) };
});
T("gcsame", () => gcPoints([10, 10], [10, 10], 4));
T("mask", () => {
  const m = globeMask();
  const at = (lon, lat) => { const x = Math.floor((lon + 180) / 360 * m.w), y = Math.floor((90 - lat) / 180 * m.h);
    return m.isoAt[m.ids[y * m.w + x]] || 0; };
  return { w: m.w, h: m.h, len: m.ids.length, isU8: m.ids instanceof Uint8Array, sea0: m.isoAt[0],
           tokyo: at(139.7, 35.7), paris: at(2.35, 48.86), atl: at(-30, 30), london: at(-0.13, 51.5),
           brazil: at(-47.9, -15.8), madrid: at(-3.7, 40.4), same: globeMask() === m,
           land: m.ids.reduce((s, v) => s + (v ? 1 : 0), 0) };
});
T("view_sct", () => [globeViewFor("GB-SCT", 72), countryCentroids().GB]);
T("view_fr", () => [globeViewFor("FR", 72), countryCentroids().FR]);
T("view_mc", () => globeViewFor("MC", 72));
T("view_none", () => globeViewFor("ZZ", 72));
const px = (data, w, x, y) => { const o = (y * w + x) * 4; return [data[o], data[o + 1], data[o + 2], data[o + 3]]; };
T("raster_fr", () => {
  const v = globeViewFor("FR", 72), d = globeRaster(v, 144, 144, { highlight: new Set(["FR"]) });
  return { len: d.length, centre: px(d, 144, 72, 72), corner: px(d, 144, 1, 1) };
});
T("raster_sea", () => {
  const v = { lon: -30, lat: 30, r: 28.8, cx: 36, cy: 36, w: 72, h: 72 }, d = globeRaster(v, 72, 72, { highlight: new Set() });
  return px(d, 72, 36, 36);
});
T("raster_99", () => {
  // N. Cyprus carries iso -99: highlighting it must paint no highlight green anywhere.
  const v = { lon: 33.6, lat: 35.3, r: 200, cx: 100, cy: 100, w: 200, h: 200 };
  const a = globeRaster(v, 200, 200, { highlight: new Set(["-99"]) }), b = globeRaster(v, 200, 200, { highlight: new Set() });
  let diff = 0; for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) diff++;
  return diff;
});
T("raster_eng", () => {
  const v = globeViewFor("GB-ENG", 72), d = globeRaster(v, 144, 144, { highlight: new Set(["GB-ENG"]) });
  const e = globeRaster(v, 144, 144, { highlight: new Set(["GB"]) });
  let diff = 0; for (let i = 0; i < d.length; i++) if (d[i] !== e[i]) diff++;
  return diff;
});
T("raster_agrees", () => {
  // The raster's own per-pixel maths against globeInverse + the mask, on a 2x canvas, two centres.
  const m = globeMask(), bad = []; let n = 0;
  for (const v of [{ lon: 100, lat: 10, r: 120, cx: 150, cy: 150, w: 300, h: 300 }, { lon: -60, lat: -45, r: 28.8, cx: 36, cy: 36, w: 72, h: 72 }]) {
    const dw = v.w * 2;
    globeRaster(v, dw, dw, { highlight: new Set() });
    const idb = _gIdb.subarray(0, dw * dw);   // the raster's per-pixel ids (one shared buffer)
    for (let i = 0; i < 400; i++) {
      const px = Math.floor(rnd() * dw), py = Math.floor(rnd() * dw), ll = globeInverse((px + 0.5) / 2, (py + 0.5) / 2, v);
      if (!ll) { if (idb[py * dw + px] !== -1) bad.push(["off", px, py]); continue; }
      const x = Math.floor((ll[0] + 180) / 360 * m.w) & (m.w - 1), y = Math.min(m.h - 1, Math.floor((90 - ll[1]) / 180 * m.h));
      n++;
      if (idb[py * dw + px] !== m.ids[y * m.w + x]) bad.push([px, py, ll, idb[py * dw + px], m.ids[y * m.w + x]]);
    }
  }
  return { n, bad: bad.length, ex: bad.slice(0, 3) };
});
T("ring", () => {
  // the tiny-place ring: a quarter of the radius on the 72px badge, never over 9px on a big globe
  const arcs = [];
  const ctx = new Proxy({}, { get: (o, k) => (k === "arc" ? (x, y, r) => arcs.push(r)
    : k === "createRadialGradient" ? () => ({ addColorStop() {} }) : k === "createImageData" ? (w, h) => ({ data: new Uint8ClampedArray(w * h * 4) })
    : k in o ? o[k] : () => {}), set: (o, k, v) => { o[k] = v; return true; } });
  const cv = (w) => ({ width: w, height: w, getContext: () => ctx });
  document.createElement = () => cv(10);
  const ringR = (iso, size) => { arcs.length = 0; const v = globeViewFor(iso, size); globeDraw(cv(size * 2), v, { highlight: new Set([iso]) });
    return arcs.filter((r) => r > 2.5 && Math.abs(r - v.r) > 1e-6 && Math.abs(r - v.r * 1.2) > 1e-6); };
  return { badge: ringR("MC", 72), big: ringR("MC", 380), sg: ringR("SG", 300), fr: ringR("FR", 300) };
});
print(JSON.stringify(out));
"""

with tempfile.TemporaryDirectory() as d:
    sp = os.path.join(d, "run.js")
    open(sp, "w", encoding="utf-8").write(HARNESS + "\n" + APP + "\n" + DRIVER.replace("WORLD_PATH", json.dumps(P("public", "world.geojson"))))
    r = subprocess.run([JSC, sp], capture_output=True, text=True, timeout=120)
try:
    js = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:
    js = {"error": (r.stderr or r.stdout)[-800:]}
results.append(ok("error" not in js, "app.js ran under jsc %s" % js.get("error", "")))
if "error" in js:
    print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
    sys.exit(1)
errs = {k: v["error"] for k, v in js.items() if isinstance(v, dict) and "error" in v}
results.append(ok(not errs, "every case ran %s" % (json.dumps(errs)[:900] if errs else "")))
G = lambda k: js.get(k) if not (isinstance(js.get(k), dict) and "error" in js.get(k)) else None
near = lambda a, b, e=1e-6: a is not None and b is not None and abs(a - b) <= e

rt = G("roundtrip") or {}
results.append(ok(rt.get("n") == 50 and not rt.get("bad"), "inverse(project(p)) = p within 1e-6 for 50 random visible points (%s)" % rt))
fs_ = G("farside") or [[0, 0, None]] * 4
results.append(ok(fs_[0][2] is True and fs_[1][2] is False and fs_[2][2] is False and fs_[3][2] is False,
                  "the centre is visible; the antipode, a point past the limb and the north pole seen from 60S are not (%s)" % [f[2] for f in fs_]))
results.append(ok(js.get("offdisc", 0) is None and "offdisc" in js, "a screen point off the disc has no inverse (%s)" % js.get("offdisc")))
c = G("centre") or [0, 0, 0]
results.append(ok(near(c[0], 60) and near(c[1], 70) and c[2] is True, "the view's centre projects to (cx, cy) (%s)" % c))
nn = G("north") or [0, 999, 0]
results.append(ok(near(nn[0], 60) and nn[1] < 70, "north is up: 10 degrees north of the centre is above it (%s)" % nn))
gc = G("gc") or []
results.append(ok(len(gc) == 3 and near(gc[1][0], 45) and near(gc[1][1], 0) and near(gc[0][0], 0) and near(gc[2][0], 90),
                  "gcPoints([0,0],[90,0],3) = [0,0],[45,0],[90,0] (%s)" % gc))
g2 = G("gc2") or {}
results.append(ok(g2.get("n") == 17 and g2.get("finite") and near(g2["first"][0], -74) and near(g2["last"][0], 139.7)
                  and near(g2["last"][1], 35.7) and g2.get("maxLat", 0) > 60,
                  "New York -> Tokyo: 17 points, ends exact, bows over the Arctic (max lat %s)" % g2.get("maxLat")))
gs = G("gcsame") or []
results.append(ok(len(gs) == 4 and all(near(p[0], 10) and near(p[1], 10) for p in gs), "a zero-length arc stays put (%s)" % gs))

m = G("mask") or {}
results.append(ok(m.get("w") == 1024 and m.get("h") == 512 and m.get("len") == 1024 * 512 and m.get("isU8"),
                  "globeMask is 1024x512 bytes (%s)" % {k: m.get(k) for k in ("w", "h", "len", "isU8")}))
results.append(ok(m.get("tokyo") == "JP" and m.get("paris") == "FR" and m.get("london") == "GB" and m.get("brazil") == "BR"
                  and m.get("madrid") == "ES", "JP at Tokyo, FR at Paris, GB at London, BR at Brasilia, ES at Madrid (%s)"
                  % {k: m.get(k) for k in ("tokyo", "paris", "london", "brazil", "madrid")}))
results.append(ok(m.get("atl") == 0 and not m.get("sea0"), "0 (sea) mid-Atlantic at (-30, 30) (%r)" % m.get("atl")))
land = (m.get("land") or 0) / (1024 * 512)
results.append(ok(0.22 < land < 0.36, "land is a plausible share of the equirectangular map (%.3f)" % land))
results.append(ok(m.get("same") is True, "built once (the same object the second time)"))

vs = G("view_sct") or [{}, [0, 0]]
results.append(ok(near(vs[0].get("lon"), vs[1][0]) and near(vs[0].get("lat"), vs[1][1]) and vs[0].get("cx") == 36 and vs[0].get("cy") == 36
                  and 0 < vs[0].get("r", 0) <= 36, "globeViewFor('GB-SCT', 72) centres on GB's centroid (%s)" % vs))
vf = G("view_fr") or [{}, [0, 0]]
results.append(ok(near(vf[0].get("lon"), vf[1][0]) and near(vf[0].get("lat"), vf[1][1]), "globeViewFor('FR') centres on France (%s)" % vf))
vm = G("view_mc") or {}
results.append(ok(all(isinstance(vm.get(k), (int, float)) for k in ("lon", "lat", "r", "cx", "cy")) and 43 < vm.get("lat", 0) < 44.5,
                  "a microstate (Monaco) gets a finite view on itself (%s)" % vm))
vz = G("view_none") or {}
results.append(ok(all(isinstance(vz.get(k), (int, float)) for k in ("lon", "lat", "r", "cx", "cy")), "an unknown place still gets a finite view (%s)" % vz))

rf = G("raster_fr") or {}
ce, co = rf.get("centre") or [0, 0, 0, 0], rf.get("corner") or [9, 9, 9, 9]
# the site green, #0a7d28 (10,125,40), shaded: dark, green-dominant
results.append(ok(rf.get("len") == 144 * 144 * 4 and ce[3] == 255 and ce[1] > ce[0] * 2 and ce[1] > ce[2] * 1.5 and ce[1] < 190,
                  "France's own globe: the centre pixel is the highlight green (%s)" % ce))
results.append(ok(co[3] == 0, "outside the disc: transparent (%s)" % co))
rs = G("raster_sea") or [0, 0, 0, 0]
results.append(ok(rs[3] == 255 and rs[2] > rs[1] > rs[0], "open sea is ocean blue (%s)" % rs))
results.append(ok(G("raster_99") == 0, "a -99 feature (N. Cyprus) is never highlighted (%s pixels changed)" % G("raster_99")))
results.append(ok(G("raster_eng") == 0, "England highlights the UK (GUIDE_PARENT) (%s pixels differ)" % G("raster_eng")))
ra = G("raster_agrees") or {}
# float32 column offsets can tip a pixel sitting exactly on a mask column edge: allow a handful in 800
results.append(ok(ra.get("n", 0) > 300 and ra.get("bad", 99) <= 4,
                  "the raster samples the same country as globeInverse + the mask (%s)" % ra))
rg = G("ring") or {}
results.append(ok(len(rg.get("badge") or []) == 1 and 7 < rg["badge"][0] < 8 and rg.get("fr") == []
                  and all(len(rg.get(k) or []) == 1 and rg[k][0] <= 9 for k in ("big", "sg")),
                  "the tiny-place ring: %.1fpx on the 72px badge (as before), at most 9px on a big globe (Monaco %s, Singapore %s), none for France"
                  % ((rg.get("badge") or [0])[0], rg.get("big"), rg.get("sg"))))

# Doug's spin globe and the flat maps: byte for byte as on main (186e43e).
def fn_src(name):
    i = APP.find("\nfunction " + name + "(")
    if i < 0:
        return None
    j = APP.find("{", i)
    depth, k = 0, j
    while k < len(APP):
        ch = APP[k]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return APP[i + 1:k + 1]
        k += 1
    return None
PINNED = {
    "drawMap": "aa0698b20d771605",
    "startGlobe": "999b6d8f6094c4d1",
    "drawGlobe": "13e6957e226beeb5",
    "sphereCache": "c609927f61bf6e1d",
    "landMask": "c9235941abeac622",
}
for name, want in PINNED.items():
    s = fn_src(name)
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:16] if s else None
    results.append(ok(h == want, "%s unchanged (sha256 %s)" % (name, h)))
a0, a1 = APP.find("// ---- small globes"), APP.find("// ---- end of small globes")
sec = APP[a0:a1] if 0 < a0 < a1 else ""
# its own comments may name them (to say it doesn't use them); the code never does
code = re.sub(r"^\s*//.*$", "", sec, flags=re.M)
results.append(ok(sec and not re.search(r"\b(drawGlobe|startGlobe|sphereCache|landMask|WORLD_LAND_ENC|_landMask|_sph)\b", code),
                  "the small-globe section calls none of the spin globe's code"))

print("\n%d/%d passed" % (sum(1 for x in results if x), len(results)))
sys.exit(0 if all(results) else 1)
