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

---

## Upstream port — frappe/crm v1.83.0

**Completed 2026-09-10.** Branch `fix/upstream-v1.83-port`, ten commits, one per fix.

### Where upstream actually is, relative to us

We descend from upstream **`develop`** (which calls itself `2.0.0-dev`), not from the line
its releases are cut on. `git merge-base develop upstream/develop` is `7dcd8430d`,
2026-08-13 — upstream's own PR #2664 — with 144 upstream develop commits landed since.
Upstream's `main` / `main-hotfix`, where every `v1.x` tag lives, split off `develop` at
`0fa0ae132` on 2025-03-24 and has been maintained by backport ever since.

Two consequences worth writing down, because both cost time to rediscover:

- **No `v1.x` release tag is an ancestor of our history** — all 258 checked. "Which upstream
  release are we on" has no clean answer; the honest one is "roughly `v1.81.2`-era develop",
  that release having been cut the same morning as our merge base. The familiar "17 months
  diverged" figure is the distance to the *release* line, not to develop.
- **An upstream range must be read as a net per-file diff, never as a series of
  cherry-pickable commits.** `2826f2d35` in this very range ships literal `<<<<<<< HEAD`
  markers in `Field.vue`, cleaned up only by a later "resolve merge conflicts" commit.
  `git cherry -v develop <new> <old>` is the right first filter — it found 5 of the 41
  commits already present verbatim — but it is patch-id exact, so a fix we already carry in
  adapted form reads as missing and every remaining commit still needs reading against our
  file. Three of the "missing" ones turned out to be present, one of them with a fuller
  rationale than upstream's and extended to `crm/api/whatsapp.py` besides.

### What was ported

Ten fixes: the erpnext `standard_rate` `None` that made `frappe.db.set_value` raise
IntegrityError on a NOT NULL Currency column; the `delete_doc` realtime race that flashed
"Document does not exist" for a delete that succeeded; the kanban task three-dot opening the
edit modal, its unawaited delete, and the missing confirmation; HTML email templates silently
not applying; grid `read_only` on the two controls that reach it; list scroll position across
grouping; filter date pickers ignoring the system date format; the Data tab resetting on save;
silent activity-timeline load failures; and duplicated numeric field descriptions.

### What was deliberately not ported

Each of these is a decision of its own, not an oversight:

- **`fetch_from` support.** The one genuine capability gap in the range — we have no
  `fetch_from` handling anywhere in the frontend, and Frappe doctypes use it freely. A
  feature, though, not a fix, and it drags in `utils/fetchFrom.js`, an `applyFetchFrom` hop in
  `document.js`, and the `Grid.vue` `disabled` rework.
- **Visited-record `_seen` dimming.** A feature, and it adds a whitelisted endpoint
  (`crm.api.doc.add_seen`), `track_seen` on Deal and Lead, and a patch.
- **The frappe-ui/editor migration** (`RichTextField.vue`, `TextEditorControl`, the bubble
  toolbar, and the seven call sites that follow). We are on frappe-ui beta.55 against
  upstream's beta.29; check what we already did differently before adopting theirs.
- **`ViewControls.vue` param stabilisation.** Defensive, not a live bug: we set
  `list.value.params` immediately after creating the resource, and we have roughly ten more
  `list.value.params` call sites than the patch covers.
- **`@vitejs/plugin-vue` in `vitest.config.js`** — needed only for component tests, which
  our coverage config excludes on purpose.

### Load-bearing decisions

- **The Data-tab fix is deliberately not upstream's.** Our `Tabs` is the frappe-ui v1 one: it
  selects by trigger *value*, and it already falls back to the first selectable tab when the
  bound value is not among them. Upstream's index-plus-name dual model exists to reconcile a
  numeric index we do not use, and porting it verbatim would have added reconciliation logic
  fighting our own Tabs. `FieldLayout` instead gained a single optional `activeTab` model —
  the other fifteen call sites bind nothing and keep the local ref they had — and `DataFields`
  parks the value in `sessionStorage` per doctype and docname. That also removed the need to
  thread state through `Activities.vue` at all, which upstream had to do.
- **Most of the new grid `read_only` bindings are unreachable, and that is the point.** The
  cell block opens with a read-only *display* control whose `v-if` claims every fieldtype
  except a named list, so a `read_only` Link, Select, Date or textarea never reaches its real
  control. Only Check (excluded from that list, and honouring `editable_grid` but not
  `read_only`) and the fallback control (reached by a `read_only` Geolocation, HTML or Text
  Editor) were live bugs. The other seven bindings are added for consistency with `Password`,
  which already carried the same unreachable binding, so the block states the rule one way
  throughout and narrowing that exclusion list later cannot quietly reintroduce the bug.
  Upstream needs all of them because its `fetch_from` disables fields that are not `read_only`.
- **The delete race is fixed at three call sites, not one.** Upstream patched
  `DeleteLinkedDocModal`; `MobileContact.vue` and `MobileOrganization.vue` are ours and call
  `useDocument` for the record they then delete, so they had the identical race and upstream's
  patch could not have covered them.
- **The task delete gained a confirmation** because fixing the three-dot click made an
  unconfirmed, irreversible Delete reachable for the first time. It uses our own
  `ConfirmDelete` two-step, the idiom the settings lists already use, rather than upstream's
  `DeleteLinkedDocModal`.

### Verification

572 frontend unit tests and 1786 python tests (four blocks, all OK) pass, `ruff`, `eslint` and
`prettier` at the CI-pinned 3.2.5 are clean, and the production build succeeds. Playwright was
run twice against the same dev site, once serving this branch and once serving `develop`, and
produced an **identical 9-failure / 16-pass / 2-not-run result** — no regression either way.
Those nine are pre-existing in that environment: the manager demo account 401s on login, which
strands the `manager` project, and `convert` leaves its dialog open. They are not this port's
and are not fixed by it.

---

## frappe-ui v1 release-candidate migration (beta.63 → beta.76)

Landed 2026-09-21 on `chore/frappe-ui-v1-beta76`, after dependabot's beta.70 bump (#265)
went red and was closed as not-a-bump. frappe-ui's beta.65+ is its v1 RC batch: 311
commits, ~25 marked breaking, and upstream frappe/crm is still on beta.29, so there was
no port source — the migration was ours to do.

### What actually broke

Far less than the breaking-commit list suggested. The production build had **no loud
breaks**; every import still resolved. The silent ones, all fixed in the frontend:

- `SidebarItem` `to` → `route` (the one that turned #265 red: every nav row became a
  button with no href), `Sidebar` `disable-collapse` → `collapsible` inverted.
- `Tabs` `#tab-item` slot prop `selected` → `active` on the four record pages.
- `Tooltip`/`HoverCard` `hoverDelay` in milliseconds.
- `Popover` trigger slot lost `toggle` (now `setOpen`) and **wires its own click** —
  IconPicker consumers that also called `togglePopover()` would toggle twice and stay shut.
- `trigger="hover"` Popovers → `HoverCard`; `placement` → `side`+`align` on Popover and
  Tooltip (dead since beta.63, now anchoring correctly).
- 19 `rounded`/`rounded-lg` sites had emitted no CSS since the radius aliases went;
  `tokens-v2 --radius-only` renamed them.

### Load-bearing decisions

- **Codemods first, then grep for what they leave behind.** `navigation-v1` renamed the
  slot destructuring but not the `:class` that read `selected` three lines down.
  `tokens-v2` rewrote the `${rounded}` template literal in `utils/gauge.js` into
  `${rounded-4}` — vitest caught it; revert that file after every run of the codemod.
- **The tailwind-4 compat layer stays.** frappe-ui's peer is `tailwindcss >=3.4.2 <4`;
  `tailwind.preset-v4.js` and `src/lib/frappe-ui-compat/` are as necessary at beta.76 as
  at beta.63. The `frappe-ui/internals` vite alias points at a file upstream deleted;
  nothing imports it, so it was left for the next person who touches that block.
- **HoverCard bodies lose their own surface classes.** HoverCard renders its content
  inside `PopoverPanel`, so the `bg-surface-elevation-2 rounded-*` the old bare Popover
  needed would have drawn a panel inside a panel.

### Verification

vitest 49 files / 633 tests; Playwright 27/27 against the built app served from the dev
bench; a scripted pass over every route in both themes recorded zero Vue warnings and no
page errors. The dev site needed four adjustments to match CI's fresh site for the e2e
run (test flag, outgoing mail account, demo passwords, forecasting mandatory fields);
the recipe is in the machine-local memory, not here, because it is about this bench.

---

## Upstream port — frappe/crm v1.84.0 → v1.86.0

**Completed 2026-10-09.** Branch `fix/upstream-v1.86-port`, 26 commits, one per fix (#2722
and #2837 share one; #2813 includes its follow-up `9dde67afb`).

### Where upstream is

The merge base is still `7dcd8430d` (2026-08-13), and upstream `develop` is now 742 commits past
it. As before, no `v1.x` tag is an ancestor. The release notes for v1.84.0, v1.85.0, v1.85.1 and
v1.86.0 were used only as a **list of PRs to read**. Each fix was taken from its original merge
commit on `upstream/develop` (`<merge>^1..<merge>`), not from the backport. They are merge
commits, so `--grep='#NNNN)'` finds nothing; grep `#NNNN` with `--merges`.

### What was ported

- **Email and conversion:**
  - replies sent with the customer's address as the sender (#2897);
  - Lost, Junk and Unqualified leads converting to deals and being reset to Qualified (#2813);
  - no-reply and mailer-daemon mail becoming leads (#2915);
  - `no_of_employees` dropped on conversion (#2751).
- **Calls and routing:**
  - site-file call recordings not playing (#2874);
  - a TypeError calling a deal with no primary contact (#2903);
  - a transient users-fetch failure sending a CRM user to Not Permitted (#2261, router half).
- **Lists:**
  - one global default view, so setting it on Deals wiped Leads (#2722 + #2837);
  - an unsaved filter lost on re-entering a cached view (#2905);
  - the quick filter rewinding while typing (#2822);
  - no quick filters on mobile (#2786);
  - the clipped quick-filter select (#2842);
  - bulk edit swallowing failures and unable to set a Lost status (#2733).
- **Fields and side panel:**
  - double error toasts on every failed inline save (#2821);
  - primary contact not first or expanded (#2699, #2778);
  - details panel width lost on reload (#2754);
  - no "Create new" on side-panel Links (#2834);
  - Autocomplete refusing free text (#2675);
  - edit-layout tooltip (#2876);
  - grid header misalignment (#2929);
  - email-template select placement (#2868);
  - untranslated Select labels (#2810).
- **Activity and files:**
  - new emails not appearing live (#2797, new-email half);
  - web-link attachments never completing (#2831);
  - the uploader losing the doctype's public default and limits from the second open
    (#2918).

### Already present

#2228 (`@me` in export-all), #2610 (notification links into the CRM UI) and #2655 (Phone
field branch) were in our history. #2787 and #2788 (call-log and deal-contacts read checks)
were present in our own form. **#2805 (assignment write check) must not be taken:** ours,
`crm/api/todo.py` `may_assign`, deliberately does not exempt `ignore_permissions`, while
upstream's does, which leaves the `assign_to.add` path open.

### What was deliberately not ported

- **Features, as product decisions rather than maintenance:** the command palette (#2921 and
  its fixes #2926 and #2952), workflow automations (#2783, #2945, #2953), the onboarding "first
  web form" step (#2887), and the ERPNext quotations tab (#2938).
- **#2846 (LDAP users skip password setup).** We have no password-setup flow.
- **#2934 (web form stamps the target doctype).** At our frappe pin, `accept()` resolves the
  doctype server-side; the client value matters only under the Payments app override.
- **#2926's button half.** Upstream says an exposed ref doesn't write through. That is not
  true on our Vue 3.5: a minimal mount of our `emailBox` wiring under happy-dom opened the
  box.
- **#2623 (read-only TextEditor → `v-html` + sanitizeHTML).** A refactor, not an XSS fix: our
  read-only TipTap already drops scripts and `on*` attributes through its schema. It belongs
  with the editor migration deferred in the v1.83.0 port.
- **#2797's read-receipt half.** Frappe marks an email read with `frappe.db.set_value`, which
  emits no realtime event, so there is nothing to listen for.
- **#2261's store edits.** Session expiry is handled globally in `main.js` /
  `utils/sessionExpiry.js`.
- **#2751's `OrganizationModal.vue` hunk.** It makes no difference here: the
  `Object.assign(props.data)` that follows overwrites the default either way.
- **#2918's `filesUploader.test.js`.** It mounts `.vue` files, and our vitest has no vue plugin
  on purpose. The derivation moved to `utils/fileUploaderDefaults.js` and is unit-tested there
  instead.
- **Vite 8 (#2601).** We were already ahead.
- **A fix of our own for `get_call_log` naming a lead or deal the caller cannot read.** The
  first attempt was built, reviewed and dropped. Hiding `_lead`/`_deal` turned on the modal's
  "Create Lead" button. That either redirected to the hidden lead, or, for a hidden deal,
  created a duplicate lead. And the name was still in `reference_docname` and `links[]`, which
  are permlevel 0 and readable via `/api/resource`. Fixed later, as a decision about what a
  call log may reveal of its links: see "Call logs never name a hidden lead or deal" below.

### Load-bearing decisions

- **#2822 is not upstream's counter.** A skip-counter leaks when a save-triggered re-read
  changes nothing, and then swallows the next real change. Instead, each re-read holds a token
  in a `Set` until it settles and Vue has flushed the watchers it queued. The `getView`
  watcher stands down while any token is held. Known gap, shared with upstream: a real view
  switch made inside that one-request window is also ignored.
- **#2261 retries a failed users resource:** `await (users.error ? users.reload() :
  users.promise)`. frappe-ui never replaces a failed resource's promise, so upstream's
  `next(false)` alone would refuse every later navigation until a reload.
- **#2874 hardens upstream's site-file check.** A `recording_url` containing `..`, `%2e` or a
  backslash still goes through the proxy, so a crafted URL cannot point the audio element at
  another endpoint on the site.
- **#2675 also covers the grid Autocomplete** (`Controls/Grid.vue`), which upstream missed.
  Both use one helper, `withCustomValueOption` in `utils/fieldTransforms.js`.
- **#2810 also translates two sites of ours:** the side panel and the quick-filter options in
  `crm/api/doc.py`. The Form Builder's options editor stays untranslated, since it edits the
  options themselves.
- **#2733 extracts `Controls/LostReasonFields.vue`,** shared by `LostReasonModal` and bulk edit.
  It keeps our `reportActionError` catch, the `frappe-ui/experimental` TextEditor import and the
  "enqueued (≥20)" toast. Frappe also raises its own enqueued alert, so a large bulk edit may
  show both.
- **#2786 gives mobile quick filters their own scrolling row** above the toolbar, instead of
  squeezing them into it.

### Verification

- **Implementation:** four parallel worktrees, one per area, combined onto the branch without
  conflicts. Bench runs were serialised with `flock` because the worktrees share `test_site`.
- **Tests:** vitest 55 files / 663 tests. The full python suite passed with
  `PYTHONPATH=/workspace/.worktrees/upstream-v1.86-port`, and `crm.__file__` resolved to the
  worktree: 616 + 1181 + 216 (26 skipped) + 53 = 2,066 tests, all OK.
- **Lint and build:** eslint, prettier 3.2.5 and ruff 0.8.1 are clean, and the production build
  succeeds.
- **Review:** the `upstream-port-reviewer` found no local change overwritten. Its one
  medium-severity finding was the call-log fix above, which was dropped. It also flagged the
  #2751 tests as able to pass on a dirty site, and they now use unique organization names.
- **Not done:** Playwright and browser QA. Worth a manual look on the built app: the mobile
  quick-filter row, the select placements, the lost-reason fields in bulk edit, and the side
  panel's "Create new".

## Upstream port — frappe/crm v1.87.0

**Completed 2026-10-13.** Branch `fix/upstream-v1.87-port`, 11 commits, one per fix.

### Where upstream is

The merge base is still `7dcd8430d` (2026-08-13); upstream `develop` is now 1,253 commits past
it. As before, the release notes were used only as a list of PRs to read, and each fix was taken
from its original merge commit on `upstream/develop` (`<merge>^1..<merge>`), not from the
mergify backport.

### What was ported

- **Calls:** the referenced lead or deal shown instead of a phone-number match, with the name
  withheld when the caller cannot read the reference (#2974); a task or note created from the
  call modal linked to that lead or deal (#2775).
- **Board:** a lost-reason prompt when a lead or deal card is dragged into a Lost column (#2884).
  Before, `validate_lost_reason` refused the write and the card snapped back with nothing to fill
  in, so a record could not be marked Lost from the board at all.
- **Users:** role changes and invitation acceptance refused for a user whose roles a Role
  Profile governs, since `User.validate` reverted them silently (#2856).
- **Onboarding:** the cached first lead or deal validated server-side before navigating (#2861).
- **Lists:** a kanban column's `page_length` no longer replaces the list's own in the response
  (#2850).
- **Telephony:** Exotel statuses mapped onto the Call Log Select, with an empty second-leg
  status left unset instead of overwriting a real one (#2780). We carry the handler; nothing on
  prod uses Exotel, so this is hygiene.
- **Settings and layout:** the email account saving when only "Create Lead from Incoming
  Emails" changed (#3002); the Data tab header and Save button sticky while scrolling (#2939);
  the brand favicon on the dashboard, data import and persona pages (#3003); task row dividers
  aligned (#2949).

### Already present

#2861's `get_list` half: both onboarding endpoints were already permission-aware here.

### What was deliberately not ported

- **#2975 (workflow builder error placement).** Workflow automations were never taken; the fork
  shipped its own deterministic automation rules (`CRM Automation Rule`) on 2026-08-14, five
  weeks before upstream merged theirs.
- **#2979 (Meta lead sync window).** The lead-sync doctype does not exist here.
- **#2879 (CRM Territory as a NestedSet).** We removed the territory tree on purpose:
  `crm/patches/v1_0/drop_crm_territory_tree_fields.py` records why. Every territory filter in
  the app is an equality match.
- **#2951 (remove the single All tab).** Our notifications panel has two tabs, All and Events.
- **#3000 (priority bars).** Our `TaskPriorityIcon` is a deliberate redesign with its own
  contrast rationale, and the comma-expression bug upstream was fixing is already fixed here.
  Icons in the priority dropdown are a design choice, not a defect.
- **#2972 (persona option order and Skip).** Upstream's product opinion about its own
  onboarding questionnaire; ours is already customised.
- **#2850's frontend default and its e2e spec.** Reviewed as possibly needed, since `getParams`
  seeds `page_length` from the first response. Checked in the browser instead: a cold load of
  the leads list went from 20 of 136 to 40 of 136 on one Load More, so the first page's
  `page_length` is already a number by the time it is added to.
- **#2884's in-place revert, its `from`/`fromIndex` payload and its toasts.** The board reloads
  on failure or cancel, which is what the task closing-note flow already does; one convention,
  not two. The failure toast is `reportActionError`, as everywhere else.

### Load-bearing decisions

- **#2884 reuses `LostReasonModal`** rather than a second dialog: it now accepts no `document`
  and emits `save`/`cancel`, and `ViewControls` wraps it in a promise the way
  `collectClosingValues` already works. The Dialog's close also fires `cancel` after a save, so
  the promise settles once. Upstream's other half, saving where the card was dropped in its new
  column into the view, is taken too (`persistKanbanColumns`); a same-column reorder already did.
- **The Exotel webhook test leaves state behind.** `create_call_log` commits, so
  `test_first_event_without_status_still_creates_call_log` leaves `CRM Exotel Settings` enabled
  with the token `test-token` on the test site. Same as upstream; the other Exotel tests set
  `enabled` explicitly, so nothing depends on it being off. Remember it when one does.
- **#2974's `get_call_contact` checks `has_permission` with `doc=`** (our convention) and
  falls back to `lookup_contact_by_phone_number`, the unrestricted lookup, exactly where the old
  code called it. The `_lead`/`_deal` names a caller cannot read were still returned by
  `get_call_log` at this point; that was the open item from the v1.86 port, fixed in the
  "Call logs never name a hidden lead or deal" section below.

### Verification

- **Tests:** vitest 55 files / 663 tests. The ported Python modules pass against the worktree
  (`crm.__file__` resolved to `.worktrees/upstream-v1.87-port`): call log 40, role profile 5,
  user roles 4, onboarding 10, page length 2, integrations 42. The full python suite passed
  with `PYTHONPATH=/workspace/.worktrees/upstream-v1.87-port`: 616 + 1214 + 216 (26 skipped)
  + 53 = 2,099 tests, all OK.
- **Lint and build:** eslint, prettier 3.2.5 and ruff 0.8.1 clean; production build succeeds.
- **Review:** the `permissions-reviewer` found no leak. Its two low findings were taken: a
  forced delete leaves a call's reference dangling and `has_permission` on a missing name
  raises, so `get_call_contact` now checks existence first (both branches answer `{}`); and
  the role-profile guard in `update_user_role` now runs after the System Manager and Sales
  Manager checks, as it does in `remove_crm_roles_from_user`, so a caller who may not touch
  the user does not learn how their roles are managed. It also noted that `get_linked_calls`
  now returns `reference_docname`, which is the same name-only leak class as the then-open
  call-log item, not a new one (both closed in the next section). The `upstream-port-reviewer` found no local change overwritten and no
  ported test passing for the wrong reason; its findings became the Load More check above, the
  column-order half of #2884, and a second lead sharing the number in the dangling-reference
  test, so a fallback to the phone lookup would fail it.
- **Browser (Playwright script against the dev bench serving the worktree build):** dragging a
  lead into Unqualified opens the Lost Reason dialog; Cancel reloads the card back into New; an
  empty Save shows "Lost Reason is required"; choosing a reason and saving writes the status and
  `lost_reason`. The Data tab's header and Save stay in view when the fields scroll. The Chrome
  extension was not connected, so this was scripted rather than driven by hand; the CI Playwright
  job on the PR covers the suite.

---

## Call logs never name a hidden lead or deal

**2026-10-13.** The open item carried through the v1.86 and v1.87 ports. The design was built
on 2026-10-09 in a parked worktree (`open/a-calllog`, never pushed) right after the v1.86
merge, and landed here rebased onto the v1.87 port, which had changed the two places it
interacts with.

### The problem

A call log is visible to its owner, caller and receiver even when the lead or deal it hangs
off is not (`crm.permissions.linked_records`): a rep's own call on a reassigned lead stays
theirs. The call then named that record on every read path: `get_call_log` resolved it into
`_lead`/`_deal`, the modal drew a link to it, and `reference_docname` and `links[].link_name`
are permlevel 0, so `/api/resource`, `frappe.client.get` and the desk form load returned it
raw. The names are naming-series IDs, so the record never leaked, only that it exists and
which calls touched it; the first attempt in the v1.86 port showed that hiding `_lead`/`_deal`
alone made things worse (Create Lead appeared over an already-linked call).

### The decision

**A call log may say that it is attached to a record the viewer cannot read, but never which
one, and the app never acts on that record for them.** Concretely:

- `redact_hidden_references(calls)` in `crm_call_log.py` blanks `reference_docname` and drops
  the `links` rows that name a `CRM Lead` or `CRM Deal` the session user cannot read, and
  marks the call `_has_hidden_reference`. Readability is `frappe.get_list` under the session
  user, the same row scoping the Leads and Deals lists apply, batched per doctype. A name that
  no longer exists hides nothing.
- It runs on every path that serves a call: an `apply_fieldlevel_read_permissions` override
  on the Document (frappe calls it from `/api/resource`, `/api/v2/document`,
  `frappe.client.get` and `frappe.desk.form.load.getdoc`), `get_call_log`, the CRM list via
  `parse_list_data`, and the timeline rows of `get_linked_calls`, where the join lays one link
  row flat as `link_doctype`/`link_name` next to the call's own reference.
- **Redaction must not hand the name back another way.** `get_call_contact` falls back to the
  phone-number match only for a call that points at nothing; once `_has_hidden_reference` is
  set it answers Unknown. Without that, blanking the reference re-named the hidden lead
  whenever it was the record on that number, which is the common case. The test for it puts
  the hidden lead's number on the call.
- **A bare name counts.** A list asked for `reference_docname` without `reference_doctype`
  (a custom column set, or `link_name` on a timeline row) still carries the name, so a name
  without its doctype is tried under every scoped doctype; one that exists nowhere hides
  nothing. Kanban columns of `get_data` go through `parse_list_data` like the list does.
- `validate` puts a hidden reference or link row back, at its stored position, if a save of
  the redacted document would drop it, so a rep who edits the call (status, note) from what
  they were served cannot detach it from a record they cannot see, nor move a hidden lead link
  behind their own (the first lead link is the call's lead to readable users).
- **The save response is redacted too.** `frappe.client.save` / `set_value` and the v1
  resource PUT return the saved document without the read-path hook, and `validate` has just
  put the reference back on it. `on_change`, the last post-save hook and after the Version
  row is written from the restored document, redacts the in-memory document again. It stands
  down for `ignore_permissions` saves and Guest, which is how the Twilio and Exotel webhooks
  write.
- The notes and tasks served with a call (`_notes`, `_tasks`) carry their own
  `reference_docname`; those are blanked the same way, without hiding the note or task.
- **The phone-number fallback reads only what the viewer may read.** `get_call_contact` now
  uses `get_contact_by_phone_number`, the restricted lookup, for a call that points at
  nothing; the unrestricted `lookup_contact_by_phone_number` is for the webhooks. Before, a
  manual call from a hidden lead's number named that lead by its display name, the one real
  display-name disclosure the review found; everything else was the naming-series ID.
- `create_lead_from_call_log` returns a readable lead the call already has, whatever else it
  links; otherwise it refuses, with a `PermissionError` that does not name the record, a call
  that references or links a hidden lead or deal, and refuses with a `ValidationError` a call
  already on a deal.
- The modal shows "Linked to a record you don't have access to" where Create Lead was, and the
  reference row (with its link arrow) is simply absent, as it is for an unlinked call. A note
  or task created from such a call is not pointed at the hidden record.

### Not covered, on purpose

Generic queries that ask for `reference_docname` by name (`frappe.client.get_list`,
`frappe.client.get_value`, `/api/resource/CRM Call Log?fields=[...]`, reportview and export,
child-table reads of `Dynamic Link` with `parent_doctype`), and filtering on
`reference_docname = <guess>` as a yes/no oracle. Frappe has no row-scoped column redaction;
only permlevel, which is role-based and would hide the field from every Sales User, including
on calls whose lead they own. Those paths return the opaque ID, which is the same disclosure
every `reference_docname` on a note, task or event makes across the framework. Closing it
would mean a `get_list` override or moving the reference out of a readable field.

Over-redaction is accepted in two edges: a lead shared with the rep through DocShare is
readable by `has_permission` but absent from `get_list`, and User Permissions narrow
`get_list` but not the call-log scoping. Both hide a name the rep could open, never the
reverse.

### Verification

- `crm.fcrm.doctype.crm_call_log.test_crm_call_log`: 62 tests OK, 22 of them in
  `TestCallLogHidesUnreadableReferences`, covering `get_call_log`, `frappe.client.get`, the v1
  and v2 resource APIs, `getdoc`, the CRM list (with and without `reference_doctype` in the
  rows), the timeline (hidden deal by link and by reference), the phone-number fallback for a
  flagged call and for an unreferenced one, the task payload, the `set_value` response, the
  refused Create Lead with no name in the message or the message log, the readable lead
  beside a hidden deal, the save round-trip and link order, and that the owner, an in-tree
  Sales Manager and Administrator still see everything. Neighbouring modules
  (`test_linked_record_permissions`, `test_activities_permissions`,
  `test_activities_timeline`, `test_integrations`, `test_exotel_realtime`,
  `test_list_page_length`, `permissions.test_org_hierarchy`, `test_rep_planning`,
  `agent.tests.test_signals`) OK.
- **Review:** the `permissions-reviewer` read the first cut as incomplete, not unsound, and
  every finding was taken: the save response (HIGH), bare-name list rows and the kanban
  branch, the note and task payloads, the unrestricted phone fallback, link order on restore,
  and a readable lead beside a hidden deal. Its two over-redaction edges and the generic list
  APIs are recorded above as accepted. It found no under-redaction, no cache poisoning (the
  `getdoc` pickle happens before the redaction and `get_call_log` redacts an `as_dict` copy),
  no attach or duplicate abuse through the restore, and no regression for the webhooks.
- Full python suite with `PYTHONPATH=/workspace/.worktrees/call-log-hidden-reference`:
  616 + 1236 + 216 (26 skipped) + 53 = 2,121 tests, all OK (2,114 on the first cut, before the
  review).
- vitest 55 files / 663 tests; eslint and prettier 3.2.5 clean on the modal; ruff 0.8.1 clean.
- **Browser (Playwright script against the dev bench serving the worktree build):** a throwaway
  Sales User who was the caller on a call referencing a lead owned by Administrator. As the
  rep: the lead GET is 403, the raw call GET has no `reference_docname`, no lead link row and
  `_has_hidden_reference: 1`; `get_call_log` names no `_lead` and shows the receiver as
  Unknown; the list row says Unknown; the modal shows "Linked to a record you don't have
  access to" with no Create Lead and no Lead row; the lead's ID appears nowhere in the page.
  As Administrator the same call shows the lead's name, the Lead row with its link, and no
  message. No console or page errors. The QA user, lead, call and the view filter the probe
  accidentally saved were deleted afterwards.
- A caveat met on the way: in the call-log list every labelled cell applies a quick filter on
  click and the fork persists it to the user's standard view, so a scripted click on the
  receiver cell left the rep's list filtered to `receiver = Unknown`. Click the duration cell.


---

## Upstream port — frappe/crm v1.88.0

**Completed 2026-10-20.** Branch `fix/upstream-v1.88-port`, 6 fix commits, one per fix.

### Where upstream is

The merge base is still `7dcd8430d` (2026-08-13); upstream `develop` is now 1,550 commits past
it. As before, the v1.88.0 release notes were used only as a list of PRs to read, and each fix
was taken from its original merge commit on `upstream/develop` (`<merge>^1..<merge>`), not from
the mergify backport. **v1.88.0 is the scope, not a position:** neither v1.87.0 nor v1.88.0 is
an ancestor of `upstream/develop` or of ours. Develop-only fixes from the same window that no
release carried yet are listed at the end for the next port.

### What was ported

- **Email multiselect** shows users again (#3072). `const { allUsers } = usersStore()`
  unwrapped a Pinia computed to an array and then read `.value` on it, so users mode offered
  nothing: Settings → Users → Add existing user had no suggestions. `storeToRefs` fixes it.
- **Default view** survives an edit to a standard view (#3035). `create_or_update_standard_view`
  wrote `is_default = view.is_default or False` on every save; only `set_as_default` sets it
  now. The views dropdown marks the default and Set As Default closes the menu. The dashboard
  drill-down's `standardViewPayload` already echoed `is_default` back to dodge this; that is
  now redundant and was left alone.
- **Tasks empty state** uses the tasks icon (#3029).
- **Inline email colours on the dark theme** (#2989, the colour half), adapted; see below.
- **Enrichment runs are row-scoped** (#3062), adapted; see below. A real leak: Sales User
  could list every `CRM Enrichment Run` on the site, including emails, phones and `raw_json`,
  for leads and deals the hierarchy hid.
- **Enrichment edge cases** (#3064, backend only): an About page that redirects off-site is no
  longer accepted as the company's; the `HTML` scope matches markup rather than visible text;
  the `URL` scope is filled in; `Headers` (never captured) is dropped, and
  `drop_enrichment_headers_scope` moves any Headers rule to Full Text.

### Load-bearing decisions

- **#2989 is our code now.** Upstream deleted `emailColors.js`, its test, `EmailContent.vue` and
  `emailContent.css` a day after merging it (#2995, 2026-10-08), moving email rendering to
  `EmailItem` in frappe's unpublished `@framework/ui`. We keep our `EmailContent.vue` (sandbox,
  CSP, theme observer from `fe10d6346`), so a later port will see upstream "delete" these files
  and must not follow it. Adapted on the way in: the surface is our `--email-canvas`
  (`#1c1e2c`, pinned to the CSS by a unit test) rather than frappe-ui's gray; the text floor is
  AA 4.5:1 rather than 3:1, and borders keep the 3:1 non-text floor; the DOM walk lives in
  `utils/emailColors.js` so it is unit-tested; it hangs off the existing MutationObserver
  rather than `useColorScheme`. Colours are collected once, before the first theme mirror,
  while the frame is still light. Measured in Chromium against the dark canvas: inline
  `color:black` 1.27 → 16.52, `<font color=#1F497D>` 1.81 → 7.02, prose in a `bgcolor=#fff`
  cell 1.24 → 10.49; the light theme is identical after a round trip. happy-dom returns `""`
  for `<font color>`, `[bgcolor]` and inherited colour, so those three cases are covered only
  by that Chromium harness, not by the unit suite.
- **#3062 extends `crm/permissions/linked_records.py`** instead of upstream's separate condition
  in the run controller, so runs follow the same rule as notes, tasks and call logs: visible
  when the referenced lead or deal is. A run has no "own" clause (it belongs to the record, not
  whoever triggered it), uses `reference_name` rather than `reference_docname`, and a run whose
  reference is not a lead or deal (an organization) or is empty stays as visible as the
  doctype. Upstream also admits runs on records shared via DocShare; `linked_records` does not
  do that for notes, tasks or calls, so neither does this. `retry` now checks read on the run
  before it reads it: its errors otherwise confirmed that a run on a hidden record existed and
  which doctype it pointed at. If Organization or Contact ever gains row scoping, it must join
  `SCOPED_REFERENCES`, or its runs stay open; the code says so where it matters.
- **#3064 changes what HTML-scoped industry rules match.** Only industry rules read
  `match_scope`. The seeded ones are all Headline; the six seeded HTML rules are social, whose
  scope is never read. A rule an admin wrote with HTML scope now matches raw markup (more hits
  from class names, scripts and repeated nav; fewer where tags or entities split a phrase), and
  a Headers rule moved to Full Text starts matching where it never did. No patch converts HTML,
  since that would undo the fix. **Before upgrading a site with enrichment in use, check**
  `SELECT rule_type, match_scope, enabled, COUNT(*) FROM `tabCRM Enrichment Rule` GROUP BY 1,2,3`
  — if no Industry row is HTML or Headers, nothing changes. The patch is in `[post_model_sync]`
  at the end of `patches.txt`; upstream placed it mid-list next to patches we do not carry.

### What was deliberately not ported

- **#3012 (skip the desk setup wizard on Frappe Cloud).** We do not run on Frappe Cloud.
- **#3063 (lead notes in deal activity groups).** Fixes upstream's note grouping from #3020;
  our `crm/api/activities.py` has no `group_note_activities`.
- **#3051 (enrichment settings layout)** and **#3064's `DataFields.vue` hunk.** We carry the
  enrichment backend and the EnrichFromWebsite modals, not upstream's Settings → Enrichment UI;
  the hunk keys off an `enriching` document flag we do not have.
- **#3070 (EmailMultiSelect from develop).** A release-line copy of what develop, and we,
  already have. Its other half, #3071 (dead `surface-modal` tokens), was taken in the
  follow-ups below, differently from upstream.
- **#2989's resizable email/comment editor.** A feature, not a fix.
- **#3031 (settings page copy).** Wording and full stops.
- **Features:** #3018 (empty-state actions), #3036 (deal from a contact or organization page),
  #3020 (notes refresh), #3059 (upstream's enrichment UI), #3052 (frappe-ui rc.2; we are on our
  own v1 line). Product decisions, not maintenance. Two fixes ride inside #3020 and were taken
  in the follow-ups below. #3036's TDZ fix (`c6cb129d6`) does not apply: our `DealModal`
  watcher is not `immediate`.

### Follow-ups (branch `fix/upstream-v1.88-followups`, stacked on the port)

Taken the same day from the port's open list. Apart from #3071, which shipped in v1.88.0
inside #3070, they are develop-only or ride inside a feature PR, so no v1.x release carries
them yet.

- **#2858:** a layout that still names a deleted custom field no longer hands the form a bare
  string. `get_fields_layout` and `get_sidepanel_sections` build each column from resolved
  fields only (a dict lookup instead of a linear search), and `Column.vue` skips anything
  without a fieldname. Our `has_permission` guards and Select label translation survive.
- **#3034:** WhatsApp notifications name the lead (`lead_name`) or deal (organization, then
  lead name), as mentions and assignments already did, still escaped. Adapted to our
  `reference_name`.
- **#3046:** the Exotel unknown-status test clears Error Logs through `delete_doc`.
- **#3020 riders:** `DoctypeModal.update()` says "Nothing to update" and closes on an unchanged
  doc (frappe-ui's `saveIfChanged` called neither callback, so Update did nothing); `.prose-f`
  uses `break-words` instead of `break-all`, also in our `emailContent.css` copy, which upstream
  no longer has. A residual gap upstream shares: `isDirty` compares the whole doc's JSON while
  `getChangedFields` compares only present keys, so removing a key brings the silent no-op back.
- **#3071, taken differently:** Grid rows carried `bg-surface-modals`, which nothing defines,
  so rows were transparent. Upstream replaced it with `bg-surface-elevation-2`. Measured in the
  Settings modal on the dark theme, that is the modal's own colour (#212332), and it leaves a
  lighter strip beside the edit button against the row's cells (`bg-surface-base`, #131521).
  We use `bg-surface-base`, which also matches the page where Grid renders in a Data tab. A
  future diff will show upstream's class as "missing"; the comment on the row says why.
  #3071's `WorkflowFlow.vue` hunk does not apply (workflow automations were never taken).
- **#2642, already present:** `get_deal_status_change_counts` has counted distinct deals per
  stage since `a508d5e81`, covered by `test_metrics.py`. Ours also deliberately keeps deals now
  Lost in the funnel, which upstream drops.

Follow-up verification: vitest 56 files / 696 tests. The full python suite with
`PYTHONPATH=/workspace/.worktrees/upstream-followups`: 660 + 1334 + 219 (26 skipped) + 53, all
OK, including the Acumatica module that failed once in the port's second run. The new Python
tests (#2858 two, #3034 two) were run red first. Browser (Playwright against the dev bench
serving the build): Update on an unchanged note shows "Nothing to update", closes and sends no
save request; `.prose-f` computes `overflow-wrap: break-word`, and a sentence wraps at no
mid-word point while a long URL still breaks; plus the Grid measurement above.
`upstream-port-reviewer` found no local change overwritten. Its notes became the Grid comment,
a stronger escape assertion, and this section.

### Verification

- **Tests:** vitest 56 files / 696 tests. Every new Python test was run red first against the
  worktree (tracebacks named `.worktrees/upstream-v1.88`): view settings 2, enrichment-run
  scoping 2 plus the `retry` check (the first version of that test passed on the old code,
  because `_enqueue_run`'s later write check raised the same error, so it now asserts the
  refusal comes before the target is loaded), crawler 1, extractors 2. The full python suite with
  `PYTHONPATH=/workspace/.worktrees/upstream-v1.88`, before the enrichment commits:
  656 + 1325 + 216 (26 skipped) + 53, all OK. After them: 660 + 1329 + 53 OK, and the third
  block 216 with two failures in `crm.integrations.acumatica.test_outbound`
  (`test_autonumbering_never_asks_acumatica_for_a_derived_id`,
  `test_connection_error_lands_in_sync_issues_not_the_users_save`). That module passes alone
  on both this branch and unmodified `develop` (28/28), and passed in the first and third full
  runs. Cause, very likely: **two test runs on one `test_site` at once.** That run overlapped
  review agents running deal-inserting suites on the same site (one hit MariaDB deadlocks).
  `push_customer_for_deal` reads settings via `get_cached_doc`, which is shared Redis; the
  test's `_enable()` sets `enabled=1` in an uncommitted transaction, and any other process's
  deal insert (the `queue_customer_push` hook calls `get_settings()`) re-caches the committed
  `enabled=0` -- so the push returns silently, exactly the failure seen. Not a code defect;
  never run two `bench run-tests` against one site concurrently.
- **Lint and build:** eslint, prettier 3.2.5 and ruff 0.8.1 clean; production build succeeds.
- **Review:** `upstream-port-reviewer` found no local change overwritten. It found two omission
  reasons wrong: #3062 and #3064 had been left out as "no enrichment module here", but we carry
  the whole backend. Both were then taken. It also flagged the undocumented #2995 deletion, the
  #3071 and #3020 riders, and a wrong claim in the #3035 commit message about the drill-down;
  all are addressed above. `theme-contrast-reviewer`: the "Default" label's `text-ink-gray-5`
  measures 5.2–7.6:1 on every dropdown surface in both themes; `DARK_SURFACE` matches the CSS.
  It noted that a sender's `<style>` block or class-based colours are not handled, the same
  scope as upstream. `doctype-migration-reviewer`: the Select change and the patch are safe on a
  site with rule rows; the behaviour notes are under #3064 above. `permissions-reviewer`
  found no path that reads a run on a hidden lead or deal (list, count, report, export,
  `frappe.client.get`/`get_value`, desk form load, link search, print, sharing) and no
  regression for notes, tasks or calls; its lows were taken: the `retry` read check, the
  `SCOPED_REFERENCES` comment, and tests for a manager outside the hierarchy at both settings.
- **Browser:** the email colour logic was measured in Chromium with a standalone harness over
  the shipped util. The rest was driven afterwards with a Playwright script against the dev
  bench serving this worktree's build (no Chrome extension): the views menu shows "Default"
  beside List; the Tasks empty state shows the tasks icon (list response emptied in flight, no
  data touched); Add Existing User now offers a user, where the old code offered none at all.