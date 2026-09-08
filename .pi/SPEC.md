# CRM Scripting — Stable Contracts

> **This file**: Stable, user-facing API contracts only. No future plans. No implementation history.  
> **Roadmap**: [PLAN.md](./PLAN.md)  
> **Completed phases**: [ARCHIVE.md](./ARCHIVE.md)  
> **Full scripting guide**: [feats/form-scripting/guide.md](./feats/form-scripting/guide.md)  
> **formDialog full reference**: [feats/form-scripting/form-dialog.md](./feats/form-scripting/form-dialog.md)

---

## Table of Contents

1. [Form Script Class Contract](#form-script-class-contract)
2. [Lifecycle Hooks](#lifecycle-hooks)
3. [Field Change Hooks](#field-change-hooks)
4. [setFieldProperty API](#setfieldproperty-api)
5. [Supported Field Properties](#supported-field-properties)
6. [Override Priority](#override-priority)
7. [formDialog API](#formdialog-api)
8. [Available Helpers](#available-helpers)
9. [Testing](#testing)
10. [Role visibility](#role-visibility)

---

## Form Script Class Contract

Class name = DocType name with spaces removed:

| DocType | Class name |
|---|---|
| `CRM Lead` | `CRMLead` |
| `CRM Deal` | `CRMDeal` |
| `Contact` | `Contact` |
| `CRM Organization` | `CRMOrganization` |

```js
class CRMLead {
  // hooks go here
}
```

`this.doc` — live proxy to the document. Read/write fields directly. No `.value`.  
`this.doc.trigger('methodName')` — the correct way to call methods on your own class.

---

## Lifecycle Hooks

| Hook | Aliases | When it fires |
|---|---|---|
| `onLoad` | `on_load` | Once, when document first loads from server |
| `onRender` | `on_render`, `refresh` | Every time the page renders (first visit + re-visits) |
| `onValidate` | `on_validate`, `validate` | Before every save — throw to block |
| `onSave` | `on_save` | After a successful save |
| `onError` | `on_error` | When a save fails |
| `onBeforeCreate` | `on_before_create` | Before a new document is created via modal |
| `onCreateLead` | `on_create_lead` | CRM Lead only — lead creation flow |
| `convertToDeal` | `convert_to_deal` | CRM Lead only — lead to deal conversion |

All hooks are optional. All hooks can be `async`.

---

## Field Change Hooks

Define a method named **exactly the same as the fieldname**:

```js
class CRMLead {
  status() { /* fires when status field changes */ }
  annual_revenue() { /* fires when annual_revenue changes */ }
}
```

Inside a field hook:
- `this.value` — the new value just set
- `this.oldValue` — the previous value
- `this.currentRowIdx` — the row index if the change was inside a child table

**Row add/remove hooks:**
- `[parentfield]_add` — fires after a row is added. `this.value` = new row object
- `[parentfield]_remove` — fires after row(s) are deleted. `this.selectedRows` = removed names

---

## setFieldProperty API

### `this.setFieldProperty(target, property, value [, rowName])`

```js
// Field
this.setFieldProperty('annual_revenue', 'hidden', true)
this.setFieldProperty('status', 'options', 'New\nOpen\nClosed')

// Section or tab (by name from layout)
this.setFieldProperty('financial_section', 'hidden', true)
this.setFieldProperty('advanced_tab', 'hidden', true)

// Child table column (dot notation)
this.setFieldProperty('products.discount', 'hidden', true)

// Specific row in child table (4th param: row.name)
this.setFieldProperty('products.rate', 'read_only', true, row.name)
```

### `this.setFieldProperties(target, properties [, rowName])`

```js
this.setFieldProperties('annual_revenue', {
  read_only: true,
  label: 'Revenue (USD)',
  description: 'Auto-calculated',
})
```

### `this.removeFieldProperty(target, property [, rowName])`

```js
this.removeFieldProperty('annual_revenue', 'hidden')
this.removeFieldProperty('products.rate', 'read_only', row.name)
```

### `this.getField(fieldname)`

Returns effective field definition (raw meta merged with current script overrides). Not reactive — call again after changes.

```js
const field = this.getField('status')
console.log(field.options, field.read_only, field.hidden)
```

---

## Supported Field Properties

### Field

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide the field |
| `read_only` | `boolean` | Make non-editable |
| `reqd` | `boolean` | Make mandatory (asterisk + validation) |
| `label` | `string` | Field label |
| `placeholder` | `string` | Input placeholder |
| `description` | `string` | Help text below the field |
| `options` | `string` | Select choices (newline-separated) or Link doctype |
| `link_filters` | `object` | Filter object for Link autocomplete |
| `precision` | `string` | Decimal precision for Float/Currency/Percent |
| `button_color` | `string` | `"Default"`, `"Primary"`, `"Info"`, `"Success"`, `"Warning"`, `"Danger"` |

**Select `options` format** — always a newline-separated string:
```js
this.setFieldProperty('status', 'options', 'New\nIn Progress\nClosed')
```

**`link_filters` format** — plain object:
```js
this.setFieldProperty('lead_owner', 'link_filters', { enabled: 1 })
```

### Section

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide entire section |
| `label` | `string` | Section heading |
| `collapsible` | `boolean` | Make collapsible |
| `opened` | `boolean` | Default expanded state |
| `hideLabel` | `boolean` | Hide the section label |
| `hideBorder` | `boolean` | Remove top border |

### Tab

| Property | Type | Effect |
|---|---|---|
| `hidden` | `boolean` | Show/hide the entire tab |
| `label` | `string` | Tab heading |

---

## Override Priority

```
Final value =
  1. Script per-row override  (products.qty:row_name)    ← highest
  2. Script column override   (products.qty)
  3. Script field override    (fieldname)
  4. depends_on expression    (read_only_depends_on, etc.)
  5. Server meta default                                  ← lowest
```

**Hidden fields are always skipped in mandatory validation.** A field hidden via script override is never checked for `reqd`, even if `reqd: 1` in the DocType.

---

## formDialog API

Opens a dialog with a full FieldLayout. Returns a `Promise<object|null>`.

```js
formDialog(options)
```

### Three patterns (all composable)

```js
// 1. Promise — sequential, await the result
const data = await formDialog({ title: 'Step 1', fields: [...] })
if (!data) return  // cancelled

// 2. onSubmit callback — fire-and-forget, code after runs immediately
formDialog({
  title: 'Mark as Lost',
  fields: [...],
  submitLabel: 'Mark as Lost',
  cancelLabel: 'Cancel',
  onSubmit(data) { ... },
  onCancel() { ... },
})

// 3. Custom actions — full control
formDialog({
  title: 'Review',
  fields: [...],
  actions: [
    { label: 'Approve', variant: 'solid', onClick({ data, close, validate }) { close(data) } },
    { label: 'Cancel', onClick({ close }) { close(null) } },
  ],
})
```

### Options

| Option | Type | Description |
|---|---|---|
| `title` | `string` | Dialog title |
| `fields` | `Array` | Flat field definitions — auto-wrapped in single section |
| `tabs` | `Array` | Full layout: `tabs > sections > columns > fields` |
| `doctype` | `string` | Fetch Quick Entry layout for this doctype |
| `fieldnames` | `Array<string>` | With `doctype` — pick only these fields from doctype meta |
| `defaults` | `object` | Pre-fill field values |
| `required` | `Array<string>` | Force mandatory: shows asterisk + validates |
| `size` | `string` | Dialog size: `'sm'`, `'md'`, `'lg'`, `'xl'`, `'2xl'`. Default: `'xl'` |
| `actions` | `Array` | Custom buttons — overrides default Submit and `onSubmit` |
| `onSubmit` | `Function` | Called with `data` on submit. Throw to stay open |
| `onCancel` | `Function` | Called on cancel/close/overlay/escape |
| `submitLabel` | `string` | Default Submit button label. Default: `'Submit'` |
| `cancelLabel` | `string` | If provided, shows a Cancel button with this label |

### Behavior matrix

| `actions` | `onSubmit` | Behavior |
|---|---|---|
| ✗ | ✗ | Submit button → validates → closes → Promise resolves with data |
| ✗ | ✓ | Submit button → validates → `onSubmit(data)` → closes → Promise resolves |
| ✓ | (ignored) | Custom buttons only. Each calls `close(result)` |

> Full reference with layout modes, column layouts, and examples: [feats/form-scripting/form-dialog.md](./feats/form-scripting/form-dialog.md)

---

## Available Helpers

All helpers are available as bare names everywhere in your script — no imports needed.

| Helper | Description |
|---|---|
| `call(method, params)` | Frappe backend RPC — returns a `Promise` |
| `toast.success(msg)` | Green toast notification |
| `toast.error(msg)` | Red toast notification |
| `toast.info(msg)` | Info toast notification |
| `createDialog(options)` | Simple frappe-ui confirm/message dialog (fire-and-forget) |
| `formDialog(options)` | Form dialog with FieldLayout — returns a Promise. See [form-dialog.md](./feats/form-scripting/form-dialog.md) |
| `router` | Vue Router — `router.replace()`, `router.push()`, `router.currentRoute` |
| `router.previousRoute` | Route navigated from — compare `.path` (not `.fullPath`) |
| `socket` | Socket.io instance for realtime events |
| `throwError(message)` | `toast.error` + `throw` in one call — stops execution |
| `crm.makePhoneCall(number)` | Initiate a phone call via CRM call integration |
| `crm.openSettings(page)` | Open the CRM settings panel to a specific page |

---

## Testing

**Runner**: Vitest · **Environment**: happy-dom  
**Location**: `frontend/tests/`

```bash
cd frontend
yarn test          # watch mode
yarn test:run      # single run (CI)
```

**Current state**: 21 test files · 420 tests · well under a second

### Test files

| File | What it tests |
|---|---|
| `processField.test.js` | Field clone, Select/Link transforms, perm + script overrides |
| `fieldPropertyOverrides.test.js` | setFieldProperty / remove / batch / dot notation / per-row |
| `checkMandatory.test.js` | findMissingMandatory with script override scenarios |
| `scriptHelpers.test.js` | getClassNames, createDocProxy |
| `parseLinkFilters.test.js` | Safe JSON/object parsing for link_filters |
| `renderFieldLayoutDialog.test.js` | Promise behavior, options passthrough, onSubmit/onCancel, concurrent dialogs |

### Rules for adding tests

- Functions under test must be **pure** and **importable without side effects**
- If a function needs extraction from a Vue component, extract to `src/utils/` first
- Use `@/` alias (resolves to `src/`), standard `describe`/`it`/`expect` (vitest globals)

```js
import { processField } from '@/utils/fieldTransforms'

describe('processField', () => {
  it('clones the field', () => {
    const raw = { fieldname: 'x', fieldtype: 'Data' }
    expect(processField(raw)).not.toBe(raw)
  })
})
```

> See `tests/setup.js` for available globals (`__`, `window.sysdefaults`)

---

## Role visibility

> `Settings → Access Control`. Backend: `crm/api/access.py`. Frontend registry: `frontend/src/utils/surfaces.js`. Frontend store: `frontend/src/stores/access.js` (`canSee`). This is a separate, later contract from the scripting API above — it lives in this file because SPEC.md is where stable, user-facing contracts go. Rationale and history: [ARCHIVE.md — Role-Based Access Control](./ARCHIVE.md#role-based-access-control).

### `get_visibility()`

```
GET crm.api.access.get_visibility
→ {
    role: "System Manager" | "Sales Manager" | "Sales User",
    hidden: string[],                                     // the caller's own row
    matrix: { "Sales Manager": string[], "Sales User": string[] } | null,
  }
```

Example, for a rep with two surfaces hidden:

```json
{ "role": "Sales User", "hidden": ["nav.notes", "settings.email_templates"], "matrix": null }
```

`matrix` is populated for a System Manager or a Sales Manager, `null` for a Sales User — a
rep never receives another role's configuration. Any CRM role may call this
(`_require_crm_user()` — deliberately wider than `sales_user_only`, see ARCHIVE.md); a caller
holding no CRM role gets `frappe.PermissionError`.

### `set_visibility(role, hidden)`

```
POST crm.api.access.set_visibility
  role: "Sales Manager" | "Sales User"
  hidden: string[]              // a JSON-encoded string is also accepted
→ { role: string, hidden: string[] }
```

Whole-row replace, not add/remove: the caller posts the complete row it is showing, so two
managers editing at once cannot silently lose each other's change.

| Caller | `role: "Sales User"` | `role: "Sales Manager"` | `role: "System Manager"` |
|---|---|---|---|
| System Manager | allowed | allowed | refused — `ValidationError` (not configurable, ever) |
| Sales Manager | allowed | refused — `PermissionError` | refused — `ValidationError` |
| Sales User | refused — `PermissionError` | refused — `PermissionError` | refused — `PermissionError` |

Every entry in `hidden` must match the surface key shape below; the request is capped at
`MAX_SURFACES` (200) entries. A malformed key, an over-long key, or too many keys raises
`frappe.ValidationError` and saves nothing.

**Must be called with `method: 'POST'`.** Both write endpoints are
`@frappe.whitelist(methods=["POST"])`; a `createResource` (or any other caller) that leaves
the default GET gets a 403.

### The narrowing invariant

> Configuration can only ever hide a surface. It can never reveal one.

Every consumer composes `canSee(key)` with the role gate the surface already had:

```js
canSee('nav.analyst') && isAdmin()   // correct — the only shape
canSee('nav.analyst') || isAdmin()   // never
canSee('nav.analyst')                // never, on its own
```

Unhiding `nav.analyst` for reps changes nothing: `isAdmin()` still fails in the nav, the
route guard still redirects, and `crm.agent.api.ask_analyst` is still
`frappe.only_for("System Manager", True)`. `crm/tests/test_access_settings.py::test_unhiding_a_surface_does_not_make_its_endpoint_callable`
asserts this against a live endpoint, not just the gate function — treat it as the one test
here that must never be weakened.

Consequence: an unrecognised or misspelled surface key is inert. It can only fail to hide
something, never grant it.

### The two-column rule

The matrix has exactly two columns — `Sales Manager` and `Sales User` (`CONFIGURABLE_ROLES`).
There is no System Manager column: nothing is hideable from an administrator, so an
administrator can never configure themselves out of the pane that would undo it. Enforced
twice, independently: `set_visibility`'s own role check, and `CRMAccessSettings.validate()` →
`reject_unconfigurable_roles()` on the doctype itself, because the desk form is a second door
onto the same data.

Python source of truth: `CONFIGURABLE_ROLES` in
`crm/fcrm/doctype/crm_access_settings/crm_access_settings.py` — the doctype owns its own
Select `options` string. JS copy: `CONFIGURABLE_ROLES` in `frontend/src/utils/surfaces.js`,
commented as mirroring the Python constant. No cross-language import exists; keep both in
step by hand.

### Surface key shape

```
^(nav|settings)\.[a-z0-9_]{1,48}\Z
```

Enforced server-side (`crm/api/access.py::SURFACE_KEY`). Shape-validated rather than checked
against a Python allow-list, so the registry that produces valid keys lives once, client-side
— there is no server-side copy of the surface list to keep in sync.

Each registry entry in `frontend/src/utils/surfaces.js`'s `SURFACES` array:

| Field | Type | Meaning |
|---|---|---|
| `key` | `string` | `nav.*` or `settings.*`, matching the shape above |
| `group` | `'nav' \| 'settings'` | which list this came from — `AppSidebar.vue` (13 entries) or `Settings.vue` (27 entries) |
| `label` | `string` | display label |
| `section` | `string?` | settings only — the settings group the surface lives under. The pane renders `section · label`, because several labels are meaningless alone ("Accounts", "Templates") and "Dashboard" / "Calendar" / "Assistant" each name both a nav link and a settings pane |
| `floor` | `string?` | the role gate the surface's own code already enforces (e.g. `nav.analyst` → `ADMIN_ROLE`). The matrix renders that cell as a fixed dash, not a toggle — see `isAtFloor(surface, role)` |

### Adding a surface

Two steps, in order:

1. **Register it** — add an entry to `SURFACES` in `frontend/src/utils/surfaces.js`: a key
   matching the shape above, `group`, `label`, and `section` / `floor` if applicable.
2. **Wire `canSee` at the surface's existing gate.** The mechanism differs by group:
   - **`nav.*`** (`AppSidebar.vue`): compose it directly into the link's own `condition`:
     `condition: () => canSee('nav.foo') && <existing gate>`.
   - **`settings.*`** (`Settings.vue`): give the item a `key: 'settings.foo'` matching the
     registry and leave its own `condition` untouched. The shared `tabs` computed already
     applies `canSee(item.key)` before `item.condition()` for every keyed item — adding the
     key is the whole change.

A surface left off the registry simply stays visible to everyone the existing gate already
allowed. That is the safe direction, not a hole.

### Data access switches

The other half of `crm/api/access.py` — the two switches that change what the database
returns, not what the shell shows. Administrator-only to write; `get_data_access` is also
readable by a Sales Manager, so the pane can show a manager their own scope as read-only
context.

```
GET  crm.api.access.get_data_access
POST crm.api.access.set_data_access
  enable_sales_hierarchy?: 0 | 1
  manager_outside_hierarchy?: "All records" | "Own records only"
→ {
    enable_sales_hierarchy: 0 | 1,
    manager_outside_hierarchy: "All records" | "Own records only",
    hierarchy_size: number,        // frappe.db.count("CRM Sales Hierarchy")
  }
```

`manager_outside_hierarchy` accepts only the two `MANAGER_SCOPES` values (`crm_access_settings.py`
— also the doctype's own Select `options`, so this tuple is the only enforcement on this path,
which bypasses both `validate()` and frappe's own Select validation); anything else raises
`frappe.ValidationError`. `set_data_access` is `frappe.only_for("System Manager", True)` — a
Sales Manager gets `frappe.PermissionError`.

`crm.api.access.manager_outside_hierarchy_sees_all() -> bool` is the single place the
out-of-tree decision is made. Consumed by `crm/permissions/org_hierarchy.py` (leads, deals)
and by `crm_rep_plan.visible_users()` (plans; and, through it, quota's `visible_reps()`,
`CRM Suggestion`, and `CRM Forecast Snapshot`) — one function rather than a copy per doctype.

See [ARCHIVE.md — Role-Based Access Control](./ARCHIVE.md#role-based-access-control) for why
these two switches exist and why a new install's defaults differ from an existing site's.
