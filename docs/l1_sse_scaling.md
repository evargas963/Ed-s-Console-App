> **Classification:** Policy Specification | **Scope:** Technical documentation `docs/l1_sse_scaling.md`.

# L1 light SSE scaling (Issue 31)

This document records **measurement**, **server limits**, and **defined behavior** for multiple simultaneous connections to `GET /api/analytics/light/stream` (multi-tab, multi-scope, reconnect storms). It is not an SSE redesign.

## Browser connection limits (measured)

Browsers enforce a **per-origin concurrent connection** budget (commonly **6** for HTTP/1.1 to the same host). Each `EventSource` uses one connection. Opening more than the budget typically leaves extra connections in `CONNECTING` or delayed until a slot frees — behavior is **browser-defined**, not server-defined.

**How we measure:** run Playwright test `tests/e2e/l1-sse-scaling.spec.js` (navigate to `/` first so `EventSource` is same-origin; the spec does this). The test attaches JSON rows (`l1-sse-scaling-table`) — copy counts into the table below. Results vary by browser and OS.

| Connections | Result (Chromium / Playwright) | Notes |
|---------------|-------------------------------|--------|
| 1 | Open | Baseline |
| 2–6 | Usually open | Fits typical per-host limit |
| 7–10 | Partial open | Expect some `CONNECTING` / stalled until another tab closes |

**Server implication:** even if the server allows more connections, the **UI may not open more than ~6** streams to the same origin until HTTP/2/multiplexing or multiple hostnames are used. That is expected and separate from server caps.

## Server behavior under load

- **Fanout:** One authoritative L1 envelope is copied to each subscribed connection’s asyncio queue (see `_l1_light_sse_dispatch_loop`). Per-queue order is FIFO; under saturation, oldest events may be dropped in favor of the latest projection (documented backpressure).
- **Reconnect storm:** The client uses **`_l1LightReconnectDelayMs`** — exponential backoff with **random jitter** (cap 30s) before reconnecting L1 light SSE. This limits synchronized reconnects after network loss or server restart.
- **Diagnostics:** `GET /api/diagnostics/l1` → `ed_l1.l1_sse_light` includes:
  - `l1_light_sse_connections` — current L1 light SSE connections
  - `l1_light_sse_connections_peak` — peak since process start
  - `l1_light_sse_connections_by_scope` — counts keyed as `TICKER|expiry_key`
  - `l1_light_sse_duplicate_scope_same_client_warn_total` — same coarse client key + scope connected more than once (e.g. duplicate tab)
  - `l1_light_sse_rejected_total` — new connections rejected due to caps
  - `l1_light_sse_limit_max_total` / `l1_light_sse_limit_max_per_scope` — policy constants

**Coarse client key:** `X-Forwarded-For` first hop, else `request.client.host`. Not an authenticated identity.

## Hard limits (defined behavior)

Issue 31 names (conceptual) map to these module-level constants in `server.py`:

| Issue 31 name | Code constant | Value |
|---------------|----------------|-------|
| `MAX_SSE_CONNECTIONS_TOTAL` | `MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL` | `64` |
| `MAX_SSE_CONNECTIONS_PER_SCOPE` | `MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE` | `8` |

| Symbol | Value | Meaning |
|--------|-------|---------|
| `MAX_L1_LIGHT_SSE_CONNECTIONS_TOTAL` | `64` | Max simultaneous L1 light SSE connections process-wide |
| `MAX_L1_LIGHT_SSE_CONNECTIONS_PER_SCOPE` | `8` | Max connections per `(ticker, expiry_key)` scope |

When a limit is exceeded, the server responds with **HTTP 503** and a short `detail` string, increments `l1_light_sse_rejected_total`, and logs a warning. **Existing connections are not force-closed** (simple policy).

**Safe envelope (server):** Correctness and stability remain defined for up to **64** concurrent L1 light SSE connections and **8** per scope, bounded by the fanout and queue policies already in `server.py`. Beyond that, **new** connections are **rejected** rather than leaving the system in an undefined state.

**Combined with browser limits:** Effective concurrent streams per origin are often **~6** on the client; server caps apply when using many clients, tools, or multiple origins.

## Safety tests

`tests/test_l1_sse_scaling_safety.py` covers:

- Per-queue ordering and monotonic `l1_generation` under fanout
- Identical payload material for duplicate scope connections for the same event
- Global and per-scope cap behavior (via `_l1_light_sse_try_reserve` / `_l1_light_sse_release`)
- Light fanout micro-benchmark (1 / 5 / 10 subscribers)

## Known constraints

- **Playwright / TestClient:** Holding multiple open SSE streams in a single `TestClient` can deadlock; cap tests call the reserve/release helpers directly (see tests).
- **Fanout cost:** Characterization is best-effort (micro-benchmark + diagnostics). No SLA on broadcast latency.
- **Reconnect storm CPU:** Mitigated by client backoff + jitter; server-side observe via diagnostics and process metrics outside this doc.

## Conclusion

- **Browser:** Expect **~6** concurrent `EventSource` connections per origin on typical Chromium; measure with `l1-sse-scaling.spec.js`.
- **Server:** Up to **64** total / **8** per scope are **safe and defined**; additional connects get **503** and counters/logs, not undefined behavior.
