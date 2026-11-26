# Top Picks Postcard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One click on a Top Picks / Hidden gems row opens an inline postcard (photo, one-liner, three facts, Full guide → / 🧳 Add to trip) instead of leaving the tab; the five maps' country card takes the same look.

**Architecture:** Two pure helpers in public/app.js build the postcard's facts and markup (unit-tested in node like scripts/test_snapshot_band.py); a session-cached photo loader reuses the guide hero's lookup; the grade-table click delegate toggles one `<tr class="pcrow">` under the clicked row; `showCountryCard` renders the same markup plus its map's own fact.

**Tech Stack:** vanilla JS (public/app.js → public/app.min.js via scripts/build_min_js.py), public/styles.css, public/index.html, Python test scripts that run extracted JS in node, headless Chrome (scripts/dev/cdp.mjs) for layout and keyboard checks.

**Spec:** /Users/doug/Desktop/Claude Workspace/docs/specs/2026-11-26-top-picks-postcard-design.md (commit it, and this plan, as docs/superpowers/specs/2026-11-26-top-picks-postcard-design.md and docs/superpowers/plans/2026-11-26-top-picks-postcard.md on the branch).

## Global Constraints

- Buttons exactly "Full guide →" and "🧳 Add to trip" / "✓ On your trip"; subtitle exactly "Graded like a report card — tap a row for a quick look." (public/index.html:170 and any server copy of it).
- Facts in this order: 💰 price in words (`plPhrase(pl / plAnchor(guidePassport()).pl, anchor.name)`), 🛂 visa (`visaInfo(iso, guidePassport())` → `VISA_META[status].label`; own country → "your home country"), third fact 📅 best months (`monthSpan(climate[iso].best)`) or, on a row already showing a month (flex row `data-m`, or a "🗓️ Best in" seasonal tag), 🧳 "worth N–M days" (`activities[iso].days`).
- One-liner = `activities[iso].summary`.
- Photo = first of `iconicPhotos(iso)` (honours photo-skip.json), drawn via `wmThumbAt` at 330 (500 on devicePixelRatio ≥ 1.5), alt from `photoWhere`, credit via `loadPhotoCredits` in an ⓘ; fixed box; flag on tint when none.
- No history entry, no URL change on open/close. Nothing new fetched at page load.
- Map cards: postcard + that map's fact (Currency 💱 move vs 1-yr avg; Safety 🛡️ advisory words; Flights its fare fact if shown today) + small "✓ Been" / "★ Want to go".
- Rebuild app.min.js + .sha256 after every app.js change; never touch drawMap/startGlobe/drawGlobe; Wikimedia allowed thumb widths only; minimal on-page text; newsletter output byte-identical.

## Review Focus

1. Cmd/ctrl/shift/middle-click on the country name → browser opens /guide/<slug> in a new tab; no postcard opens (test in Task 3).
2. The photo arrives 2 s late (throttled) → postcard height identical before and after (test in Task 5).
3. Sort, filter, month or budget change while a postcard is open → stays open on the same country if still listed, closes if not; never two `.pcrow` (test in Task 3).
4. Rates down (round 10's "Live exchange rates didn't load" notice) or advisories down → no postcard errors; price fact follows round 10's wording; non-US passport before /visa-passport.json lands → visa fact fills in place without moving the card (tests in Tasks 1 and 3).
5. Keyboard only: Tab to a name, Enter opens, Tab reaches both buttons, Esc closes and focus returns to the name; screen reader hears expanded/collapsed (test in Task 3).

---

### Task 1: Postcard facts and markup (pure)

**Files:**
- Modify: `public/app.js` (new functions next to `showCountryCard`, ≈ line 1640)
- Test: `scripts/test_postcard.py` (new; extract functions into node the way `scripts/test_snapshot_band.py` does)

**Interfaces:**
- Produces: `postcardFacts(iso, { rowHasMonth: boolean, mapFact: string|null }) -> Array<{ k: "price"|"visa"|"months"|"days"|"map", html: string, pending: boolean }>`
- Produces: `postcardHTML(iso, { rowHasMonth, mapFact, photo: {src, srcset, alt, credit}|null, inTrip: boolean, secondary: boolean }) -> string` (secondary = map card's Been / Want to go)

- [ ] **Step 1: Write failing tests** `test_postcard.py`: (a) JP with fixtures, rowHasMonth=false → facts k == ["price","visa","months"], price html contains "cheaper than the US" or "pricier than the US"; (b) rowHasMonth=true → third k == "days" and html "worth 10–21 days"; (c) passport == iso → visa html "your home country"; (d) visa matrix not loaded for passport "DE" → visa fact `pending: true` with a reserved non-empty placeholder; (e) markup has `href="/guide/japan"` on "Full guide →", "🧳 Add to trip" when inTrip=false and "✓ On your trip" when true; (f) photo=null → flag markup inside the same `.pcphoto` box; (g) every interpolated string escaped (`<b>` in a summary renders `&lt;b&gt;`); (h) mapFact given → appended as k "map"; secondary=true → "✓ Been" and "★ Want to go" present.
- [ ] **Step 2: Run** `/usr/bin/python3 scripts/test_postcard.py` → FAIL (functions missing).
- [ ] **Step 3: Implement** both functions per Global Constraints (rates-down price wording comes from the helpers round 10 left in place; do not re-derive it).
- [ ] **Step 4: Run** test → PASS; `/usr/bin/python3 scripts/build_min_js.py`.
- [ ] **Step 5: Commit** "Postcard: facts and markup helpers".

### Task 2: Photo loader with session cache

**Files:**
- Modify: `public/app.js` (next to `iconicPhotos`, ≈ 4359)
- Test: `scripts/test_postcard.py` (add cases)

**Interfaces:**
- Consumes: `iconicPhotos(iso)`, `wmThumbAt(url, w, origW)`, `photoWhere(p, iso)`, `loadPhotoCredits(photos)`
- Produces: `postcardPhoto(iso) -> Promise<{src, srcset, alt, credit} | null>` (memoised per iso for the session; a rejected lookup resolves null and is not cached forever: retry on the next open)

- [ ] **Step 1: Failing tests** with stubbed `iconicPhotos`: first photo used; width 330 in `src`, 500 in `srcset`; only allowed widths; second call returns the same promise (one lookup); lookup throws → null.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement.** **Step 4: Run** → PASS; rebuild min. **Step 5: Commit** "Postcard: photo loader".

### Task 3: Row toggle in Top Picks and Hidden gems

**Files:**
- Modify: `public/app.js` grade-table click delegate (≈ 9145-9170), `renderGradeTable` (≈ 9056, re-open after re-render), `public/index.html:170` subtitle (and its server copy if render code emits it)
- Test: `scripts/test_postcard.py` (delegate logic extracted) + headless script `scripts/dev/postcard_check.mjs` (new)

**Interfaces:**
- Consumes: Task 1 `postcardHTML`, Task 2 `postcardPhoto`, `tripHas`, `tripToggle`, `rowFocus`, `setFlexFocus`, `openGuideFor`
- Produces: `togglePostcard(tr: HTMLTableRowElement) -> void`, `closePostcard(returnFocus: boolean) -> void`, module state `_pcOpen = { hostId, iso } | null`

- [ ] **Step 1: Failing headless checks** (local server, recorded fixtures, 390 and 1280): plain click on row / on a grade pill / on the name → one `.pcrow` directly after that row, URL unchanged, `#tab-value` still shown; click same row → closed; click another → moves; Esc → closed + focus on that row's `a.destlink`; cmd-click on name → no `.pcrow` (default not prevented); Enter on focused name → opens, `aria-expanded="true"`; sort click while open → same iso still open, one `.pcrow`; filter that removes it → closed; "Full guide →" on an Any-time row → guide tab on `data-m` month; "🧳 Add to trip" → label flips to "✓ On your trip", postcard still open, Trip tab count +1; rates blocked → round 10 notice shows, no console errors.
- [ ] **Step 2: Run** → FAIL. **Step 3: Implement** (prefetch `postcardPhoto` on `pointerenter`/`focusin` of a row, ≥ 150 ms dwell). **Step 4: Run** → PASS; all `scripts/test_*.py`; rebuild min. **Step 5: Commit** "Top Picks: a row opens its postcard; going deeper is a second click".

### Task 4: Map cards take the postcard look

**Files:**
- Modify: `public/app.js` `showCountryCard` / `renderCountryCard` (≈ 1640-1720) and its caller (≈ 1237)
- Test: `scripts/dev/postcard_check.mjs` (map cases)

**Interfaces:**
- Consumes: Task 1, Task 2
- Produces: `mapFactFor(hostId: string, iso: string) -> string|null` ("map" fact per map: currency, advisory, flights)

- [ ] **Step 1: Failing headless checks**: on each of the 5 maps (incl. full-screen overlay) a country click shows the postcard with that map's fact; Currency map card shows the 💱 move; "✓ Been" / "★ Want to go" still toggle and the Wander List updates; ✕ closes.
- [ ] **Step 2-5:** run → FAIL, implement, run → PASS + all tests + rebuild min, commit "Maps: the country card is the postcard, plus the map's own fact".

### Task 5: Styles, phones, no shift

**Files:**
- Modify: `public/styles.css` (new `.pcrow`, `.postcard`, `.pcphoto`, `.pcfacts`, `.pcbtns`; map `.countrycard` variant)
- Test: `scripts/dev/postcard_check.mjs` (layout cases) + the repo's CLS tools

- [ ] **Step 1: Failing checks**: at 390 the postcard stacks (photo strip on top), at ≥ 768 photo left; column widths of the table identical with a postcard open vs closed; photo throttled 2 s → card height unchanged; no horizontal scroll at 320/390/768/1280; page-load CLS on `/` equal to main (3 cold loads, no postcard involved).
- [ ] **Step 2-5:** run → FAIL, implement, run → PASS, commit "Postcard: layout".

### Task 6: Whole-branch verification

- [ ] Commit the spec and this plan under docs/superpowers/.
- [ ] ALL `scripts/test_*.py` one by one (mock upstash for test_accounts), parity USD and --all, `build_min_js --check`, newsletter goldens unchanged (Dec 1 USD email byte-identical).
- [ ] Headless proof screenshots (390 and 1280: Top Picks open postcard, Hidden gems, a map card) saved to scratch for the report.
