# One-faucet closeout — scoreboard (mission one-faucet-closeout-v1)

**ONE_FAUCET_REPO_WIDE = YES · REMAINING = 0** — every census concept is SINGLE or was
KILLED_TONIGHT, each with a T1 lock that screams on regression. Machine copy:
`multi_faucet_one_faucet_closeout_latest.json`.

| concept | status | kill / authority |
|---|---|---|
| prior_day family | **KILLED_TONIGHT (B3)** | chart client compute deleted; `enginePD()` sole accessor; engine absent → renders absent |
| vwap (+bands) | SINGLE | `compute_session_vwap` (Tier-B, 6d49604d); substitution hard-fails |
| opening_range | SINGLE | `compute_opening_range` (Tier-B) |
| overnight | SINGLE | `get_overnight_levels` RC-153 interval (Tier-B) |
| today value_area | SINGLE | `compute_volume_profile_levels` (Tier-B) |
| charm / greeks | SINGLE | `bs_charm` faucet (RC-224); strip renders real charm per RC-199 tonight |
| clocks | SINGLE | ET session keys + CT display (RC-223) |
| spot | SINGLE | `resolve_spot` + single-payload binding (RC-225) |
| walls / flip | SINGLE | terrain producer (RC-80); flip stack measured layered, not dual |
| strikes bindings | **KILLED_TONIGHT (STRIP)** | `today_side_sums` server-aggregated on the payload's own spot; browser re-sum deleted |
| display precision | **KILLED_TONIGHT (PDH_PRECISION)** | level family serves RAW; rounding render-only |
| expected_move | SINGLE | terrain sigma band, E-34 locked |
| /api/price-levels | **KILLED_TONIGHT (B6)** | 410 GONE with `/api/levels` pointer; no alias, no second surface |

**Locks landed tonight** (tests/test_levels_single_producer_v1.py, 24 passed):
`test_b3_chart_never_computes_prior_day` · `test_strip_never_reaggregates_side_sums_client_side` ·
`test_strip_charm_row_not_vote_locked` · `test_strikes_payload_carries_server_side_sums` ·
`test_price_levels_route_retired_410` · `test_state_level_family_serves_raw_not_rounded`

**Also fixed in passing (standing order, RC-199):** the FORCES strip's charm row rendered
"locked pending DIR-01(i) vote" — a gate the operator revoked. It now renders
`charm_below`/`charm_above` from `/api/forces` banked chains.

Full defect chain and five-whys: RC-227 in `governance/root_cause_log.md` (renumbered from a
duplicate RC-226 taken concurrently by the writer-drift guard row).
