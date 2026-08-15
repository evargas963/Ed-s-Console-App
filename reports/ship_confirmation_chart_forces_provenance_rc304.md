# Ship confirmation — static/chart.html FORCES provenance (RC-304) — FEATURE-BY-FEATURE against actual code, RENDERED-FRAME verified

Operator law (non-negotiable, 2026-08-02): *"you are to always confirm first with actual code
before you ship."* This document is that confirmation for the RC-304 correctness fix to the
FORCES panel of `static/chart.html`.

**Scope of the change.** No redesign. Same five rows, same cells, same layout. The only thing
that changes on the operator's screen is the SOURCE text at the right of three rows, which
previously said something untrue of two of them.

## RENDERED-FRAME evidence

Live console started on 127.0.0.1:8777 (`preview_start ed-console`), real Schwab-banked
chains, ticker SPY. The FORCES grid was read out of the **rendered DOM** after the 15s load
cycle — not from source, not from the endpoint alone:

```
document.querySelectorAll('#f-grid .fl')   -> fr-gex, fr-ov, fr-doi, fr-dex, fr-charm
document.querySelectorAll('#f-grid .fsrc') -> [
  "live · 238 strikes",
  "live session",
  "banked 2026-08-06→2026-08-07",
  "banked 2026-08-07",
  "banked 2026-08-07 · full_chain_banked"
]
window.EdForcesProvenance                  -> object   (module loaded)
#f-reading -> "Reading: gamma -2.5B below vs 11.7B above (0.22:1) · volume 1.31:1 below ·
               ΔOI -91K below / -79K above."
```

The payload those labels describe, read the same minute from
`curl -s "http://127.0.0.1:8777/api/forces?ticker=SPY"`:

```
available        True
older_et_date    '2026-08-06'      newer_et_date  '2026-08-07'
charm_below      -583617.5327      charm_above    -635440.9188
charm_book_scope 'full_chain_banked'
charm_error      None
```

A screenshot could not be captured this session — the Browser pane was not compositing
frames ("the Browser pane is not displayed") — so the frame evidence here is the rendered
DOM read out of the live page, which is the same surface the eye reads and is stated as such
rather than implied.

## FEATURE-BY-FEATURE (what the row claims → what the code does → what the frame shows)

| # | Row | What the source label must be true of | Code anchor | On the rendered frame |
|---|---|---|---|---|
| 1 | GEX $ | the LIVE per-strike book | `liveSrc` from `strikes.today.all` | `live · 238 strikes` — unchanged |
| 2 | OPT VOL | this session's live volume | literal `live session` | `live session` — unchanged |
| 3 | ΔOI | BOTH banked captures, differenced | `forcesRowSource(fz,'doi')`; server sums `oi1[k] - oi0[k]` at `server.py:12505` | `banked 2026-08-06→2026-08-07` — the span is real |
| 4 | DEX $ | the NEWER capture ALONE | `forcesRowSource(fz,'dex')`; server sums `per1` (from `c1`) at `server.py:12507` | `banked 2026-08-07` — **was** `banked 2026-08-06→2026-08-07` |
| 5 | CHARM | the NEWER capture, and WHICH BOOK it covered | `forcesRowSource(fz,'charm')`; server sums `chain1 = json.loads(c1)` at `:12480` and derives `charm_book_scope` at `:12521` | `banked 2026-08-07 · full_chain_banked` — **was** `banked 2026-08-06→2026-08-07`, with the book scope shown nowhere |

## Absence and failure states (checked by execution, not by reading)

| Condition | Rendered source text |
|---|---|
| `charm_error` served | `banked <date> · charm failed: <reason>` — previously an em-dash under a confident banked label |
| charm fields null, no error | `banked <date> · charm not served` |
| `charm_book_scope` absent | `banked <date> · book scope unknown` — never a fabricated `full_chain_banked` |
| a date missing | `banked pair — date unknown` / `banked — date unknown` |
| `available: false` | the server's own `reason`, truncated |
| module failed to load | `provenance module not loaded` — the row says so rather than rendering a blank |

## Why this is a fix and not a restyle

`charm_book_scope` exists because `compute_net_charm` runs on ONE selected expiry while
`compute_charm_by_strike` runs on the whole chain (RC-288, `server.py:1687`). On this screen
charm is printed beside whole-book GEX. Without the scope the operator cannot tell whether
the two numbers cover the same book — which is a risk-reading hazard, not a cosmetic one.

## Verification commands

```
node tests/forces_provenance_node.mjs
python -m pytest tests/test_forces_provenance_v1.py tests/test_exposure_tab_v1.py
```

`tests/test_exposure_tab_v1.py::test_chart_charm_and_bias_live_contract` is the independent
witness: it asserted the chart reads `charm_book_scope`, it had been failing, and it is green
with this change. The node assertions CALL the real function (RC-298) — a mutation that
restores the shared label fails them, checked by reintroducing it.

## Deletions

No feature, row or cell removed. `git diff --cached --numstat static/chart.html` reports
**23 insertions / 6 deletions**, and the six deleted lines are exactly the replaced label:
the three-line `const bankSrc = ...` expression and the three call sites that passed it. The
rendered DOM read above is the independent check that the adjacent features survived — all
five FORCES rows (`fr-gex`, `fr-ov`, `fr-doi`, `fr-dex`, `fr-charm`) are present and the
Reading line still populates.
