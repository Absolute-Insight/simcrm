# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The two-year demo history: enough of it for every analytics window, and
gone without a trace when cleared."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.demo.deals import delete_demo_deals
from crm.demo.history import MONTHS_BACK, create_demo_history, delete_demo_history
from crm.demo.users import DEMO_USER_EMAILS, create_demo_users, delete_demo_users


class DemoHistoryTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_demo_users()
		cls.created = create_demo_history(DEMO_USER_EMAILS)

	@classmethod
	def tearDownClass(cls):
		delete_demo_history(cls.created)
		delete_demo_users(DEMO_USER_EMAILS)
		frappe.db.commit()
		super().tearDownClass()

	def test_every_month_of_the_window_has_leads_and_most_have_won_revenue(self):
		lead_dates = frappe.get_all(
			"CRM Lead", filters={"name": ["in", self.created["leads"]]}, pluck="creation"
		)
		months_with_leads = {str(d)[:7] for d in lead_dates}
		self.assertGreaterEqual(len(months_with_leads), MONTHS_BACK)

		closed = frappe.get_all(
			"CRM Deal", filters={"name": ["in", self.created["deals"]], "status": "Won"}, pluck="closed_date"
		)
		won_months = {str(d)[:7] for d in closed if d}
		self.assertGreaterEqual(len(won_months), MONTHS_BACK - 4)

	def test_the_dashboard_reads_the_history(self):
		from crm.api.dashboard import actual_by_month, forecast_accuracy_rows, plan_adherence, quota_in_period

		start = frappe.utils.add_months(frappe.utils.get_first_day(frappe.utils.today()), -12)
		end = frappe.utils.today()
		actual = actual_by_month(str(start), end)
		self.assertGreaterEqual(len([m for m, v in actual.items() if v > 0]), 8)
		self.assertGreater(quota_in_period(str(start), end), 0)
		adherence = plan_adherence(str(frappe.utils.add_days(end, -30)), end)[0]
		self.assertGreater(adherence["planned"], 0)
		self.assertTrue(any(row.get("forecasted") for row in forecast_accuracy_rows()))

	def test_open_deals_carry_a_stage_history_and_won_deals_a_closed_date(self):
		for name in self.created["deals"][:40]:
			deal = frappe.db.get_value("CRM Deal", name, ["status", "closed_date", "creation"], as_dict=True)
			logs = frappe.get_all(
				"CRM Status Change Log",
				filters={"parent": name},
				fields=["from_date", "to_date"],
				order_by="idx",
			)
			self.assertTrue(logs, name)
			self.assertEqual(str(logs[0]["from_date"])[:10], str(deal.creation)[:10], name)
			if deal.status == "Won":
				self.assertIsNotNone(deal.closed_date, name)
				self.assertLessEqual(str(deal.creation)[:10], str(deal.closed_date), name)

	def test_zz_delete_removes_everything_it_created(self):
		"""Runs last (unittest orders by name): tears the fixture down and checks nothing is left."""
		created = self.created
		delete_demo_history(created)
		for doctype, key in (
			("CRM Deal", "deals"),
			("CRM Lead", "leads"),
			("CRM Organization", "organizations"),
			("CRM Quota", "quotas"),
			("CRM Forecast Snapshot", "snapshots"),
			("CRM Rep Plan", "plans"),
			("Comment", "comments"),
		):
			names = created.get(key, [])
			if names:
				self.assertEqual(frappe.db.count(doctype, {"name": ["in", names]}), 0, doctype)


class DemoSeedingGuardsTest(IntegrationTestCase):
	"""The seeder's edges, one function at a time, without seeding two years."""

	def tearDown(self):
		frappe.db.rollback()

	def test_clearing_keeps_demo_rows_that_real_records_adopted(self):
		"""delete_doc(force=True) skips frappe's link check, so the LinkExistsError
		guard never fired: a demo industry, territory or organization a real record
		had picked up was deleted under it, and that record could no longer be saved."""
		for doctype, field, value in (
			("CRM Industry", "industry", "Demo Adopted Industry"),
			("CRM Industry", "industry", "Demo Unused Industry"),
			("CRM Territory", "territory_name", "Demo Adopted Territory"),
		):
			frappe.get_doc({"doctype": doctype, field: value}).insert(ignore_permissions=True)
		demo_org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Demo Adopted Smelter"}
		).insert(ignore_permissions=True)
		unused_org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Demo Unused Smelter"}
		).insert(ignore_permissions=True)
		real_org = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Real Adopting Customer",
				"industry": "Demo Adopted Industry",
				"territory": "Demo Adopted Territory",
			}
		).insert(ignore_permissions=True)
		frappe.get_doc(
			{"doctype": "CRM Deal", "status": "Qualification", "organization": demo_org.name}
		).insert(ignore_permissions=True)

		with patch.object(frappe.db, "commit"):
			delete_demo_history(
				{
					"industries": ["Demo Adopted Industry", "Demo Unused Industry"],
					"territories": ["Demo Adopted Territory"],
					"organizations": [demo_org.name, unused_org.name],
				}
			)

		self.assertTrue(frappe.db.exists("CRM Industry", "Demo Adopted Industry"))
		self.assertTrue(frappe.db.exists("CRM Territory", "Demo Adopted Territory"))
		self.assertTrue(frappe.db.exists("CRM Organization", demo_org.name))
		self.assertFalse(frappe.db.exists("CRM Industry", "Demo Unused Industry"))
		self.assertFalse(frappe.db.exists("CRM Organization", unused_org.name))
		real_org.reload()
		real_org.annual_revenue = 1_000_000
		real_org.save(ignore_permissions=True)  # was "Could not find Industry"

	def test_clearing_base_demo_deals_keeps_an_organization_a_real_deal_uses(self):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": "Demo Shared Refinery"}
		).insert(ignore_permissions=True)
		demo_deal = frappe.get_doc(
			{"doctype": "CRM Deal", "status": "Qualification", "organization": org.name}
		).insert(ignore_permissions=True)
		real_deal = frappe.get_doc(
			{"doctype": "CRM Deal", "status": "Qualification", "organization": org.name}
		).insert(ignore_permissions=True)

		delete_demo_deals({"deals": [demo_deal.name]}, [])

		self.assertFalse(frappe.db.exists("CRM Deal", demo_deal.name))
		self.assertTrue(frappe.db.exists("CRM Organization", org.name))
		frappe.get_doc("CRM Deal", real_deal.name).save(ignore_permissions=True)

	def test_clearing_disables_a_demo_user_a_real_record_adopted(self):
		"""Deleting the user under a real lead it owns would leave that lead
		unsaveable; the fake user is disabled instead, so it still cannot sign in."""
		email = "demo.adopted@crmtest.test"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Demo Adopted",
				"send_welcome_email": 0,
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Real Lead", "lead_owner": email}).insert(
			ignore_permissions=True
		)
		messages = list(frappe.local.message_log)

		delete_demo_users([email])

		self.assertTrue(frappe.db.exists("User", email))
		self.assertEqual(frappe.db.get_value("User", email, "enabled"), 0)
		self.assertEqual(frappe.db.get_value("CRM Lead", lead.name, "lead_owner"), email)
		# the refused delete is not reported to whoever cleared the demo
		self.assertEqual(frappe.local.message_log, messages)
