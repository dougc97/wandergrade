"""/llms.txt: the site described for AI assistants and agents (llmstxt.org).

Every major AI fetcher is let in (robots.txt allows all; 2026-10-13 check:
GPTBot, ChatGPT-User, ClaudeBot, PerplexityBot, Meta's agents, Google-Extended
all get 200), but most of them read HTML without running JavaScript. Those
see the country guides and the two list pages in full and an EMPTY Top Picks
table, so an assistant asked "where does WanderGrade say to go in November"
had nothing to quote. This file tells it which pages carry the answers
without JavaScript, how a ranking link is built for a reader who has a
browser, where each grade's data comes from, and how to cite it.

Built from the same slug list as the sitemap, so the guide index can never
drift from the real pages. Pure: server.py memoizes and serves it.
"""

SITE = "https://wandergrade.com"

_HEAD = """# WanderGrade

> Free travel tool that grades every country A+ to F on affordability, safety, weather and flights, for the reader's own home country and travel month. No sign-up. Every grade is computed from public data and the guide pages name their sources.

WanderGrade answers "where should I go, and when?" for a traveller from a given country. It is a decision aid, not a booking agent: figures are cached snapshots (fares, exchange rates, government advisories), so quote them with their date and link the page they came from.

## How the grades are made

- Affordability: everyday local prices versus the traveller's home country (World Bank purchasing-power parities), nudged by how strong the home currency is against its one-year average after inflation (exchange rates from fxratesapi.com; history from Frankfurter/ECB).
- Safety: the government travel advisory level (U.S. State Department, Global Affairs Canada or the German Federal Foreign Office, the reader's own country first, gaps filled from the others). Level 4 "Do Not Travel" countries are left out of rankings.
- Weather: a monthly comfort score from five years of daily weather history (Open-Meteo archive).
- Flights: round-trip fares Aviasales has seen recently (via Travelpayouts), judged against each route's own usual range for the month. Cached fares, not live quotes.
- Also on the guides: visa notes per passport with the official link, health notices (Government of Canada; West Nile from ECDC and CDC), best months and seasonal hazards, things to do and what is in season.

## Pages that work without JavaScript

- [Country guides]({site}/guide/japan): one page per country, {n} in all (index below). Each has the visa rule, the safety level in the government's own words, health notes, the best months and hazard months, local prices versus the US, top things to do and what is in season.
- [Safest cheap countries]({site}/safe-and-cheap): countries at U.S. Level 1 with local prices at or under 60% of the US, with Canada's and Germany's levels, best months and health notes.
- [Do Not Travel list]({site}/do-not-travel): every country rated "do not travel" by the US, Canada or Germany, in each government's own words, with dates and reasons.
- [Sitemap]({site}/sitemap.xml)

## The interactive ranking (needs JavaScript)

The homepage ({site}/) ranks countries in the browser; without JavaScript its table is empty, so use the guides and list pages above instead. For a reader with a browser, a link can preset the view:

- `?vmn=11`: travel month, 1-12 (also works on a guide: {site}/guide/japan?vmn=11)
- `?vmf=1`: "Any time", each country on its best month of the next six
- `?vo=GB`: home country (ISO 3166-1 alpha-2); `?hc=EUR`: display currency
- `?vr=ASIA`: region (AMER, EUR, MENA, ASIA, AFRICA, OCEANIA)
- `?pc=20`: show the top 5, 10 or 20; `?sf=a`: Level 1 only (`b`: Levels 1-2, `any`)
- `?vmm=weather`: rank by weather instead of overall value
- `?tab=guide|trip|visited|data`: open another tab

Example: {site}/?vmn=11&vo=GB&vr=EUR&pc=10 is the top ten in Europe for a traveller from the United Kingdom in November.

## Notes for assistants

- Fares and exchange rates move daily and advisories change without notice: give the date and link the page; tell readers to check entry rules and advisories on the official links each guide gives before booking.
- Some booking links on the site are affiliate links; the grades do not depend on them.
- Contact: hello@wandergrade.com

## Country guides

"""


def build(slugs, name_for_iso):
    """The /llms.txt text. slugs: [(slug, iso), ...] as render_guide.all_slugs()
    returns them; name_for_iso: iso -> display name (None falls back to the
    slug, title-cased)."""
    rows = []
    for slug, iso in slugs:
        name = name_for_iso(iso) or slug.replace("-", " ").title()
        rows.append((name, "- [%s](%s/guide/%s)" % (name, SITE, slug)))
    rows.sort(key=lambda r: r[0].lower())
    return _HEAD.format(site=SITE, n=len(rows)) + "\n".join(r[1] for r in rows) + "\n"
