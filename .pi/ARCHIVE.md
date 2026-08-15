# CRM — Completed Work Archive

> **This file**: Completed phases only — decision rationale, what was built, implementation detail.  
> **Current API contracts**: [SPEC.md](./SPEC.md)  
> **Upcoming work**: [PLAN.md](./PLAN.md)

---

## Phase 1 — setFieldProperty & Meta Refactor

> **Completed.** Implemented `setFieldProperty`, `setFieldProperties`, `removeFieldProperty`, `getField` for fields, sections, tabs, and child table rows.

### New pure utility files

| File | Purpose |
|---|---|
| `src/utils/expressions.js` | `_eval`, `evaluateDependsOnValue`, `evaluateExpression` — extracted from `utils/index.js` to allow import without pulling in Vue components |
| `src/utils/fieldTransforms.js` | `processField()`, `findMissingMandatory()`, `parseLinkFilters()` — pure functions, independently testable |
| `src/utils/scriptHelpers.js` | `getClassNames()`, `createDocProxy()` — extracted from `script.js` closure |

### Mutation fixes

Every place that previously mutated shared field objects now clones first:
- `Field.vue` computed: `let field = { ...props.field }`
- `SidePanelLayout.vue` `parsedField()`: `field = { ...field }`
- `Grid.vue` `getFieldObj()`: `field = { ...field }`

`JSON.parse(field.link_filters)` (6 call sites, would throw when `link_filters` was already an object) replaced everywhere with `parseLinkFilters(field.link_filters)`.

### `fieldPropertyOverrides` map structure

Added to the document cache entry alongside `fieldHtmlMap`:

```js
fieldPropertyOverrides = {
  // parent/side-panel fields
  'annual_revenue': { hidden: true },
  'status': { options: 'New\nIn Progress' },

  // sections and tabs (by name)
  'financial_section': { hidden: true },
  'advanced_tab': { hidden: true, label: 'Expert' },

  // child table columns (dot notation)
  'products.qty': { read_only: true },
  'products.discount': { hidden: true },

  // child table per-row (dot notation + colon + row.name)
  'products.rate:row_abc123': { read_only: false },
}
```

### `checkMandatory` rewritten

Old: called `getFields()` which filtered out hidden fields and only checked `mandatory_depends_on`.  
New: `findMissingMandatory()` from `fieldTransforms.js` which:
- Uses raw `doctypesMeta[doctype].fields` (all fields including hidden)
- Checks both `reqd: 1` and `mandatory_depends_on` expressions
- Respects `hidden` and `reqd` from `fieldPropertyOverrides` (script overrides win)
- Hidden fields are always skipped regardless of `reqd`

### Rendering flow (still accurate as of Phase 2)

```
script.js setFieldProperty()
  └─► ctx.fieldPropertyOverrides[target][property] = value
          │
          ├─ SidePanelLayout.vue
          │    parsedField() → Object.assign(field, overrides)
          │    parsedSection() → Object.assign(section, overrides)
          │
          ├─ FieldLayout.vue
          │    processedTabs computed → tab/section overrides merged → hidden tabs filtered
          │    │
          │    └─ Field.vue (non-grid)
          │         computed field → getFieldOverrides(fieldname) → Object.assign(field, overrides)
          │         provide('fieldPropertyOverrides', ...) → Grid.vue injects it
          │
          └─ Field.vue (isGridRow=true, inside GridRowModal)
               inject fieldPropertyOverrides from Grid.vue
               resolves: col key (products.qty) + row key (products.qty:rowName)

Grid.vue
  getFieldObj(field)
    → colKey = `${parentFieldname}.${field.fieldname}`
    → Object.assign(field, overrides[colKey])     ← column-level
    → hidden columns filtered → gridTemplateColumns recalculated

  getRowFieldObj(field, row)
    → rowKey = `${colKey}:${row.name}`
    → merged = { ...colOverrides, ...rowOverrides }  ← row wins over column
    → per-row hidden → empty cell (preserves grid alignment)
```

### Known remaining issues (as of Phase 1 completion)

| Issue | Status |
|---|---|
| `getFields()` still mutates `doctypesMeta` field objects (Select options, Link→User) | Deferred — rendering components clone first now, acceptable until Phase 4 |
| Layout APIs return redundant full field meta | Deferred — full getMeta refactor (Phase 4) |
| `getMeta` `getFields()` filters hidden fields | Intentional for now; raw `doctypesMeta` used where hidden fields needed |

---

## Phase 3A — FieldLayout Standalone Mode

> **Completed.** Added `context` prop to FieldLayout enabling standalone rendering without `useDocument`.

### Problem solved

`FieldLayout.vue` always called `useDocument(props.doctype, props.data?.name)` to get `fieldPropertyOverrides`. For a dialog with inline fields (no doctype), this called `useDocument('', undefined)` creating a garbage entry in `documentsCache`. For a dialog with a real doctype like `'CRM Lost Reason'`, it would trigger script loading unintentionally.

### Decision: Option B — `context` prop

The `context` prop carries the externally managed context object (`{ fieldPropertyOverrides, fieldHtmlMap }`). When provided, `useDocument` is skipped entirely.

**Not chosen: Option A** (`standalone` boolean) — `context` is more extensible, can carry more in future (triggerOnChange, triggerButton, etc.) without adding more props.

### What was built

**`FieldLayout.vue`**:
- Added `context: { type: Object, default: null }` prop
- When `context` is present: uses `context.fieldPropertyOverrides` for tab/section overrides instead of calling `useDocument`
- Provides `fieldLayoutContext` via inject for child Field components

**`Field.vue`**:
- Injects `fieldLayoutContext`. When present: skips `useDocument` entirely, field changes update data directly, scripting triggers are no-ops
- Guards `getMeta(doctype)` — only called when doctype is truthy. Inline mode uses `formatNumber`/`formatCurrency` fallback formatters directly

---

## Phase 2 — formDialog()

> **Completed.** Script authors can open a FieldLayout-based dialog, collect data, and act on it.

### Decision: Option C — Promise + onSubmit callback + custom actions (all three work)

Three patterns were considered:
- **Option A** (callbacks only, consistent with `createDialog`) — too verbose for simple cases
- **Option B** (`onSubmit` only) — doesn't support sequential multi-step workflows
- **Option C** (all three, Promise always resolves) — chosen. Most flexible. Promise for sequential, callback for fire-and-forget, actions for full control.

**Dialog fields are NOT scriptable (intentional).** The dialog is a data collector only. `setFieldProperty` called inside a dialog action affects the **page** fields, not the dialog's fields. Full isolation would require a separate `fieldPropertyOverrides` scope per dialog — deferred.

### What was built

| File | Description |
|---|---|
| `frontend/src/components/Modals/FieldLayoutDialog.vue` | Dialog shell + standalone FieldLayout + local reactive doc. Validates before resolving. |
| `frontend/src/components/Modals/FieldLayoutDialogContainer.vue` | Renders entries from the `fieldLayoutDialogs` reactive array |
| `frontend/src/utils/renderFieldLayoutDialog.js` | Pushes config to array, returns Promise. Internal `onResolve` is distinct from user's `onSubmit`. |
| `frontend/src/components/Modals/GlobalModals.vue` | Mounts `<FieldLayoutDialogContainer />` |
| `frontend/src/data/script.js` | `helpers.formDialog = renderFieldLayoutDialog` — bare helper in script scope |

### Key fixes during implementation

- **Buttons stuck in loading**: `_loading` was a `ref()` inside `computed()`. Vue doesn't auto-unwrap refs nested inside plain objects in templates. Fixed with `reactive({})` `actionLoadingMap` outside the computed.
- **Double-event bug**: `v-bind="dialog.props"` passed `onResolve` as a `@resolve` listener AND `@resolve` explicitly added it again. Fixed by stripping `onResolve` from the spread in `FieldLayoutDialogContainer`.
- **`getMeta('')` console error**: `Field.vue` called `getMeta(doctype)` unconditionally. When doctype is empty (inline mode) this triggers an API call that fails. Fixed with doctype guard.
- **`v-bind="action"` spreading internals**: Template was spreading entire action objects including `_loading` ref, wrapped `onClick`, etc. onto Button. Fixed with explicit prop bindings.

### Layout priority

1. `tabs` — full custom layout (highest)
2. `fields` — flat list, auto-wrapped
3. `doctype` + `fieldnames` — specific fields from doctype meta
4. `doctype` alone — full Quick Entry layout

> Current stable API: [SPEC.md — formDialog API](./SPEC.md#formdialog-api)  
> Full guide with examples: [feats/form-scripting/form-dialog.md](./feats/form-scripting/form-dialog.md)

---

## Phase 7 — Vectora Rebrand & Design Language

> Completed 2026-08-14, branch `vectora-rebrand`. Verified live against the dev bench
> (light + dark; list/kanban/detail/modal/empty surfaces, screenshot pass).

### What shipped

- **7A — Rebrand (display layer only)**: `app_title`, `__title__`, PWA manifest
  (name + `theme_color #5B5FE8`), all UI copy, invitation email, Twilio resource name,
  ERPNext custom-field labels, desk workspace label/title, desk logo
  (`crm/public/images/logo.{svg,png}`, `desk.png`), favicon, maskable PWA icons,
  34 apple splash screens, `CRMLogo.vue` → gradient V (all five consumers inherit).
  Deliberately kept: `app_name = "crm"`, `CRM *` doctype names, workspace `"name"`,
  `useOnboarding('frappecrm')` key, the ERPNext-side setting label, generated
  `locale/*.po` (regenerate on a bench), `crm/public/frontend/` build output.
- **7B — Design system**: cool graphite neutrals (hue ≈243) at stock-matched lightness
  overriding frappe-ui's gray-family semantic CSS vars in both themes; brand indigo
  reserved for focus/selection/active; **the position rail** (2.5px gradient) on the
  active sidebar item + selected-tab underline as the single signature; Space Grotesk
  display face wired to the `text-2xl-*`/`text-3xl-*` scale and header title cluster;
  tabular numerals globally; slim token scrollbars; actionable empty-state copy.
- **7C — Coherence audit**: swept all modules light+dark; fixed 6 hardcoded `bg-white`
  in Settings (broke dark mode) → `bg-surface-elevation-2`; empty-state copy fixed
  once in `ListViews/EmptyState.vue`.

### Load-bearing decisions

- `frontend/src/styles/vectora-theme.css` is **generated** — rerun
  `python3 frontend/scripts/generate_vectora_theme.py` after any frappe-ui token sync.
- The theme file loads after frappe-ui's stylesheet and `:root` ties
  `[data-theme="dark"]` on specificity → every token touched must be emitted for
  **both** modes; the generator backfills stock values for asymmetric tokens
  (`surface-sidebar` is gray-50 light / `neutral/transparent` dark — missing that
  painted the dark sidebar light).
- Design record: `docs/superpowers/plans/2026-08-14-vectora-design-pass-7b.md`;
  task plan: `docs/superpowers/plans/2026-08-13-vectora-rebrand-7a.md`.

### Deferred to backlog

- Discoverable keyboard-shortcut sheet (feature work, not styling)
- Skeleton-loading redesign (frappe-ui defaults inherit the new tokens)

---

## Phase 8 — Proactive Agent Workflows

**Completed 2026-08-14/15.** Task plan:
`docs/superpowers/plans/2026-08-14-proactive-suggestions-phase8.md`.
Feature doc: [feats/suggestions/README.md](./feats/suggestions/README.md).

### What shipped

- **`CRM Suggestion`** with dedupe on `(signal, reference, open)`, TTL expiry, a shorter
  cooldown for expired rows (so the job cannot expire and re-create the same row every
  hour), and a daily purge that keeps anything a plan item still links to.
- **Signal engine** (`crm/agent/signals.py`): pure detectors over plain rows, batched
  queries, per-candidate savepoint isolation, `search_index` on the five columns the
  dedupe and lookup queries filter on. Backward-looking: `idle_deal`, `no_next_step`,
  `lead_sla`, `stale_plan`. **Forward-looking**: `close_at_risk` (fires while the close
  date is still ahead and the stage says it will not be met) and `deal_cooling` (fires on
  cadence decay against the deal's own rhythm, days before the flat idle threshold).
- **Prediction** (`crm/agent/predict.py`): explainable scoring, every factor carrying
  `{key, label, weight}`. Forward-looking factors — `slow_stage` against the historical
  median for that stage, `slip_risk` against `expected_closure_date`, `cadence_slowing`.
- **Suggestion inbox** — shell panel with a realtime badge (`crm_suggestion` over the
  socket, one event per user per run, empty payload), per-record "Needs attention",
  typed accept flows per `suggested_action`, and dismissal reasons that feed back into
  the cooldown.
- **Automation rules** — deterministic trigger → condition → action, priority-ordered,
  idempotent, model-free, with a Settings pane (they were desk-only).
- **Write tier** (`crm/agent/actions.py`) — model-drafted replies as proposals only.
  The module never imports frappe and an AST test enforces it.

### Load-bearing decisions

- **Agent output is untrusted input.** The live injection gate confirmed granite followed
  a hostile instruction embedded in an email body 3/3 while holding the control 3/3. The
  human in the compose window is the write gate, not the prompt fence. See
  [feats/agent/README.md](./feats/agent/README.md).
- **The deterministic tier never depends on a model.** Signals, scoring and automation all
  work with the agent tier disabled; the model ranks and enriches, it does not gate.
- **Ownership is enforced at both doors** — in the endpoints (which save with
  `ignore_permissions` because the state machine is theirs) and on the doctype, because
  `frappe.client.get_list` reaches the same table. `crm/tests/test_row_permissions.py`
  knocks on the second door specifically.
- `Document.as_dict()` coerces an unsaved Int/Check to `0`, so settings are read through
  `frappe.db.get_singles_dict` — reading them the other way would have shipped signals
  **off** with zero thresholds on every site that never opened the settings page.

---

## Phase 9 — Rep Planning

**Completed 2026-08-14/15.** Task plan:
`docs/superpowers/plans/2026-08-14-rep-planning-phase9.md`.
Feature doc: [feats/planning/README.md](./feats/planning/README.md).

### What shipped

- `CRM Rep Plan` / `CRM Rep Plan Item`, one plan per `(user, Monday)` enforced by a
  **unique index**, not by a read-then-throw in `validate`.
- Pure `match_items` (kind + reference + week window, one actual per item ever, closest
  date wins, deterministic tie-break) plus a per-kind `ACTUAL_SOURCES` table for the
  frappe-facing adapter.
- Planner page: week grid, add/edit/remove, drag-to-reschedule with a keyboard
  equivalent, propose-my-week through the write gate, manual fulfilment override,
  optimistic-concurrency token, and a dirty guard on week/rep change.
- Daily matcher with per-plan savepoint isolation.

### Load-bearing decisions

- **Week-only granularity**; month is a rollup view, not a separate plan.
- **Managers read, reps write.** Visibility follows the CRM Sales Hierarchy that already
  scopes Leads and Deals — not the role alone, so an in-tree Sales Manager sees their
  subtree and not the company.
- **The matcher re-derives its whole horizon every run** rather than appending to it. A
  match is a claim on a record, so deleting the call behind an item takes its Done away
  again and `Missed` is a verdict the run reached, not a state the item is stuck in. The
  one thing the job never touches is an item a rep corrected by hand.
- Each activity kind gets its fulfilment wrong differently, so the source table is
  explicit: Calls match on **caller or receiver** (a telephony log is owned by the
  integration user) and key on `start_time`; Meetings keep their reference; Emails
  require `communication_type = Communication` and `medium = Email`.

---

## Phase 11 — Reporting

**Completed 2026-08-14/15.** Task plan:
`docs/superpowers/plans/2026-08-14-reporting-phase11.md`.
Feature doc: [feats/reporting/README.md](./feats/reporting/README.md).

### What shipped

- Five built-in reports over the metrics layer: pipeline by stage, funnel conversion,
  plan adherence by rep, forecast vs actual, quota attainment by rep.
- Viewer page with deep-linkable state, the position rail on the selected report,
  per-column description tooltips, CSV export (formula-injection neutralised, UTF-8
  BOM) and a print view that paginates.
- `CRM Report Digest` + a daily job. Recipients must be enabled Users holding a CRM
  role, and each message renders inside `frappe.set_user(recipient)` so a rep gets their
  rows and a manager the team's. Every interpolated value is HTML-escaped.

### Load-bearing decisions

- **`reports.py` holds no aggregation.** Where a report needs a different shape from a
  tile, the shared function in `crm.api.dashboard` grows a parameter and both call sites
  pass it. Tests assert the tile and the report row are equal for the same period.
- A report declares `period: false` when it is a snapshot rather than a window, and the
  UI hides the date picker for those — a control that changes nothing is worse than no
  control.
- Registry strings are untranslated literals with `_()` applied per request: a module is
  imported once per worker, so translating at import time freezes every label to the
  language of whoever made the first request.
