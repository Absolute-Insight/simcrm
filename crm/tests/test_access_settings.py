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
	if frappe.db.exists("User", email):
		user = frappe.get_doc("User", email)
	else:
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	# Outside the branch above so a pre-existing user still gets any role this
	# call asks for -- a fixture whose roles only apply on first creation is
	# order-dependent on which test class happens to run (and so create the
	# user) first, and silently stops meaning what its call site says.
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

	def test_saving_an_unconfigurable_role_is_rejected(self):
		"""``reject_unconfigurable_roles`` is the only thing standing between the
		desk form and an admin locking themselves out of this pane. Task 3's own
		guard runs in the endpoint before it ever calls save(), so this is the one
		test in the whole plan that can catch the doctype-level check going
		silently missing -- asserting the specific message, not just that
		*something* raised, because frappe's own Select validation could also
		reject "System Manager" and produce a false pass."""
		settings = frappe.get_single("CRM Access Settings")
		self.addCleanup(self._forget_hidden_surfaces, ("System Manager", "diagnostic.probe"))
		settings.append("hidden_surfaces", {"role": "System Manager", "surface": "diagnostic.probe"})
		with self.assertRaises(frappe.ValidationError) as ctx:
			settings.save(ignore_permissions=True)
		self.assertIn("is not a configurable role", str(ctx.exception))

	def test_duplicate_hidden_surface_rows_are_dropped_keeping_the_first(self):
		"""``drop_duplicate_rows`` must keep the first occurrence and preserve
		order -- a table that silently kept the second copy, or reordered rows,
		would still look deduplicated at a glance."""
		settings = frappe.get_single("CRM Access Settings")
		self.addCleanup(
			self._forget_hidden_surfaces, ("Sales User", "nav.notes"), ("Sales User", "nav.tasks")
		)
		settings.append("hidden_surfaces", {"role": "Sales User", "surface": "nav.notes"})
		settings.append("hidden_surfaces", {"role": "Sales User", "surface": "nav.notes"})
		settings.append("hidden_surfaces", {"role": "Sales User", "surface": "nav.tasks"})
		settings.save(ignore_permissions=True)

		# order_by is load-bearing: CRM Role Surface's own sort_field/sort_order
		# is ("creation", "DESC"), so an unordered fetch silently returns rows
		# newest-first instead of in child-table (idx) order -- which is exactly
		# the order this test exists to check.
		rows = frappe.get_all(
			"CRM Role Surface",
			filters={"parenttype": "CRM Access Settings", "parentfield": "hidden_surfaces"},
			fields=["role", "surface"],
			order_by="idx asc",
		)
		self.assertEqual(
			[(row.role, row.surface) for row in rows],
			[("Sales User", "nav.notes"), ("Sales User", "nav.tasks")],
		)

	def _forget_hidden_surfaces(self, *pairs):
		"""Remove exactly the (role, surface) pairs a test added, by value --
		not a blanket wipe of hidden_surfaces, which would risk clobbering a
		peer session's own rows on this shared Single."""
		settings = frappe.get_single("CRM Access Settings")
		settings.hidden_surfaces = [
			row for row in settings.hidden_surfaces if (row.role, row.surface) not in pairs
		]
		settings.save(ignore_permissions=True)


class AccessApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		# crm.api.user.update_user_role grants System Manager promotions all
		# three roles, and Sales Manager promotions both sales roles -- a
		# single-role System Manager is not a shape the product creates, so a
		# fixture that made one was exercising a user this app never produces.
		ensure_user(ADMIN, "Access Admin", "System Manager", "Sales Manager", "Sales User")
		ensure_user(MANAGER, "Access Manager", "Sales Manager", "Sales User")
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

	def test_a_bare_system_manager_can_still_read_visibility(self):
		"""A user holding only System Manager -- reachable via
		``bench add-system-manager`` or the desk, not through this product's own
		``update_user_role`` -- is still admitted to the CRM by
		``crm.api.session.get_session_role_flags``. ``get_visibility`` gates the
		shell's own chrome and the pane an administrator would use to fix their
		access, so it must not be the thing that locks such an administrator out.
		Distinct email from ``ADMIN``, which now carries all three roles."""
		from crm.api.access import get_visibility

		email = "access-bare-system-manager@crmtest.test"
		ensure_user(email, "Bare System Manager", "System Manager")
		frappe.set_user(email)
		payload = get_visibility()
		self.assertEqual(payload["role"], "System Manager")
		self.assertEqual(payload["hidden"], [])

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
		# assertRaisesRegex, not assertRaises: attributes the failure to
		# frappe.only_for's own message specifically, rather than to any
		# PermissionError raised anywhere earlier in the call path.
		with self.assertRaisesRegex(frappe.PermissionError, "only allowed for"):
			ask_analyst("what is my pipeline worth")

	# --- data access ----------------------------------------------------

	def test_a_manager_cannot_change_data_access(self):
		from crm.api.access import set_data_access

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			set_data_access(enable_sales_hierarchy=1)

	def test_a_rep_cannot_read_data_access(self):
		"""get_data_access was narrowed to System Manager and Sales Manager, but
		nothing asserted that a plain Sales User is refused. Its sibling
		get_visibility has exactly this kind of edge covered (see
		test_a_bare_system_manager_can_still_read_visibility, the other
		direction); without this test, a future re-widening of get_data_access's
		frappe.only_for list would go uncaught."""
		from crm.api.access import get_data_access

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			get_data_access()

	def test_an_admin_can_change_data_access(self):
		from crm.api.access import get_data_access, set_data_access

		frappe.set_user(ADMIN)
		before = get_data_access()
		self.addCleanup(
			set_data_access,
			before["enable_sales_hierarchy"],
			before["manager_outside_hierarchy"],
		)
		result = set_data_access(enable_sales_hierarchy=1, manager_outside_hierarchy="Own records only")
		self.assertEqual(result["enable_sales_hierarchy"], 1)
		self.assertEqual(result["manager_outside_hierarchy"], "Own records only")

	def test_an_unknown_data_access_value_is_refused(self):
		from crm.api.access import set_data_access

		frappe.set_user(ADMIN)
		with self.assertRaises(frappe.ValidationError):
			set_data_access(manager_outside_hierarchy="Everything")


class InstallDefaultsTest(IntegrationTestCase):
	"""A new install starts scoped; an existing one is never touched."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.saved_hierarchy = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.saved_scope = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", self.saved_hierarchy or 0)
		frappe.db.set_single_value(
			"CRM Access Settings", "manager_outside_hierarchy", self.saved_scope or "All records"
		)

	def test_ensure_access_defaults_scopes_a_fresh_site(self):
		"""A fresh site has no row in Singles for either field at all -- not a
		falsy stored value. A Check field with no row also casts to 0
		(``frappe.utils.cast``), so setting the field to 0 and deleting its row
		are different states that must not be conflated."""
		from crm.install import ensure_access_defaults

		frappe.db.delete("Singles", {"doctype": "FCRM Settings", "field": "enable_sales_hierarchy"})
		frappe.db.delete("Singles", {"doctype": "CRM Access Settings", "field": "manager_outside_hierarchy"})

		ensure_access_defaults()

		self.assertEqual(frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy"), 1)
		self.assertEqual(
			frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy"),
			"Own records only",
		)

	def test_ensure_access_defaults_leaves_a_configured_site_alone(self):
		"""First-run only: once a row exists -- even one that happens to match
		what used to be the only behaviour -- an administrator's choice stands.
		This is exactly the shape FCRMSettings.restore_defaults produces on an
		existing site, since it calls after_install."""
		from crm.install import ensure_access_defaults

		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")

		ensure_access_defaults()

		self.assertEqual(frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy"), 0)
		self.assertEqual(
			frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy"),
			"All records",
		)
