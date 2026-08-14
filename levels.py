from __future__ import annotations

from dataclasses import dataclass
from typing import List

from math_exposure import ExposureRow, WallsRow, TotalsRow, fmt_money as _fmt_money_abbrev, fmt_money_gex as _fmt_gamma_money_1pct
import logging

log = logging.getLogger(__name__)



@dataclass(frozen=True)
class DisplayRow:
    range_label: str
    net_gamma: str
    net_delta: str
    gamma_pin: str
    delta_inf: str
    gamma_inf: str
    oi_center: str
    pin_strength: str
    bias_signal: str


def _fmt_level(x: float | None) -> str:
    if x is None:
        return "N/A"
    return f"{x:.2f}"


def _fmt_plain_2(x: float | None) -> str:
    if x is None:
        return "N/A"
    return f"{x:.2f}"


def to_display_rows(rows: List[ExposureRow]) -> List[DisplayRow]:
    # NOTE: ExposureRow net_gamma/net_delta use institutional aggregates when spot is known:
    #   - net_gamma = Σ net_gex_1pct (GEX$ per 1% move); else Σ net_gamma (γ×OI×mult)
    #   - net_delta = Σ net_dex_dollars; else Σ net_delta
    out: List[DisplayRow] = []
    for r in rows:
        out.append(
            DisplayRow(
                range_label=r.label,
                net_gamma=_fmt_money_abbrev(r.net_gamma),
                net_delta=_fmt_money_abbrev(r.net_delta),
                gamma_pin=_fmt_level(r.gamma_pin),
                delta_inf=_fmt_level(r.delta_inflection),
                gamma_inf=_fmt_level(r.gamma_inflection),
                oi_center=_fmt_level(r.oi_center),
                pin_strength=r.pin_strength,
                bias_signal=r.bias_signal,
            )
        )
    return out


def walls_to_df_rows(walls: List[WallsRow]) -> list[dict]:
    """Walls table headers must use words (no Greek symbols)."""
    out: list[dict] = []
    for w in walls:
        out.append(
            {
                "RANGE": w.label,
                "Call Gamma Wall": _fmt_level(w.call_gamma_wall),
                "Call Gamma Strength (GEX$ / 1%)": _fmt_gamma_money_1pct(w.call_gamma_strength),
                "Put Gamma Wall": _fmt_level(w.put_gamma_wall),
                "Put Gamma Strength (GEX$ / 1%)": _fmt_gamma_money_1pct(w.put_gamma_strength),
                "Dominant Gamma Side": w.dom_gamma_side or "N/A",
                "Dominant Gamma Wall": _fmt_level(w.dom_gamma_wall),
                "Dominant Gamma Strength (GEX$ / 1%)": _fmt_gamma_money_1pct(w.dom_gamma_strength),

                "Call Delta Wall": _fmt_level(w.call_delta_wall),
                "Call Delta Strength (DEX$)": _fmt_money_abbrev(w.call_delta_strength),
                "Put Delta Wall": _fmt_level(w.put_delta_wall),
                "Put Delta Strength (DEX$)": _fmt_money_abbrev(w.put_delta_strength),
                "Dominant Delta Side": w.dom_delta_side or "N/A",
                "Dominant Delta Wall": _fmt_level(w.dom_delta_wall),
                "Dominant Delta Strength (DEX$)": _fmt_money_abbrev(w.dom_delta_strength),

                "Call OI Wall": _fmt_level(w.call_oi_wall),
                "Call OI Strength (OI$)": _fmt_money_abbrev(w.call_oi_strength),
                "Put OI Wall": _fmt_level(w.put_oi_wall),
                "Put OI Strength (OI$)": _fmt_money_abbrev(w.put_oi_strength),
                "Dominant OI Side": w.dom_oi_side or "N/A",
                "Dominant OI Wall": _fmt_level(w.dom_oi_wall),
                "Dominant OI Strength (OI$)": _fmt_money_abbrev(w.dom_oi_strength),
            }
        )
    return out


def totals_to_df_rows(totals: List[TotalsRow]) -> list[dict]:
    """Totals table headers use words. Values are dollarized."""
    out: list[dict] = []
    for t in totals:
        out.append(
            {
                "RANGE": t.label,
                "Call Gamma (GEX$ / 1%)": _fmt_money_abbrev(t.call_gamma),
                "Put Gamma (GEX$ / 1%)": _fmt_money_abbrev(t.put_gamma),
                "Net Gamma (GEX$ / 1%)": _fmt_money_abbrev(t.net_gamma),

                "Call Delta (DEX$)": _fmt_money_abbrev(t.call_delta),
                "Put Delta (DEX$)": _fmt_money_abbrev(t.put_delta),
                "Net Delta (DEX$)": _fmt_money_abbrev(t.net_delta),

                "Call OI (OI$)": _fmt_money_abbrev(t.call_oi),
                "Put OI (OI$)": _fmt_money_abbrev(t.put_oi),
                "Net OI (Call - Put)": _fmt_money_abbrev(t.net_oi),

                "Put/Call OI Ratio": _fmt_plain_2(t.pcr_oi),
                "ATM Implied Vol": _fmt_plain_2(t.atm_iv),
                "Skew (Call IV - Put IV)": _fmt_plain_2(t.skew_proxy),
            }
        )
    return out


def key_levels_to_plot_rows(
    *,
    spot: float | None,
    expiry: str | None,
    consensus_walls: "WallsRow | None",
    consensus_summary: "ExposureRow | None",
    contracts: list | None = None,
    regime: str = "",
    rec_strike: float | None = None,
    filter_pct: float = 0.05,
    dedup_pts: float = 0.25,
) -> list[dict]:
    """
    Key Levels to Plot — institutional grade.

    Dedup strategy (v2):
      Instead of silently dropping a level when two metrics share the same strike,
      we MERGE them into a combined label: "Gamma + Delta Wall CALL @ 694".
      This is MORE informative — a strike where gamma, delta, AND OI all peak is
      a confluence strike and much stronger than any single metric alone.

      dedup_pts default tightened to 0.25 (was 0.50) so levels within 0.5 pts
      of each other that are genuinely distinct still show as separate rows.

    Behavior column (v2):
      Two-part format: "approach → at level" e.g. "Accelerates → Hard ceiling"
      Regime-aware: pin regime vs expansion regime changes expected behavior.
    """

    def _sr(level: float | None) -> str:
        if spot is None or level is None:
            return ""
        try:
            return "Support" if float(level) <= float(spot) else "Resistance"
        except Exception:
            return ""

    # ── Regime detection ─────────────────────────────────────────────────────
    reg = (regime or "").upper()
    is_pin       = "PIN" in reg or "LONG" in reg or "BULL" in reg
    is_expansion = "EXPANSION" in reg or "SHORT" in reg or "EXPAND" in reg or "BEAR" in reg

    # ── Behavior tags: "approach → at level" two-part format ─────────────────
    if is_pin:
        call_wall_beh  = "Accelerates up → Hard ceiling (dealers sell)"
        put_wall_beh   = "Slows descent → Floor (dealers buy)"
        call_pin_beh   = "Drifts toward → Sticky (expiry magnet)"
        put_pin_beh    = "Drifts toward → Sticky (expiry magnet)"
        inf_beh        = "Regime boundary → Expansion if broken below"
        vanna_call_beh = "Vol crush → Mechanical dealer buying"
        vanna_put_beh  = "Vol crush → Overhead resistance eases"
    elif is_expansion:
        call_wall_beh  = "Breakout risk → Breach likely, moves amplify"
        put_wall_beh   = "Breakdown risk → Breach likely, moves amplify"
        call_pin_beh   = "Unstable → May break cleanly"
        put_pin_beh    = "Unstable → May break cleanly"
        inf_beh        = "Already in expansion → Pin if recaptured above"
        vanna_call_beh = "Vol spike → Dealer selling pressure"
        vanna_put_beh  = "Vol spike → Forced dealer selling, drops amplify"
    else:
        call_wall_beh  = "Watch → Ceiling or breakout depending on flow"
        put_wall_beh   = "Watch → Floor or breakdown depending on flow"
        call_pin_beh   = "Unstable → Near regime flip"
        put_pin_beh    = "Unstable → Near regime flip"
        inf_beh        = "Regime flip zone → Direction uncertain"
        vanna_call_beh = "IV sensitive → Watch VIX direction"
        vanna_put_beh  = "IV sensitive → Watch VIX direction"

    oi_wall_beh = "Expiry magnet → Pins price into close (stronger near expiry)"
    oi_pin_beh  = "Near-term magnet → Max pain gravity"
    synth_beh   = "Parity level → Institutional arbitrage reference"

    def _oe_flag(level: float | None) -> str:
        if rec_strike is None or level is None:
            return ""
        try:
            return " ★ OE" if abs(float(level) - float(rec_strike)) < 0.01 else ""
        except Exception:
            return ""

    def _row(metric: str, level: float | None, side: str, strength: str, behavior: str) -> dict | None:
        if level is None:
            return None
        if spot is not None and filter_pct > 0:
            try:
                if abs(float(level) - float(spot)) > float(spot) * filter_pct:
                    return None
            except Exception as e:
                log.debug("level filter / parity row: %s", e, exc_info=True)
        sr  = _sr(level)
        oe  = _oe_flag(level)
        return {
            "Metric":   metric + oe,
            "Level":    _fmt_level(level),
            "Side":     side or "",
            "Strength": strength or "",
            "S/R":      sr,
            "Behavior": behavior,
            "_level_f": float(level),
            "_side":    side or "",
            "_raw_metric": metric,   # used for confluence label building
        }

    rows: list[dict] = []

    # ── Spot ─────────────────────────────────────────────────────────────────
    if spot is not None:
        rows.append({
            "Metric":      "Spot",
            "Level":       _fmt_level(spot),
            "Side":        "",
            "Strength":    "",
            "S/R":         "",
            "Behavior":    f"Expiry: {expiry or 'N/A'}",
            "_level_f":    float(spot),
            "_side":       "",
            "_raw_metric": "Spot",
        })

    if consensus_walls is None or consensus_summary is None:
        return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

    w = consensus_walls
    s = consensus_summary

    # ── Gamma levels ─────────────────────────────────────────────────────────
    for level, side, strength, label, beh in [
        (w.call_gamma_wall, "CALL", w.call_gamma_strength, "Gamma Wall", call_wall_beh),
        (w.put_gamma_wall,  "PUT",  w.put_gamma_strength,  "Gamma Wall", put_wall_beh),
        (w.call_gamma_pin,  "CALL", w.call_gamma_pin_strength, "Gamma Pin", call_pin_beh),
        (w.put_gamma_pin,   "PUT",  w.put_gamma_pin_strength,  "Gamma Pin", put_pin_beh),
    ]:
        r = _row(label, level, side, _fmt_gamma_money_1pct(strength), beh)
        if r:
            rows.append(r)

    if s.gamma_inflection is not None:
        r = _row("Gamma Inflection", s.gamma_inflection, "NET", "", inf_beh)
        if r:
            rows.append(r)

    # ── Delta levels ─────────────────────────────────────────────────────────
    for level, side, strength, label, beh in [
        (w.call_delta_wall, "CALL", w.call_delta_strength, "Delta Wall", call_wall_beh),
        (w.put_delta_wall,  "PUT",  w.put_delta_strength,  "Delta Wall", put_wall_beh),
        (w.call_delta_pin,  "CALL", w.call_delta_pin_strength, "Delta Pin", call_pin_beh),
        (w.put_delta_pin,   "PUT",  w.put_delta_pin_strength,  "Delta Pin", put_pin_beh),
    ]:
        r = _row(label, level, side, _fmt_money_abbrev(strength), beh)
        if r:
            rows.append(r)

    if s.delta_inflection is not None:
        r = _row("Delta Inflection", s.delta_inflection, "NET", "", inf_beh)
        if r:
            rows.append(r)

    # ── OI levels ────────────────────────────────────────────────────────────
    for level, side, strength, label, beh in [
        (w.call_oi_wall, "CALL", w.call_oi_strength, "OI Wall", oi_wall_beh),
        (w.put_oi_wall,  "PUT",  w.put_oi_strength,  "OI Wall", oi_wall_beh),
        (w.call_oi_pin,  "CALL", w.call_oi_pin_strength, "OI Pin", oi_pin_beh),
        (w.put_oi_pin,   "PUT",  w.put_oi_pin_strength,  "OI Pin", oi_pin_beh),
    ]:
        r = _row(label, level, side, _fmt_money_abbrev(strength), beh)
        if r:
            rows.append(r)

    if s.oi_center is not None:
        r = _row("OI Center", s.oi_center, "NET", "", "Gravity center → Price gravitates here near expiry")
        if r:
            rows.append(r)

    # ── Vanna Walls ──────────────────────────────────────────────────────────
    for level, side, strength, label, beh in [
        (getattr(w, "call_vanna_wall", None), "CALL",
         getattr(w, "call_vanna_strength", None), "Vanna Wall", vanna_call_beh),
        (getattr(w, "put_vanna_wall",  None), "PUT",
         getattr(w, "put_vanna_strength",  None), "Vanna Wall", vanna_put_beh),
    ]:
        r = _row(label, level, side, _fmt_money_abbrev(strength), beh)
        if r:
            rows.append(r)

    # ── Synthetic Forward ─────────────────────────────────────────────────────
    if contracts and spot is not None:
        try:
            from math_exposure import parity_f_minus_spot_from_contracts
            parity_resid = parity_f_minus_spot_from_contracts(contracts, spot=float(spot))
            if parity_resid is not None and abs(parity_resid) > 0.10:
                synth_fwd = float(spot) + parity_resid
                r = _row(
                    "Synthetic Fwd",
                    synth_fwd,
                    "CALL" if parity_resid > 0 else "PUT",
                    f"{parity_resid:+.2f} pts residual",
                    synth_beh
                )
                if r:
                    rows.append(r)
        except Exception as e:
            log.debug("level filter / parity row: %s", e, exc_info=True)
    # ── Regime row ───────────────────────────────────────────────────────────
    rows.append({
        "Metric":      "Regime",
        "Level":       f"{s.pin_strength} | {s.bias_signal}",
        "Side":        "",
        "Strength":    "",
        "S/R":         "",
        "Behavior":    "",
        "_level_f":    -1.0,
        "_side":       "",
        "_raw_metric": "Regime",
    })

    # ── Confluence dedup: merge rows at the same strike into combined label ───
    # Strategy: group all rows by rounded strike level.
    # If multiple metric types land at the same strike (within dedup_pts),
    # combine their labels: "Gamma + Delta Wall CALL" — more informative than dropping one.
    # Inflection rows are always kept separate (they represent a different concept).
    # Spot and Regime rows are always kept separate.
    if dedup_pts >= 0 and spot is not None:
        # Separate non-level rows from level rows
        special = [r for r in rows if r.get("_level_f", -1.0) < 0]
        level_rows = [r for r in rows if r.get("_level_f", -1.0) >= 0]

        # Group by (rounded_level, side) — same strike + same side = confluence candidate
        from collections import defaultdict
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for r in level_rows:
            lf = r["_level_f"]
            side = r.get("_side", "")
            # Round to nearest dedup_pts bucket
            bucket = round(lf / (dedup_pts if dedup_pts > 0 else 0.25))
            groups[(bucket, side)].append(r)

        # For each group, either keep single row or build confluence row
        merged_rows: list[dict] = []
        for (bucket, side), grp in groups.items():
            if len(grp) == 1:
                merged_rows.append(grp[0])
            else:
                # Multiple metrics at same strike/side — build confluence label
                # Priority order for label building: Wall > Inflection > Pin > other
                def _metric_base(m: str) -> str:
                    """Extract base metric type for confluence label."""
                    for base in ("Gamma", "Delta", "OI", "Vanna"):
                        if base in m:
                            return base
                    return m.split()[0] if m.split() else m

                def _row_priority(r: dict) -> int:
                    m = r.get("_raw_metric", "")
                    if "Wall" in m:        return 4
                    if "Inflection" in m:  return 3
                    if "Pin" in m:         return 2
                    return 1

                grp_sorted = sorted(grp, key=_row_priority, reverse=True)
                best = grp_sorted[0]  # highest priority row drives level, strength, behavior

                # Build combined metric label from unique bases
                seen_bases = []
                for r in grp_sorted:
                    base = _metric_base(r.get("_raw_metric", ""))
                    if base not in seen_bases:
                        seen_bases.append(base)

                # Determine unified label suffix (Wall if any wall present, else highest)
                label_suffix = "Wall" if any("Wall" in r.get("_raw_metric","") for r in grp_sorted) else                                "Pin"  if any("Pin"  in r.get("_raw_metric","") for r in grp_sorted) else ""

                # e.g. "Gamma + Delta + OI Wall"  or "Gamma + OI Pin"
                combined_metric = " + ".join(seen_bases)
                if label_suffix:
                    combined_metric += f" {label_suffix}"

                # Confluence: enhance the behavior note
                n = len(seen_bases)
                confluence_note = f"⚡ {n}-metric confluence — " + best["Behavior"]

                # OE flag: propagate if any row in the group has it
                oe_flag = ""
                for r in grp:
                    if "★ OE" in r.get("Metric", ""):
                        oe_flag = " ★ OE"
                        break

                merged_rows.append({
                    **best,
                    "Metric":   combined_metric + oe_flag,
                    "Behavior": confluence_note,
                    "_raw_metric": combined_metric,
                })

        # Re-sort by level descending (highest price first) — easier to read top-to-bottom on chart
        merged_rows.sort(key=lambda r: r["_level_f"], reverse=True)
        rows = merged_rows + special

    # Strip internal fields before returning
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]

