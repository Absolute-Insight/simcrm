# Role-Based Access Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `Settings → Access Control` pane that makes the site's real data boundary an explicit admin choice and lets admins and managers hide nav links and settings panes per role — without that hiding ever being able to grant access.

**Architecture:** A new admin-only Single doctype (`CRM Access Settings`) holds the out-of-tree manager rule plus a sparse table of hidden `(role, surface)` pairs. One endpoint module (`crm/api/access.py`) reads it for the session user and writes it under a rule that stops a manager editing their own row. The frontend gets a pure registry of surfaces in `src/utils/`, a store exposing `canSee(key)`, and every existing gate becomes `canSee(key) && <existing role gate>` — so configuration can only ever narrow.

**Tech Stack:** Frappe (Python 3.11+, MariaDB), Vue 3 + frappe-ui, vitest, `bench run-tests` (`frappe.tests.IntegrationTestCase`).

**Spec:** `docs/superpowers/specs/2026-09-08-role-access-control-design.md` — read it before Task 1. The plan argues from it; where the two disagree, the spec is right and the plan is a bug.

## Global Constraints

- **The narrowing invariant.** Every gate is `canSee(key) && <existing role gate>`. Never `||`, never `canSee(key)` alone. Task 3 has an executable test for this; do not weaken it.
- **The matrix has exactly two columns:** `Sales Manager` and `Sales User`. There is no System Manager column — nothing is hideable from an admin, so an admin cannot lock themselves out of the pane.
- **A `CRM Role Surface` row's existence means hidden.** There is no `visible` field.
- **Existing sites must not change behaviour.** `manager_outside_hierarchy` falls back to `All records` in the reader, because `frappe.db.get_single_value` returns `None` for a Single that has never been saved. No migration patch anywhere in this plan.
- **Do NOT put a group condition on the `Integrations` settings group.** It would hide Telephony from reps, which is where a rep configures their own agent number. Only `Email → Templates` gets a condition, and only on the item.
- **Commit style:** `feat:` / `fix:` / `test:` / `docs:`, one commit per coherent change. Pre-commit runs prettier + eslint + oxlint; if it rewrites a file, `git add` it again and re-commit.
- **Coloured text uses the `-9` step** of `--ink-{green,red,orange}-*` (AGENTS.md). Use orange, not amber, for warnings. Check both themes in a browser.
- **Never hand-edit** `frontend/src/styles/vectora-theme.css`, `crm/www/crm.html`, `crm/public/frontend/**`, lockfiles, or `crm/__init__.py` — a PreToolUse hook refuses these.

## Prerequisites — read this before running any test command

**Both suites need the devcontainer**; the host has no `bench` and no `yarn`.

**It is already up and verified** (2026-09-08): container `simcrm_devcontainer-frappe-1`,
compose project `simcrm_devcontainer`, volumes `simcrm_devcontainer_{bench-data,mariadb-data}`.
Sites `dev.localhost` and `test_site` both exist; `test_site` has `allow_tests`
and all four mail keys set. Run commands through it:

```bash
docker exec simcrm_devcontainer-frappe-1 bash -lc '<command>'
```

Do **not** `docker compose up` from `.devcontainer/` without `-p simcrm_devcontainer`:
the project name defaults to `devcontainer`, which builds a second stack on
empty volumes and then fails to bind :8000 against the real one.

**The scheduler is disabled, deliberately.** `bench doctor` reports it, and the
`/dev-up` skill says to enable it — do not. This devcontainer runs 0 workers, so
enabling it only fills a queue nothing consumes, which is the `QueueOverloaded`
failure that reads like a test regression. Nothing in this feature uses a
scheduled job. Before any full `run-tests --app crm`, still purge:
`bench --site test_site purge-jobs`.

**The worktree needs a `node_modules`.** `yarn install` ran in the main checkout
only, so `frontend/node_modules` is absent under `.worktrees/`. This branch adds
no dependencies and the two `yarn.lock` files are byte-identical, so a symlink is
correct and instant — already created, but re-create it if it goes missing:

```bash
ln -sfn /workspace/frontend/node_modules \
        /workspace/.worktrees/feat-role-access/frontend/node_modules
```

It is gitignored, so it does not dirty `git status`.

**Baseline before any change:** 41 files, 548 tests passing, ~0.9s, run as
`cd /workspace/.worktrees/feat-role-access/frontend && yarn test:run`. AGENTS.md
says "29 files · 480 tests"; that line has drifted, which is why it tells you to
re-read the counts rather than trust it.

**The bench does not see this branch by default, and the symlink is NOT the reason.**

The venv carries `env/lib/python3.14/site-packages/crm.pth` whose entire content
is the line `/workspace`, so `import crm` resolves to the **main checkout** no
matter where `apps/crm` points. Re-pointing that symlink changes nothing for
Python — it only appears to work, and an earlier version of this plan told you
to do exactly that.

The fix is `PYTHONPATH`, which precedes site-packages `.pth` entries on
`sys.path`, is inherited by bench's child processes, and mutates **no shared
state** — nothing to restore, and the peer sessions sharing this bench are
unaffected. Use the wrapper, which sets it and then refuses to run unless
`import crm` actually resolved to the worktree:

```bash
.superpowers/sdd/2026-09-08-role-access-control/bench-on-branch.sh 'bench --site test_site migrate'
.superpowers/sdd/2026-09-08-role-access-control/bench-on-branch.sh 'bench --site test_site run-tests --module crm.tests.test_access_settings'
```

Do not flip `apps/crm`, and do not edit `crm.pth` — both are shared state, and
neither is necessary.

**Proven with a discriminator**, which is the only evidence that counts here:
`crm/fcrm/doctype/crm_access_settings/` exists only on this branch. With
`PYTHONPATH` set it imports; without it, `ModuleNotFoundError`. A check that
resolves `crm` after manually inserting a path onto `sys.path` proves nothing —
it tests the insertion, not the bench.

**Python tests run against a dedicated site**, never a browsing site (AGENTS.md): `bench --site test_site run-tests --app crm`. Purge the job queue first — the devcontainer has no workers and a full queue raises `QueueOverloaded` errors that read like regressions:

```bash
bench --site test_site purge-jobs
```

---

### Task 1: Close the two audit gaps

Independent of the feature and correct on its own, so it lands first and can be reviewed without the pane.

**Files:**
- Modify: `frontend/src/components/Settings/Settings.vue` (the `Email` group's `Templates` item, ~line 246-252)
- Modify: `frontend/src/stores/users.js:148-152` and its export at `:177`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing. Later tasks do not depend on this task.

- [ ] **Step 1: Confirm both gaps are still present**

```bash
cd /home/evo/dev/simcrm/.worktrees/feat-role-access
# Expect: the Templates item with no `condition:` line after it
sed -n '244,256p' frontend/src/components/Settings/Settings.vue
# Expect: the definition, and exactly one other hit (the export) — i.e. no callers
grep -rn "isSalesUser" frontend/src
```

Expected: `Templates` has no `condition`; `isSalesUser` appears only at its definition (`stores/users.js:148`) and in the return block (`:177`).

- [ ] **Step 2: Gate Email → Templates**

In `frontend/src/components/Settings/Settings.vue`, the `Templates` item becomes:

```js
        {
          label: __('Templates'),
          icon: EmailTemplateIcon,
          component: markRaw(EmailTemplatePage),
          // The Email group carries no group condition (Telephony's group
          // cannot have one — a rep configures their own agent number there),
          // so an ungated item here falls through to reps. Templates is an
          // authoring surface; a rep *uses* templates from the composer, not
          // from Settings.
          condition: () => isManager(),
        },
```

- [ ] **Step 3: Delete the dead `isSalesUser`**

In `frontend/src/stores/users.js`, delete the function:

```js
  function isSalesUser(email) {
    return getUser(email).role === 'Sales User'
  }
```

and remove `isSalesUser,` from the returned object. It has no callers, and its exact-role match contradicts `isManager()`'s inclusive semantics — the next person to reach for it gets the wrong answer.

- [ ] **Step 4: Verify nothing referenced it and the suite is unchanged**

```bash
grep -rn "isSalesUser" frontend/src && echo "STILL REFERENCED — fix before committing" || echo "clean"
cd frontend && yarn test:run
```

Expected: `clean`, then every test passing. Re-read the file/test counts from this output rather than trusting AGENTS.md's line, which drifts.

- [ ] **Step 5: Browser check both roles**

With the dev site up, sign in as a Sales User and open Settings. Expected: `Email` group is now absent entirely (its only rep-visible item is gone), `Integrations → Telephony` is **still present**. Sign in as a Sales Manager: `Email → Templates` present.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/Settings/Settings.vue frontend/src/stores/users.js
git commit -m "fix: gate Email templates behind manager, drop the dead isSalesUser

The Email settings group carries no group condition, so its only
individually-ungated item fell through to reps. Templates is an authoring
surface -- a rep uses templates from the composer, not from Settings.

Integrations deliberately keeps no group condition: Telephony is where a
rep sets their own agent number, and its manager-only controls are gated
one by one.

isSalesUser had no callers and matched the role exactly where its sibling
isManager() is inclusive -- two meanings for one idea, waiting to be
reached for wrongly."
```

---

### Task 2: The `CRM Access Settings` and `CRM Role Surface` doctypes

**Files:**
- Create: `crm/fcrm/doctype/crm_role_surface/__init__.py` (empty)
- Create: `crm/fcrm/doctype/crm_role_surface/crm_role_surface.json`
- Create: `crm/fcrm/doctype/crm_role_surface/crm_role_surface.py`
- Create: `crm/fcrm/doctype/crm_access_settings/__init__.py` (empty)
- Create: `crm/fcrm/doctype/crm_access_settings/crm_access_settings.json`
- Create: `crm/fcrm/doctype/crm_access_settings/crm_access_settings.py`
- Test: `crm/tests/test_access_settings.py`

**Interfaces:**
- Consumes: nothing.
- Produces: doctype `CRM Access Settings` (Single) with fields `manager_outside_hierarchy: str` (`"All records"` | `"Own records only"`) and `hidden_surfaces: Table[CRM Role Surface]`; child doctype `CRM Role Surface` with `role: str` and `surface: str`. Tasks 3, 4 and 5 all read these exact names.

- [ ] **Step 1: Write the failing test**

Create `crm/tests/test_access_settings.py`:

```python
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The access-control doctype, its endpoints, and the invariant behind them.

The invariant is that configuration can only ever *hide* a surface, never
reveal one -- so the test that matters most here is
``test_unhiding_a_surface_does_not_make_its_endpoint_callable``. Everything
else guards the write rule that keeps a Sales Manager out of their own row.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

ADMIN = "access-admin@crmtest.test"
MANAGER = "access-manager@crmtest.test"
REP = "access-rep@crmtest.test"


def ensure_user(email: str, name: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		if roles:
			user.add_roles(*roles)


class AccessSettingsDocTypeTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(ADMIN, "Access Admin", "System Manager")
		ensure_user(MANAGER, "Access Manager", "Sales Manager")
		ensure_user(REP, "Access Rep", "Sales User")
		self.addCleanup(lambda: frappe.set_user("Administrator"))

	def test_the_doctype_is_a_single(self):
		self.assertTrue(frappe.get_meta("CRM Access Settings").issingle)

	def test_only_system_manager_holds_permissions_on_it(self):
		"""A Sales Manager must not reach this doctype through the generic
		document API. FCRM Settings grants them rwcd, which is why the matrix
		does not live there."""
		roles = {p.role for p in frappe.get_meta("CRM Access Settings").permissions}
		self.assertEqual(roles, {"System Manager"})

	def test_a_manager_cannot_read_it_directly(self):
		frappe.set_user(MANAGER)
		self.assertFalse(frappe.has_permission("CRM Access Settings", "read"))

	def test_a_rep_cannot_read_it_directly(self):
		frappe.set_user(REP)
		self.assertFalse(frappe.has_permission("CRM Access Settings", "read"))

	def test_manager_outside_hierarchy_defaults_to_all_records(self):
		"""Existing sites keep today's behaviour. The field default carries it for
		a site that saves the Single; ``crm.permissions.org_hierarchy`` carries it
		for one that never has."""
		field = frappe.get_meta("CRM Access Settings").get_field("manager_outside_hierarchy")
		self.assertEqual(field.default, "All records")
		self.assertEqual(field.options.split("\n"), ["All records", "Own records only"])

	def test_the_child_row_has_no_visible_flag(self):
		"""A row's existence means hidden. A second way to say the same thing is
		a second thing to keep in step."""
		fieldnames = {f.fieldname for f in frappe.get_meta("CRM Role Surface").fields}
		self.assertEqual(fieldnames, {"role", "surface"})
```

- [ ] **Step 2: Run it to make sure it fails**

```bash
cd /home/frappe/frappe-bench
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: FAIL — `DoesNotExistError: DocType CRM Access Settings not found`.

**Not** `No module named 'crm.tests.test_access_settings'`. That error means the
bench cannot see this branch at all (see Prerequisites) and is indistinguishable
from the test file not existing — if you get it, your harness is broken, not
your code, and the RED you are looking at is meaningless.

- [ ] **Step 3: Create the child doctype**

`crm/fcrm/doctype/crm_role_surface/__init__.py` — empty file.

`crm/fcrm/doctype/crm_role_surface/crm_role_surface.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "creation": "2026-09-08 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "role",
  "surface"
 ],
 "fields": [
  {
   "fieldname": "role",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Role",
   "options": "Sales Manager\nSales User",
   "reqd": 1
  },
  {
   "description": "A surface key such as nav.analyst or settings.email_templates. The row's existence means hidden for this role.",
   "fieldname": "surface",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Surface",
   "reqd": 1
  }
 ],
 "index_web_pages_for_search": 1,
 "istable": 1,
 "links": [],
 "modified": "2026-09-08 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "FCRM",
 "name": "CRM Role Surface",
 "owner": "Administrator",
 "permissions": [],
 "row_format": "Dynamic",
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": []
}
```

`crm/fcrm/doctype/crm_role_surface/crm_role_surface.py`:

```python
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class CRMRoleSurface(Document):
	pass
```

- [ ] **Step 4: Create the parent Single doctype**

`crm/fcrm/doctype/crm_access_settings/__init__.py` — empty file.

`crm/fcrm/doctype/crm_access_settings/crm_access_settings.json`:

```json
{
 "actions": [],
 "allow_rename": 0,
 "creation": "2026-09-08 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "data_access_section",
  "manager_outside_hierarchy",
  "surface_section",
  "hidden_surfaces"
 ],
 "fields": [
  {
   "fieldname": "data_access_section",
   "fieldtype": "Section Break",
   "label": "Data Access"
  },
  {
   "default": "All records",
   "description": "What a Sales Manager who is not in the sales hierarchy may read. \"All records\" is the historical behaviour and stays the default so existing sites are unchanged; a new install is set to \"Own records only\".",
   "fieldname": "manager_outside_hierarchy",
   "fieldtype": "Select",
   "label": "Managers outside the hierarchy",
   "options": "All records\nOwn records only"
  },
  {
   "description": "Which nav links and settings panes each role is shown. Hiding a surface tidies the app; it does not protect data. Nothing can be hidden from an administrator.",
   "fieldname": "surface_section",
   "fieldtype": "Section Break",
   "label": "Hidden Surfaces"
  },
  {
   "fieldname": "hidden_surfaces",
   "fieldtype": "Table",
   "label": "Hidden Surfaces",
   "options": "CRM Role Surface"
  }
 ],
 "index_web_pages_for_search": 1,
 "issingle": 1,
 "links": [],
 "modified": "2026-09-08 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "FCRM",
 "name": "CRM Access Settings",
 "owner": "Administrator",
 "permissions": [
  {
   "create": 1,
   "email": 1,
   "print": 1,
   "read": 1,
   "role": "System Manager",
   "share": 1,
   "write": 1
  }
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}
```

`track_changes: 1` is deliberate: a change to who can see what should leave a Version diff.

`crm/fcrm/doctype/crm_access_settings/crm_access_settings.py`:

```python
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

CONFIGURABLE_ROLES = ("Sales Manager", "Sales User")


class CRMAccessSettings(Document):
	def validate(self):
		self.reject_unconfigurable_roles()
		self.drop_duplicate_rows()

	def reject_unconfigurable_roles(self):
		"""There is no System Manager column, by design.

		Nothing is hideable from an administrator, which is what stops an admin
		configuring themselves out of the one pane that would undo it. Enforced
		on the doctype and not only in the endpoint, because the desk form is a
		second door.
		"""
		for row in self.hidden_surfaces:
			if row.role not in CONFIGURABLE_ROLES:
				frappe.throw(
					_("{0} is not a configurable role. Nothing can be hidden from an administrator.").format(
						row.role
					)
				)

	def drop_duplicate_rows(self):
		"""One row per (role, surface). Duplicates are harmless to read but they
		make the desk table lie about how many surfaces are hidden."""
		seen = set()
		kept = []
		for row in self.hidden_surfaces:
			key = (row.role, row.surface)
			if key in seen:
				continue
			seen.add(key)
			kept.append(row)
		self.hidden_surfaces = kept
```

- [ ] **Step 5: Migrate and run the test**

```bash
cd /home/frappe/frappe-bench
bench --site test_site migrate
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: PASS, 6 tests. `bench run-tests` prints several `Ran N tests` blocks — grep every `Ran` line rather than reading the last one, and compare totals.

- [ ] **Step 6: Commit**

```bash
git add crm/fcrm/doctype/crm_role_surface crm/fcrm/doctype/crm_access_settings crm/tests/test_access_settings.py
git commit -m "feat: add the CRM Access Settings doctype

An admin-only Single holding the out-of-tree manager rule and a sparse
table of hidden (role, surface) pairs. Admin-only and not fields on FCRM
Settings, because FCRM Settings grants rwcd to Sales Manager -- a manager
could rewrite their own row through the generic document API, which is the
escalation this pane would otherwise open.

A row's existence means hidden; there is no visible flag. The role column
accepts only Sales Manager and Sales User, so nothing is hideable from an
administrator and an admin cannot configure themselves out of the pane
that would undo it."
```

---

### Task 3: `crm/api/access.py` — read and write, and the narrowing invariant

**Files:**
- Create: `crm/api/access.py`
- Modify: `crm/tests/test_access_settings.py` (append a second test class)

**Interfaces:**
- Consumes: `CRM Access Settings` / `CRM Role Surface` from Task 2.
- Produces:
  - `crm.api.access.get_visibility() -> dict` returning `{"role": str, "hidden": list[str], "matrix": dict[str, list[str]] | None}`
  - `crm.api.access.set_visibility(role: str, hidden: list[str] | str) -> dict` returning `{"role": str, "hidden": list[str]}`
  - `crm.api.access.get_data_access() -> dict` returning `{"enable_sales_hierarchy": int, "manager_outside_hierarchy": str, "hierarchy_size": int}`
  - `crm.api.access.set_data_access(enable_sales_hierarchy=None, manager_outside_hierarchy=None) -> dict` (same shape as `get_data_access`)
  - `crm.api.access.manager_outside_hierarchy_sees_all() -> bool` — Task 4 imports this.
  - Task 6's registry must use the same key shape: `^(nav|settings)\.[a-z0-9_]+$`.

- [ ] **Step 1: Write the failing tests**

Append to `crm/tests/test_access_settings.py`:

```python
class AccessApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(ADMIN, "Access Admin", "System Manager")
		ensure_user(MANAGER, "Access Manager", "Sales Manager")
		ensure_user(REP, "Access Rep", "Sales User")
		settings = frappe.get_single("CRM Access Settings")
		settings.hidden_surfaces = []
		settings.save(ignore_permissions=True)
		self.addCleanup(self._reset)

	def _reset(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single("CRM Access Settings")
		settings.hidden_surfaces = []
		settings.save(ignore_permissions=True)

	# --- the write rule -------------------------------------------------

	def test_a_manager_may_hide_a_surface_from_reps(self):
		from crm.api.access import set_visibility

		frappe.set_user(MANAGER)
		result = set_visibility("Sales User", ["nav.notes"])
		self.assertEqual(result["hidden"], ["nav.notes"])

	def test_a_manager_may_not_edit_the_manager_row(self):
		"""The rule that stops this pane being a way for a manager to widen
		their own surface set."""
		from crm.api.access import set_visibility

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			set_visibility("Sales Manager", ["nav.reports"])

	def test_an_admin_may_edit_the_manager_row(self):
		from crm.api.access import set_visibility

		frappe.set_user(ADMIN)
		result = set_visibility("Sales Manager", ["nav.reports"])
		self.assertEqual(result["hidden"], ["nav.reports"])

	def test_a_rep_may_not_write_at_all(self):
		from crm.api.access import set_visibility

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			set_visibility("Sales User", ["nav.notes"])

	def test_the_admin_role_is_not_configurable(self):
		from crm.api.access import set_visibility

		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			set_visibility("System Manager", ["nav.notes"])

	# --- key validation -------------------------------------------------

	def test_malformed_keys_are_refused(self):
		from crm.api.access import set_visibility

		frappe.set_user(ADMIN)
		for bad in ("Nav.Analyst", "analyst", "nav.", "nav.a b", "reports.x", "nav." + "x" * 200):
			with self.subTest(key=bad), self.assertRaises(frappe.ValidationError):
				set_visibility("Sales User", [bad])

	def test_too_many_keys_are_refused(self):
		from crm.api.access import MAX_SURFACES, set_visibility

		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			set_visibility("Sales User", [f"nav.k{i}" for i in range(MAX_SURFACES + 1)])

	def test_a_json_string_body_is_accepted(self):
		"""The HTTP layer hands lists over as JSON strings."""
		from crm.api.access import set_visibility

		frappe.set_user(ADMIN)
		result = set_visibility("Sales User", '["nav.notes"]')
		self.assertEqual(result["hidden"], ["nav.notes"])

	# --- the read path --------------------------------------------------

	def test_a_rep_reads_only_their_own_row_and_no_matrix(self):
		from crm.api.access import get_visibility, set_visibility

		frappe.set_user(ADMIN)
		set_visibility("Sales User", ["nav.notes"])
		set_visibility("Sales Manager", ["nav.reports"])

		frappe.set_user(REP)
		payload = get_visibility()
		self.assertEqual(payload["role"], "Sales User")
		self.assertEqual(payload["hidden"], ["nav.notes"])
		self.assertIsNone(payload["matrix"])

	def test_a_manager_reads_the_whole_matrix(self):
		from crm.api.access import get_visibility, set_visibility

		frappe.set_user(ADMIN)
		set_visibility("Sales User", ["nav.notes"])

		frappe.set_user(MANAGER)
		payload = get_visibility()
		self.assertEqual(payload["role"], "Sales Manager")
		self.assertEqual(payload["matrix"]["Sales User"], ["nav.notes"])
		self.assertEqual(payload["matrix"]["Sales Manager"], [])

	def test_an_admin_is_never_hidden_anything(self):
		from crm.api.access import get_visibility, set_visibility

		frappe.set_user(ADMIN)
		set_visibility("Sales Manager", ["nav.reports"])
		self.assertEqual(get_visibility()["hidden"], [])

	# --- the invariant --------------------------------------------------

	def test_unhiding_a_surface_does_not_make_its_endpoint_callable(self):
		"""THE test in this file.

		Configuration narrows and never widens. A rep with nav.analyst visible
		-- which is its default state, since the matrix stores only what is
		hidden -- still cannot reach the Analyst, because every gate is
		``canSee(key) and <existing role gate>`` and the endpoint is
		``frappe.only_for("System Manager")``. If this test ever fails, the
		visibility matrix has become a permission system and the pane is
		unsafe to expose to managers.
		"""
		from crm.agent.api import ask_analyst
		from crm.api.access import get_visibility

		frappe.set_user(REP)
		self.assertNotIn("nav.analyst", get_visibility()["hidden"])
		with self.assertRaises(frappe.PermissionError):
			ask_analyst("what is my pipeline worth")

	# --- data access ----------------------------------------------------

	def test_a_manager_cannot_change_data_access(self):
		from crm.api.access import set_data_access

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			set_data_access(enable_sales_hierarchy=1)

	def test_an_admin_can_change_data_access(self):
		from crm.api.access import get_data_access, set_data_access

		frappe.set_user(ADMIN)
		before = get_data_access()
		self.addCleanup(
			set_data_access,
			before["enable_sales_hierarchy"],
			before["manager_outside_hierarchy"],
		)
		result = set_data_access(
			enable_sales_hierarchy=1, manager_outside_hierarchy="Own records only"
		)
		self.assertEqual(result["enable_sales_hierarchy"], 1)
		self.assertEqual(result["manager_outside_hierarchy"], "Own records only")

	def test_an_unknown_data_access_value_is_refused(self):
		from crm.api.access import set_data_access

		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			set_data_access(manager_outside_hierarchy="Everything")
```

- [ ] **Step 2: Run them to make sure they fail**

```bash
cd /home/frappe/frappe-bench
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: FAIL — `ModuleNotFoundError: No module named 'crm.api.access'`.

- [ ] **Step 3: Write the implementation**

Create `crm/api/access.py`:

```python
# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Role visibility and the data-access boundary.

Two things live here, and the difference between them is the whole design.

``get_data_access`` / ``set_data_access`` are the *real* boundary: they move
``enable_sales_hierarchy`` and ``manager_outside_hierarchy``, which change what
the database returns. Administrator only.

``get_visibility`` / ``set_visibility`` are *chrome*: which nav links and
settings panes a role is shown. A manager may set the rep row; only an
administrator may set the manager row. The invariant that makes that safe is
that every consumer composes this with the role gate it already had --
``canSee(key) && isAdmin()``, never ``canSee(key)`` alone -- so configuration
can only ever hide a surface, never reveal one. ``crm/tests/test_access_settings.py``
asserts it against a real endpoint.

There is deliberately no System Manager row: nothing is hideable from an
administrator, so an administrator cannot configure themselves out of the pane
that would undo it.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

from crm.utils import sales_user_only

SETTINGS_DOCTYPE = "CRM Access Settings"

#: Roles whose surface set is configurable. Not System Manager -- see the
#: module docstring.
CONFIGURABLE_ROLES = ("Sales Manager", "Sales User")

#: Shape-validated rather than checked against an allow-list, so the surface
#: registry lives in one place (frontend/src/utils/surfaces.js) instead of two.
#: An unrecognised key is inert: because config only narrows, the worst it can
#: do is fail to hide something.
SURFACE_KEY = re.compile(r"^(nav|settings)\.[a-z0-9_]{1,48}$")

#: A bound on how much one write may store. The registry is ~40 surfaces across
#: two roles; this leaves room to grow without leaving the table unbounded.
MAX_SURFACES = 200

MANAGER_SCOPES = ("All records", "Own records only")


def _effective_role(user: str | None = None) -> str:
	"""The single role the frontend reasons with, most privileged first.

	Mirrors ``crm.api.session.get_session_role_flags``, which keeps its three
	flags mutually exclusive. A user holding both Sales Manager and Sales User
	is a manager.
	"""
	roles = frappe.get_roles(user or frappe.session.user)
	if user == "Administrator" or "System Manager" in roles:
		return "System Manager"
	if "Sales Manager" in roles:
		return "Sales Manager"
	return "Sales User"


def _hidden_for(role: str) -> list[str]:
	"""Surfaces hidden for ``role``. Always empty for an administrator."""
	if role not in CONFIGURABLE_ROLES:
		return []
	return frappe.get_all(
		"CRM Role Surface",
		filters={"parenttype": SETTINGS_DOCTYPE, "role": role},
		pluck="surface",
		order_by="idx asc",
	)


def manager_outside_hierarchy_sees_all() -> bool:
	"""Whether a Sales Manager who is not in the tree reads the whole site.

	``get_single_value`` reads ``tabSingles`` and returns ``None`` for a Single
	that has never been saved, so the historical answer has to be the fallback
	here and not only the field default -- otherwise installing this feature
	would silently narrow every existing site on the next request.

	Deliberately uncached, for the reason ``org_hierarchy._in_hierarchy`` gives:
	``frappe.local.request_cache`` lives for a whole scheduler process, so a
	setting changed mid-run would read stale until a restart.
	"""
	value = frappe.db.get_single_value(SETTINGS_DOCTYPE, "manager_outside_hierarchy")
	return (value or "All records") == "All records"


# --- surface visibility ----------------------------------------------------


@frappe.whitelist()
@sales_user_only
def get_visibility() -> dict:
	"""What the session user's shell should hide, plus the matrix if they may see it.

	``hidden`` is the caller's own row and is all ``AppSidebar`` and ``Settings``
	need. ``matrix`` is populated for an administrator or a manager -- the pane's
	data arrives with the same call that gates the sidebar -- and ``None`` for a
	rep, who has no business holding another role's configuration.
	"""
	role = _effective_role()
	matrix = None
	if role in ("System Manager", "Sales Manager"):
		matrix = {configurable: _hidden_for(configurable) for configurable in CONFIGURABLE_ROLES}
	return {"role": role, "hidden": _hidden_for(role), "matrix": matrix}


def _validated_keys(hidden) -> list[str]:
	if isinstance(hidden, str):
		hidden = frappe.parse_json(hidden)
	if hidden is None:
		hidden = []
	if not isinstance(hidden, list):
		frappe.throw(_("Hidden surfaces must be a list."))
	if len(hidden) > MAX_SURFACES:
		frappe.throw(_("At most {0} surfaces may be hidden at once.").format(MAX_SURFACES))

	keys = []
	for key in hidden:
		if not isinstance(key, str) or not SURFACE_KEY.match(key):
			frappe.throw(_("{0} is not a surface key.").format(key))
		if key not in keys:
			keys.append(key)
	return keys


@frappe.whitelist()
def set_visibility(role: str, hidden: list | str) -> dict:
	"""Replace ``role``'s hidden set.

	A whole-row replace rather than add/remove: the pane posts the row it is
	showing, so there is no read-modify-write window in which two managers
	editing at once lose each other's changes.

	Saved with ``ignore_permissions`` because the doctype is administrator-only
	by design -- this endpoint *is* the manager's authorisation, and the check
	above is the rule. Same shape as ``crm.api.suggestions``, which says the
	same thing about its own state machine.
	"""
	frappe.only_for(["System Manager", "Sales Manager"], True)

	if role not in CONFIGURABLE_ROLES:
		frappe.throw(
			_("{0} is not a configurable role. Nothing can be hidden from an administrator.").format(role)
		)

	if "System Manager" not in frappe.get_roles() and role != "Sales User":
		frappe.throw(
			_("Only an administrator can change what managers see."),
			frappe.PermissionError,
		)

	keys = _validated_keys(hidden)

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	settings.hidden_surfaces = [row for row in settings.hidden_surfaces if row.role != role]
	for key in keys:
		settings.append("hidden_surfaces", {"role": role, "surface": key})
	settings.save(ignore_permissions=True)

	return {"role": role, "hidden": keys}


# --- data access -----------------------------------------------------------


@frappe.whitelist()
@sales_user_only
def get_data_access() -> dict:
	"""The two switches that actually change what the database returns.

	Readable by anyone in the CRM so the pane can render for a manager as
	read-only context -- knowing the site scopes by hierarchy leaks nothing, and
	a manager seeing "your team only" explains their own numbers to them.
	"""
	return {
		"enable_sales_hierarchy": frappe.db.get_single_value(
			"FCRM Settings", "enable_sales_hierarchy"
		)
		or 0,
		"manager_outside_hierarchy": frappe.db.get_single_value(
			SETTINGS_DOCTYPE, "manager_outside_hierarchy"
		)
		or "All records",
		"hierarchy_size": frappe.db.count("CRM Sales Hierarchy"),
	}


@frappe.whitelist()
def set_data_access(
	enable_sales_hierarchy: int | str | None = None,
	manager_outside_hierarchy: str | None = None,
) -> dict:
	"""Move the real boundary. Administrator only.

	Not a Sales Manager: widening this is how a manager would reach another
	team's compensation figures, which is the invariant SECURITY.md names.
	"""
	frappe.only_for("System Manager", True)

	if enable_sales_hierarchy is not None:
		frappe.db.set_single_value(
			"FCRM Settings", "enable_sales_hierarchy", 1 if frappe.utils.cint(enable_sales_hierarchy) else 0
		)

	if manager_outside_hierarchy is not None:
		if manager_outside_hierarchy not in MANAGER_SCOPES:
			frappe.throw(
				_("{0} is not a valid setting. Choose one of: {1}.").format(
					manager_outside_hierarchy, ", ".join(MANAGER_SCOPES)
				)
			)
		frappe.db.set_single_value(
			SETTINGS_DOCTYPE, "manager_outside_hierarchy", manager_outside_hierarchy
		)

	return get_data_access()
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd /home/frappe/frappe-bench
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: PASS, 22 tests across the two classes.

- [ ] **Step 5: Format with the pinned ruff, not the local one**

CI formats with ruff 0.8.1 and the local install is newer; verifying with the wrong one gets the PR bounced.

```bash
cd /workspace/.worktrees/feat-role-access
uvx ruff@0.8.1 format crm/api/access.py crm/tests/test_access_settings.py \
  crm/fcrm/doctype/crm_access_settings/crm_access_settings.py
uvx ruff@0.8.1 check crm/api/access.py crm/tests/test_access_settings.py
```

- [ ] **Step 6: Commit**

```bash
git add crm/api/access.py crm/tests/test_access_settings.py
git commit -m "feat: read and write role visibility and the data access boundary

get_visibility hands the shell the caller's own hidden set and, for an
admin or manager, the whole matrix -- a rep never receives another role's
configuration. set_visibility replaces one row at a time and refuses any
row but Sales User unless the caller is an administrator, which is what
keeps the pane from being a way for a manager to widen their own access.

set_data_access moves the two switches that change what the database
returns, and is administrator-only: widening those is how a manager would
reach another team's compensation figures.

The invariant is under test against a real endpoint -- a rep with
nav.analyst visible still gets PermissionError from ask_analyst, because
every gate composes canSee(key) with the role gate it already had."
```

---

### Task 4: The out-of-tree manager rule, and safe defaults for new installs

**Files:**
- Modify: `crm/permissions/org_hierarchy.py:29-31` and `:87-88`
- Modify: `crm/install.py` (add `ensure_access_defaults()`, call it from `after_install`)
- Test: `crm/permissions/test_org_hierarchy.py` (append), `crm/tests/test_access_settings.py` (append)

**Interfaces:**
- Consumes: `crm.api.access.manager_outside_hierarchy_sees_all()` from Task 3.
- Produces: `crm.install.ensure_access_defaults()` — called by `after_install`, and called directly by its test.

- [ ] **Step 1: Write the failing tests**

Append to `crm/permissions/test_org_hierarchy.py`:

```python
class ManagerOutsideHierarchyTest(IntegrationTestCase):
	"""The out-of-tree manager used to be hardcoded to "sees everything".

	That is a fair escape hatch for a manager who runs the whole book, and it is
	also what every manager got on a site whose tree nobody had built -- so
	defaulting the hierarchy on, alone, just moved the problem. It is now a
	setting, and this is the test that it is actually read.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		email = "outside-manager@crmtest.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Outside Manager",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True).add_roles("Sales Manager")
		self.manager = email

		self.saved_hierarchy = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.saved_scope = frappe.db.get_single_value(
			"CRM Access Settings", "manager_outside_hierarchy"
		)
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value(
			"FCRM Settings", "enable_sales_hierarchy", self.saved_hierarchy or 0
		)
		frappe.db.set_single_value(
			"CRM Access Settings", "manager_outside_hierarchy", self.saved_scope or "All records"
		)

	def test_all_records_leaves_an_out_of_tree_manager_unrestricted(self):
		from crm.permissions.org_hierarchy import get_deal_permission_query_conditions

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.assertEqual(get_deal_permission_query_conditions(self.manager), "")

	def test_own_records_only_scopes_an_out_of_tree_manager(self):
		from crm.permissions.org_hierarchy import get_deal_permission_query_conditions

		frappe.db.set_single_value(
			"CRM Access Settings", "manager_outside_hierarchy", "Own records only"
		)
		condition = get_deal_permission_query_conditions(self.manager)
		self.assertNotEqual(condition, "")
		self.assertIn(self.manager, condition)

	def test_an_unsaved_setting_reads_as_all_records(self):
		"""get_single_value returns None for a Single that was never saved, so an
		existing site upgrading into this feature must not change behaviour."""
		from crm.api.access import manager_outside_hierarchy_sees_all

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", None)
		self.assertTrue(manager_outside_hierarchy_sees_all())
```

Append to `crm/tests/test_access_settings.py`:

```python
class InstallDefaultsTest(IntegrationTestCase):
	"""A new install starts scoped; an existing one is never touched."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.saved_hierarchy = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.saved_scope = frappe.db.get_single_value(
			"CRM Access Settings", "manager_outside_hierarchy"
		)
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.db.set_single_value(
			"FCRM Settings", "enable_sales_hierarchy", self.saved_hierarchy or 0
		)
		frappe.db.set_single_value(
			"CRM Access Settings", "manager_outside_hierarchy", self.saved_scope or "All records"
		)

	def test_ensure_access_defaults_scopes_a_fresh_site(self):
		from crm.install import ensure_access_defaults

		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")

		ensure_access_defaults()

		self.assertEqual(
			frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy"), 1
		)
		self.assertEqual(
			frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy"),
			"Own records only",
		)
```

- [ ] **Step 2: Run them to make sure they fail**

```bash
cd /home/frappe/frappe-bench
bench --site test_site run-tests --module crm.permissions.test_org_hierarchy
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: the two scope tests fail (the setting is not read yet — `Own records only` still returns `""`), and `ensure_access_defaults` fails to import.

- [ ] **Step 3: Read the setting in `org_hierarchy.py`**

Replace lines 29-31:

```python
	# Sales Manager outside the tree retains the default ie sees everything
	if "Sales Manager" in roles and not in_tree:
		return ""
```

with:

```python
	# A Sales Manager outside the tree sees everything -- unless an administrator
	# has said otherwise. The historical answer is the fallback (see
	# manager_outside_hierarchy_sees_all), so an existing site is unchanged; a
	# new install is set to "Own records only", without which defaulting the
	# hierarchy on does nothing on a site whose tree nobody has built yet.
	if "Sales Manager" in roles and not in_tree and manager_outside_hierarchy_sees_all():
		return ""
```

and lines 87-88:

```python
	if "Sales Manager" in roles and not in_tree:
		return True
```

with:

```python
	if "Sales Manager" in roles and not in_tree and manager_outside_hierarchy_sees_all():
		return True
```

Add the import at the top of both functions' shared module scope — put it inside the two functions, next to the existing local import of `hierarchy_enabled`'s neighbours, to avoid a circular import (`crm.api.access` imports `crm.utils`, which is safe, but `crm.api` packages import broadly):

```python
	from crm.api.access import manager_outside_hierarchy_sees_all
```

Place that line immediately after the existing `roles = frappe.get_roles(user)` in `_permission_query_conditions`, and after the same line in `_has_permission`.

- [ ] **Step 4: Add the install default**

In `crm/install.py`, add after `ensure_acumatica_fields()` in the `after_install` body:

```python
	ensure_access_defaults()
```

and define it beside the other `ensure_*` helpers:

```python
def ensure_access_defaults():
	"""A fresh site scopes managers to their own team until a tree exists.

	Two stored writes rather than field defaults, so no existing site is
	touched: there is no migration patch, and ``org_hierarchy`` treats a missing
	value as the historical "sees everything".

	One consequence to know about: ``FCRMSettings.restore_defaults`` calls
	``after_install``, so an administrator pressing *Restore Defaults* on an
	existing site also switches the hierarchy on. That is defensible for a
	button with that name, and it is in the release note.
	"""
	frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
	frappe.db.set_single_value(
		"CRM Access Settings", "manager_outside_hierarchy", "Own records only"
	)
```

- [ ] **Step 5: Run both modules to verify they pass**

```bash
cd /home/frappe/frappe-bench
bench --site test_site run-tests --module crm.permissions.test_org_hierarchy
bench --site test_site run-tests --module crm.tests.test_access_settings
```

Expected: PASS in both. Then the whole app, because `org_hierarchy` is load-bearing for every lead and deal query:

```bash
bench --site test_site purge-jobs
bench --site test_site run-tests --app crm
```

Expected: no new failures. Grep every `Ran N tests` line; the last two blocks' split shifts between runs, so compare totals rather than blocks.

- [ ] **Step 6: Commit**

```bash
cd /workspace/.worktrees/feat-role-access
uvx ruff@0.8.1 format crm/permissions/org_hierarchy.py crm/install.py crm/permissions/test_org_hierarchy.py
git add crm/permissions/org_hierarchy.py crm/permissions/test_org_hierarchy.py crm/install.py crm/tests/test_access_settings.py
git commit -m "feat: make the out-of-tree manager rule a setting, and scope new installs

org_hierarchy hardcoded "a Sales Manager outside the tree sees everything"
in two places. That is a fair escape hatch for a manager who runs the whole
book, and it was also what every manager got on a site whose tree nobody had
built -- so enable_sales_hierarchy defaulting off meant a default install
handed any manager every lead, deal, quota and plan on the site.

The rule is now manager_outside_hierarchy, and a new install is set to
\"Own records only\" alongside the hierarchy. Existing sites are untouched:
there is no patch, and get_single_value returns None for a Single that was
never saved, so the reader falls back to the historical answer."
```

---

### Task 5: `frontend/src/utils/surfaces.js` — the registry and the pure gate

**Files:**
- Create: `frontend/src/utils/surfaces.js`
- Test: `frontend/tests/unit/surfaces.test.js`

Lives in `src/utils/` deliberately: `frontend/vitest.config.js` scopes coverage to `src/utils/**` and `src/composables/**`, so pure logic put anywhere else contributes nothing to the patch target.

**Interfaces:**
- Consumes: the key shape from Task 3 — `^(nav|settings)\.[a-z0-9_]{1,48}$`.
- Produces:
  - `SURFACES: Array<{key, group, label, floor?}>` where `group` is `'nav' | 'settings'`, `floor` is `'System Manager' | 'Sales Manager'` or absent
  - `canSee(key, hidden) -> boolean`
  - `editableBy(callerRole, targetRole) -> boolean`
  - `isAtFloor(surface, role) -> boolean`
  - `surfacesByGroup(group) -> Array`
  - Tasks 6 and 7 import all of these.

- [ ] **Step 1: Write the failing test**

Create `frontend/tests/unit/surfaces.test.js`:

```js
import { describe, it, expect } from 'vitest'
import {
  SURFACES,
  canSee,
  editableBy,
  isAtFloor,
  surfacesByGroup,
} from '@/utils/surfaces'

const KEY_SHAPE = /^(nav|settings)\.[a-z0-9_]{1,48}$/

describe('SURFACES', () => {
  it('gives every surface a key the server will accept', () => {
    for (const surface of SURFACES) {
      expect(surface.key, surface.key).toMatch(KEY_SHAPE)
    }
  })

  it('has no duplicate keys', () => {
    const keys = SURFACES.map((s) => s.key)
    expect(new Set(keys).size).toBe(keys.length)
  })

  it('groups every surface as nav or settings', () => {
    for (const surface of SURFACES) {
      expect(['nav', 'settings']).toContain(surface.group)
    }
  })

  it('labels every surface', () => {
    for (const surface of SURFACES) {
      expect(surface.label, surface.key).toBeTruthy()
    }
  })

  it('gives every settings surface a section, and no nav surface one', () => {
    // The matrix renders `section · label` for settings rows, because
    // "Accounts" and "Templates" mean nothing on their own.
    for (const surface of surfacesByGroup('settings')) {
      expect(surface.section, surface.key).toBeTruthy()
    }
    for (const surface of surfacesByGroup('nav')) {
      expect(surface.section, surface.key).toBeUndefined()
    }
  })

  it('uses only section names that exist in Settings.vue', () => {
    const real = [
      'User Configuration',
      'System Configuration',
      'User Management',
      'Email',
      'Automation & Rules',
      'Customization',
      'Integrations',
    ]
    for (const surface of surfacesByGroup('settings')) {
      expect(real, surface.key).toContain(surface.section)
    }
  })

  it('covers the nav links and the settings panes', () => {
    expect(surfacesByGroup('nav').length).toBe(13)
    expect(surfacesByGroup('settings').length).toBe(27)
  })
})

describe('canSee', () => {
  it('shows a surface nobody has hidden', () => {
    expect(canSee('nav.notes', [])).toBe(true)
  })

  it('hides a surface in the hidden set', () => {
    expect(canSee('nav.notes', ['nav.notes'])).toBe(false)
  })

  it('treats a missing hidden set as nothing hidden', () => {
    expect(canSee('nav.notes', undefined)).toBe(true)
    expect(canSee('nav.notes', null)).toBe(true)
  })

  it('ignores an unrecognised key in the hidden set', () => {
    expect(canSee('nav.notes', ['nav.nonsense'])).toBe(true)
  })
})

describe('editableBy', () => {
  it('lets an admin edit both configurable roles', () => {
    expect(editableBy('System Manager', 'Sales Manager')).toBe(true)
    expect(editableBy('System Manager', 'Sales User')).toBe(true)
  })

  it('lets a manager edit only the rep row', () => {
    expect(editableBy('Sales Manager', 'Sales User')).toBe(true)
    expect(editableBy('Sales Manager', 'Sales Manager')).toBe(false)
  })

  it('lets a rep edit nothing', () => {
    expect(editableBy('Sales User', 'Sales User')).toBe(false)
    expect(editableBy('Sales User', 'Sales Manager')).toBe(false)
  })

  it('refuses the admin row to everyone, admins included', () => {
    expect(editableBy('System Manager', 'System Manager')).toBe(false)
  })
})

describe('isAtFloor', () => {
  const analyst = { key: 'nav.analyst', group: 'nav', label: 'Analyst', floor: 'System Manager' }
  const targets = { key: 'settings.sales_targets', group: 'settings', label: 'Sales Targets', floor: 'Sales Manager' }
  const notes = { key: 'nav.notes', group: 'nav', label: 'Notes' }

  it('is at floor when the role already cannot reach it', () => {
    expect(isAtFloor(analyst, 'Sales User')).toBe(true)
    expect(isAtFloor(analyst, 'Sales Manager')).toBe(true)
    expect(isAtFloor(targets, 'Sales User')).toBe(true)
  })

  it('is not at floor when the role can reach it', () => {
    expect(isAtFloor(targets, 'Sales Manager')).toBe(false)
    expect(isAtFloor(notes, 'Sales User')).toBe(false)
  })

  it('is never at floor for a surface with no floor', () => {
    expect(isAtFloor(notes, 'Sales Manager')).toBe(false)
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd frontend
yarn vitest run tests/unit/surfaces.test.js
```

Expected: FAIL — `Failed to resolve import "@/utils/surfaces"`.

- [ ] **Step 3: Write the implementation**

Create `frontend/src/utils/surfaces.js`:

```js
/**
 * The surfaces an administrator or manager may hide, per role.
 *
 * This is the registry Settings → Access Control renders and the shell
 * consults. Two rules keep it honest:
 *
 *  1. **Configuration only narrows.** Every consumer composes this with the
 *     role gate it already had — `canSee(key) && isAdmin()`, never
 *     `canSee(key)` alone. Unhiding a surface therefore cannot reveal it, and
 *     an unrecognised key can only fail to hide something.
 *  2. **There is no admin row.** Nothing is hideable from a System Manager, so
 *     an administrator can never configure themselves out of this pane.
 *
 * `floor` records the role gate the code *already* enforces, so the matrix can
 * render a cell as fixed rather than offering a toggle the first rule
 * guarantees is inert. Keep it in step with the `condition:` on the surface.
 *
 * Adding a surface: add it here, and add `canSee('<key>') &&` to its existing
 * condition in AppSidebar.vue or Settings.vue. A surface missing from this list
 * simply stays visible, which is the safe direction.
 *
 * Keys must match the server's shape check in `crm/api/access.py`:
 * `^(nav|settings)\.[a-z0-9_]{1,48}$`.
 */

export const ADMIN_ROLE = 'System Manager'
export const MANAGER_ROLE = 'Sales Manager'
export const REP_ROLE = 'Sales User'

/** The matrix's columns. Not ADMIN_ROLE — see rule 2 above. */
export const CONFIGURABLE_ROLES = [MANAGER_ROLE, REP_ROLE]

export const SURFACES = [
  // --- nav: AppSidebar.vue's `links` ---
  { key: 'nav.dashboard', group: 'nav', label: 'Dashboard' },
  { key: 'nav.assistant', group: 'nav', label: 'Assistant' },
  { key: 'nav.analyst', group: 'nav', label: 'Analyst', floor: ADMIN_ROLE },
  { key: 'nav.planner', group: 'nav', label: 'Planner' },
  { key: 'nav.leads', group: 'nav', label: 'Leads' },
  { key: 'nav.deals', group: 'nav', label: 'Deals' },
  { key: 'nav.reports', group: 'nav', label: 'Reports' },
  { key: 'nav.notes', group: 'nav', label: 'Notes' },
  { key: 'nav.tasks', group: 'nav', label: 'Tasks' },
  { key: 'nav.calendar', group: 'nav', label: 'Calendar' },
  { key: 'nav.organizations', group: 'nav', label: 'Organizations' },
  { key: 'nav.contacts', group: 'nav', label: 'Contacts' },
  { key: 'nav.call_logs', group: 'nav', label: 'Call Logs' },

  // --- settings: Settings.vue's `tabs` ---
  // `section` is the settings group the pane lives under. It exists because
  // several labels are meaningless alone in a flat matrix -- "Accounts" (of
  // what?), "Templates" -- and because "Dashboard", "Calendar" and "Assistant"
  // each name BOTH a nav link and a settings pane. The pane renders
  // `section · label`.
  { key: 'settings.profile', group: 'settings', section: 'User Configuration', label: 'Profile' },
  { key: 'settings.preferences', group: 'settings', section: 'User Configuration', label: 'Preferences' },
  { key: 'settings.general', group: 'settings', section: 'System Configuration', label: 'General', floor: MANAGER_ROLE },
  { key: 'settings.dashboard', group: 'settings', section: 'System Configuration', label: 'Dashboard', floor: MANAGER_ROLE },
  { key: 'settings.defaults', group: 'settings', section: 'System Configuration', label: 'Defaults', floor: ADMIN_ROLE },
  { key: 'settings.brand', group: 'settings', section: 'System Configuration', label: 'Brand', floor: MANAGER_ROLE },
  { key: 'settings.calendar', group: 'settings', section: 'System Configuration', label: 'Calendar', floor: MANAGER_ROLE },
  { key: 'settings.users', group: 'settings', section: 'User Management', label: 'Users', floor: MANAGER_ROLE },
  { key: 'settings.invite_user', group: 'settings', section: 'User Management', label: 'Invite User', floor: MANAGER_ROLE },
  { key: 'settings.sales_hierarchy', group: 'settings', section: 'User Management', label: 'Sales Hierarchy', floor: MANAGER_ROLE },
  { key: 'settings.sales_targets', group: 'settings', section: 'User Management', label: 'Sales Targets', floor: MANAGER_ROLE },
  { key: 'settings.access_control', group: 'settings', section: 'User Management', label: 'Access Control', floor: MANAGER_ROLE },
  { key: 'settings.email_accounts', group: 'settings', section: 'Email', label: 'Accounts', floor: ADMIN_ROLE },
  { key: 'settings.email_templates', group: 'settings', section: 'Email', label: 'Templates', floor: MANAGER_ROLE },
  { key: 'settings.assignment_rules', group: 'settings', section: 'Automation & Rules', label: 'Assignment Rules', floor: ADMIN_ROLE },
  { key: 'settings.sla_policies', group: 'settings', section: 'Automation & Rules', label: 'SLA Policies', floor: MANAGER_ROLE },
  { key: 'settings.automation_rules', group: 'settings', section: 'Automation & Rules', label: 'Automation Rules', floor: MANAGER_ROLE },
  { key: 'settings.assistant', group: 'settings', section: 'Automation & Rules', label: 'Assistant', floor: ADMIN_ROLE },
  { key: 'settings.knowledge', group: 'settings', section: 'Automation & Rules', label: 'Knowledge', floor: ADMIN_ROLE },
  { key: 'settings.report_digests', group: 'settings', section: 'Automation & Rules', label: 'Report Digests', floor: MANAGER_ROLE },
  { key: 'settings.forms', group: 'settings', section: 'Automation & Rules', label: 'Forms', floor: MANAGER_ROLE },
  { key: 'settings.home_actions', group: 'settings', section: 'Customization', label: 'Home Actions', floor: MANAGER_ROLE },
  { key: 'settings.telephony', group: 'settings', section: 'Integrations', label: 'Telephony' },
  { key: 'settings.whatsapp', group: 'settings', section: 'Integrations', label: 'WhatsApp', floor: MANAGER_ROLE },
  { key: 'settings.simerp', group: 'settings', section: 'Integrations', label: 'SIMERP', floor: MANAGER_ROLE },
  { key: 'settings.acumatica', group: 'settings', section: 'Integrations', label: 'Acumatica', floor: MANAGER_ROLE },
  { key: 'settings.lead_syncing', group: 'settings', section: 'Integrations', label: 'Lead Syncing', floor: MANAGER_ROLE },
]

/** How much each role can reach, for comparing against a surface's floor. */
const RANK = { [REP_ROLE]: 0, [MANAGER_ROLE]: 1, [ADMIN_ROLE]: 2 }

export function surfacesByGroup(group) {
  return SURFACES.filter((surface) => surface.group === group)
}

/**
 * Whether `key` should be shown, given the hidden set from the server.
 *
 * Compose this with the surface's existing role gate — never use it alone.
 */
export function canSee(key, hidden) {
  return !(hidden || []).includes(key)
}

/** Whether `callerRole` may change `targetRole`'s row. Mirrors `set_visibility`. */
export function editableBy(callerRole, targetRole) {
  if (!CONFIGURABLE_ROLES.includes(targetRole)) return false
  if (callerRole === ADMIN_ROLE) return true
  if (callerRole === MANAGER_ROLE) return targetRole === REP_ROLE
  return false
}

/**
 * Whether `role` already cannot reach `surface`, so hiding it would do nothing.
 *
 * The matrix renders these cells as fixed. Offering a toggle whose effect the
 * narrowing rule guarantees is nil teaches the operator the wrong model of what
 * this pane does.
 */
export function isAtFloor(surface, role) {
  if (!surface.floor) return false
  return RANK[role] < RANK[surface.floor]
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
cd frontend
yarn vitest run tests/unit/surfaces.test.js
```

Expected: PASS. If the two count assertions fail, the registry and the app have drifted — reconcile against `AppSidebar.vue`'s `links` and `Settings.vue`'s `tabs` rather than editing the expected numbers.

- [ ] **Step 5: Format with the pinned prettier**

```bash
cd frontend
npx prettier@3.2.5 --write src/utils/surfaces.js tests/unit/surfaces.test.js
yarn test:run
```

- [ ] **Step 6: Commit**

```bash
git add frontend/src/utils/surfaces.js frontend/tests/unit/surfaces.test.js
git commit -m "feat: add the surface registry and the pure visibility gate

One list of the 13 nav links and 27 settings panes, with the role floor
each already enforces, so the matrix can render a cell as fixed rather
than offering a toggle the narrowing rule guarantees is inert.

canSee is the whole gate and is meant to be composed, never used alone.
editableBy mirrors set_visibility's rule so the UI never offers a control
the server will refuse. In src/utils/ because vitest.config.js scopes
coverage there."
```

---

### Task 6: `frontend/src/stores/access.js` and the router await

**Files:**
- Create: `frontend/src/stores/access.js`
- Modify: `frontend/src/router.js:184-190`

**Interfaces:**
- Consumes: `canSee`, `editableBy`, `SURFACES`, `CONFIGURABLE_ROLES` from Task 5; `crm.api.access.get_visibility` from Task 3.
- Produces: `accessStore()` exposing `visibility` (resource), `canSee(key)`, `role` (computed string), `matrix` (computed object or null), `reload()`. Task 7 imports all of these.

- [ ] **Step 1: Write the store**

Create `frontend/src/stores/access.js`:

```js
/**
 * What the current session may see, per Settings → Access Control.
 *
 * `canSee` is a *narrowing* gate: compose it with the role check a surface
 * already had (`canSee('nav.analyst') && isAdmin()`), never on its own. See
 * `@/utils/surfaces` for why.
 *
 * The resource is awaited in the router's global guard alongside `users`, so
 * the shell paints once with the right set instead of showing a link and then
 * retracting it. Until it resolves — and if it fails — nothing is hidden, which
 * is the correct fail-open for chrome: a link that should have been tidied away
 * is a wart, and a shell missing half its nav because one request failed is an
 * outage.
 */
import { computed, reactive } from 'vue'
import { createResource } from 'frappe-ui'
import { defineStore } from 'pinia'
import { canSee as canSeeSurface } from '@/utils/surfaces'

export const accessStore = defineStore('crm-access', () => {
  const state = reactive({ role: 'Sales User', hidden: [], matrix: null })

  const visibility = createResource({
    url: 'crm.api.access.get_visibility',
    cache: 'access-visibility',
    auto: false,
    onSuccess(data) {
      state.role = data?.role || 'Sales User'
      state.hidden = data?.hidden || []
      state.matrix = data?.matrix || null
    },
    onError() {
      // fail open — see the module comment
      state.hidden = []
    },
  })

  function canSee(key) {
    return canSeeSurface(key, state.hidden)
  }

  function reload() {
    return visibility.fetch()
  }

  return {
    visibility,
    canSee,
    reload,
    role: computed(() => state.role),
    hidden: computed(() => state.hidden),
    matrix: computed(() => state.matrix),
  }
})
```

- [ ] **Step 2: Await it in the router's existing guard**

In `frontend/src/router.js`, the guard currently reads:

```js
  const { isLoggedIn, user } = sessionStore()
  const { users, isCrmUser, isAdmin } = usersStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }
```

Add the access resource to the same await, so both are resolved before the shell renders:

```js
  const { isLoggedIn, user } = sessionStore()
  const { users, isCrmUser, isAdmin } = usersStore()
  const { visibility: accessVisibility } = accessStore()

  if (isLoggedIn && !users.fetched) {
    try {
      await users.promise
    } catch (error) {
      console.error('Error loading users', error)
    }
  }

  // Awaited here rather than in the sidebar so the shell paints once. A
  // failure is swallowed on purpose: the store leaves nothing hidden, which
  // is the right fail-open for chrome.
  if (isLoggedIn && !accessVisibility.fetched) {
    try {
      await accessVisibility.fetch()
    } catch (error) {
      console.error('Error loading access settings', error)
    }
  }
```

and add the import beside the other store imports at the top of `router.js`:

```js
import { accessStore } from '@/stores/access'
```

- [ ] **Step 3: Verify the suite still passes and the app boots**

```bash
cd frontend
yarn test:run
yarn build
```

Expected: tests pass, build succeeds. QA on the built app at `:8000`, not the vite server at `:8080` — `:8080` POSTs race the CSRF token mint, which shows up as spurious 400s that look like a bug in this code.

- [ ] **Step 4: Confirm one request, not one per component**

Open the built app, sign in, and check the network panel: exactly one `crm.api.access.get_visibility` call on load. More than one means a component is fetching instead of reading the store.

- [ ] **Step 5: Commit**

```bash
cd frontend
npx prettier@3.2.5 --write src/stores/access.js src/router.js
cd ..
git add frontend/src/stores/access.js frontend/src/router.js
git commit -m "feat: load role visibility once, in the router guard

The shell must not paint a nav link and then retract it, so the visibility
resource is awaited alongside users in the guard that already waits for
them. A failure is swallowed and nothing is hidden: a link that should have
been tidied away is a wart, a shell missing half its nav because one
request failed is an outage."
```

---

### Task 7: The `Access Control` pane, and `canSee` in the two shells

The biggest task, and the one that needs eyes on a screen. `Quotas.vue` is the model — the other grid pane in Settings, and it already carries the four states this needs.

**Files:**
- Create: `frontend/src/components/Settings/AccessControl.vue`
- Modify: `frontend/src/components/Settings/Settings.vue` (import + register the pane in `User Management`; add `key` to every item; compose `canSee`)
- Modify: `frontend/src/components/Layouts/AppSidebar.vue` (compose `canSee` into each link's condition)

**Interfaces:**
- Consumes: `accessStore()` from Task 6; `SURFACES`, `CONFIGURABLE_ROLES`, `editableBy`, `isAtFloor`, `surfacesByGroup` from Task 5; `crm.api.access.get_data_access` / `set_data_access` / `set_visibility` from Task 3.
- **`set_visibility` and `set_data_access` are `@frappe.whitelist(methods=["POST"])`.** frappe-ui's `createResource` defaults to GET, so every write resource here MUST pass `method: 'POST'` or the save will 403. The two read endpoints stay GET.
- Produces: the pane, reachable as `Settings → Access Control`.

- [ ] **Step 1: Add stable keys to the settings items**

In `Settings.vue`, every item in `tabs` gains a `key` matching its registry entry. For example:

```js
        {
          label: __('Profile'),
          key: 'settings.profile',
          icon: () => h(Avatar, { ... }),
          component: markRaw(ProfilePage),
        },
```

Do this for all 26 existing items, using the keys in `@/utils/surfaces`.

**Do not** rewire `activeTab`, `openPage` or `setActiveTab` to use `key`. They match on `item.label` today, and `AppSidebar.vue:664` deep-links by setting `activeSettingsPage.value = 'Invite User'` — an untranslated string compared against a translated `__('Invite User')`, so that deep link is already fragile on a translated site. That is a real latent bug and it is **not** in scope here; fixing it means touching the deep-link contract and belongs in its own change.

- [ ] **Step 2: Compose `canSee` into the settings conditions**

Still in `Settings.vue`, add to the script:

```js
import { accessStore } from '@/stores/access'

const { canSee } = accessStore()
```

and change the filter at the bottom of the `tabs` computed so a key'd item is also subject to the matrix:

```js
  return _tabs.filter((tab) => {
    if (tab.condition && !tab.condition()) return false
    if (tab.items) {
      // canSee only ever narrows: an item still has to pass the role condition
      // it already carried. See @/utils/surfaces.
      tab.items = tab.items.filter((item) => {
        if (item.key && !canSee(item.key)) return false
        if (item.condition && !item.condition()) return false
        return true
      })
    }
    return true
  })
```

A group whose items all filter out should not render its heading. Guard it:

```js
    return true
  }).filter((tab) => !tab.items || tab.items.length > 0)
```

- [ ] **Step 3: Register the pane**

In `Settings.vue`, import it and add it to the `User Management` group after `Sales Targets`:

```js
import AccessControl from '@/components/Settings/AccessControl.vue'
import { PhLockKey as LockKey } from '@phosphor-icons/vue'
```

```js
        {
          label: __('Access Control'),
          key: 'settings.access_control',
          icon: markRaw(h(LockKey)),
          component: markRaw(AccessControl),
          condition: () => isManager(),
        },
```

- [ ] **Step 4: Compose `canSee` into the nav links**

In `AppSidebar.vue`, add to the script beside the existing `usersStore()` destructure:

```js
import { accessStore } from '@/stores/access'

const { canSee } = accessStore()
```

Then give every entry in `links` a `key` and fold `canSee` into its condition. Entries with no condition gain one; entries that have one keep it and AND with `canSee`:

```js
  {
    label: 'Dashboard',
    key: 'nav.dashboard',
    icon: DashboardIcon,
    to: 'Dashboard',
    tint: 'text-ink-blue-6',
    condition: () => canSee('nav.dashboard'),
  },
  ...
  {
    label: 'Analyst',
    key: 'nav.analyst',
    icon: AnalystIcon,
    to: 'Analyst',
    tint: 'text-ink-cyan-6',
    // canSee narrows only: isAdmin() still decides, and the route guard at
    // router.js:64 and frappe.only_for in crm/agent/api.py both stand behind it.
    condition: () => canSee('nav.analyst') && isAdmin(),
  },
  ...
  {
    label: 'Calendar',
    key: 'nav.calendar',
    icon: CalendarIcon,
    to: 'Calendar',
    tint: 'text-ink-red-6',
    condition: () => canSee('nav.calendar') && !props.mobile,
  },
```

- [ ] **Step 5: Write the pane**

Create `frontend/src/components/Settings/AccessControl.vue`:

```vue
<!--
  Settings → Access Control.

  Two sections, and the difference between them is the design: above the rule,
  switches that change what the database returns; below it, a matrix that
  changes what the app shows. The copy says so, and it is load bearing -- edit
  it away and this pane starts implying it protects data that it does not.

  Nothing is hideable from an administrator, so the matrix has two columns. A
  manager may set the rep column only; the server refuses the rest
  (crm/api/access.py::set_visibility) and this UI does not offer it.
-->
<template>
  <div class="flex h-full flex-col gap-6 p-8">
    <div class="flex flex-col gap-1">
      <h2 class="v-title text-ink-gray-8">{{ __('Access Control') }}</h2>
      <p class="text-p-sm text-ink-gray-5">
        {{
          __(
            'Who can read what, and which parts of the app each role is shown.',
          )
        }}
      </p>
    </div>

    <!-- §1 Data access -->
    <section class="flex flex-col gap-3">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-base font-semibold text-ink-gray-8">
          {{ __('Data access') }}
        </h3>
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'These change what the server returns. They apply everywhere — lists, dashboards, reports and the API.',
            )
          }}
        </p>
      </div>

      <SkeletonTable
        v-if="dataAccess.loading"
        :columns="2"
        :rows="2"
        density="compact"
        :label="__('Loading data access settings')"
      />

      <ErrorState
        v-else-if="dataAccess.error"
        :error="dataAccess.error"
        :title="__('Could not load the data access settings')"
        :retry="dataAccess.reload"
      />

      <div v-else class="flex flex-col gap-3">
        <div
          class="flex items-start justify-between gap-4 rounded-[var(--v-radius-card)] bg-surface-white p-4"
        >
          <div class="flex flex-col gap-0.5">
            <div class="text-base text-ink-gray-8">
              {{ __('Restrict by sales hierarchy') }}
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{
                hierarchyCopy
              }}
            </p>
          </div>
          <CheckSwitch
            :model-value="dataAccess.data?.enable_sales_hierarchy"
            size="sm"
            :disabled="!isAdmin()"
            @update:model-value="onHierarchyToggle"
          />
        </div>

        <div
          class="flex items-start justify-between gap-4 rounded-[var(--v-radius-card)] bg-surface-white p-4"
        >
          <div class="flex flex-col gap-0.5">
            <div class="text-base text-ink-gray-8">
              {{ __('Managers outside the hierarchy') }}
            </div>
            <p class="text-p-sm text-ink-gray-5">
              {{
                __(
                  'A manager who is not in the tree either reads the whole site or only their own records. On a site with no tree yet, that is every manager.',
                )
              }}
            </p>
          </div>
          <Select
            class="w-48 shrink-0"
            :model-value="dataAccess.data?.manager_outside_hierarchy"
            :options="managerScopeOptions"
            :disabled="!isAdmin()"
            @update:model-value="onManagerScopeChange"
          />
        </div>

        <p v-if="!isAdmin()" class="text-p-sm text-ink-orange-9">
          {{ __('Only an administrator can change these.') }}
        </p>
      </div>
    </section>

    <!-- §2 Surface visibility -->
    <section class="flex min-h-0 flex-1 flex-col gap-3">
      <div class="flex flex-col gap-0.5">
        <h3 class="text-base font-semibold text-ink-gray-8">
          {{ __('What each role is shown') }}
        </h3>
        <!-- The sentence this pane is honest because of. Do not remove it. -->
        <p class="text-p-sm text-ink-gray-5">
          {{
            __(
              'Hiding a surface tidies the app for that role. It is not a permission — the data behind a hidden page is still governed by Data access above. Nothing can be hidden from an administrator.',
            )
          }}
        </p>
      </div>

      <div class="min-h-0 flex-1 overflow-auto">
        <table class="min-w-full text-base">
          <thead class="sticky top-0 z-10 bg-surface-elevation-2">
            <tr class="text-left text-ink-gray-6">
              <th class="py-2 pr-4 font-medium">{{ __('Surface') }}</th>
              <th
                v-for="role in CONFIGURABLE_ROLES"
                :key="role"
                class="w-40 py-2 pr-4 font-medium"
              >
                {{ roleLabel(role) }}
              </th>
            </tr>
          </thead>
          <tbody>
            <template v-for="group in ['nav', 'settings']" :key="group">
              <tr>
                <td
                  :colspan="CONFIGURABLE_ROLES.length + 1"
                  class="pb-1 pt-4 text-xs-medium uppercase tracking-wide text-ink-gray-5"
                >
                  {{ group === 'nav' ? __('Navigation') : __('Settings') }}
                </td>
              </tr>
              <tr
                v-for="surface in surfacesByGroup(group)"
                :key="surface.key"
                class="border-t border-[var(--v-shell-hairline)]"
              >
                <td class="py-2 pr-4 text-ink-gray-8">
                  <span v-if="surface.section" class="text-ink-gray-5"
                    >{{ __(surface.section) }} &middot; </span
                  >{{ __(surface.label) }}
                </td>
                <td
                  v-for="role in CONFIGURABLE_ROLES"
                  :key="role"
                  class="py-2 pr-4"
                >
                  <Tooltip
                    v-if="isAtFloor(surface, role)"
                    :text="
                      __('Already unavailable to this role: {0} only.', [
                        roleLabel(surface.floor),
                      ])
                    "
                  >
                    <span class="text-ink-gray-4">—</span>
                  </Tooltip>
                  <CheckSwitch
                    v-else
                    :model-value="isVisible(role, surface.key) ? 1 : 0"
                    size="sm"
                    :disabled="!editableBy(callerRole, role) || saving"
                    @update:model-value="
                      (v) => onToggle(role, surface.key, Boolean(v))
                    "
                  />
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { createResource, Select, Tooltip, toast } from 'frappe-ui'
import CheckSwitch from '@/components/ui/CheckSwitch.vue'
import ErrorState from '@/components/ui/ErrorState.vue'
import SkeletonTable from '@/components/ui/SkeletonTable.vue'
import { accessStore } from '@/stores/access'
import { usersStore } from '@/stores/users'
import { globalStore } from '@/stores/global'
import {
  CONFIGURABLE_ROLES,
  editableBy,
  isAtFloor,
  surfacesByGroup,
} from '@/utils/surfaces'

const { isAdmin } = usersStore()
const { $dialog } = globalStore()
const access = accessStore()

const saving = ref(false)

const callerRole = computed(() => access.role)

const ROLE_LABELS = {
  'Sales Manager': __('Manager'),
  'Sales User': __('Rep'),
  'System Manager': __('Admin'),
}
function roleLabel(role) {
  return ROLE_LABELS[role] || role
}

const managerScopeOptions = [
  { label: __('All records'), value: 'All records' },
  { label: __('Own records only'), value: 'Own records only' },
]

const dataAccess = createResource({
  url: 'crm.api.access.get_data_access',
  auto: true,
})

const hierarchyCopy = computed(() => {
  const size = dataAccess.data?.hierarchy_size || 0
  return dataAccess.data?.enable_sales_hierarchy
    ? __('On. Leads and deals are scoped to the reporting tree — {0} people are in it.', [size])
    : __('Off. Every manager reads every lead and deal on the site, and every rep\'s targets.')
})

function saveDataAccess(payload, message) {
  createResource({
    url: 'crm.api.access.set_data_access',
    params: payload,
  })
    .fetch()
    .then(() => {
      dataAccess.reload()
      toast.success(message)
    })
    .catch((error) => toast.error(error?.messages?.[0] || __('Could not save')))
}

function onHierarchyToggle(value) {
  // Only the *disabling* direction is confirmed: that is the one that widens
  // what a manager can read. Same shape as Hierarchy.vue.
  if (!value) {
    $dialog({
      title: __('Stop restricting by hierarchy?'),
      message: __(
        'Every manager will be able to read every lead, deal and sales target on the site. Are you sure?',
      ),
      actions: [
        {
          label: __('Stop restricting'),
          variant: 'solid',
          theme: 'red',
          onClick: ({ close }) => {
            saveDataAccess(
              { enable_sales_hierarchy: 0 },
              __('Hierarchy restriction disabled'),
            )
            close()
          },
        },
      ],
    })
    return
  }
  saveDataAccess({ enable_sales_hierarchy: 1 }, __('Hierarchy restriction enabled'))
}

function onManagerScopeChange(value) {
  saveDataAccess(
    { manager_outside_hierarchy: value },
    __('Saved'),
  )
}

function hiddenFor(role) {
  return access.matrix?.[role] || []
}

function isVisible(role, key) {
  return !hiddenFor(role).includes(key)
}

async function onToggle(role, key, nextVisible) {
  const hidden = new Set(hiddenFor(role))
  if (nextVisible) hidden.delete(key)
  else hidden.add(key)

  saving.value = true
  try {
    await createResource({
      url: 'crm.api.access.set_visibility',
      params: { role, hidden: Array.from(hidden) },
    }).fetch()
    // Re-read rather than patching local state: the caller's own row may be
    // among the ones that changed, and the shell reads it from this store.
    await access.reload()
  } catch (error) {
    toast.error(error?.messages?.[0] || __('Could not save'))
  } finally {
    saving.value = false
  }
}
</script>
```

- [ ] **Step 6: Verify the suite and build**

```bash
cd frontend
yarn test:run
yarn build
```

Expected: all tests pass, build succeeds.

- [ ] **Step 7: Browser QA — the part that cannot be skipped**

On the built app at `:8000`. Check as an **admin**:

1. `Settings → Access Control` is present and both sections render.
2. Toggling the hierarchy off raises the confirmation; the copy names the consequence.
3. `Analyst` shows a dash in both columns; `Sales Targets` shows a dash in the Rep column and a switch in the Manager column.
4. Hide `nav.notes` for `Sales User`. Sign in as a rep: Notes is gone from the nav. Sign back in as admin: unhide it; it returns.
5. **The invariant, by hand:** with `nav.analyst` visible for reps (its default), sign in as a rep and navigate to `/crm/analyst` directly. Expected: redirected to Dashboard by the route guard, and the endpoint refuses.

Then as a **manager**:

6. The Rep column is switches; the Manager column is disabled; the §1 controls are disabled with the "administrator only" line showing.

Then **both themes** — the `-9` steps used here (`text-ink-orange-9`) are not covered by the theme generator's contrast floors, so they need eyes in light and dark.

- [ ] **Step 8: Commit**

```bash
cd frontend
npx prettier@3.2.5 --write src/components/Settings/AccessControl.vue \
  src/components/Settings/Settings.vue src/components/Layouts/AppSidebar.vue
cd ..
git add frontend/src/components/Settings/AccessControl.vue \
  frontend/src/components/Settings/Settings.vue \
  frontend/src/components/Layouts/AppSidebar.vue
git commit -m "feat: add the Access Control settings pane

Two sections: the switches that change what the server returns, and a
role x surface matrix over the nav links and settings panes. The line
saying the matrix tidies rather than protects is load bearing -- without
it the pane implies a boundary it does not draw.

Every gate is now canSee(key) && the role check it already had, so
configuration can only narrow. The matrix has two columns because nothing
is hideable from an admin, and a manager gets the rep column only --
the same rule set_visibility enforces, so the UI never offers a control
the server will refuse."
```

---

### Task 8: Documentation

**Files:**
- Modify: `.pi/SPEC.md` (the stable contract)
- Modify: `.pi/ARCHIVE.md` (the rationale)
- Modify: `AGENTS.md` (the key-files tables)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing code depends on.

- [ ] **Step 1: Add the contract to `.pi/SPEC.md`**

Document, under a new `Role visibility` heading: the two endpoints and their exact payload shapes; the narrowing invariant as a stated contract; the two-column rule; the surface key shape; and "adding a surface" as a two-step recipe (registry entry, then `canSee` in the condition).

- [ ] **Step 2: Add the rationale to `.pi/ARCHIVE.md`**

Record what the audit found — the `enable_sales_hierarchy` default, the hardcoded out-of-tree rule, the ungated `Email → Templates` — and why the fix is shaped this way: why the matrix is not on `FCRM Settings`, why there is no admin column, why new installs differ from existing ones.

- [ ] **Step 3: Add the new files to `AGENTS.md`**

`crm/api/access.py` and `crm/permissions/org_hierarchy.py` to a permissions row; `AccessControl.vue` to the product-surfaces table; `utils/surfaces.js` to the meta/stores table.

- [ ] **Step 4: Commit**

`.pi/` paths are tracked but gitignored — `git add` on one warns and exits 1 *while still staging the file*, so never chain it with `&&`:

```bash
git add .pi/SPEC.md .pi/ARCHIVE.md AGENTS.md
git status --short
git commit -m "docs: record the role visibility contract and its rationale"
```

- [ ] **Step 5: Full verification before opening the PR**

```bash
cd frontend && yarn test:run
cd /home/frappe/frappe-bench && bench --site test_site purge-jobs
bench --site test_site run-tests --app crm
```

Then **restore the bench symlink** if you re-pointed it in the Prerequisites:

```bash
ln -sfn /workspace apps/crm
```

Report the actual counts from the output. Do not claim a suite passes without the output in front of you.

---

## Self-review

**Spec coverage.** §1 Data access → Tasks 3, 4, 7. §2 Surface visibility → Tasks 5, 6, 7. Narrowing invariant → Task 3 Step 1 (executable) and Task 5 (`editableBy`, `isAtFloor`), composed in Task 7. Storage and permissions → Task 2. Write path and the manager rule → Task 3. Surface registry → Task 5. Read path and load ordering → Task 6. Out-of-tree manager → Task 4. New-install default → Task 4. UI → Task 7. Testing → Tasks 2-5 inline, plus Task 8 Step 5. The two audit fixes → Task 1. Out-of-scope items stay out.

**One spec item deliberately deferred:** the spec's Files table lists `frontend/src/stores/users.js` for dropping `isSalesUser` — that is Task 1, ahead of the feature, not with it.

**Type consistency.** Three bugs found and fixed in this pass: the pane read
`dataAccess.doc?.` in the template where `createResource` exposes `.data` (only
`createDocumentResource` has `.doc`), and it imported `createDocumentResource`
and `MANAGER_ROLE` without using either, which eslint fails on.
 `hidden` is `list[str]` server-side and `Array<string>` client-side throughout. `matrix` is `dict[str, list[str]] | None` in Task 3 and read as `access.matrix?.[role] || []` in Task 7. `canSee(key, hidden)` in Task 5 is wrapped as `canSee(key)` by the store in Task 6 and only ever called that way in Task 7. `CONFIGURABLE_ROLES` is `("Sales Manager", "Sales User")` in Python and `[MANAGER_ROLE, REP_ROLE]` in JS — same two values, same order. `manager_outside_hierarchy` takes exactly `"All records"` / `"Own records only"` in the JSON options, `MANAGER_SCOPES`, and `managerScopeOptions`.

