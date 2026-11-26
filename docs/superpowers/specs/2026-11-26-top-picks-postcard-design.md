# Top Picks postcard (quick look) — design

Status: APPROVED by Doug 2026-11-26 ("your calls all sound good, build it after r10 and r11 ship"); builder-check answers folded in the same day as my calls 2, 3, 3b, 7 · builds after rounds 10 and 11 ship
Where it lives: here in the workspace for now (main must stay at 1a1d75b while round 10's gate runs); it gets committed to the repo as `docs/superpowers/specs/2026-11-26-top-picks-postcard-design.md` on the feature branch.

## Intent (Doug's words, 2026-11-26)

"Add a quick dropdown whenever someone clicks on a country in the list that gives a brief, high-level overview of the country and add option to either find more details (navigates to travel guide tab) or an 'add to cart' feature that adds the country to the 'trip' list. Want to avoid navigating them away from the top picks tab with just one click (forcing them to click back button to go back to tab), and have them intentionally choose to find out more details about a particular country if they want."

Doug picked the **postcard** (option B): the country's lead photo, its one-line description and three facts the row doesn't show, with **Full guide →** and **🧳 Add to trip**. The map's country card switches to the same look.

## How it works today

- Top Picks and 💎 Hidden gems share `renderGradeTable` (public/app.js ≈ 9056). Each row is `<tr data-iso data-m?>`, and the country name is a real link `<a class="destlink" href="/guide/<slug>">` (keyboard focus, cmd/middle-click opens a new tab, Google sees it).
- One delegated click handler (≈ 9145-9170) sends **every** click somewhere else: name or empty space → `openGuideFor(iso, true)` (the Travel Guide tab, a history entry); each grade cell (`td.scell[data-go]`) → `goToDetail(factor, iso)` (Data tab or the guide's weather). "Any time" rows carry `data-m` and call `setFlexFocus(month)` first so the guide opens on that row's best month.
- The Top Picks map (and other maps) open `showCountryCard` (≈ 1640-1720): facts (currency move, price in words, safety in words, best months, "worth N–M days"), `activities[iso].summary`, and buttons Country guide →, ✓ Been, ★ Want to go, 🧳 Add to trip.
- Trip list: `tripHas`, `tripToggle` (≈ 6985); the guide's "Add Japan to my trip" button and the Trip tab use the same list.
- Lead photo per country: the guide hero calls Wikipedia's API live (`photoSubjects` → `wikiIconic`, honouring `photo-skip.json`) and shows a credit (`loadPhotoCredits`). (`public/og-images.json` exists but is stale and unused by share previews since they moved to the site's own cards; see my call 2.) Hotlinked Wikimedia thumbnails must use the allowed widths (20/40/60/120/250/330/500/960/1280/1920/3840 or 400); `scripts/dev/thumb_check.mjs` checks.
- Visa: `visaInfo(iso, passport)` + `VISA_META` labels (Visa-free / eTA / On arrival / eVisa / Visa req'd / Restricted / Check); US passports use `visa.json`, others the lazily loaded `/visa-passport.json` (`ensureVisaMatrix`).
- Price in words: `plPhrase(pl / plAnchor(home).pl, name)` ("~84% cheaper than the US"); round 10 settles what it says when live rates fail (compare with the US, no "no figure for …").
- Subtitle today: "Graded like a report card — tap a row for the full guide."

## Goals

1. One click on a Top Picks or Hidden gems row opens a postcard right under that row; nothing leaves the tab.
2. Going deeper is a deliberate second click: **Full guide →** (Travel Guide tab, on the row's own month in "Any time").
3. **🧳 Add to trip** from the postcard, with clear state ("✓ On your trip" to undo).
4. The postcard tells the reader something the row doesn't, in a glance: photo, one line, three facts.
5. The map's country card looks the same, so a country "looks" the same wherever you open it.

## Non-goals

- No change to the Travel Guide page, the newsletter, the Data tab tables, or the server's data.
- No new data files or endpoints: the photo comes through the guide hero's existing lookup.
- No URL/history entry for opening a postcard (Back never closes a postcard; it leaves the page as it does today).
- No new analytics.

## Anti-goals (a failure even if it works)

- A postcard that grows or jumps after it opens (a late photo or late facts pushing the page).
- Any layout shift on page load, or a slower first paint of Top Picks (nothing new is fetched until a postcard opens).
- A text-heavy card. Doug's direction: minimal on-page text, bold story-like type, explanations in ⓘ tips.
- Breaking cmd/middle-click "open in new tab" on the country name, or removing the crawlable guide links.
- Trapping or losing keyboard focus.

## Approaches considered

| | What | Trade-off |
|---|---|---|
| A | The map's existing card, trimmed to two buttons, opened under the row | Fastest, text only, matches the map as it is |
| **B (picked by Doug)** | **Postcard: lead photo + one-liner + 3 facts + 2 buttons; map card switches to it** | Story-like, adds visa (a real deciding factor missing from the row); one photo per open and more phone layout work |
| C | Only stop the navigation (row click does nothing new) | Solves the Back problem but gives no overview; rejected |

## The design (decided parts)

```
#1 🇪🇬 Egypt  [Best in Apr]                     A+   B   A+   A+     A 92
┌──────────────────────────────────────────────────────────────────────┐
│ ┌──────────┐  Pyramids, Nile cruises and Red Sea diving.             │
│ │  photo   │  💰 ~84% cheaper than the US · 🛂 eVisa · 📅 Oct–Apr      │
│ │          │  [ Full guide → ]  [ 🧳 Add to trip ]                ✕  │
│ └──────────┘                                                    ⓘ   │
└──────────────────────────────────────────────────────────────────────┘
#2 🇮🇳 India …
```

- **Opens:** a plain click (or Enter) anywhere on a row, including the grade badges, toggles that row's postcard. One postcard open at a time; opening another closes the first. Clicking the same row, ✕, or Esc closes it (Esc returns focus to the row's name).
- **Content, in this order:** lead photo · `activities[iso].summary` (one line) · three facts: 💰 price in words vs the reader's home, 🛂 visa status for the reader's passport (the `VISA_META` label; the reader's own country says so), 📅 best months (the same months the guide's "best months" sentence names) · buttons **Full guide →** and **🧳 Add to trip** / **✓ On your trip**.
- **Full guide →** is a real link to `/guide/<slug>`: a plain click opens the Travel Guide tab as the row does today (with `setFlexFocus(data-m)` on "Any time" rows); cmd/middle-click opens a new tab.
- **Add to trip** uses `tripToggle`; the button flips in place and the postcard stays open.
- **Map card:** `showCountryCard` takes the postcard look (photo, one-liner, the same three facts, the two buttons). See "my calls" for the Been / Want to go buttons.
- **Subtitle:** "Graded like a report card — tap a row for a quick look." (the served copy in index.html too).

## My calls (not Doug's; easy to change)

1. **Grade badges open the postcard too** instead of jumping to the factor's detail, so no single click leaves the tab (Doug's goal). Their hover tips stay; the detail is one click further via Full guide.
2. **Photo (revised after the builder check):** the guide hero's own first photo, looked up on open through the hero's existing path (`photoSubjects` → `wikiIconic`, which already honours `photo-skip.json`, picks a sized thumbnail, and gives the place name for the alt text), NOT `og-images.json`. That file is stale (last built Oct 6; 45 of its 190 entries are now on the Oct 30 skip list, incl. Spain, Chile, Iceland, Israel, Hong Kong; it predates later gallery decisions such as Japan opening on Fushimi Inari; nothing reads it any more except a privacy test; 10 entries are full-size originals). Cost: one Wikipedia API call per first open of a country (cached for the session; may start on hover/focus of a row to hide the wait); still nothing at page load. Shown as a 330px (500px on 2x screens) Wikimedia thumbnail in a fixed-size box reserved before the image arrives, so the card never grows. If the lookup or image fails, the box keeps its size and shows the country's flag on a tinted background. The photo's author and licence go in a small ⓘ on the photo (`loadPhotoCredits`, as the hero does). `og-images.json` is left alone.
3. **Map card (revised after the builder check):** `showCountryCard` is shared by five maps (Currency, Safety, Cost, Flights, Top Picks). Every one gets the postcard look (photo, one-liner, the postcard's facts, Full guide → and 🧳 Add to trip), plus **the one fact that map is about**, so no map loses its readout: the Currency map keeps 💱 "your USD +1.2% vs 1-yr avg"; the Safety map keeps 🛡️ the advisory in words; the Flights map keeps its fare fact if the card shows one today. "Worth N–M days" moves into the third-fact rule below. ✓ Been and ★ Want to go stay on map cards as two small secondary buttons, because the Wander List relies on marking countries from the maps; Top Picks rows don't show them (two buttons, as Doug asked). The full-screen map overlay, where the card floats over the map, gets the same card.
3b. **Third fact (revised after the builder check):** 📅 best months, EXCEPT on a row that already speaks about months — an "Any time" row's "Best in <month>" chip (app.js ≈ 8921 removed weather-best months beside that chip because the two "read as if they disagreed") or a single-month row's "🗓️ Best in …" tag. There the third fact is 🧳 "worth 8–12 days" (`activities[iso].days`) instead, so the postcard never repeats or seems to contradict its row. Map cards (no row) show 📅.
4. **Re-renders:** if the list re-renders while a postcard is open (sort, filter, month, budget), the postcard stays open if that country is still in the list, else it closes.
5. **Phones:** the postcard stacks (photo on top as a short wide strip, text and buttons under it) at narrow widths; same content.
6. **No extra fetch at page load:** the photo lookup and (for non-US passports) `/visa-passport.json` load on the first open; facts that need data still on its way show their final layout immediately (reserved line), filling in place.
7. **Starting point:** build on main after rounds 10 and 11 ship. Round 11 only touches the guide's "Where to stay" block (`renderGuideStay`, `guide_sizers.stay`), not Top Picks. Round 10's `r10/picks-rates-down` may replace the Top Picks / Hidden gems list with a "Live exchange rates didn't load" line when rates fail; no postcard exists in that state, and the postcard must not break that notice or its retry.

## Constraints the build must respect

- app.js ships minified: rebuild `public/app.min.js` (+ `.sha256`) after edits. Don't touch drawMap/startGlobe/drawGlobe.
- The served homepage draws the first rows before app.js (servedOnScreen / holdServedPicks): those links keep working as plain links until the app takes over; no layout shift on load at 390, 768 and 1280 (CLS tools, main vs branch).
- Accessibility: the control that opens a postcard announces its expanded state and what it controls; focus moves sensibly into and out of the postcard; screen-reader names for the buttons and photo (place name, as the hero's alt does).
- Wikimedia: allowed thumbnail widths only; no other image hosts.
- Rates-down and advisory-down behaviour follow rounds 9 and 10 (no band word for non-US readers, no "no figure for …" when only live rates failed).
- The newsletter's output must stay byte-identical (it shouldn't read any of this).
- After it ships, the local Jan 1 newsletter branch (jan/window-polish) must merge main again before its Dec 2 landing.

## Left to the builder

- Markup and CSS (an extra `<tr><td colspan>` under the row is the obvious shape; keep the table's column widths stable when it opens).
- The exact best-months helper to reuse and the compact month-span format.
- How the toggle is exposed to assistive tech while keeping the name a real link for new-tab and crawlers.
- Test files (node-extracted unit tests in the repo's style + headless at 390/768/1280: Top Picks, Hidden gems, "Any time", visited rows, budget filter, a non-US reader, rates down, keyboard, layout shift).
