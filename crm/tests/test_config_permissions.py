# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pipeline configuration is read by reps and written by managers.

Deal Status probability and type feed the stage-probability signal, the weekly
forecast snapshot, lost-reason validation and every Won aggregate; the other
configuration doctypes name the options every record picks from. None of the
API endpoints gate them, so the doctype permissions are the only door: a rep
who could ``frappe.client.set_value`` a stage's probability to 100 the day
before the snapshot would overstate the site forecast permanently.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

REP = "configperm-rep@crmtest.test"
MANAGER = "configperm-manager@crmtest.test"

CONFIGURATION_DOCTYPES = (
	"CRM Deal Status",
	"CRM Lead Status",
	"CRM Lost Reason",
	"CRM Industry",
	"CRM Territory",
	"CRM Holiday List",
	"CRM Communication Status",
	"CRM Global Settings",
)


def ensure_user(email: str, name: str, role: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


class ConfigurationPermissionTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Config Rep", "Sales User")
		ensure_user(MANAGER, "Config Manager", "Sales Manager")
		self.addCleanup(frappe.set_user, "Administrator")
		self.stage = frappe.get_doc(
			{
				"doctype": "CRM Deal Status",
				"deal_status": "Config Perm Stage",
				"type": "Ongoing",
				"probability": 10,
				"color": "blue",
			}
		).insert(ignore_permissions=True, ignore_if_duplicate=True)
		frappe.db.set_value("CRM Deal Status", self.stage.name, "probability", 10)
		self.addCleanup(
			lambda: frappe.db.exists("CRM Deal Status", self.stage.name)
			and frappe.delete_doc("CRM Deal Status", self.stage.name, force=True, ignore_permissions=True)
		)

	def test_the_configuration_doctypes_give_a_sales_user_read_only(self):
		for doctype in CONFIGURATION_DOCTYPES:
			with self.subTest(doctype=doctype):
				perms = [p for p in frappe.get_meta(doctype).permissions if p.role == "Sales User"]
				self.assertTrue(perms, "Sales User lost read")
				self.assertTrue(perms[0].read)
				for ptype in ("write", "create", "delete"):
					self.assertFalse(perms[0].get(ptype), ptype)

	def test_a_rep_cannot_rewrite_a_stage_probability(self):
		frappe.set_user(REP)
		self.assertTrue(frappe.has_permission("CRM Deal Status", doc=self.stage.name, ptype="read"))
		self.assertFalse(frappe.has_permission("CRM Deal Status", doc=self.stage.name, ptype="write"))
		self.assertFalse(frappe.has_permission("CRM Deal Status", ptype="create"))
		with self.assertRaises(frappe.PermissionError):
			frappe.client.set_value("CRM Deal Status", self.stage.name, "probability", 100)
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Deal Status", self.stage.name, "probability"), 10)

	def test_a_sales_manager_still_maintains_the_pipeline(self):
		frappe.set_user(MANAGER)
		self.assertTrue(frappe.has_permission("CRM Deal Status", doc=self.stage.name, ptype="write"))
		frappe.client.set_value("CRM Deal Status", self.stage.name, "probability", 55)
		self.assertEqual(frappe.db.get_value("CRM Deal Status", self.stage.name, "probability"), 55)
