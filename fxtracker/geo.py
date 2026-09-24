"""Country geometry helpers over public/world.geojson, shared by the build
scripts and the newsletter scorer.

country_centroids() is a line-for-line port of app.js countryCentroids(): the
area centroid of each country's LARGEST ring, nudged onto land when a concave
shape puts it outside. A plain vertex average gets dragged toward vertex-dense
coastlines and overseas parts — it put France's climate sample in the Atlantic
west of Morocco (French Guiana's vertices) and Fiji's in the Indian Ocean
(antimeridian vertices averaging out).
"""

import json
import math
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GEOJSON = os.path.join(ROOT, "public", "world.geojson")


def load_world(path=GEOJSON):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def polygons(geometry):
    """Every polygon (list of rings) in a Polygon or MultiPolygon."""
    if geometry["type"] == "MultiPolygon":
        return geometry["coordinates"]
    return [geometry["coordinates"]]


def in_ring(pt, ring):
    """Even-odd point-in-ring test (same as app.js inRing)."""
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > pt[1]) != (yj > pt[1]) and \
                pt[0] < (xj - xi) * (pt[1] - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_geometry(pt, geometry):
    """True when pt (lon, lat) is on any polygon's land (outer ring, not a hole)."""
    for poly in polygons(geometry):
        if poly and in_ring(pt, poly[0]) and not any(in_ring(pt, h) for h in poly[1:]):
            return True
    return False


def _ring_area(ring):
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2


def largest_ring(geometry):
    best, best_a = None, -1
    for poly in polygons(geometry):
        ring = poly[0]
        a = _ring_area(ring)
        if a > best_a:
            best_a, best = a, ring
    return best


def ring_centroid(ring):
    """Shoelace centroid of one ring, nudged to the nearest interior point of a
    16x16 grid over its bounding box when a concave shape (Norway's fjord
    crescent, Croatia's banana, Vietnam's S) puts it outside. None if degenerate."""
    a2 = cx = cy = 0.0
    for i in range(len(ring) - 1):
        cr = ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
        a2 += cr
        cx += (ring[i][0] + ring[i + 1][0]) * cr
        cy += (ring[i][1] + ring[i + 1][1]) * cr
    if not a2:
        return None
    c = [cx / (3 * a2), cy / (3 * a2)]
    if not in_ring(c, ring):
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        mnx, mxx, mny, mxy = min(xs), max(xs), min(ys), max(ys)
        best_pt, best_d = None, float("inf")
        n = 16
        for gy in range(1, n):
            for gx in range(1, n):
                p = [mnx + (mxx - mnx) * gx / n, mny + (mxy - mny) * gy / n]
                if not in_ring(p, ring):
                    continue
                d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2
                if d < best_d:
                    best_d, best_pt = d, p
        if best_pt:
            c = best_pt
    return c


def country_centroids(world=None):
    """{iso: [lon, lat]} exactly as app.js countryCentroids() computes it."""
    world = world or load_world()
    out = {}
    for f in world["features"]:
        props = f["properties"]
        # The Northern Ireland subdivision carries iso "GB"; it must not
        # overwrite the real UK centroid.
        if props.get("sub") and props.get("iso") == props.get("sub"):
            continue
        ring = largest_ring(f["geometry"])
        if not ring:
            continue
        c = ring_centroid(ring)
        if c is not None:
            out[props.get("iso")] = c
    out.setdefault("BQ", [-68.26, 12.18])   # Caribbean Netherlands (Bonaire), no geometry
    return out


def bbox(geometry):
    """(min_lon, min_lat, max_lon, max_lat) over every ring."""
    xs, ys = [], []
    for poly in polygons(geometry):
        for ring in poly:
            for p in ring:
                xs.append(p[0])
                ys.append(p[1])
    return min(xs), min(ys), max(xs), max(ys)


def dist_km(a, b):
    """Great-circle distance between two (lon, lat) points (app.js distKm)."""
    r, to_r = 6371, math.pi / 180
    dlat = (b[1] - a[1]) * to_r
    dlon = (b[0] - a[0]) * to_r
    s = math.sin(dlat / 2) ** 2 + \
        math.cos(a[1] * to_r) * math.cos(b[1] * to_r) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(s))
