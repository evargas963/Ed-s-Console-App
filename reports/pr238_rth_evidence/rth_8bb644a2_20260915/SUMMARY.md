# PR #238 live-vendor proof — PARTIAL

captured_utc: 2026-09-15T20:15:13.179905+00:00
running_sha: 8bb644a2ca13dbea7671334dad3e1e6ce98ccba5
sha_matches_current_branch_tip: True
code_drift: {'repo_moved_past_process': False, 'running_code': '8bb644a2ca13dbea7671334dad3e1e6ce98ccba5', 'checked_out_code': '8bb644a2ca13dbea7671334dad3e1e6ce98ccba5'}
cross_ticker_contamination: none

## SPY: PASS_NO_CELL_VALUE_CHANGE_OBSERVED
- baseline_ok: True
- subscribed_contract: SPY   260915C00758000 (accepted=True)
- [1] live tick identity — overlay names our contract: True
- [2] heatmap updates — subscribed cell located=True, value changed=False (0 -> 0)
- [3] overlay state — stream_overlay_observed=True, symbols_seen=['SPY   260915C00757000', 'SPY   260915C00758000']
- [4] freshness — sane=True, age_sec_samples(first/last)=[42.4]/[112.7]
- [5] ticker switching — identity_mismatches=0
- terrain_cycle_advanced_during_poll: True
- microstructure_contract_match_observed: False

## QQQ: PARTIAL_NO_OVERLAY_OBSERVED
- baseline_ok: True
- subscribed_contract: QQQ   260915C00705000 (accepted=True)
- [1] live tick identity — overlay names our contract: False
- [2] heatmap updates — subscribed cell located=True, value changed=False (-367847380 -> -367847380)
- [3] overlay state — stream_overlay_observed=False, symbols_seen=[]
- [4] freshness — sane=True, age_sec_samples(first/last)=[24597.8]/[24597.8]
- [5] ticker switching — identity_mismatches=0
- terrain_cycle_advanced_during_poll: False
- microstructure_contract_match_observed: False
