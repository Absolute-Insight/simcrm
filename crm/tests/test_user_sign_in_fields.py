# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep must not read a colleague's User row: last sign-in time and IP, phone,
birth date. See ``crm.permissions.users`` for why the right is withdrawn rather
than the columns hidden."""

from __future__ import annotations

from types import SimpleNamespace

import frappe
from frappe.client import get_count
from frappe.desk.search import search_link
from frappe.tests import IntegrationTestCase

from crm.permissions.users import (
	MAX_PAGE_LENGTH,
	close_user_select,
	refuse_sign_in_field_queries,
	restore_user_select,
	user_link_query,
)

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


def pick(txt: str = "", filters=None, page_len: int = 20):
	"""The picker query itself. search_link turns its refusal into an empty answer
	outside developer mode, which would pass these tests for the wrong reason."""
	return user_link_query("User", txt, "name", 0, page_len, filters)


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

	def test_no_filter_shape_reaches_a_column_outside_the_allowlist(self):
		# found in review: a five-element row was checked on [1] and queried on [-3:]
		frappe.set_user(REP)
		smuggled = [
			[["x", "name", "last_ip", "like", "203.%"]],
			[["x", "name", "roles.role", "=", "System Manager"]],
			[["Has Role", "name", "like", "%"]],
			[["roles.role", "=", "System Manager"]],
			[["`tabUser`.`last_ip`", "like", "203.%"]],
			[["name"]],
			["last_ip"],
			{"name": ["like", "%", "extra"]},
			{"name": ["is", "set"]},
			{"name": "x", "last_ip": "203.0.113.7"},
			{"roles.role": "System Manager"},
		]
		for filters in smuggled:
			with self.subTest(filters=filters), self.assertRaises(frappe.PermissionError):
				pick(filters=filters)

	def test_the_picker_returns_one_page_at_most(self):
		frappe.set_user(REP)
		self.assertLessEqual(len(pick(page_len=0)), MAX_PAGE_LENGTH)
		self.assertEqual(len(pick("signin-", page_len=1)), 1)

	def test_uninstall_gives_the_desk_user_rule_back_and_migrate_takes_it_again(self):
		restore_user_select()
		rule = {"parent": "User", "role": "Desk User", "permlevel": 0}
		self.assertTrue(frappe.db.exists("Custom DocPerm", rule))
		self.assertEqual(frappe.db.get_value("Custom DocPerm", rule, "select"), 1)
		close_user_select()
		self.assertFalse(frappe.db.exists("Custom DocPerm", rule))

	def test_a_site_with_its_own_user_rules_keeps_them(self):
		# an admin's Role Permission Manager rows: the copy is skipped, only Desk User goes
		extra = frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "User",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": "Sales Manager",
				"permlevel": 0,
				"read": 1,
			}
		).insert(ignore_permissions=True)
		restore_user_select()
		close_user_select()
		self.assertTrue(frappe.db.exists("Custom DocPerm", extra.name))
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": "User", "role": "Desk User"}))

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
		fields = ["role", "permlevel", "select", "read", "write", "create", "delete"]
		before = frappe.get_all("Custom DocPerm", filters={"parent": "User"}, fields=fields)
		close_user_select()
		after = frappe.get_all("Custom DocPerm", filters={"parent": "User"}, fields=fields)
		self.assertEqual(
			sorted(map(tuple, (r.values() for r in before))), sorted(map(tuple, (r.values() for r in after)))
		)
		self.assertNotIn("Desk User", [r.role for r in after])
		self.assertIn(("System Manager", 0), [(r.role, r.permlevel) for r in after])
		self.assertIn(("System Manager", 1), [(r.role, r.permlevel) for r in after])


class SignInFieldGuardTest(IntegrationTestCase):
	"""The joins no permission rule reaches: any doctype with a Link to User."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_user(REP, "Sales User")
		ensure_user(ADMIN, "System Manager")
		ensure_user(COLLEAGUE, "Sales Manager")

	def setUp(self):
		super().setUp()
		self._request = getattr(frappe.local, "request", None)
		self._form_dict = frappe.local.form_dict

	def tearDown(self):
		frappe.local.request = self._request
		frappe.local.form_dict = self._form_dict
		frappe.set_user("Administrator")
		super().tearDown()

	def call(self, user: str, path: str = "/api/method/frappe.client.get_list", **form):
		frappe.set_user(user)
		frappe.local.request = SimpleNamespace(path=path)
		frappe.local.form_dict = frappe._dict(form)
		refuse_sign_in_field_queries()

	def test_a_rep_cannot_join_to_a_colleagues_sign_in_fields(self):
		for form in (
			{"doctype": "ToDo", "fields": '["name", "assigned_by.last_ip"]'},
			{"doctype": "ToDo", "fields": ["name", "assigned_by.LAST_LOGIN"]},
			{"doctype": "CRM Deal", "filters": '[["deal_owner.last_active", ">", "2026-01-01"]]'},
			{"doctype": "CRM Deal", "filters": {"deal_owner.last_ip": ["like", "198.%"]}},
			{"doctype": "CRM Deal", "order_by": "`tabUser`.`last_ip` desc"},
			{"doctype": "User", "fieldname": "last_ip", "filters": COLLEAGUE},
		):
			with self.subTest(form=form), self.assertRaises(frappe.PermissionError):
				self.call(REP, **form)

	def test_json_escapes_do_not_hide_a_sign_in_field(self):
		# found in review: frappe decodes these strings after the hook, so \\u005f was
		# "_" by the time the query ran
		for form in (
			{"doctype": "ToDo", "fields": '["name", "assigned_by.last\\u005fip"]'},
			{"doctype": "ToDo", "fields": '["assigned_by.\\u006cast_login"]'},
			{"doctype": "CRM Deal", "filters": '[["deal_owner.last\\u005factive", ">", "2026-01-01"]]'},
			{"doctype": "CRM Deal", "filters": {"x": '["deal_owner.last\\u005fip"]'}},
			{"doctype": "ToDo", "fields": '"[\\"assigned_by.last\\\\u005fip\\"]"'},
		):
			with self.subTest(form=form), self.assertRaises(frappe.PermissionError):
				self.call(REP, **form)

	def test_the_guard_covers_every_api_route(self):
		for path in (
			"/api/resource/ToDo",
			"/api/v2/method/frappe.client.get_list",
			"/api/method/crm.api.doc.get_data",
		):
			with self.subTest(path=path), self.assertRaises(frappe.PermissionError):
				self.call(REP, path, fields='["assigned_by.last_ip"]')

	def test_ordinary_requests_and_lookalike_names_pass(self):
		self.call(REP, doctype="ToDo", fields='["name", "assigned_by", "last_name", "last_login_hint"]')
		self.call(REP, "/crm/deals", fields="last_ip")  # a page, not the API

	def test_a_system_manager_may_still_ask(self):
		self.call(ADMIN, doctype="ToDo", fields='["assigned_by.last_ip"]')

	def test_with_select_withdrawn_a_join_reaches_no_colleague(self):
		"""close_user_select already stops the join: a rep reads User only through the
		share of their own row, and frappe holds the joined row to that too. The guard
		is for a site where a role holds select or read on User again."""
		close_user_select()
		frappe.db.set_value("User", COLLEAGUE, SIGN_IN, update_modified=False)
		todo = frappe.get_doc(
			{"doctype": "ToDo", "description": "sign-in guard", "allocated_to": REP, "assigned_by": COLLEAGUE}
		).insert(ignore_permissions=True)
		frappe.set_user(REP)
		rows = frappe.get_list("ToDo", fields=["name", "assigned_by.last_ip"], filters={"name": todo.name})
		self.assertIsNone(rows[0].last_ip)
		probe = [["assigned_by.last_ip", "like", "203.%"], ["name", "=", todo.name]]
		self.assertEqual(frappe.get_list("ToDo", filters=probe), [])
