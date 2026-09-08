# Role-based access control — audit findings and the Access Control pane

**Date:** 2026-09-08
**Status:** drafted in session, pending review
**Context:** an audit of every role gate in the app (doctype permissions, the
nine `permission_query_conditions` / `has_permission` hooks, ~40 endpoint gates,
and the frontend `isManager()` / `isAdmin()` conditions), followed by a request
for a settings pane where admins and managers can control what each role sees.

## Goal

Two things, and they are not the same thing:

1. Make the site's real access boundary **a choice an admin makes on purpose**,
   rather than a default nobody set.
2. Let admins and managers tidy the app's chrome per role — without letting that
   tidying masquerade as a permission, and without letting it become a way to
   grant one.

## What the audit found

The server side is in good shape. Every rep-scoped read on the dashboard and the
reports funnels through `crm.api.dashboard.pin_user`; `crm/api/form.py` gates all
nine authoring endpoints through `_check_manager()`; `crm_view_settings.py`
re-states its endpoint rule on the doctype itself because *"the endpoints are not
the only door"*. `crm/tests/test_security_gates.py` and
`crm/tests/test_admin_only_actions.py` hold the line on the ones that matter.
This design does not relitigate any of that.

Three findings do need answering.

**`enable_sales_hierarchy` defaults to `0`.** `crm/permissions/org_hierarchy.py`
is explicit at line 31 — *"Sales Manager outside the tree retains the default ie
sees everything"* — and on a fresh site nobody is in the tree. So a Sales Manager
reads every lead and deal on the site, and because `visible_users()` returns
`None` for them, every rep's quota target, attainment, plan and suggestion too.
SECURITY.md names precisely this as the invariant worth probing: *"rep-level
users must not read or write other reps' plans, quotas, suggestions, or deal
aggregates outside their hierarchy subtree."* The flag that enforces it is off by
default and surfaced only inside a tree editor, admin-only
(`Hierarchy.vue:290`), where it reads as a feature of that editor rather than as
the master switch it is.

**The out-of-tree case is hardcoded.** `org_hierarchy.py:30-31` and `:87-88` both
return "sees everything" for a Sales Manager who is not in the hierarchy. That is
a reasonable escape hatch for a manager who genuinely runs the whole book, but it
is also what every manager gets on a site whose tree nobody has built yet — so
defaulting the hierarchy on, on its own, just relocates the problem to the first
manager added.

**Two settings groups carry no group condition.** `Settings.vue` gates five of
its seven groups with `isManager()`. `Email` and `Integrations` do not, so their
individually-ungated items fall through to reps: `Email → Templates` and
`Integrations → Telephony`. Telephony is deliberate — a rep configures their own
agent number there and the manager-only controls inside are gated one by one
(`TelephonySettings.vue:157-191`). Templates appears to be an oversight.

So the fix is **not** symmetrical, and a group condition on `Integrations` would
be a regression: it would take a rep's own telephony configuration away. Only
`Email → Templates` needs gating, as a condition on the item.

Separately: `isSalesUser()` (`stores/users.js:148`) is exported, has no callers,
and is an exact role match where its sibling `isManager()` is inclusive — two
different meanings for one idea, waiting for someone to reach for the wrong one.

## What the pane controls

One new pane, **Settings → Access Control**, in the User Management group, in two
sections. The split between them is the honest part of this design and it is
carried in the UI copy, not just here.

### §1 Data access — server-enforced, admin only

Two switches, both of which change what the database returns:

- **Sales hierarchy** — the existing `enable_sales_hierarchy`, moved to the front
  of this pane with its consequence written out and a live count of how many
  people are actually in the tree. An admin should be able to read this section
  and know what their managers can see.
- **Managers outside the hierarchy** — a new setting,
  `manager_outside_hierarchy`, with two values: `All records` and `Own records
  only`. The field default is `All records`, and the one reader treats a missing
  value as `All records` too — `frappe.db.get_single_value` reads `tabSingles`
  and returns `None` for a Single that has never been saved, so the fallback has
  to be in the code and not only in the field. Between them, every existing site
  keeps today's behaviour with no patch.
  `after_install` then writes `Own records only` for new installs — which is
  what makes "default the hierarchy on" mean anything on a site whose tree is
  still empty, since otherwise every manager on a fresh site is out of tree and
  the flag changes nothing.

### §2 Surface visibility — chrome, admin and manager

A role × surface matrix over the two lists of surfaces the app already has: the
13 nav links in `AppSidebar.vue` and the 26 settings items in `Settings.vue`.
The section header says what it is: hiding a surface tidies the app, it does not
protect data. Where the data behind a surface is already row-scoped (Dashboard,
Reports, Planner all pin a rep to their own numbers server-side), hiding is
*purely* cosmetic and the pane says so rather than implying otherwise.

## The narrowing invariant

The property that makes §2 safe to ship, and the one thing in this design that
must not be compromised for convenience:

> **Configuration can only ever hide a surface. It can never reveal one.**

Every gate becomes `canSee(key) && <the existing role gate>`, never
`canSee(key) || …` and never `canSee(key)` alone. So a manager who unhides
`nav.analyst` for reps changes nothing: `isAdmin()` still fails in the nav, the
route guard at `router.js:64` still redirects, and `crm.agent.api.ask_analyst`
is still `frappe.only_for("System Manager", True)`. The Analyst is the existing
model for this — nav condition, route guard and endpoint gate all agreeing — and
it is the shape every surface in the matrix should be checked against.

A direct consequence worth stating: an unknown or misspelled surface key is
inert. It can only fail to hide something.

## Storage and permissions

A new Single doctype **`CRM Access Settings`**, granted `rwcd` to System Manager
and to nobody else, holding:

| Field | Type | Meaning |
|---|---|---|
| `manager_outside_hierarchy` | Select | `All records` \| `Own records only` |
| `hidden_surfaces` | Table (`CRM Role Surface`) | the §2 matrix |

`CRM Role Surface` is a child doctype with exactly two fields: `role` (Select:
`Sales Manager` / `Sales User`) and `surface` (Data). **A row's existence means
hidden** — there is no `visible` flag, because a sparse table of what has been
hidden needs no second way to say the same thing. The parent field is named
`hidden_surfaces` so a row reads correctly in the desk UI without a legend.

A child table rather than a JSON blob, deliberately: `FCRM Settings` already
holds `dropdown_items` and `event_notifications` this way, so it is the house
pattern; it stays inspectable from the bench when a customer reports a missing
menu item; and it gets Version diffs for free, which is what you want on a
change to who can see what.

`enable_sales_hierarchy` **stays on `FCRM Settings`**. Moving it would mean a
migration for a field the new pane can simply read and write, and
`org_hierarchy.hierarchy_enabled()` already reads it there.

Why a new doctype instead of more fields on `FCRM Settings`: `FCRM Settings`
grants `rwcd` to Sales Manager. Putting the matrix there would let a manager
rewrite their own row through the generic document API, which is the escalation
this pane would otherwise open — and it is the same class of problem
`test_admin_only_actions.py` was written for. The new doctype's door is closed to
managers entirely; their writes go through one narrow endpoint instead.

## The write path

`crm/api/access.py::set_visibility(role, surfaces)`:

1. `frappe.only_for(["System Manager", "Sales Manager"], True)` — the pattern
   `crm/api/quota.py::_only_managers` and `form.py::_check_manager` already use.
2. If the caller is not a System Manager, **refuse any row whose `role` is not
   `Sales User`.** A manager tunes what their reps see; the Sales Manager column
   is an admin's to set. This is the rule that keeps the pane from being a way
   for a manager to widen their own access.

   Note the matrix has **two columns, not three**: `Sales Manager` and
   `Sales User`. There is deliberately no System Manager column — nothing can be
   hidden from an admin, which means an admin can never configure themselves out
   of the pane that would let them undo it. The feature stays recoverable by
   construction rather than by a reset button.
3. Validate each key by shape — `^(nav|settings)\.[a-z0-9_]+$`, with a cap on
   count and key length — rather than against a Python allowlist. One registry
   instead of two, and the narrowing invariant already makes an unrecognised key
   harmless.
4. Save with `ignore_permissions=True`, because the doctype is admin-only by
   design and this endpoint *is* the manager's authorisation.

`§1` writes are admin-only: `frappe.only_for("System Manager", True)`.

## The surface registry

The registry lives in the frontend, extracted from the two arrays that already
*are* the list of surfaces:

- `AppSidebar.vue`'s `links` — already keyed by `to` or `action`, so
  `nav.dashboard`, `nav.analyst`, `nav.assistant` fall out of it.
- `Settings.vue`'s `tabs` — currently identified only by a **translated** label,
  so each item needs a stable `key` added. 26 one-line additions.

Both move to a shared module (`frontend/src/utils/surfaces.js`) that the sidebar,
the settings nav and the new pane all import, so a new surface is registered
once. Each entry carries the role floor the code already enforces
(`nav.analyst` → admin), which lets the pane render that cell as fixed rather
than as a toggle that would do nothing — the matrix should not offer a control
that the narrowing invariant guarantees is inert.

## The read path

`crm/api/access.py::get_visibility()` returns, for the session user:

```
{
  "role": "Sales User",
  "hidden": ["nav.notes", "settings.email_templates"],
  "matrix": null
}
```

`hidden` is always the session user's own row, and is all the shell needs.
`matrix` is `{ "<role>": ["<surface>", …] }` for a System Manager or Sales
Manager and `null` for a rep, so the pane's data arrives with the same call that
gates the sidebar and a rep never receives another role's configuration. A new
store `frontend/src/stores/access.js` exposes `canSee(key)` over `hidden`.

**Load ordering matters.** The shell must not paint a link and then retract it.
`router.js` already awaits `users.promise` in its global `beforeEach`; the access
resource joins that await, so the sidebar renders once with the right set. The
in-memory default while unresolved is *visible*, which is the correct fail-open
for chrome — but with the await in place it is not a state a user reaches.

## Server change: the out-of-tree manager

`org_hierarchy.py` gains one read of `manager_outside_hierarchy` in the two
places that currently hardcode the answer:

- `_permission_query_conditions` line 31 — instead of returning `""` for an
  out-of-tree Sales Manager, return `""` only when the setting is `All records`;
  otherwise fall through to the Sales User branch below it (own records plus
  records assigned to them), which is already written and tested.
- `_has_permission` line 86 — the same condition, the same fall-through.

Not cached, for the reason the file already gives about `_in_hierarchy`: a
`request_cache` here lives for a whole scheduler process, so a setting changed
mid-run would read stale until a restart. One `get_single_value` per check, which
frappe caches per request anyway.

## New-install default

`crm/install.py::after_install` writes `enable_sales_hierarchy = 1` and
`manager_outside_hierarchy = Own records only`. Both are stored writes rather
than field defaults, and there is no migration patch, so every existing site —
MBP's live v3.10.1 included — keeps exactly what it has; flipping it under a running trial would silently narrow what their
managers see with nothing on screen to explain it.

One consequence to document rather than hide: `FCRMSettings.restore_defaults`
calls `after_install`, so an admin pressing *Restore Defaults* on an existing
site would also switch the hierarchy on. That is defensible for a button named
"restore defaults", but it should be in the release note.

## UI

`Quotas.vue` is the model, not `SettingsLayoutBase`: it is the other grid pane in
Settings, and it already carries the four states this pane needs
(`SkeletonTable` while loading, `ErrorState` with a retry, an empty state, then
the grid). Two sections stacked in one scroll container.

§1 renders as two labelled switches with a sentence of consequence each, using
the `CheckSwitch` + `fcrmSettings.setValue` pattern from `Hierarchy.vue` — and
the same `$dialog` confirmation on the *disabling* direction, since that is the
one that widens what a manager can read.

§2 renders as a table: one row per surface, grouped by nav / settings, with a
column per role. A manager sees the Sales User column as toggles and the Sales
Manager column as read-only, matching what `set_visibility` will accept — the UI
should not offer a control the server will refuse. Cells at their role floor
render as a dash with a tooltip naming the gate.

Coloured text uses the `-9` step, per AGENTS.md, and both themes get checked in a
browser before this is called done.

## Testing

**Python** — `crm/tests/test_access_settings.py`:

- a Sales Manager may write a `Sales User` row
- a Sales Manager may **not** write a `Sales Manager` row, nor an admin one
- a Sales User may not write at all
- malformed and over-long keys are refused; the row cap holds
- **unhiding a surface does not make its endpoint callable** — a rep with
  `nav.analyst` visible still gets `PermissionError` from `ask_analyst`. This is
  the narrowing invariant as an executable assertion, and it is the single most
  important test here.
- `manager_outside_hierarchy = Own records only` changes what
  `get_deal_permission_query_conditions` returns for an out-of-tree manager, and
  `All records` preserves today's behaviour

Run against a dedicated `test_site` per AGENTS.md — the suggestion ceiling counts
site-wide rows, so a demo-laden site measures the demo.

**Frontend** — `frontend/tests/unit/access.test.js` on the pure narrowing helper:
`canSee` with no config, with a hidden key, with an unknown key, and the
`canSee(key) && roleGate` composition. Pure logic in `src/utils/`, which is
exactly what `tests/unit/` is for.

## Files

| File | Change |
|---|---|
| `crm/fcrm/doctype/crm_access_settings/` | new Single doctype |
| `crm/fcrm/doctype/crm_role_surface/` | new child doctype |
| `crm/api/access.py` | new — `get_visibility`, `set_visibility` |
| `crm/permissions/org_hierarchy.py` | read `manager_outside_hierarchy` in two places |
| `crm/install.py` | hierarchy on for new installs |
| `crm/tests/test_access_settings.py` | new |
| `frontend/src/utils/surfaces.js` | new — the shared registry |
| `frontend/src/stores/access.js` | new — `canSee` |
| `frontend/src/components/Settings/AccessControl.vue` | new pane |
| `frontend/src/components/Settings/Settings.vue` | stable keys, register the pane, `canSee` in conditions, **a condition on Email → Templates** |
| `frontend/src/components/Layouts/AppSidebar.vue` | `canSee` in conditions |
| `frontend/src/router.js` | await the access resource |
| `frontend/src/stores/users.js` | drop the dead `isSalesUser` |
| `frontend/tests/unit/access.test.js` | new |
| `.pi/ARCHIVE.md`, `.pi/SPEC.md` | record the contract and the rationale |

Commits, per AGENTS.md, one per coherent change: the two audit fixes (group
conditions; dead helper) land separately from the feature, ahead of it, because
they are correct on their own and should not need the pane to be reviewed.

## Risks

**The pane implies more than it does.** The mitigation is copy, and it is load
bearing: §2's header states that hiding is not protecting. If that sentence gets
edited away in review, the feature becomes security theatre.

**A manager hides something a rep needs.** Reps cannot unhide it themselves.
Mitigated by keeping every §2 default visible, and by the surface list naming
what each one is; an admin can always reset.

**A fresh site's first manager sees nothing.** With both new-install defaults
applied, a manager invited before anyone builds the tree is out of tree and now
scoped to their own records — a plausible "why can't I see my team?" support
call on day one. Accepted deliberately: it is the safe direction, §1 of the pane
is where an admin looks for exactly this, and `Settings → Sales Hierarchy`
already exists to answer it. The alternative default is the finding this design
is fixing.

**Registry drift.** A surface added to the sidebar but not to
`utils/surfaces.js` simply will not appear in the matrix — it stays visible,
which is the safe direction. Worth a comment at both call sites.

## Out of scope

- **Manager forecast visibility.** `CRM Forecast Snapshot` is already correctly
  scoped by its `has_permission` hook and tested in
  `test_forecast_snapshot_permissions.py`. A toggle over working code is a knob,
  not a feature.
- **Field-level permissions.** `usePermLevel` is Phase 6B in PLAN.md and stays
  there; this pane is surfaces and rows, not fields.
- **New roles.** Three roles, as today. A fourth is a much larger change than a
  settings pane.
- **`CRM Sales Hierarchy` read for Sales User.** Any rep can currently enumerate
  the org chart. It is worth a decision, but it is a doctype permission change
  with its own blast radius, not part of this pane.
