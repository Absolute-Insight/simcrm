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

	def test_a_name_collision_with_another_customer_is_refused(self):
		importer.upsert_organization(C(CustomerID="C-A", CustomerName="Twin Ltd"))
		with self.assertRaisesRegex(ValueError, "already belongs"):
			importer.upsert_organization(C(CustomerID="C-B", CustomerName="Twin Ltd"))

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
		"""An organization already linked to a DIFFERENT Acumatica customer. A customer
		arriving under that name is refused rather than merged into it, which is the
		shape of failure an admin fixes in Acumatica and expects the CRM to pick up."""
		name = f"Contested {suffix}"
		frappe.get_doc({"doctype": "CRM Organization", "organization_name": name}).insert(
			ignore_permissions=True
		)
		frappe.db.set_value("CRM Organization", name, "acumatica_id", f"OTHER{suffix}")
		# tearDown clears out everything carrying this suffix -- this row and whatever
		# the importer went on to write under it
		self._retry_suffixes.append(suffix)
		return name

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
		client.get_page.return_value = [bad]

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
		client.get_page.return_value = [bad]

		importer.run_backfill()
		self.assertEqual(self._pending()["Customer"][f"retry-{suffix}"], 1)

		# the admin renames the customer in Acumatica; the retry re-fetches it and it lands
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		client.get_page.return_value = [_customer(suffix, f"Freed {suffix}")]

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
		client.get_page.return_value = [bad]

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
		client.get_page.side_effect = RuntimeError("Acumatica GET Customer -> 503")
		for _ in range(importer.MAX_RETRY_ATTEMPTS - 1):
			importer.run_backfill()  # must not let a dead endpoint abort the sweep

		self.assertEqual(self._pending(), {})
		issues = [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == f"retry-{suffix}"
		]
		self.assertEqual([row.kind for row in issues], ["Gave Up"])

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
