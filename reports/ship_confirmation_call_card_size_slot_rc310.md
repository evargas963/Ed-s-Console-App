# Ship confirmation — static/index.html Call-card size slot (RC-310) — FEATURE-BY-FEATURE against actual code, RENDERED-FRAME verified

Operator law (non-negotiable, 2026-08-02): *"you are to always confirm first with actual code
before you ship."*

**Scope of the change.** One slot on the Call card, plus one new pure helper. No layout, no
new element, no removed element. What changes on the operator's screen: when the producer
supplies risk units but no prose sizing cue, the size line now shows a number instead of
staying blank.

## The defect, measured

`static/index.html` rendered the slot as:

```
T('cv2-c-size', fstr(s.size_cue, s.sizing_summary, s.r_units));
```

`fstr` is defined in the same closure and returns the first argument satisfying
`typeof v === 'string' && v.trim()`. `r_units` is a float from `signal_types.TheCall`
(`Optional[float]`). A number fails that type test for **every possible value** — 2.5, 0,
negative — so the third argument could never be returned. The fallback had never fired: when
the producer had risk units and no prose cue, the operator saw an empty slot while a real
size existed.

The only test pointing at this field asserted `"r_units" not in HTML` — the absence of the
field NAME as a stand-in for the withhold contract. It went red when the binding appeared and
said nothing about whether the binding worked.

## FEATURE-BY-FEATURE (rule → code anchor → executed result)

| # | Rule | Code anchor | Executed |
|---|---|---|---|
| 1 | A prose sizing cue still wins | `fstr(s.size_cue, s.sizing_summary)` first | live console: slot reads `SKIP` from the producer's cue — unchanged |
| 2 | A finite number renders as risk units | `rUnitsText(s.r_units)` | `rUnitsText(2.5)` → `"2.50 R"` |
| 3 | **Zero is a real size**, not absence | `if (typeof v !== 'number' \|\| !isFinite(v)) return null` | `rUnitsText(0)` → `"0.00 R"` |
| 4 | Negative risk units still render | same | `rUnitsText(-1.25)` → `"-1.25 R"` |
| 5 | Absence stays withheld | returns `null`, slot keeps its em-dash | `null`, `undefined`, `NaN`, `Infinity`, `-Infinity`, `'2.5'`, `{}` → all `null` |
| 6 | Nothing numeric reaches `fstr` again | asserted on the slot text | `tests/test_stack_wire_3_ui_phase3_closure.py` |

## RENDERED-FRAME evidence

Live console on 127.0.0.1:8777, `/` (the Console page), read out of the **rendered DOM**
after the load cycle:

```
typeof window.rUnitsText                  -> "function"
window.rUnitsText(0)                      -> "0.00 R"
window.rUnitsText(2.5)                    -> "2.50 R"
window.rUnitsText(null)                   -> null
document.getElementById('cv2-c-size')     -> "SKIP"     (prose cue still wins)
typeof window.resolveHorizonCardVisualState -> "function"
read_console_messages(onlyErrors)         -> none
```

A screenshot could not be captured this session — the Browser pane was not compositing
frames — so the frame evidence is the rendered DOM of the live page, stated as such.

## Verification commands

```
node tests/index_html_contracts_node.mjs
python -m pytest tests/test_stack_wire_3_ui_phase3_closure.py tests/test_issue18_ui_contract.py
```

## Deletions

No element, slot or feature removed. `git diff --numstat static/index.html` for this change:
the size line is replaced in place and `rUnitsText` is added beside `n2`. The Call card's
other slots (`cv2-c-verd`, `cv2-c-sub`, `cv2-c-entry`, `cv2-c-stop`, `cv2-c-tgt`, `cv2-c-rr`,
`cv2-c-inval`) are untouched, and the live DOM read above confirms the page renders with no
console errors.
