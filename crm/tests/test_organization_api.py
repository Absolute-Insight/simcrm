"""Customer-code search. Reps know their accounts as C-IMP003E, not by name."""

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.organization import find_by_code
from crm.api.session import get_organizations
from crm.integrations.acumatica.install import ensure_custom_fields


class FindByCodeTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()

	def setUp(self):
		super().setUp()
		for code, name in (
			("C-IMP003E", "Impala - Shaft 10"),
			("C-IMP003F", "Impala - Shaft 11"),
			("C-SIB001", "Sibanye"),
		):
			frappe.get_doc(
				{"doctype": "CRM Organization", "organization_name": name, "acumatica_id": code}
			).insert()

	def tearDown(self):
		frappe.db.rollback()

	def test_prefix_match_ordered_by_code(self):
		rows = find_by_code("c-imp003")
		self.assertEqual([r["acumatica_id"] for r in rows], ["C-IMP003E", "C-IMP003F"])
		self.assertEqual(rows[0]["name"], "Impala - Shaft 10")

	def test_no_match_is_an_empty_list_not_an_error(self):
		self.assertEqual(find_by_code("C-NOPE"), [])

	def test_a_blank_code_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			find_by_code("  ")

	def test_a_site_without_the_field_is_told_so_rather_than_shown_nothing(self):
		meta = frappe.get_meta("CRM Organization")
		with patch.object(meta, "get_field", return_value=None), patch("frappe.get_meta", return_value=meta):
			with self.assertRaisesRegex(frappe.ValidationError, "not installed"):
				find_by_code("C-IMP003E")


class OrganizationLogoLookupTest(IntegrationTestCase):
	"""The store every list page loads on app start, for one field: the logo."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.with_logo = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Logo Lookup With Logo",
				"organization_logo": "/files/logo-lookup.png",
			}
		).insert(ignore_permissions=True)
		self.without_logo = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Logo Lookup Without Logo"}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def test_it_carries_the_name_and_logo_of_organizations_that_have_one(self):
		rows = {row["name"]: row for row in get_organizations()}
		self.assertEqual(
			rows[self.with_logo.name],
			{"name": self.with_logo.name, "organization_logo": "/files/logo-lookup.png"},
		)
		self.assertNotIn(self.without_logo.name, rows)
		self.assertTrue(all(set(row) == {"name", "organization_logo"} for row in rows.values()))
