# WanderGrade full-site review 3 — 2026-10-27/28

Live site https://wandergrade.com reviewed on 2026-10-28 (UTC) against `main` at a1c6d84, GET requests only, analytics beacon blocked in every headless-Chrome load. Seven area reviewers ran in parallel (one Chrome at a time), then a separate skeptic pass tried to disprove every finding.

**Totals:** 68 raw findings → 5 duplicates merged → 5 dropped by the skeptic pass → **58 confirmed: 2 High, 17 Medium, 39 Low.**
**Fixed: 47** — 36 already on `main`: `review3/fixes`' 33 (guides byte-identical to a1c6d84) and the newsletter copy NL-1, NL-3 and NL-5 (`review3/newsletter`, Doug's spec of 2026-10-28), which `main` took as copies on 2026-10-28; 11 on `review3/after-nov9` (draft dougc97/wandergrade#3, change guide HTML or guide words; merge after 2026-11-09). **Not fixed: 11** (5 owned by the other session, 6 with reasons below).

Branches: `review3/report` (this file only, from a1c6d84). `review3/fixes` and `review3/newsletter` are on `main` as copies (26e8fc8 … dd92140, then d6b7a4b; 63acb48 is an earlier newsletter version it supersedes; dougc97/wandergrade#2 closed as landed), so the commits cited below are `main`'s. `review3/after-nov9` is rebased onto that `main` (30c9071); its PR is the draft dougc97/wandergrade#3.

| Area | High | Medium | Low | Fixed | Not fixed |
|---|---|---|---|---|---|
| 1. Top Picks, Any time, gems, Trip, Wander List, share | 1 | 2 | 5 | 7 | 1 |
| 2. Guides | 0 | 4 | 9 | 10 | 3 |
| 3. Data tabs | 0 | 2 | 6 | 7 | 1 |
| 4. List pages | 1 | 2 | 5 | 7 | 1 |
| 5. Newsletter | 0 | 2 | 3 | 4 | 1 |
| 6. Technical | 0 | 0 | 7 | 4 | 3 |
| 7. Accessibility & mobile | 0 | 5 | 4 | 8 | 1 |
| **Total** | **2** | **17** | **39** | **47** | **11** |

Severity in this file is the final (post-skeptic) severity. Where a finding needs a production observation, the quoted output is from production unless it says "local".

---

## 1. Top Picks, Any time, hidden gems, Trip, Wander List, share image

### TP-1 · High · data — Spain, the UK, Canada, China, Sweden, Iceland and Taiwan listed as "Hidden gems — off the beaten path"
- **Where:** `/` `#gemsBox`/`#gemRows`; `public/app.js` `ensurePopularity` (~8384–8401); newsletter `fxtracker/picks.py` `_popular_set` (~479–490).
- **Evidence:** `/api/popularity` has 211 rows but `ES GB CA CN SE IS TW MT LT LV …` (41 scored countries) are null. The World Bank's `ST.INT.RCPT.CD` (last updated 2026-10-08) returns `None` for ES/GB/CA in every year 2015–2025 and France only to 2020. The page ran with `popularDataBacked:true`, `"ES:false GB:false CA:false CN:false"`; gems at Top 20, Europe, Any time: `CY MT MK AD ES SM ME SI LT LV SK MD EE XK BA RS GB AL SE IS`; China was gem #12 with no filter. The newsletter uses the same set (its popular set equals production's 60/60).
- **Fix:** a curated-list country with no figure stays popular (union with the fallback list), in app.js and picks.py alike. Goldens unaffected (the snapshot uses the fallback set); parity 0 mismatches.
- **Branch:** `main` 26e8fc8.

### TP-2 · Medium · bug — A pick/gem with no guide page (Malta, Andorra, San Marino…) rewrites the URL to /guide/japan
- **Where:** `app.js` `buildShareURL` (~11346, `guidePath(_guideTarget || $("bestCountry").value || "JP")`), `buildBestPickers` (~4075).
- **Evidence:** clicking the Malta gem gave `{"href":"https://wandergrade.com/guide/japan","h":"🇲🇹 Malta travel: cost, safety & when to go","sel":"JP"}`; `buildShareURL(true)` → `/guide/japan?vmf=1`; reload showed Japan. Affects AD BQ FM JE KM LI MC MH MO MT PW SC SJ SM TC VA VG. Reproduced by the skeptic from the Cost-of-living table.
- **Fix:** keep `/?tab=guide&gc=MT` for a no-guide country; picker left empty for it; share link and tab meta use the country on screen. No guide page changes (every guide country has a picker option).
- **Branch:** `main` b4a28f0; a follow-up, `main` 30c9071, fixed its share link when it carries a month (a second `?` made `gc` read `MT?vmf=1` and opened Japan).

### TP-3 · Low · copy — Rank share image calls a month's cheapest fare "avg flight"
- **Where:** `app.js` `buildRankShareSVG` (~12032).
- **Evidence:** image text `"avg flight ~US$511 · prices ~71% cheaper than the US"` (Thailand, best in Nov) while the row is graded on `TH:month:fare=511` and the fare strip says `November: from USD 511 round-trip`; the Trip prompt's real average is `flights avg USD 1,030`.
- **Fix:** "flights from ~US$511 in Jan" when graded on the month's fare; "avg flight" kept for year-round; stale comment updated.
- **Branch:** `main` 8aefa38.

### TP-4 · Medium · policy (safety wording) — Top Picks row hover states safety with no source
- **Where:** `app.js` `whyLine` (~7816), the `title` of every `#topCards`/`#gemRows` row.
- **Evidence:** TH row title `"… decent weather in November · safest travel rating"`; Level 3 rows `"⚠️ has a reconsider-travel advisory"` — no government named, while the pill in the same row says `Level 1: normal precautions — per US State Dept`.
- **Fix:** the hover gives the level in the government's own words and names it (`"Level 1: normal precautions per US State Dept"`, `"⚠️ Level 3: reconsider travel per US State Dept"`, a gap-filling government named as such).
- **Branch:** `main` 57ae54b.

### TP-5 — duplicate of LP-1 (Côte d'Ivoire / Republic of the Congo "no advisory").

### TP-6 · Low · perf/CLS — Returning visitor with a ✓ been mark: Top Picks table drops 18px on a phone
- **Where:** `index.html` `#picksNote` stand-in and the inline script inside `#topCards`.
- **Evidence:** cls.mjs, production, 390px, `M_NET=150,1600`, `M_SEED={"fx_visited":["FR"]}`: `0.0045`, sources `#topCards,#rankShare`, rect 670→688; cold visitor `0`. The stand-in lacks the ` N you've been to hidden · show` note renderValue appends.
- **Fix (proposed):** the pre-paint script also reads `fx_visited` and appends an invisible `.beennote` stand-in.
- **Branch:** not fixed — owned elsewhere (the `#topCards` skeleton and its inline script are what the other session's server-rendered Top Picks rows replace).

### TP-7 · Low · bug — Re-sharing a shared trip sends the viewer's own month
- **Where:** `app.js` ~11362 reads `localStorage.fx_tripmonth`.
- **Evidence:** `/?tab=trip&tp=TH,VN&td=10&tm=3` with `fx_tripmonth=5`: screen says March, share link `…&tm=5`; a fresh viewer's link drops `tm`.
- **Fix:** use `tripMonthSaved()`.
- **Branch:** `main` 0df5274 (with TP-8).

### TP-8 · Low · consistency — Trip "I'm flexible": Flights link Dec 27–Jan 6, Stays link Nov 15–18 on the same row
- **Where:** `app.js` ~6476 (`flightSearchURL(fr.dest, null)` → today+60) vs `tripStayDates` ~6431.
- **Evidence:** Thailand row `aviasales.com/search/NYC2712BKK06011` next to `stay22…checkin=2026-11-15&checkout=2026-11-18` (URL strings only; not clicked).
- **Fix:** flexible trips' flight links search the stays' month (mid-month).
- **Branch:** `main` 0df5274.

### TP-9 · Low · copy — Under "Any time" the grade-table header tips say "your chosen month" / "this month's fare"
- **Where:** `app.js` `renderGradeTable` header titles (~8262–8277); `index.html` `#valueTable` header (~411–412).
- **Evidence:** header tips `weather comfort for your chosen month` and `this month's fare vs the route's usual…` while the rows read `Best in Nov`, `Best in Feb`.
- **Fix:** app.js says "each row's month" under Any time (`main` ae0d578); the template's static tips say "the month graded" (`review3/after-nov9` 0f9adaa, template = guide HTML).

---

## 2. Guides (/guide/<slug>)

Sampled 43 on production, raw and hydrated: antarctica, england, scotland, wales, united-kingdom, syria, yemen, afghanistan, russia, venezuela, guernsey, isle-of-man, faroe-islands, greenland, aruba, curacao, puerto-rico, guam, falkland-islands, french-southern-territories, western-sahara, hong-kong, taiwan, cuba, united-states, portugal (Vrbo), iceland, thailand (Vrbo), japan, india, kenya, morocco (Vrbo), nigeria, south-africa, egypt, peru, mexico, argentina, fiji, new-zealand, jordan, united-arab-emirates (Vrbo), china. Advisory levels matched the live US/CA/DE feeds; home nations use GBP and the UK-wide price; Antarctica has no currency/cost/flights lines; Vrbo buttons matched the deliberate list; canonical/og stable after hydration.

### GD-1 · Medium · policy — Level 4 guides serve the EKTA insurance affiliate link in their server HTML
- **Where:** `/guide/syria` (also yemen, afghanistan, russia) `#ssrGuide p.afflink`; `fxtracker/render_guide.py` ~595.
- **Evidence:** right after `<p>🛡️ Level 4 · Do not travel — Safety · per US State Dept (Oct 2026)</p>`: `<a class="staybtn" href="https://tp.media/r?campaign_id=225&amp;marker=738472&amp;p=5869&amp;sub_id=guide-syria…" rel="sponsored nofollow noopener">🛡️ Travel insurance (EKTA)</a>`; after hydration `#guideInsurance` is hidden. Crawlers and no-JS readers see it, contradicting app.js's "never flashes on a Level 4 page".
- **Fix:** the crawler block omits the insurance line when the snapshot's level is 4.
- **Branch:** `review3/after-nov9` 30ac276.

### GD-2 · Medium · bug (layout) — Unrated guides show a 228–250px blank where Safety would be
- **Where:** `/guide/western-sahara`, `/guide/french-southern-territories` `#guideSafety`; `styles.css` ~1268 (`display:block` beats `[hidden]`) + the `:empty` min-height hold.
- **Evidence:** production geometry `"guideSafety":{"y":463,"h":250,"hidden":true,"empty":true}` (390px), `h:228` at 1280. The reviewer's `[hidden]{display:none}` alone would collapse 250px after JS (new CLS) — rejected by the skeptic.
- **Fix:** styles.css only: the hold is released from first paint on the server's own marks for an unrated guide (`#tab-guide:not([data-level])[data-lvca="0"][data-lvde="0"]`, only these two guides carry them) and the hidden state is `display:none`. Frame-by-frame: height 0 from the first frame; France/Syria unchanged; cls.mjs identical.
- **Branch:** `main` 3653a5d.

### GD-3 · Low · bug — "🏨 Where to stay" jump chip shows on guides with no stays and scrolls to the newsletter
- **Where:** `nav.guidejump button[data-go="guideStay"]` on syria, yemen, afghanistan, russia, venezuela, antarctica; `app.js` ~10811.
- **Evidence:** Syria hydrated: `{'go': 'guideStay', 't': '🏨 Where to stay', 'vis': True}` while `#guideStay` is hidden; the handler falls back to `$("subscribe")`.
- **Fix:** `#tab-guide[data-nostay] .guidejump [data-go="guideStay"] { display: none; }` (removes visible guide words).
- **Branch:** `review3/after-nov9` cbfc99d.

### GD-4 · Medium · policy (attribution) — Canada's "📍 Avoid all travel" lines sit under "Safety · per U.S. State Department"
- **Where:** Level 1–2 guides (thailand, mexico, peru, morocco, egypt) `#guideSafety .woreg`; `app.js` `renderWatchouts` calm branch (~3626); `guide_sizers._watchouts`.
- **Evidence:** Thailand: `Safety · per U.S. State Department: “Exercise normal precaution in Thailand…”` then `📍 Avoid all travel: the area within 50 kilometres of the Thailand-Cambodia border ⓘ` … then `🧭 Safety notes (8) — nothing unusual for a Level 1 country (per Global Affairs Canada — details ↗)`. Level 1 is the US level (Canada rates Thailand 2), and "nothing unusual" is the site's own judgement.
- **Fix:** Canada's lines follow a "Regional advice (per Global Affairs Canada — details ↗)" heading; the fold reads "🧭 Safety notes (8)" with the source; app.js and its server stand-in alike. Local check: stand-in height equals hydrated height (Thailand 335/335, Mexico 355/355, Japan 166/166).
- **Branch:** `review3/after-nov9` 16c4010.

### GD-5 · Low · copy — State Department quotes cut mid-word, sentences run together
- **Where:** `#guideSafety .advwhy` and stand-in; `fxtracker/advisories.py` `_summary` (`out[:277] + "..."`).
- **Evidence:** Afghanistan `“Do not travel to Afghanistan for any reason We urge American citizens … and U.S. pas...”`; Aruba `“Exercise normal precaution in Aruba Aruba is generally a safe destination…”`; UAE `“… restrictions U.S. government employees … due to U...”`.
- **Fix:** cut at the last sentence end (not after an initial like "U.S.") or the last word + "…"; an unpunctuated block end ends its sentence; styled section titles ("Crime", Gabon's "Unrest", Guinea's bold line before a break) are dropped. 20 of 214 current summaries change (checked one by one); DR Congo loses a spurious "Other" chip.
- **Branch:** `review3/after-nov9` 043d28c.

### GD-6 · Low · consistency — Guernsey/Isle of Man (GBP) and Faroes/Greenland (DKK) show the plain exchange-rate move beside England's after-inflation figure
- **Where:** `#guideFx`; `app.js` ~2931, `GUIDE_PARENT` (~1843) covers only England/Scotland/Wales.
- **Evidence:** same session: England `+0.2% vs its 12-month average, after inflation — about typical`; Guernsey and Isle of Man `+0.7% vs its 12-month average (exchange rate only)`; Faroes/Greenland `+4.1% … (exchange rate only)`. Skeptic: the "(exchange rate only)" label is the deliberate honest-gap pattern (d19a87b), so this is not a banned nominal claim.
- **Fix (proposed):** an FX-only parent map `GG/IM/JE→GB, FO/GL→DK` for the inflation side.
- **Branch:** not fixed — borrowing the UK's/Denmark's CPI for the Crown dependencies and the Faroes/Greenland is an approximation for Doug to judge.

### GD-7 · Medium · bug — England, Scotland, Wales and the Faroes say "Not enough data to grade it"
- **Where:** `#guideGrades`; `app.js` `valueScores` (~5710) gets the bare ISO (`priceLevel("GB-ENG")` null).
- **Evidence:** England `— | Not enough data to grade it` beside `Local prices ≈ 91% of the US (UK-wide figure)`, Level 2, weather and 12 months of fares; `/guide/united-kingdom` is `C 60`.
- **Fix (proposed):** `priceLevel(GUIDE_PARENT[iso] || iso)` and `advMap[iso] ?? advMap[ADV_PARENT[iso]]` in valueScores.
- **Branch:** not fixed — owned elsewhere (guide A–F grade row).

### GD-8 · Low · data — Greenland "Schengen 90 days"; Bulgaria and Romania lack "Schengen"
- **Where:** `public/visa.json` GL, BG, RO.
- **Evidence:** Greenland `Visa-free entry · Schengen 90 days.` (Greenland is outside Schengen; the Faroes already read without it); BG/RO `90 days` (full members since 2025-01-01).
- **Fix:** GL "90 days"; BG/RO "Schengen 90 days".
- **Branch:** `review3/after-nov9` 20bf5b7.

### GD-9 · Low · copy — "Your USD in United Kingdom", "Add United Kingdom to my trip", "Plan United Kingdom with AI"
- **Where:** `app.js` renderGuideFx (~2977/3001), renderGuideAI (~7435/7441); `server.py` → `guide_sizers.ai`.
- **Evidence:** UK guide shows those three beside `Things to do in the United Kingdom`; same for the US, UAE, Isle of Man.
- **Fix:** `countryNameInText` / `render_guide.name_in_text` at those sites.
- **Branch:** `review3/after-nov9` b189846.

### GD-10 · Low · data — French Southern Territories offers "Where to stay"
- **Where:** `public/stay-coords.json` "TF".
- **Evidence:** `Where to stay near Kerguelen | Kerguelen | Crozet Islands | Île Amsterdam | Île Saint-Paul | Booking.com | Hostelworld` while its summary says "reachable only by research/supply ship from Réunion" (URLs inspected, not clicked).
- **Fix:** TF dropped from stay-coords.json; `gen_stay_spots.NO_STAYS = {"TF"}` stops a rebuild bringing it back; test_stay_near expects none.
- **Branch:** `review3/after-nov9` dee480f.

### GD-11 · Low · perf — Small Wikimedia originals are hotlinked full size
- **Where:** `app.js` activity thumbs (~9969 `/(\d+)px-/` → `/330px-`), hero (~3939), `pithumbsize=1600` (~3709).
- **Evidence:** an original ≤1600px comes back unscaled with no `/NNNpx-` part, so the 330 rewrite silently does nothing: Cuba loads `…/DJI_0197_crp_wiki.jpg?…thumbnail_unscaled` (1920px) into an 84px slot; Wales thumbs `Snowdon_massif.jpg?…thumbnail_unscaled` hit `429 … use thumbnail images in sizes listed on https://w.wiki/GHai`.
- **Fix:** build a proper `/thumb/…/<W>px-<name>` with W a standard step strictly narrower than the original (330 for activities, 1280/960 for the hero); originals narrower than the step stay as they are; the chosen photo is unchanged.
- **Branch:** `main` 3deae86.

### GD-12 · Low · data — Iceland's "Northern lights" thumbnail is a photo from Alaska
- **Where:** `/guide/iceland` `#actDetail`; `public/activities.json` IS `p:"Aurora"`.
- **Evidence:** `img.actthumb` src `…/Aurora_borealis_over_Eielson_Air_Force_Base%2C_Alaska.jpg/330px-…`.
- **Fix:** pinned `File:Aurora Borealis over Jökulsárlón ice beach (16283783717).jpg` (CC BY-SA 2.0); `gen_stay_spots._subjects` skips File: subjects; `/guide/iceland` byte-identical (render_guide doesn't read `p`).
- **Branch:** `main` ca56abb.

### GD-14 · Low · copy/data — Antarctica's "Best time": hyphen minus signs and best months from all-zero scores
- **Where:** `#bestDetail`; `app.js` `fmtTemp` (~4152); `public/climate.json` AQ.
- **Evidence:** `3° Jan · -4° Feb · -11° Mar` with U+002D (also any sub-zero guide: Mongolia, Greenland, Canada); AQ `scores` all 0 yet `best` [1,2,3], inland temperatures.
- **Fix (proposed):** fmtTemp prints U+2212; build_climate sets no `best` on a tie, or curates Antarctica (Nov–Mar, Peninsula).
- **Branch:** not fixed — owned elsewhere (Best time section, climate.json).

### Dropped by the skeptic pass
- GD-13 (server's dated price vs hydrated price differ by 1 point, e.g. Iceland 126 vs 125): transient snapshot-vs-live drift by design.
- GD-15 (empty hero collapses ~240px, CLS ~0.156 at 390): seen only because Wikipedia 429s this VM; not confirmed for real visitors.

---

## 3. Data tabs

Checked clean: the dollar-strength chart starts 4 Jan 1999, the cost chart 1990; numbers match production JSON; Flights bands Low ≤ Typical ≤ High and labelled from the US; every safety statement credited (US/CA/DE, ECDC/CDC); U+2212 everywhere; nominal figures are labelled "before inflation"/"Nominal"; no console errors; keyboard-operable.

### DT-1 · Medium · consistency — Currency map's "biggest gains" lists three Level 4 countries and ignores the higher-risk filter
- **Where:** `/?tab=data&dm=currency` `.mappicksrow[data-for="map"]`; `app.js` renderMap `gains` (~1766), `setShowRisky` (~9649).
- **Evidence:** default state: `Your dollar's biggest gains, after inflation 1. Bolivia +33.5% 2. Uganda +17.8% 3. Iran +16.1% 4. Iraq +15.9% …`; UG/IR/IQ are US Level 4 and hidden from the table below; ticking the box leaves the list identical.
- **Fix:** gains skip Level 3–4 unless the box is ticked, and redraw with it.
- **Branch:** `main` 06ec81f (with DT-2, DT-4).

### DT-2 · Low · consistency — Currency summary counts rows the table hides
- **Where:** `#summary`; `app.js` ~714.
- **Evidence:** `"139 currencies · 35 stronger than usual after inflation ⓘ"` above 99 visible rows, 31 green; the Cost of living line counts only visible rows.
- **Fix:** counts the rows shown (99 · 31; 139 · 35 with the box ticked).
- **Branch:** `main` 06ec81f.

### DT-3 · Medium · bug — Flights tab opens on December (two months out) late in the month under "Any time"
- **Where:** `/?tab=data&dm=flights`; `app.js` `flightMonthNum` (~8956).
- **Evidence:** 28 Oct: `travelMonth()=11 flexWindow=11,12,1,2,3,4 flightMonthNum=12`, `"December fares from United States…"`, `Below typical for December 1. Georgia −43% …`, head `DEC FARE`; the served stand-in says `Below typical for November`, Top Picks `Best in Nov`. flexWindow already skipped October (<10 days left), then the after-the-15th rule advanced again.
- **Fix:** the after-the-15th rule counts from the calendar month unless a month was chosen or a row's month is in focus (which also keeps a Top Picks row's own month).
- **Branch:** `main` bc30a48.

### DT-4 · Low · bug — Region "Africa" drops the franc-zone, Cape Verde and Comoros countries
- **Where:** `#curRegion` = Africa; `app.js` ~771 (EUR row tagged Europe only).
- **Evidence:** Senegal, Cameroon etc. absent from the table and gains list under Africa.
- **Fix:** folded currencies keep their countries' regions (`1. CFA Franc BCEAO +4.9% 2. Cape Verde +4.4% 3. Comoros +4.0% …`).
- **Branch:** `main` 06ec81f.

### DT-5 · Low · data — Safety says Bangladesh was lowered to Level 2 "on 5 Oct"; the State Department dated it 30 Jul
- **Where:** Safety tab change column; `/guide/bangladesh`; `fxtracker/advhistory.py` `_since`.
- **Evidence:** live BD `updated 2026-07-30`, `changed 2026-10-05`; the RSS item `Thu, 30 Jul 2026`, already Level 2.
- **Fix (proposed):** when the feed's own `updated` predates the stored previous level's `since`, the stored record was wrong; don't log a change dated today.
- **Branch:** not fixed — the cause is in the stored `advlvl:us` history in Upstash (not reachable from this machine), so which record was wrong can't be established here; also changes guide words.

### DT-6 · Low · data — Flights table "Avg round-trip" equals "Cheapest" from a single cached fare
- **Where:** Flights table; `app.js` table average.
- **Evidence:** Uruguay `$1,021 / $720 / $720` (avg = min, `n=1`) while the curve holds dearer months (also Iceland, Guinea).
- **Fix:** a one-fare route's average includes the route's other monthly fares (each distinct fare once): Uruguay 871; with none it shows "—" with a tip. Routes with ≥2 fares unchanged.
- **Branch:** `main` 9366305.

### DT-7 · Low · bug — Safety view stays "Loading…" forever when advisories fail; error says "advisory"
- **Where:** Safety sub-line, map, governments panel, table.
- **Evidence:** local, `/api/advisories` blocked: four "Loading…" remain; `Could not load advisory: feed unavailable`.
- **Fix:** "Couldn't load" states; the error uses each view's tab name ("Could not load Safety: …").
- **Branch:** `main` af00801.

### DT-8 · Low · consistency — World Bank names "Macao SAR, China", "Micronesia, Fed. Sts." in the Data tabs
- **Where:** `app.js` `NAME_FIX` (~10054).
- **Evidence:** those strings in the Cost of living table; `ppp.json` names.
- **Fix:** `MO: "Macau", FM: "Micronesia"` (mirrored in picks.py). On after-nov9 because a guide's FX tip names MO for a reader whose home currency is the pataca.
- **Branch:** `review3/after-nov9` 1938bdc.

---

## 4. List pages

Checked clean: the 12 month pages name the right year everywhere (October–December 2026, January–September 2027) in title, h1, description, og and body, and the hub runs Oct 2026–Sep 2027; /safe-and-cheap recomputes to 33 + 51; /do-not-travel lists all 24 US Level 4s; counts agree with the hub; 206 internal links 200; /privacy matches what the code stores and sends; no overflow at 390.

### LP-1 · High · data — Côte d'Ivoire and Republic of Congo are in the State Department feed, but the site says they're missing
- **Where:** `/cheapest/october`, `/cheapest` "Left out" note; `/guide/cote-d-ivoire`, `/guide/republic-of-the-congo`; Top Picks pills; newsletter gem letters; `fxtracker/advisories.py` `_norm` and `ALIASES`.
- **Evidence:** feed titles `Côte d’Ivoire - Level 2: Exercise Increased Caution`, `Republic of Congo - Level 2: …`; `_norm('Côte d’Ivoire')` → `'cote divoire'` (U+2019 vanishes in the ASCII fold) vs alias `cote d ivoire`; no alias for "republic of congo" or "Naoero" (Nauru). Pages: `Left out: … countries missing from the State Department's feed (this month: Côte d'Ivoire)`; Top Picks pill `US State Dept publishes no advisory here; level per Global Affairs Canada`.
- **Fix:** curly apostrophes fold to a straight one before the ASCII fold; aliases `republic of congo`, `naoero`. The live feed then matches all 214 titles.
- **Branch:** `review3/after-nov9` ccff7ba (the two guides' safety line changes).

### LP-2 · Medium · policy (nominal claim) — /safe-and-cheap shows Turkmenistan's plain exchange-rate move as after inflation
- **Where:** Turkmenistan row `td[data-l="Dollar vs 1-yr avg"]`; `render_lists.py` `real_fx`/`_fx_cell` (~323–343).
- **Evidence:** `+0.0%` under a note "after local and US inflation"; TM has no inflation figure, so the figure is nominal; /dollar-strength marks the same case `0.0%†`.
- **Fix:** `0.0%‡` with a tooltip and the note "‡ No inflation figure for that country: the exchange-rate move alone." (‡ because † already marks official-rate prices on that page).
- **Branch:** `main` 93285eb (with LP-3, LP-8, LP-9).

### LP-3 · Low · consistency — /safe-and-cheap prints hyphen minus and "+0.0%"
- **Where:** `render_lists.py` ~343 `"%+.1f%%"`.
- **Evidence:** `<span class="v">-1.6%</span>` (Vietnam) and 8 more; `grep -c '−'` 0; Turkmenistan `+0.0%`.
- **Fix:** `render_strength.signed_pct` (U+2212, unsigned 0.0%).
- **Branch:** `main` 93285eb.

### LP-4 · Medium · data — /do-not-travel shows "US reasons: —" for Afghanistan
- **Where:** Afghanistan row `td[data-l="US reasons"]`; Safety-tab chips; `advisories.py` risks.
- **Evidence:** row `Afghanistan | Do not travel 20 Feb 2026 | Avoid all travel | Travel warning | —`; the feed item begins `Do not travel<p>due to <b>civil unrest</b>, <b>crime, terrorism</b>, …`; API `risks: []`.
- **Fix:** when the lead naming the country gives no reasons, read the placeless same-level lead; only Afghanistan changes (Mali's feed really has none).
- **Branch:** `main` bced936.

### LP-6 · Low · data — Palestine shows "no rating" for Canada although Canada's "Israel and Palestine" advisory covers it
- **Where:** `/do-not-travel` Palestine row; `advisories.py` `_canadian_advisories` (~135–165).
- **Evidence:** `Palestine | Do not travel | no rating | Travel warning`; Canada's feed `IL {'country-eng': 'Israel and Palestine', 'advisory-state': 2, …}`.
- **Fix (proposed):** emit Canada's own PS item from that advisory, or link it with a regional note.
- **Branch:** not fixed — Canada publishes one level for both and an "avoid all travel" for Gaza inside it; which level Palestine shows is an editorial call (and it changes /guide/palestine).

### LP-8 · Low · copy — Latent "1 countries qualify", "1 of them are", "A further 1 are"
- **Where:** `render_lists.py` ~475–480, 600–627; `render_strength.py` ~493.
- **Evidence:** one-country fixture renders `1 countries qualify today … 1 of them are also at the lowest level`, `1 countries rated do not travel`.
- **Fix:** shared `_plural`; new assertions in test_list_pages.
- **Branch:** `main` 93285eb.

### LP-9 · Low · consistency — /safe-and-cheap phone cards drop the rank
- **Where:** `/safe-and-cheap` at 390px; `render_lists.py` ~457.
- **Evidence:** cards read `🇧🇹 Bhutan ✓ all three agree` (no number) while `/cheapest/october` reads `1. 🇲🇦 Morocco`; `class="rk"` absent.
- **Fix:** `<span class="rk">N.</span>` and a general `.listtable .rk` (hidden from 1024px where # shows). Checked at 390/700/1280.
- **Branch:** `main` 93285eb.

### LP-10 · Low · bug — /privacy's contact address is "[email protected]" without JavaScript (= TE-1)
- **Where:** `/privacy` three mailto links; `render_privacy.py` `_mail()`.
- **Evidence:** `<a href="/cdn-cgi/l/email-protection#1f77…"><span class="__cf_email__" …>[email&#160;protected]</span></a>`; `/cdn-cgi/l/email-protection` → 404; the origin sends a plain mailto (Cloudflare rewrites at the edge).
- **Fix:** wrap in `<!--email_off-->…<!--/email_off-->`; test_privacy asserts it. (Turning off Scrape Shield → Email Address Obfuscation in Cloudflare also works.)
- **Branch:** `main` b0009ae.

### LP-11 ⊂ TE-5, LP-12 ⊂ TE-6.

### Dropped by the skeptic pass
- LP-5 ("Safest Cheap Countries" title/h1 as the site's own safety superlative): Doug's wording in cf881a8, pinned by test_list_pages; the lede states the rule and the source (US Level 1). Doug's decision.
- LP-7 (Poland 51% on /safe-and-cheap vs 50% on /cheapest/may for a few hours after midnight): transient snapshot-vs-live by design.

---

## 5. Newsletter

**Tests:** on `main` `parity.py --all` 0 mismatches (159 countries × 11 fields, every edition; also `--month 1`, `--month 11`), `test_digest_variants` 24/24, `--against 4788fd2` 27/27, `test_send_digest` 40/40; with the newsletter copy (`main` d6b7a4b) `test_digest_variants` 25/25 and `--against 4788fd2` 29/29 (new checks: review 3's pieces each in place, every edition's year against `render_cheapest.year_for`, a gap-filled grade naming its filler), `test_send_digest` 40/40, parity 0. The Nov 1 cron builds the **January 2027** issue: subject `🧭 Where your dollar goes furthest this January`; picks Thailand A, Vietnam A, Dominican Rep. B+, Argentina B+, Philippines B+; gems El Salvador A, Cape Verde A, Côte d'Ivoire A. Every link returned 200; month/year, preheader, /cheapest/january link, "after inflation" wording and the unsubscribe placeholder are right; no Level 3/4 or do-not-travel pick or gem.

### NL-1 · Medium · policy (safety wording) — The email's 🛡️ letters never name a source; a gem's "B" is Canada's level
- **Where:** `fxtracker/newsletter.py` ~530, 550, 564, 691.
- **Evidence:** `grep -c "State Department\|advisory\|Canada"` → 0 in the live render and in the archived December issue; gem line `Côte d'Ivoire — A · 💰 A+ · 🛡️ B · 🌤️ A+ · ✈️ B+` with CI `via: 'ca'` (itself caused by LP-1).
- **Fix:** each 🛡️ grade names whose level it is, as the site's pills do: `🛡️ Safety <b>A</b> per US State Dept`, `🛡️ B per Global Affairs Canada` for a gap Canada fills (`picks.advisory_sources` carries each country's source or `via` into the digest). The live January 2027 render: 6 of 8 grades "per US State Dept", Puerto Rico and Côte d'Ivoire "per Global Affairs Canada".
- **Branch:** `main` d6b7a4b (with NL-3, NL-5; supersedes 63acb48's footer sentence). Goldens regenerated; `digest_snapshot.REVIEW3`, one regex like CHEAP_LINK, strips exactly the changed pieces from both trees for `test_digest_variants --against 4788fd2` and `test_send_digest`, which also require each piece where it belongs.

### NL-2 · Medium · consistency — The email uses the map data's abbreviated names ("Dominican Rep.")
- **Where:** `fxtracker/picks.py` ~426 (name from climate.json).
- **Evidence:** live January issue `<a href="https://wandergrade.com/?tab=guide&gc=DO&vmn=1" …>Dominican Rep.</a> — B+`; 12 such names (Bosnia and Herz., Dem. Rep. Congo, S. Sudan, United States of America…).
- **Fix:** `picks.NAME_FIX` mirrors app.js's NAME_FIX. Goldens unchanged (none of the 12 appear in the frozen months); `--against 4788fd2` 27/27; parity 0.
- **Branch:** `main` c6f725b (MO/FM added with DT-8 on after-nov9).

### NL-3 · Low · bug — `send_digest.py --month N` prints the wrong year
- **Where:** `picks.py` ~524 `year = today.year + (1 if today.month + 2 > 12 else 0)` ignores an explicit month.
- **Evidence:** on 2026-10-03 with `--month 1`: `… January 2026`; on 2026-11-01 with `--month 11`: `November 2027`. The cron passes no `--month`, so sends are right.
- **Fix:** the year is `render_cheapest.year_for(month, today)`, the month's next occurrence as the linked /cheapest/<month> page names it (`--month 1` on 2026-10-03: January 2027, with that year's quote; the default month is unchanged). The fare-key fallback (`month > today.month`, mirroring app.js) is left as is; it differs only for an issue of the current month.
- **Branch:** `main` d6b7a4b.

### NL-5 · Low · copy — "✨ New:" AI callout since July; names two of the four AIs; one straight apostrophe
- **Where:** `newsletter.py` ~514, 655–657.
- **Evidence:** callout since 79101d3 (2026-07-10); "ChatGPT or Claude" vs the button's "ChatGPT, Claude, Grok or Perplexity"; `route's` with U+0027.
- **Fix:** "✨ Open any country’s guide and tap **Plan with AI** for a tailored, month-aware itinerary — ChatGPT, Claude, Grok or Perplexity, your call."; `route’s`.
- **Branch:** `main` d6b7a4b.

### NL-6 · Low · consistency — Archive URL/utm_campaign come from the emoji subject; the archive's unsubscribe link is empty
- **Where:** `newsletter.py` ~160 (no `slug` in the USD `send()` payload).
- **Evidence:** archive `…/archive/u1f9ed-where-your-dollar-goes-furthest-this-6224/`; links carry `utm_campaign=u1f9ed-where-your-dollar-goes-furthest-this-6224`; archived page `<a href="" style="color:#888">unsubscribe</a>`.
- **Fix (proposed):** pass a dated slug ("2027-01-january") to `send()`; disable archiving or accept the dead link.
- **Branch:** not fixed — needs Buttondown's API behaviour confirmed with credentials (none on this machine) and the call-for-call proof updated.

### Dropped
- NL-4 (picks/gems exclude only US Level 3–4, not a Canadian/German do-not-travel): same rule as Top Picks, no current case — the site's rule (Doug's decision).

Not reported: cover photos missing in the local render (Wikimedia 429 to this VM; the archived issue has all 5).

---

## 6. Technical

Checked clean: sitemap 209 URLs, all 200, no redirects/duplicates, lastmods 2026-09-24…2026-10-28; robots.txt; ~60 404/redirect variants (404s are `no-store` + `noindex` with the guide index; percent-encoded and alias guide paths 301 keeping the query); meta/og/twitter on home, 9 shell pages, 5 guides; og.png 1200×630; homepage JSON-LD parses; 0 CSP violations on 17 URLs; 226 internal links 200 (except LP-10); no off-step Wikimedia width in HTML or JSON (only `/1280px-` in og-images.json, `/330px-` and API 1600 in app.js).

### TE-1 — duplicate of LP-10.

### TE-2 · Low · perf/CLS — Homepage is `public, max-age=300` even when its pick rows are stand-ins
- **Where:** `server.py` `/` (~2134) with `_home_sizers`.
- **Evidence:** local, upstream blocked: `/  Cache-Control: public, max-age=300` with the blank `data-for="advMap"` stand-in; guides/list pages go `no-store` in the same state.
- **Branch:** not fixed — owned elsewhere (homepage Top Picks server rendering).

### TE-3 · Low · data — /data stays cacheable when its dataset is down, quoting a hard-coded "176 countries"
- **Where:** `server.py` `/data` (~2188), fallback ~604–610.
- **Evidence:** local, upstream blocked: `/data 200 Cache-Control: public, max-age=300`, body `US$100 buys in 176 countries`, date dropped, while `/data/price-levels.json` → `503 … no-store`.
- **Fix:** `no-store` while nothing has ever been built.
- **Branch:** `main` 970515d (with TE-6).

### TE-4 · Low · bug — /api/fx-trend and /api/watchouts answer an upstream failure with a cacheable empty 200
- **Where:** `server.py` ~2080–2090; `watchouts.py` ~2105–2110.
- **Evidence:** local, upstream blocked: `/api/fx-trend?cur=EUR 200 public, max-age=300 {"months": []}`, `/api/watchouts?iso=fr 200 public, max-age=300 {"watchouts": [], …}`.
- **Fix:** same status and body, `Cache-Control: no-store` on failure (`watchouts.lookup` returns the failed flag); genuine empties stay cacheable.
- **Branch:** `main` ae511ce.

### TE-5 · Low · security — CSP allows framing Stay22 though nothing embeds anything (⊃ LP-11)
- **Where:** `server.py` ~100–116.
- **Evidence:** `frame-src https://www.stay22.com https://stay22.com`; no iframe/object/embed anywhere; no embedded Stay22 map is Doug's decision.
- **Fix:** `frame-src 'none'; object-src 'none'` (img-src/connect-src left as they are).
- **Branch:** `main` ef51bf5.

### TE-6 · Low · SEO — URL normalisation gaps (⊃ LP-12)
- **Where:** `server.py` routing.
- **Evidence:** `/cheapest/January`, `/Cheapest`, `/Safe-and-cheap` → 404 while `/guide/Poland` → 301; `/data/` 200; `/og.png/`, `/app.js/`, `/robots.txt/` 200.
- **Fix:** capitalised list/cheapest/dollar-strength/privacy/data paths 301 in one hop to lowercase (query kept); `/data/` 301; a static path ending in "/" is 404. /guide/ untouched.
- **Branch:** `main` 970515d.

### TE-7 · Low · policy — Class/id names starting with `adv` (= AX-10)
- **Where:** `guide_sizers.py` (`advbadge`, `advlvl1–4`, `advwhy`, `advlinks` in every guide's HTML), 21 `.adv*` selectors in styles.css, ids `advFilter`, `advMap`, `advRows`, `advTable`, … in index.html/app.js.
- **Evidence:** `/guide/france` `<span class="advbadge advlvl2">🛡️ Level 2 …`; none currently matched by EasyList generic rules (checked), so latent. Predates the rule (b035bd3, 2026-06).
- **Fix (proposed):** one mechanical rename to a neutral prefix (e.g. `sfty…`) and extend the FORBIDDEN check to the homepage and a guide.
- **Branch:** not fixed — `advMap`/`data-for="advMap"` and the Top Picks rows are in the other session's homepage server-rendering work; rename after both land, after 2026-11-09.

### TE-8 · Low · SEO — /llms.txt leaves out /data and its CSV/JSON
- **Branch:** not fixed — owned elsewhere (`fxtracker/llms_txt.py`).

---

## 7. Accessibility and mobile

Covered at 390×844 and 1280×900, light and dark: Top Picks, each Data tab, Trip, Wander List, guides japan/syria/guernsey (+ 8 more for AX-1), /safe-and-cheap, /cheapest/november, /dollar-strength, /privacy. Clean: no horizontal overflow anywhere (also with every details open); focus visible on every stop (70 home, 75 guide); subscribe modal and map full screen trap and return focus; charts `role=img` with data labels; all images have alt; `lang="en"`; one h1 per page.

### AX-1 · Medium · a11y — Guide "Your USD in X" figure fails contrast (hard-coded colours)
- **Where:** `.guidefx .fxhead > b[style]`; `app.js` ~2974/3002.
- **Evidence:** light `fg=47,158,68 bg=255,255,255 ratio=3.45` (green), `136,145,160 … 3.18` (grey), Turkey `217,72,15 … 4.30`; dark orange `3.86`. 12.5px bold needs 4.5.
- **Fix:** `.pos/.neg/.flat` classes on theme tokens (≥5.28:1 light, ≥6.55:1 dark measured); sparkline keeps its hex; words unchanged.
- **Branch:** `main` 6a218df.

### AX-2 · Medium · a11y — Top Picks filter selects have no accessible name
- **Where:** `select#safeFloor`, `#beenFilter`, `#pickCount` (index.html ~225–249).
- **Evidence:** accessibility tree `#safeFloor role=combobox name="" nameFrom=` (same for the other two).
- **Fix:** each caption gets an id and its select `aria-labelledby` (checked in Chrome: "🛡️ Safety at least / Been-to / Show").
- **Branch:** `review3/after-nov9` 0f9adaa (template).

### AX-3 · Medium · a11y — Photo lightbox is `aria-modal` but Tab walks into the page behind it
- **Where:** `#lightbox`; `app.js` ~3947–4035.
- **Evidence:** after Enter on a hero: `BUTTON.lbnav prev | BUTTON.lbnav next | A "Wikimedia Commons" inDialog=true | BODY | A.homelink inDialog=false | BUTTON#installBtn inDialog=false …` while still open.
- **Fix:** the rest of the page is inert while open (as map full screen does), restored before focus returns to the opener.
- **Branch:** `main` bd789ad (with AX-4).

### AX-4 · Medium · a11y — ⓘ tooltips vanish when the pointer moves onto them (WCAG 1.4.13)
- **Where:** `#wgtip` (`styles.css` ~1526 `pointer-events:none`), `app.js` ~13056–13140.
- **Evidence:** hover `#valueMapSub` → shown; pointer moved to the tip's centre → `hidden=true`.
- **Fix:** the tip takes the pointer and stays while hovered, with a 300ms grace across the gap; row hovers and focus behaviour unchanged.
- **Branch:** `main` bd789ad.

### AX-5 · Medium · consistency — Section headings render at weight 700, not Plus Jakarta Sans 800
- **Where:** `styles.css` ~560, 628, 1489, 2914, no global h2/h3 rule; e.g. `h2#valueMapTitle`, `#mapH2`, `#guideH1`, `h3.staytitle`.
- **Evidence:** computed `font-weight: 700` at both widths, both themes; list pages and the homepage h1 are 800.
- **Fix:** `h2, h3 { font-weight: 800 }` and the card/stay/full-screen headings at 800; cls.mjs at 390 unchanged on the homepage and 7 guides; every held block still matches. "Best time to visit" (owned elsewhere) kept at 700, stand-in and real h2 alike, so its holds don't move.
- **Branch:** `main` c0dea00 + dd92140.

### AX-6 · Low · a11y — Newsletter email field labelled only by its placeholder (2.43:1 in dark)
- **Where:** `form.subform input[type=email]` (app.js ~10974/10987), `styles.css` ~953.
- **Evidence:** `role=textbox name="you@email.com" nameFrom=placeholder`; dark `ph=rgb(117,117,117) bg=rgb(59,59,59)` = 2.43:1.
- **Fix:** `aria-label="Email address"`, themed input background/colour, global `::placeholder` on `--gray` (5.74:1 light, 6.55:1 dark). (The sign-in form's input has the same pattern; untouched.)
- **Branch:** `main` 4d07060.

### AX-7 · Low · a11y — No `<main>`, no skip link, unnamed navs; 12 Tab stops before content
- **Where:** `index.html` (app shell and guides).
- **Evidence:** `main:0 nav:3 header:1 footer:1` on home, tabs and guides; no skip link; `#tabs` and `.guideindex-links` unnamed.
- **Fix:** "Skip to content" link (off-screen until focused), `<main id="main">` around the five tabs (each keeps its positioning), `aria-label`s on both navs. Chrome: first Tab lands on the skip link at top 8px; no overflow; no console errors.
- **Branch:** `review3/after-nov9` 0f9adaa (template).

### AX-8 · Low · a11y — "Browse all 190 country guides" links fail target spacing at 390px
- **Where:** `nav.guideindex-links > a` (`styles.css` ~2372 `gap: 4px 14px`).
- **Evidence:** 18px-tall links, row tops 1986/2008/2030 (22px apart, under 24).
- **Fix:** row gap 8px (26px apart); collapsed by default, no shift.
- **Branch:** `main` 3207222.

### AX-9 · Low · a11y — Primary controls below 44×44 at 390px (all pass 24×24 AA)
- **Evidence:** tabs 30–78×34, header icon buttons 35×33, map controls 32×32.
- **Branch:** not fixed — they meet WCAG 2.2 AA (24×24); 44×44 is AAA and would grow the header (layout shift risk). Optional.

### AX-10 — duplicate of TE-7.

---

## Verification

- **Guide byte-diff (`review3/fixes` vs a1c6d84, the `main` it was cut from):** both servers `FX_PUBLIC=1`, 30 s start, every `/guide/` URL in `/sitemap.xml` fetched once to warm and again to compare, `?v=` stripped, a mismatch re-fetched up to three times. **Result: 190 of 190 identical.** Across three full runs one guide per run (Austria, Greece, Trinidad and Tobago) first differed only by the Safety stand-in that Canada's feed fills, missing on whichever server's fetch through this machine's proxy had just failed (`ws_closed_mid_exchange` to data.international.gc.ca); each was byte-identical once both servers were warm.
- Fare-dependent guide markup (`_fare_strip_hint`, `_fare_col_hints`, fare lines) is invisible to that diff (no fare token here); no fix touched it.
- **Tests:** every `scripts/test_*.py` passes on a1c6d84, `review3/fixes`, `review3/newsletter` (= `main`'s tree but for 30c9071 and the Instagram scripts) and `review3/after-nov9` rebased onto `main` (test_accounts with `scripts/mock_upstash.py`); `parity.py --all` 0 mismatches on all; `test_digest_variants --against 4788fd2` 27/27 on a1c6d84 and `review3/fixes`, 29/29 with the newsletter copy; `test_send_digest` 40/40 throughout.
- **Could not run / observe:** production layout shift of the photo strip (Wikipedia/Wikimedia 429 this VM); Buttondown (no credentials); Upstash-stored advisory history (DT-5); fares locally (no Travelpayouts token).
