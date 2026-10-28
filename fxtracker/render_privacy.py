"""/privacy as a pure function: the page body, its <title>, description and
"last updated" date, in the shell the list pages use (server.py _shell_page).

Every sentence describes something the code (or the hosting set-up) does, and
says where:

  * Analytics: server.py _analytics_tag() — Cloudflare Web Analytics'
    beacon.min.js from static.cloudflareinsights.com, which reports to
    cloudflareinsights.com/cdn-cgi/rum; no cookie or storage of its own.
  * The reader's browser: app.js's localStorage keys (fx_*, wg_*), the
    session counter in sessionStorage, and public/sw.js's offline cache.
  * Country: server.py /api/geo reads Cloudflare's CF-IPCountry header
    (no-store, never kept); app.js seedGeoDefaults asks on every visit until
    fx_origin is set (US readers never get one saved) and saves the guess.
  * Accounts: fxtracker/accounts.py — Upstash Redis (user:<email> with
    visited, wishlist, newsletter choices, created/updated, no expiry;
    sess:<sid> 90 days rolling; magic:<token> 15 minutes; rl:e:/rl:i:
    counters 1 hour), Resend for the sign-in mail, and server.py's wg_sess
    cookie (the only Set-Cookie there is). Deletion is by email: the owner
    runs scripts/delete_account.py (accounts.delete_account: sessions,
    unused links, the record, the counter, the Buttondown subscriber).
  * Newsletter: app.js subscribeFormHTML posts from the reader's browser to
    Buttondown (which records the signup IP and its country, and has
    per-subscriber open/click fields); accounts.py _sync_newsletter mirrors an
    account's choice from the server; Buttondown sends through Postmark
    (newsletter.wandergrade.com). newsletter.py's issues carry Buttondown's
    unsubscribe link, flagcdn.com flags and picks.cover()'s photos, Wikimedia
    files resized by images.weserv.nl.
  * Partner links: app.js flightSearchURL (Aviasales, Travelpayouts marker;
    the path starts with the reader's departure hub), renderGuideStay
    (Stay22 Allez to Booking.com and Vrbo, aid=wandergrade, lat/lng, dates),
    viatorURL, insuranceHref and render_guide._EKTA (EKTA via tp.media);
    hostelworldURL is a plain link with no partner ID.
  * Third-party content: app.js's Wikipedia and Commons API calls (fetch, no
    credentials) and the photos they return (upload. and thumb.wikimedia.org,
    loaded as plain images, whose responses set Wikimedia's WMF-Uniq cookie,
    a year-long ID, where third-party cookies are allowed); fonts, map and
    music are the site's own files.
  * AI buttons: app.js AI_SITES / aiLink — the prompt in the link (?q=) or
    the clipboard; buildTripAIPrompt / buildCountryAIPrompt add the reader's
    been-to countries.
  * Sharing: app.js buildShareURL — v=/tp= only for Share; vo, hc, db, fo,
    pri, fac and the rest also ride in the address bar (history.replaceState).
  * Hosting: Render behind Cloudflare, whose responses carry NEL/Report-To
    (failed loads reported to a.nel.cloudflare.com); server.py
    Handler.log_message logs the request line (query string included, a
    sign-in token redacted) and status, no client address.
  * Mail to hello@: Cloudflare Email Routing forwards it to a Gmail inbox;
    replies go out through Resend (Gmail send-as). The sign-in mail and the
    newsletter both carry Reply-To hello@.

When any of those changes, change this page and UPDATED with it.
scripts/test_privacy.py checks that every third-party host the pages and the
newsletter load (computed from the code) is named here.
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
        "that pay for the site work. No ads, nothing sold.")

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
    """The contact link, inside Cloudflare's email_off markers: its Email
    Address Obfuscation otherwise swaps the address for "[email protected]" and a
    /cdn-cgi/l/email-protection link that 404s without JavaScript."""
    return '<!--email_off--><a href="mailto:%s">%s</a><!--/email_off-->' % (CONTACT, CONTACT)


def privacy():
    """{"title", "desc", "h1", "html", "updated"} for /privacy."""
    body = "".join([
        '<div class="listpage privacy"><h1>Privacy</h1>',
        '<p class="lede">No ads, nothing sold, and no cookie from WanderGrade unless you sign in. '
        "Most of what you set here stays in your own browser. Here is what leaves it, and where it "
        "goes.</p>",
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
             "<p>Until you've set a home country, Cloudflare, which every request passes through, tells "
             "the server which country you're connecting from, so the site can start you on your own "
             "country and currency. The server doesn't keep it; the site saves its guess in your "
             "browser, and you can change it.</p>"),

        _sec("account", "Account (optional)",
             "<p>“Save your travel map” signs you in with a one-time link, no password. Resend emails "
             "the link; it works once, within 15 minutes.</p>"
             "<ul>"
             "<li>Stored with Upstash, a database service, until you ask me to delete it: your email "
             "address, the countries on your Wander List, your newsletter choices, and when the account "
             "was created and last changed.</li>"
             "<li>One cookie, <code>wg_sess</code>, keeps you signed in for 90 days from your last visit. "
             "It's the only cookie WanderGrade sets, and only once you sign in.</li>"
             "<li>To stop abuse, sign-in requests are counted per email address and per IP address. "
             "The counters expire after an hour.</li>"
             "</ul>"
             "<p>Sign out from the account panel. To delete your account, email %s from its address: "
             "I'll delete the account, sign out every device and take the address off the newsletter "
             "list.</p>" % _mail()),

        _sec("newsletter", "Newsletter",
             "<p>Buttondown keeps the list and sends the monthly issue, through Postmark. It holds your "
             "email address, your currency if you pick one and, if you sign up with the form, the IP "
             "address you signed up from and its country. It can also record whether you open an issue "
             "and click its links. Every issue has an unsubscribe link. The signup form opens Buttondown "
             "in a new window.</p>"
             "<p>Issue photos come from Wikimedia Commons, resized by images.weserv.nl, and flags from "
             "flagcdn.com; your mail app loads them like any image.</p>"),

        _sec("partners", "Booking links",
             "<p>Some links pay for the site: flights on Aviasales (through Travelpayouts), stays on "
             "Booking.com and Vrbo (through Stay22), tours on Viator and travel insurance from EKTA "
             "(through Travelpayouts). Each carries WanderGrade's partner ID and the trip: where you're "
             "going, your dates and, for flights, the city you'd fly from. Nothing else about you. If "
             "you book, WanderGrade may earn a commission, at no extra cost to you. The grades don't "
             "depend on it.</p>"
             "<p>Nothing goes to these partners until you click. After that, the partner and the network "
             "in between set their own cookies to credit the booking, under their own privacy policies. "
             "Hostelworld links are plain links for now, with no partner ID.</p>"),

        _sec("content", "Photos and Wikipedia",
             "<p>Photos and their credits load straight from Wikipedia and Wikimedia Commons, so the "
             "Wikimedia Foundation sees your IP address, your browser and which places' photos you're "
             "viewing. Where your browser allows third-party cookies, Wikimedia's image servers also set "
             "their own, including a year-long ID (<code>WMF-Uniq</code>). Fonts, maps and music come "
             "from WanderGrade's own server.</p>",
             _hosts(WIKI_HOSTS)),

        _sec("ai", "AI buttons",
             "<p>“Open in ChatGPT”, and the Gemini, Claude, Grok and Perplexity buttons beside it, build a "
             "prompt from what's on your screen: the destination, your dates, home country, passport, "
             "budget and the countries you've marked as visited. Nothing is sent until you click. The "
             "button opens that service with the prompt in the link's address, so it lands in your "
             "browser history and that service's logs, or copies it for you to paste. From there that "
             "service's privacy policy applies.</p>"),

        _sec("sharing", "Sharing and feedback",
             "<p>A share link carries your list or trip, with your home country, currency and settings, "
             "inside the link itself, and only when you press Share. Your settings also show in the "
             "address bar, so they go with any address you copy. The feedback link opens a Google "
             "Form.</p>"),

        _sec("hosting", "Hosting",
             "<p>The site runs on Render, behind Cloudflare. Like any web host, they see your IP address, "
             "your browser and the page you asked for, and may keep short-lived logs under their own "
             "policies. Cloudflare also asks your browser to report pages that fail to load, to "
             "a.nel.cloudflare.com. WanderGrade's own server log records the address of each request, "
             "settings in the link included, but not your IP address.</p>"),

        _sec("never", "What I don't do",
             "<ul>"
             "<li>No ads, and no advertising cookies.</li>"
             "<li>I never sell your personal data or share it for marketing. Your email address goes only "
             "to the services named on this page, each for its own job.</li>"
             "</ul>"),

        _sec("rights", "Your rights",
             "<p>Wherever you live, you can ask for a copy of what's stored about you, a correction, or "
             "its deletion: email %s. In the EU and the UK, data protection law (the GDPR and the UK GDPR) "
             "gives you those rights, and you can also complain to your data protection authority.</p>"
             "<p>WanderGrade is run by one person. Most of the services named here are US companies, so "
             "your data may be handled in the United States. Unsubscribing stops the newsletter; "
             "Buttondown keeps the address, marked unsubscribed, until you ask me to delete it.</p>"
             % _mail()),

        _sec("contact", "Contact",
             "<p>Questions about any of this: %s. Mail to that address, replies to WanderGrade's emails "
             "included, is forwarded by Cloudflare to my Gmail inbox, and I answer from there. When this "
             "page changes, the date at the top changes with it.</p>" % _mail()),
        "</div>",
    ])
    return {"title": TITLE, "desc": DESC, "h1": "Privacy", "html": body, "updated": UPDATED}
