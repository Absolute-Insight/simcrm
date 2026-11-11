import frappe
from frappe.tests import IntegrationTestCase

from crm.api.auth import land_in_crm


class TestLandInCrm(IntegrationTestCase):
	"""Where a form login sends someone.

	``get_home_page`` ignores the flag under test, so the flag is what is
	asserted; that frappe then answers the login with it is frappe's.
	"""

	def setUp(self):
		frappe.local.flags.home_page = None
		self.addCleanup(setattr, frappe.local.flags, "home_page", None)

	def user(self, email: str, roles: list[str]) -> frappe._dict:
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": email.split("@")[0],
					"send_welcome_email": 0,
					"roles": [{"role": role} for role in roles],
				}
			).insert(ignore_permissions=True)
		return frappe._dict(user=email)

	def test_a_rep_lands_in_the_crm(self):
		land_in_crm(self.user("landing-rep@example.com", ["Sales User"]))
		self.assertEqual(frappe.local.flags.home_page, "crm")

	def test_a_sales_manager_lands_in_the_crm(self):
		land_in_crm(self.user("landing-manager@example.com", ["Sales Manager"]))
		self.assertEqual(frappe.local.flags.home_page, "crm")

	def test_a_system_manager_keeps_the_desk(self):
		land_in_crm(self.user("landing-admin@example.com", ["System Manager", "Sales Manager"]))
		self.assertIsNone(frappe.local.flags.home_page)
		land_in_crm(frappe._dict(user="Administrator"))
		self.assertIsNone(frappe.local.flags.home_page)

	def test_someone_with_no_crm_role_is_left_alone(self):
		land_in_crm(self.user("landing-other@example.com", []))
		self.assertIsNone(frappe.local.flags.home_page)

	def test_the_hook_is_wired(self):
		self.assertIn("crm.api.auth.land_in_crm", frappe.get_hooks("on_login"))
