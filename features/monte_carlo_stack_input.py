"""
Monte Carlo stack inputs: spot and lineage checks use InferenceSnapshotV1 MVP only.

Do not source MC spot from ad hoc SignalInput alone when a canonical row exists — avoids
parallel truth paths with the fusion / ML stack.
"""

from __future__ import annotations

from typing import Any

REL_SPOT_TOL = 1e-5

# Monte Carlo inputs taken from L1 / SignalInput only — not part of MVP contract v1_1m_mvp.
# They do not duplicate canonical structure fields; spot is always canonical (see resolve_*).
MONTE_CARLO_NON_CANONICAL_L1_KEYS = frozenset({
    "call_gamma_wall",
    "put_gamma_wall",
    "em_upper",
    "em_lower",
    "realized_vol",
    "atr",
    "garch_sigma_bars",
})


class MonteCarloStackInputError(ValueError):
    """Canonical MVP row missing required fields or lineage mismatch for Monte Carlo."""


def resolve_monte_carlo_stack_inputs(
    inp: Any,
    inference_snapshot_v1: dict[str, Any],
) -> dict[str, Any]:
    """
    Return kwargs compatible with ``monte_carlo.simulate`` spot/lineage fields.

    - ``spot`` comes **only** from ``features["price.spot"]`` when present and valid.
    - If canonical spot is None, MC must not silently substitute ``inp.spot`` (fail closed).
    - If both canonical and ``inp.spot`` are present and differ materially, fail closed.
    - Non-MVP context (iv, walls, em_*, garch, rv, atr) remains from ``inp`` (not duplicated in MVP).
    """
    feats = inference_snapshot_v1.get("features") or {}
    spot = feats.get("price.spot")
    if spot is None:
        raise MonteCarloStackInputError(
            "Monte Carlo blocked: canonical MVP price.spot is missing (no ad hoc inp.spot fallback)."
        )
    try:
        spot_f = float(spot)
    except (TypeError, ValueError) as e:
        raise MonteCarloStackInputError(f"Monte Carlo blocked: invalid canonical price.spot: {spot!r}") from e
    if not (spot_f > 0.0):
        raise MonteCarloStackInputError(f"Monte Carlo blocked: canonical price.spot must be > 0, got {spot_f!r}")

    raw = getattr(inp, "spot", None)
    if raw is not None:
        try:
            rf = float(raw)
            if rf > 0 and abs(rf - spot_f) / spot_f > REL_SPOT_TOL:
                raise MonteCarloStackInputError(
                    "Monte Carlo blocked: SignalInput.spot disagrees with canonical MVP price.spot "
                    f"(inp={rf!r}, canonical={spot_f!r})."
                )
        except MonteCarloStackInputError:
            raise
        except (TypeError, ValueError):
            raise MonteCarloStackInputError(f"Monte Carlo blocked: invalid SignalInput.spot: {raw!r}") from None

    out = {
        "spot": spot_f,
        "call_gamma_wall": getattr(inp, "call_gamma_wall", None),
        "put_gamma_wall": getattr(inp, "put_gamma_wall", None),
        "em_upper": getattr(inp, "em_upper", None),
        "em_lower": getattr(inp, "em_lower", None),
        "realized_vol": getattr(inp, "realized_vol", None),
        "atr": getattr(inp, "atr", None),
        "garch_sigma_bars": getattr(inp, "garch_sigma_bars", None),
    }
    out["_mc_context_lineage"] = {
        "canonical_mvp_keys_used": ("price.spot",),
        "non_canonical_l1_keys": tuple(sorted(MONTE_CARLO_NON_CANONICAL_L1_KEYS)),
    }
    return out
