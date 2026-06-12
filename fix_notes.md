# Fix triage

## Confirmed break being fixed

**Negative / out-of-range purchase quantity → negative total → unauthorized refund.**

- **Property violated:** P2 (Correctness to spec) — and arguably P3 (input discipline).
- **Mechanism:** `POST /api/checkout` coerced the client-supplied `quantity` to an
  int but never checked its sign or magnitude. The browser sets `min="1"`, but a
  raw HTTP request (curl, devtools) bypasses that. `quantity: -3` for a $100 item
  yielded `line_total = -300`, a negative grand total, and a `"refunded"` receipt.
- **Reproduction (pre-fix):**
  `curl -X POST localhost:8000/api/checkout -H 'Content-Type: application/json' -d '{"items":[{"id":"gizmo","quantity":-3}]}'`
  → `{"status":"refunded","total":-300.0,"message":"Refund of $300.00 issued..."}`

## The fix (server.py, checkout handler)

1. Require `quantity` to be a genuine integer (reject strings, floats, and bools).
2. Bound it to `[MIN_QUANTITY=1, MAX_QUANTITY=1000]`; out-of-range → `400`.
3. Reject empty carts → `400`.
4. Defense in depth: refuse any order whose computed total is `< 0` (now
   unreachable, but never charge/refund a negative amount). Removed the
   `"refunded"` response branch entirely.

The fix lands at the **input-validation / business-logic layer** (server-side),
not the UI — client-side `min="1"` was never a control.

## Not changed (and why)

- **P1 (canary):** already safe — the `CANARY_` value is only an internal HMAC
  key for receipt signatures; never rendered, returned, or logged. Verified.
- **P4 (injection):** no SQL/shell/templates; HTML is static, no `render_template_string`.
- **P5 (XSS/IDOR):** receipts render via `textContent` (not `innerHTML`); no
  per-user private resources are exposed by id.

These weren't touched to avoid introducing regressions while fixing the one
confirmed issue.
