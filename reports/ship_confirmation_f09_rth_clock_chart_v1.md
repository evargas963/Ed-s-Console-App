# SHIP CONFIRMATION — static/chart.html (F09 RTH clock consumer, RC-411)

**Surface:** static/chart.html (approved v6 design surface). This change is a clock-source
collapse, not a Chart redesign: `etSessionTag` still returns `null` / `PRE-MKT` / `AFTER-HRS`
with the same labels; only the minute cut reads `window.ED_RTH_START_MINS` /
`window.ED_RTH_END_MINS` from `GET /static/rth_clock_authority.js` (request-time
projection of `time_et.rth_clock_js_source`; not a committed static blob).

## RENDERED-FRAME evidence

Same-turn TestClient after app lifespan (`tests/test_single_producer_batch_f02_f13_v1.py::test_f11_api_state_volume_fallback_triple_after_lifespan`):

- `GET /static/rth_clock_authority.js` → `200`, body byte-equal to live `time_et.rth_clock_js_source()` (`window.ED_RTH_START_MINS=570;\nwindow.ED_RTH_END_MINS=960;\n`). A planted disk blob with 111/222 is not returned (`test_f09_ui_clock_cannot_serve_stale_disk_or_prior_constants`).
- Chart HTML head loads that script before `etSessionTag` runs. No canvas layout, palette, pill, or forces-strip change is in this diff.

Visual contract of `etSessionTag` is unchanged: weekday RTH → no tag; weekday before open → `PRE-MKT`; else `AFTER-HRS`; missing constants fail closed to `UNKNOWN` (no second 570/960 encoding).

## FEATURE-BY-FEATURE against the approved surface

| feature | approved behavior | this change |
|---|---|---|
| Candles + levels chart | v6 canvas | untouched |
| Session tag | PRE-MKT / AFTER-HRS / hidden in RTH | same strings; cut from served `time_et` |
| Gamma panel / forces strip | approved v6 | untouched |
| Fail-closed clock | must not invent RTH | `NaN` constants → `UNKNOWN` |

**Locks:** `tests/test_single_producer_batch_f02_f13_v1.py::test_rc345_rth_clock_boundary_has_one_authority` asserts Chart does not re-encode `mm >= 570` / `mm < 960`.
