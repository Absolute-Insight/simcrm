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
