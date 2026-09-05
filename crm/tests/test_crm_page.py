import frappe
from frappe.tests import IntegrationTestCase

from crm.www.crm import get_context


class TestCRMPage(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")

	def test_a_guest_is_sent_to_log_in_and_back(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.Redirect):
			get_context()
		self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=/crm")

	def test_a_user_without_the_crm_module_is_still_refused(self):
		user = "no-crm-page@example.com"
		if not frappe.db.exists("User", user):
			frappe.get_doc(
				{"doctype": "User", "email": user, "first_name": "No", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
		frappe.set_user(user)
		with self.assertRaises(frappe.PermissionError):
			get_context()
