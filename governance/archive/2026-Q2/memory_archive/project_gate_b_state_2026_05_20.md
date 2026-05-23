---
name: project-gate-b-state-2026-05-20
description: "Gate B audit/paired-fix session bookmark — closed lanes, pending bayesian_fusion paired-fix, queue, cadence lessons learned"
metadata: 
  node_type: memory
  type: project
  originSessionId: 0c0dc4ac-d25e-46af-b696-3be671664dda
---

Gate B audit + paired-fix work-in-progress as of 2026-05-20.

**Operating branch:** `feature/institutional-key-levels` (local, not pushed). Worktree: `jovial-blackwell-2bee88`. HEAD of worktree itself is `4b8ba2d` on `claude/jovial-blackwell-2bee88` (different branch — Schwab register work, unrelated). Gate B commits are on `feature/institutional-key-levels` via the operator's shell, verified via `git show feature/institutional-key-levels:<path>`.

**Closed lanes (signed off):**

| Lane | SHA(s) | What closed |
|---|---|---|
| Lane 3 (MCSI) | `a64b098` | FIND-MCSI-1/2/3 — `monte_carlo_stack_input.py` + `signals._spot_for_mc_fusion_adjustment` numeric_contract routing |
| MHMLB | `9495cea` | FIND-MHMLB-1/2/3 — `multi_horizon_ml_bundle.py` float_finite_or_none + direction_from_normalized_triplet + renorm provenance |
| REPO_SWEEP #2 | `1599d75` | SWEEP-EP-6..20 — server.py 11 + ml_scheduler.py 4 silent passes promoted; baseline 42 → 27; money-path files expanded to 13 |
| MHD | `d831732` + `4ec2716` | FIND-MHD-1..8 — `multi_horizon_decision.py` numeric_contract uniform; entry FSM no_setup on invalid zone/spot (4ec2716 is the MHD-7 completion with verbatim Option A return tuple) |
| MS | `1b5216f` | FIND-MS-1..10 — `market_state.py` `_f_ms`/`_ms_price_disp` uniform across builder; UI em dash on non-finite |

`OPEN_ITEMS.md` unchecked: ~37 (down from ~55 at session start).

**PENDING (awaiting Cursor commit):** `bayesian_fusion.py` paired-fix.

- Claude-drafted audit brief delivered on 2026-05-20 (find it in transcript at the turn before this bookmark)
- 6 FINDs: BF-1 (`_model_direction_triplet` raw float), BF-2 (`_model_dominant_class` accepts upstream label without triplet check — MHMLB-2-class), BF-3 (`_optional_support` raw float), BF-4 (`_bayesian_update` likelihood ^ weight), BF-5 (missing `float_finite_or_none` import), BF-6 (env-var parse fail-closed too broad)
- Commit body target: `Slice: AUDIT_LANE_PAIRED_FIX. FIND-BF-1..6. float_finite_or_none across model parsing; dominant_class always triplet-derived; env-var local fail-closed.`
- Awaiting `go paired-fix-bf` commit SHA from Cursor

**MS OBS-MS-8 cross-cutting closed by-construction:** `bayesian_fusion.dominant_direction` is already triplet-derived via `direction_from_normalized_triplet` at L660 and L713 — MHMLB-2-analogous fix not needed for that surface. (Confirmed in BF audit; brief states this explicitly in §2.)

**Next queue (when BF paired-fix signs off):**
1. `go audit-mada` — `v2_decision/module_a_adapter.py` (coherence-lens unread)
2. `go audit-lifecycle` — `lifecycle_rule_core.py` (coherence-lens unread)
3. `go sweep-3-error-propagation` — residual 27 silent passes across schwab_full_accessible_field_inventory.py (4), levels.py (2), live_market_plane.py (2), schwab_client.py (2), schwab_full_field_inventory.py (2) — non-money-path tail
4. `go audit-slvb-backfill` — `_slvb_tmp` calibration backfill coverage gaps
5. `go audit-ui-50405b8` — staged UI + server changes

**Cadence discipline (operator-corrected over multiple turns):**
- Claude drafts canonical audit briefs (gatekeeping role per "why didn't you do the mhd audit brief?" correction). NOT Cursor.
- Cursor implements per the brief; Cursor does NOT draft parallel briefs as default. When Cursor offers "I'll deliver the audit brief," reject and produce it myself.
- Claude verifies the implementation at the commit SHA via independent re-Read (independent full-Read verification).
- Sign-off requires return-tuple-against-spec verification, not just routing-mechanism match (lesson from d831732 → 4ec2716 MHD-7 completion).

**Calibration lessons (recorded same session):**
- f7f449d rejection: rejected for deferring FIND-MHD-6/7 as "defense-in-depth-LOW next pass" — that was real drift; rejection was correct.
- d831732 over-correction: I retracted sign-off when MHD-7 used "forming" instead of "no_setup" return string. Both fail-closed in trade-effect (tradeable=False either way). Operator corrected: severity by safety-impact, not spec-literalism. Retraction was over-correction.
- MS-2 application: implementation kept `if mc_iv_level > 0 then _f(...)` instead of literal `float_positive_or_none`. Behaviorally equivalent for NaN/inf/0/negative/finite-positive. Accepted at sign-off per the calibration above; flagged as consistency follow-up, not safety blocker.
- Net rule: "fix-as-we-find" applies to scope coverage (don't defer FINDs); "severity by safety-impact" applies to implementation review (accept behavioral equivalents).

**Key authority modules (single-source):** `time_et.py` (ET), `numeric_contract.py` (`float_finite_or_none`, `float_positive_or_none`, `direction_from_normalized_triplet`), `fusion_contract.py` (`fusion_is_authoritative`), `replay_hold_bars.py`, `position_sizing_policy.py`.

**Money-path modules (money-path module roster (AGENTS.md) zero-tolerance silent pass):** signals.py, call_engine.py, prediction_engine.py, realized_contract_eval.py, bayesian_fusion.py, mc_fusion_adjustment.py, market_state.py, live_decision_bundle.py, features/signal_layer_v1.py, features/inference_snapshot.py, features/fusion_policy_contract.py, server.py, ml_scheduler.py (13 total post-sweep #2).

**Why:** Operator needs to restart computer mid-session; without this bookmark the next session would have to rediscover where lanes closed and what's pending.

**How to apply:** On next session resume — read this file first, check `git log --oneline -10 feature/institutional-key-levels` to verify SHA chain hasn't moved unexpectedly, then check whether `go paired-fix-bf` SHA has landed. If yes, verify under 7-artifact at that SHA. If no, await Cursor.

Linked: [[feedback-cursor-drafts-claude-verifies]] (the cadence rule that got refined this session — audit briefs are now Claude-drafted, not Cursor-drafted), [[feedback-strict-gatekeeping-role]], [[feedback-full-read-verification-protocol]].
