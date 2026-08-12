"""Server-side rendering for per-country Travel Guide pages (SEO).

Every country gets a real URL (/guide/<slug>) whose HTML the server fills in
with country-specific <title>/meta/canonical and a crawlable content block
(best months, things to do with their insight sentences, what's in season,
visa). The SPA then hydrates on top — app.js removes the SSR block (#ssrGuide)
once it renders the interactive guide, so users never see it twice.

All content is read from the same JSON the frontend uses; no new data.
"""

import html
import json
import os

PUBLIC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public")
SITE = "https://wandergrade.com"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
# Spelled out for prose. Every search that reaches these pages is some form of
# "best time to visit <country>", and people type "December", not "Dec" — the
# abbreviations were fine as chip labels and invisible as body copy.
MON_FULL = ["January", "February", "March", "April", "May", "June", "July",
            "August", "September", "October", "November", "December"]


def _join_and(items):
    """a, b and c — reads as a sentence rather than a data dump."""
    items = list(items)
    if len(items) <= 1:
        return items[0] if items else ""
    return "%s and %s" % (", ".join(items[:-1]), items[-1])

_data = None


def _load():
    global _data
    if _data is not None:
        return _data

    def j(name):
        with open(os.path.join(PUBLIC, name), encoding="utf-8") as f:
            return json.load(f)

    slugs = j("slugs.json")            # slug -> iso
    try:
        og = j("og-images.json")       # iso -> hero photo URL (optional)
    except OSError:
        og = {}
    _data = {
        "slugs": slugs,
        "iso2slug": {iso: s for s, iso in slugs.items()},
        "names": j("country-names.json"),  # iso -> name
        "acts": j("activities.json"),
        "clim": j("climate.json"),
        "visa": j("visa.json"),
        "og": og,
    }
    return _data


def iso_for_slug(slug):
    """ISO-2 for a URL slug, or None if it isn't a known country."""
    return _load()["slugs"].get(slug)


def _label(x):
    """An activity is either a plain string or {'t': label, 'd': insight}."""
    return x.get("t") if isinstance(x, dict) else x


def _insight(x):
    return x.get("d") if isinstance(x, dict) else ""


def _clip(text, n=157):
    text = " ".join(text.split())
    return text if len(text) <= n else text[:n].rsplit(" ", 1)[0] + "…"


# EKTA travel insurance, via Travelpayouts. A plain link on purpose: their only
# alternative is an embedded widget, and a third-party script is a failure mode
# this site does not need (a blocked one silently cost us every analytics number
# we had). marker=738472 is the affiliate id and is public by design — it ships
# in the URL either way.
#
# sub_id is the only part that varies. EKTA has no per-country pages — every
# destination is chosen inside one quote form on their homepage, and guessed
# paths like /colombia 404 — so all 176 links land in the same place. Tagging
# each with its slug costs nothing and is the only way to learn which guide
# pages actually convert. It does NOT make the destination country-specific,
# which is why the link text below says "travel insurance" and not "Colombia
# travel insurance": the reader picks their own destination once they arrive,
# and promising otherwise would be a lie for a few extra clicks.
_EKTA = ("https://tp.media/r?campaign_id=225&marker=738472&p=5869"
         "&sub_id=guide-%s&trs=541205&u=https%%3A%%2F%%2Fektatraveling.com")


def _seasons(scores):
    """peak / shoulder / off per month. Mirrors seasons() in app.js — same
    min-max normalisation, same 0.66 / 0.34 cuts — so the prose below can never
    disagree with the bars the reader sees next to it."""
    valid = [s for s in scores if s is not None]
    if not valid:
        return ["na"] * len(scores)
    mn, mx = min(valid), max(valid)
    rng = (mx - mn) or 1
    out = []
    for s in scores:
        if s is None:
            out.append("na")
            continue
        f = (s - mn) / float(rng)
        out.append("peak" if f >= 0.66 else "off" if f <= 0.34 else "shoulder")
    return out


def _month_by_month(name, clim, acts):
    """A month-by-month section, generated from data the site already holds.

    The reason this exists: the server-rendered body was ~173 words per country,
    wrapped in an app shell identical across all 176 pages. Google reads that as
    a near-duplicate template and files it under "Discovered - currently not
    indexed" — found, judged not worth an index slot. 121 pages sat there. No
    quantity of backlinks fixes a 173-word page.

    Every figure here is real: monthly temperatures and comfort scores from
    climate.json, month-tagged hazards from activities.json. Nothing is padded
    or invented — a table of plausible-sounding filler would be worse than the
    thin page it replaced.
    """
    temps = (clim.get("temps") or [])
    scores = (clim.get("scores") or [])
    if len(scores) != 12:
        return ""
    seas = _seasons(scores)
    best = set(clim.get("best") or [])

    hz = {}
    for h in (acts.get("hazards") or []):
        for m in (h.get("months") or []):
            if h.get("note"):
                hz.setdefault(m, h["note"])

    peak = [i + 1 for i, s in enumerate(seas) if s == "peak"]
    off = [i + 1 for i, s in enumerate(seas) if s == "off"]

    # Its own element because renderGuide() deletes the rest of the server block
    # on hydration — everything else in there (the h1, best-time, things to do,
    # visa) is duplicated by client UI, but this table is not. It gets moved into
    # the live guide instead of dropped, so a reader sees it and a JS-rendering
    # crawler still finds it after hydration.
    p = ['<section id="ssrMonths" class="ssrmonths">']
    p.append("<h2>%s month by month</h2>" % html.escape(name))
    lead = []
    if peak:
        lead.append("The most comfortable stretch is %s"
                    % _join_and([MON_FULL[m - 1] for m in peak]))
    if off:
        lead.append("the least comfortable is %s"
                    % _join_and([MON_FULL[m - 1] for m in off]))
    if lead:
        p.append("<p>%s, judged on temperature and general weather comfort. "
                 "Off-peak months are usually cheaper and quieter, which can be "
                 "the better trade depending on what you want.</p>"
                 % html.escape("; ".join(lead)))

    rows = []
    for i in range(12):
        t = temps[i] if i < len(temps) else None
        label = {"peak": "Peak", "shoulder": "Shoulder", "off": "Off-peak"}.get(seas[i], "—")
        note = hz.get(i + 1, "")
        if (i + 1) in best and not note:
            note = "One of the best months to visit"
        rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>" % (
                html.escape(MON_FULL[i]),
                # Both units: the client has a °C/°F toggle, but this copy is
                # static, and the search traffic is a mix of metric and not.
                ("%d&deg;C (%d&deg;F)" % (round(t), round(t * 9.0 / 5 + 32)))
                if t is not None else "&mdash;",
                html.escape(label),
                html.escape(note) or "&mdash;"))
    p.append('<table class="mbm"><thead><tr><th>Month</th><th>Avg temp</th>'
             "<th>Season</th><th>Notes</th></tr></thead><tbody>%s</tbody></table>"
             % "".join(rows))

    rainy = [h for h in (acts.get("hazards") or []) if h.get("note")]
    if rainy:
        bits = ["<strong>%s:</strong> %s" % (
            html.escape(_join_and([MON_FULL[m - 1] for m in (h.get("months") or []) if 1 <= m <= 12])),
            html.escape(h["note"])) for h in rainy if h.get("months")]
        if bits:
            p.append("<p>Worth planning around &mdash; %s.</p>" % "; ".join(bits))
    p.append("</section>")
    return "".join(p)


def _insurance_link(slug):
    return ('<p class="afflink"><a href="%s" rel="sponsored nofollow noopener" '
            'target="_blank">Compare travel insurance</a> '
            '<span class="affnote">Affiliate link — we may earn a commission, '
            "at no extra cost to you.</span></p>" % html.escape(_EKTA % slug, quote=True))


def _faq_jsonld(name, best_txt, acts, seasonal, summary):
    """FAQPage schema for the questions people actually search — 'best time to
    visit X', 'things to do in X', 'what's in season' — so the page can win
    Google rich results. Data-backed answers only (no invented facts)."""
    qas = []
    if best_txt:
        a = "The best months to visit %s are %s, based on weather and seasonality." % (name, best_txt)
        if summary:
            a += " " + summary
        qas.append(("When is the best time to visit %s?" % name, a))
    top = [_label(x) for x in acts[:4] if _label(x)]
    if top:
        qas.append(("What are the top things to do in %s?" % name,
                    "Top experiences in %s include %s." % (name, ", ".join(top))))
    if seasonal:
        s = seasonal[0]
        months = [MON[m - 1] for m in (s.get("months") or []) if 1 <= m <= 12]
        if s.get("what"):
            a = s["what"] + ((" (%s)" % ", ".join(months)) if months else "")
            if s.get("d"):
                a += " — " + s["d"]
            qas.append(("What's in season in %s?" % name, a))
    if not qas:
        return ""
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {"@type": "Question", "name": q,
             "acceptedAnswer": {"@type": "Answer", "text": a}}
            for q, a in qas
        ],
    }
    return '<script type="application/ld+json">%s</script>' % json.dumps(data, ensure_ascii=False)


def render(iso):
    """Return the token values for a country page: title, description, og title,
    canonical URL, and the crawlable body HTML."""
    d = _load()
    name = d["names"].get(iso, iso)
    slug = d["iso2slug"].get(iso, iso.lower())
    a = d["acts"].get(iso, {}) or {}
    c = d["clim"].get(iso, {}) or {}
    v = d["visa"].get(iso, {}) or {}

    best = c.get("best") or []
    best_txt = ", ".join(MON[m - 1] for m in best if 1 <= m <= 12)
    summary = (a.get("summary") or "").strip()
    acts = a.get("activities") or []
    seasonal = a.get("seasonal") or []

    # Meta description: prefer the curated summary; always lead with best months.
    desc = summary or ("What to do in %s, when to go, and what's in season — "
                       "graded on prices, weather, safety and flights." % name)
    if best_txt:
        desc = "Best time to visit %s: %s. %s" % (name, best_txt, desc)
    desc = _clip(desc)

    title = "%s Travel Guide — Best Time to Visit & What to Do | WanderGrade" % name
    og_title = "%s Travel Guide — WanderGrade" % name
    url = "%s/guide/%s" % (SITE, slug)

    p = ["<h1>%s Travel Guide</h1>" % html.escape(name)]
    if summary:
        p.append("<p>%s</p>" % html.escape(summary))
    if best_txt:
        # Every query landing here is "best time to visit <country>", and that
        # phrase used to appear only in the <title> — the body answered it under
        # the heading "What's in season", which is a different question, and in
        # abbreviated months nobody searches for. Heading and prose now say the
        # thing people actually typed.
        best_full = _join_and(MON_FULL[m - 1] for m in best if 1 <= m <= 12)
        p.append("<h2>Best time to visit %s</h2>" % html.escape(name))
        p.append("<p>The best months to visit %s are <strong>%s</strong>, "
                 "judged on weather and seasonality.</p>"
                 % (html.escape(name), html.escape(best_full)))
    mbm = _month_by_month(name, c, a)
    if mbm:
        p.append(mbm)
    if acts:
        p.append("<h2>Top things to do in %s</h2><ul>" % html.escape(name))
        for x in acts:
            t, ins = _label(x), _insight(x)
            li = "<li><strong>%s</strong>" % html.escape(t or "")
            if ins:
                li += " — %s" % html.escape(ins)
            p.append(li + "</li>")
        p.append("</ul>")
    if seasonal:
        p.append("<h2>What's in season in %s</h2><ul>" % html.escape(name))
        for s in seasonal:
            months = [MON[m - 1] for m in (s.get("months") or []) if 1 <= m <= 12]
            li = "<li><strong>%s</strong>" % html.escape(s.get("what", ""))
            if months:
                li += " (%s)" % ", ".join(months)
            if s.get("d"):
                li += " — %s" % html.escape(s["d"])
            p.append(li + "</li>")
        p.append("</ul>")
    if v.get("note") or v.get("status"):
        vtxt = " ".join(x for x in (v.get("status", ""), v.get("note", "")) if x)
        p.append("<p><strong>Visa (US passport):</strong> %s</p>" % html.escape(vtxt))
    p.append(_insurance_link(slug))

    return {
        "iso": iso,
        "title": title,
        "desc": desc,
        "og_title": og_title,
        "url": url,
        "body": "\n".join(p),
        "jsonld": _faq_jsonld(name, best_txt, acts, seasonal, summary),
        "ogimage": d["og"].get(iso, ""),
    }


def all_slugs():
    """Every (slug, iso) for the sitemap and any build tooling."""
    return sorted(_load()["slugs"].items())


def name_for_iso(iso):
    """Display name for an ISO2, or None. Used by the homepage's crawlable
    index of every guide page — anchor text needs the country's real name, not
    the slug, both for readers and because the words in a link are a ranking
    signal for the page it points at."""
    return (_load()["names"] or {}).get(iso)
