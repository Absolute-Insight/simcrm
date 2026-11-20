# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep must not read a colleague's User row: last sign-in time and IP, phone,
birth date. See ``crm.permissions.users`` for why the right is withdrawn rather
than the columns hidden."""

from __future__ import annotations

import frappe
from frappe.client import get_count
from frappe.desk.search import search_link
from frappe.tests import IntegrationTestCase

from crm.permissions.users import close_user_select, user_link_query

REP = "signin-rep@crmtest.test"
COLLEAGUE = "signin-colleague@crmtest.test"
ADMIN = "signin-admin@crmtest.test"
WEBSITE = "signin-website@crmtest.test"
SIGN_IN = {
	"last_login": "2026-11-20 09:00:00",
	"last_ip": "203.0.113.7",
	"last_active": "2026-11-20 09:05:00",
}


def ensure_user(email: str, *roles: str, user_type: str | None = None) -> None:
	if not frappe.db.exists("User", email):
		doc = {"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		if user_type:
			doc["user_type"] = user_type
		frappe.get_doc(doc).insert(ignore_permissions=True)
	if roles:
		frappe.get_doc("User", email).add_roles(*roles)


def pick(txt: str = "", filters=None):
	"""The picker query itself. search_link turns its refusal into an empty answer
	outside developer mode, which would pass these tests for the wrong reason."""
	return user_link_query("User", txt, "name", 0, 20, filters)


class UserSignInFieldsTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		close_user_select()
		ensure_user(REP, "Sales User")
		ensure_user(ADMIN, "System Manager")
		ensure_user(COLLEAGUE, "Sales User")
		ensure_user(WEBSITE, user_type="Website User")
		frappe.db.set_value("User", COLLEAGUE, SIGN_IN, update_modified=False)

	def tearDown(self):
		frappe.set_user("Administrator")
		super().tearDown()

	def test_a_rep_lists_only_their_own_row(self):
		# frappe shares each user's own User row with them, so that one stays readable
		frappe.set_user(REP)
		rows = frappe.get_list("User", fields=["name", *SIGN_IN], limit=0)
		self.assertEqual([row.name for row in rows], [REP])
		self.assertEqual(frappe.get_list("User", filters={"name": COLLEAGUE}), [])

	def test_a_rep_cannot_probe_an_address_through_a_filter(self):
		frappe.set_user(REP)
		self.assertEqual(frappe.get_list("User", filters={"last_ip": SIGN_IN["last_ip"]}), [])
		self.assertEqual(get_count("User", filters={"last_ip": SIGN_IN["last_ip"]}), 0)
		with self.assertRaises(frappe.PermissionError):
			pick(filters={"last_ip": SIGN_IN["last_ip"]})
		with self.assertRaises(frappe.PermissionError):
			pick(filters=[["User", "last_ip", "like", "203.%"]])

	def test_the_user_picker_still_finds_a_colleague_by_name(self):
		frappe.set_user(REP)
		found = search_link("User", "signin-colleague")
		self.assertEqual([row["value"] for row in found], [COLLEAGUE])
		self.assertNotIn(SIGN_IN["last_ip"], frappe.as_json(found))

	def test_the_picker_takes_the_filters_the_app_sends(self):
		frappe.set_user(REP)
		found = search_link("User", "signin-", filters=[["User", "user_type", "=", "System User"]])
		self.assertIn(COLLEAGUE, [row["value"] for row in found])
		found = search_link("User", "signin-", filters={"name": ["in", [COLLEAGUE]]})
		self.assertEqual([row["value"] for row in found], [COLLEAGUE])

	def test_the_picker_leaves_out_website_users_and_disabled_accounts(self):
		frappe.set_user(REP)
		found = [row["value"] for row in search_link("User", "signin-")]
		self.assertNotIn(WEBSITE, found)
		frappe.set_user("Administrator")
		frappe.db.set_value("User", COLLEAGUE, "enabled", 0)
		try:
			frappe.set_user(REP)
			self.assertNotIn(COLLEAGUE, [row["value"] for row in search_link("User", "signin-")])
		finally:
			frappe.set_user("Administrator")
			frappe.db.set_value("User", COLLEAGUE, "enabled", 1)

	def test_a_website_user_cannot_use_the_picker(self):
		frappe.set_user(WEBSITE)
		with self.assertRaises(frappe.PermissionError):
			pick("signin-")

	def test_a_system_manager_still_reads_the_sign_in_details(self):
		frappe.set_user(ADMIN)
		row = frappe.get_list("User", fields=["name", *SIGN_IN], filters={"name": COLLEAGUE})[0]
		self.assertEqual(row.last_ip, SIGN_IN["last_ip"])
		self.assertTrue(row.last_login and row.last_active)

	def test_running_it_again_changes_nothing(self):
		before = frappe.get_all("Custom DocPerm", filters={"parent": "User"}, fields=["role", "permlevel"])
		close_user_select()
		after = frappe.get_all("Custom DocPerm", filters={"parent": "User"}, fields=["role", "permlevel"])
		self.assertEqual(
			sorted(map(tuple, (r.values() for r in before))), sorted(map(tuple, (r.values() for r in after)))
		)
		self.assertNotIn("Desk User", [r.role for r in after])
		self.assertIn("System Manager", [r.role for r in after])
