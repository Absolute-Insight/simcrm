# Vectora Development Plan

> **This file**: Current and upcoming work only. No completed phases.
> **Completed phases**: [ARCHIVE.md](./ARCHIVE.md)
> **Stable API contracts**: [SPEC.md](./SPEC.md)
> **Per-phase task plans** (TDD, bite-sized): `docs/superpowers/plans/` — written when a phase starts.

---

## Product Direction (updated 2026-08-13)

The product rebrands to **Vectora**. Direction, in priority order:

1. **Agentic workflow & automation as the spine.** The system watches, predicts, and
   proposes — *proactive with a predictive approach, not reactive*. The rep's day starts
   with "here is what needs attention and why", not with an empty list view.
2. **Global feature coherence.** Every module (Leads, Deals, Contacts, Organizations,
   Tasks, Calls, Notes) uses the same patterns: filters, quick actions, empty/loading
   states, keyboard behaviour. New features must reuse these patterns, never invent
   parallel ones.
3. **Original, intuitive, professional, modern, premium UI.** A deliberate design
   language, not restyled defaults.
4. **Rep planning linked to actual activity.** Plans (auto-proposed by the agent and
   manually authored by reps) resolve against real logged activity — plan vs. actual is
   a first-class measure.
5. **Accurate analytics and forecasts; clean, informative reporting.** One tested
   metrics layer is the single source of numbers for dashboards, forecasts, and reports.

**Scope guard for the rebrand**: Vectora is a *display-layer* brand. `app_name = "crm"`,
Python module paths, and `CRM *` doctype names stay — renaming them is a breaking data
migration and breaks every existing Form Script, for zero user-visible gain.

---

## Implementation Order

Two tracks. The **product track** delivers the new direction; the **platform track**
(pre-existing refactors) continues and stays valuable, but no longer blocks product work.

| Order | Phase | Track | Scope | Status |
|---|---|---|---|---|
| **1** | [Phase 7 — Vectora rebrand & design language](#phase-7--vectora-rebrand--design-language) | Product | Brand + UI overhaul + coherence audit | 🔜 Next |
| **2** | [Phase 8 — Proactive agent workflows](#phase-8--proactive-agent-workflows) | Product | Signals, predictions, suggestions, automation | After 7A (7B/7C can overlap) |
| **3** | [Phase 9 — Rep planning](#phase-9--rep-planning) | Product | Auto + manual plans linked to actuals | After 8 |
| **4** | [Phase 10 — Dashboards, analytics & forecasts](#phase-10--dashboards-analytics--forecasts) | Product | Metrics layer, role-aware dashboards, forecasting | After 9 |
| **5** | [Phase 11 — Reporting](#phase-11--reporting) | Product | Saved reports, exports, scheduled digests | After 10 |
| 6 | [Phase 3B — Full decouple (Grid independent)](#phase-3b--full-decouple-grid-independent) | Platform | Structural refactor | Interleave; see conflict note |
| 7 | [Phase 4 — getMeta single source of truth](#phase-4--getmeta-single-source-of-truth) | Platform | Architectural cleanup | After 3B |
| 8 | [Phase 6 — More Capabilities (selected)](#phase-6--more-capabilities-selected) | Platform | Feature expansion | After 4 |
| 9 | [Phase 5 — Scripting DX Rethink](#phase-5--scripting-dx-rethink) | Platform | Syntax/API redesign | Last |

**Conflict note (7B × 3B)**: Phase 7B restyles surfaces that Phase 3B restructures
(`FieldLayout`, `Field`, `Grid`). Do not run both against those files simultaneously —
either land 3B first, or keep 7B's form-surface polish to design tokens only until 3B
merges.

---

## Phase 7 — Vectora Rebrand & Design Language

> **First. Everything that ships after this lands as Vectora.**

### 7A — Rebrand (small, mechanical)

Display-layer rename only (see scope guard above).

**Known branding surfaces** (verified by grep):

| Surface | Change |
|---|---|
| `crm/hooks.py` | `app_title = "Vectora"` (`app_name = "crm"` stays) |
| `frontend/index.html` | `<title>`, meta description |
| `frontend/public/favicon.png` | New favicon; add logo assets alongside |
| `frontend/src/components/Layouts/AppSidebar.vue` | Wordmark/logo |
| `frontend/src/components/Modals/AboutModal.vue` | Name, links, version copy |
| `frontend/src/pages/NotPermitted.vue`, `PersonaForm.vue` | Copy |
| `frontend/src/components/Settings/ERPNextSettings.vue` | Copy |
| PWA manifest / mobile icons (locate at implementation) | Name + icons |
| Email/notification templates in `crm/` (grep at implementation) | Sender name, footer copy |

**Blocked on user input**: final logo/wordmark assets and brand palette. Until supplied,
implement with a placeholder wordmark and a token-based palette that can be swapped in
one file.

### 7B — Design language (the premium pass)

Use the `frontend-design` skill at implementation time. This is a *designed* pass, not a
reskin: define the system first, then apply it surface by surface.

1. **Tokens** — typography scale, spacing, radius, elevation/shadow, motion durations,
   and a semantic color palette (light + dark) in `tailwind.config.js` + CSS variables.
   frappe-ui components inherit via CSS vars where possible; wrap where not.
2. **App shell** — sidebar, top bar, navigation states, notification surface.
3. **List surfaces** — list views, kanban, group-by headers, selection & bulk-action bar.
4. **Detail surfaces** — Lead/Deal/Contact/Organization pages, side panel, activity
   timeline (highest-traffic screen; the timeline is where "premium" is won or lost).
5. **Overlays** — modals (incl. `FieldLayoutDialog`), dropdowns, toasts, tooltips.
6. **States** — designed empty states (with a next action, not just an illustration),
   loading skeletons, error states.

### 7C — Coherence audit

One pass across all modules producing a checklist of divergences, then fix them:

- Same filter/sort/column controls on every list view
- Same quick-action set and placement on every detail page
- Same keyboard shortcuts everywhere (and a discoverable shortcut sheet)
- Same empty/loading/error treatment everywhere
- Same terminology (one word per concept — no "rep/agent/user" drift in UI copy)

### Checklist

- [x] Obtain logo/wordmark + brand palette from user — master at
      `frontend/public/vectora-logo.png`; palette: sky `#21ABFB` → indigo `#5B5FE8` →
      magenta `#DF5FEB` (sampled from the logo)
- [x] 7A: all surfaces renamed (2026-08-13, branch `vectora-rebrand`) — remaining
      `Frappe CRM` strings are deliberate: workspace `"name"` (data layer), the
      ERPNext-side setting label, generated `locale/*.po` (regenerate needs a bench),
      and `crm/public/frontend/` build output (regenerates on next build). Extra
      surfaces found and done: desk logo (`crm/public/images/logo.{svg,png}`,
      `desk.png`, `app_icon_title`), PWA `theme_color` → `#5B5FE8`
- [ ] 7B: token file + dark mode parity
- [ ] 7B: shell → lists → details → overlays → states, in that order
- [ ] 7C: divergence checklist written, then burned down
- [ ] Visual regression: screenshot pass over Leads/Deals/Contact/Organization +
      modals, light and dark

---

## Phase 8 — Proactive Agent Workflows

> **The spine of the product direction. Everything in Phases 9–11 plugs into this.**

### Goal

Move from "user asks → agent answers" (current read tier) to "system watches →
predicts → proposes → user confirms → system acts". Proactive and predictive, never
silently autonomous.

### Hard constraints (from the live-model gate — see `feats/agent/README.md`)

The injection testing showed **every model tried follows instructions embedded in email
bodies**. These are design constraints, not preferences:

1. Model output is attacker-influenced input. **No write happens without explicit user
   confirmation** through `formDialog()` — the confirm dialog shows exactly what will be
   written, as plain text, never HTML.
2. Predictions that drive decisions are computed from **structured data** (stage age,
   activity cadence, response gaps, amounts) — never solely from untrusted message text.
3. Deterministic automation does not need a model. Rules fire reliably with the agent
   disabled; the model *ranks and enriches*, it does not gate the feature.
4. The injection thread from the gate becomes a permanent eval; new capabilities add to
   that eval set before they ship.

### Components

**1. Signal engine** (server, `crm/agent/signals.py` + scheduler)
Deterministic detectors over structured data, run via `doc_events` hooks + hourly/daily
scheduler jobs. Initial signal set:

- Deal idle: no activity logged in N days (N per stage, configurable)
- No next step: deal has no open task/planned activity
- Close date at risk: expected close within N days while stage is early
- Unanswered inbound: communication received, no reply in N hours
- Lead SLA: new lead untouched past the response-time target
- Stale plan: rep plan item overdue with no linked activity (lands with Phase 9)

**2. Prediction layer** (`crm/agent/predict.py`)
Explainable-first scoring:

- Deal health score + close-date risk from structured features (stage duration vs.
  historical median, activity cadence, inbound/outbound balance)
- Every score ships with its top contributing factors — shown in UI, always
- Model-assisted refinement is optional and additive, applied only when the agent tier
  is enabled and clearly labeled in the UI as model-derived

**3. Suggestion queue** (`CRM Suggestion` doctype)
The proactive surface. Fields: source signal, reference doctype/name, proposed action
(typed: create task / schedule call / draft reply / update field), rationale,
status (`open / accepted / dismissed / expired`), expiry.

- Signals and predictions emit suggestions; dedupe on (signal, reference, open)
- Accepting opens a pre-filled `formDialog()` confirm; the accepted action creates the
  real record (task, event, draft) — the confirm is the write gate from constraint 1
- Dismissals are recorded with reason — dismissal patterns tune signal thresholds
- Realtime badge via `$socket`; suggestion inbox in the app shell + per-record section
  on detail pages

**4. Automation rules** (deterministic, admin-configured)
Trigger → condition → action records (assignment rotation, SLA escalation, follow-up
task on stage change). Runs with the agent disabled. Model involvement: none.

**5. Write-tier capability layer** (`crm/agent/actions.py`)
Mirror image of `tools.py`: typed, permission-checked, rate-limited *proposals* only —
each returns a draft payload for the confirm dialog, never writes directly. Same AST
allowlist test pattern as `tools.py`.

### Decisions needed before starting

1. First signal set — the list above, or trimmed? (Recommendation: ship idle-deal,
   no-next-step, and lead-SLA first; they need no historical data.)
2. Where the suggestion inbox lives — dedicated page vs. panel in the shell.
   (Recommendation: panel in the shell + section on detail pages; a dedicated page adds
   navigation for no benefit at this volume.)
3. Snooze semantics — is "dismissed" final, or does a signal re-fire after N days?

### Checklist

- [ ] `CRM Suggestion` doctype + dedupe + expiry
- [ ] `signals.py` with first three signals + scheduler wiring + unit tests per signal
- [ ] `predict.py` heuristic scores + factor attribution + unit tests on fixture data
- [ ] `actions.py` write-tier proposals + AST allowlist test (pattern from `tools.py`)
- [ ] Suggestion inbox UI + per-record suggestions + accept→`formDialog()` confirm flow
- [ ] Automation rule doctype + runner + tests (agent disabled path proven)
- [ ] Injection eval set extended to cover every new model-touching path
- [ ] Rate limits on every endpoint that can trigger a model call

---

## Phase 9 — Rep Planning

> **After Phase 8 — auto-planning consumes the suggestion queue and the write gate.**

### Goal

Reps and managers plan activity per period (week/month); the agent proposes plans;
every plan item links to the actual activity that fulfils it. Plan vs. actual is
computed, not self-reported.

### Model

- `CRM Rep Plan` — user, period type (week/month), period start, status, rollup targets
  (calls, meetings, new leads touched, deals advanced)
- `CRM Rep Plan Item` (child) — planned activity type, linked Lead/Deal, planned date,
  note, and **fulfilment link**: the actual `CRM Task` / `CRM Call Log` / event that
  satisfied it, resolved automatically by matching (type, linked record, date window),
  manually overridable

Concrete items are the source of truth; the rollup targets are derived, so "planned 30
calls" and the 30 planned call items can never disagree.

### Flows

- **Manual**: planner page — week grid, drag/reschedule items, per-rep; managers see the
  team roster with plan status
- **Auto**: "Propose my week" — the agent drafts a plan from open suggestions (idle
  deals → planned touches, SLA leads → planned calls), rep reviews and confirms via the
  Phase 8 write gate; items are editable after acceptance like manual ones
- **Actuals linkage**: background job matches new activity records to open plan items;
  unmatched planned items age into the "stale plan" signal (Phase 8)

### Decisions needed before starting

1. Period granularity to ship first — week only, or week+month? (Recommendation: week
   only; month is a rollup view, not a separate plan.)
2. Can managers edit a rep's plan, or only comment? (Ask — org-culture dependent.)

### Checklist

- [ ] Doctypes + fulfilment-matching logic with unit tests (matching is pure logic —
      extract and test)
- [ ] Planner page (rep view, manager roster view)
- [ ] "Propose my week" flow through the Phase 8 confirm gate
- [ ] Actuals matcher job + manual override UI
- [ ] Plan-vs-actual computed fields exposed for Phase 10

---

## Phase 10 — Dashboards, Analytics & Forecasts

> **After Phase 9 — plan adherence and prediction data now exist to display.**

### Goal

Role-aware, user-friendly, powerful dashboards; accurate forecasts; all numbers from
one tested source.

### 1. Metrics layer first (`crm/api/metrics.py`)

Single module producing every aggregate: pipeline by stage, funnel conversion, activity
counts, plan adherence, forecast. Unit-tested against fixtures, timezone- and
currency-aware. **Dashboards, forecasts, and reports may only consume this module** —
"accurate analytics" is an architecture decision, not a QA task: numbers can't disagree
if they have one source.

### 2. Dashboards (rebuild `frontend/src/pages/Dashboard.vue`)

Use the `dataviz` skill at implementation time.

- **Rep home**: my suggestions (Phase 8), my plan today vs. done (Phase 9), my pipeline,
  my at-risk deals with the *why* (factor attribution from `predict.py`)
- **Manager view**: team pipeline & forecast vs. quota, plan adherence per rep, funnel,
  at-risk deals across the team
- User-friendly = opinionated defaults with light customization (show/hide/reorder
  cards), not a widget-builder. Powerful = every number clicks through to the filtered
  list view behind it.

### 3. Forecasting

- Baseline: stage-probability-weighted pipeline per period per rep/team
- Adjusted: baseline modulated by Phase 8 deal-health scores, shown side by side with
  the baseline — never silently replacing it
- **Forecast snapshots**: a scheduled job stores the forecast weekly, so forecast
  accuracy is measured against reality over time — this is what makes "accurate
  forecasts" verifiable rather than aspirational

### Checklist

- [ ] `metrics.py` with fixture-based unit tests (incl. timezone/currency cases)
- [ ] Quota field/doctype (needed for forecast vs. quota — confirm shape with user)
- [ ] Rep home + manager view, every figure click-through to its list view
- [ ] Forecast baseline + adjusted view + weekly snapshot job
- [ ] Forecast-accuracy view once ≥ 4 snapshots exist

---

## Phase 11 — Reporting

> **After Phase 10 — reports are saved views over the metrics layer.**

### Goal

Clean, informative reporting: saved report definitions, exports, scheduled delivery.
No new aggregation code — reports parameterize `metrics.py`.

### Scope

- `CRM Report` doctype: metric set, filters, grouping, period, recipients, schedule
- Report viewer page: clean tabular + chart rendering, print stylesheet
- Exports: CSV always; PDF via print view
- Scheduled digests: weekly pipeline summary, plan-adherence summary, emailed to
  recipients (uses existing frappe email queue)
- Ship 3–4 strong built-in reports before building any custom-report UI: pipeline by
  stage, funnel conversion, activity & plan adherence, forecast vs. actual

### Checklist

- [ ] `CRM Report` doctype + runner over `metrics.py`
- [ ] Viewer page + print styles + CSV export
- [ ] Scheduled digest job + email template (Vectora-branded, Phase 7 assets)
- [ ] Four built-in reports listed above

---

## Phase 3B — Full Decouple (Grid Independent)

> **Platform track. Structural refactor. See conflict note in Implementation Order.**

### Goal

Make `Grid` work as a standalone component that does not depend on inject/provide chains
from `FieldLayout → Field.vue`. Make `FieldLayout` and `Field` use a single unified
context instead of 6+ separate inject keys.

### Current inject/provide chain (to eliminate)

```
FieldLayout provides:     data, hasTabs, doctype, preview, isGridRow
Field.vue provides:       triggerOnChange, triggerButton, triggerOnRowAdd,
                          triggerOnRowRemove, fieldPropertyOverrides
Field.vue provides:       (also) parentFieldname — for Grid
Grid.vue provides:        parentDoc, fieldPropertyOverrides, parentFieldname
GridRowModal provides:    parentFieldname
```

If Grid is used outside this chain, all injects fall back to defaults (empty
functions/objects) and scripting silently doesn't work.

### Proposed approach

**`useFieldLayout(doctype, options)` composable** — encapsulates all wiring. One
provide/inject key replaces all 6+.

```js
// src/composables/useFieldLayout.js
export function useFieldLayout(doctype, options = {}) {
  // options.docname         — for existing doc (triggers script loading via useDocument)
  // options.doc             — for standalone mode (local reactive data, no useDocument)
  // options.readonly        — all fields read-only
  // options.onFieldChange   — callback instead of script hooks

  const fieldPropertyOverrides = reactive({})

  return {
    context: {
      doc,
      doctype,
      fieldPropertyOverrides,
      triggerOnChange,
      triggerButton,
      triggerOnRowAdd,
      triggerOnRowRemove,
      setFieldProperty: (target, property, value, rowName) => { ... },
      removeFieldProperty: (target, property, rowName) => { ... },
    }
  }
}
```

`FieldLayout`, `Field.vue`, `Grid.vue` all inject `'fieldLayoutContext'` instead of 6
separate keys. External consumers that don't use `useFieldLayout` get safe no-op
defaults automatically.

### Decisions needed before starting

1. **Should Grid work completely without any FieldLayout context?**
   - If yes: Grid needs its own script-loading path for child doctype scripts.
   - If no: Grid without FieldLayout context = display only, no scripting.
   - Recommendation: "no" for now.

2. **Should FieldLayout continue to accept `tabs` as a prop, or should it fetch its own layout?**
   - Currently all callers fetch tabs via `createResource` and pass them in.
   - Moving fetch inside FieldLayout would make it self-contained but less flexible.
   - Ask before deciding.

### Files

| File | Change |
|---|---|
| `frontend/src/composables/useFieldLayout.js` | **New** — unified composable |
| `frontend/src/components/FieldLayout/FieldLayout.vue` | Use `useFieldLayout`; provide single context key |
| `frontend/src/components/FieldLayout/Field.vue` | Inject `'fieldLayoutContext'`; remove 6 separate injects |
| `frontend/src/components/Controls/Grid.vue` | Inject `'fieldLayoutContext'` with safe fallback |
| `frontend/src/components/Controls/GridRowModal.vue` | Simplify — propagate context, remove `parentFieldname` prop |

### Checklist

- [ ] Decide Grid standalone behaviour (display only vs full scripting)
- [ ] Decide whether FieldLayout fetches its own layout
- [ ] `useFieldLayout.js` composable
- [ ] `FieldLayout.vue` — provide `fieldLayoutContext`; keep Phase 3A `context` prop working
- [ ] `Field.vue` — inject `fieldLayoutContext`; remove `isGridRow` branch
- [ ] `Grid.vue` — inject `fieldLayoutContext`; fallback to props-only mode
- [ ] `GridRowModal.vue` — simplify
- [ ] Regression test: all existing forms (Lead, Deal, Contact, Organization pages, all modals)

---

## Phase 4 — getMeta Single Source of Truth

> **After Phase 3B. Completes the architectural cleanup.**

### Goal

1. `getMeta.getField(fieldname)` is the single place that clones, applies overrides, and transforms (Select→array, Link→User).
2. Layout APIs (`get_fields_layout`, `get_sidepanel_sections`) return fieldname strings only + a perm overrides map — no embedded `field.as_dict()`.
3. Rendering components call `getMeta.getField()` instead of doing their own transforms.
4. `getFields()` no longer filters `hidden` fields — callers decide.

### Why after Phase 3B

Phase 3B gives a single context object (`useFieldLayout`) as the wiring point. Routing
all field resolution through `getMeta.getField()` can happen there in one place.

### What remains (not done in Phase 1)

- `getFields()` in `meta.js` still mutates `doctypesMeta` field objects
- Layout APIs still return full `field.as_dict()` per field (redundant)
- `getFields()` still has `!f.hidden` filter
- `processField()` is tested but not wired into rendering

### Checklist

- [ ] Phase 3B must be merged first
- [ ] `meta.js` — `getField(fieldname, options)` method: clones + applies perm overrides + script overrides + transforms
- [ ] `meta.js` — `getFields()` uses `getField()` internally; removes `!f.hidden` filter
- [ ] `useFieldLayout.js` — routes field resolution through `getMeta.getField()`
- [ ] `crm_fields_layout.py` — `get_fields_layout` returns `{ tabs: [...fieldname strings...], perm_overrides: {...} }`
- [ ] Update all callers of layout APIs to handle new format
- [ ] `ColumnSettings`, `ViewControls`, `KanbanSettings` — add explicit `hidden` filter
- [ ] Remove redundant Select/Link transforms from `SidePanelLayout.vue`

---

## Phase 6 — More Capabilities (selected)

> **After Phase 4. Feature expansion on clean foundation.**

### 6A — Programmatic layout manipulation

Inject virtual fields and sections that exist only at runtime — not in the DocType:

```js
class CRMLead {
  onLoad() {
    this.addField('basic_section', {
      fieldname: '_score_display',
      fieldtype: 'HTML',
      label: 'Lead Score',
      after: 'status',
    })

    this.addSection({
      name: '_ext_section',
      label: 'Extension Data',
      after: 'contact_section',
      fields: [
        { fieldname: '_ext_field1', fieldtype: 'Data', label: 'Custom Field' },
      ],
    })
  }
}
```

Virtual fields are managed in a separate `virtualFields` map on the document context.

### 6B — `usePermLevel` composable

Move perm level restriction logic client-side. Currently `handle_perm_level_restrictions`
in `crm_fields_layout.py` modifies `read_only`/`hidden` on the server. This means the
client must re-fetch the layout to reflect permission changes.

A `usePermLevel(doctype)` composable would:
- Fetch the user's permitted perm levels per doctype (once, cached)
- Expose `getPermOverrides(fields)` computing restrictions client-side
- Pass result as `permOverrides` into `getMeta.getField()`

**Depends on Phase 4.**

### Checklist

- [ ] Phase 4 must be merged first
- [ ] 6A: `addField(sectionName, fieldDef)` prototype method in `script.js`
- [ ] 6A: `addSection(sectionDef)` prototype method
- [ ] 6A: `virtualFields` map on document context
- [ ] 6A: Layout resolution merges virtual fields
- [ ] 6B: `usePermLevel(doctype)` composable
- [ ] 6B: `crm_fields_layout.py` — return raw perm data instead of modifying fields
- [ ] 6B: Wire into `getMeta.getField()` via Phase 4

---

## Phase 5 — Scripting DX Rethink

> **Last. Do once the full capability set (Phases 3B–6) is known and stable.**

### Why last

- The syntax should reflect all capabilities — not a subset.
- A syntax change is a breaking change for script authors — do it once.
- `setFieldProperty` works well enough in the meantime.

### Ideas (not decided — decide with maintainer)

#### Builder / chainable API

```js
this.field('annual_revenue').hide()
this.field('status').setOptions('New\nOpen\nClosed')
this.field('email').makeRequired().setLabel('Work Email')
this.section('financial_section').collapse()
this.fields(['email', 'phone']).makeRequired()
```

#### Declarative rules

```js
class CRMLead {
  rules = {
    lost_reason: {
      hidden: (doc) => doc.status !== 'Lost',
      reqd:   (doc) => doc.status === 'Lost',
    },
  }
}
```

#### Reactive shortcuts

```js
this.field('lost_reason')
  .showWhen(() => this.doc.status === 'Lost')
  .requireWhen(() => this.doc.status === 'Lost')
```

### Backwards compatibility

`setFieldProperty`, `setFieldProperties`, `removeFieldProperty`, `getField`, `formDialog`
continue to work. New syntax is additive.

---

## Deferred / Backlog

| Feature | Notes |
|---|---|
| List view scripting | Column visibility, custom cell renderers, bulk action hooks |
| Inter-script communication | `this.emit('event', data)` / `this.on('event', handler)` across scripts |
| Conditional field injection | Variant of 6A — scripts inject fields only when a condition is true |
| Custom report builder UI | Only after the four built-in reports (Phase 11) prove the metrics layer |
| Model-drafted email replies | Write-tier action; needs the Phase 8 eval set matured first |
| Territory/segment analytics | Metrics layer extension once quota shape is settled |

---

## Design Principles

1. **Generic-first** — No CRM-specific assumptions in FieldLayout, Grid, Field, or the
   scripting engine. CRM-specific behaviour lives in Form Script records.

2. **Ask before deciding** — Document the options, pick the right one with the
   maintainer. Especially for: prop names, composable APIs, breaking changes.

3. **Props > inject for public API** — Components accept props for their core inputs.
   inject/provide is for internal wiring only.

4. **Test pure logic first** — Extract functions to utility files, write unit tests,
   then wire into components. Vitest is already set up (118 tests, ~250ms).

5. **Incremental, independently shippable** — Each phase merges and is usable on its own.

6. **Extensibility via records** — Third-party apps extend via `CRM Form Script`
   records. No source code modification. Multiple scripts per doctype run sequentially;
   last-write-wins for overrides.

7. **Proactive, not reactive** — Features surface the next action before the user asks.
   Every prediction shows its contributing factors; nothing is an unexplained score.

8. **Coherent by default** — A new surface reuses the global patterns (filters, quick
   actions, states, shortcuts). Divergence is a bug, not a style choice.

9. **Agent output is untrusted input** — Proven by the live-model injection gate
   (`feats/agent/README.md`): no model-proposed write lands without a `formDialog()`
   confirmation showing the exact payload as plain text; deterministic automation never
   depends on a model being enabled.

10. **One source of numbers** — Dashboards, forecasts, and reports consume only the
    tested metrics layer. Two surfaces showing different values for the same metric is
    a release blocker.
