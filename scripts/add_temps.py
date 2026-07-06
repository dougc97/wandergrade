import json, os, time, urllib.request, ssl
from collections import defaultdict
GEOJSON="public/world.geojson"; CLIM="public/climate.json"
ARCHIVE="https://archive-api.open-meteo.com/v1/archive"; YEAR=("2024-01-01","2024-12-31")
ctx=ssl.create_default_context()
def centroid(g):
    polys=g["coordinates"]
    if g["type"]=="Polygon": polys=[polys]
    sx=sy=n=0
    for poly in polys:
        for ring in poly:
            for lon,lat in ring: sx+=lon; sy+=lat; n+=1
    return (sx/n,sy/n) if n else (None,None)
def mt(lat,lon):
    url=("{0}?latitude={1:.3f}&longitude={2:.3f}&start_date={3}&end_date={4}"
         "&daily=temperature_2m_mean&timezone=auto").format(ARCHIVE,lat,lon,YEAR[0],YEAR[1])
    req=urllib.request.Request(url,headers={"User-Agent":"wandergrade/1.0"})
    d=json.load(urllib.request.urlopen(req,timeout=30,context=ctx)).get("daily",{})
    times=d.get("time",[]); temps=d.get("temperature_2m_mean",[]); agg=defaultdict(list)
    for t,tp in zip(times,temps):
        if tp is not None: agg[int(t[5:7])].append(tp)
    return [round(sum(agg[m])/len(agg[m])) if agg[m] else None for m in range(1,13)]
geo=json.load(open(GEOJSON,encoding="utf-8")); clim=json.load(open(CLIM,encoding="utf-8"))
cent={}
for f in geo["features"]:
    iso=f["properties"].get("iso")
    if iso and iso!="-99" and iso not in cent: lon,lat=centroid(f["geometry"]); cent[iso]=(lat,lon)
def save(): json.dump(clim,open(CLIM,"w",encoding="utf-8"),separators=(",",":"),sort_keys=True)
done=0
todo=[i for i in sorted(clim) if not clim[i].get("temps")]
for iso in todo:
    ll=cent.get(iso)
    if not ll or ll[0] is None: continue
    try: clim[iso]["temps"]=mt(ll[0],ll[1]); done+=1
    except Exception as e: print("FAIL",iso,e,flush=True)
    if done%15==0: save()
    time.sleep(0.2)
save()
missing=[i for i in clim if not clim[i].get("temps")]
print("DONE added",done,"| still missing:",missing,flush=True)
