# 💵 USD Strength Tracker

Tracks the US dollar against world currencies and emails you when the dollar is
**favorable for travel** — i.e. stronger than its own recent average for a given
country's currency.

- **World heatmap** — a choropleth map coloring each country by how strong the
  dollar is against its currency (green = strong, red = weak), with hover detail.
- **Overall strength chart** — an equal-weighted USD index over time, with a
  3M / 6M / 1Y / 2Y window toggle.
- **Per-currency table** — every currency, how strong the dollar is vs its
  baseline average, and where today sits in the recent range.
- **Scheduled alerts** — a monthly job that checks rates and emails you a digest
  when watched currencies become favorable.

No build step, no `pip install`. Pure Python standard library (Python 3.9+).
FX data comes from the European Central Bank via the free, key-less
[Frankfurter](https://frankfurter.dev) API.

---

## Quick start

```bash
cd "fx-tracker"
./run.sh            # or: python3 server.py
```

Open **http://localhost:8000**. Click **Settings** to set your watchlist,
threshold, and email — then **Save settings**.

To test alerts without the dashboard:

```bash
python3 check.py --dry-run   # prints what it would alert, sends nothing
python3 check.py             # actually sends email (if configured)
```

---

## How "favorable" is decided

For each currency the app expresses the rate as **units of foreign currency per
1 USD**, so a higher number means a stronger dollar.

- **Baseline** = the average rate over the last *N* days (default 365).
- **Strength** = how far today's rate is above that baseline, in percent.
- A currency is **favorable** when strength ≥ your **threshold** (default +2%).
- **Range position** shows where today sits between the window's low and high
  (100th percentile = dollar at its strongest in the window).

Tune `baseline_days` and `threshold_pct` in Settings (or `config.json`).

---

## Email setup (Gmail example)

1. Enable 2-Step Verification on your Google account.
2. Create an **App Password** (Google Account → Security → App passwords). It's a
   16-character code — use it, *not* your normal password.
3. In **Settings**, enable email and fill in:
   - SMTP host `smtp.gmail.com`, port `587`
   - Username / From / To = your Gmail address
   - Password = the app password
4. Save, then click **Check & email now** to send a test (only sends if any
   watched currency is currently favorable).

**Keeping the password out of the file:** leave the password field blank and set
an environment variable instead:

```bash
export FX_SMTP_PASSWORD="your-app-password"
python3 check.py
```

Any SMTP provider that supports STARTTLS works (Fastmail, Outlook, etc.) — just
change host/port.

---

## Scheduling monthly checks

Alerts are set up to fire **once a month** — good cadence for trip planning. The
`alert_cooldown_hours` default (720h ≈ 30 days) also guarantees a currency that
stays favorable won't email you twice in the same month.

### Option A — cron

```bash
crontab -e
```

Add (runs on the **1st of every month** at 9:00 AM; adjust the path):

```
0 9 1 * *  cd "/Users/doug/Desktop/Claude Workspace/fx-tracker" && FX_SMTP_PASSWORD="your-app-password" /usr/bin/python3 check.py >> check.log 2>&1
```

### Option B — macOS launchd

Create `~/Library/LaunchAgents/com.fxtracker.check.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.fxtracker.check</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/Users/doug/Desktop/Claude Workspace/fx-tracker/check.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/doug/Desktop/Claude Workspace/fx-tracker</string>
  <key>EnvironmentVariables</key><dict><key>FX_SMTP_PASSWORD</key><string>your-app-password</string></dict>
  <key>StartCalendarInterval</key><dict><key>Day</key><integer>1</integer><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>StandardOutPath</key><string>/tmp/fxtracker.log</string>
  <key>StandardErrorPath</key><string>/tmp/fxtracker.err</string>
</dict></plist>
```

Then: `launchctl load ~/Library/LaunchAgents/com.fxtracker.check.plist`

The **alert cooldown** (default 720h ≈ 30 days) prevents the same currency from
emailing you more than once a month.

---

## Files

```
fx-tracker/
├── server.py            # web dashboard + JSON API (stdlib http.server)
├── check.py             # scheduled alert job
├── config.json          # your settings (created/edited via the dashboard)
├── state.json           # last-alert timestamps (auto-created)
├── run.sh               # convenience launcher
├── fxtracker/
│   ├── rates.py         # fetch rates + score favorability
│   ├── mailer.py        # SMTP email + alert formatting
│   └── store.py         # JSON config/state persistence
└── public/
    ├── index.html / app.js / styles.css   # dashboard front-end
    └── world.geojson    # slimmed Natural Earth country shapes (for the heatmap)
```

The heatmap uses an equirectangular SVG projection drawn from `world.geojson`
(Natural Earth 110m, public domain) — no mapping library. The currency→country
mapping lives in `CUR_BY_ISO` in `public/app.js`.

---

## Notes & limitations

- **Coverage:** Frankfurter exposes ~29 major currencies (the ECB reference set).
  These cover essentially every common travel destination (Europe, UK, Japan,
  Mexico, Thailand, India, etc.). To track *all* ~150 world currencies, swap in a
  keyed provider — the only network code lives in `fxtracker/rates.py`
  (`fetch_json` and the three `get_*` helpers); the rest is provider-agnostic.
- **Not financial advice.** Mid-market reference rates differ from what your bank
  or card charges. Confirm before booking.
- **macOS certs:** python.org's Python sometimes lacks CA certs; `rates.py`
  auto-finds a bundle (env `SSL_CERT_FILE`, `certifi`, or the system store) with
  verification left on.
```
