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
