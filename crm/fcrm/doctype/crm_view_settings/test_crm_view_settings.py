# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_view_settings.crm_view_settings import create, public, set_as_default

REP = "viewsettings-rep@crmtest.test"
MANAGER = "viewsettings-manager@crmtest.test"
NOBODY = "viewsettings-nobody@crmtest.test"


def ensure_user(email: str, name: str, role: str | None) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		if role:
			user.add_roles(role)


class TestCRMViewSettings(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.savepoint("view_settings")
		self.addCleanup(frappe.db.rollback, save_point="view_settings")
		self.addCleanup(frappe.set_user, "Administrator")
		ensure_user(REP, "View Rep", "Sales User")
		ensure_user(MANAGER, "View Manager", "Sales Manager")
		ensure_user(NOBODY, "View Nobody", None)

	def test_a_view_cannot_be_created_on_a_doctype_the_caller_cannot_read(self):
		"""``create`` read the doctype's meta and default columns before anything
		checked whether the caller could read the doctype at all."""
		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			create({"doctype": "CRM Deal", "label": "Nobody's view", "type": "list"})
		self.assertFalse(frappe.db.exists("CRM View Settings", {"label": "Nobody's view"}))

	def test_a_manager_cannot_publish_another_users_private_view(self):
		"""``public`` used to check the role only, so any Sales Manager could turn
		a rep's private view into a shared one; it now applies the same owner rule
		as pin and update."""
		view = frappe.get_doc(
			{"doctype": "CRM View Settings", "label": "Rep's private view", "dt": "CRM Deal", "user": REP}
		).insert(ignore_permissions=True)
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.PermissionError):
			public(view.name, 1)
		self.assertFalse(frappe.db.get_value("CRM View Settings", view.name, "public"))

		frappe.set_user("Administrator")
		public(view.name, 1)
		self.assertTrue(frappe.db.get_value("CRM View Settings", view.name, "public"))

	def make_view(self, label, doctype, is_default=0):
		return frappe.get_doc(
			{
				"doctype": "CRM View Settings",
				"label": label,
				"dt": doctype,
				"type": "list",
				"user": "Administrator",
				"is_default": is_default,
			}
		).insert(ignore_permissions=True)

	def test_name_only_call_clears_previous_default_of_same_doctype(self):
		frappe.db.delete("CRM View Settings", {"user": "Administrator"})
		old = self.make_view("Old Leads", "CRM Lead", is_default=1)
		new = self.make_view("New Leads", "CRM Lead")

		set_as_default(name=new.name)

		self.assertEqual(frappe.db.get_value("CRM View Settings", new.name, "is_default"), 1)
		self.assertEqual(frappe.db.get_value("CRM View Settings", old.name, "is_default"), 0)

	def test_name_only_call_keeps_default_of_other_doctype(self):
		"""``set_as_default`` cleared ``is_default`` across every doctype, so
		making a Leads view the default silently dropped the Deals default."""
		frappe.db.delete("CRM View Settings", {"user": "Administrator"})
		deals = self.make_view("My Deals", "CRM Deal", is_default=1)
		leads = self.make_view("My Leads", "CRM Lead")

		set_as_default(name=leads.name)

		self.assertEqual(frappe.db.get_value("CRM View Settings", deals.name, "is_default"), 1)
