# Globes on the postcard, the guide's Where to stay, and the Trip route — design

Status: draft for Doug's approval (2026-11-27). To be committed on the feature branch as
`docs/superpowers/specs/2026-11-27-globes-design.md` (main stays gated).

## Intent

Doug wants small 3D world globes woven through WanderGrade, not only one big map: they make
the site feel distinct and help a reader place a country at a glance. He saw throwaway drafts
(artifact "Globe Drafts", https://claude.ai/artifact/Kh2Maznj9VWj4uG2EuZdEn, and three
side-by-side comparisons) and picked:

- **1A** — a small globe badge on the Top Picks postcard's photo.
- **2A** — a globe inside the travel guide's **Where to stay** section.
- **3** — the **Trip** tab shows the trip as a route on a globe (lines between countries), in a
  **recommended order with the lowest cost and shortest travel time**; readers can **drag to
  reorder** countries and can **choose the priority: value/cost or least travel time**.
- Leg data (Doug, 2026-11-27): **"Real where possible"** — use real fares and flight times
  wherever a trip country has its own airport in our fare data; estimate the rest from distance
  and mark those legs **≈**. No new paid service.

## Goals

1. A reader sees where a Top Picks country is without leaving the postcard (1A).
2. A reader planning a stay sees the country and its stay spots on a globe (2A).
3. A reader with 2+ trip countries gets a sensible order without thinking, sees why (fare and
   flight time per leg), can flip the priority, and can override it by dragging (3).
4. All of it costs no extra download on first paint and no layout shift.

## Non-goals

- No booking, pricing or affiliate changes; no new affiliate links.
- No changes to the newsletter. The Dec 1 USD email must stay byte-identical (gate rule).
- No changes to `drawMap`, `startGlobe` or `drawGlobe` (Doug's own). Reading/reusing other
  helpers is fine.
- No ground transport, border or visa logic in the route (flights only).
- No per-country day planning or dated itinerary (the trip keeps one month + total days).
- No account sync of the trip (it stays in localStorage `fx_trip`, as today).

## Anti-goals (a failure even if it "works")

- Any layout shift worse than main (CLS rule: never worse than base, measured cold).
- A route presented as "cheapest" built on guesses without saying so — estimated legs must
  carry **≈** and the ⓘ must say where numbers come from.
- Spending Travelpayouts quota freely or slowing the server under crawler bursts.
- Third-party scripts or fonts (the site's CSP is `script-src 'self' 'unsafe-inline'
  https://static.cloudflareinsights.com`; render_guide.py and the privacy page promise the
  map is the site's own file; test_privacy.py enforces third-party hosts are named).
- Wordy UI. Doug's direction: minimal on-page text, explanations in ⓘ hovers.

## Constraints (facts from the code, 186e43e)

- **Map data:** `public/world.geojson` (186 KB raw / 57 KB gzip, 227 features keyed by
  `properties.iso`, Natural Earth 110m + ~20 microstates from 50m) is already fetched on every
  landing (`ensureWorld`, app.js:1213; landing call ~15431). Top Picks waits for it. No
  England/Scotland/Wales polygons (guides map to GB via `GUIDE_PARENT`, app.js:2128). Two
  features have iso `-99`.
- **Helpers to reuse (read-only use):** `ensureWorld`/`worldGeo`, `countryCentroids` (6950),
  `placeSpans` (7020), `distKm` (7037), `buildFareContext` (7053, fare = a + b·km fit),
  `reducedMotion` (8846), `hexToRgb`/`mix`, `flagEmoji`, `countryName`, `GUIDE_PARENT`.
  `sphereCache`/`drawGlobe`/`proj` have the right maths but a fixed tilt, a single cache slot
  and longitude-only rotation: copy the ideas into new code, don't modify them.
- **Spin globe's land data** (`WORLD_LAND_ENC`) is unusable for badges (58 of 226 centroids fall
  in the sea) — use world.geojson.
- **Trip today:** `fx_trip` is an insertion-ordered Set saved as an array (app.js:7456-7475);
  `fx_tripdays`, `fx_tripmonth`; Trip tab renders `renderTripBar` (7531) + `renderTripBook`
  (7634); no map, no reorder, no totals. Share link `?tab=trip&tp=TH,VN,KH&td=14&tm=10`
  keeps array order. A design comment (app.js:7446-7455) says grouping was left to the AI on
  purpose; this feature reverses that — update the comment.
- **Fares:** only from the reader's hub. `flights.ORIGIN_HUBS` has 59 countries (one city code
  each). `/api/flights?origin=XX` → per destination `avg, min, n, dur (one-way minutes, most
  direct cached trip), stops, dest, dur_city, cities` (round-trip prices, USD; `months`
  stripped). `/api/flight-months?origin=&iso=` → monthly prices (no duration). Server
  `_fares(iso)` (server.py:2646) returns a hub's payload from cache (1 h TTL, stale 24 h);
  an uncached hub costs 1-3 `get_latest_prices` calls. Nothing exists between two non-hub
  countries.
- **Layout-shift system:** guide blocks have server stand-ins (`fxtracker/guide_sizers.py`,
  `holdSizer`) and per-width `:empty` min-heights; the Trip bar has an inline first-paint
  stand-in (index.html ~597-612). New boxes must be fixed-size from first paint.
- **Class names** must not start with ad/adv/sponsor/banner/promo (tests enforce).
- **Round 15** (guide top half as two free columns from 900px; branch `r15/guide-columns`,
  build stopped at a usage limit after 2 commits, not yet reviewed) puts Where to stay at the
  top of the right column. On today's layout a taller Where to stay would stretch its row and
  leave a blank band beside a short safety box. **2A lands after round 15 ships.** Round 15 now
  also moves "Top things to do" + the trip/AI buttons up under the photos
  (2026-11-27-guide-things-to-do-first-design.md), so Where to stay is the first block of the
  right column from 900px.

## Approaches considered

**Rendering**
- *A. Own small globe code on world.geojson (chosen, my call).* Per-pixel orthographic
  projection over a country-id mask, like the spin globe's technique but centred on any
  latitude/longitude, any size, highlighted countries. 0 KB extra download; ≈6-10 KB source
  (≈2-4 KB gzipped in app.min.js); 0.5-2 MB of mask memory, built once on first use.
- *B. The drafts' d3-geo + topojson, self-hosted.* +≈20 KB gzipped, a second script file the
  build/versioning has no path for, CSP/privacy-page edits, and coarser/missing small
  countries with world-atlas data. Rejected.

**Trip leg data** (Doug picked the first)
- *Real where possible (chosen).* Real `avg` fare and one-way `dur` from a hub trip country's
  own payload; estimate the rest from distance. Toggle is meaningful wherever real legs exist
  (much of SE Asia and Western Europe).
- *Estimates only.* Free, but cost and time both scale with km, so Cheapest and Quickest give
  the same order except for the home entry/exit legs. Rejected by Doug.
- *Real prices for every pair.* n(n-1) one-way lookups per trip with a daily cap; biggest
  build; times still partly estimated. Not now.

## Design

### Shared globe module (app.js, new code)

- Built on `worldGeo`. Rasterise a **country-id mask** once (each feature's index in a byte;
  1024×512 for small globes, 2048×1024 only if the Trip globe needs it). Borders by comparing
  neighbouring mask pixels.
- **Projection:** inverse orthographic per pixel, centred on (lon, lat), cached by
  (size, DPR, centre). DPR capped at 2. Lambert shading and limb darkening in the spin globe's
  look (land rgb(96,212,138), ocean rgb(38,122,202), light from the upper left, halo, rim) so
  all globes on the site look like one family. Highlighted country in the site green with a
  white outline; others plain land.
- **Small places:** where `placeSpans` < 1.5°, draw a dot/ring at `countryCentroids()` (the
  flat maps' rule) so microstates and islands are visible.
- **Sub-national guides** (England, Scotland, Wales) highlight GB via `GUIDE_PARENT`; `-99`
  features are never highlighted.
- **Arcs:** great-circle slerp, projected with the same maths, back-facing segments hidden.
- **Lifecycle:** ResizeObserver with redraw on the next frame; stop when disconnected; pause
  any animation when the tab is hidden; nothing moves under `reducedMotion()`.
- **Theme:** the globe itself looks the same in light and dark (as the spin globe); its
  surroundings use the site's tokens (`html[data-theme]` + `prefers-color-scheme`).
- Accessibility: decorative globes are `aria-hidden`; the Trip globe has a text equivalent
  (the leg list).

### 1A — Postcard badge

- **Where:** Top Picks and Hidden gems **row postcards only** (gate on `!o.secondary` in
  `postcardHTML`, app.js:1861). Not on map cards (they already show a map; their photo boxes
  are 88/64 px tall). *(My call.)*
- **Look:** 72×72, bottom-left of `.pcphoto`, 6px in, drop shadow, whole Earth centred on the
  country, country highlighted; ring for tiny countries. **Static, no spin** *(my call: calm,
  cheap, no reduced-motion question)*.
- **Clashes:** the credit ⓘ (bottom-right) stays above it (z-index); the ✕ on phones is
  top-right, clear of it. Above 600px the photo box is 168×112 and the centred 46px flag would
  sit under the badge, so the flag centres in the remaining space (e.g. `padding-left: 78px`
  on the box when the badge is present); the image (absolute, inset 0) is unaffected. On the
  ≤600px strip no change is needed.
- **Redraws:** render once per (iso, DPR) into a cached canvas/bitmap and copy it in, so
  `pcRender` rebuilding the box costs nothing.
- **No layout shift:** absolute inside a fixed box. If `worldGeo` isn't ready (it is, Top Picks
  waits for it), the badge simply appears when it is.

### 2A — Globe in Where to stay (after round 15)

- **Where:** inside `#guideStay`, between the "🏨 Where to stay" title and the stay chips.
- **Size (fixed heights so the server can hold them):** 390 → full column width × 240;
  561-899 → centred, capped at 480 wide × 300; ≥900 (r15 right column, 415-565 wide) → column
  width × 300. 10px gap below. *(Builder may tune heights once rendered; they must stay fixed
  per width range.)*
- **Content:** the country and its neighbours, centred on the country; **stay spots as pins**
  from `stay-coords.json` (already loaded by `renderGuideStay`; note `ll` is [lat, lon]); the
  **chosen spot highlighted** (the one the Booking/Hostelworld buttons name). No extra text
  line. **Static, no drag** *(my call: no accidental scroll capture on phones; zoom chosen so
  world.geojson's coarse coastlines still look clean — no per-country outline files now)*.
- **Chip tap:** `renderGuideStay(iso, true)` re-renders the block; carry the globe canvas
  across (as the postcard keeps its photo) and only move the highlight.
- **No layout shift:** add the same box to the server stand-in (`guide_sizers.stay`), add the
  globe height + gap to every `#guideStay:empty` min-height, and draw a placeholder disc in the
  reserved box until `worldGeo` lands (guide landings don't wait for it). Hidden wherever the
  stays are hidden (Level 4, no bookings, `data-nostay`). Update test_stay_place,
  test_hostelworld_link, test_stay_skip, test_guide_grid_order accordingly.

### 3 — Trip route globe with a recommended order

**Route model**
- Round trip: **home → trip countries → home**. Home = the same origin the Trip rows' fare
  strips use today (the reader's From).
- A **leg matrix** for home + the n trip countries, directed (A→B may differ from B→A). For
  each leg: `fare` (USD, one-way estimate), `minutes` (one-way flight time), `real` (true/false).
  - **One kind of fare everywhere** *(my call, after the builder check)*: the cheapest cached
    round-trip fare for the **trip month** where known (the same figure the Trip row shows,
    e.g. "Oct USD 608"), else the yearly `avg`; halved for one way. Same rule for home legs and
    legs between trip countries. With "I'm flexible" (no month), `avg` throughout.
  - Real legs: when the "from" end is a hub country, its payload row for the "to" country
    (trip-month fare from the payload's `months` — the server has them; only the public API strips
    them — else `avg`), `minutes = dur`. If the from end has no hub but the to end does, use the
    reverse row. Home→country and country→home legs come from the reader's own payload (the
    reader's From is always a hub, so these are always real when the route is cached).
  - Estimated legs: distance between `countryCentroids()` via `distKm`; fare from a **regional
    fit** the server returns *(my call: the reader-hub `buildFareContext` fit is a long-haul
    baseline — ≈ USD 150 one way for Bangkok→Phnom Penh, about twice a real regional fare — which
    would make real legs always look cheaper than estimated ones)*: fare = a + b·km fitted over the
    cached hub-payload rows up to 5,000 km (falling back to `buildFareContext` when fewer than 30
    rows), halved; minutes = km / 800 × 60 + 120. Marked ≈.
- **New endpoint** `GET /api/trip-legs?origin=XX&isos=TH,VN,KH&month=YYYY-MM`: for each listed
  iso that is in `ORIGIN_HUBS`, read its payload via the existing `_fares` path and return only
  the rows for the other listed isos: `{legs: {iso: {to: {fare, basis: "month"|"avg", dur,
  stops}}}, fit: {a, b, n}, pending: [isos]}`. Caps: at most 12 isos; at most 4
  **uncached** hub fetches per request (the rest come back `pending`, estimated now, real on a
  later visit); obey the existing busy gate (`_flight_shadow_busy()` or the slot rules) — when
  busy, answer from cache only. No new upstream endpoint, no new key, `Cache-Control: no-store`
  or short, not indexed. *(Builder picks the exact gate per server.py's refresh/slot notes.)*

**Ordering**
- Three modes, a small switch over the list: **Best overall** (default), **Cheapest**,
  **Quickest**, plus **Your order** once the reader drags.
  - Cheapest = minimise total fare. Quickest = minimise total minutes.
  - Best overall = minimise `fare / bestFare + minutes / bestMinutes` (each total divided by its
    own best possible total; equal weight). *(My call.)*
- Search: exact (Held-Karp or brute force) for n ≤ 10; nearest-neighbour + 2-opt above.
  Recompute when legs arrive or the trip changes; never reorder under a reader's finger.
- **Drag to reorder:** a handle on each Trip row (pointer events; keyboard: focus the handle,
  Up/Down to move). Dropping sets mode to **Your order** and saves the new order into `fx_trip`
  (array order). A "↺ Recommended" link returns to the last chosen recommended mode. Mode saved
  in localStorage (e.g. `fx_tripsort`).
- **Share links** carry the order **as shown** (`tp` in display order) and open as that order
  for the recipient. *(My call: the sender's plan is what they meant to share.)*

**Display (minimal text)**
- **Globe** above the Trip rows (beside them from ~900px): home marker, numbered stops, arcs in
  route order (dashed for ≈ legs). Drag to rotate (horizontal cheap path; latitude changes
  rebuild at the end of a drag); arcs draw in once when first shown, nothing animates under
  `reducedMotion()`; pause offscreen/hidden. Fixed-size box, part of the Trip bar's first-paint
  stand-in.
- **Leg lines** between rows: "✈️ USD 95 · 1h 40m" (≈ prefix on estimates), in the reader's
  fare currency like the fare strips. One totals line: "≈ USD 1,240 · 21h flying".
- ⓘ explains: where real legs come from, that estimates use distance, that fares are halved
  round-trip averages, and that ground travel and visas aren't considered.
- With 1 country: no switch, globe shows home ↔ country. With 0: today's empty state.

**The AI button** *(my call, after the builder check)*: "✨ Plan this trip with AI" lists the
countries **in the order shown** and tells the model the site suggests that order (naming the
mode: cheapest / quickest / best overall / the reader's own) on flight legs only, so it should
keep it unless ground travel, borders or seasons make another order clearly better — instead of
today's "group these into realistic trips" from scratch. Otherwise the globe and the AI could
give two different routes. The ⓘ on the button follows. Touches `buildTripAIPrompt`
(app.js:8171), `test_ai_prompts.py`, `scripts/dev/ai_prompt_check.mjs` and the per-site link
length caps (keep every prefill link within them).

## Rollout

1. **Round 15** (two free columns + "Top things to do" first) — its own plan
   (docs/superpowers/plans/2026-11-27-round15-guide-layout.md); review, gate, ship.
2. **Round 16** — shared globe module + 1A + 3 (incl. `/api/trip-legs`), built off main.
3. **Round 17** — 2A on top of round 15.
Each round: build → review lenses → fix → integrate on latest main → independent gate (all
tests, parity USD and --all, Dec 1 USD email byte-identical, CLS never worse than main at
390/768/1280 cold incl. first-reader-after-restart cases, 0 console errors, no production
requests in tests) → ship as soon as the gate passes ("ship everything now") → live verify.
**Ship window** *(my call, conservative)*: no push to main from Nov 30 00:00 ET until the Dec 1
issue is confirmed in Gmail; a round ready in that window waits for the confirmation.

## Left to the builder

- Mask resolution, cache sizes, exact drop-shadow/halo values, pin and arc styling within the
  spin-globe look.
- Exact heights per width range for 2A (fixed per range), the badge's exact inset.
- The busy-gate wiring for `/api/trip-legs` per server.py's existing conventions.
- Held-Karp vs brute force threshold; the 2-opt details.
- Test layout (new scripts/test_*.py for the leg model, ordering, endpoint caps, and markup;
  headless CLS checks with the existing scripts/dev tools).
