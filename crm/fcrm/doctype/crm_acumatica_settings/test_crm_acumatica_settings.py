import frappe
from frappe.tests.utils import FrappeTestCase


class TestAcumaticaSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 0)

	def test_doctype_exists_with_expected_fields(self):
		meta = frappe.get_meta("CRM Acumatica Settings")
		for fieldname in (
			"enabled",
			"instance_url",
			"endpoint_name",
			"endpoint_version",
			"client_id",
			"client_secret",
			"username",
			"password",
			"quote_order_type",
			"webhook_verify_token",
			"request_pause",
			"last_synced_at",
			"sync_issues",
		):
			self.assertIsNotNone(meta.get_field(fieldname), fieldname)
		self.assertEqual(meta.get_field("endpoint_version").default, "24.200.001")

	def test_cannot_enable_both_erps(self):
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 1)
		s = frappe.get_doc("CRM Acumatica Settings")
		s.enabled = 1
		s.instance_url = "https://x.acumatica.com"
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_enable_requires_instance_url(self):
		s = frappe.get_doc("CRM Acumatica Settings")
		s.enabled = 1
		s.instance_url = ""
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_record_sync_issue_appends_row(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
			record_sync_issue,
		)

		before = len(frappe.get_doc("CRM Acumatica Settings").sync_issues)
		record_sync_issue("Customer", "ABC001", "Import Failed", "boom")
		after = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertEqual(len(after), before + 1)
		self.assertEqual(after[-1].entity, "Customer")
		self.assertEqual(after[-1].kind, "Import Failed")
