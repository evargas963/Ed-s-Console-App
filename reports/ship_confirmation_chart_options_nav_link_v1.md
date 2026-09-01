# Ship confirmation — `static/chart.html` Options nav entry (OPTIONS_ORDER_FLOW_V1)

Surface: **`static/chart.html`** (approved design surface, registry variant `v6-full-page`).
Change: add one `<a class="cv-tab" href="/options">Options</a>` entry to the existing
`.cv-nav` tab bar (same component, same pattern as the pre-existing Desk/Exposure links).
Nothing else on the surface is touched — no chart lines, gamma panel, levels, or forces
strip logic is edited.

RC-194 exists because a prior Chart build shipped verified by structure and tests only, and
the operator found real defects in the first rendered pixel. This confirmation is built on
an actual rendered frame, not on structure alone.

## RENDERED-FRAME evidence

Started the dev-worktree server (`server:app --app-dir <this worktree>`, real Schwab token,
port 8011) and loaded `/chart?ticker=SPY` in the browser. The nav bar rendered as:
`Console | Terrain | Chart (selected) | Desk | Exposure | Options` — the new tab sits after
Exposure, styled identically to the other `.cv-tab` links (same font, spacing, hover state;
no layout shift or overlap). The rest of the page (levels pulldown, timeframe buttons,
FORCES strip, gamma-panel-below banner) rendered exactly as before — this dev DB is freshly
seeded so it shows the app's own honest "Terrain unavailable" / "NO BARS YET" empty states,
which is pre-existing behavior unrelated to this change, not something this edit caused.

Confirmed interactively: `find("Options")` on the loaded page resolved to
`link "Options" href="/options"` — the new tab is a real, correctly-targeted link, not dead
markup.

## FEATURE-BY-FEATURE confirmation

| Feature | Required | Verified |
|---|---|---|
| New Options nav entry | ADDED | `<a class="cv-tab" href="/options">Options</a>` present, renders in the tab bar |
| Existing nav entries (Console/Terrain/Chart/Desk/Exposure) | UNCHANGED | all five still present, same hrefs, same order |
| Chart canvas / gamma panel / levels / FORCES strip | UNCHANGED | diff is a single added `<a>` line inside `.cv-nav`; no other line touched |
| `# ui-mockup-ok:` escape declared for this non-redesign edit | REQUIRED | present immediately above the new line (RC-186 escape, same convention as the pre-existing Exposure nav-entry comment on the line above it) |

## Scope statement

This is a **net-new page's nav-discoverability wiring**, not a redesign of Chart: no
element on the approved `v6-full-page` surface moves, changes, or is removed. The only
diff is one additional link in the shared tab component, mirroring the exact pattern
already used to add the Exposure tab (RC-200).
