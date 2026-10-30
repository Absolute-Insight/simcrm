# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The two-year demo history: enough of it for every analytics window, and
gone without a trace when cleared."""

from __future__ import annotations

import random
from datetime import date
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.demo.deals import delete_demo_deals
from crm.demo.history import (
	MONTHS_BACK,
	SEED,
	_create_snapshots,
	_settle_lead,
	create_demo_history,
	delete_demo_history,
)
from crm.demo.users import DEMO_USER_EMAILS, create_demo_users, delete_demo_users
from crm.fcrm.doctype.erpnext_crm_settings import erpnext_crm_settings
from crm.integrations.acumatica import outbound

ERP_PUSHES = (
	"crm.integrations.acumatica.outbound.push_customer_for_deal",
	"crm.fcrm.doctype.erpnext_crm_settings.erpnext_crm_settings.push_customer_for_deal",
)
PUSH_ON_WON = frappe._dict(enabled=1, create_customer_on_status_change=1, deal_status="Won")


class DemoHistoryTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		create_demo_users()
		# Seed the way a site with the Acumatica customer push switched on would,
		# recording the pushes instead of queueing them.
		cls.queued_pushes = []
		real_enqueue = frappe.enqueue

		def enqueue(method, *args, **kwargs):
			if method in ERP_PUSHES:
				cls.queued_pushes.append(method)
				return None
			return real_enqueue(method, *args, **kwargs)

		with (
			patch.object(outbound, "get_settings", return_value=PUSH_ON_WON),
			patch.object(frappe, "enqueue", enqueue),
		):
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

	def test_seeding_queues_no_erp_customer_push(self):
		"""The history inserts deals already Won. On a site with the customer push
		on, each one queued its fake organization for creation as a customer in
		the client's real ERP, which Clear Demo Data cannot take back."""
		won = frappe.db.count("CRM Deal", {"name": ["in", self.created["deals"]], "status": "Won"})
		self.assertGreater(won, 0)
		self.assertEqual(self.queued_pushes, [])

	def test_no_seeded_lead_is_lost_without_a_reason(self):
		lost_statuses = frappe.get_all("CRM Lead Status", {"type": "Lost"}, pluck="name")
		reasonless = frappe.get_all(
			"CRM Lead",
			filters={
				"name": ["in", self.created["leads"]],
				"status": ["in", lost_statuses],
				"lost_reason": ["is", "not set"],
			},
			pluck="name",
		)
		self.assertEqual(reasonless, [])

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

	def test_erp_customer_pushes_stand_down_while_demo_data_is_seeded(self):
		deal = frappe._dict(
			doctype="CRM Deal", name="DEMO-DEAL", status="Won", organization="Demo Org", erpnext_customer=None
		)
		real_get_single = frappe.get_single

		def get_single(doctype):
			return PUSH_ON_WON if doctype == "ERPNext CRM Settings" else real_get_single(doctype)

		with (
			patch.object(outbound, "get_settings", return_value=PUSH_ON_WON),
			patch.object(frappe, "get_single", get_single),
			patch.object(frappe, "enqueue", MagicMock()) as enqueue,
		):
			with patch.dict(frappe.flags, {"in_demo_seed": True}):
				outbound.queue_customer_push(deal, "on_update")
				erpnext_crm_settings.create_customer_in_erpnext(deal, "on_update")
			self.assertEqual(enqueue.call_count, 0)

			# and only while seeding: a real Won deal still pushes
			outbound.queue_customer_push(deal, "on_update")
			erpnext_crm_settings.create_customer_in_erpnext(deal, "on_update")
			self.assertEqual([c.args[0] for c in enqueue.call_args_list], list(ERP_PUSHES))

	def test_snapshots_leave_a_key_the_weekly_job_already_wrote(self):
		"""The demo's snapshot for a month is dated a week before it; when the month
		starts on a Sunday that is the weekly job's own day, and the blind insert
		died on the unique key after 25 months of history had been committed."""
		real = {"snapshot_date": "2026-01-25", "month": "2026-02", "scope": "Site", "user": ""}
		real_name = frappe.db.exists("CRM Forecast Snapshot", real) or (
			frappe.get_doc(
				{"doctype": "CRM Forecast Snapshot", **real, "forecasted": 1_250_000, "actual_at_snapshot": 0}
			)
			.insert(ignore_permissions=True)
			.name
		)
		forecasted = frappe.db.get_value("CRM Forecast Snapshot", real_name, "forecasted")
		created = {"snapshots": []}

		_create_snapshots(random.Random(SEED), ["Administrator"], date(2026, 10, 30), {}, created)

		self.assertEqual(frappe.db.count("CRM Forecast Snapshot", real), 1)
		self.assertEqual(frappe.db.get_value("CRM Forecast Snapshot", real_name, "forecasted"), forecasted)
		self.assertNotIn(real_name, created["snapshots"])
		self.assertTrue(created["snapshots"])

	def test_a_lead_settled_on_a_lost_status_carries_a_reason_and_can_be_edited(self):
		"""The status was written with db.set_value, skipping the controller, so a
		Junk or Unqualified demo lead had no lost reason and every later edit to it
		was refused with "Please specify a reason for losing the lead"."""
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Settled", "last_name": "Probe", "status": "New"}
		).insert(ignore_permissions=True)

		# Random(0) draws Junk for a lead a year old
		_settle_lead(lead.name, "Administrator", date(2025, 1, 6), 12, random.Random(0), date(2026, 10, 30))

		status, lost_reason = frappe.db.get_value("CRM Lead", lead.name, ["status", "lost_reason"])
		self.assertEqual(frappe.db.get_value("CRM Lead Status", status, "type"), "Lost")
		self.assertTrue(lost_reason)
		doc = frappe.get_doc("CRM Lead", lead.name)
		doc.job_title = "Plant Engineer"
		doc.save(ignore_permissions=True)
