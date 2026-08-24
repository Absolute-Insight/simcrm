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

	def test_record_sync_issue_caps_the_table(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
			MAX_SYNC_ISSUES,
			record_sync_issue,
		)

		doc = frappe.get_doc("CRM Acumatica Settings")
		doc.sync_issues = []
		for i in range(MAX_SYNC_ISSUES):
			doc.append(
				"sync_issues",
				{"entity": "Customer", "remote_id": f"R{i}", "kind": "Import Failed", "detail": "x"},
			)
		doc.flags.ignore_validate = True
		doc.save(ignore_permissions=True)

		record_sync_issue("Customer", "NEWEST", "Import Failed", "boom")

		rows = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertEqual(len(rows), MAX_SYNC_ISSUES)  # a bad backfill must not grow it forever
		self.assertEqual(rows[0].remote_id, "R1")  # oldest row dropped
		self.assertEqual(rows[-1].remote_id, "NEWEST")
		self.assertEqual([row.idx for row in rows], list(range(1, MAX_SYNC_ISSUES + 1)))

	def test_record_sync_issue_does_not_run_validate(self):
		"""It is called from inside a user's deal save; the mutual-exclusion check
		must not turn a logged sync issue into a failed save."""
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import record_sync_issue

		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.db.set_single_value("CRM Acumatica Settings", "instance_url", "https://x.acumatica.com")
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

		record_sync_issue("Customer", "ABC001", "Push Failed", "boom")  # must not raise

		self.assertTrue(
			any(row.remote_id == "ABC001" for row in frappe.get_doc("CRM Acumatica Settings").sync_issues)
		)

	def test_sales_user_can_read_the_enabled_flag(self):
		"""The deal form script asks for it on every load; a PermissionError here
		means every rep sees a console error and never gets the action."""
		from frappe.client import get_single_value

		email = "acumatica-rep@crmtest.test"
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.set_user(email)
		try:
			self.assertIsNotNone(get_single_value("CRM Acumatica Settings", "enabled"))
		finally:
			frappe.set_user("Administrator")

	def test_saving_settings_refreshes_a_stale_form_script(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import FORM_SCRIPT_NAME
		from crm.integrations.acumatica.api import get_crm_form_script

		try:
			s = frappe.get_doc("CRM Acumatica Settings")
			s.enabled = 1
			s.instance_url = "https://x.acumatica.com"
			s.save()

			frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "script", "class CRMDeal {}")
			s.reload()
			s.quote_order_type = "SO"
			s.save()

			self.assertEqual(
				frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "script"),
				get_crm_form_script(),
			)
		finally:
			frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
			if frappe.db.exists("CRM Form Script", FORM_SCRIPT_NAME):
				frappe.delete_doc("CRM Form Script", FORM_SCRIPT_NAME, force=True, ignore_permissions=True)

	def test_ensure_custom_fields_creates_identity_fields(self):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
		for doctype in ("CRM Organization", "Contact", "CRM Product"):
			meta = frappe.get_meta(doctype)
			self.assertIsNotNone(meta.get_field("acumatica_noteid"), doctype)
			self.assertIsNotNone(meta.get_field("acumatica_id"), doctype)
		self.assertIsNotNone(frappe.get_meta("CRM Deal").get_field("acumatica_customer"))

	def test_enabling_installs_the_crm_form_script(self):
		try:
			s = frappe.get_doc("CRM Acumatica Settings")
			s.enabled = 1
			s.instance_url = "https://x.acumatica.com"
			s.save()

			self.assertTrue(frappe.db.exists("CRM Form Script", "Create Sales Quote from CRM Deal"))
			script_doc = frappe.get_doc("CRM Form Script", "Create Sales Quote from CRM Deal")
			self.assertEqual(script_doc.dt, "CRM Deal")
			self.assertEqual(script_doc.enabled, 1)
		finally:
			frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
			if frappe.db.exists("CRM Form Script", "Create Sales Quote from CRM Deal"):
				frappe.delete_doc(
					"CRM Form Script",
					"Create Sales Quote from CRM Deal",
					force=True,
					ignore_permissions=True,
				)
