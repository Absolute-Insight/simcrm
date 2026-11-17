"""A customer's head account: Acumatica's ParentRecord, kept on the organization.

MBP files a mine's plants and shafts as customers of their own under one head
account. The sync records which one, a site imported before its head account is
linked when the head account arrives, and a one-off pass fills in the customers
imported before the field existed.
"""

from unittest.mock import MagicMock, patch

import frappe

from crm.integrations.acumatica import importer
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

	def test_a_failure_is_recorded_where_the_syncs_are(self):
		client = MagicMock()
		client.iter_all.side_effect = RuntimeError("tenant down")
		with (
			patch.object(importer, "get_settings", return_value=frappe._dict(enabled=True)),
			patch.object(importer, "AcumaticaClient", return_value=client),
			patch.object(importer.frappe.db, "commit"),
			patch.object(importer.frappe.db, "rollback"),
			self.assertRaises(RuntimeError),
		):
			importer.link_head_accounts()
		self.assertIn(
			"tenant down", frappe.db.get_single_value("CRM Acumatica Settings", "last_sync_error") or ""
		)
		client.logout.assert_called_once()

	def test_it_stands_aside_while_a_sweep_runs(self):
		from frappe.utils.synchronization import filelock

		with (
			patch.object(importer, "get_settings", return_value=frappe._dict(enabled=True)),
			patch.object(importer, "AcumaticaClient") as client,
			filelock(importer.SYNC_JOB_ID),
		):
			self.assertIn("skipped", importer.link_head_accounts())
		client.assert_not_called()

	def test_it_does_nothing_with_the_integration_off(self):
		result, client = self._run([], enabled=False)
		self.assertIn("skipped", result)
		client.iter_all.assert_not_called()


class HeadAccountVisibilityTest(ImporterTestCase):
	"""A rep never reads a head account's name, and finds a site by it only when
	the head account is theirs to read too."""

	def setUp(self):
		from crm.tests.test_row_permissions import ensure_rep

		ensure_rep("ha-alice@crmtest.test", "Alice")
		ensure_rep("ha-bob@crmtest.test", "Bob")
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.open_head = importer.upsert_organization(
			C(NoteID="hv-1", CustomerID="C-HV001", CustomerName="Openmine Group")
		)
		self.open_site = importer.upsert_organization(
			C(NoteID="hv-1a", CustomerID="C-HV001A", CustomerName="Eastplant Works", ParentRecord="C-HV001")
		)
		self.hidden_head = importer.upsert_organization(
			C(NoteID="hv-2", CustomerID="C-HV002", CustomerName="Hiddenmine Group")
		)
		self.hidden_site = importer.upsert_organization(
			C(NoteID="hv-2a", CustomerID="C-HV002A", CustomerName="Westplant Works", ParentRecord="C-HV002")
		)
		frappe.db.set_value("CRM Organization", self.hidden_head, "account_owner", "ha-bob@crmtest.test")
		frappe.db.set_value("CRM Organization", self.hidden_site, "account_owner", "ha-alice@crmtest.test")
		frappe.set_user("ha-alice@crmtest.test")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def names(self, query):
		from crm.api.command_palette import search

		return [m["name"] for m in search(query)["matches"] if m["doctype"] == "CRM Organization"]

	def test_a_rep_cannot_read_the_head_account_field(self):
		doc = frappe.get_doc("CRM Organization", self.hidden_site)
		doc.apply_fieldlevel_read_permissions()
		self.assertIsNone(doc.get("head_account"))
		self.assertIsNone(doc.get("acumatica_parent"))

	def test_a_sales_manager_cannot_read_it_either(self):
		frappe.set_user("Administrator")
		user = frappe.get_doc("User", "ha-alice@crmtest.test")
		user.add_roles("Sales Manager")
		# rollback undoes the role, not the role cache the tests after this read
		self.addCleanup(frappe.clear_cache, user="ha-alice@crmtest.test")
		frappe.set_user("ha-alice@crmtest.test")
		doc = frappe.get_doc("CRM Organization", self.hidden_site)
		doc.apply_fieldlevel_read_permissions()
		self.assertIsNone(doc.get("head_account"))

	def test_searching_a_readable_head_account_finds_its_sites(self):
		self.assertEqual(set(self.names("Openmine")), {self.open_head, self.open_site})

	def test_searching_a_hidden_head_account_finds_nothing(self):
		self.assertEqual(self.names("Hiddenmine"), [])

	def test_a_found_site_carries_no_hidden_name(self):
		from crm.api.command_palette import search

		[match] = [m for m in search("Westplant")["matches"] if m["name"] == self.hidden_site]
		self.assertNotIn("Hiddenmine", f"{match['keywords']} {match['detail']} {match['title']}")

	def test_a_link_search_does_not_describe_a_site_by_its_head_account(self):
		from frappe.desk.search import search_link

		results = search_link("CRM Organization", "Westplant")
		self.assertTrue(results)
		self.assertNotIn("Hiddenmine", str(results))


class HeadAccountPatchTest(ImporterTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_the_fields_are_for_managers_only(self):
		meta = frappe.get_meta("CRM Organization")
		self.assertEqual(meta.get_field("head_account").permlevel, 2)
		self.assertEqual(meta.get_field("acumatica_parent").permlevel, 2)
		levels = {(p.role, p.permlevel) for p in meta.permissions if p.read}
		self.assertIn(("System Manager", 2), levels)
		self.assertNotIn(("Sales Manager", 2), levels)
		self.assertNotIn(("Sales User", 2), levels)

	def test_a_stale_head_account_search_field_is_dropped(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		from crm.integrations.acumatica.install import ensure_customer_code_search

		make_property_setter(
			"CRM Organization",
			None,
			"search_fields",
			"acumatica_id,head_account,industry",
			"Data",
			for_doctype=True,
		)
		frappe.clear_cache(doctype="CRM Organization")
		ensure_customer_code_search()
		frappe.clear_cache(doctype="CRM Organization")
		self.assertEqual(frappe.get_meta("CRM Organization").search_fields, "acumatica_id,industry")
		frappe.db.rollback()
		frappe.clear_cache(doctype="CRM Organization")

	def test_the_patch_queues_nothing_with_the_integration_off(self):
		from crm.patches.v1_0 import link_customer_head_accounts as patch_module

		with patch.object(patch_module.frappe, "enqueue") as enqueue:
			patch_module.execute()
		enqueue.assert_not_called()

	def test_a_failing_enqueue_does_not_fail_the_migrate(self):
		from crm.patches.v1_0 import link_customer_head_accounts as patch_module

		with (
			patch.object(patch_module.frappe.db, "get_single_value", return_value=1),
			patch.object(patch_module.frappe, "enqueue", side_effect=ConnectionError("no redis")),
			patch.object(patch_module.frappe, "log_error") as log_error,
		):
			patch_module.execute()
		log_error.assert_called_once()
