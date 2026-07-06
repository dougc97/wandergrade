import json,unicodedata,re
acts=json.load(open('public/activities.json'))
clim=json.load(open('public/climate.json'))
ppp=json.load(open('public/ppp.json'))
# Clean, SEO-friendly display names where the map-derived name is abbreviated/awkward.
OVERRIDE={
 'MU':'Mauritius','SG':'Singapore',
 'BA':'Bosnia and Herzegovina','CF':'Central African Republic','CD':'DR Congo',
 'DO':'Dominican Republic','GQ':'Equatorial Guinea','FK':'Falkland Islands',
 'TF':'French Southern Territories','SS':'South Sudan','SB':'Solomon Islands',
 'US':'United States','EH':'Western Sahara','CG':'Republic of the Congo',
}
names={}
for iso in acts:
    n=OVERRIDE.get(iso) or (clim.get(iso,{}) or {}).get('name') or (ppp.get(iso,{}) or {}).get('name')
    names[iso]=n
def slugify(s):
    s=unicodedata.normalize('NFKD',s).encode('ascii','ignore').decode('ascii')
    s=s.replace('&','and').lower()
    s=re.sub(r"[^a-z0-9]+","-",s).strip('-')
    return s
slug2iso={}; iso2slug={}
for iso in sorted(names):
    base=slugify(names[iso]); slug=base; i=2
    while slug in slug2iso:
        slug=base+'-'+str(i); i+=1
    slug2iso[slug]=iso; iso2slug[iso]=slug
json.dump(slug2iso,open('public/slugs.json','w'),separators=(',',':'),ensure_ascii=False,sort_keys=True)
json.dump(names,open('public/country-names.json','w'),separators=(',',':'),ensure_ascii=False,sort_keys=True)
print('wrote',len(slug2iso),'slugs')
for iso in ['JP','US','KR','CD','CG','EH','CF','BA','GB','FR']:
    print(iso,'->',iso2slug[iso],'|',names[iso])
