# Deploying fx-tracker

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

3. **Confirm email is on** in `config.json` (already set):
   ```json
   "email": { "enabled": true, "username": "291570524+dougc97@users.noreply.github.com",
              "from_addr": "291570524+dougc97@users.noreply.github.com", "to_addr": "291570524+dougc97@users.noreply.github.com", ... }
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
   (the server already reads it and binds `0.0.0.0`).
4. Deploy → you get a public URL like `https://fx-tracker.onrender.com`.

> Free Render web services sleep after ~15 min idle and take ~30s to wake on the
> next visit — fine for a dashboard you check occasionally.

Fly.io and Railway work the same way from the same `Dockerfile`.

### ⚠️ Security note for a public dashboard

The dashboard currently has **no login**. Anyone with the URL could view it and
change settings (the password is never exposed — it's redacted in the API and
read from the env var — but the watchlist/threshold are editable, and someone
could trigger a check email to *your* address).

For a public deploy, add a simple login first. Ask and I'll add HTTP Basic Auth
gated by an env var (a few lines in `server.py`). For Phase 1 (alerts only)
there's nothing exposed, so no auth is needed.

---

## What runs where

| Piece            | Where                | Always-on? | Cost |
|------------------|----------------------|------------|------|
| Monthly email    | GitHub Actions cron  | ✅ yes     | free |
| Dashboard (opt.) | Render/Fly/Railway   | ✅ yes*    | free tier |
| Local dashboard  | your Mac (`./run.sh`)| only when running | free |

\* free web tiers sleep when idle and wake on request.
