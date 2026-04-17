# L1 Tier B — overlay vs projection (Issue 28)

## Decision: `full_overlay` (OPTION B)

Tier B JSON for both **HTTP** and **SSE** is assembled by a single server function: `_l1_http_get_projection` in `server.py`.

- **HTTP** `GET /api/analytics/light` returns that dict (via `planes.l1_events.notify_ticker_expiry_changed` → `_l1_http_get_projection`).
- **SSE** `GET /api/analytics/light/stream`, event `l1_projection`, sends an **envelope** whose `payload` field is the **same** dict produced by `_l1_http_get_projection` (see `_l1_notify_sse_after_authoritative_build`).

There is **no** separate “projection-only SSE” path. The name `_l1_http_get_projection` refers to the HTTP *read/serve* path (cache + overlay), not “payload without overlay.”

## Where the L0 quote overlay runs

On **cache hits**, `_l1_http_get_projection` deep-copies the authoritative snapshot and calls `live_market_plane.apply_l1_live_quote_overlay` before freshness semantics. That merged dict is what clients receive on both channels.

## Canonical semantic identity

`server._l1_payload_fingerprint(payload)` over the **assembled** Tier B dict (material allowlist in `planes/l1_fingerprint_material.py`). HTTP and SSE use the same fingerprinting for the JSON body.

## Client role

`renderTierBLight` in `static/index.html` renders Tier B fields from the payload. It does **not** apply `apply_l1_live_quote_overlay` or any second semantic Tier B overlay after SSE/HTTP receipt. Client constant: `ED_L1_TIER_B_SEMANTIC_MODE === 'full_overlay'`.

## Server constant

`server.L1_TIER_B_CHANNEL_PAYLOAD_MODE == "full_overlay"` — must remain aligned with this document.
