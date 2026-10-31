# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Renaming a user carries the rows that are named after them.

CRM Visit Target and CRM Telephony Agent are one row per user, named by the
user (autoname ``field:user``). ``rename_doc("User")`` rewrites their ``user``
Link but not their name, and everything looks them up by name -- so after a
rename the rep's target could no longer be changed or cleared, and their
telephony agent was no longer found.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.visit_targets import set_visit_target

OLD = "rename-old@crmtest.test"
NEW = "rename-new@crmtest.test"


class UserRenameTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email in (OLD, NEW):
			for doctype in ("CRM Visit Target", "CRM Telephony Agent"):
				frappe.db.delete(doctype, {"name": email})
			if frappe.db.exists("User", email):
				frappe.delete_doc("User", email, force=True, ignore_permissions=True)
		user = frappe.get_doc(
			{"doctype": "User", "email": OLD, "first_name": "Renamed", "send_welcome_email": 0}
		)
		user.append("roles", {"role": "Sales User"})
		user.insert(ignore_permissions=True)
		self.addCleanup(frappe.db.rollback)

	def rename(self):
		frappe.rename_doc("User", OLD, NEW, show_alert=False, rebuild_search=False)

	def test_a_renamed_reps_visit_target_can_still_be_changed_and_cleared(self):
		set_visit_target(OLD, 10)
		self.rename()

		self.assertEqual(frappe.db.get_value("CRM Visit Target", NEW, "visits_per_week"), 10)
		set_visit_target(NEW, 12)
		self.assertEqual(
			frappe.get_all("CRM Visit Target", filters={"user": NEW}, fields=["name", "visits_per_week"]),
			[{"name": NEW, "visits_per_week": 12}],
		)
		set_visit_target(NEW, 0)
		self.assertFalse(frappe.get_all("CRM Visit Target", filters={"user": NEW}))

	def test_a_renamed_reps_telephony_agent_is_found_under_the_new_name(self):
		frappe.get_doc(
			{"doctype": "CRM Telephony Agent", "user": OLD, "twilio_number": "+15550000042"}
		).insert(ignore_permissions=True)
		self.rename()

		self.assertEqual(frappe.db.get_value("CRM Telephony Agent", NEW, "twilio_number"), "+15550000042")
		self.assertEqual(frappe.db.get_value("CRM Telephony Agent", NEW, "user"), NEW)
		self.assertFalse(frappe.db.exists("CRM Telephony Agent", OLD))

	def test_the_patch_renames_rows_an_earlier_rename_left_behind(self):
		from crm.patches.v1_0.rename_user_keyed_rows_after_user_renames import execute

		set_visit_target(OLD, 9)
		self.rename()
		# the state a rename left before the hook: the Link rewritten, the row not
		frappe.db.sql("UPDATE `tabCRM Visit Target` SET name = %s WHERE name = %s", (OLD, NEW))
		self.assertEqual(frappe.db.get_value("CRM Visit Target", OLD, "user"), NEW)

		execute()

		self.assertFalse(frappe.db.exists("CRM Visit Target", OLD))
		self.assertEqual(frappe.db.get_value("CRM Visit Target", NEW, ["user", "visits_per_week"]), (NEW, 9))
