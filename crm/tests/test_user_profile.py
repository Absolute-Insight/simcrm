# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep can read and edit their own profile without a grant on the User doctype.

frappe's User doctype is readable by System Manager only, so Settings -> Profile
and -> Preferences, which loaded the row through ``frappe.client.get``, answered
403 for every Sales User and rendered blank. The endpoints under test are the
caller's own row through a fixed field list, and nothing else.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.user import get_profile, update_profile

REP = "profile-rep@crmtest.test"
OTHER = "profile-other@crmtest.test"


def ensure_rep(email: str, name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class OwnProfileTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(REP, "Profile Rep")
		ensure_rep(OTHER, "Profile Other")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("User", REP, {"first_name": "Profile Rep", "last_name": None}, update_modified=False)
		super().tearDown()

	def test_a_rep_reads_their_own_profile(self):
		frappe.set_user(REP)
		profile = get_profile()
		self.assertEqual(profile["email"], REP)
		self.assertEqual(profile["first_name"], "Profile Rep")
		self.assertIn("language", profile)
		self.assertNotIn("roles", profile)

	def test_a_rep_changes_their_name_and_nothing_else(self):
		frappe.set_user(REP)
		profile = update_profile({"first_name": "Renamed", "last_name": "Rep"})
		self.assertEqual(profile["full_name"], "Renamed Rep")
		self.assertEqual(frappe.db.get_value("User", REP, "first_name"), "Renamed")

		with self.assertRaises(frappe.ValidationError):
			update_profile({"email": "someone-else@example.com"})
		with self.assertRaises(frappe.ValidationError):
			update_profile({"roles": [{"role": "System Manager"}]})
		with self.assertRaises(frappe.ValidationError):
			update_profile({"enabled": 0})

	def test_the_endpoints_only_ever_touch_the_callers_row(self):
		frappe.set_user(REP)
		update_profile({"first_name": "Only Me"})
		self.assertEqual(frappe.db.get_value("User", OTHER, "first_name"), "Profile Other")
		self.assertEqual(get_profile()["name"], REP)

	def test_guests_are_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			get_profile()
		with self.assertRaises(frappe.AuthenticationError):
			update_profile({"first_name": "x"})
