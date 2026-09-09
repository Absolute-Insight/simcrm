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

- Discoverable keyboard-shortcut sheet (feature work, not styling) — still open, and
  tracked in [docs/PILOT-READINESS.md](../docs/PILOT-READINESS.md)'s P4 list rather than
  in PLAN.md.
- ~~Skeleton-loading redesign~~ — **delivered.** `ui/Skeleton.vue` and
  `ui/SkeletonTable.vue` now back the loading state on 19 components, so this is no longer
  "frappe-ui defaults inherit the new tokens"; it is a real three-state contract
  (loading / failed / empty) that `ui/EmptyState.vue` documents.

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

---

## Role-Based Access Control

**Completed 2026-09-08/09.** Design:
`docs/superpowers/specs/2026-09-08-role-access-control-design.md`. Task plan:
`docs/superpowers/plans/2026-09-08-role-access-control.md`.
Stable contract: [SPEC.md — Role visibility](./SPEC.md#role-visibility).

### What the audit found

An audit of every role gate in the app (doctype permissions, the nine
`permission_query_conditions` / `has_permission` hooks, ~40 endpoint gates, and every
frontend `isManager()` / `isAdmin()` condition) found the server side in good shape overall,
and three things that needed fixing:

- **`enable_sales_hierarchy` defaulted to `0`.** On a fresh site nobody is in the sales
  hierarchy tree, so `org_hierarchy.py`'s explicit fallback — *"a Sales Manager outside the
  tree retains the default, i.e. sees everything"* — meant every Sales Manager read every
  lead and deal on the site, and, because `visible_users()` returned `None` for them, every
  rep's quota, plan and suggestions too. SECURITY.md names exactly this as the invariant
  worth probing, and the flag that enforces it was surfaced only inside the admin-only tree
  editor (`Hierarchy.vue`), reading as a feature of that editor rather than the master switch
  it actually is.
- **The out-of-tree case was hardcoded**, not configurable. "Sees everything" is a
  reasonable escape hatch for a manager who genuinely runs the whole book — but it is also
  what *every* manager gets on a site whose tree nobody has built yet, so turning the
  hierarchy on by itself would only relocate the problem to the first manager added.
- **Two `Settings.vue` groups carried no group condition.** Five of seven groups were gated
  with `isManager()`; `Email` and `Integrations` were not. `Integrations`' ungated
  fall-through is deliberate — a rep configures their own Telephony agent number there, and
  the manager-only controls inside it are already gated one by one — so a group condition on
  `Integrations` would have been a regression, taking that away from reps. `Email →
  Templates` had no such reason and was gated at the item.

Separately: `isSalesUser()` (`stores/users.js`) was exported with no callers and was an exact
role match where its sibling `isManager()` is inclusive — two different meanings for one
idea, waiting for someone to reach for the wrong one. Both fixes (the Templates gate, the
dead helper) landed as their own commit ahead of the feature, since they are correct whether
or not the settings pane ships at all.

### What shipped

- **`CRM Access Settings`** — a Single, `rwc` (no delete) to System Manager and nobody else — holding
  `manager_outside_hierarchy` and a sparse `hidden_surfaces` child table (`CRM Role Surface`:
  `role` + `surface`). A row's existence means hidden; there is no `visible` field for it to
  fall out of sync with.
- **`crm/api/access.py`** — `get_visibility` / `set_visibility` for the chrome matrix,
  `get_data_access` / `set_data_access` for the two switches that actually change what the
  database returns, and `manager_outside_hierarchy_sees_all()`, the single place that decision
  is made.
- **`frontend/src/utils/surfaces.js`** — the registry (13 nav links, 27 settings panes) plus
  the pure `canSee` / `editableBy` / `isAtFloor` gates. **`frontend/src/stores/access.js`** —
  the Pinia wrapper the shell actually calls, loaded once in the router's global guard
  alongside `users`, so the sidebar renders once with the final set instead of painting a link
  and retracting it.
- **`Settings → Access Control`** (`AccessControl.vue`) — §1 the two data-access switches,
  admin-only; §2 the two-column role × surface matrix, styled after `Quotas.vue`'s
  skeleton/error/grid states.

Full contract, including exact payload shapes and the two-step recipe for adding a surface:
[SPEC.md — Role visibility](./SPEC.md#role-visibility).

### Load-bearing decisions

- **The matrix is a new doctype, not more fields on `FCRM Settings`.** `FCRM Settings` grants
  `rwcd` to Sales Manager (confirmed against `fcrm_settings.json`), so putting the matrix
  there would let a manager rewrite their own row through the generic document API — the
  exact escalation this pane exists to prevent, and the same class of problem
  `test_admin_only_actions.py` already guards elsewhere. `CRM Access Settings`'s door is
  closed to managers entirely; their writes go through the one narrow endpoint instead.
  `enable_sales_hierarchy` stays on `FCRM Settings` rather than migrating across, since the
  new pane can simply read and write it where it already lives.
- **There is no System Manager column, enforced twice.** Nothing is hideable from an
  administrator, so an administrator can never configure themselves out of the pane that
  would undo it — recoverable by construction, not by a reset button. `set_visibility`'s own
  role check and `CRMAccessSettings.validate()` (`reject_unconfigurable_roles`) both reject a
  non-configurable role, independently, because the desk form is a second door onto the same
  doctype.
- **New installs get safe defaults; existing sites — MBP's live v3.10.1 included — do not
  change.** `after_install` writes `enable_sales_hierarchy = 1` and
  `manager_outside_hierarchy = "Own records only"`; there is no migration patch, so an
  upgraded site keeps exactly the behaviour it already has. Getting the discriminator right
  took two tries:
  - `frappe.db.get_single_value` does **not** return `None` for a Single that has never been
    saved — it casts to the fieldtype's zero value (`""` for a Select, `0` for a Check). A
    guard written against `is None` never fires; that mistake shipped once here and had to be
    reverted. `""` being falsy is what makes `(value or "All records")` land on the historical
    answer regardless — the *code* was right, the *reasoning* about `None` was wrong, and both
    this file and the design doc originally repeated the wrong reasoning before being
    corrected.
  - **A `Singles` row's existence is not a proxy for "an administrator configured this."**
    `update_single` deletes and reinserts a row for *every* field of a Single on every save,
    and `add_standard_dropdown_items` saves `FCRM Settings` 13 lines before
    `ensure_access_defaults` runs inside `after_install` — so by the time a row-existence
    guard would check, the row already exists and says nothing about intent. The first attempt
    used row existence anyway and shipped a worse bug than the one it fixed: on a fresh
    install `enable_sales_hierarchy` became unreachable, landing on hierarchy **off** plus
    managers **scoped** — the inverse of intent, and worse than doing nothing, because with
    the hierarchy off every Sales Manager is narrowed to their own records everywhere at once.
    The real discriminator is `frappe.flags.in_install`, which the installer sets for the
    whole `after_install` hook loop and nothing else touches afterward — so
    `FCRMSettings.restore_defaults` (which also calls `after_install`) now does nothing on a
    site that already exists, instead of silently re-narrowing every out-of-tree manager on a
    site an admin already configured.
- **Scoping had to reach plans and quotas, not just leads and deals.** The out-of-tree rule
  was first wired into `org_hierarchy.py` alone, which left `crm_rep_plan.py`'s own copy of
  the same "Sales Manager sees everything" branch — backing `CRM Rep Plan`'s permission query,
  `visible_reps()`, and quota's `_only_own_team` — unrestricted. That is every rep's
  compensation figure, precisely the invariant SECURITY.md names, and the inconsistency was
  one this change introduced rather than inherited (before it, all four were uniformly
  unrestricted). Fixed by routing `crm_rep_plan.visible_users()` through the same
  `manager_outside_hierarchy_sees_all()`, so `CRM Suggestion` and `CRM Forecast Snapshot` —
  which already called `visible_users` for their own scoping — inherited the fix rather than
  needing a fourth copy of the branch. Net effect under `Own records only`: an out-of-tree
  manager sees their own rep plan, their own quota row, and their own suggestions plus
  unowned team-wide signals — and forecast snapshots go empty rather than merely narrower,
  since a `scope: "Site"` row is refused outright and an out-of-tree manager owns no
  `Team`-scoped row either.
- **The write endpoints are POST-only, not a bare `@frappe.whitelist()`.** A bare whitelist
  admits GET, and frappe skips CSRF validation for safe methods — the only CSRF-unchecked
  route into a privileged write this pane has. Not exploitable the day it shipped (frappe
  rolls back a safe-method transaction), but latent: one stray `frappe.db.commit()` later in
  the request path would have made it live, and in the meantime a GET reported success while
  persisting nothing — which would have had the pane telling an operator "saved" falsely.
- **`get_visibility` and `get_data_access` use a module-local `_require_crm_user()`
  (`crm.api.session.CRM_ALLOWED_ROLES`), not the app's usual `sales_user_only`.**
  `crm.utils.is_admin()` means the literal `Administrator` account, so `sales_user_only`
  refuses a user holding only `System Manager` — reachable via `bench add-system-manager` or
  the desk, and admitted to the CRM by `get_session_role_flags`. These two endpoints gate the
  shell's own chrome and the pane an administrator would use to fix their own access, so they
  must not be the thing that locks such an administrator out. Write endpoints keep
  `frappe.only_for` unchanged: only the two reads needed the wider gate, and widening
  `sales_user_only` itself would touch roughly twenty endpoints for a change that deserves its
  own review, not a drive-by here. (The wider version of this gap — a System-Manager-only
  account 403ing on the app's other `sales_user_only` endpoints, e.g. the dashboard and
  `ask_mentor` — predates this feature and is unfixed; the audit surfaced it, this feature
  does not close it.)
- **`bench install-app crm --force` re-runs `after_install` with the install flag set**, so it
  rewrites both access settings over an administrator's own configuration. Correct semantics
  for a forced install — it is meant to reset the app — but worth knowing before running one
  against a site an admin has already tuned.
