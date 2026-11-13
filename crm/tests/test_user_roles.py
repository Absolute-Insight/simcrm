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
PEERS_REP = "adminonly-peers-rep@crmtest.test"
NEWCOMER = "adminonly-newcomer@crmtest.test"


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
		ensure_user(PEERS_REP, "Peer's Rep", "Sales User")
		ensure_user(NEWCOMER, "Newcomer")
		self.addCleanup(frappe.set_user, "Administrator")

	def make_teams(self):
		"""MANAGER over REP, PEER over PEERS_REP: two teams, as the subtree rule needs."""
		was_enabled = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.addCleanup(
			frappe.db.set_single_value, "FCRM Settings", "enable_sales_hierarchy", was_enabled or 0
		)
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		people = [MANAGER, REP, PEER, PEERS_REP]
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", people)})
		self.addCleanup(frappe.db.delete, "CRM Sales Hierarchy", {"user": ("in", people)})
		for manager, rep in ((MANAGER, REP), (PEER, PEERS_REP)):
			top = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": manager}).insert(
				ignore_permissions=True
			)
			frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": rep, "reports_to": top.name}).insert(
				ignore_permissions=True
			)

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

	def test_a_sales_manager_cannot_offboard_another_managers_rep(self):
		"""The subtree every read in the app is scoped to. Removing the rep also
		deletes their hierarchy node, which Sales Manager may otherwise only read."""
		from crm.api.user import remove_crm_roles_from_user

		self.make_teams()
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			remove_crm_roles_from_user(PEERS_REP)
		frappe.set_user("Administrator")
		self.assertEqual(self.roles_of(PEERS_REP), {"Sales User"})
		self.assertTrue(frappe.db.exists("CRM Sales Hierarchy", {"user": PEERS_REP}))

	def test_a_sales_manager_cannot_change_another_managers_reps_role(self):
		from crm.api.user import update_user_role

		self.make_teams()
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			update_user_role(PEERS_REP, "Sales User")

	def test_a_sales_manager_still_brings_a_new_account_into_the_crm(self):
		"""An account with no CRM role is on nobody's team yet: adding it is onboarding."""
		from crm.api.user import add_existing_users

		frappe.db.delete("Has Role", {"parent": NEWCOMER, "role": ("in", ["Sales User", "Sales Manager"])})
		frappe.clear_cache(user=NEWCOMER)
		frappe.set_user(MANAGER)
		add_existing_users([NEWCOMER], "Sales User")
		frappe.set_user("Administrator")
		self.assertEqual(self.roles_of(NEWCOMER), {"Sales User"})

	def test_a_sales_manager_still_manages_reps(self):
		from crm.api.user import remove_crm_roles_from_user, update_user_role

		self.make_teams()
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


class StandardUserRoleChangeTest(IntegrationTestCase):
	"""Administrator and Guest are refused by name, not by what their Has Role
	rows happen to hold: Administrator's need not include System Manager."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(MANAGER, "Manager", "Sales Manager", "Sales User")
		self.addCleanup(frappe.set_user, "Administrator")
		# the install the guard used to depend on not existing
		frappe.db.delete(
			"Has Role", {"parent": "Administrator", "parenttype": "User", "role": "System Manager"}
		)
		frappe.clear_cache(user="Administrator")

	def administrator_state(self) -> tuple[set[str], int]:
		roles = set(
			frappe.db.get_all("Has Role", {"parent": "Administrator", "parenttype": "User"}, pluck="role")
		)
		blocked = frappe.db.count("Block Module", {"parent": "Administrator", "parenttype": "User"})
		return roles, blocked

	def test_a_sales_manager_cannot_change_the_administrators_role(self):
		from crm.api.user import add_existing_users, update_user_role

		before = self.administrator_state()
		frappe.set_user(MANAGER)
		for new_role in ("Sales User", "Sales Manager", "System Manager"):
			with self.subTest(new_role=new_role), self.assertRaises(frappe.PermissionError):
				update_user_role("Administrator", new_role)
		with self.assertRaises(frappe.PermissionError):
			add_existing_users(["Administrator"], "Sales User")
		frappe.set_user("Administrator")
		self.assertEqual(self.administrator_state(), before)

	def test_a_sales_manager_cannot_offboard_the_administrator(self):
		from crm.api.user import remove_crm_roles_from_user

		before = self.administrator_state()
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			remove_crm_roles_from_user("Administrator")
		frappe.set_user("Administrator")
		self.assertEqual(self.administrator_state(), before)

	def test_guest_is_refused_too(self):
		from crm.api.user import remove_crm_roles_from_user, update_user_role

		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			update_user_role("Guest", "Sales User")
		with self.assertRaises(frappe.PermissionError):
			remove_crm_roles_from_user("Guest")

	def test_a_system_manager_is_refused_as_well(self):
		"""frappe lets only Administrator edit a standard user; these endpoints
		save past that rule, so they do not offer it to anyone."""
		from crm.api.user import update_user_role

		with self.assertRaises(frappe.PermissionError):
			update_user_role("Administrator", "Sales User")

	def test_a_differently_spelled_name_is_the_same_account(self):
		"""``frappe.get_doc("User", "administrator")`` loads Administrator: the
		database ignores case and trailing spaces, so the guard must as well."""
		from crm.api.user import add_existing_users, remove_crm_roles_from_user, update_user_role

		before = self.administrator_state()
		frappe.set_user(MANAGER)
		for name in ("administrator", "ADMINISTRATOR", "Administrator ", "guest"):
			with self.subTest(name=name):
				with self.assertRaises(frappe.PermissionError):
					update_user_role(name, "Sales User")
				with self.assertRaises(frappe.PermissionError):
					remove_crm_roles_from_user(name)
				with self.assertRaises(frappe.PermissionError):
					add_existing_users([name], "Sales User")
		frappe.set_user("Administrator")
		self.assertEqual(self.administrator_state(), before)

	def test_nobody_removes_themselves_under_another_spelling(self):
		from crm.api.user import remove_crm_roles_from_user

		frappe.set_user(MANAGER)
		for name in (MANAGER.upper(), f"{MANAGER} "):
			with self.subTest(name=name), self.assertRaises(frappe.PermissionError):
				remove_crm_roles_from_user(name)
		frappe.set_user("Administrator")
		self.assertIn("Sales Manager", frappe.get_roles(MANAGER))

	def test_a_differently_spelled_rep_is_still_managed(self):
		"""The other direction: the name is resolved, not refused."""
		from crm.api.user import update_user_role

		ensure_user(PEER, "Peer", "Sales Manager", "Sales User")
		update_user_role(PEER.upper(), "Sales User")
		self.assertEqual(set(frappe.get_roles(PEER)) & {"Sales User", "Sales Manager"}, {"Sales User"})
