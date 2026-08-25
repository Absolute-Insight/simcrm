# Vectora Lux phase 2 — Command Center dashboard (design)

**Date:** 2026-08-25
**Status:** Approved (user picked "Option A — Command Center" from the design
canvas: https://claude.ai/code/artifact/3fc1ee7e-60b6-441b-95bf-e7e6408ce72d)
**Builds on:** `2026-08-25-vectora-lux-dashboard-design.md` (glass tokens, glow
charts — already on branch `feat/vectora-lux-dashboard`, PR #127)

## What we are building

The full layout redesign the first pass deliberately excluded. The dashboard
page is restructured to the approved Option A mockup: a four-tile KPI band
with dramatic numerals, a hero trend chart, a radial-gauge rail for the two
percentage metrics, and the existing panels/chart-grid restyled beneath. Dark
becomes the app's default theme. The mockup is the visual authority; this
spec maps it onto the real, role-aware dashboard.

## Decisions (settled with the user)

| Question | Decision |
|---|---|
| Structure freedom | **Full redesign** — arrangement and presentation change; all data, drilldowns, panel hide/reorder, and the manager grid's edit mode keep working. |
| Direction | **Option A — Command Center** (bento: KPI band → hero + gauges → panels → chart grid). |
| Theme default | **Dark by default**: a visitor with no stored preference gets dark; stored preferences (light/dark/system) are always respected. |
| Chart palette | The dark series palette is rebuilt to pass the color-blind separation validator (the current one fails deutan checks); anchored on brand hues `#5b5fe8`, `#0d9488`, `#d33fd1`, `#d97706`. Light palette unchanged this phase. |

## Layout (both roles, top to bottom)

1. **Header** — unchanged mechanics: LayoutHeader (breadcrumbs,
   Refresh/Edit/Save buttons), then the filter row (period preset, user,
   territory). Filters keep their components; only spacing/styling may be
   touched lightly.
2. **KPI band** — the first four tile-catalogue entries (`total_leads`
   [team-only], `ongoing_deals`, `won_deals`, `deals_at_risk`) as restyled
   StatTiles: 10px uppercase letterspaced label, ~40px display numeral,
   delta beside the numeral. `deals_at_risk` gets a danger accent (red-tinted
   border + red label via the `-9`/dark-safe ink treatment already in use).
   Drilldowns, loading skeletons, error/retry, unfiltered-territory notes all
   keep working exactly as today.
3. **Hero row** (grid: 2/3 + 1/3):
   - **Hero chart**: the `sales_trend` axis chart, rendered large (~300px)
     for **both** roles via a single always-on chart resource. The rep chart
     strip drops its `sales_trend` entry (the hero replaces it) and keeps
     `funnel_conversion`. The manager grid is left untouched; if its saved
     layout also contains the sales trend, that duplication far below the
     fold is accepted this phase rather than risking layout-identity
     heuristics.
   - **Gauge rail**: two `RadialGauge` cards replacing the `plan_adherence`
     and `quota_attainment` StatTiles. A gauge shows an SVG ring (brand
     sky→indigo gradient stroke, glow in dark mode), the percentage in
     display type at center, label + server hint text + delta beside it.
     Value is clamped to 0–100 for the ring; the number shows the server's
     value as-is. States mirror StatTile: skeleton while loading, inline
     retry on error, drill-through click when the tile is drillable,
     unfiltered-territory note when the server flags it.
4. **Panels** — the existing PanelCard catalogue (attention / today /
   adherence / pipeline / quota by role), same hide/reorder machinery. One
   presentation upgrade: the **pipeline** panel renders gradient progress
   bars (share of the largest stage) instead of a plain table; other panels
   keep their current row rendering. The forecasting-off notice keeps its
   place and meaning.
5. **Chart grid** (managers) — untouched functionally; it already wears the
   glass/glow treatment from phase 1.

## Components

| Piece | Change |
|---|---|
| `frontend/src/utils/gauge.js` (new) | Pure ring math: clamp + stroke-dasharray for a given radius. Unit-tested. |
| `frontend/src/components/Dashboard/RadialGauge.vue` (new) | The gauge card described above. Consumes the same tile resource shape StatTile does. |
| `frontend/src/components/Dashboard/StatTile.vue` | Uppercase label, larger numeral, `accent` prop (`'danger'`) for the critical tile. |
| `frontend/src/pages/Dashboard.vue` | The restructure: tile split, hero resource + section, gauge rail, pipeline bars. |
| `frontend/src/utils/chartTheme.js` | New `DARK_SERIES` (validator-passing, 8 colors, brand-anchored). |
| `frontend/src/index.css` | `.v-kpi-label` utility (10px/600/0.09em/uppercase, muted ink); anything else stays Tailwind-inline. |
| `frontend/src/main.js` | Seed `localStorage.theme = 'dark'` when unset, before app mount (frappe-ui's `useColorScheme` then restores it as a normal stored preference). |

## Non-goals

- No backend changes; every number comes from the endpoints already called.
- No new data series (no sparklines in KPI tiles — no per-tile trend data
  exists server-side).
- No changes to Reports, Planner, or the app shell/sidebar.
- Light theme keeps the same new layout with phase 1's light treatment
  (solid cards, no glow); it is restyled by inheritance, not designed anew.
- The manager grid's saved layouts are not migrated or filtered.

## Accessibility constraints (hard)

- All text on ink tokens; colored text at the `-9` step; orange for
  warnings, never amber (existing rules).
- The gauge's percentage and hint are real text; the ring is decorative.
  Empty/zero states keep their server-provided explanation visible.
- Contrast floor 4.5:1 for body text in both themes, verified in the
  browser in both roles' views.
- KPI drill targets remain buttons with accessible names, as today.

## Verification

1. `cd frontend && yarn test:run` — including new gauge and palette tests.
2. Playwright: dashboard as Administrator (team view) in dark and light;
   the rep-relevant states exercised at minimum via the team view's
   user-filter; screenshots delivered.
3. `pre-commit run` on changed files.
