# Vectora Lux Command Center Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure the dashboard to the approved "Command Center" mockup — KPI band with dramatic numerals, hero trend chart, radial-gauge rail, gradient pipeline bars — plus dark-by-default theming and a validator-passing dark chart palette.

**Architecture:** New pure ring-math util + `RadialGauge.vue` component; `StatTile` restyle with a danger accent; `Dashboard.vue` layout restructure that re-wires existing resources (no backend changes); a rebuilt `DARK_SERIES`; a one-line dark-default seed in `main.js`. All existing behavior — drilldowns, panel hide/reorder, role gating, chart-grid editing — is preserved.

**Tech Stack:** Vue 3, Tailwind (frappe-ui preset), frappe-ui experimental charts, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-25-vectora-lux-command-center-design.md` (the mockup at https://claude.ai/code/artifact/3fc1ee7e-60b6-441b-95bf-e7e6408ce72d is the visual authority)

## Global Constraints

- Branch: `feat/vectora-lux-dashboard` (continues PR #127). Pre-commit hooks rewrite files — `git add` the result and re-commit; never `--no-verify`.
- Never hand-edit `frontend/src/styles/vectora-theme.css`.
- All text on existing ink tokens; colored text uses the `-9` step only; orange for warnings, never amber.
- No backend changes; no new endpoints or params beyond those already used.
- Role behavior preserved: `teamOnly` tiles never fetch or render for reps; the rep "Your trends" strip and manager chart grid keep their gating.
- All commands run from `/workspace/frontend` unless stated otherwise.
- Dark series palette must be exactly the validated set in Task 2 (validated against surface `#131521`: all six checks pass, one legal WARN on the 7↔8 adjacent pair).

---

### Task 1: Ring math + delta formatting util

**Files:**
- Create: `frontend/src/utils/gauge.js`
- Test: `frontend/tests/unit/gauge.test.js` (create)

**Interfaces:**
- Produces: `ringDash(value, radius)` → `{ pct, dasharray }` where `pct` is the value clamped to [0, 100] (non-numeric → 0) and `dasharray` is `"<filled> <rest>"` for an SVG circle of that radius; `formatDelta(delta, suffix)` → the compact signed string StatTile-style (`"+33%"`, `"−4.2%"`, `">999%"`, `""` for zero/absent). Task 3's `RadialGauge.vue` consumes both.

- [ ] **Step 1: Write the failing tests**

Create `frontend/tests/unit/gauge.test.js`:

```js
import { describe, expect, it } from 'vitest'
import { formatDelta, ringDash } from '@/utils/gauge'

describe('ringDash', () => {
  it('fills the ring proportionally to the clamped percentage', () => {
    const C = 2 * Math.PI * 58
    const { pct, dasharray } = ringDash(33, 58)
    expect(pct).toBe(33)
    const [filled, rest] = dasharray.split(' ').map(Number)
    expect(filled).toBeCloseTo(C * 0.33, 1)
    expect(filled + rest).toBeCloseTo(C, 1)
  })

  it('clamps to the 0-100 band', () => {
    expect(ringDash(140, 58).pct).toBe(100)
    expect(ringDash(-20, 58).pct).toBe(0)
  })

  it('treats non-numeric input as zero', () => {
    expect(ringDash(null, 58).pct).toBe(0)
    expect(ringDash('n/a', 58).pct).toBe(0)
    const [filled] = ringDash(undefined, 58).dasharray.split(' ').map(Number)
    expect(filled).toBe(0)
  })

  it('accepts numeric strings', () => {
    expect(ringDash('66.5', 58).pct).toBe(66.5)
  })
})

describe('formatDelta', () => {
  it('formats small deltas with sign and one decimal', () => {
    expect(formatDelta(33, '%')).toBe('+33%')
    expect(formatDelta(-4.25, '%')).toBe('−4.3%')
  })

  it('rounds three-digit magnitudes to integers', () => {
    expect(formatDelta(123.7, '%')).toBe('+124%')
  })

  it('clamps past 999 as a comparison', () => {
    expect(formatDelta(1721.4, '%')).toBe('>999%')
    expect(formatDelta(-1721.4, '%')).toBe('<−999%')
  })

  it('returns empty for zero or absent deltas', () => {
    expect(formatDelta(0, '%')).toBe('')
    expect(formatDelta(null, '%')).toBe('')
    expect(formatDelta(undefined, '%')).toBe('')
  })
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /workspace/frontend && yarn test:run tests/unit/gauge.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `frontend/src/utils/gauge.js`:

```js
/**
 * Ring math for RadialGauge, kept pure so the arc a gauge draws is testable
 * without mounting SVG. The number shown on the gauge is the server's value
 * as-is; only the drawn arc clamps to the ring's 0-100 domain.
 */
export function ringDash(value, radius) {
  const number = Number(value)
  const pct = Number.isFinite(number) ? Math.min(100, Math.max(0, number)) : 0
  const circumference = 2 * Math.PI * radius
  const filled = (circumference * pct) / 100
  return { pct, dasharray: `${filled} ${circumference - filled}` }
}

/**
 * Same display rules as StatTile's delta (see StatTile.vue): one decimal
 * under 100, integers to 999, a comparison past that — sixteen significant
 * figures of period-over-period change is noise. Zero and absent deltas
 * render as nothing rather than "+0".
 */
export function formatDelta(delta, suffix = '') {
  const value = Number(delta) || 0
  if (!value) return ''
  const sign = value > 0 ? '+' : '−'
  const magnitude = Math.abs(value)
  if (magnitude >= 1000) return `${value > 0 ? '>' : '<−'}999${suffix}`
  const rounded =
    magnitude >= 100 ? Math.round(magnitude) : Math.round(magnitude * 10) / 10
  return `${sign}${rounded}${suffix}`
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /workspace/frontend && yarn test:run tests/unit/gauge.test.js` then the full `yarn test:run`.
Expected: PASS, full suite green.

- [ ] **Step 5: Commit**

```bash
cd /workspace && git add frontend/src/utils/gauge.js frontend/tests/unit/gauge.test.js && git commit -m "feat: ring math and delta formatting for radial gauges

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Dark palette rebuild + KPI label utility + dark default

**Files:**
- Modify: `frontend/src/utils/chartTheme.js`
- Modify: `frontend/tests/unit/chartTheme.test.js`
- Modify: `frontend/src/index.css`
- Modify: `frontend/src/main.js`

**Interfaces:**
- Produces: the new `DARK_SERIES` order (used automatically by every dark chart); the `.v-kpi-label` CSS class (consumed by Tasks 3 and 4); dark-by-default boot behavior.

- [ ] **Step 1: Replace DARK_SERIES in `frontend/src/utils/chartTheme.js`**

Replace:

```js
const DARK_SERIES = [
  '#a5a8f2',
  '#7dc9fd',
  '#eb9bf3',
  '#2dd4bf',
  '#fbbf24',
  '#a78bfa',
  '#38bdf8',
  '#f472b6',
]
```

with:

```js
/* Rebuilt against the CVD validator on the dark surface #131521: the previous
   lifted pastels collapsed under deuteranopia (indigo/sky/magenta all read as
   the same blue, worst adjacent ΔE 1.8). These sit in the OKLCH L 0.48-0.67
   band and alternate hue families so adjacent series stay separable; the one
   sub-8 pair (positions 7-8) is legal because every chart carries a legend
   and direct labels as secondary encoding. */
const DARK_SERIES = [
  '#5b5fe8', // brand indigo — the primary series
  '#0d9488', // teal
  '#d33fd1', // magenta
  '#d97706', // amber
  '#7c3aed', // violet
  '#0284c7', // deep sky
  '#be185d', // deep magenta
  '#4d7c0f', // olive
]
```

- [ ] **Step 2: Pin the palette in the tests**

In `frontend/tests/unit/chartTheme.test.js`, inside the existing `describe('applyLuxChartTheme', ...)` block, add:

```js
  it('anchors the dark palette on the validated brand set', () => {
    const dark = applyLuxChartTheme({ title: 'x', data: [] }, true)
    expect(dark.colors.slice(0, 4)).toEqual([
      '#5b5fe8',
      '#0d9488',
      '#d33fd1',
      '#d97706',
    ])
  })
```

Run: `cd /workspace/frontend && yarn test:run tests/unit/chartTheme.test.js` — all pass (the new test plus the existing ones; none of the existing tests pin the old hex values).

- [ ] **Step 3: Add the KPI label utility to `frontend/src/index.css`**

Immediately after the closing brace of the `[data-theme='dark'] .v-lux-stage { ... }` rule, insert:

```css
/* KPI label — the small uppercase caption above a Command Center numeral.
   Sets shape only; callers pick the ink (gray normally, red-9 on the danger
   tile) so token contrast rules stay theirs to obey. */
.v-kpi-label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.09em;
  text-transform: uppercase;
}
```

- [ ] **Step 4: Dark by default in `frontend/src/main.js`**

At the very top of the file's executable code (immediately after the import block, before anything else runs), insert:

```js
/* Vectora ships dark-first: a visitor with no stored preference boots into
   the premium dark theme. Any stored choice — light, dark, or system — wins
   untouched; frappe-ui's useColorScheme then restores this like any other
   saved preference. */
try {
  if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'dark')
} catch {
  /* storage disabled: the browser default (system) applies */
}
```

- [ ] **Step 5: Verify + commit**

Run: `cd /workspace/frontend && yarn test:run` — green.

```bash
cd /workspace && pre-commit run --files frontend/src/utils/chartTheme.js frontend/tests/unit/chartTheme.test.js frontend/src/index.css frontend/src/main.js; git add -A frontend/src frontend/tests && git commit -m "feat: validated dark chart palette, KPI label utility, dark-first default

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: RadialGauge component + StatTile restyle

**Files:**
- Create: `frontend/src/components/Dashboard/RadialGauge.vue`
- Modify: `frontend/src/components/Dashboard/StatTile.vue`

**Interfaces:**
- Consumes: `ringDash`, `formatDelta` from `@/utils/gauge` (Task 1); `.v-kpi-label` (Task 2); `deltaTone` from `@/utils/dashboardHome` (existing).
- Produces: `RadialGauge` props — `label` (req), `value`, `suffix`, `hint`, `delta`, `deltaSuffix`, `negativeIsBetter`, `loading`, `error`, `retry`, `drilldownLabel`, `unfilteredNote` — same semantics as StatTile's; emits `drill`. StatTile gains prop `accent` (`''` | `'danger'`).

- [ ] **Step 1: Create `frontend/src/components/Dashboard/RadialGauge.vue`**

```vue
<!--
  RadialGauge — a percentage that reads at arm's length.

  The same object-in-three-states contract as StatTile (loading skeleton,
  inline retry, resolved), and the same clickable-means-button rule. The ring
  is decoration for the number: the arc clamps to 0-100 while the text shows
  the server's value untouched, and the server's hint stays visible because a
  bare percentage is a number where an answer should be.
-->
<template>
  <component
    :is="clickable ? NativeButton : 'div'"
    :type="clickable ? 'button' : undefined"
    class="v-glass group flex w-full items-center gap-5 rounded-6 p-4 text-left"
    :class="
      clickable
        ? 'cursor-pointer hover:border-outline-gray-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
        : ''
    "
    :aria-label="clickable ? drilldownLabel : undefined"
    @click="clickable && $emit('drill')"
  >
    <Skeleton
      v-if="loading"
      shape="circle"
      height="6.5rem"
      width="6.5rem"
      :label="__('Loading {0}', [label])"
    />
    <svg v-else width="104" height="104" viewBox="0 0 140 140" aria-hidden="true">
      <defs>
        <linearGradient :id="gradientId" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stop-color="#21abfb" />
          <stop offset="1" stop-color="#5b5fe8" />
        </linearGradient>
      </defs>
      <circle
        cx="70"
        cy="70"
        r="58"
        fill="none"
        class="stroke-outline-gray-1"
        stroke-width="10"
      />
      <circle
        v-if="ring.pct > 0"
        cx="70"
        cy="70"
        r="58"
        fill="none"
        :stroke="`url(#${gradientId})`"
        stroke-width="10"
        stroke-linecap="round"
        :stroke-dasharray="ring.dasharray"
        transform="rotate(-90 70 70)"
      />
      <text
        x="70"
        y="76"
        text-anchor="middle"
        class="fill-ink-gray-9 font-display"
        font-size="26"
        font-weight="600"
      >
        {{ display }}
      </text>
    </svg>

    <div v-if="error" class="flex min-w-0 flex-1 flex-col gap-1">
      <span class="text-sm text-ink-gray-7">{{ __('Could not load this') }}</span>
      <button
        v-if="retry"
        type="button"
        class="self-start rounded-4 text-sm text-ink-gray-5 underline underline-offset-2 hover:text-ink-gray-8 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        @click.stop="retry"
      >
        {{ __('Try again') }}
      </button>
    </div>
    <div v-else class="flex min-w-0 flex-1 flex-col gap-1">
      <span class="v-kpi-label text-ink-gray-5">{{ label }}</span>
      <span v-if="hint" class="text-sm text-ink-gray-5">{{ hint }}</span>
      <span
        v-if="deltaDisplay"
        class="text-sm font-medium"
        :class="{
          'text-ink-green-9': tone === 'positive',
          'text-ink-red-9': tone === 'negative',
          'text-ink-gray-5': tone === 'neutral',
        }"
      >
        {{ deltaDisplay }}
      </span>
      <span v-if="unfilteredNote" class="text-sm text-ink-orange-9">
        {{ unfilteredNote }}
      </span>
    </div>
  </component>
</template>

<script setup>
import Skeleton from '@/components/ui/Skeleton.vue'
import { deltaTone } from '@/utils/dashboardHome'
import { formatDelta, ringDash } from '@/utils/gauge'
import { computed, defineComponent, h, markRaw, useId } from 'vue'

/* Same trap StatTile documents: the string 'button' handed to
   `<component :is>` resolves to frappe-ui's globally registered Button, so
   the real element needs a wrapper that dodges the name lookup. */
const NativeButton = markRaw(
  defineComponent({
    name: 'RadialGaugeNativeButton',
    setup(_, { slots }) {
      return () => h('button', null, slots.default?.())
    },
  }),
)

const props = defineProps({
  label: { type: String, required: true },
  value: { type: [Number, String], default: null },
  suffix: { type: String, default: '%' },
  hint: { type: String, default: '' },
  delta: { type: [Number, String], default: 0 },
  deltaSuffix: { type: String, default: '' },
  negativeIsBetter: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  error: { type: [Object, String, Error], default: null },
  retry: { type: Function, default: null },
  drilldownLabel: { type: String, default: '' },
  unfilteredNote: { type: String, default: '' },
})

defineEmits(['drill'])

const gradientId = `gauge-grad-${useId()}`

const clickable = computed(
  () => Boolean(props.drilldownLabel) && !props.loading && !props.error,
)

const ring = computed(() => ringDash(props.value, 58))

const display = computed(() => {
  if (props.value === null || props.value === undefined || props.value === '') {
    return '—'
  }
  return `${props.value}${props.suffix}`
})

const tone = computed(() => deltaTone(props.delta, props.negativeIsBetter))
const deltaDisplay = computed(() =>
  formatDelta(props.delta, props.deltaSuffix),
)
</script>
```

Note: check that `Skeleton.vue` supports `shape="circle"` (see `frontend/src/components/ui/Skeleton.vue` / `skeletonShapes.test.js`); if its circle shape is named differently, use that name — the skeleton must occupy roughly the ring's footprint.

- [ ] **Step 2: Restyle StatTile**

In `frontend/src/components/Dashboard/StatTile.vue`:

1. Add to the props definition (after `drilldownLabel`):

```js
  // 'danger' tints the tile's frame and label red: the one tile whose number
  // being high is itself the alert (critical deals).
  accent: { type: String, default: '' },
```

2. Replace the root element's static class/`:class` pair (currently the `v-stat-tile v-glass ...` string and the clickable conditional) so the danger accent joins in:

```
    class="v-stat-tile v-glass group relative flex min-h-[6.5rem] w-full flex-col justify-between gap-2 rounded-6 p-4 text-left"
    :class="[
      clickable
        ? 'cursor-pointer hover:border-outline-gray-2 hover:shadow-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2'
        : '',
      accent === 'danger' ? '!border-[rgba(216,77,77,0.35)]' : '',
    ]"
```

3. Replace the label span (currently `class="text-sm text-ink-gray-6"`):

```
        <span
          class="v-kpi-label"
          :class="accent === 'danger' ? 'text-ink-red-9' : 'text-ink-gray-5'"
        >{{ label }}</span>
```

4. Replace the numeral span's class (currently `font-display text-3xl-semibold tracking-tight text-ink-gray-9`):

```
        class="font-display text-[38px] font-semibold leading-[1.05] tracking-tight text-ink-gray-9"
```

- [ ] **Step 3: Verify + commit**

Run: `cd /workspace/frontend && yarn test:run` — green (template-only + new component; gauge tests from Task 1 cover the math).

```bash
cd /workspace && pre-commit run --files frontend/src/components/Dashboard/RadialGauge.vue frontend/src/components/Dashboard/StatTile.vue; git add -A frontend/src && git commit -m "feat: RadialGauge component and Command Center stat tiles

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Dashboard.vue restructure

**Files:**
- Modify: `frontend/src/pages/Dashboard.vue`

**Interfaces:**
- Consumes: `RadialGauge` (Task 3), StatTile `accent` prop (Task 3), existing resources and helpers already in the file (`chartResource`, `axisChartEmpty`, `DashboardItem`, `unfilteredNoteFor`, `drilldownLabelFor`, `drillInto`).
- Produces: the Command Center layout. No interface changes for other files.

All anchors below refer to the file as it is on this branch.

- [ ] **Step 1: Script — split tiles into KPIs and gauges**

Import `RadialGauge` alongside the other Dashboard components:

```js
import RadialGauge from '@/components/Dashboard/RadialGauge.vue'
```

After the existing `tiles` computed (which stays — `tileResources` and `reloadAll` depend on the catalogue), add:

```js
/* Command Center split: the four counting tiles form the KPI band; the two
   percentage tiles render as radial gauges in the hero rail. One catalogue,
   two presentations — the resources, role gating, and drilldowns are shared
   unchanged. */
const GAUGE_NAMES = ['plan_adherence', 'quota_attainment']
const kpiTiles = computed(() =>
  tiles.value.filter((t) => !GAUGE_NAMES.includes(t.name)),
)
const gaugeTiles = computed(() =>
  tiles.value.filter((t) => GAUGE_NAMES.includes(t.name)),
)
```

- [ ] **Step 2: Script — the hero trend resource**

After the `repCharts` array definition, add:

```js
/* The hero: the same sales_trend chart the rep strip used to render, now the
   page's centerpiece for both roles. The server scopes it by role exactly as
   it does for the grid and the strip. */
const heroTrend = createResource({
  url: 'crm.api.dashboard.get_chart',
  makeParams: () => ({
    name: 'sales_trend',
    type: 'axis_chart',
    from_date: fromDate.value,
    to_date: toDate.value,
    user: scopeUser.value,
    territory: scopeTerritory.value,
  }),
  auto: true,
})
```

Remove the `sales_trend` entry from `repCharts` (the hero replaces it), leaving only the `funnel_conversion` entry.

In `reloadAll()`, add `quiet(heroTrend.reload())` as the first line of the function body.

- [ ] **Step 3: Script — pipeline bar share**

Add near the other small helpers:

```js
/* Bar width for the pipeline panel: share of the largest stage, floored at
   2% so a tiny stage still draws a visible sliver rather than nothing. */
function pipelineShare(rows, row) {
  const max = Math.max(...rows.map((r) => r.deals || 0), 1)
  return Math.max(2, Math.round(((row.deals || 0) / max) * 100))
}
```

- [ ] **Step 4: Template — KPI band**

The existing StatTile grid (the `grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4` div iterating `tiles`) changes in two ways: iterate `kpiTiles` instead of `tiles`, and pass the accent. Replace `v-for="tile in tiles"` with `v-for="tile in kpiTiles"` and add to the StatTile bindings (after `:label="tile.label"`):

```
          :accent="tile.name === 'deals_at_risk' ? 'danger' : ''"
```

- [ ] **Step 5: Template — hero row (chart + gauge rail)**

Insert directly after the KPI band's closing `</div>` (before the panels grid):

```html
      <!-- The hero: the trend everyone asks about first, at a size that
           answers before it is clicked. Beside it, the two percentages that
           are targets rather than counts, drawn as rings. -->
      <div class="mt-4 grid grid-cols-1 gap-3 xl:grid-cols-3">
        <div
          class="h-80 overflow-hidden rounded-6 xl:col-span-2"
          :class="
            heroTrend.loading || heroTrend.error || axisChartEmpty(heroTrend.data)
              ? 'v-glass'
              : ''
          "
        >
          <SkeletonTable v-if="heroTrend.loading" :rows="5" :columns="3" />
          <ErrorState
            v-else-if="heroTrend.error"
            compact
            :error="heroTrend.error"
            :retry="() => heroTrend.reload()"
          />
          <div
            v-else-if="axisChartEmpty(heroTrend.data)"
            class="relative h-full"
          >
            <EmptyState
              icon="lucide-line-chart"
              :title="__('Nothing here yet')"
              :description="
                __('Leads, deals and wins chart here as they are logged.')
              "
              top="15%"
              width="lg"
            />
          </div>
          <DashboardItem
            v-else-if="heroTrend.data"
            :index="0"
            :item="{ type: 'axis_chart', data: heroTrend.data }"
          />
        </div>
        <div class="flex flex-col gap-3">
          <RadialGauge
            v-for="tile in gaugeTiles"
            :key="tile.name"
            class="flex-1"
            :label="tile.label"
            :value="tile.resource.data?.value"
            :suffix="tile.resource.data?.suffix || '%'"
            :hint="tile.resource.data?.tooltip || ''"
            :delta="tile.resource.data?.delta ?? 0"
            :delta-suffix="tile.resource.data?.deltaSuffix || ''"
            :negative-is-better="!!tile.resource.data?.negativeIsBetter"
            :loading="tile.resource.loading"
            :error="tile.resource.error"
            :retry="() => tile.resource.reload()"
            :drilldown-label="drilldownLabelFor(tile)"
            :unfiltered-note="unfilteredNoteFor(tile.resource.data)"
            @drill="drillInto(tile.name, drilldownContext)"
          />
        </div>
      </div>
```

- [ ] **Step 6: Template — pipeline panel bars**

Inside the PanelCard body, insert a new branch between the `panel.id === 'today'` block's closing `</div>` and the generic `<div v-else>`:

```html
          <!-- The pipeline as bars rather than a table: stage sizes are the
               one panel where the shape IS the answer. The count (and value,
               when forecasting is on) stays as text — the bar only ranks. -->
          <div v-else-if="panel.id === 'pipeline'" class="flex flex-col gap-3">
            <p
              v-if="panel.note?.value"
              class="flex items-start gap-2 rounded bg-surface-orange-1 px-3 py-2 text-sm text-ink-orange-9"
            >
              <LucideInfo class="mt-0.5 size-4 shrink-0" />
              <span>{{ panel.note.value }}</span>
            </p>
            <div
              v-for="(row, i) in panel.rows.value"
              :key="i"
              class="flex flex-col gap-1.5"
            >
              <div class="flex items-baseline justify-between gap-2 text-base">
                <span class="truncate text-ink-gray-7">{{ row.stage }}</span>
                <span class="shrink-0 tabular-nums text-ink-gray-8">
                  {{ panel.cell(row) }}
                </span>
              </div>
              <div
                class="h-2 w-full overflow-hidden rounded-full bg-surface-gray-3"
                role="img"
                :aria-label="`${row.stage}: ${panel.cell(row)}`"
              >
                <div
                  class="h-full rounded-full"
                  :style="{
                    width: `${pipelineShare(panel.rows.value, row)}%`,
                    background: 'var(--brand-gradient)',
                  }"
                />
              </div>
            </div>
          </div>
```

- [ ] **Step 7: Verify + commit**

Run: `cd /workspace/frontend && yarn test:run` — green.

```bash
cd /workspace && pre-commit run --files frontend/src/pages/Dashboard.vue; git add frontend/src/pages/Dashboard.vue && git commit -m "feat: Command Center dashboard layout — KPI band, hero trend, gauge rail

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Visual verification, both themes (and fixes it surfaces)

**Files:**
- Possibly modify: any file above, only where the checks demand it.

- [ ] **Step 1: Run the app**

Backend and frontend dev servers may already be running (`curl -s localhost:8000/api/method/ping`, vite usually on :8080). Start whichever is missing: `cd /workspace/frappe-bench && bench start` (background), `cd /workspace/frontend && yarn dev` (background).

- [ ] **Step 2: Verify dark-by-default**

With Playwright, clear the stored preference and reload:
`localStorage.removeItem('theme')` → reload → assert `document.documentElement.getAttribute('data-theme') === 'dark'` and `localStorage.getItem('theme') === 'dark'`. Then set `'light'`, reload, assert light survives (stored preference wins).

- [ ] **Step 3: Checklist in dark, as Administrator (team view)**

`http://localhost:<vite-port>/crm` (login Administrator/admin), dashboard page: KPI band shows four tiles (Leads, Open deals, Won deals, Critical deals) with uppercase labels and 38px numerals; the critical tile carries the red border + red label; the hero trend renders large with glow and the new palette; the gauge rail shows Plan adherence with a filled arc and its hint + delta, Quota attainment with its server hint; clicking a drillable gauge navigates like the old tile did; the pipeline panel draws gradient bars with counts (and the forecasting-off notice); panels still hide/reorder; Edit mode on the chart grid still works; nothing clipped at 1366×768 and 1904×1104. Spot-check the worst-looking text (gauge hint on glass) with computed styles — ≥ 4.5:1.

- [ ] **Step 4: Checklist in light**

Same page in light: no glow/glass bleed-through; new layout intact with solid cards; charts use the (unchanged) light palette; contrast holds.

- [ ] **Step 5: Screenshots + gate**

Full-page screenshots of both themes saved under the SDD workspace as `command-center-dark.png` / `command-center-light.png`. Then:

```bash
cd /workspace/frontend && yarn test:run
cd /workspace && pre-commit run --files $(git diff --name-only develop...HEAD -- frontend | tr '\n' ' ')
```

- [ ] **Step 6: Commit any fixes**

```bash
cd /workspace && git add -A frontend && git commit -m "fix: Command Center polish from the visual pass

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Skip if no changes were needed.
