import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import importer
from crm.integrations.acumatica.install import ensure_custom_fields


def C(**kw):
	"""Build a wrapped Acumatica record from plain values."""
	return {k: {"value": v} for k, v in kw.items()}


def _customer(suffix, name):
	"""The customer the retry tests push through the sweep, unique per run: run_backfill
	commits, so anything these tests import is still there on the next suite run."""
	return C(NoteID=f"retry-{suffix}", CustomerID=f"RETRY{suffix}", CustomerName=name)


class ImporterTestCase(FrappeTestCase):
	"""Create the identity custom fields this module queries.

	They are not part of the schema of a site that never turned Acumatica on:
	``create_custom_fields_for_acumatica_in_crm`` is guarded on the setting, so on a
	fresh install -- which is every CI run -- it does nothing. Nothing in this module
	enables the integration, so every ``acumatica_noteid`` lookup here used to depend on
	some *other* module issuing the DDL first (``test_outbound._enable()`` saving the
	Single, or ``test_crm_acumatica_settings`` calling this function). Test discovery
	order is filesystem order, so that made the whole module fail or pass by luck of the
	inode -- 1054 "Unknown column 'acumatica_noteid'" on the runs where it lost."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()


class TestUpserts(ImporterTestCase):
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

	def test_a_second_customer_with_a_taken_name_is_created_with_its_id_as_a_suffix(self):
		"""MBP's tenant has three accounts named "Sibanye Rustenburg Platinum Mines (Pty)
		Ltd". CRM Organization autonames on the name, so the second collided in the
		database and was queued for a retry that fails the same way every night."""
		importer.upsert_organization(
			C(NoteID="g-sib-1", CustomerID="C-SIB001", CustomerName="Sibanye Twin Ltd")
		)
		second = importer.upsert_organization(
			C(NoteID="g-sib-2", CustomerID="C-SIB002", CustomerName="Sibanye Twin Ltd")
		)
		self.assertEqual(second, "Sibanye Twin Ltd (C-SIB002)")
		self.assertEqual(frappe.db.get_value("CRM Organization", second, "acumatica_noteid"), "g-sib-2")
		# the first keeps its plain name and its own link
		self.assertEqual(
			frappe.db.get_value("CRM Organization", "Sibanye Twin Ltd", "acumatica_noteid"), "g-sib-1"
		)
		# and a re-sync of the second finds it by NoteID, not by making a third
		self.assertEqual(
			importer.upsert_organization(
				C(NoteID="g-sib-2", CustomerID="C-SIB002", CustomerName="Sibanye Twin Ltd")
			),
			second,
		)

	def test_an_unusable_phone_does_not_block_the_contact(self):
		"""Acumatica's Phone1 held a street address on a few hundred of MBP's contacts:
		"12 Delfos Boulevard is not a valid Phone Number" failed the whole person."""
		name = importer.upsert_contact(
			C(
				NoteID="g-ph-1",
				ContactID=9001,
				FirstName="Thabo",
				LastName="Address",
				Phone1="12 Delfos Boulevard",
				Email="thabo.address@example.test",
			)
		)
		doc = frappe.get_doc("Contact", name)
		self.assertEqual([row.phone for row in doc.phone_nos], [])
		self.assertEqual([row.email_id for row in doc.email_ids], ["thabo.address@example.test"])

	def test_a_namesake_already_linked_elsewhere_becomes_a_second_contact(self):
		"""Two Acumatica contacts with the same name at the same customer are two people
		(or a duplicate the office should merge) -- either way the second is not
		"already linked", it is new."""
		importer.upsert_organization(
			C(NoteID="g-org-twin", CustomerID="C-TWIN01", CustomerName="Twin Contacts Ltd")
		)
		first = importer.upsert_contact(
			C(NoteID="g-c-1", ContactID=9101, FirstName="Portia", LastName="Twin", BusinessAccount="C-TWIN01")
		)
		second = importer.upsert_contact(
			C(NoteID="g-c-2", ContactID=9102, FirstName="Portia", LastName="Twin", BusinessAccount="C-TWIN01")
		)
		self.assertNotEqual(first, second)
		self.assertEqual(frappe.db.get_value("Contact", first, "acumatica_noteid"), "g-c-1")
		self.assertEqual(frappe.db.get_value("Contact", second, "acumatica_noteid"), "g-c-2")

	def test_a_long_item_description_is_cut_for_the_name_and_kept_whole(self):
		long = "450mm Water Trap, Mild Steel Galvanised Body, Flanged to SABS 1123 Table 1000/1600, 10 Bar Rated, Stainless Steel Drain Valve, T-Section complete with Mechanical Autodrain and Sight Glass"
		self.assertGreater(len(long), 140)
		name = importer.upsert_product(
			C(NoteID="g-it-long", InventoryID="2WTFO-TEST", Description=long, DefaultPrice=1.0)
		)
		doc = frappe.get_doc("CRM Product", name)
		self.assertLessEqual(len(doc.product_name), 140)
		self.assertTrue(doc.product_name.endswith("…"))
		self.assertIn(long, doc.description)

	def test_a_record_without_noteid_never_adopts_a_stranger(self):
		# an unrelated org with no NoteID must not be returned by a NULL lookup
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Bystander Ltd"}).insert()
		name = importer.upsert_organization(C(CustomerID="C-NEW01", CustomerName="Newcomer Ltd"))
		self.assertEqual(name, "Newcomer Ltd")
		self.assertIsNone(frappe.db.get_value("CRM Organization", "Bystander Ltd", "acumatica_id"))

	def test_a_record_without_noteid_reuses_the_org_with_its_customer_id(self):
		# a different CustomerName on the second call means the organization_name
		# fallback would find a DIFFERENT (nonexistent) row -- only the acumatica_id
		# lookup can make this reuse the first call's org rather than duplicate it.
		first = importer.upsert_organization(C(CustomerID="C-REP01", CustomerName="Repeat Ltd"))
		second = importer.upsert_organization(C(CustomerID="C-REP01", CustomerName="Repeat Limited"))
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("CRM Organization", {"acumatica_id": "C-REP01"}), 1)
		self.assertEqual(
			frappe.db.get_value("CRM Organization", first, "organization_name"), "Repeat Limited"
		)

	def test_a_name_collision_with_another_customer_is_not_merged(self):
		"""Two Acumatica customers, one name: never one CRM Organization. It used to be
		refused outright; now the second lives under its ID, and the first is untouched."""
		importer.upsert_organization(C(CustomerID="C-A", CustomerName="Twin Ltd"))
		second = importer.upsert_organization(C(CustomerID="C-B", CustomerName="Twin Ltd"))
		self.assertEqual(second, "Twin Ltd (C-B)")
		self.assertEqual(frappe.db.get_value("CRM Organization", "Twin Ltd", "acumatica_id"), "C-A")

	def test_a_record_without_noteid_does_not_erase_a_synced_noteid(self):
		importer.upsert_organization(C(NoteID="guid-keep", CustomerID="C-KEEP1", CustomerName="Keeper Ltd"))
		importer.upsert_organization(C(CustomerID="C-KEEP1", CustomerName="Keeper Ltd"))
		self.assertEqual(
			frappe.db.get_value("CRM Organization", "Keeper Ltd", "acumatica_noteid"), "guid-keep"
		)


class TestAdoptOnMatch(ImporterTestCase):
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

	def test_upsert_contact_adopts_a_namesake_inside_the_same_company(self):
		"""A name is only an identity within one company, so adoption by name needs the
		BusinessAccount to resolve to a CRM Organization first."""
		last = f"Adoptee{frappe.generate_hash(length=6)}"
		customer_id = f"ADOPT{frappe.generate_hash(length=5)}"
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Adopting-{frappe.generate_hash(length=6)}"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", customer_id)
		existing = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Ana", "last_name": last, "company_name": org.name}
		).insert(ignore_permissions=True)

		name = importer.upsert_contact(
			C(
				NoteID="g-adopt-4",
				ContactID="41",
				FirstName="Ana",
				LastName=last,
				BusinessAccount=customer_id,
			)
		)

		self.assertEqual(name, existing.name)
		self.assertEqual(frappe.db.get_value("Contact", name, "acumatica_noteid"), "g-adopt-4")
		self.assertEqual(frappe.db.count("Contact", {"first_name": "Ana", "last_name": last}), 1)

	def test_a_namesake_at_an_unresolved_company_is_not_adopted(self):
		"""With no organization to scope the name by, "Ana Diaz" at one customer would
		otherwise adopt -- and take over the NoteID of -- her namesake at another.
		Only a primary-email match identifies a person across companies."""
		last = f"Namesake{frappe.generate_hash(length=6)}"
		stranger = frappe.get_doc({"doctype": "Contact", "first_name": "Ana", "last_name": last}).insert(
			ignore_permissions=True
		)

		# BusinessAccount names a customer this site has never imported, so it
		# resolves to no organization -- and the record carries no email.
		name = importer.upsert_contact(
			C(NoteID="g-namesake", ContactID="42", FirstName="Ana", LastName=last, BusinessAccount="NOPE")
		)

		self.assertNotEqual(name, stranger.name)
		self.assertFalse(frappe.db.get_value("Contact", stranger.name, "acumatica_noteid"))

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


class TestBackfill(ImporterTestCase):
	def setUp(self):
		super().setUp()
		self._retry_suffixes = []

	def tearDown(self):
		frappe.db.rollback()
		# run_backfill commits, so what it left behind outlives that rollback -- both a
		# queued retry or a recorded crash on the Single, and the organizations these
		# tests fed through the importer, which would otherwise litter the site with a
		# fresh set on every suite run.
		for suffix in self._retry_suffixes:
			for name in frappe.get_all(
				"CRM Organization", filters={"organization_name": ("like", f"%{suffix}")}, pluck="name"
			):
				frappe.delete_doc(
					"CRM Organization", name, force=True, ignore_permissions=True, delete_permanently=True
				)
		frappe.db.set_single_value("CRM Acumatica Settings", "pending_retries", "{}")
		frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", "")
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def _pending(self):
		return json.loads(frappe.db.get_single_value("CRM Acumatica Settings", "pending_retries") or "{}")

	def _contested_org(self, suffix):
		"""An organization carrying the incoming customer's ID but a DIFFERENT NoteID.
		The importer refuses to steal a link (see ``_adopt``), so the record fails on
		every sweep until an admin fixes the link -- the shape of failure the retry
		queue exists for. (A plain name collision used to play this part; since a
		second customer with a taken name is now created under its ID, it no longer
		fails at all.)"""
		name = f"Contested {suffix}"
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": name}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value(
			"CRM Organization",
			name,
			{"acumatica_id": f"RETRY{suffix}", "acumatica_noteid": f"other-{suffix}"},
		)
		# tearDown clears out everything carrying this suffix -- this row and whatever
		# the importer went on to write under it
		self._retry_suffixes.append(suffix)
		return name

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_sync_logs_out_when_it_finishes_and_when_it_dies(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		client.settings.request_pause = 0
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		importer.run_backfill()
		client.logout.assert_called_once()

		client.iter_all.side_effect = RuntimeError("token expired mid-run")
		with self.assertRaises(RuntimeError):
			importer.run_backfill()
		self.assertEqual(client.logout.call_count, 2)

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_run_backfill_counts_and_records_issue_on_bad_record(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0

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
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
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
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		record_sync_issue_mock.side_effect = Exception("boom")

		def fake_iter(entity, **kw):
			if entity == "Customer":
				return iter([C(NoteID=None, CustomerID="BAD")])  # triggers the except path
			return iter([])

		client.iter_all.side_effect = fake_iter

		out = importer.run_backfill()  # must not raise even though record_sync_issue blew up

		self.assertEqual(out["issues"], 1)
		self.assertIsNotNone(frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at"))

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_failed_record_is_retried_next_sweep_and_given_up_after_the_cap(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		bad = _customer(suffix, self._contested_org(suffix))
		client.iter_all.side_effect = lambda entity, **kw: iter([bad] if entity == "Customer" else [])
		client.get_by_id.return_value = bad

		importer.run_backfill()

		self.assertEqual(self._pending()["Customer"][f"retry-{suffix}"], 1)

		# Acumatica never sends the record again -- it was not modified, only mishandled.
		# Only the queue keeps it in front of the importer.
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		for _ in range(importer.MAX_RETRY_ATTEMPTS - 1):
			importer.run_backfill()

		self.assertNotIn(f"retry-{suffix}", self._pending().get("Customer", {}))
		issues = [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == f"RETRY{suffix}"
		]
		# one row when it first failed, one when the retries ran out -- not one per sweep
		self.assertEqual([row.kind for row in issues], ["Import Failed", "Gave Up"])

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_retried_record_that_now_succeeds_leaves_the_queue(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		bad = _customer(suffix, self._contested_org(suffix))
		client.iter_all.side_effect = lambda entity, **kw: iter([bad] if entity == "Customer" else [])
		client.get_by_id.return_value = bad

		importer.run_backfill()
		self.assertEqual(self._pending()["Customer"][f"retry-{suffix}"], 1)

		# the admin clears the stale link on the CRM side; the retry re-fetches the
		# record, adopts the organization by its ID and it lands
		frappe.db.set_value("CRM Organization", f"Contested {suffix}", "acumatica_noteid", None)
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		client.get_by_id.return_value = _customer(suffix, f"Freed {suffix}")

		importer.run_backfill()

		self.assertEqual(self._pending(), {})
		self.assertEqual(
			frappe.db.get_value(
				"CRM Organization", {"acumatica_noteid": f"retry-{suffix}"}, "organization_name"
			),
			f"Freed {suffix}",
		)

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_record_that_fails_in_both_passes_still_runs_out_of_attempts(self, ClientCls):
		"""A backfill -- start_backfill, or the first sweep of all -- passes no
		high-water mark, so it re-scans the very records the retry pass has just tried.
		Treating that second failure as a fresh queue entry would put the record back to
		one attempt every single run, and it would never reach the cap."""
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		bad = _customer(suffix, self._contested_org(suffix))
		# offered by BOTH passes on every run, which is what an unfiltered backfill does
		client.iter_all.side_effect = lambda entity, **kw: iter([bad] if entity == "Customer" else [])
		client.get_by_id.return_value = bad

		for _ in range(importer.MAX_RETRY_ATTEMPTS):
			importer.run_backfill()

		kinds = [
			row.kind
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == f"RETRY{suffix}"
		]
		# one failure per run, then the give-up inside the last one -- and, after it, that
		# run's own main-loop failure, which a backfill re-offering the record earns fairly
		self.assertEqual(
			kinds, ["Import Failed"] * (importer.MAX_RETRY_ATTEMPTS - 1) + ["Gave Up", "Import Failed"]
		)

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_retry_whose_re_fetch_fails_gives_up_on_the_noteid_it_has(self, ClientCls):
		"""The re-fetch is a call of its own and can be the thing that fails. There is
		no record to name that issue after then, only the guid the queue is keyed by."""
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		bad = _customer(suffix, self._contested_org(suffix))
		client.iter_all.side_effect = lambda entity, **kw: iter([bad] if entity == "Customer" else [])

		importer.run_backfill()

		client.iter_all.side_effect = lambda entity, **kw: iter([])
		client.get_by_id.side_effect = RuntimeError("Acumatica GET Customer -> 503")
		for _ in range(importer.MAX_RETRY_ATTEMPTS - 1):
			importer.run_backfill()  # must not let a dead endpoint abort the sweep

		self.assertEqual(self._pending(), {})
		issues = [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == f"retry-{suffix}"
		]
		self.assertEqual([row.kind for row in issues], ["Gave Up"])

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_job_timeout_ends_the_run_instead_of_blaming_the_record(self, ClientCls):
		"""rq raises JobTimeoutException inside whatever line the job's time limit
		interrupts, and it subclasses Exception -- so the per-record handler used to
		swallow the run's own deadline, log a healthy record as Import Failed, queue it
		for retry, and carry on through every remaining page with no limit at all."""
		client = MagicMock()
		ClientCls.return_value = client
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		rec = _customer(suffix, f"Timeout {suffix}")
		client.iter_all.side_effect = lambda entity, **kw: iter([rec] if entity == "Customer" else [])

		def timed_out(record):
			raise importer.JobTimeoutException("Task exceeded maximum timeout value")

		# _ENTITIES binds the upsert functions at import time, so the fake goes there.
		with patch.object(importer, "_ENTITIES", (("Customer", timed_out, "customers"),)):
			with self.assertRaises(importer.JobTimeoutException):
				importer.run_backfill()

		issues = [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == f"RETRY{suffix}"
		]
		self.assertEqual(issues, [], "the run's deadline is not the record's fault")
		self.assertNotIn(f"retry-{suffix}", self._pending().get("Customer", {}))

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_run_that_crashes_keeps_the_retry_attempt_it_counted(self, ClientCls):
		"""Retry state used to be written only on a clean finish, so a record that
		fails every sweep AND crashes the run behind it never reached the give-up cap:
		its attempt count evaporated with the crash, every single time."""
		client = MagicMock()
		ClientCls.return_value = client
		client.settings.request_pause = 0
		suffix = frappe.generate_hash(length=6)
		bad = _customer(suffix, self._contested_org(suffix))
		client.iter_all.side_effect = lambda entity, **kw: iter([bad] if entity == "Customer" else [])
		client.get_by_id.return_value = bad

		importer.run_backfill()
		self.assertEqual(self._pending()["Customer"][f"retry-{suffix}"], 1)

		# The retry pass tries it again and it fails again (attempt 2); then the run
		# dies outside any one record -- expired credentials, a dropped connection.
		def dead_endpoint(entity, **kw):
			raise RuntimeError("token expired")

		client.iter_all.side_effect = dead_endpoint

		with self.assertRaises(RuntimeError):
			importer.run_backfill()

		self.assertEqual(self._pending()["Customer"][f"retry-{suffix}"], 2)

	def test_two_syncs_do_not_run_at_once(self):
		"""The manual backfill, the webhook and the scheduler all reach run_backfill;
		two of them importing the same page at once race over the same documents."""
		from frappe.utils.synchronization import filelock

		with filelock("acumatica_sync", timeout=0):
			self.assertEqual(importer.run_backfill(), {"skipped": "another sync is running"})

	def test_a_crashing_run_leaves_its_error_on_the_settings(self):
		"""A run that dies outside any one record -- expired credentials, a dropped
		connection -- otherwise leaves an admin nothing but a mark that stopped moving."""
		with patch("crm.integrations.acumatica.importer.AcumaticaClient", side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				importer.run_backfill()

		self.assertIn("boom", frappe.db.get_single_value("CRM Acumatica Settings", "last_sync_error"))

	@patch("crm.integrations.acumatica.importer.AcumaticaClient")
	def test_a_clean_run_clears_the_last_error(self, ClientCls):
		client = MagicMock()
		ClientCls.return_value = client
		# MagicMock's default __float__ is 1.0, not 0 -- unset this and _retry_pending's
		# new inter-request pause (mirroring the paging loop's) turns every retry test
		# into a real sleep.
		client.settings.request_pause = 0
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		frappe.db.set_single_value("CRM Acumatica Settings", "last_sync_error", "an older failure")

		importer.run_backfill()

		self.assertFalse(frappe.db.get_single_value("CRM Acumatica Settings", "last_sync_error"))


class TestScheduleSweep(FrappeTestCase):
	"""The scheduler hands the sweep to the long queue rather than running it inline:
	a first backfill takes hours, and the scheduler's own worker has other jobs."""

	def setUp(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 1)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	def tearDown(self):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		# an `enabled` that leaked out of this module would send every later test's
		# deal save at a real Acumatica instance
		frappe.db.commit()  # nosemgrep: frappe-manual-commit
		frappe.clear_cache(doctype="CRM Acumatica Settings")

	@patch("crm.integrations.acumatica.importer.frappe.enqueue")
	def test_it_queues_the_sweep_under_the_one_sync_job_id(self, enqueue):
		importer.schedule_sweep()

		self.assertEqual(enqueue.call_args[0][0], "crm.integrations.acumatica.importer.nightly_sweep")
		self.assertEqual(enqueue.call_args.kwargs["queue"], "long")
		self.assertEqual(enqueue.call_args.kwargs["job_id"], importer.SYNC_JOB_ID)
		self.assertEqual(enqueue.call_args.kwargs["timeout"], importer.BACKFILL_TIMEOUT)

	@patch("crm.integrations.acumatica.importer.frappe.enqueue")
	def test_it_does_nothing_while_the_integration_is_off(self, enqueue):
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

		importer.schedule_sweep()

		enqueue.assert_not_called()
