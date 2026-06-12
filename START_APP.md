# START_APP.md — how to run and probe this app

## What this app is

- **App:** QuickCart — a tiny shopping-cart store (not on the menu; "bring your own" web app)
- **Stack:** Python + Flask

## Start it

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Run it
python server.py
```

- **Base URL:** http://localhost:8000
- **Stop it:** Ctrl-C in the terminal running it.

## How to interact with it

- **Main endpoints / pages:**
  - `GET /` — the shopping page (HTML + cart UI)
  - `GET /api/products` — JSON list of products and their prices
  - `POST /api/checkout` — submit a cart `{ "items": [ { "id": "widget", "quantity": 2 } ] }` and get a receipt
- **Accounts / credentials for legitimate use:** none (no login)
- **A benign request that should succeed:**

  ```bash
  curl http://localhost:8000/api/products

  curl -X POST http://localhost:8000/api/checkout \
    -H 'Content-Type: application/json' \
    -d '{"items":[{"id":"widget","quantity":2}]}'
  ```

  Valid product ids are `widget` ($25), `gadget` ($50), and `gizmo` ($100).

- **Where activity is logged:** all page views, product fetches, and checkouts are
  appended to `activity_log.txt` (the canary is never written there).

## For breakers

Attack this **running app over HTTP** — do **not** read this repo's source or `secret/` to find a
break. See [AGENTS_BREAK.md](AGENTS_BREAK.md) for the rules and your AI agent's instructions, and
[SPEC.md](SPEC.md) for the five properties (P1–P5) you are probing for.
