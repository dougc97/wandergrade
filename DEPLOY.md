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
