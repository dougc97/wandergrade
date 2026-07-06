import json
slugs=json.load(open('public/slugs.json'))  # slug->iso
SITE="https://wandergrade.com"
static=[("/","daily","1.0"),("/?tab=data","daily","0.6"),("/?tab=visited","monthly","0.5")]
lines=['<?xml version="1.0" encoding="UTF-8"?>',
       '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
for loc,cf,pr in static:
    lines+=[f'  <url><loc>{SITE}{loc}</loc><changefreq>{cf}</changefreq><priority>{pr}</priority></url>']
for slug in sorted(slugs):
    lines.append(f'  <url><loc>{SITE}/guide/{slug}</loc><changefreq>weekly</changefreq><priority>0.8</priority></url>')
lines.append('</urlset>')
open('public/sitemap.xml','w').write("\n".join(lines)+"\n")
print("sitemap urls:",len(static)+len(slugs))
