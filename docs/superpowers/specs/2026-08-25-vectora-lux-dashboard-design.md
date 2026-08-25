# Vectora Lux — premium dashboard treatment (design)

**Date:** 2026-08-25
**Status:** Approved (user sign-off in session)
**Scope:** Dashboard page first; the visual language is built as reusable
tokens so later phases can extend it to Reports, Planner, and the app shell.

## What we are building

A premium, dark-glassmorphism restyle of the CRM dashboard, modeled on the
user's reference image: deep navy ambient background, translucent glass
cards with lit rims, large display numerals for KPIs, and charts whose
lines glow and whose bars carry gradient fills. The dark theme is the full
showcase; the light theme receives a refined but conventional polish. The
app continues to respect the user's theme choice.

## Decisions (settled with the user)

| Question | Decision |
|---|---|
| Theme strategy | **Dark-first showcase.** Dark theme gets the full glass/glow treatment; light theme gets premium polish (elevation, typography, chart gradients) without glassmorphism. No change to theme defaults. |
| Scope of this pass | **Dashboard first.** Establish the language as reusable tokens; later phases spread it. |
| Accent direction | **Brand gradient, glow-tuned.** Keep sky `#21abfb` / indigo `#5b5fe8` / magenta `#df5feb`; add glow and gradient treatments rather than shifting hue toward the reference's exact cyan/violet. |
| Implementation strategy | **Reusable token layer** in `frontend/src/index.css` + a pure chart-config transform in `frontend/src/utils/chartTheme.js`. Dashboard components consume them. |

## Visual language

### 1. Ambient stage (dark theme only)

The dashboard page's scroll container gets a staged background:

- Deep navy base (darker than the card surfaces so glass reads as glass).
- Two faint radial gradients at very low alpha: sky-blue biased toward the
  upper-left, magenta toward the lower-right.
- A soft vignette toward the edges.

Implemented as CSS on a dashboard wrapper class in `index.css`, scoped
under `[data-theme="dark"]`. The light theme keeps the current surface
untouched.

### 2. Glass cards — `.v-glass`

One utility class in `index.css`, applied to stat tiles, panel cards, and
chart cards.

Dark theme:
- Translucent surface (~4% white over the stage).
- `backdrop-filter: blur(...)` — used only on these cards, not nested, to
  bound the paint cost.
- 1px hairline border in low-alpha white.
- Inset top-edge highlight (the "lit rim").
- Soft ambient outer shadow.
- Hover: slight lift and rim brighten, using the existing motion language
  in `index.css`.

Light theme (same class, different variables):
- Solid surface; **no blur, no glow**.
- Refined two-layer elevation shadow + hairline border.

### 3. Display numerals

KPI values on stat tiles use the display type scale already defined in
`index.css`: large, tight tracking, `tabular-nums`. Labels above the value
are small and muted. Delta/trend badges use the `-9` ink steps only
(`--ink-green-9` / `--ink-red-9` / `--ink-orange-9`) per the repo's
contrast rules — orange for warnings, never amber.

### 4. Glowing charts

`chartTheme.js` grows a pure config transform layered onto the existing
`withVectoraTheme` (same contract: never overrides a config that set its
own colors):

- **Dark:** line/area series get a soft same-hue glow (`shadowBlur` +
  `shadowColor` at reduced alpha) and a vertical gradient area fill fading
  to transparent; bar series get vertical gradient fills (brand hue → a
  deeper stop of the same hue); axis lines, grid lines, and splitlines
  fade to near-invisible so the data glows against the stage.
- **Light:** gradient area/bar fills only — no glow.

The transform is pure (input config → output config) and unit-tested in
`frontend/tests/unit/`.

### 5. Non-goals

- No new widget types. The reference's radial gauge maps onto styling the
  existing donut/number widgets.
- No layout or information-architecture changes to the dashboard.
- No hand edits to the generated `vectora-theme.css`; no generator changes
  (no new text colors are introduced, so no new contrast floors to
  assert).
- No change to which theme users get by default.
- No changes to Reports, Planner, or the app shell in this pass.

## Files touched

| File | Change |
|---|---|
| `frontend/src/index.css` | Stage background, `.v-glass` tokens/effects for both themes, any small type utilities needed |
| `frontend/src/utils/chartTheme.js` | Glow/gradient config transform (pure), composed with `withVectoraTheme` |
| `frontend/tests/unit/` (new file) | Unit tests for the chart transform |
| `frontend/src/pages/Dashboard.vue` | Stage wrapper class; glass class on chart cards |
| Dashboard components (StatTile, PanelCard, `Dashboard/DashboardItem.vue`) | Consume `.v-glass`, display numerals |

## Accessibility constraints (hard)

- All text remains on existing ink tokens; colored text uses the `-9`
  step. Glow and gradients are decorative only — never the sole carrier of
  meaning.
- The dark-theme translucent surfaces must keep body text at ≥ 4.5:1
  against the effective (blurred) background; verified in the browser, not
  assumed.
- Both themes are verified visually with Playwright before commit — the
  generator's floors do not cover these hand-authored effects.

## Verification

1. `cd frontend && yarn test:run` — all unit tests pass, including the new
   chart-transform tests.
2. Playwright: load the dashboard on the dev server in **both** themes;
   screenshot; check contrast of tile labels, deltas, panel text on the
   glass surfaces; confirm light mode shows no glass/glow bleed-through
   and no regression.
3. `pre-commit run --files <changed files>`.

## Rollout (later phases, out of scope here)

Reports → Planner → app shell adopt `.v-glass` and the chart transform.
Each phase gets its own design pass; this spec covers the dashboard only.
