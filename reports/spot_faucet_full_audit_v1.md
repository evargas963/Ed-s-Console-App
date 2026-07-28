# Spot faucet full audit v1 — 2026-07-28 ~10:25 CT

**HEAD:** `90048e5e` (after RC-108–114; quote memo in `6c2bb9d9`)  
**Question:** Where is spot used? Multiple faucets? If there is a fast connection, should everything consume it once?

**Verdict:** **Multiple semantic faucets remain. Vendor double-fetch is FIXED (RC-112 memo). Client read authorities are per-page unified. Display vs math still diverge by design of overlay. Fast lane is the console display authority — not the sole system authority.**

---

## 1. Same-turn mechanical proof

| Check | Result |
|---|---|
| `python -m tools.data_faucet_audit` | **0** faucet violations (server+client) |
| `audit_client()` | **0** |
| pytest memo + client spot faucet | **15 passed** (`test_quote_memo_*` + `test_client_spot_single_faucet_v1`) |
| `_memoized_quote_response` in `_spot_from_quote` | **YES** |
| `_memoized_quote_response` in `_build_rest_fast_quote_payload` | **YES** |
| `merge_into_state` copies `quote_source_detail` | **NO** (plane builds it; merge omits) |
| Chart RC-111 `_gammaSpotDrawn` | **YES** |
| Gamma bars still `fnum((t \|\| {}).spot)` | **YES** (bypass `consoleSpot`) |
| `cv2-hd-px` via `T('cv2-hd-px'` | **3** call sites (multi-writer clock) |

Exact call counts (this turn): `consoleSpot(` **14**, `edLiveSpot(` **4**, `effectiveDisplaySpot(` **4**, `paintSpotDisplays(` **4**, chart `currentSpot(` **7**, server `resolve_spot(` **7**.

---

## 2. Architecture map (live)

```
                    Schwab quote API
                           │
              ┌────────────┴────────────┐
              │  _memoized_quote_response │  ← RC-112 (1s TTL, 200-only)
              │         (ONE vendor read) │
              └────────────┬────────────┘
                 ┌─────────┴─────────┐
                 ▼                   ▼
        resolve_spot()      _build_rest_fast_quote /
        (math /api/spot /     record_from_level_one /
         terrain reprice)     record_quote → live_market_plane
                 │                   │
                 │                   ▼
                 │            SSE /api/fast-quote
                 │                   │
                 │                   ▼
                 │         window._fastLaneSpot
                 │                   │
                 ▼                   ▼
           MATH / walls        consoleSpot() ──► paintSpotDisplays
           (terrain loop,            │              + EdCv2 paint()  ← multi-writer
            analytics)               ▼
                               Chart: /api/spot → liveSpot → currentSpot()
                               (separate page authority; same memo on server)
```

---

## 3. Report corpus re-grade (spot-related only)

Sources: `reports/repo_wide_adversarial_audit_wave1.json`, `wave2.json`, `claude_finish_adversarial_audit_v1`…`v9`, `claude_finish_lock_violations_v7`/`v9`, `reports/locks_violation_audit_v1.json`, `OPEN_ITEMS.md`, `governance/root_cause_log.md` RC-14/15/28/29/75–77/81/102/111/112.

| ID / claim (from reports) | Grade at `90048e5e` | Notes |
|---|---|---|
| **RC-14** single `resolve_spot` | **FIXED** (server math authority) | Still does not *read* the plane |
| **RC-75/76** chart one `currentSpot` | **FIXED** | Alias-proof client audit green |
| **RC-77/81** console `consoleSpot` + one paint tick | **PARTIAL** | Readers unified; **`cv2-hd-px` still multi-writer** (W1-C4) |
| **RC-102** edLiveSpot dual door | **FIXED** (delegate) | PARTIAL row remains for DOM proof of staleness chips |
| **RC-111** chart gamma canvas spot freeze | **FIXED** | `draw()` re-triggers `drawGamma` when spot moves |
| **RC-112 / AUDIT-QUOTE-MEMO-V1** double Schwab fetch | **FIXED** | OPEN_ITEMS `[x]`; memo test green |
| **W1-C2** math spot ≠ display spot | **PARTIAL** | Same **vendor** quote via memo; math still `resolve_spot`, display still plane overlay after compute — numbers can still differ by fallback path / stale overlay |
| **W1-C4** header multi-writer | **OUTSTANDING** | `paintSpotDisplays` + EdCv2 `T('cv2-hd-px'` ×3 |
| **W1-H2** gamma bars raw `t.spot` | **OUTSTANDING** | Live: `fnum((t \|\| {}).spot)` still present |
| **W2-C3** auth carry-forward skips plane | **OUTSTANDING** | `_stale_fast_quote_carried_forward` still returned without always `record_quote` |
| **W2-C4** QSD strip in `merge_into_state` | **OUTSTANDING** | Field list omits `quote_source_detail` |
| **W2-H1** dual quote writers stream vs REST | **OUTSTANDING** (class) | Both feed plane; stomps possible |
| Faucet audit “spot OK / 0 faucets” | **THEATER vs plane** | Declares `resolve_spot` only; **does not count `live_market_plane` as a competing faucet** (known limit since wave1) |
| Client audit green | **TRUE for readers** | Does not prove single **writer clock** or gamma-bar path |

Historical narrative (RC-14→15→28→29→75→77→81→102→111→112): each close fixed a *surface*; the class “one spot everywhere” is still incomplete. That is the recurring SURFACE_NOT_CLASS pattern named in RC-111/112 roots.

---

## 4. Answers to the operator questions

### Do we have multiple faucets for spot?
**Yes — at least three semantic layers:**

1. **Vendor memo** (`_memoized_quote_response`) — one REST read (RC-112)  
2. **Math authority** (`resolve_spot`) — quote memo → stored snapshot → chain close  
3. **Display plane** (`live_market_plane` ← stream + REST fast quote) → console `_fastLaneSpot` → `consoleSpot`  
4. **Chart page authority** (`/api/spot` → `liveSpot` → `currentSpot`) — server uses same memo; **browser path ≠ console SSE**  
5. **Residuals:** gamma bars `t.spot`; radar/stored cold paths; diagnostic `underlyingPrice`

### If we have a fast connection, should it be used everywhere / consume once?
**Consume the vendor once — yes (now mechanized for REST).**  
**Pipe browser `_fastLaneSpot` into GEX math — no.**

Correct law (aligned with RC-112 ROOT + OPEN_ITEMS closure intent):

| Layer | Should use |
|---|---|
| Schwab HTTP quote | **One memo** (done) |
| Console display | **Plane / fast lane only** via `consoleSpot` (mostly done; finish writers + gamma bars) |
| Chart display | Same **server memo** via `/api/spot` today; ideally also join plane/SSE so both pages share one clock |
| Terrain / analytics **math** | `resolve_spot` reading the **same memo** (done for quote leg) — not a window global |
| Auth-degraded / stale flags | Must enter the plane (W2-C3/C4 still open) so “fast” never looks fresher than truth |

So: **one vendor read → many consumers.** Not: **one browser global → all consumers.**

---

## 5. What “finished single-spot” still requires

1. Collapse **`cv2-hd-px` writers** to one clock (W1-C4).  
2. Gamma bars → `consoleSpot(t)` (W1-H2).  
3. Carry auth-degraded quotes into plane + merge `quote_source_detail` (W2-C3/C4).  
4. Optionally unify chart onto console plane/SSE so two pages cannot drift by poll tree.  
5. Teach `data_faucet_audit` that **plane is a declared spot faucet** (or that spot has two declared legs: math vs display) — today’s `[OK] spot 0 faucets` hides the dual path.

---

## 6. Status line

`CLAIM: vendor double-fetch FIXED (RC-112); per-page client readers FIXED; math≠display and multi-writer/QSD/gamma-bar still OUTSTANDING · DONE: full report synthesis + same-turn re-proof · NEXT: W1-C4 + W1-H2 + W2-C3/C4 · BLOCKER: green faucet audit ≠ one spot system`
