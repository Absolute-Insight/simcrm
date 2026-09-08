import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import set_request

from crm.www.crm import get_context, login_redirect_for


class TestCRMPage(IntegrationTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.local.request = None

	def test_a_guest_is_sent_to_log_in_and_back(self):
		frappe.set_user("Guest")
		set_request(method="GET", path="/crm")
		with self.assertRaises(frappe.Redirect):
			get_context()
		self.assertEqual(frappe.local.flags.redirect_location, "/login?redirect-to=/crm")

	def test_a_guest_opening_a_deep_link_comes_back_to_it(self):
		# The notification email links to the record, not to the app's front door.
		frappe.set_user("Guest")
		set_request(method="GET", path="/crm/deals/CRM-DEAL-2026-00042")
		with self.assertRaises(frappe.Redirect):
			get_context()
		self.assertEqual(
			frappe.local.flags.redirect_location,
			"/login?redirect-to=/crm/deals/CRM-DEAL-2026-00042",
		)

	def test_the_query_string_survives_the_round_trip(self):
		frappe.set_user("Guest")
		set_request(method="GET", path="/crm/leads/view/list", query_string="view=Mine&x=1")
		with self.assertRaises(frappe.Redirect):
			get_context()
		self.assertEqual(
			frappe.local.flags.redirect_location,
			"/login?redirect-to=/crm/leads/view/list%3Fview%3DMine%26x%3D1",
		)

	def test_the_redirect_target_never_leaves_the_app(self):
		# website_route_rules only send /crm/* here, but the value is built from
		# the request, so it is pinned to the app rather than trusted.
		self.assertEqual(login_redirect_for("/crm/deals/X"), "/login?redirect-to=/crm/deals/X")
		self.assertEqual(login_redirect_for("/crm/deals/X?"), "/login?redirect-to=/crm/deals/X")
		self.assertEqual(login_redirect_for(""), "/login?redirect-to=/crm")
		self.assertEqual(login_redirect_for(None), "/login?redirect-to=/crm")
		self.assertEqual(login_redirect_for("//evil.example/crm"), "/login?redirect-to=/crm")
		self.assertEqual(login_redirect_for("/app/deal"), "/login?redirect-to=/crm")
		self.assertEqual(login_redirect_for("/crm-form/x"), "/login?redirect-to=/crm")

	def test_a_guest_with_no_request_object_still_gets_the_front_door(self):
		frappe.set_user("Guest")
		frappe.local.request = None
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
