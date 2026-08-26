# Ship confirmation — `static/chart.html` faint CALL/PUT RANGE fill removal (2026-08-26)

Surface: **`static/chart.html`** (approved design surface, registry variant `v6-full-page`).
Change: remove the two full-width `0.05`-alpha `fillRect` washes drawn by `rangeShade()` for
CALL RANGE / PUT RANGE. Nothing else on the surface is touched.

Operator instruction this satisfies (2026-08-26): *"the main price chart again shows a very faint
translucent shading/fill … Find the actual source of the current shading and remove only that faint
fill. Do not alter any chart lines, gamma flip/pin/wall lines, labels, axis tags, or the red and
green boxes around the gamma call/put areas."*

RC-194 exists because a prior Chart build shipped verified by structure and tests only, and the
operator found real defects in the first rendered pixel. So this confirmation is built on an actual
rendered frame, not on structure alone.

## RENDERED-FRAME evidence

Rendered the live surface in the browser against the running console (`/chart?ticker=SPY`,
1440x900 viewport), then measured the canvas pixels directly — quantitative, not a visual impression.

Method: sample a vertical strip of the main price canvas (`#cv`, 1169x358) at column x = 0.75·W,
every 3 px from 8% to 92% of height. Then suppress **exactly** what this change removes — any
`fillRect` whose `fillStyle` carries `0.05` alpha, which is precisely `palRgba(col, 0.05)` in
`rangeShade()` — force a redraw, and re-measure the same strip.

| Strip pixel profile | Modal plot-column colour | Wall-band colours present |
|---|---|---|
| BEFORE (shipped code, wash drawn) | `143,153,122` / `153,153,133` — tinted | red `219,116,121`, green `89,188,134` |
| AFTER (0.05-alpha fills suppressed) | `0,0,0` — clean background | red `255,92,113`, green `50,205,135` |

Reading:
* The wash is real and covers the plot column — the modal colour of most sampled rows was a tint,
  and with only those fills suppressed it collapses to the clean `0,0,0` background the candles are
  meant to read against. This is the "dulled candles" the operator reported, measured in pixels.
* **The red and green wall areas survive** the removal — they are painted by a DIFFERENT code path
  (the wall band's own `0.14`-alpha fill plus its `strokeRect` border), which this change does not
  touch. Their colours are still present after suppression (and read *more* saturated once the wash
  over them is gone).

Frames captured at both states.

## FEATURE-BY-FEATURE confirmation

Verified against the actual branch file (not the running build), each item executed:

| Feature the operator named | Required | Verified |
|---|---|---|
| Faint CALL/PUT RANGE fill | REMOVED | `palRgba(col, 0.05)` absent from the file |
| Red/green boxes around gamma call/put areas | UNCHANGED | `strokeRect(PADL, yTop` present |
| Wall band fills behind those boxes | UNCHANGED | `palRgba(PAL.red, 0.14)` present |
| Gamma FLIP line | UNCHANGED | `'gamma_flip', 'FLIP'` present |
| GSF line | UNCHANGED | `'gsf', 'GSF'` present |
| Chart lines / labels / axis tags | UNCHANGED | no other draw call altered; diff is 2 deleted `fillRect` lines + comments |
| RANGE information itself | PRESERVED, not deleted | hover tooltip (`tipHtml: tip`) and off-scale pin both retained |

Additional checks that ran clean:
* The follow-up commit adds **4 lines, all `//` comments** — verified programmatically; comments
  cannot alter parsing.
* `node --check` passes on every extracted `<script>` block of the file.
* `tests/test_chart_intent_lock_v1.py`, `tests/test_chart_accrual_consumer_v1.py`,
  `tests/test_ui_mockup_lock_v1.py` — **46 passed**, including the locks that guard this surface's
  intended visual contract.

## Scope statement

This is a **removal of a regression**, not a redesign: no layout moves, no element is added, no
approved feature is dropped. The approved `v6-full-page` spec is unchanged by it — the RANGE value
area remains available on hover and as an off-scale pin, so no computed level is lost from the
surface.
