import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

SETTINGS = "CRM Acumatica Settings"


class TestAcumaticaSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 0)
		self.clear_sync_issues()

	@staticmethod
	def clear_sync_issues():
		"""``record_sync_issue`` saves the Single from inside whatever transaction
		hit the failure, so its rows outlive the test that wrote them. Left alone,
		the cap test's 200 rows carry into the next run and the append test then
		measures a table already at MAX_SYNC_ISSUES -- appending trims one off and
		the count does not move. Each test starts from a table it set itself.
		"""
		doc = frappe.get_doc("CRM Acumatica Settings")
		if not doc.sync_issues:
			return
		doc.sync_issues = []
		doc.flags.ignore_validate = True
		doc.flags.write_sync_issues = True
		doc.save(ignore_permissions=True)

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
			"last_sync_error",
			"pending_retries",
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

		self.clear_sync_issues()
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
		doc.flags.write_sync_issues = True
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

	def test_a_sales_user_learns_only_whether_it_is_enabled(self):
		"""The deal form script needs one bit. The settings document also holds the
		webhook secret and the API identity, and frappe.client.get_single_value checks
		doctype-level read only -- so the bit comes through its own method and the
		document itself is closed to reps."""
		from frappe.client import get_single_value

		from crm.integrations.acumatica.api import is_enabled

		email = "acumatica-rep@crmtest.test"
		if not frappe.db.exists("User", email):
			user = frappe.get_doc(
				{"doctype": "User", "email": email, "first_name": "Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.set_user(email)
		try:
			self.assertFalse(is_enabled())
			with self.assertRaises(frappe.PermissionError):
				get_single_value("CRM Acumatica Settings", "webhook_verify_token")
		finally:
			frappe.set_user("Administrator")

	def test_the_webhook_token_is_stored_encrypted(self):
		s = frappe.get_doc("CRM Acumatica Settings")
		s.webhook_verify_token = "plain-token-for-test"
		s.flags.ignore_validate = True
		s.save(ignore_permissions=True)
		try:
			self.assertNotEqual(
				frappe.db.get_single_value("CRM Acumatica Settings", "webhook_verify_token"),
				"plain-token-for-test",
			)
			self.assertEqual(s.get_password("webhook_verify_token"), "plain-token-for-test")
		finally:
			s.webhook_verify_token = ""
			s.save(ignore_permissions=True)

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

	def test_identity_fields_are_schema_not_a_feature_flag(self):
		"""#166: the only route to the custom fields used to be enabling the
		integration, which also arms a live ERP write. Install and migrate own
		them now, and the patch no longer looks at the toggle."""
		from crm.patches.v1_0.create_custom_fields_for_acumatica_in_crm import execute

		self.assertIn(
			"crm.integrations.acumatica.install.ensure_custom_fields",
			frappe.get_hooks("after_migrate"),
		)
		self.assertEqual(frappe.db.get_single_value("CRM Acumatica Settings", "enabled"), 0)
		execute()
		self.assertIsNotNone(frappe.get_meta("CRM Organization").get_field("acumatica_id"))
		self.assertIsNotNone(frappe.get_meta("Contact").get_field("acumatica_noteid"))

	def test_disabling_disables_the_form_script_and_enabling_brings_it_back(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import FORM_SCRIPT_NAME

		try:
			s = frappe.get_doc("CRM Acumatica Settings")
			s.enabled = 1
			s.instance_url = "https://x.acumatica.com"
			s.save()
			self.assertEqual(frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"), 1)

			s.reload()
			s.enabled = 0
			s.save()
			# the record survives (a site may have customised it) but the button is gone
			self.assertEqual(frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"), 0)

			s.reload()
			s.enabled = 1
			s.save()
			self.assertEqual(frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"), 1)
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


class TestMutualExclusion(FrappeTestCase):
	"""One ERP integration at a time, enforced on BOTH saves."""

	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.set_single_value("ERPNext CRM Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def test_guard_is_wired_to_the_erpnext_settings_save(self):
		self.assertIn(
			"crm.integrations.acumatica.install.block_dual_erp",
			frappe.get_hooks("doc_events").get("ERPNext CRM Settings", {}).get("validate", []),
		)

	def test_enabling_erpnext_while_acumatica_is_on_is_refused(self):
		"""Driven through the guard rather than ERPNextCRMSettings.save(): on a site
		without erpnext installed that controller throws "ERPNext is not installed"
		before any doc_event hook runs, which would prove nothing about this rule."""
		from crm.integrations.acumatica.install import block_dual_erp

		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

		erpnext_settings = frappe.get_doc("ERPNext CRM Settings")
		erpnext_settings.enabled = 1
		with self.assertRaises(frappe.ValidationError):
			block_dual_erp(erpnext_settings, "validate")

	def test_enabling_erpnext_while_acumatica_is_off_is_allowed(self):
		from crm.integrations.acumatica.install import block_dual_erp

		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

		erpnext_settings = frappe.get_doc("ERPNext CRM Settings")
		erpnext_settings.enabled = 1
		block_dual_erp(erpnext_settings, "validate")  # must not raise


class TestDealLayoutFields(FrappeTestCase):
	"""The customer and quote ids have to be visible on the deal page once the
	integration is on -- the custom fields alone put them nowhere."""

	LAYOUTS = ("CRM Deal-Side Panel", "CRM Deal-Data Fields", "CRM Organization-Side Panel")

	def setUp(self):
		self.saved = {
			name: frappe.db.get_value("CRM Fields Layout", name, "layout")
			for name in self.LAYOUTS
			if frappe.db.exists("CRM Fields Layout", name)
		}
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		for name, layout in self.saved.items():
			frappe.db.set_value("CRM Fields Layout", name, "layout", layout)
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _fields(self, name):
		from crm.integrations.acumatica.install import _layout_fields

		return _layout_fields(json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout")))

	def test_disabled_integration_leaves_the_layouts_alone(self):
		from crm.integrations.acumatica.install import ensure_layout_fields

		ensure_layout_fields()
		for name in self.saved:
			self.assertFalse({"acumatica_sales_quote", "acumatica_id"} & self._fields(name), name)

	def test_enabling_adds_the_fields_once(self):
		from crm.integrations.acumatica.install import ensure_layout_fields

		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		ensure_layout_fields()
		ensure_layout_fields()  # idempotent
		from crm.integrations.acumatica.install import LAYOUT_FIELDS

		for name in self.saved:
			layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout"))
			sections = layout[0]["sections"] if "sections" in layout[0] else layout
			acumatica = [s for s in sections if s.get("name") == "acumatica_section"]
			self.assertEqual(len(acumatica), 1, name)
			self.assertEqual(acumatica[0]["columns"][0]["fields"], LAYOUT_FIELDS[name])

	def test_an_admin_placed_field_is_respected(self):
		from crm.integrations.acumatica.install import ensure_layout_fields

		name = "CRM Deal-Side Panel"
		layout = json.loads(self.saved[name])
		layout[-1]["columns"][0]["fields"].append("acumatica_sales_quote")
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))

		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		ensure_layout_fields()
		layout = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout"))
		self.assertFalse([s for s in layout if s.get("name") == "acumatica_section"])

	def test_an_admins_removal_and_disable_survive_a_migrate_and_a_settings_save(self):
		"""Nothing recorded that the section had been placed, so "absent" read as
		"never added" and every migrate put it back; the script refresh switched
		the quote button back on too. Turning the integration on places both --
		after that they are the admin's."""
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import FORM_SCRIPT_NAME
		from crm.integrations.acumatica.install import refresh_integration

		self.addCleanup(
			lambda: frappe.db.exists("CRM Form Script", FORM_SCRIPT_NAME)
			and frappe.delete_doc("CRM Form Script", FORM_SCRIPT_NAME, force=True, ignore_permissions=True)
		)
		name = "CRM Deal-Side Panel"
		settings = frappe.get_doc("CRM Acumatica Settings")
		settings.enabled = 1
		settings.instance_url = "https://x.acumatica.com"
		settings.save()
		self.assertIn("acumatica_sales_quote", self._fields(name))

		# the admin takes the section off the side panel and switches the button off
		layout = [
			section
			for section in json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout"))
			if section.get("name") != "acumatica_section"
		]
		frappe.db.set_value("CRM Fields Layout", name, "layout", json.dumps(layout))
		frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled", 0)

		refresh_integration()
		settings.reload()
		settings.quote_order_type = "SO"
		settings.save()

		self.assertNotIn("acumatica_sales_quote", self._fields(name))
		self.assertEqual(frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"), 0)

	def test_a_migrate_still_brings_the_script_text_up_to_date(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import FORM_SCRIPT_NAME
		from crm.integrations.acumatica.api import get_crm_form_script
		from crm.integrations.acumatica.install import refresh_integration

		self.addCleanup(
			lambda: frappe.db.exists("CRM Form Script", FORM_SCRIPT_NAME)
			and frappe.delete_doc("CRM Form Script", FORM_SCRIPT_NAME, force=True, ignore_permissions=True)
		)
		settings = frappe.get_doc("CRM Acumatica Settings")
		settings.enabled = 1
		settings.instance_url = "https://x.acumatica.com"
		settings.save()
		frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, {"script": "class CRMDeal {}", "enabled": 0})

		refresh_integration()

		self.assertEqual(
			frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "script"), get_crm_form_script()
		)
		self.assertEqual(frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"), 0)


class TestCustomerPushSettings(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_the_new_fields_and_their_defaults(self):
		meta = frappe.get_meta("CRM Acumatica Settings")
		self.assertEqual(meta.get_field("new_customer_class").default, "COD")
		self.assertEqual(meta.get_field("home_country").default, "South Africa")
		self.assertEqual(meta.get_field("home_country").options, "Country")
		self.assertIsNotNone(meta.get_field("tax_zone_home"))
		self.assertIsNotNone(meta.get_field("tax_zone_abroad"))
		kinds = frappe.get_meta("CRM Acumatica Sync Issue").get_field("kind").options.split("\n")
		self.assertIn("Push Blocked", kinds)
		self.assertIn("Possible Duplicate", kinds)

	def test_the_switch_needs_a_customer_class(self):
		doc = frappe.get_doc("CRM Acumatica Settings")
		doc.create_customer_on_status_change = 1
		doc.deal_status = "Won"
		doc.new_customer_class = " "
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_an_existing_site_gets_the_defaults_once(self):
		from crm.integrations.acumatica.install import ensure_customer_push_defaults

		frappe.db.delete("Singles", {"doctype": "CRM Acumatica Settings", "field": "new_customer_class"})
		frappe.db.set_single_value("CRM Acumatica Settings", "home_country", None)
		ensure_customer_push_defaults()
		self.assertEqual(frappe.db.get_single_value("CRM Acumatica Settings", "new_customer_class"), "COD")
		# a field an admin cleared stays cleared
		self.assertFalse(frappe.db.get_single_value("CRM Acumatica Settings", "home_country"))

	def test_vat_and_confirmed_fields_are_installed(self):
		from crm.integrations.acumatica.install import LAYOUT_FIELDS, ensure_custom_fields

		ensure_custom_fields()
		meta = frappe.get_meta("CRM Organization")
		self.assertEqual(meta.get_field("tax_registration_id").label, "VAT Number")
		self.assertTrue(meta.get_field("acumatica_confirmed_for").hidden)
		self.assertIn("tax_registration_id", LAYOUT_FIELDS["CRM Organization-Side Panel"])

	def test_a_stale_save_of_the_settings_keeps_the_issue_log(self):
		"""The panel saves the copy it loaded; rows a job recorded or a manager
		dismissed since must survive it."""
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
			dismiss_sync_issues,
			record_sync_issue,
		)

		record_sync_issue("Customer", "STALE-1", "Push Failed", "first")
		stale = frappe.get_doc("CRM Acumatica Settings")
		record_sync_issue("Customer", "STALE-2", "Push Failed", "recorded after the copy was loaded")
		dismiss_sync_issues("Customer", "STALE-1", ("Push Failed",))
		stale.save(ignore_permissions=True)

		rows = {r.remote_id: r for r in frappe.get_doc("CRM Acumatica Settings").sync_issues}
		self.assertIn("STALE-2", rows)
		self.assertEqual(rows["STALE-1"].dismissed, 1)

	def test_the_vat_number_patch_puts_it_beside_the_customer_code(self):
		from crm.patches.v1_0 import add_vat_number_to_organization_side_panel as patch_module

		layout = [
			{
				"name": "details",
				"columns": [{"name": "c1", "fields": ["website", "acumatica_id", "industry"]}],
			}
		]
		name = "CRM Organization-Side Panel"
		if frappe.db.exists("CRM Fields Layout", name):
			doc = frappe.get_doc("CRM Fields Layout", name)
			doc.layout = json.dumps(layout)
			doc.save(ignore_permissions=True)
		else:
			frappe.get_doc(
				{
					"doctype": "CRM Fields Layout",
					"dt": "CRM Organization",
					"type": "Side Panel",
					"layout": json.dumps(layout),
				}
			).insert(ignore_permissions=True)

		patch_module.execute()
		patch_module.execute()  # idempotent

		fields = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout"))[0]["columns"][0][
			"fields"
		]
		self.assertEqual(fields, ["website", "acumatica_id", "tax_registration_id", "industry"])


class TestInstanceUrlAndItsSecrets(FrappeTestCase):
	"""The secrets are masked on read, but they are posted to whatever the instance
	URL says -- and a Sales Manager can write the instance URL. So the URL is
	checked when it changes, and the secrets stored for one host never follow it to
	another: whoever moves it has to enter them again."""

	URL = "https://mbp.example.com/MBP"
	SECRETS = (("client_secret", "stored-client-secret"), ("password", "stored-api-password"))

	def setUp(self):
		from frappe.utils.password import set_encrypted_password

		from crm.integrations import remote_url

		frappe.set_user("Administrator")
		frappe.db.set_single_value(SETTINGS, {"enabled": 0, "instance_url": self.URL})
		for field, value in self.SECRETS:
			set_encrypted_password(SETTINGS, SETTINGS, value, field)
			frappe.db.set_single_value(SETTINGS, field, "*" * len(value))
		frappe.clear_document_cache(SETTINGS, SETTINGS)

		def resolve(host):
			if host == "db.internal":
				return ["10.0.3.7"]
			return ["93.184.215.14"]

		for patcher in (
			patch.object(remote_url, "_resolve", side_effect=resolve),
			patch.dict(frappe.local.conf, {"developer_mode": 0, remote_url.TRUSTED_HOSTS_CONFIG: []}),
		):
			patcher.start()
			self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def stored(self, field):
		return frappe.get_doc(SETTINGS).get_password(field, raise_exception=False)

	def test_moving_the_instance_does_not_take_the_stored_secrets_with_it(self):
		s = frappe.get_doc(SETTINGS)
		s.instance_url = "https://attacker.example"
		with self.assertRaises(frappe.ValidationError) as refused:
			s.save()
		self.assertIn("Client Secret", str(refused.exception))
		self.assertIn("Password", str(refused.exception))
		# nothing moved: the URL and both secrets are as they were
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "instance_url"), self.URL)
		self.assertEqual(self.stored("client_secret"), "stored-client-secret")

	def test_the_api_a_manager_saves_through_is_held_to_it(self):
		"""The pane saves with frappe.client.set_value; so can anyone with the role."""
		for values in (
			{"instance_url": "https://attacker.example"},
			# one secret typed, the other left on its mask
			{"instance_url": "https://attacker.example", "client_secret": "mine"},
			{"instance_url": "https://mbp.example.com:8443/MBP"},
			{"instance_url": "https://mbp.example.com.attacker.example/MBP"},
		):
			with self.subTest(values=values), self.assertRaises(frappe.ValidationError):
				frappe.client.set_value(SETTINGS, SETTINGS, values)
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "instance_url"), self.URL)

	def test_the_instance_can_be_moved_by_entering_the_secrets_again(self):
		s = frappe.get_doc(SETTINGS)
		s.instance_url = "https://live.example.com/"
		s.client_secret = "new-client-secret"
		s.password = "new-api-password"
		s.save()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "instance_url"), "https://live.example.com")
		self.assertEqual(self.stored("client_secret"), "new-client-secret")
		self.assertEqual(self.stored("password"), "new-api-password")

	def test_another_company_on_the_same_host_keeps_the_secrets(self):
		"""Sandbox and live share a host and differ by path; so does a typo fixed."""
		s = frappe.get_doc(SETTINGS)
		s.instance_url = "https://MBP.example.com/Live/"
		s.save()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "instance_url"), "https://MBP.example.com/Live")
		self.assertEqual(self.stored("password"), "stored-api-password")

	def test_removing_the_url_clears_the_secrets_stored_for_it(self):
		"""Otherwise the move is two saves: blank the URL, then set the new one."""
		s = frappe.get_doc(SETTINGS)
		s.instance_url = ""
		s.save()
		self.assertIsNone(self.stored("client_secret"))
		self.assertIsNone(self.stored("password"))

		s.reload()
		s.instance_url = "https://attacker.example"
		s.save()  # nothing stored is left to send there
		self.assertIsNone(self.stored("client_secret"))

	def test_secrets_stored_before_any_url_are_not_sent_to_the_first_one(self):
		frappe.db.set_single_value(SETTINGS, "instance_url", "")
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		s = frappe.get_doc(SETTINGS)
		s.instance_url = "https://attacker.example"
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_a_url_that_is_not_public_https_is_refused(self):
		for url in (
			"http://live.example.com",
			"https://127.0.0.1:8000",
			"https://169.254.169.254/latest",
			"https://db.internal",
			"https://user:pw@live.example.com",
			"live.example.com",
		):
			with self.subTest(url=url):
				s = frappe.get_doc(SETTINGS)
				s.instance_url = url
				s.client_secret = "typed"
				s.password = "typed"
				with self.assertRaises(frappe.ValidationError):
					s.save()

	def test_a_path_or_slash_edit_on_a_url_from_before_the_rules_is_not_re_judged(self):
		"""Same scheme, host and port: the same server the secrets were entered for,
		so neither the URL rules nor the re-entry rule has anything new to decide."""
		frappe.db.set_single_value(SETTINGS, "instance_url", "http://10.0.0.5/acumatica")
		for url, kept in (
			("http://10.0.0.5/acumatica/", "http://10.0.0.5/acumatica"),
			("http://10.0.0.5/AcumaticaLive", "http://10.0.0.5/AcumaticaLive"),
			("http://10.0.0.5:80/AcumaticaLive", "http://10.0.0.5:80/AcumaticaLive"),
		):
			with self.subTest(url=url):
				frappe.clear_document_cache(SETTINGS, SETTINGS)
				s = frappe.get_doc(SETTINGS)
				s.instance_url = url
				s.save()
				self.assertEqual(frappe.db.get_single_value(SETTINGS, "instance_url"), kept)
				self.assertEqual(self.stored("password"), "stored-api-password")
		# another host is still another host
		s = frappe.get_doc(SETTINGS)
		s.instance_url = "http://10.0.0.6/acumatica"
		with self.assertRaises(frappe.ValidationError):
			s.save()

	def test_the_other_settings_still_save_beside_a_url_from_before_the_rules(self):
		"""An existing site's URL is judged when it is used, not on every save of
		something else -- or its admin could not change anything until it was fixed."""
		frappe.db.set_single_value(SETTINGS, "instance_url", "http://10.0.0.5/acumatica")
		frappe.clear_document_cache(SETTINGS, SETTINGS)
		s = frappe.get_doc(SETTINGS)
		s.quote_order_type = "QT"
		s.save()
		self.assertEqual(frappe.db.get_single_value(SETTINGS, "quote_order_type"), "QT")
		self.assertEqual(self.stored("password"), "stored-api-password")
