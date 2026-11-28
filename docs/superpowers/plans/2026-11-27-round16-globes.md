# Round 16 — globes: postcard badge (1A) + Trip route in a recommended order (3) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A still globe badge on Top Picks postcards, and a Trip tab that shows the trip as a route on a globe in a recommended order (Best overall / Cheapest / Quickest), reorderable by drag, with per-leg fare and flight time — real where our fare data has it, ≈ estimated otherwise.

**Architecture:** One small globe module in `public/app.js` (own code, no library) rendering a per-pixel orthographic globe over a country-id mask built from the already-loaded `world.geojson`; a new read-only endpoint `/api/trip-legs` that answers leg fares/times from the server's existing cached hub fares (pure logic in a new `fxtracker/triplegs.py`); the route model and ordering as pure JS functions tested under `jsc`; the Trip UI (switch, drag, leg lines, globe) on top. 2A (Where to stay globe) is NOT in this round (it lands after round 15).

**Tech Stack:** stdlib Python server (`server.py`, `fxtracker/`), `public/app.js` (+ `app.min.js` via `scripts/build_min_js.py`), `public/index.html`, `public/styles.css`; tests `scripts/test_*.py` (JS under `jsc` where noted); headless checks with `scripts/dev/*.mjs` + the r13 gate harness.

**Spec:** `/Users/doug/Desktop/Claude Workspace/docs/specs/2026-11-27-globes-design.md` (approved 2026-11-27: "proceed with shipping everything").

## Global Constraints

- No third-party script, font or data host (CSP `script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com`; `scripts/test_privacy.py` must pass unchanged in spirit — no new hosts).
- Geometry = `public/world.geojson` via `ensureWorld()`/`worldGeo` only; no new data download on first paint.
- Never modify `drawMap`, `startGlobe`, `drawGlobe` (copy ideas, not code paths). No class names starting ad/adv/sponsor/banner/promo.
- Globe look = the spin globe family: land rgb(96,212,138), ocean rgb(38,122,202), light from the upper left, halo, rim; highlighted country in the site green with a white outline; DPR capped at 2.
- Badge: Top Picks / Hidden gems ROW postcards only (`!o.secondary`), 72×72, bottom-left 6px, static, `aria-hidden`, under the credit ⓘ.
- Legs: one fare kind — trip-month cheapest cached round trip where known, else yearly `avg`, halved for one way; "I'm flexible" → `avg`. Real minutes = `dur`; estimated minutes = km/800×60+120; estimated fare from the server's regional fit (≤5,000 km rows; fallback `buildFareContext` when < 30 rows), halved. Estimated legs show "≈".
- `/api/trip-legs`: ≤12 isos; ≤4 uncached hub fetches per request (rest `pending`); cache-only while `_flight_shadow_busy()` (or the slot rules) says busy; `Cache-Control: no-store`; never indexed; no new upstream endpoint or key.
- Modes: Best overall (default) = minimise fare/bestFare + minutes/bestMinutes; Cheapest = min fare; Quickest = min minutes; Your order after a drag. Exact search n ≤ 10, nearest-neighbour + 2-opt above. Never reorder while the reader is dragging; a dragged order is never overridden by arriving data.
- Route = home → trip → home; home = the reader's From (always an `ORIGIN_HUBS` country).
- Share links carry `tp` in the order shown and open as that order.
- Nothing animates under `reducedMotion()`; pause rAF when hidden/offscreen/disconnected; globe drag must not block vertical page scroll on phones.
- CLS never worse than main on Top Picks (postcard open) and the Trip tab (0/1/3/8 countries) at 390/768/1280, slow+fast, cold.
- Minimal on-page text; explanations in ⓘ.
- Dec 1 USD email byte-identical; commits as Doug <291570524+dougc97@users.noreply.github.com> ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`; rebuild `app.min.js` after app.js edits; /usr/bin/python3; no production requests; one headless Chrome at a time via the scratchpad `chrome-lock.sh`.
- Update the app.js comment (≈7446-7455) that says grouping is left to the AI on purpose.

## Review Focus

1. Trips holding countries with no polygon of their own (GB-ENG/SCT/WLS → GB via `GUIDE_PARENT`, microstates as dots, both England and the UK on one trip): ordering works, the globe highlights/marks each stop once, no NaN coordinates. → Task 4 test `parent_and_tiny_stops`.
2. `/api/trip-legs` slow, failing (5xx/offline) or `pending`: the order is still computed from estimates (≈), totals show, and arriving real legs re-order only if the reader hasn't dragged. → Task 5 test `legs_fail_or_late`.
3. 11-12 countries (heuristic path) and 12+ (capped): ordering under 50 ms, no freeze, every country still listed. → Task 4 test `big_trip_fast`.
4. Changing From, fare currency or trip month while on the Trip tab: legs refetch, leg lines and totals switch currency/month, order recomputed (unless "Your order"). → Task 5 test `context_change`.
5. Reduced motion, touch phones: no arc animation or auto motion; a vertical swipe over the globe scrolls the page; horizontal drag rotates. → Task 6 test `motion_and_touch`.

---

### Task 1: Globe module (pure maths + renderer)

**Files:**
- Modify: `public/app.js` (new section near the other map helpers, after `distKm` ≈7037)
- Test: create `scripts/test_globe_math.py` (runs the pure functions under `jsc` with `public/world.geojson`)

**Interfaces:**
- Produces:
  - `globeMask(): {w:number, h:number, ids:Uint8Array, isoAt:string[]}` — built once from `worldGeo` (1024×512; feature index+1 per pixel, 0 = sea; `-99` features never highlighted).
  - `globeProject(lon:number, lat:number, view:{lon,lat,r,cx,cy}): [x,y,visible]` and `globeInverse(x, y, view): [lon,lat]|null`.
  - `gcPoints(a:[lon,lat], b:[lon,lat], n:number): [lon,lat][]` (great-circle slerp).
  - `globeViewFor(iso:string, size:number): {lon,lat,r,cx,cy}` (centre on `countryCentroids()`, parent via `GUIDE_PARENT`).
  - `globeDraw(canvas:HTMLCanvasElement, view, opts:{highlight:Set<string>, dots?:[lon,lat][], arcs?:{a,b,dashed,label}[], home?:[lon,lat]}): void` — per-pixel shading with a per-(size,dpr,centre) cache; tiny places (`placeSpans` < 1.5°) drawn as a ring/dot.

- [ ] **Step 1: Failing tests** in `test_globe_math.py`: `globeInverse(globeProject(p))` ≈ p within 1e-6 for 50 random visible points; `gcPoints([0,0],[90,0],3)[1]` ≈ [45,0]; a point on the far side is `visible=false`; `globeMask` gives JP at Tokyo (139.7, 35.7), FR at Paris (2.35, 48.86), 0 at (-30, 30) mid-Atlantic, GB at London; `globeViewFor("GB-SCT", 72)` centres on GB's centroid.
- [ ] **Step 2:** Run `/usr/bin/python3 scripts/test_globe_math.py`; expected FAIL (functions missing).
- [ ] **Step 3:** Implement (copy the per-pixel idea of `sphereCache`/`drawGlobe`, never call or edit them).
- [ ] **Step 4:** Run; expected PASS. Rebuild min.js; commit "Globe module: own orthographic globe on world.geojson".

### Task 2: 1A — globe badge on row postcards

**Files:**
- Modify: `public/app.js` `postcardHTML(iso, o)` (≈1861) and the row-postcard render path (`pcRender` ≈9759) to draw the badge; `public/styles.css` `.pcphoto` block (≈262-344)
- Test: `scripts/test_postcard.py` (extend), headless `scripts/dev/postcard_check.mjs` (extend)

**Interfaces:**
- Consumes: `globeViewFor`, `globeDraw` (Task 1).
- Produces: `<canvas class="pcglobe" width=144 height=144 aria-hidden="true">` inside `.pcphoto` when `!o.secondary`; `globeBadge(iso):HTMLCanvasElement` cached per iso+dpr.

- [ ] **Step 1: Failing tests:** markup: row postcards have exactly one `canvas.pcglobe`, map cards (`secondary`) none; CSS: `.pcglobe` 72×72, `left:6px; bottom:6px`, z-index below `.pccredit`; above 600px `.pcphoto:has(.pcglobe)` centres the flag in the space right of the badge; headless (390, 1280): the badge canvas has non-transparent pixels and the highlighted-country green, the ⓘ still clickable, CLS of opening a postcard unchanged vs base.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (static draw, no rAF).
- [ ] **Step 4:** Run; expected PASS. Rebuild min.js; commit "Top Picks postcard: globe badge on the photo".

### Task 3: `/api/trip-legs`

**Files:**
- Create: `fxtracker/triplegs.py`
- Modify: `server.py` (route next to `/api/flight-months` ≈3817; reuse `_fares`, `_flight_shadow_busy`, `flights.ORIGIN_HUBS`, `fxtracker/geo.py` centroids)
- Test: create `scripts/test_trip_legs.py` (no network: stub the fares source)

**Interfaces:**
- Produces:
  - `triplegs.legs(origin:str, isos:list[str], month:str|None, fares_for:callable(iso)->dict|None, cached:callable(iso)->bool, busy:bool) -> dict` returning `{"legs": {from_iso: {to_iso: {"fare": float, "basis": "month"|"avg", "dur": int|None, "stops": int|None}}}, "fit": {"a": float, "b": float, "n": int}, "pending": [iso]}`.
  - `triplegs.regional_fit(rows:list[(km:float, fare:float)], fallback:(a,b)) -> (a, b, n)` — least squares over rows ≤ 5,000 km; fallback when n < 30.
  - HTTP: `GET /api/trip-legs?origin=XX&isos=A,B,C&month=YYYY-MM` → that JSON, `Cache-Control: no-store`, `X-Robots-Tag: noindex`.
- [ ] **Step 1: Failing tests:** 13 isos → 400 (or the first 12 only — pick 400 and test it); unknown origin → 400; with 6 hub isos all uncached → exactly 4 fetched, 2 in `pending`; `busy=True` → 0 fetched, uncached in `pending`; month present in a payload row's months → `basis:"month"` with that price, else `"avg"`; a non-hub from-iso with a hub to-iso uses the reverse row; `regional_fit` ignores rows > 5,000 km and falls back under 30 rows; the handler never calls upstream when everything is cached; response headers as above.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expected PASS; `test_health_stall.py` still passes (the endpoint takes no page slot); commit "Server: /api/trip-legs from cached hub fares".

### Task 4: Route model and ordering (pure JS)

**Files:**
- Modify: `public/app.js` (new functions near the Trip code ≈7456)
- Test: create `scripts/test_trip_order.py` (jsc)

**Interfaces:**
- Consumes: `/api/trip-legs` JSON (Task 3), `countryCentroids`, `distKm`, `GUIDE_PARENT`, the Trip row fare source (`ensureFareMonths`/`flightsData`).
- Produces:
  - `tripLegMatrix(isos:string[], home:string, legsJson, homeFares:{[iso]:{to:number, back:number, basis}}): {n, fare:number[][], min:number[][], real:boolean[][]}` (index 0 = home).
  - `tripBestOrder(m, mode:"best"|"cheap"|"quick"): number[]` (indices into isos, home excluded).
  - `tripTotals(m, order): {fare:number, minutes:number, estimated:boolean}`.
- [ ] **Step 1: Failing tests:** for 200 random asymmetric matrices n=2..7, `tripBestOrder(m,"cheap")` total equals brute force's minimum (same for "quick"); a constructed 3-country matrix where cheap ≠ quick returns different orders, and "best" returns the minimiser of fare/bestFare + min/bestMin; n=1 → [0]; ties keep the input order; `parent_and_tiny_stops`: GB-ENG + GB + MC trip gives finite matrix entries and one stop each; `big_trip_fast`: n=12 random completes < 50 ms under jsc and returns a permutation.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (Held-Karp n ≤ 10; nearest-neighbour + 2-opt above).
- [ ] **Step 4:** Run; expected PASS; commit "Trip: leg model and recommended order".

### Task 5: Trip UI — switch, drag, leg lines, totals, share

**Files:**
- Modify: `public/app.js` `renderTripBar` (≈7531), `renderTripBook` (≈7634), share build/read (≈13399-13411, 13543-13557), new `fx_tripsort` key; `public/index.html` Trip stand-in script (≈597-612) to include the switch row and leg lines; `public/styles.css`
- Test: `scripts/test_trip_order.py` (UI-free parts), create headless `scripts/dev/trip_route_check.mjs`

**Interfaces:**
- Consumes: Task 4 functions; `saveTrip()`.
- Produces: `tripSortMode(): "best"|"cheap"|"quick"|"mine"`; rows carry a drag handle `button.tbdrag` (keyboard Up/Down when focused); leg line elements `.tbleg` between rows; totals `.tbtotal`.
- [ ] **Step 1: Failing tests (headless, 390 and 1280, 3-country trip TH VN KH from US):** switch shows Best overall selected; Cheapest/Quickest reorder rows and leg lines; dragging KH to the top sets "Your order", persists after reload (`fx_trip` order + `fx_tripsort=mine`), "↺ Recommended" restores the last mode; keyboard Up/Down on a handle moves a row; `?tab=trip&tp=KH,TH,VN` opens in that order as Your order; `legs_fail_or_late`: with `/api/trip-legs` blocked the list still orders, legs show ≈; delaying it 3 s then answering re-orders only when not dragged; `context_change`: switching fare currency and month refetches legs and the totals line changes currency; Trip tab CLS with 3 and 8 countries not worse than base; a 1-country trip shows no switch and no drag handle (globe home ↔ country in Task 6); an empty trip shows today's empty state unchanged.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement (leg line copy "✈️ USD 95 · 1h 40m", "≈" prefix when estimated; one totals line; one ⓘ).
- [ ] **Step 4:** Run; expected PASS; rebuild min.js; commit "Trip: recommended order with a priority switch, drag to reorder".

### Task 6: Trip route globe

**Files:**
- Modify: `public/app.js` (draw in `renderTripBar`/`renderTripBook` area), `public/index.html` (stand-in gets the globe box), `public/styles.css`
- Test: `scripts/dev/trip_route_check.mjs` (extend)

**Interfaces:**
- Consumes: `globeDraw`, `gcPoints`, the current order (Task 5).
- Produces: `div.tripglobe > canvas` fixed box (above rows; beside them from 900px).
- [ ] **Step 1: Failing tests:** the globe draws home + numbered stops + one arc per leg in order (dashed where ≈); horizontal drag rotates, a vertical swipe scrolls the page (`touch-action: pan-y`); `motion_and_touch`: under emulated `prefers-reduced-motion` no rAF runs after the first draw; hidden tab → rAF stops; Trip tab CLS unchanged with the box in the stand-in.
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run; expected PASS; rebuild min.js; commit "Trip: the route on a globe".

### Task 7: The AI button follows the shown order

**Files:**
- Modify: `public/app.js` `buildTripAIPrompt` (≈8171) and the `#tripPlanBtn` ⓘ text in `public/index.html`
- Test: `scripts/test_ai_prompts.py`, `scripts/dev/ai_prompt_check.mjs`

- [ ] **Step 1: Failing tests:** the prompt lists the countries in the displayed order and names the mode ("cheapest" / "quickest" / "best overall" / "your own order") as a flight-legs-only suggestion to keep unless ground travel, borders or seasons argue otherwise; the old "Group these into realistic trips" ask is gone; every site's prefill link stays within its length cap (the caps the test already pins).
- [ ] **Step 2:** Run; expected FAIL.
- [ ] **Step 3:** Implement; update the ⓘ; update the app.js ≈7446 design comment.
- [ ] **Step 4:** Run; expected PASS; ALL `scripts/test_*.py` one by one, parity USD and `--all`, `build_min_js.py --check`, goldens; commit "Trip AI prompt: keep the shown order".
