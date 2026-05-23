---
name: Redesigns must be genuinely different, not variations on a theme
description: When proposing N design alternatives, each must come from a different philosophy/primitive — not 3 versions of "rearrange the same blocks"
type: feedback
originSessionId: b724fbb2-9fd1-49e3-a3a2-f6ee89a57d27
---
When the operator asks for N alternative designs, they want N **genuinely different** approaches, not N variations on the same layout pattern. Caught 2026-05-18 when I proposed 3 horizon-dashboard redesigns that all kept the existing `.block` + `.kv` (key/value label-rows) primitive and only varied the arrangement (consolidate vs 3-column vs collapsible). Operator response: "i don't like any of them."

**Why:** The operator likes the 4 horizon cards at the top because they use *visual primitives* (color-coded card, arrow, dot, big number, confidence band). The rest of the dashboard is `.block` + `.kv` text rows — visually flat and dense. All 3 of my mockups kept that primitive intact and only moved cards around. None of them addressed the actual problem (visual primitive mismatch).

**How to apply:**
- When asked for multiple designs, make each one start from a different *primitive set* — e.g. one with bars/gauges, one with sparklines/trend chips, one with heat-map zones — not 3 versions of "the same form, fewer rows."
- Operator pattern preference: prefers visual primitives over label/value text rows for at-a-glance scanning. Match the visual density of the things they already like (top horizon cards) rather than the things they're trying to fix (label-value blocks).
- If unsure which primitive direction matches the operator's mental model, ask one specific question first instead of proposing 3 variations of one direction.
- "I don't like any of them" usually means the dimension being varied was wrong, not that the variations within that dimension were bad.
