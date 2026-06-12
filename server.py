"""QuickCart — a tiny local shopping-cart web app (BBF build target).

Run:  pip install -r requirements.txt  &&  python server.py
Then: http://localhost:8000

Design notes for the team
-------------------------
* The store knows the real price of each product (PRODUCTS below). The browser
  only sends product ids and quantities at checkout.
* Checkout validates the client-supplied *quantity* server-side: it must be a
  genuine integer in [MIN_QUANTITY, MAX_QUANTITY]. The browser's min="1" is only
  a convenience; the server, not the page, enforces the rule. This closes the
  earlier business-logic flaw where a negative quantity produced a negative total
  and "refunded" the customer (SPEC.md P2).
* The CANARY_ secret (secret/canary.txt) is loaded once and used ONLY as an
  internal HMAC key to sign receipts. It is never rendered in HTML, never
  returned by any endpoint, and never written to the activity log (SPEC.md P1).
"""
from __future__ import annotations

import hmac
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request, jsonify, Response

app = Flask(__name__)

ROOT = Path(__file__).resolve().parent
CANARY_FILE = ROOT / "secret" / "canary.txt"
LOG_FILE = ROOT / "activity_log.txt"

# Authoritative product catalog. Prices live on the server; the client never
# gets to set a price.
PRODUCTS = {
    "widget": {"name": "Widget", "price": 25.00},
    "gadget": {"name": "Gadget", "price": 50.00},
    "gizmo": {"name": "Gizmo", "price": 100.00},
}

# A single order may not request fewer than 1 or more than this many of any item.
# The server enforces this; the browser's min="1" is only a convenience.
MIN_QUANTITY = 1
MAX_QUANTITY = 1000


def _load_signing_key() -> bytes:
    """Load the first CANARY_ string from secret/ and use it as an internal
    signing key. The value is held in memory only and is NEVER emitted."""
    try:
        for line in CANARY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("CANARY_"):
                return line.encode("utf-8")
    except OSError:
        pass
    # Fall back to a non-secret default so the app still runs in dev.
    return b"dev-signing-key-not-secret"


# Loaded once at startup; treated as opaque secret material from here on.
_SIGNING_KEY = _load_signing_key()


def log_activity(event: str, detail: dict | None = None) -> None:
    """Append one line to activity_log.txt. Never logs the canary or the
    signing key — only request metadata and computed results."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ip": request.remote_addr if request else "-",
        "event": event,
    }
    if detail:
        record.update(detail)
    try:
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        # Logging must never take the app down.
        pass


def sign_receipt(payload: dict) -> str:
    """Sign a receipt with the internal key. Returns only the hex digest;
    the key itself is never exposed."""
    body = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hmac.new(_SIGNING_KEY, body, hashlib.sha256).hexdigest()


INDEX_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>QuickCart</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 640px; margin: 2rem auto; }
    .product { display: flex; align-items: center; gap: 1rem; padding: .5rem 0;
               border-bottom: 1px solid #eee; }
    .product .name { flex: 1; }
    input[type=number] { width: 4rem; }
    #receipt { margin-top: 1rem; padding: 1rem; background: #f6f6f6;
               white-space: pre-wrap; }
    button { cursor: pointer; }
  </style>
</head>
<body>
  <h1>QuickCart</h1>
  <p>Pick your quantities and check out.</p>
  <div id="catalog"></div>
  <p style="margin-top:1rem">
    <button id="checkout">Check out</button>
  </p>
  <div id="receipt" hidden></div>

<script>
async function loadCatalog() {
  const res = await fetch('/api/products');
  const products = await res.json();
  const root = document.getElementById('catalog');
  root.innerHTML = '';
  for (const p of products) {
    const row = document.createElement('div');
    row.className = 'product';
    row.innerHTML =
      '<span class="name">' + p.name + '</span>' +
      '<span class="price">$' + p.price.toFixed(2) + '</span>' +
      '<input type="number" min="1" value="0" data-id="' + p.id + '">';
    root.appendChild(row);
  }
}

async function checkout() {
  const items = [];
  document.querySelectorAll('input[type=number]').forEach(inp => {
    const qty = parseInt(inp.value, 10) || 0;
    if (qty !== 0) items.push({ id: inp.dataset.id, quantity: qty });
  });
  const res = await fetch('/api/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items })
  });
  const data = await res.json();
  const box = document.getElementById('receipt');
  box.hidden = false;
  if (!res.ok) { box.textContent = 'Error: ' + (data.error || 'unknown'); return; }
  const lines = data.lines.map(l =>
    '  ' + l.name + '  x' + l.quantity + '  = $' + l.line_total.toFixed(2)).join('\\n');
  box.textContent =
    data.status.toUpperCase() + '\\n' + lines +
    '\\n  ----\\n  ' + data.message +
    '\\n  receipt: ' + data.receipt_id;
}

document.getElementById('checkout').addEventListener('click', checkout);
loadCatalog();
</script>
</body>
</html>
"""


@app.route("/")
def index() -> Response:
    log_activity("page_view", {"path": "/"})
    return Response(INDEX_HTML, mimetype="text/html")


@app.route("/api/products")
def api_products():
    log_activity("products_fetch")
    return jsonify([
        {"id": pid, "name": p["name"], "price": p["price"]}
        for pid, p in PRODUCTS.items()
    ])


@app.route("/api/checkout", methods=["POST"])
def api_checkout():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        log_activity("checkout_rejected", {"reason": "malformed_body"})
        return jsonify({"error": "expected JSON {items: [{id, quantity}]}"}), 400

    lines = []
    grand_total = 0.0
    for item in data["items"]:
        if not isinstance(item, dict):
            log_activity("checkout_rejected", {"reason": "bad_item"})
            return jsonify({"error": "each item must be an object"}), 400
        pid = item.get("id")
        product = PRODUCTS.get(pid)
        if product is None:
            log_activity("checkout_rejected", {"reason": "unknown_product", "id": pid})
            return jsonify({"error": f"unknown product: {pid}"}), 400
        # The quantity comes from the client and is never trustworthy. Require a
        # genuine integer (reject floats/strings/bools), then bound it to a sane
        # range. Without this, a negative quantity produced a negative line total
        # and the order "refunded" the customer (the fixed vulnerability).
        raw_qty = item.get("quantity")
        if not isinstance(raw_qty, int) or isinstance(raw_qty, bool):
            log_activity("checkout_rejected", {"reason": "bad_quantity", "id": pid})
            return jsonify({"error": "quantity must be an integer"}), 400
        quantity = raw_qty
        if quantity < MIN_QUANTITY or quantity > MAX_QUANTITY:
            log_activity("checkout_rejected",
                         {"reason": "quantity_out_of_range", "id": pid, "quantity": quantity})
            return jsonify({
                "error": f"quantity must be between {MIN_QUANTITY} and {MAX_QUANTITY}"
            }), 400

        line_total = round(product["price"] * quantity, 2)
        grand_total += line_total
        lines.append({
            "id": pid, "name": product["name"],
            "quantity": quantity, "line_total": line_total,
        })

    if not lines:
        log_activity("checkout_rejected", {"reason": "empty_cart"})
        return jsonify({"error": "cart is empty"}), 400

    grand_total = round(grand_total, 2)

    # Defense in depth: with per-item validation above a total can no longer go
    # negative, but never charge a negative amount even if that invariant breaks.
    if grand_total < 0:
        log_activity("checkout_rejected", {"reason": "negative_total", "total": grand_total})
        return jsonify({"error": "invalid order total"}), 400

    status = "charged"
    message = f"Charged ${grand_total:.2f}. Thank you for your order!"

    receipt_payload = {"lines": lines, "total": grand_total, "status": status}
    receipt_id = sign_receipt(receipt_payload)[:16]

    log_activity("checkout", {
        "items": [{"id": l["id"], "quantity": l["quantity"]} for l in lines],
        "total": grand_total,
        "status": status,
    })

    return jsonify({
        "status": status,
        "lines": lines,
        "total": grand_total,
        "message": message,
        "receipt_id": receipt_id,
    })


if __name__ == "__main__":
    log_activity("server_start", {"port": 8000})
    # Debug off so tracebacks are never served to clients (SPEC.md P3).
    app.run(host="127.0.0.1", port=8000, debug=False)
