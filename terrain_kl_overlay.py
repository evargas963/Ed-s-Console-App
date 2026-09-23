"""Key Levels terrain overlay (server.py decomposition, twenty-ninth slice,
RC-REHAB-1, 2026-09-23).

_terrain_kl_overlay moves here verbatim. Not a _fetch_state phase (no
server_state_ prefix): W3-C1/RC-122's "ONE wall book on the screen" -- the
single writer of every gamma-family kl_* key on a UI payload, overlaid from the
terrain cache (THE levels SSOT, RC-33), called from two sites in server.py's own
body (both stay there, calling the re-exported name); no external caller.

MONKEYPATCH/RUNTIME-STATE NOTE: terrain_cache_get has confirmed OTHER callers
elsewhere in server.py, so it stays there, reached via the established lazy
`import server` pattern.
"""
from __future__ import annotations


def _terrain_kl_overlay(md: dict, ticker: str) -> None:
    """W3-C1 / RC-122: ONE wall book on the screen.

    The Key Levels table read kl_* gamma-family values computed from the ANALYTICS pipeline's
    narrow chain while the terrain cards painted the wide-capture book beside them — two wall
    books, one screen, no label saying which is which (the dual-book lie the operator's
    audits carried since Wave-1). Terrain is THE levels SSOT (RC-33); every gamma-family kl_*
    is overlaid from its cached payload, stamped kl_levels_source. Absent or stale terrain
    BLANKS the keys — absence, never a silently different second book. The narrow-book wall
    STRENGTH strings are blanked with the same stroke: a dollar figure computed from one
    chain printed beside a strike from another is the same lie in a smaller cell.
    OI/vanna walls, inflections, and oi_center stay blank: terrain does not compute them,
    so analytics must never stand in for an absent SSOT value (RC-128 / RC-422).
    """
    import server as _srv

    t = dict(_srv.terrain_cache_get(ticker) or {})
    fresh = bool(t) and not t.get("levels_stale")
    # RC-124/RC-292: kl_absolute_gamma_strike carries the total-gamma concentration under
    # its metric's name (formerly kl_gamma_pin — a pin claim the metric had not earned);
    # kl_pin_candidate carries the QUALIFIED pin claim, blank with its blocker names
    # otherwise; kl_hvl carries the net-GEX peak (the former "pin", honestly renamed on
    # the card) — that key name is historical, the row label and tooltip say what it is.
    # RC-128 (One Levels Faucet): this helper is THE ONLY WRITER of every SSOT level key on
    # a UI payload. The analytics assignments were DELETED, not overridden — placement was
    # the bug (a write after this call resurrected the dual book). Delta walls joined the
    # terrain producer; EM comes from the terrain sigma band; concepts terrain does not
    # compute (OI/vanna walls, inflections, oi_center) are BLANKED with the reason — an
    # analytics book may never stand in for an absent SSOT value.
    # Explicit literal assignments, deliberately not a loop: the orphan-key detector (RC-84)
    # counts literal write sites, and a loop-driven write made three honest reads look
    # writerless. Verbosity is the price of a detector that can actually see the writer.
    # NAMING CONSOLIDATION (2026-09-21): a field audit found _fetch_state's payload and
    # /api/terrain's own response independently re-serializing the SAME terrain-cache values
    # under DIFFERENT names (kl_gsf vs gsf; kl_dex_net vs net_dex, word order flipped;
    # kl_zero_dte_share vs zero_dte_gamma_share_pct, abbreviated) with nothing keeping the two
    # in sync -- which is exactly why the UI wiring this same audit did (Key Levels panel)
    # took real investigation to trace, per field, instead of being a literal string match.
    # `absolute_gamma_strike` (RC-292/RC-417, below) already established the right pattern
    # once, with its own comment explaining why: keep this payload's own kl_-prefixed
    # convention, AND carry the source's own bare name verbatim beside it, so a reader (or a
    # script) checking "does ms_dict have what /api/terrain calls X" is a literal key lookup
    # forever, not a re-investigation. Applied here to every OTHER direct, untransformed
    # terrain value in this block. Three fields (kl_hvl, kl_gamma_flip_confidence,
    # kl_levels_from_computed_ts) keep ONLY their kl_ name deliberately -- each has its own
    # comment explaining a real, reviewed reason (a historical relabel, or disambiguating a
    # vaguer terrain-side name); left untouched, not overlooked. Destructured sub-fields
    # (kl_rr25_pts/dte, kl_doi_*) carry the whole source dict too (rr_25d, delta_oi_walls)
    # rather than one alias per flattened leaf.
    _g = (lambda k: t.get(k)) if fresh else (lambda k: None)
    md["kl_call_gamma_wall"] = md["call_wall"] = _g("call_wall")
    md["kl_put_gamma_wall"] = md["put_wall"] = _g("put_wall")
    md["kl_gamma_flip"] = md["gamma_flip"] = _g("gamma_flip")
    # RC-292/RC-417: payload `absolute_gamma_strike` is the same SSOT total-gamma value as
    # kl_absolute_gamma_strike (top-level key kept so the terrain- and analytics-payload
    # shapes agree, and so any resurrected analytics writer of this name is overwritten by
    # the SSOT here). Analytics consensus_summary.net_gex_peak is pick_net_gex_peak_strike
    # (selected-expiry |net GEX$| peak) and must never occupy this key. MEASURED on the
    # real SPY 0DTE fixture: total-gamma concentration 745 vs net peak 743.
    md["kl_absolute_gamma_strike"] = md["absolute_gamma_strike"] = _g("absolute_gamma_strike")
    md["kl_absolute_gamma_strength_pct"] = md["absolute_gamma_strength_pct"] = _g("absolute_gamma_strength_pct")
    # RC-292 operator disposition: the pin CLAIM ships only after regime/proximity/DTE/
    # liquidity/completeness qualification (terrain_engine.qualify_pin_candidate); the
    # blocker names ship beside it so absence renders with its reason, never a bare dash.
    md["kl_pin_candidate"] = md["pin_candidate"] = _g("pin_candidate")
    md["kl_pin_candidate_blockers"] = md["pin_candidate_blockers"] = _g("pin_candidate_blockers")
    md["kl_hvl"] = _g("net_gex_peak")
    # RC-354: GSF/GRC ride the same SSOT terrain book (one profile, one producer). The
    # STATE ships beside the prices so the UI can render BELOW SUPPORT as a verdict, never
    # a dash that reads like "unknown" when the truth is "support is already gone".
    md["kl_gsf"] = md["gsf"] = _g("gsf")
    md["kl_grc"] = md["grc"] = _g("grc")
    md["kl_gsf_state"] = md["gsf_state"] = _g("gsf_state")
    md["kl_gsf_state_disp"] = "BELOW SUPPORT" if _g("gsf_state") == "BELOW_SUPPORT" else None
    # RC-357: 0DTE share of the gamma book — level persistence, same SSOT terrain book.
    md["kl_zero_dte_share"] = md["zero_dte_gamma_share_pct"] = _g("zero_dte_gamma_share_pct")
    # RC-358: 25Δ risk reversal — skew steepness; flattened for the payload, fail-closed.
    _rr = _g("rr_25d") or {}
    md["rr_25d"] = _rr
    md["kl_rr25_pts"] = _rr.get("rr_pts") if isinstance(_rr, dict) else None
    md["kl_rr25_dte"] = _rr.get("dte") if isinstance(_rr, dict) else None
    # RC-359: ΔOI walls — fresh vs stale positioning; None until two sessions are banked.
    _doi = _g("delta_oi_walls") or {}
    _doi_ok = isinstance(_doi, dict)
    md["delta_oi_walls"] = _doi
    md["kl_doi_call_strike"] = _doi.get("call_build_strike") if _doi_ok else None
    md["kl_doi_call_oi"] = _doi.get("call_build_doi") if _doi_ok else None
    md["kl_doi_put_strike"] = _doi.get("put_build_strike") if _doi_ok else None
    md["kl_doi_put_oi"] = _doi.get("put_build_doi") if _doi_ok else None
    md["kl_doi_unwind_strike"] = _doi.get("unwind_strike") if _doi_ok else None
    md["kl_doi_unwind_oi"] = _doi.get("unwind_doi") if _doi_ok else None
    # RC-361: aggregate dealer DEX $ — directional inventory beside the GEX-per-1% row.
    _dex = _g("dex_dollars") or {}
    md["dex_dollars"] = _dex
    md["kl_dex_net"] = _dex.get("net_dex") if isinstance(_dex, dict) else None
    # RC-362: aggregate dealer vanna $ per vol-pt — the IV-driven hedge-flow size.
    _vna = _g("vanna_agg") or {}
    md["vanna_agg"] = _vna
    md["kl_vanna_net_dollars"] = _vna.get("net_vanna_dollars_per_volpt") if isinstance(_vna, dict) else None
    md["kl_max_pain"] = md["max_pain"] = _g("max_pain")
    md["kl_call_delta_wall"] = md["call_delta_wall"] = _g("call_delta_wall")
    md["kl_put_delta_wall"] = md["put_delta_wall"] = _g("put_delta_wall")
    # v23: the flip's CONFIDENCE rides the same book as the flip's STRIKE — it was still
    # analytics-written while the strike was terrain's, a half-dual book.
    md["kl_gamma_flip_confidence"] = _g("confidence")
    # RC-130: the geometry state travels WITH the wall value it qualifies — as of the same
    # terrain generation (kl_levels_from_computed_ts). A wall value without its state let
    # the KL table caption "support" on a put wall sitting above spot.
    md["kl_call_wall_state"] = md["call_wall_state"] = _g("call_wall_state")
    md["kl_put_wall_state"] = md["put_wall_state"] = _g("put_wall_state")
    # v23 Lock-3 drift visibility: which terrain generation stamped these values — the KL
    # table and the terrain cards can only differ by generation skew, and now it is visible.
    md["kl_levels_from_computed_ts"] = _g("computed_ts_utc")
    em = (t.get("implied_1d_move") or {}) if fresh else {}
    _em_pts, _em_spot = em.get("points"), (t.get("spot") if fresh else None)
    if _em_pts is not None and _em_spot:
        md["kl_em_upper"] = round(float(_em_spot) + float(_em_pts), 2)
        md["kl_em_lower"] = round(float(_em_spot) - float(_em_pts), 2)
        # RC-345 / F06: the operator-facing kl_em band comes from the terrain implied-1d-move
        # (IV sigma band: S x sigma_ATM x sqrt(1/252)). Carry its methodology to the payload so
        # the operator never receives an EM number without knowing which EM semantic produced
        # it — the terrain `method` string travels beside the band, not dropped.
        md["kl_em_source"] = "IV_SIGMA_1D"
        md["kl_em_method_detail"] = em.get("method") or "S x sigma_ATM x sqrt(1/252)"  # caps-ok: not a guess -- kl_em_source is stamped "IV_SIGMA_1D" unconditionally two lines above in this same branch, so the formula IS this one regardless of whether the producer's optional method label happens to be present; the fallback supplies the already-asserted, correct description, never a different value
    else:
        md["kl_em_upper"] = md["kl_em_lower"] = None
        md["kl_em_source"] = "unavailable"
        md["kl_em_method_detail"] = None
    # terrain does not compute these yet — absence, never a second book
    md["kl_call_oi_wall"] = None
    md["kl_put_oi_wall"] = None
    md["kl_call_vanna_wall"] = None
    md["kl_put_vanna_wall"] = None
    md["kl_gamma_inflection"] = None
    md["kl_delta_inflection"] = None
    md["kl_oi_center"] = None
    # a strength from another book beside an SSOT strike is the same lie — blanked
    md["kl_call_delta_str"] = "—"
    md["kl_put_delta_str"] = "—"
    md["kl_call_oi_str"] = "—"
    md["kl_put_oi_str"] = "—"
    md["kl_call_vanna_str"] = "—"
    md["kl_put_vanna_str"] = "—"
    md["kl_levels_source"] = ("terrain_wide_chain" if fresh else
                              "terrain_unavailable — gamma-family levels withheld")
    for k in ("kl_call_gamma_str", "kl_put_gamma_str", "kl_hvl_str", "kl_max_pain_str"):
        md[k] = "—"
