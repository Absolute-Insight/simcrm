from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import importer


def C(**kw):
	"""Build a wrapped Acumatica record from plain values."""
	return {k: {"value": v} for k, v in kw.items()}


class TestUpserts(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_upsert_organization_creates_then_updates(self):
		rec = C(NoteID="guid-org-1", CustomerID="ACME01", CustomerName="Acme Ltd")
		name = importer.upsert_organization(rec)
		org = frappe.get_doc("CRM Organization", name)
		self.assertEqual(org.organization_name, "Acme Ltd")
		self.assertEqual(org.acumatica_id, "ACME01")

		rec2 = C(NoteID="guid-org-1", CustomerID="ACME01", CustomerName="Acme Limited")
		name2 = importer.upsert_organization(rec2)
		self.assertEqual(name, name2)  # matched on NoteID, not created twice
		self.assertEqual(
			frappe.db.get_value("CRM Organization", name, "organization_name"),
			"Acme Limited",
		)

	def test_upsert_contact_links_organization(self):
		importer.upsert_organization(C(NoteID="g-o2", CustomerID="ORG2", CustomerName="Org Two"))
		name = importer.upsert_contact(
			C(
				NoteID="g-c1",
				ContactID="7",
				FirstName="Ana",
				LastName="Diaz",
				Email="ana@example.com",
				BusinessAccount="ORG2",
			)
		)
		contact = frappe.get_doc("Contact", name)
		self.assertEqual(contact.first_name, "Ana")
		self.assertEqual(contact.email_ids[0].email_id, "ana@example.com")
		org_name = frappe.db.get_value("CRM Organization", {"acumatica_id": "ORG2"}, "name")
		self.assertEqual(contact.company_name, org_name)

	def test_upsert_contact_without_name_returns_none(self):
		self.assertIsNone(importer.upsert_contact(C(NoteID="g-c9", ContactID="9")))

	def test_upsert_product_maps_price(self):
		name = importer.upsert_product(
			C(NoteID="g-i1", InventoryID="WIDGET", Description="A widget", DefaultPrice=12.5)
		)
		prod = frappe.get_doc("CRM Product", name)
		self.assertEqual(prod.product_code, "WIDGET")
		self.assertEqual(prod.standard_rate, 12.5)


class TestBackfill(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_run_backfill_counts_and_records_issue_on_bad_record(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client

		def fake_iter(entity, **kw):
			if entity == "Customer":
				return iter(
					[C(NoteID="g1", CustomerID="A1", CustomerName="One"), C(NoteID=None, CustomerID="BAD")]
				)  # no NoteID -> issue
			if entity == "Contact":
				return iter([])
			if entity == "StockItem":
				return iter([C(NoteID="g2", InventoryID="X", Description="X", DefaultPrice=1)])
			raise AssertionError(entity)

		client.iter_all.side_effect = fake_iter
		out = importer.run_backfill()
		self.assertEqual(out["customers"], 1)
		self.assertEqual(out["products"], 1)
		self.assertEqual(out["issues"], 1)
		self.assertIsNotNone(frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at"))

	def test_nightly_sweep_noop_when_disabled(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")  # get_settings() is cached
		importer.nightly_sweep()  # must not raise, must not call out
