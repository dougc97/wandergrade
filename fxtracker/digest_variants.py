"""The monthly digest's home-currency editions, and which of them are live.

One edition per home currency ("variant"): it is scored for a traveller from
that currency's country (fares from there, prices compared with there, the
currency's strength measured in it) and worded for them ("your euro",
"below German levels"). Readers choose one in the subscribe box or their
account panel; Buttondown holds the choice as a tag (`tag` below). Readers
with no currency tag get the USD edition, which is byte-for-byte the digest
as it was before editions existed.

ROLLOUT is the on/off switch, and it is a committed constant on purpose: the
monthly GitHub workflow passes only BUTTONDOWN_API_KEY to send_digest.py, so
an environment variable or repo setting would never reach it without editing
the workflow. Turning a currency on is therefore a reviewed commit, and that
same commit shows it in the site's subscribe picker (server.py reads
picker_codes()). Stages:

  "send"   in the subscribe picker and in the monthly send
  "draft"  only in `send_digest.py --draft` / `--dry-run` runs, so the owner
           can check the audience in Buttondown before readers can pick it
  absent   off

Stdlib only and no imports from fxtracker, so server.py, the tests and the
send script can all read it without pulling in the scorer.

A typo in ROLLOUT must never take the site down: server.py and accounts.py
import this module, so only the fixed VARIANTS facts below are asserted. A
bad ROLLOUT entry ({"EUR": "Send"}, {"XYZ": "send"}) is ignored by stage() and
the *_codes() lists, which always keep USD at "send"; rollout_problems()
names it, send_digest.py refuses to run (exit 2) until it is fixed, and
scripts/test_digest_variants.py fails.

RUNBOOK (the owner's steps; send_digest.py's docstring has the commands)
  1. Buttondown -> Billing: tags and segmentation must be in the plan.
     Without them stay USD-only. Don't pre-create the currency-* tags, don't
     make them subscriber-editable, leave the API version pin alone.
  2. Trial a currency: commit ROLLOUT = {"USD": "send", "EUR": "draft"}.
     Subscribe an address you control at
     https://buttondown.com/wandergrade?tag=currency-eur and confirm it.
  3. Actions -> Monthly travel digest -> Run workflow -> draft. The log must
     show "EUR: draft ... (1 readers)": that line is the proof Buttondown
     counts readers by tag name; "skipped — no readers" with a WARNING means
     it doesn't, and the edition would silently go to nobody. In Buttondown
     the EUR draft shows 1 recipient and the USD draft excludes that address.
     Delete both drafts.
  4. Commit EUR -> "send" (the picker appears within ~5 minutes, the
     Cloudflare HTML cache). Remove the test subscriber.
  - Change ROLLOUT only between monthly sends, never between the 1st and a
    re-run of that month's send: a re-run with fewer editions (USD-only
    especially) doesn't look for editions already out and re-sends USD to
    their readers; with more, the new edition's readers already had USD.
  - Readers with two currency tags (re-subscribing through the public form
    ADDS a tag; Buttondown never swaps it) get the first edition in
    SEND_ORDER, which may not be their latest pick. When one writes in to
    switch, or before a send: Buttondown -> Subscribers, filter by each
    currency-* tag, and on anyone holding two remove the one they no longer
    want. Signed-in readers can switch in their account panel, which
    replaces the tag.
  - EUR is graded for Germany (Frankfurt fares, German price levels) for
    every euro reader, French or Finnish alike; its footer says so ("a
    traveler from Germany (paying in euros)"). A per-country euro edition
    would need its own tag and noun.
  - A draft whose audience filter Buttondown dropped or changed is renamed
    "[DO NOT SEND — audience dropped] ..." (deleted if the rename fails):
    sending it would mail the whole list. Delete it once you've looked.
"""

import collections

Variant = collections.namedtuple(
    "Variant",
    "code home_iso adv_source tag noun noun_cap fx_emoji levels_adj vs_place traveler exclude_home")

# home_iso is what fares are fetched for (/api/flights?origin=); the server
# maps it to a hub: US NYC, DE FRA, GB LON, CA YTO, AU SYD, JP TYO, CN BJS,
# IN DEL, KR SEL, CH ZRH. adv_source "us" for all ten matches the site's
# default advisory source. fx_emoji is the matching banknote where Unicode
# has one (dollar, euro, pound, yen), else the currency-exchange sign.
# exclude_home leaves the reader's own country out of their picks; USD keeps
# the US in, because its issue must stay exactly what it was.
VARIANTS = collections.OrderedDict((v.code, v) for v in (
    Variant("USD", "US", "us", "currency-usd", "dollar", "Dollar", "\U0001f4b5",
            "US", "the US", "a US traveler", False),
    Variant("EUR", "DE", "us", "currency-eur", "euro", "Euro", "\U0001f4b6",
            "German", "Germany", "a traveler from Germany (paying in euros)", True),
    Variant("GBP", "GB", "us", "currency-gbp", "pound", "Pound", "\U0001f4b7",
            "UK", "the UK", "a traveler from the UK", True),
    Variant("CAD", "CA", "us", "currency-cad", "Canadian dollar", "Canadian dollar", "\U0001f4b5",
            "Canadian", "Canada", "a traveler from Canada", True),
    Variant("AUD", "AU", "us", "currency-aud", "Australian dollar", "Australian dollar", "\U0001f4b5",
            "Australian", "Australia", "a traveler from Australia", True),
    Variant("JPY", "JP", "us", "currency-jpy", "yen", "Yen", "\U0001f4b4",
            "Japanese", "Japan", "a traveler from Japan", True),
    Variant("CNY", "CN", "us", "currency-cny", "yuan", "Yuan", "\U0001f4b1",
            "Chinese", "China", "a traveler from China", True),
    Variant("INR", "IN", "us", "currency-inr", "rupee", "Rupee", "\U0001f4b1",
            "Indian", "India", "a traveler from India", True),
    Variant("KRW", "KR", "us", "currency-krw", "won", "Won", "\U0001f4b1",
            "South Korean", "South Korea", "a traveler from South Korea", True),
    Variant("CHF", "CH", "us", "currency-chf", "franc", "Franc", "\U0001f4b1",
            "Swiss", "Switzerland", "a traveler from Switzerland", True),
))

# Send priority. USD goes LAST: it is everyone's fallback, sent to whoever
# holds none of the tags of a currency issue that already went out this
# cycle, so a currency that fails, is off, or has no readers falls back to it.
# A reader holding two currency tags gets the first issue in this order.
SEND_ORDER = ("EUR", "GBP", "CAD", "AUD", "JPY", "CNY", "INR", "KRW", "CHF", "USD")
# The subscribe picker's order (the owner's list).
PICKER_ORDER = ("USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CNY", "INR", "KRW", "CHF")

# The switch. CNY and INR should go through "draft" and a --dry-run review
# first: CNY has cached fares to only ~10 countries, so nearly every
# destination's Flights grade is the neutral estimate (no longer inflated: an
# estimated fare grades 70, see picks._score), and INR grades nearly
# everything F on affordability, so its picks are mostly C overall.
ROLLOUT = {"USD": "send"}

STAGES = ("send", "draft")

# Fixed facts about the editions (a code change, never an owner's switch):
# these may assert at import, because a test run catches them before deploy.
assert sorted(SEND_ORDER) == sorted(VARIANTS) == sorted(PICKER_ORDER)
assert SEND_ORDER[-1] == "USD"       # USD is everyone's fallback, so it goes last
assert len(set(v.tag for v in VARIANTS.values())) == len(VARIANTS)
# The subject names only the noun and the month, and it is how a re-run finds
# what already went out: two editions with one noun would be mistaken for each other.
assert len(set(v.noun for v in VARIANTS.values())) == len(VARIANTS)
# accounts.py's opt-out reconcile reads the cadence- prefix; never collide.
assert not any(v.tag.startswith("cadence-") for v in VARIANTS.values())


def rollout_problems(rollout=None):
    """What's wrong with ROLLOUT, as sentences ([] when it's fine). Nothing
    here raises: server.py and accounts.py import this module, and a typo in
    the owner's switch must not stop the site. send_digest.py exits 2 on any
    problem and the tests assert there are none."""
    r = ROLLOUT if rollout is None else rollout
    out = []
    if not isinstance(r, dict):
        return ["digest_variants.ROLLOUT must be a dict like {\"USD\": \"send\"}, not %r" % (r,)]
    for c, s in r.items():
        if c not in VARIANTS:
            hint = (" (codes are upper case: %r)" % c.upper()) if isinstance(c, str) \
                and c.upper() in VARIANTS else ""
            out.append("digest_variants.ROLLOUT: unknown currency %r%s; it is ignored" % (c, hint))
        elif s not in STAGES:
            out.append("digest_variants.ROLLOUT[%r] = %r: the stage must be \"send\" or \"draft\"; "
                       "%s is treated as off" % (c, s, c))
    if r.get("USD") != "send":
        out.append("digest_variants.ROLLOUT must keep USD at \"send\" (everyone's fallback); "
                   "it is treated as \"send\" regardless")
    return out


def _rollout():
    """ROLLOUT with every invalid entry dropped and USD forced to "send"."""
    r = ROLLOUT if isinstance(ROLLOUT, dict) else {}
    ok = {c: s for c, s in r.items() if c in VARIANTS and s in STAGES}
    ok["USD"] = "send"
    return ok


TAG_PREFIX = "currency-"


def stage(code):
    """"send", "draft" or None (off) for a currency code. USD is always
    "send"; an invalid ROLLOUT entry reads as off."""
    return _rollout().get(code)


def send_codes():
    """Currencies in the monthly send, in SEND_ORDER (USD last, always)."""
    r = _rollout()
    return tuple(c for c in SEND_ORDER if r.get(c) == "send")


def draft_codes():
    """Currencies a --draft run builds ("send" + "draft"), in SEND_ORDER."""
    r = _rollout()
    return tuple(c for c in SEND_ORDER if r.get(c) in STAGES)


def picker_codes():
    """Currencies readers can choose in the subscribe box, in PICKER_ORDER.
    Just ("USD",) means no picker: the form is exactly today's."""
    r = _rollout()
    return tuple(c for c in PICKER_ORDER if r.get(c) == "send")


def by_tag(tag):
    """The currency code whose tag this is (case-insensitive), else None."""
    t = (tag or "").lower() if isinstance(tag, str) else ""
    for v in VARIANTS.values():
        if v.tag == t:
            return v.code
    return None
