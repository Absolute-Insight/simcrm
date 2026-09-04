"""The three fields the old rep app's New Lead form captured and CRM Lead did not."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.install import SA_PROVINCES, ensure_sa_provinces


class LeadPersonFieldsTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_birthday_and_contact_type_are_stored(self):
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Piet",
				"last_name": "Fourie",
				"birthday": "1979-03-14",
				"contact_type": "Maintenance",
			}
		).insert()
		self.assertEqual(str(lead.birthday), "1979-03-14")
		self.assertEqual(lead.contact_type, "Maintenance")

	def test_an_unknown_contact_type_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": "CRM Lead", "first_name": "X", "contact_type": "Astronaut"}).insert()

	def test_provinces_exist_as_territories_and_seeding_is_idempotent(self):
		ensure_sa_provinces()
		ensure_sa_provinces()
		for province in SA_PROVINCES:
			self.assertTrue(frappe.db.exists("CRM Territory", province), province)
		self.assertEqual(len(SA_PROVINCES), 9)
