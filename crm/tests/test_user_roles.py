# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Who may change whose CRM role through ``crm.api.user``."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

MANAGER = "adminonly-manager@crmtest.test"
PEER = "adminonly-peer@crmtest.test"
REP = "adminonly-rep@crmtest.test"


def ensure_user(email: str, name: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)


class ManagerRoleChangeTest(IntegrationTestCase):
	"""A Sales Manager manages reps. Peer managers are a System Manager's to
	promote, demote or remove -- the same rule that already governs *granting*
	Sales Manager."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(MANAGER, "Manager", "Sales Manager", "Sales User")
		ensure_user(PEER, "Peer", "Sales Manager", "Sales User")
		ensure_user(REP, "Rep", "Sales User")
		self.addCleanup(frappe.set_user, "Administrator")

	def roles_of(self, user: str) -> set[str]:
		return set(frappe.get_roles(user)) & {"Sales User", "Sales Manager", "System Manager"}

	def test_a_sales_manager_cannot_demote_a_peer_manager(self):
		from crm.api.user import update_user_role

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			update_user_role(PEER, "Sales User")
		frappe.set_user("Administrator")
		self.assertIn("Sales Manager", self.roles_of(PEER))

	def test_a_sales_manager_cannot_strip_a_peer_managers_crm_roles(self):
		from crm.api.user import remove_crm_roles_from_user

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			remove_crm_roles_from_user(PEER)
		frappe.set_user("Administrator")
		self.assertEqual(self.roles_of(PEER), {"Sales User", "Sales Manager"})

	def test_a_sales_manager_still_manages_reps(self):
		from crm.api.user import remove_crm_roles_from_user, update_user_role

		frappe.set_user(MANAGER)
		update_user_role(REP, "Sales User")
		remove_crm_roles_from_user(REP)
		frappe.set_user("Administrator")
		self.assertEqual(self.roles_of(REP), set())

	def test_a_system_manager_demotes_a_manager(self):
		from crm.api.user import update_user_role

		frappe.set_user("Administrator")
		update_user_role(PEER, "Sales User")
		self.assertEqual(self.roles_of(PEER), {"Sales User"})
