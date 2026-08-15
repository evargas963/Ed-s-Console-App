# Claude Finish Adversarial Audit v27 — RC-133 Decide burn

**Target:** `d0fe5912` — RC-133 Decide fail-open pills  
**Claude claim:** 100% Decide safety; LONG/SHORT absent from every card; SESSION_CLOSEOUT_GREEN  
**Auditor:** Cursor, 2026-07-29 (same-turn re-execution)

---

## Verdict: **REJECT 100%** — **PARTIAL ACCEPT** of the named burn

The measured fail-open (per-horizon up/down under `!tradeable`) is **real-fixed and locked**.  
It is **not** end-to-end Decide-10 with zero escapes. Do not treat Decide as 10/10 yet.

| Claim | Result |
|---|---|
| Per-horizon pills: no up/down/glow/LONG text under `!tradeable` | **ACCEPT** |
| Contract helper executed under node + old-shape fire control | **ACCEPT** (32 passed this turn) |
| Legalizing “must not erase horizon direction” sentence gone | **ACCEPT** |
| “LONG/SHORT absent from every card” (absolute) | **REJECT** — escape proven |
| 100% / no patches / Decide dimension = 10 | **REJECT** |

---

## Escape (same-turn MEASURED)

`resolveHorizonCardVisualState` under `tradeable=false`:

| case | state | glow | dirText |
|---|---|---|---|
| `5c` LONG | dim | "" | `—` ✓ |
| `consolidated` LONG | dim | "" | **`LONG`** ✗ |
| `consolidated` SHORT | dim | "" | **`SHORT`** ✗ |

Cause: dirText logic is

```text
(!tradeable && !isConsolidated) ? '—' : (FLAT ? NEUTRAL : dir)
```

So **ALL** under `!tradeable` still prints LONG/SHORT when `dir` is fed that way.

Feed path (index.html ~5645–5649): `operatorMirrorVeto` + `final_bias` LONG/SHORT sets `dir = biasDir` while `tradeable` is false → helper returns dim color but **dirText LONG**.

Tests never covered `consolidated + LONG + !tradeable` (only FLAT). Live probe today had `final_bias=WAIT`, so Claude’s DOM pass could not see this path — **presence-only live proof**.

Also still set under `!tradeable`: `data-tf-signal-dir=long|short` via `sigDir`, and `data-horizon-direction=LONG|SHORT`. Stale CSS comment ~2567 still says keep LONG/SHORT color when stale / non-actionable opinion visible.

---

## What did land (keep)

- Early `if (!tradeable) { state=dim }` — revoke of color fail-open for horizons  
- `dirText` single-writer for pill text on horizons  
- Tags gated `tradeable ? deriveTag : null`  
- Structural locks + old-shape fixture fire control  
- RC-133 row + commit real  

---

## Required to reach 100% (no patches)

1. Under `!tradeable`, **every** slug including `consolidated`: `dirText` ∈ {`—`,`NEUTRAL`,`UNAVAILABLE`,`WAIT`} — never LONG/SHORT.  
2. Under `!tradeable`: `sigDir` / `data-tf-signal-dir` / `data-horizon-direction` must not carry long/short (neutral only), or prove zero CSS consumer — prefer neutralize.  
3. Lock: node case `consolidated,LONG,false` must assert `dirText` not LONG/SHORT; fire control on current escaped shape.  
4. Kill or rewrite CSS comment ~2567 that still legalizes “direction visible” under non-actionable.  
5. Re-prove live DOM + injected veto/LONG path (not only WAIT sessions).  
6. Cursor re-audit → only then Decide = 10.

---

`CLAIM:` RC-133 horizon color fail-open ACCEPT; absolute no-LONG-text REJECT (ALL escape) · `DONE:` v27 · `NEXT:` Claude seal escape · `BLOCKER:` none
