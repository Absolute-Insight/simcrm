"""A customer's head account: Acumatica's ParentRecord, kept on the organization.

MBP files a mine's plants and shafts as customers of their own under one head
account. The sync records which one, a site imported before its head account is
linked when the head account arrives, and a one-off pass fills in the customers
imported before the field existed.
"""

import json
from unittest.mock import MagicMock, patch

import frappe

from crm.integrations.acumatica import importer
from crm.integrations.acumatica.install import ensure_customer_code_search
from crm.integrations.acumatica.test_importer import C, ImporterTestCase


def _head(name):
	return frappe.db.get_value("CRM Organization", name, ["acumatica_parent", "head_account"])


class HeadAccountSyncTest(ImporterTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_a_site_is_linked_to_its_head_account(self):
		head = importer.upsert_organization(C(NoteID="ha-1", CustomerID="C-HA001", CustomerName="Head Mines"))
		site = importer.upsert_organization(
			C(NoteID="ha-1a", CustomerID="C-HA001A", CustomerName="Head East Plant", ParentRecord="C-HA001")
		)
		self.assertEqual(_head(site), ("C-HA001", head))
		self.assertEqual(_head(head), (None, None))

	def test_a_site_that_arrives_first_is_linked_when_its_head_account_does(self):
		site = importer.upsert_organization(
			C(NoteID="ha-2a", CustomerID="C-HA002A", CustomerName="Early Shaft", ParentRecord="C-HA002")
		)
		self.assertEqual(_head(site), ("C-HA002", None))
		head = importer.upsert_organization(C(NoteID="ha-2", CustomerID="C-HA002", CustomerName="Late Head"))
		self.assertEqual(_head(site), ("C-HA002", head))

	def test_a_record_without_the_field_leaves_the_link_alone(self):
		head = importer.upsert_organization(C(NoteID="ha-3", CustomerID="C-HA003", CustomerName="Keep Head"))
		site = importer.upsert_organization(
			C(NoteID="ha-3a", CustomerID="C-HA003A", CustomerName="Keep Site", ParentRecord="C-HA003")
		)
		# the spreadsheet import carries no ParentRecord at all
		importer.upsert_organization(C(CustomerID="C-HA003A", CustomerName="Keep Site"))
		self.assertEqual(_head(site), ("C-HA003", head))

	def test_a_site_moved_off_its_head_account_is_unlinked(self):
		importer.upsert_organization(C(NoteID="ha-4", CustomerID="C-HA004", CustomerName="Old Head"))
		site = importer.upsert_organization(
			C(NoteID="ha-4a", CustomerID="C-HA004A", CustomerName="Moved Site", ParentRecord="C-HA004")
		)
		importer.upsert_organization(
			C(NoteID="ha-4a", CustomerID="C-HA004A", CustomerName="Moved Site", ParentRecord=None)
		)
		self.assertEqual(_head(site), (None, None))

	def test_a_customer_naming_itself_has_no_head_account(self):
		name = importer.upsert_organization(
			C(NoteID="ha-5", CustomerID="C-HA005", CustomerName="Self Head", ParentRecord="C-HA005")
		)
		self.assertEqual(_head(name), (None, None))

	def test_a_renamed_head_account_keeps_its_sites(self):
		head = importer.upsert_organization(
			C(NoteID="ha-6", CustomerID="C-HA006", CustomerName="Before Name")
		)
		site = importer.upsert_organization(
			C(NoteID="ha-6a", CustomerID="C-HA006A", CustomerName="Loyal Site", ParentRecord="C-HA006")
		)
		renamed = importer.upsert_organization(
			C(NoteID="ha-6", CustomerID="C-HA006", CustomerName="After Name")
		)
		self.assertNotEqual(head, renamed)
		self.assertEqual(_head(site), ("C-HA006", renamed))


class LinkHeadAccountsTest(ImporterTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _run(self, records, enabled=True):
		client = MagicMock()
		client.iter_all.return_value = records
		settings = frappe._dict(enabled=enabled)
		with (
			patch.object(importer, "get_settings", return_value=settings),
			patch.object(importer, "AcumaticaClient", return_value=client),
			patch.object(importer.frappe.db, "commit"),
		):
			result = importer.link_head_accounts()
		return result, client

	def test_customers_imported_before_the_field_are_filled_in(self):
		head = importer.upsert_organization(C(NoteID="lh-1", CustomerID="C-LH001", CustomerName="Fill Head"))
		site = importer.upsert_organization(
			C(NoteID="lh-1a", CustomerID="C-LH001A", CustomerName="Fill Site")
		)
		result, client = self._run(
			[C(CustomerID="C-LH001"), C(CustomerID="C-LH001A", ParentRecord="C-LH001")]
		)
		self.assertEqual(_head(site), ("C-LH001", head))
		self.assertEqual(result["changed"], 1)
		self.assertEqual(client.iter_all.call_args.kwargs["select"], "CustomerID,ParentRecord")
		client.logout.assert_called_once()
		# a second run has nothing left to write
		self.assertEqual(
			self._run([C(CustomerID="C-LH001"), C(CustomerID="C-LH001A", ParentRecord="C-LH001")])[0][
				"changed"
			],
			0,
		)

	def test_it_does_nothing_with_the_integration_off(self):
		result, client = self._run([], enabled=False)
		self.assertIn("skipped", result)
		client.iter_all.assert_not_called()


class HeadAccountSearchTest(ImporterTestCase):
	def test_the_head_account_is_a_search_field(self):
		ensure_customer_code_search()
		fields = frappe.get_meta("CRM Organization").search_fields.split(",")
		self.assertIn("acumatica_id", fields)
		self.assertIn("head_account", fields)

	def test_an_older_search_setup_gains_the_head_account(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		make_property_setter(
			"CRM Organization", None, "search_fields", "acumatica_id,industry", "Data", for_doctype=True
		)
		frappe.clear_cache(doctype="CRM Organization")
		ensure_customer_code_search()
		frappe.clear_cache(doctype="CRM Organization")
		fields = frappe.get_meta("CRM Organization").search_fields.split(",")
		self.assertEqual(fields, ["acumatica_id", "head_account", "industry"])
		frappe.db.rollback()
		frappe.clear_cache(doctype="CRM Organization")

	def test_the_side_panel_patch_puts_it_beside_the_vat_number(self):
		from crm.patches.v1_0 import link_customer_head_accounts as patch_module

		layout = [
			{"name": "s", "columns": [{"name": "c", "fields": ["acumatica_id", "tax_registration_id"]}]}
		]
		name = patch_module.LAYOUT
		existed = frappe.db.exists("CRM Fields Layout", name)
		doc = (
			frappe.get_doc("CRM Fields Layout", name)
			if existed
			else frappe.new_doc("CRM Fields Layout").update({"dt": "CRM Organization", "type": "Side Panel"})
		)
		doc.layout = json.dumps(layout)
		doc.save(ignore_permissions=True)
		with patch.object(patch_module.frappe, "enqueue") as enqueue:
			patch_module.execute()
			patch_module.execute()
		fields = json.loads(frappe.db.get_value("CRM Fields Layout", name, "layout"))[0]["columns"][0][
			"fields"
		]
		self.assertEqual(fields, ["acumatica_id", "tax_registration_id", "head_account"])
		enqueue.assert_not_called()  # the integration is off on the test site
		frappe.db.rollback()
