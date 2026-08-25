# Vectora Lux Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the CRM dashboard a premium dark-glassmorphism treatment — ambient staged background, glass cards, display numerals, glowing gradient charts — with the light theme receiving a refined conventional polish.

**Architecture:** A reusable token layer: glass-surface CSS variables and a `.v-glass` utility plus a dark-only `.v-lux-stage` background in `frontend/src/index.css`; a pure chart-config transform in `frontend/src/utils/chartTheme.js` that injects ECharts glow/gradient options through frappe-ui's `echartOptions` passthrough. Dashboard components consume both. No frappe-ui changes, no theme-generator changes.

**Tech Stack:** Vue 3, Tailwind (frappe-ui preset), frappe-ui experimental charts (ECharts), Vitest.

**Spec:** `docs/superpowers/specs/2026-08-25-vectora-lux-dashboard-design.md`

## Global Constraints

- Branch: `feat/vectora-lux-dashboard`. Pre-commit hooks rewrite files — `git add` the result and re-commit; never `--no-verify`.
- Never hand-edit `frontend/src/styles/vectora-theme.css` (generated).
- All text stays on existing ink tokens; colored text uses the `-9` step only (`text-ink-green-9`, `text-ink-red-9`, `text-ink-orange-9`); orange for warnings, never amber.
- Glow/gradients are decorative only — never the sole carrier of meaning.
- `backdrop-filter` appears only on `.v-glass` cards, never nested.
- Light theme: no blur, no glow — solid surfaces, gradient chart fills only.
- All commands run from `/workspace/frontend` unless stated otherwise.
- Verify before claiming done: `yarn test:run` must pass; visual verification in **both** themes (Task 4).

---

### Task 1: Chart glow/gradient transform in chartTheme.js

**Files:**
- Modify: `frontend/src/utils/chartTheme.js`
- Test: `frontend/tests/unit/chartTheme.test.js` (create)

**Interfaces:**
- Consumes: existing `LIGHT_SERIES`, `DARK_SERIES`, `isDark()`, `withVectoraTheme(config)` in the same file (shown below in context).
- Produces: `export function hexToRgba(hex, alpha): string`; `export function applyLuxChartTheme(config, dark): config` (pure); `export function withVectoraLux(config): config` (wraps `applyLuxChartTheme` with `isDark()`). Task 3 imports `withVectoraLux` in `DashboardItem.vue`. `withVectoraTheme` remains exported and unchanged.

Context you need: `chartTheme.js` currently exports `chartSeriesColors()` and `withVectoraTheme(config)`; the palettes are module-local constants `LIGHT_SERIES` / `DARK_SERIES` (8 hex colors each, first entry `#5b5fe8` light). frappe-ui's `AxisChart` merges each series' `echartOptions` **last** via a deep merge (`mergeDeep(standardSeriesOptions, seriesTypeOptions, s.echartOptions)`), so options we place in `series[i].echartOptions` reach ECharts, and deep-merge with e.g. `lineStyle.width` from frappe-ui. We spread the caller's existing `echartOptions` **after** ours so a caller's explicit choices win.

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/unit/chartTheme.test.js`:

```js
import { describe, expect, it } from 'vitest'
import {
  applyLuxChartTheme,
  hexToRgba,
  withVectoraTheme,
} from '@/utils/chartTheme'

function axisConfig(overrides = {}) {
  return {
    data: [],
    title: 'Revenue',
    xAxis: { key: 'month', type: 'category' },
    yAxis: {},
    series: [
      { name: 'won', type: 'line' },
      { name: 'lost', type: 'bar' },
      { name: 'pipeline', type: 'area' },
    ],
    ...overrides,
  }
}

describe('hexToRgba', () => {
  it('converts a hex color and alpha to an rgba() string', () => {
    expect(hexToRgba('#5b5fe8', 0.5)).toBe('rgba(91, 95, 232, 0.5)')
  })

  it('handles full alpha', () => {
    expect(hexToRgba('#000000', 1)).toBe('rgba(0, 0, 0, 1)')
  })
})

describe('applyLuxChartTheme', () => {
  it('passes through nullish and non-object configs', () => {
    expect(applyLuxChartTheme(null, true)).toBe(null)
    expect(applyLuxChartTheme(undefined, false)).toBe(undefined)
  })

  it('never overrides a config that set its own colors', () => {
    const config = axisConfig({ colors: ['#123456'] })
    expect(applyLuxChartTheme(config, true)).toBe(config)
  })

  it('applies the series palette to configs without series (donut/number)', () => {
    const config = { title: 'Sources', data: [] }
    const dark = applyLuxChartTheme(config, true)
    const light = applyLuxChartTheme(config, false)
    expect(dark.colors).toHaveLength(8)
    expect(light.colors).toHaveLength(8)
    expect(dark.colors).not.toEqual(light.colors)
  })

  it('gives line series a same-hue glow in dark mode only', () => {
    const dark = applyLuxChartTheme(axisConfig(), true)
    const light = applyLuxChartTheme(axisConfig(), false)
    const darkLine = dark.series[0].echartOptions.lineStyle
    expect(darkLine.shadowBlur).toBe(14)
    expect(darkLine.shadowColor).toMatch(/^rgba\(/)
    expect(light.series[0].echartOptions?.lineStyle).toBeUndefined()
  })

  it('derives the glow from the series own color when one is set', () => {
    const config = axisConfig({
      series: [{ name: 'won', type: 'line', color: '#ff0000' }],
    })
    const themed = applyLuxChartTheme(config, true)
    expect(themed.series[0].echartOptions.lineStyle.shadowColor).toBe(
      'rgba(255, 0, 0, 0.4)',
    )
  })

  it('gives bar series a vertical gradient fill in both modes', () => {
    for (const dark of [true, false]) {
      const themed = applyLuxChartTheme(axisConfig(), dark)
      const fill = themed.series[1].echartOptions.itemStyle.color
      expect(fill.type).toBe('linear')
      expect(fill.colorStops).toHaveLength(2)
      expect(fill.colorStops[0].color).toMatch(/^rgba\(/)
    }
  })

  it('gives line and area series a gradient area fill fading to transparent', () => {
    const themed = applyLuxChartTheme(axisConfig(), false)
    for (const idx of [0, 2]) {
      const fill = themed.series[idx].echartOptions.areaStyle.color
      expect(fill.type).toBe('linear')
      expect(fill.colorStops[1].color).toMatch(/, 0\)$/)
    }
  })

  it('lets a caller-supplied echartOptions key win over the lux one', () => {
    const lineStyle = { width: 4 }
    const config = axisConfig({
      series: [{ name: 'won', type: 'line', echartOptions: { lineStyle } }],
    })
    const themed = applyLuxChartTheme(config, true)
    expect(themed.series[0].echartOptions.lineStyle).toBe(lineStyle)
  })

  it('does not mutate the input config', () => {
    const config = axisConfig()
    const snapshot = JSON.stringify(config)
    applyLuxChartTheme(config, true)
    expect(JSON.stringify(config)).toBe(snapshot)
  })
})

describe('withVectoraTheme (existing contract)', () => {
  it('still applies the palette without touching explicit colors', () => {
    expect(withVectoraTheme({ colors: ['#abc'] }).colors).toEqual(['#abc'])
    expect(withVectoraTheme({}).colors).toHaveLength(8)
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd /workspace/frontend && yarn test:run tests/unit/chartTheme.test.js`
Expected: FAIL — `applyLuxChartTheme` and `hexToRgba` are not exported.

- [ ] **Step 3: Implement the transform**

Append to `frontend/src/utils/chartTheme.js` (after the existing `withVectoraTheme` export):

```js
/**
 * Vectora Lux — the dashboard's glow treatment, expressed purely as config.
 *
 * frappe-ui's charts merge each series' `echartOptions` into the final ECharts
 * series (caller-last), which is the whole mechanism here: the glow, gradients,
 * and fades below are plain data injected through that seam. Dark mode gets a
 * same-hue glow under lines and gradient fills; light mode gets the gradient
 * fills only. A config that chose its own colors is left entirely alone, same
 * contract as withVectoraTheme.
 */
const LINE_GLOW = { blur: 14, alpha: 0.4, offsetY: 6 }

export function hexToRgba(hex, alpha) {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

function verticalFade(hex, topAlpha, bottomAlpha) {
  return {
    type: 'linear',
    x: 0,
    y: 0,
    x2: 0,
    y2: 1,
    colorStops: [
      { offset: 0, color: hexToRgba(hex, topAlpha) },
      { offset: 1, color: hexToRgba(hex, bottomAlpha) },
    ],
  }
}

export function applyLuxChartTheme(config, dark) {
  if (!config || typeof config !== 'object') return config
  if (config.colors?.length) return config
  const palette = dark ? [...DARK_SERIES] : [...LIGHT_SERIES]
  if (!Array.isArray(config.series)) return { ...config, colors: palette }

  const series = config.series.map((s, index) => {
    const hue = s.color || palette[index % palette.length]
    const lux = {}
    if (s.type === 'bar') {
      lux.itemStyle = { color: verticalFade(hue, 1, dark ? 0.5 : 0.7) }
    }
    if (s.type === 'line' || s.type === 'area') {
      if (dark) {
        lux.lineStyle = {
          shadowBlur: LINE_GLOW.blur,
          shadowColor: hexToRgba(hue, LINE_GLOW.alpha),
          shadowOffsetY: LINE_GLOW.offsetY,
        }
      }
      lux.areaStyle = {
        color: verticalFade(hue, dark ? 0.32 : 0.22, 0),
        opacity: 1,
      }
    }
    if (!Object.keys(lux).length) return s
    return { ...s, echartOptions: { ...lux, ...s.echartOptions } }
  })

  return { ...config, colors: palette, series }
}

export function withVectoraLux(config) {
  return applyLuxChartTheme(config, isDark())
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /workspace/frontend && yarn test:run tests/unit/chartTheme.test.js`
Expected: PASS (all tests). Then run the full suite: `yarn test:run` — everything passes.

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add frontend/src/utils/chartTheme.js frontend/tests/unit/chartTheme.test.js && git commit -m "feat: lux chart transform — glow lines, gradient fills, pure config

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Glass tokens and dashboard stage in index.css

**Files:**
- Modify: `frontend/src/index.css`

**Interfaces:**
- Consumes: existing tokens `--surface-base`, `--surface-elevation-2`, `--outline-gray-1` from the generated theme; the `[data-theme='dark']` attribute convention.
- Produces: `.v-glass` (surface class used by Task 3 on StatTile, PanelCard, DashboardItem, Dashboard chart cards) and `.v-lux-stage` (dark-only page background used by Task 3 on the dashboard scroll container). CSS variables `--v-glass-bg`, `--v-glass-border`, `--v-glass-shadow`.

- [ ] **Step 1: Add the Lux layer**

In `frontend/src/index.css`, insert the following block immediately after the `.v-number-card .text-ink-green-6` rule (which ends with `}` after `color: var(--ink-green-9);`) and before the `/* Slim, token-colored scrollbars everywhere. */` comment:

```css
/* Vectora Lux — glass surfaces and the dashboard stage.

   One surface class, two renderings. Light theme: a solid card with a hairline
   border and a soft two-layer shadow — premium but conventional, per the
   design spec. Dark theme: translucent glass over the stage — a lit top rim,
   a low-alpha fill, and blur. The blur lives ONLY on .v-glass cards and cards
   never nest, which is what keeps the paint cost bounded. */
:root {
  --v-glass-bg: var(--surface-elevation-2);
  --v-glass-border: var(--outline-gray-1);
  --v-glass-shadow:
    0 1px 2px rgba(16, 24, 40, 0.05),
    0 10px 28px -14px rgba(16, 24, 40, 0.14);
}
[data-theme='dark'] {
  --v-glass-bg: rgba(255, 255, 255, 0.04);
  --v-glass-border: rgba(255, 255, 255, 0.09);
  --v-glass-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.07),
    0 14px 36px -18px rgba(0, 0, 0, 0.6);
}
.v-glass {
  background: var(--v-glass-bg);
  border: 1px solid var(--v-glass-border);
  box-shadow: var(--v-glass-shadow);
}
[data-theme='dark'] .v-glass {
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
}

/* The stage the glass sits on. Light theme is untouched — the class exists so
   the dark theme has somewhere to hang its depth: two faint brand glows (the
   gradient's own sky and magenta ends) and a vignette toward the edges. */
[data-theme='dark'] .v-lux-stage {
  background:
    radial-gradient(
      55rem 38rem at 12% -8%,
      rgba(33, 171, 251, 0.07),
      transparent 60%
    ),
    radial-gradient(
      48rem 34rem at 96% 108%,
      rgba(223, 95, 235, 0.06),
      transparent 60%
    ),
    radial-gradient(
      120rem 80rem at 50% 40%,
      var(--surface-base) 30%,
      color-mix(in srgb, var(--surface-base) 88%, black) 100%
    );
}
```

- [ ] **Step 2: Verify the app still builds and serves**

Run: `cd /workspace/frontend && yarn dev` in the background (needs `yarn install` in `frontend/` and `frappe-ui/` once per container; backend via `cd /workspace/frappe-bench && bench start` in the background). Load `http://localhost:<vite-port>/crm` and confirm the app renders with no console errors. Nothing visible changes yet — no markup uses the classes.

- [ ] **Step 3: Commit**

```bash
cd /workspace && pre-commit run --files frontend/src/index.css; git add frontend/src/index.css && git commit -m "feat: v-glass surface tokens and dark dashboard stage (Vectora Lux)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Apply the Lux layer to the dashboard components

**Files:**
- Modify: `frontend/src/components/Dashboard/StatTile.vue`
- Modify: `frontend/src/components/Dashboard/PanelCard.vue`
- Modify: `frontend/src/components/Dashboard/DashboardItem.vue`
- Modify: `frontend/src/pages/Dashboard.vue`

**Interfaces:**
- Consumes: `.v-glass` / `.v-lux-stage` from Task 2; `withVectoraLux(config)` from Task 1.
- Produces: no new interfaces — visual consumption only.

All edits below are exact string replacements against the current files.

- [ ] **Step 1: StatTile — glass surface + display numeral**

In `frontend/src/components/Dashboard/StatTile.vue`:

Replace (root element class, currently line 14):

```
    class="v-stat-tile group relative flex min-h-[6.5rem] w-full flex-col justify-between gap-2 rounded-6 border border-outline-gray-1 bg-surface-elevation-2 p-4 text-left"
```

with:

```
    class="v-stat-tile v-glass group relative flex min-h-[6.5rem] w-full flex-col justify-between gap-2 rounded-6 p-4 text-left"
```

Replace (headline numeral class, currently line 67):

```
        class="font-display text-2xl font-medium tracking-tight text-ink-gray-9"
```

with:

```
        class="font-display text-3xl-semibold tracking-tight text-ink-gray-9"
```

(`text-3xl-semibold` is an existing frappe-ui composite type utility — e.g. `Welcome.vue` uses it — and `[class*='text-3xl-']` already selects the display face in `index.css`.)

Leave the `hover:border-outline-gray-2 hover:shadow-sm` clickable classes as they are — they still work over `.v-glass` (Tailwind's border-color/shadow utilities override the class's longhand values).

- [ ] **Step 2: PanelCard — glass surface**

In `frontend/src/components/Dashboard/PanelCard.vue`, replace (section class, currently line 16):

```
    class="group/panel flex min-w-0 flex-col rounded-6 border border-outline-gray-1 bg-surface-elevation-2"
```

with:

```
    class="group/panel v-glass flex min-w-0 flex-col rounded-6"
```

The header's internal `border-b border-outline-gray-1` hairline stays.

- [ ] **Step 3: DashboardItem — glass chart cards + lux chart theme**

In `frontend/src/components/Dashboard/DashboardItem.vue`:

Replace the number-card class (currently line 5):

```
      class="v-number-card flex h-full w-full rounded-4 shadow overflow-hidden cursor-pointer"
```

with:

```
      class="v-number-card v-glass flex h-full w-full rounded-4 overflow-hidden cursor-pointer"
```

Replace the axis-chart class (currently line 25):

```
      class="relative h-full w-full rounded-5 bg-surface-base shadow"
```

with:

```
      class="v-glass relative h-full w-full rounded-5"
```

Replace the donut-chart class (currently line 33):

```
      class="relative h-full w-full rounded-5 bg-surface-base shadow overflow-hidden"
```

with:

```
      class="v-glass relative h-full w-full rounded-5 overflow-hidden"
```

Replace the import (currently line 42):

```
import { withVectoraTheme } from '@/utils/chartTheme'
```

with:

```
import { withVectoraLux } from '@/utils/chartTheme'
```

Replace (currently line 56):

```
const themed = computed(() => withVectoraTheme(props.item.data))
```

with:

```
const themed = computed(() => withVectoraLux(props.item.data))
```

The spacer div keeps `bg-surface-base` — it is an editing placeholder, not a card.

- [ ] **Step 4: Dashboard.vue — stage wrapper and chart-grid cards**

In `frontend/src/pages/Dashboard.vue`:

Replace the scroll container (currently line 144):

```
    <div class="w-full flex-1 overflow-y-auto px-5 pb-6">
```

with:

```
    <div class="v-lux-stage w-full flex-1 overflow-y-auto px-5 pb-6">
```

The chart-grid card wrapper (currently line 352) shows a bordered frame around a DashboardItem that is now glass itself — a double frame. Replace:

```
            class="h-72 overflow-hidden rounded-6 border border-outline-gray-1"
```

with:

```
            class="h-72 overflow-hidden rounded-6"
            :class="
              chart.resource.loading || chart.resource.error ? 'v-glass' : ''
            "
```

so the wrapper only paints its own surface while it is showing the skeleton or error state (when DashboardItem is not rendered inside it).

- [ ] **Step 5: Run the unit tests**

Run: `cd /workspace/frontend && yarn test:run`
Expected: PASS — these are template-only changes plus a renamed import; the chartTheme tests from Task 1 cover the new call.

- [ ] **Step 6: Commit**

```bash
cd /workspace && pre-commit run --files frontend/src/components/Dashboard/StatTile.vue frontend/src/components/Dashboard/PanelCard.vue frontend/src/components/Dashboard/DashboardItem.vue frontend/src/pages/Dashboard.vue; git add -A frontend/src && git commit -m "feat: dashboard consumes v-glass surfaces, stage, and lux charts

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Visual verification in both themes (and fixes it surfaces)

**Files:**
- Possibly modify: `frontend/src/index.css`, `frontend/src/utils/chartTheme.js` (+ its test) — only if the checks below demand it.

**Interfaces:**
- Consumes: everything above, running in the real app.
- Produces: screenshots of both themes delivered to the user; any contrast fixes.

- [ ] **Step 1: Run the app**

```bash
cd /workspace/frappe-bench && bench start   # background; web on :8000
cd /workspace/frontend && yarn dev          # background; note the vite port
```

If POSTs 400: `bench --site dev.localhost set-config ignore_csrf 1` (dev only). If the Playwright browser is missing: `sudo env "PATH=$PATH" npx playwright install chrome`.

- [ ] **Step 2: Screenshot the dashboard in both themes**

With the Playwright browser tools: navigate to `http://localhost:<vite-port>/crm`, log in as `Administrator` / `admin`, open the Dashboard page. For each theme, set it explicitly before screenshotting:

```js
// browser_evaluate, dark:
localStorage.setItem('theme', 'dark')
document.documentElement.setAttribute('data-theme', 'dark')
// then reload; and the same with 'light' for the light pass
```

Take a full-page screenshot per theme.

- [ ] **Step 3: Check the checklist against the screenshots**

Dark theme: stage glows visible but faint; cards read as glass (rim, translucency); tile labels (`text-ink-gray-6`), values (`text-ink-gray-9`), hints (`text-ink-gray-5`), deltas (`-9` inks), and panel text are all comfortably legible on the glass; chart lines glow; bars have gradients; nothing is clipped. Spot-check the worst-looking label with `browser_evaluate` + `getComputedStyle` and compute its contrast against the sampled card background; the floor is 4.5:1 for body text. Light theme: **no** glass/glow/stage bleed-through; cards look like the pre-change cards with a slightly softer shadow; charts show gradient fills but no glow; nothing else regressed.

- [ ] **Step 4 (conditional): fade the grid lines in dark mode**

Only if the dark screenshots show axis grid lines fighting the glow, extend `applyLuxChartTheme` — inside the `Array.isArray(config.series)` branch, change the final return to also fade the y-axis split lines (caller still wins):

```js
  const darkAxes = dark
    ? {
        yAxis: {
          ...config.yAxis,
          echartOptions: {
            splitLine: {
              lineStyle: { color: 'rgba(255, 255, 255, 0.08)' },
            },
            ...config.yAxis?.echartOptions,
          },
        },
      }
    : {}

  return { ...config, colors: palette, series, ...darkAxes }
```

And add this test to `chartTheme.test.js`:

```js
  it('fades y-axis split lines in dark mode without clobbering caller axis options', () => {
    const dark = applyLuxChartTheme(axisConfig(), true)
    expect(dark.yAxis.echartOptions.splitLine.lineStyle.color).toBe(
      'rgba(255, 255, 255, 0.08)',
    )
    expect(applyLuxChartTheme(axisConfig(), false).yAxis.echartOptions).toBeUndefined()
  })
```

Re-run `yarn test:run` and re-screenshot dark before proceeding.

- [ ] **Step 5: Deliver the screenshots and finish**

Send both screenshots to the user. Then the full gate:

```bash
cd /workspace/frontend && yarn test:run
cd /workspace && pre-commit run --files $(git diff --name-only develop...HEAD -- frontend | tr '\n' ' ')
```

Expected: tests pass, hooks clean (re-add and re-commit if hooks rewrote files).

- [ ] **Step 6: Commit any fixes from this task**

```bash
cd /workspace && git add -A frontend && git commit -m "fix: dark-mode polish from visual pass (contrast/grid-line adjustments)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Skip the commit if the visual pass required no changes.
