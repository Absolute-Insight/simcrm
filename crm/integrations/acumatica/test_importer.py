from datetime import datetime, timezone
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

	def test_upsert_product_renames_product_code_on_inventory_id_change(self):
		importer.upsert_product(C(NoteID="g-i2", InventoryID="OLDCODE", Description="Old", DefaultPrice=1))
		name = importer.upsert_product(
			C(NoteID="g-i2", InventoryID="NEWCODE", Description="New", DefaultPrice=2)
		)
		# field:product_code autoname re-derives the field from the docname on save
		self.assertEqual(frappe.db.get_value("CRM Product", name, "product_code"), "NEWCODE")
		self.assertEqual(frappe.db.get_value("CRM Product", name, "product_name"), "New")


class TestAdoptOnMatch(FrappeTestCase):
	"""A backfill onto a CRM that already holds the same customers must claim those
	records, not collide with them -- an unlinked org gets a SECOND Customer pushed
	back into Acumatica by the outbound hook."""

	def tearDown(self):
		frappe.db.rollback()

	def test_upsert_organization_adopts_pre_existing_org_by_name(self):
		org_name = f"Adopt Org {frappe.generate_hash(length=6)}"
		existing = frappe.get_doc({"doctype": "CRM Organization", "organization_name": org_name}).insert(
			ignore_permissions=True
		)
		self.assertFalse(existing.get("acumatica_noteid"))

		name = importer.upsert_organization(C(NoteID="g-adopt-1", CustomerID="ADOPT1", CustomerName=org_name))

		self.assertEqual(name, existing.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", name, "acumatica_noteid"), "g-adopt-1")
		self.assertEqual(frappe.db.get_value("CRM Organization", name, "acumatica_id"), "ADOPT1")
		self.assertEqual(
			frappe.db.count("CRM Organization", {"organization_name": org_name}),
			1,
		)

	def test_upsert_organization_refuses_to_steal_a_differently_linked_org(self):
		org_name = f"Claimed Org {frappe.generate_hash(length=6)}"
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": org_name}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value("CRM Organization", org_name, "acumatica_noteid", "g-other")

		with self.assertRaises(ValueError):
			importer.upsert_organization(C(NoteID="g-adopt-2", CustomerID="ADOPT2", CustomerName=org_name))

		self.assertEqual(frappe.db.get_value("CRM Organization", org_name, "acumatica_noteid"), "g-other")

	def test_upsert_product_adopts_pre_existing_product_by_code(self):
		code = f"ADOPT-{frappe.generate_hash(length=6)}"
		existing = frappe.get_doc(
			{"doctype": "CRM Product", "product_code": code, "product_name": "Local name"}
		).insert(ignore_permissions=True)

		name = importer.upsert_product(C(NoteID="g-adopt-3", InventoryID=code, Description="Remote name"))

		self.assertEqual(name, existing.name)
		self.assertEqual(frappe.db.get_value("CRM Product", name, "acumatica_noteid"), "g-adopt-3")
		self.assertEqual(frappe.db.count("CRM Product", {"product_code": code}), 1)

	def test_upsert_contact_adopts_pre_existing_contact_by_name(self):
		last = f"Adoptee{frappe.generate_hash(length=6)}"
		existing = frappe.get_doc({"doctype": "Contact", "first_name": "Ana", "last_name": last}).insert(
			ignore_permissions=True
		)

		name = importer.upsert_contact(C(NoteID="g-adopt-4", ContactID="41", FirstName="Ana", LastName=last))

		self.assertEqual(name, existing.name)
		self.assertEqual(frappe.db.get_value("Contact", name, "acumatica_noteid"), "g-adopt-4")
		self.assertEqual(frappe.db.count("Contact", {"first_name": "Ana", "last_name": last}), 1)

	def test_upsert_contact_adopts_on_primary_email_when_the_name_differs(self):
		email = f"{frappe.generate_hash(length=8)}@example.com"
		existing = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Robert",
				"last_name": f"Mail{frappe.generate_hash(length=6)}",
				"email_ids": [{"email_id": email, "is_primary": 1}],
			}
		).insert(ignore_permissions=True)

		name = importer.upsert_contact(
			C(NoteID="g-adopt-5", ContactID="51", FirstName="Bob", LastName="Renamed", Email=email)
		)

		self.assertEqual(name, existing.name)
		self.assertEqual(frappe.db.get_value("Contact", name, "acumatica_noteid"), "g-adopt-5")


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

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_run_backfill_stores_high_water_mark_as_naive_utc(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		client.iter_all.side_effect = lambda entity, **kw: iter([])

		importer.run_backfill()

		last_synced_at = frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at")
		now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
		# test_site resolves to UTC+5:30; a site-local (now_datetime()) capture
		# stored here would be off by hours, well outside this window.
		self.assertLessEqual(abs((now_utc - last_synced_at).total_seconds()), 120)

	@patch("crm.integrations.acumatica.importer.record_sync_issue")
	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_run_backfill_survives_a_failing_record_sync_issue_call(self, ClientCls, record_sync_issue_mock):
		client = MagicMock()
		ClientCls.return_value = client
		record_sync_issue_mock.side_effect = Exception("boom")

		def fake_iter(entity, **kw):
			if entity == "Customer":
				return iter([C(NoteID=None, CustomerID="BAD")])  # triggers the except path
			return iter([])

		client.iter_all.side_effect = fake_iter

		out = importer.run_backfill()  # must not raise even though record_sync_issue blew up

		self.assertEqual(out["issues"], 1)
		self.assertIsNotNone(frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at"))
