"""/privacy as a pure function: the page body, its <title>, description and
"last updated" date, in the shell the list pages use (server.py _shell_page).

Every sentence describes something the code does, and says where:

  * Analytics: server.py _analytics_tag() — Cloudflare Web Analytics'
    beacon.min.js from static.cloudflareinsights.com, which reports to
    cloudflareinsights.com/cdn-cgi/rum; no cookie or storage of its own.
  * The reader's browser: app.js's localStorage keys (fx_*, wg_*), the
    session counter in sessionStorage, and public/sw.js's offline cache.
  * First-visit country: server.py /api/geo reads Cloudflare's CF-IPCountry
    header (no-store, never kept); app.js seedGeoDefaults.
  * Accounts: fxtracker/accounts.py — Upstash Redis (user:<email> with
    visited, wishlist, newsletter choice, created/updated; sess:<sid> 90 days
    rolling; magic:<token> 15 minutes; rl:e:/rl:i: counters 1 hour), Resend
    for the sign-in mail, and server.py's wg_sess cookie (the only Set-Cookie
    there is). There is no delete endpoint: deletion is by email.
  * Newsletter: app.js subscribeFormHTML posts to Buttondown; accounts.py
    _sync_newsletter mirrors an account's choice there; newsletter.py's
    issues carry Buttondown's unsubscribe link, flagcdn.com flags and
    Wikimedia photos.
  * Partner links: app.js flightSearchURL (Aviasales, Travelpayouts marker),
    renderGuideStay (Stay22 Allez to Booking.com and Vrbo, aid=wandergrade),
    viatorURL, insuranceHref and render_guide._EKTA (EKTA via tp.media);
    hostelworldURL is a plain link with no partner ID.
  * Third-party content: app.js's Wikipedia and Commons API calls and the
    photos they return (upload. and thumb.wikimedia.org); fonts, map and
    music are the site's own files.
  * AI buttons: app.js AI_SITES / aiLink — a link (or the clipboard) only.
  * Hosting: Render behind Cloudflare; server.py Handler.log_message logs
    the request line and status, no client address.

When any of those changes, change this page and UPDATED with it.
scripts/test_privacy.py checks that every third-party host the pages load
(computed from the code) is named here.
"""

import html

UPDATED = "2026-10-21"
CONTACT = "hello@wandergrade.com"

# Named on the page, host by host: the test computes the same list from the
# code and the served HTML and fails on any it can't find here.
ANALYTICS_HOSTS = ("static.cloudflareinsights.com", "cloudflareinsights.com")
WIKI_HOSTS = ("en.wikipedia.org", "commons.wikimedia.org", "upload.wikimedia.org", "thumb.wikimedia.org")

TITLE = "Privacy | WanderGrade"
DESC = ("What WanderGrade keeps (very little), where your data goes, and how the booking links "
        "that pay for the site work. No ads, no tracking cookies.")

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December")


def updated_text(day=UPDATED):
    """'21 October 2026': day-month-year, for a page read from anywhere."""
    y, m, d = day.split("-")
    return "%d %s %s" % (int(d), _MONTHS[int(m) - 1], y)


def _hosts(hosts):
    return '<p class="hosts">%s</p>' % " · ".join("<code>%s</code>" % html.escape(h) for h in hosts)


def _sec(sid, title, *parts):
    return '<section id="%s"><h2>%s</h2>%s</section>' % (sid, title, "".join(parts))


def _mail():
    return '<a href="mailto:%s">%s</a>' % (CONTACT, CONTACT)


def privacy():
    """{"title", "desc", "h1", "html", "updated"} for /privacy."""
    body = "".join([
        '<div class="listpage privacy"><h1>Privacy</h1>',
        '<p class="lede">No ads, no tracking cookies, nothing sold. Most of what you set here stays in '
        "your own browser. This is everything that leaves it, and where it goes.</p>",
        '<p class="asof">Last updated %s</p>' % updated_text(),

        _sec("device", "On your device",
             "<p>Your choices (home country, currency, travel month, budget, priorities, safety source, "
             "°C or °F, light or dark), your Wander List and your trip plan are saved in your browser's "
             "local storage, with a few small counters, like how many visits you've made and whether you "
             "closed the newsletter invite. The server stores none of it, except your Wander List if you "
             "sign in to save it. The site also keeps pages you've opened, for offline use. Clearing this "
             "site's data in your browser wipes it all.</p>"),

        _sec("analytics", "Analytics",
             "<p>Cloudflare Web Analytics counts page views and how fast pages load. It sets no cookies "
             "and stores nothing in your browser, and Cloudflare says it doesn't fingerprint you or follow "
             "you across sites. No Google Analytics, no ad pixels.</p>",
             _hosts(ANALYTICS_HOSTS)),

        _sec("country", "Your country",
             "<p>On a first visit, Cloudflare, which every request passes through, tells the server which "
             "country you're connecting from, so the site can start you on your own country and currency. "
             "The server doesn't keep it; what you pick is saved in your browser.</p>"),

        _sec("account", "Account (optional)",
             "<p>“Save your travel map” signs you in with a one-time link, no password. Resend emails "
             "the link; it works once, within 15 minutes.</p>"
             "<ul>"
             "<li>Stored with Upstash, a database service: your email address, the countries on your "
             "Wander List, your newsletter choice, and when the account was created and last changed.</li>"
             "<li>One cookie, <code>wg_sess</code>, keeps you signed in for 90 days from your last visit. "
             "It's the only cookie WanderGrade sets, and only once you sign in.</li>"
             "<li>To stop abuse, sign-in requests are counted per email address and per IP address. "
             "The counters expire after an hour.</li>"
             "</ul>"
             "<p>Sign out from the account panel. To delete your account, email %s from its address "
             "and I'll remove it.</p>" % _mail()),

        _sec("newsletter", "Newsletter",
             "<p>Buttondown keeps the list and sends the monthly issue: your email address and, if you "
             "pick one, your currency. Every issue has an unsubscribe link. The signup form opens "
             "Buttondown in a new window. Issues show photos from Wikimedia Commons and flags from "
             "flagcdn.com, which your mail app loads like any image.</p>"),

        _sec("partners", "Booking links",
             "<p>Some links pay for the site: flights on Aviasales (through Travelpayouts), stays on "
             "Booking.com and Vrbo (through Stay22), tours on Viator and travel insurance from EKTA "
             "(through Travelpayouts). Each carries WanderGrade's partner ID and where and when you're "
             "going, nothing about you. If you book, WanderGrade may earn a commission, at no extra cost "
             "to you. The grades don't depend on it.</p>"
             "<p>Nothing goes to these partners until you click. After that, the partner and the network "
             "in between set their own cookies to credit the booking, under their own privacy policies. "
             "Hostelworld links are plain links for now, with no partner ID.</p>"),

        _sec("content", "Photos and Wikipedia",
             "<p>Guide photos and their credits load straight from Wikipedia and Wikimedia Commons, so the "
             "Wikimedia Foundation sees your IP address and browser, as it would for any image you load "
             "from it. Fonts, maps and music come from WanderGrade's own server.</p>",
             _hosts(WIKI_HOSTS)),

        _sec("ai", "AI buttons",
             "<p>“Open in ChatGPT”, and the Gemini, Claude, Grok and Perplexity buttons beside it, build a "
             "prompt from what's on your screen: the destination, your dates, home country, passport and "
             "budget. Nothing is sent until you click. The button opens that service with the prompt filled "
             "in, or copies it for you to paste, and from there that service's privacy policy applies.</p>"),

        _sec("sharing", "Sharing and feedback",
             "<p>A share link carries your list or trip inside the link itself, and only when you press "
             "Share. The feedback link opens a Google Form.</p>"),

        _sec("hosting", "Hosting",
             "<p>The site runs on Render, behind Cloudflare. Like any web host, they see your IP address, "
             "your browser and the page you asked for, and may keep short-lived logs under their own "
             "policies. WanderGrade's own server log records which page or data was asked for, not your "
             "IP address.</p>"),

        _sec("never", "What I don't do",
             "<ul>"
             "<li>No ads, and no advertising or cross-site tracking cookies.</li>"
             "<li>I never sell your personal data or share it for marketing. Your email address goes only "
             "to the services above that do the job: Resend, Upstash and Buttondown.</li>"
             "</ul>"),

        _sec("rights", "Your rights",
             "<p>Wherever you live, you can ask for a copy of what's stored about you, a correction, or "
             "its deletion: email %s. In the EU and the UK, data protection law (the GDPR and the UK GDPR) "
             "gives you those rights, and you can also complain to your data protection authority.</p>"
             % _mail()),

        _sec("contact", "Contact",
             "<p>Questions about any of this: %s. When this page changes, the date at the top changes "
             "with it.</p>" % _mail()),
        "</div>",
    ])
    return {"title": TITLE, "desc": DESC, "h1": "Privacy", "html": body, "updated": UPDATED}
