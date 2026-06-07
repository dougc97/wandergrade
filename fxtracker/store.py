"""Tiny JSON-file persistence with atomic writes. No dependencies."""

import json
import os
import tempfile

# Project root is the parent of this package directory.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(ROOT, "config.json")
STATE_PATH = os.path.join(ROOT, "state.json")

# Sensible defaults so the app runs before the user touches anything.
DEFAULT_CONFIG = {
    # Currencies to watch for alerts. Empty list = watch every available currency.
    "watch": [],
    # How many days of history to average for the "normal" baseline.
    "baseline_days": 365,
    # USD must be this many percent stronger than its baseline to count as favorable.
    "threshold_pct": 2.0,
    # Don't re-alert the same currency more often than this. ~30 days = monthly,
    # so a currency that stays favorable won't re-alert until next month.
    "alert_cooldown_hours": 720,
    # Email delivery. Password is read from the FX_SMTP_PASSWORD env var if blank here.
    "email": {
        "enabled": False,
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 587,
        "username": "",
        "password": "",
        "from_addr": "",
        "to_addr": "",
    },
}


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return default


def save_json(path, data):
    """Atomic write: dump to a temp file in the same dir, then rename over the target."""
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _merge_defaults(cfg, defaults):
    """Fill in any keys missing from a loaded config (handles upgrades gracefully)."""
    out = dict(defaults)
    for k, v in (cfg or {}).items():
        if isinstance(v, dict) and isinstance(defaults.get(k), dict):
            out[k] = _merge_defaults(v, defaults[k])
        else:
            out[k] = v
    return out


def load_config():
    return _merge_defaults(load_json(CONFIG_PATH, {}), DEFAULT_CONFIG)


def save_config(cfg):
    save_json(CONFIG_PATH, cfg)


def load_state():
    return load_json(STATE_PATH, {"last_alerts": {}})


def save_state(state):
    save_json(STATE_PATH, state)
