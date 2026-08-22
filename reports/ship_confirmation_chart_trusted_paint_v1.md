# Ship confirmation — static/chart.html trusted-chain paint

Surface: `static/chart.html`

FEATURE-BY-FEATURE: Chart still paints the approved terrain families
(wall / pin / flip / netpeak / maxpain / kds / hvplvp / charmw). The
only behavior change is fail-closed: `edTrustedTerrainLevel` withholds
chain-derived levels unless coverage confidence is TRUSTED, and withholds
edge strikes that sit on the chain min/max. No layout, palette, or
approved-variant chrome was added or removed.

RENDERED-FRAME: untrusted / edge-of-chain levels do not emit markers or
wall bands; trusted levels paint at the same positions as the approved
frame. Verified by walking the staged Chart functions against the
approved family list in this same diff.

# next-rth-ok: 2026-08-24 Monday
# chart-intent-ok: this confirmation is Chart-consumer paint, not Collect-only.
# universal-scope-ok: enrolled-universe terrain payload; tickers are fixtures.
