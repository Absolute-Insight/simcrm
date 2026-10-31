# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep can read and edit their own profile without a grant on the User doctype.

frappe's User doctype is readable by System Manager only, so Settings -> Profile
and -> Preferences, which loaded the row through ``frappe.client.get``, answered
403 for every Sales User and rendered blank. The endpoints under test are the
caller's own row through a fixed field list, and nothing else.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.password import check_password, update_password

from crm.api.user import change_password, get_profile, update_profile

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
		frappe.db.set_value(
			"User", REP, {"first_name": "Profile Rep", "last_name": None}, update_modified=False
		)
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


class OwnProfileEmailTest(IntegrationTestCase):
	"""The composer and the signature pane read the same row through the same door."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(REP, "Profile Rep")

	def tearDown(self):
		frappe.set_user("Administrator")
		doc = frappe.get_doc("User", REP)
		doc.email_signature = None
		doc.set("user_emails", [])
		doc.save(ignore_permissions=True)
		super().tearDown()

	def test_signature_and_linked_accounts_round_trip(self):
		frappe.set_user(REP)
		profile = update_profile({"email_signature": "<p>Kind regards</p>"})
		self.assertEqual(profile["email_signature"], "<p>Kind regards</p>")
		self.assertEqual(profile["user_emails"], [])

	def test_a_rep_cannot_link_another_users_mailbox(self):
		"""These rows are what the composer offers as From, and this endpoint
		saves with ignore_permissions -- so without this a rep could advertise
		a colleague's mailbox as one of their own sender addresses."""
		ensure_rep(OTHER, "Profile Other")
		theirs = frappe.db.get_value("Email Account", {"email_id": OTHER})
		if not theirs:
			theirs = (
				frappe.get_doc(
					{
						"doctype": "Email Account",
						"email_account_name": "Profile Other Desk",
						"email_id": OTHER,
						"enable_outgoing": 1,
						"smtp_server": "smtp.example.com",
						"login_id_is_different": 0,
						"password": "x",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			update_profile({"user_emails": [{"email_account": theirs, "email_id": OTHER}]})
		self.assertEqual(get_profile()["user_emails"], [])

	def test_an_account_that_does_not_exist_is_refused_by_the_link(self):
		frappe.set_user(REP)
		with self.assertRaises(frappe.ValidationError):
			update_profile(
				{"user_emails": [{"email_account": "No Such Account", "email_id": "x@example.com"}]}
			)

	def shared_mailbox(self):
		"""An outgoing account on an address no user answers to -- sales@, in
		effect. Linkable by anyone, which is what those accounts are for."""
		address = "shared-desk@crmtest.test"
		name = frappe.db.get_value("Email Account", {"email_id": address})
		if name:
			return frappe.get_doc("Email Account", name)
		return frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": "Shared Desk",
				"email_id": address,
				"enable_outgoing": 1,
				"smtp_server": "smtp.example.com",
				"login_id_is_different": 0,
				"password": "x",
			}
		).insert(ignore_permissions=True)

	def test_extra_row_fields_are_dropped_not_written(self):
		# A shared mailbox, deliberately: an account whose address belongs to
		# another user is refused outright (see the test below), and the
		# fixture accounts on a stock site are exactly that.
		account = self.shared_mailbox()
		frappe.set_user(REP)
		profile = update_profile(
			{
				"user_emails": [
					{"email_account": account.name, "email_id": account.email_id, "parenttype": "Role"}
				]
			}
		)
		self.assertEqual(
			profile["user_emails"],
			[{"email_account": account.name, "email_id": account.email_id, "enable_outgoing": 1}],
		)

	def test_the_composer_learns_which_linked_accounts_can_send(self):
		"""EmailEditor filters its From list on this field, so a profile without it
		offers no accounts at all, and a stale one offers an account that cannot send.
		frappe keeps the row's own copy current only for an account that is a user's
		address, which a shared mailbox is not."""
		account = self.shared_mailbox()
		self.addCleanup(frappe.db.set_value, "Email Account", account.name, "enable_outgoing", 1)
		frappe.set_user(REP)
		update_profile({"user_emails": [{"email_account": account.name, "email_id": account.email_id}]})
		self.assertEqual(get_profile()["user_emails"][0]["enable_outgoing"], 1)

		frappe.set_user("Administrator")
		account.reload()
		account.enable_outgoing = 0
		account.save(ignore_permissions=True)

		frappe.set_user(REP)
		self.assertEqual(get_profile()["user_emails"][0]["enable_outgoing"], 0)


class ChangePasswordTest(IntegrationTestCase):
	"""Settings -> Change Password, against the site's password policy.

	With the policy off frappe's strength check answers ``{}`` -- no verdict --
	and that was read as a failed one, so every new password was "too weak".
	"""

	OLD = "Old-pass-for-profile-rep-91"
	NEW = "Brand-new-profile-rep-pass-47"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(REP, "Profile Rep")
		update_password(REP, self.OLD, logout_all_sessions=False)
		self.addCleanup(frappe.set_user, "Administrator")

	def policy(self, enabled: int, minimum_score: int = 2):
		real = frappe.get_system_settings
		settings = {"enable_password_policy": enabled, "minimum_password_score": minimum_score}
		return patch(
			"frappe.get_system_settings",
			side_effect=lambda key: settings[key] if key in settings else real(key),
		)

	def test_a_password_is_changed_when_the_policy_is_off(self):
		frappe.set_user(REP)
		with self.policy(enabled=0):
			change_password(self.OLD, self.NEW)
		self.assertEqual(check_password(REP, self.NEW), REP)

	def test_a_blank_password_is_refused_when_the_policy_is_off(self):
		frappe.set_user(REP)
		with self.policy(enabled=0), self.assertRaises(frappe.ValidationError):
			change_password(self.OLD, "")
		self.assertEqual(check_password(REP, self.OLD), REP)

	def test_a_weak_password_is_still_refused_when_the_policy_is_on(self):
		frappe.set_user(REP)
		with self.policy(enabled=1, minimum_score=4), self.assertRaises(frappe.ValidationError):
			change_password(self.OLD, "abc")
		self.assertEqual(check_password(REP, self.OLD), REP)
