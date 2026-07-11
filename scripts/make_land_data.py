#!/usr/bin/env python3
"""Regenerate the WORLD_LAND_ENC coastline string embedded in public/app.js.

Source data: Natural Earth 110m land polygons (public domain):
  curl -sLO https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_land.geojson

Usage: python3 scripts/make_land_data.py ne_110m_land.geojson
Prints stats and writes land_enc.txt next to the input; paste its contents
into the WORLD_LAND_ENC constant in public/app.js.

Output format: polygons joined by ';', each polygon 'lon,lat,lon,lat,...'
with integer-degree coordinates (plenty at a ~200px globe: 1 deg ~ 1px).
"""
import json, math, os, sys

def dp(points, tol):
    """Douglas-Peucker simplification."""
    if len(points) < 3:
        return points
    def perp(p, a, b):
        ax, ay = a; bx, by = b; px, py = p
        dx, dy = bx - ax, by - ay
        if dx == dy == 0:
            return math.hypot(px - ax, py - ay)
        t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
    dmax, idx = 0, 0
    for i in range(1, len(points) - 1):
        d = perp(points[i], points[0], points[-1])
        if d > dmax:
            dmax, idx = d, i
    if dmax > tol:
        left = dp(points[:idx + 1], tol)
        right = dp(points[idx:], tol)
        return left[:-1] + right
    return [points[0], points[-1]]

def ring_area(pts):
    s = 0
    for i in range(len(pts) - 1):
        s += pts[i][0] * pts[i + 1][1] - pts[i + 1][0] * pts[i][1]
    return abs(s) / 2

src = sys.argv[1] if len(sys.argv) > 1 else "ne_110m_land.geojson"
gj = json.load(open(src))
polys = []
for f in gj["features"]:
    g = f["geometry"]
    rings = []
    if g["type"] == "Polygon":
        rings = [g["coordinates"][0]]          # outer ring only
    elif g["type"] == "MultiPolygon":
        rings = [p[0] for p in g["coordinates"]]
    for r in rings:
        if ring_area(r) < 6:                   # drop specks < ~6 sq deg (tiny islets)
            continue
        s = dp(r, 0.55)
        # quantize to integer degrees, drop consecutive dupes
        q, prev = [], None
        for lon, lat in s:
            pt = (round(lon), round(lat))
            if pt != prev:
                q.append(pt)
                prev = pt
        if len(q) >= 4:
            polys.append(q)

# sort biggest-first so major continents paint first
polys.sort(key=lambda p: -ring_area([(x, y) for x, y in p] + [p[0]]))
enc = ";".join(",".join(f"{x},{y}" for x, y in p) for p in polys)
print(f"polygons: {len(polys)}, points: {sum(len(p) for p in polys)}, encoded bytes: {len(enc)}")
out = os.path.join(os.path.dirname(os.path.abspath(src)), "land_enc.txt")
open(out, "w").write(enc)
print(f"wrote {out}")
