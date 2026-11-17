"""Customer-code search. Reps know their accounts as C-IMP003E, not by name."""

import json
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


class CustomerCodeShownTest(IntegrationTestCase):
	"""The code is how the sales team names an account, so it is on the list,
	in every organization picker, and labelled as what it is."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()

	def tearDown(self):
		frappe.db.rollback()
		# a rolled-back Property Setter must not outlive the test in the meta cache
		frappe.clear_cache(doctype="CRM Organization")

	def test_the_field_is_called_customer_code_and_is_a_list_column(self):
		field = frappe.get_meta("CRM Organization").get_field("acumatica_id")
		self.assertEqual(field.label, "Customer Code")
		self.assertTrue(field.in_list_view)
		self.assertTrue(field.read_only, "the sync matches on the code; it must not be hand-edited")
		self.assertEqual(frappe.get_meta("CRM Deal").get_field("acumatica_customer").label, "Customer Code")

	def test_the_default_list_shows_the_code(self):
		from crm.fcrm.doctype.crm_organization.crm_organization import CRMOrganization

		data = CRMOrganization.default_list_data()
		self.assertIn("acumatica_id", [c["key"] for c in data["columns"]])
		self.assertIn("acumatica_id", data["rows"])

	def test_a_link_search_matches_the_code_and_describes_the_option_with_it(self):
		from frappe.desk.search import search_link

		frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Karee Merensky",
				"acumatica_id": "C-LON001J",
			}
		).insert()
		options = search_link("CRM Organization", "C-LON001")
		match = next((o for o in options if o["value"] == "Karee Merensky"), None)
		self.assertIsNotNone(match, "searching by customer code found nothing")
		self.assertIn("C-LON001J", match.get("description") or "")

	def test_a_saved_standard_view_gains_the_column_once(self):
		from crm.patches.v1_0.add_customer_code_to_saved_views import execute

		columns = [
			{"key": "organization_name", "label": "Organization"},
			{"key": "website", "label": "Website"},
		]
		view = frappe.get_doc(
			{
				"doctype": "CRM View Settings",
				"dt": "CRM Organization",
				"type": "list",
				"is_standard": 1,
				"label": "Saved",
				"user": "Administrator",
				"columns": json.dumps(columns),
				"rows": json.dumps(["name", "organization_name", "website"]),
			}
		).insert(ignore_permissions=True)

		execute()
		execute()

		saved = frappe.db.get_value("CRM View Settings", view.name, ["columns", "rows"], as_dict=True)
		self.assertEqual(
			[c["key"] for c in json.loads(saved.columns)], ["organization_name", "acumatica_id", "website"]
		)
		self.assertIn("acumatica_id", json.loads(saved.rows))

	def test_a_malformed_saved_view_does_not_stop_the_migrate(self):
		from frappe import _dict

		from crm.patches.v1_0.add_customer_code_to_saved_views import add_customer_code

		for columns, rows in (('["x"]', "[]"), ("5", "[]"), ("[]", "5")):
			add_customer_code(_dict(name="not-saved", columns=columns, rows=rows))

	def test_setting_up_the_search_twice_keeps_an_admins_own_search_fields(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		from crm.integrations.acumatica.install import ensure_customer_code_search

		make_property_setter("CRM Organization", None, "search_fields", "website", "Data", for_doctype=True)
		frappe.clear_cache(doctype="CRM Organization")
		ensure_customer_code_search()
		ensure_customer_code_search()
		frappe.clear_cache(doctype="CRM Organization")
		self.assertEqual(frappe.get_meta("CRM Organization").search_fields, "acumatica_id,website")
