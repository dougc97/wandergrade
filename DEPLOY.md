# Deploying Wandergrade

Goal: the **monthly email alert runs in the cloud** so it fires even when your
Mac is off. The dashboard hosting is optional (do Phase 2 only if you want to
open the page from anywhere).

---

## Phase 1 — Monthly email alerts via GitHub Actions (free, recommended)

This needs no server. GitHub runs `check.py` once a month on a schedule and
emails you a digest of favorable currencies.

### One-time setup

1. **Create a GitHub repo** (private is fine) and push this folder to it:
   ```bash
   cd "fx-tracker"
   git init
   git add .
   git commit -m "fx-tracker"
   git branch -M main
   git remote add origin https://github.com/<you>/fx-tracker.git
   git push -u origin main
   ```
   (`.gitignore` keeps `state.json` and any secrets out of the repo. `config.json`
   *is* committed — it holds your email address and settings, but **not** the
   password.)

2. **Add your email password as an encrypted secret:**
   - In the repo: **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `FX_SMTP_PASSWORD`
   - Value: your Gmail **App Password** (16 chars)
   - This is encrypted by GitHub and never visible in logs.
   - Also add `FX_SMTP_USER` (the sending address) and `FX_ALERT_TO` (where the
     owner alert goes). CI reads SMTP settings from these env vars because the
     committed `config.json` is blank on purpose; without them the owner-alert
     step skips cleanly and the subscriber digest is unaffected.

3. **Turn email on** in `config.json` (kept blank in the repo — fill in locally,
   never commit a real address):
   ```json
   "email": { "enabled": true, "username": "you@example.com",
              "from_addr": "you@example.com", "to_addr": "you@example.com", ... }
   ```

### Test it immediately

- Repo → **Actions** tab → **Monthly USD favorability check** → **Run workflow**.
- It runs `check.py`; if any watched currency is favorable, you get an email.
- The schedule (`.github/workflows/monthly-check.yml`) then fires automatically
  at **13:00 UTC on the 1st of each month**. Change that cron line to retime it.

> Each run uses a fresh machine, so the 24h/30-day cooldown doesn't carry over —
> which is exactly what you want for a monthly digest: one email per month listing
> whatever is currently favorable.

---

## Phase 2 — Host the dashboard (optional)

Only needed if you want to load the web page remotely (not just locally via
`./run.sh`). The app is a single stdlib Python process, so any container host works.

### Render (easiest)

1. Push the repo (Phase 1, step 1).
2. On [render.com](https://render.com): **New → Web Service → connect the repo.**
3. Render detects the `Dockerfile`. Leave defaults; it sets `$PORT` automatically
   (the server already reads it and binds `0.0.0.0`). Optional: set **Health Check
   Path** to `/healthz` (returns 200 without login).
4. **Add a dashboard login** (since the URL is public): in the service's
   **Environment** settings add `FX_DASH_USER` and `FX_DASH_PASSWORD`. When both
   are set the server requires HTTP Basic Auth on every request; when unset
   (local use) it stays open.
   - *Optional:* add `TRAVELPAYOUTS_TOKEN` (free, from travelpayouts.com) to enable
     the Flight prices tab; without it that tab shows a "not configured" note.
5. Deploy → you get a public URL like `https://fx-tracker.onrender.com`.

> Free Render web services sleep after ~15 min idle and take ~30s to wake on the
> next visit — fine for a dashboard you check occasionally.

Fly.io and Railway work the same way from the same `Dockerfile`.

### Dashboard login (built in)

The dashboard supports HTTP Basic Auth, enforced **only when** both
`FX_DASH_USER` and `FX_DASH_PASSWORD` are set:

- **Set them** for any public deploy (Render env vars, or the tunnel below) so the
  URL isn't wide open.
- **Leave them unset** for local use and the dashboard stays open (no login).

The SMTP password is never exposed either way — it's redacted in the API and read
from `FX_SMTP_PASSWORD`.

---

## Temporary public link via Cloudflare tunnel (no account)

For an instant `https://…trycloudflare.com` URL pointing at the dashboard running
on your Mac. Lives only while your Mac + the server + the tunnel run.

```bash
cd "fx-tracker"

# 1) Cloudflare's official tunnel tool (Apple-Silicon build)
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-darwin-arm64.tgz -o cf.tgz
tar -xzf cf.tgz && chmod +x cloudflared && rm cf.tgz

# 2) Choose a dashboard login
export FX_DASH_USER="doug"
export FX_DASH_PASSWORD="pick-a-password"

# 3) Start the dashboard (with login) in the background
python3 server.py 8000 &

# 4) Open the tunnel — it prints your public https URL
./cloudflared tunnel --url http://localhost:8000
```

Open the printed URL, log in with the user/password from step 2. Press Ctrl+C in
the tunnel window to take it offline. (`cloudflared`/`cf.tgz` are gitignored.)

---

## What runs where

| Piece            | Where                | Always-on? | Cost |
|------------------|----------------------|------------|------|
| Monthly email    | GitHub Actions cron  | ✅ yes     | free |
| Dashboard (opt.) | Render/Fly/Railway   | ✅ yes*    | free tier |
| Local dashboard  | your Mac (`./run.sh`)| only when running | free |

\* free web tiers sleep when idle and wake on request.

## Guide snapshot: refreshes itself daily (manual rebuild is the fallback)

Every guide's title, meta description, FAQ answers and server-rendered 💰/🛡️
lines quote two dated figures — the price level vs the US and the advisory
level ("As of Oct 2026") — from one document, served at `/guide-facts.json`.
The server keeps it current itself (`fxtracker/guide_facts.py`):

- **Daily recompute.** On Render (or locally with `GUIDE_FACTS_REFRESH=1`;
  `GUIDE_FACTS_REFRESH_DELAY` sets the first check, default 120 s after boot) a
  background thread checks every 6 h and, once a UTC day, recomputes the
  document from the server's own cached rates and advisories (what
  `/api/rates` and `/api/advisories` serve — in-process, never over HTTP) and
  the PPP table `/ppp.json` serves. It is stored in Upstash
  (`guidefacts:doc`, tagged with a hash of the code and content that make its
  strings), so a restart serves it at once. Log lines start `[guide-facts]`.
- **Previous copy kept** when an input failed (a rates 429 with nothing
  cached), is the cache's stale copy, is dated before the served copy, or
  looks truncated (under 75% of guides with a price figure or 90% with an
  advisory, or more than 3 guides losing one); it retries hourly.
- **Lastmods.** Each guide's sitemap `<lastmod>` is the day its own entry last
  changed (a figure, level, title or description) — a month boundary changes
  every "As of" and so re-dates the guides that print one. `/` and `/data`
  keep `public/content-stamp.txt`.
- **Edge cache.** Guide HTML is edge-cached 5 min, `/guide-facts.json` 10 min
  in browsers: a recompute shows within that.

**Fallback (rare): rebuild the committed copy.** `public/guide-facts.json` is
what a fresh deploy serves until its first check, what any deploy that changes
the title rules or content serves until then (a stored copy from other code is
ignored), and what a server whose inputs stay down keeps serving. Past 90
days its figures drop out, so `scripts/test_guide_meta.py` fails once it is 75
days old (and notes it from day 46). Rebuild it then, or if the logs show
`[guide-facts] … keeping the copy` for days:

```bash
/usr/bin/python3 scripts/parity/parity.py --refresh   # GET-only: production /api fixtures
/usr/bin/python3 scripts/build_guide_facts.py         # same compute as the server, on the fixtures
/usr/bin/python3 scripts/test_guide_meta.py           # lengths, lockstep, attribution, fallback age
```

Commit `public/guide-facts.json` and `scripts/parity/fixture_*.json`, deploy.
