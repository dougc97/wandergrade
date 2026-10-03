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
# first (CNY has fares to ~10 countries; INR grades nearly everything F on
# affordability).
ROLLOUT = {"USD": "send"}

STAGES = ("send", "draft")

# USD is the fallback every other edition leans on; it can never be off.
assert ROLLOUT.get("USD") == "send", "digest_variants.ROLLOUT must keep USD at 'send'"
assert all(c in VARIANTS and s in STAGES for c, s in ROLLOUT.items()), \
    "digest_variants.ROLLOUT: unknown currency or stage"
assert sorted(SEND_ORDER) == sorted(VARIANTS) == sorted(PICKER_ORDER)
assert len(set(v.tag for v in VARIANTS.values())) == len(VARIANTS)
# The subject names only the noun and the month, and it is how a re-run finds
# what already went out: two editions with one noun would be mistaken for each other.
assert len(set(v.noun for v in VARIANTS.values())) == len(VARIANTS)
# accounts.py's opt-out reconcile reads the cadence- prefix; never collide.
assert not any(v.tag.startswith("cadence-") for v in VARIANTS.values())

TAG_PREFIX = "currency-"


def stage(code):
    """"send", "draft" or None (off) for a currency code."""
    return ROLLOUT.get(code)


def send_codes():
    """Currencies in the monthly send, in SEND_ORDER (USD last)."""
    return tuple(c for c in SEND_ORDER if ROLLOUT.get(c) == "send")


def draft_codes():
    """Currencies a --draft run builds ("send" + "draft"), in SEND_ORDER."""
    return tuple(c for c in SEND_ORDER if ROLLOUT.get(c) in STAGES)


def picker_codes():
    """Currencies readers can choose in the subscribe box, in PICKER_ORDER.
    Just ("USD",) means no picker: the form is exactly today's."""
    return tuple(c for c in PICKER_ORDER if ROLLOUT.get(c) == "send")


def by_tag(tag):
    """The currency code whose tag this is (case-insensitive), else None."""
    t = (tag or "").lower() if isinstance(tag, str) else ""
    for v in VARIANTS.values():
        if v.tag == t:
            return v.code
    return None
