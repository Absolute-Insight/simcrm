# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

REP = "enrichrun-rep@crmtest.test"
OTHER = "enrichrun-other@crmtest.test"
MANAGER = "enrichrun-manager@crmtest.test"


class TestEnrichmentRunScoping(IntegrationTestCase):
	"""A run records what was scraped for one lead or deal -- company, emails,
	phones, the raw extraction -- and Sales User may read the doctype. Without
	row scoping a rep listed every run on the site, whatever the hierarchy hid on
	the record itself (upstream frappe/crm #3062)."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email, name, role in (
			(REP, "Enrich Rep", "Sales User"),
			(OTHER, "Enrich Other", "Sales User"),
			(MANAGER, "Enrich Manager", "Sales Manager"),
		):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True).add_roles(role)

		self.own_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": REP}
		).insert(ignore_permissions=True)
		self.hidden_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Hidden", "lead_owner": OTHER}
		).insert(ignore_permissions=True)
		deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": OTHER, "organization": "Hidden Org"})
		deal.flags.ignore_mandatory = True
		deal.flags.ignore_links = True
		self.hidden_deal = deal.insert(ignore_permissions=True)

		self.own_run = self.make_run("CRM Lead", self.own_lead.name)
		self.hidden_lead_run = self.make_run("CRM Lead", self.hidden_lead.name)
		self.hidden_deal_run = self.make_run("CRM Deal", self.hidden_deal.name)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def make_run(self, doctype, name):
		return frappe.get_doc(
			{
				"doctype": "CRM Enrichment Run",
				"reference_doctype": doctype,
				"reference_name": name,
				"status": "Completed",
				"raw_json": '{"emails": ["ceo@hidden.example"]}',
			}
		).insert(ignore_permissions=True)

	def listed(self):
		names = {self.own_run.name, self.hidden_lead_run.name, self.hidden_deal_run.name}
		return set(frappe.get_list("CRM Enrichment Run", filters={"name": ("in", list(names))}, pluck="name"))

	def test_a_rep_lists_only_runs_on_records_they_can_read(self):
		frappe.set_user(REP)
		self.assertEqual(self.listed(), {self.own_run.name})

	def test_a_rep_cannot_open_a_run_on_a_hidden_lead_or_deal(self):
		frappe.set_user(REP)
		self.assertTrue(frappe.has_permission("CRM Enrichment Run", "read", doc=self.own_run.name))
		for run in (self.hidden_lead_run, self.hidden_deal_run):
			self.assertFalse(frappe.has_permission("CRM Enrichment Run", "read", doc=run.name))
			with self.assertRaises(frappe.PermissionError):
				frappe.client.get("CRM Enrichment Run", run.name)

	def test_a_run_on_an_unscoped_doctype_stays_visible(self):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Enrich Scoping Org"}
		).insert(ignore_permissions=True)
		run = self.make_run("CRM Organization", org.name)
		frappe.set_user(REP)
		self.assertEqual(
			frappe.get_list("CRM Enrichment Run", filters={"name": run.name}, pluck="name"), [run.name]
		)
		self.assertTrue(frappe.has_permission("CRM Enrichment Run", "read", doc=run.name))

	def test_administrator_sees_every_run(self):
		self.assertEqual(
			self.listed(), {self.own_run.name, self.hidden_lead_run.name, self.hidden_deal_run.name}
		)

	def test_retry_refuses_a_run_on_a_hidden_record(self):
		"""``retry`` loaded the run with no read check, so its errors told a rep
		that a run existed and which doctype it pointed at."""
		from crm.domain_enrichment import api

		frappe.set_user(REP)
		# refused on the run itself, before the target is loaded or anything queued
		with (
			patch.object(api, "get_config") as get_config,
			patch.object(api, "_enqueue_run") as enqueue,
			self.assertRaises(frappe.PermissionError),
		):
			api.retry(self.hidden_lead_run.name)
		get_config.assert_not_called()
		enqueue.assert_not_called()

	def manager_scope(self, scope):
		saved = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", scope)
		self.addCleanup(
			frappe.db.set_single_value,
			"CRM Access Settings",
			"manager_outside_hierarchy",
			saved or "All records",
		)

	def test_a_manager_outside_the_hierarchy_at_all_records_sees_every_run(self):
		self.manager_scope("All records")
		frappe.set_user(MANAGER)
		self.assertEqual(
			self.listed(), {self.own_run.name, self.hidden_lead_run.name, self.hidden_deal_run.name}
		)

	def test_a_manager_outside_the_hierarchy_at_own_records_sees_only_their_own(self):
		self.manager_scope("Own records only")
		frappe.set_user(MANAGER)
		self.assertEqual(self.listed(), set())
