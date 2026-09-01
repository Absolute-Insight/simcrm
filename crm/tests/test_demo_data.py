import json
import os
from typing import ClassVar

import frappe
from frappe.tests import IntegrationTestCase


class TestDemoData(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		from crm.demo.api import clear_demo_data

		clear_demo_data()

	def _check_demo_records_exist(self, doctype, record_names):
		"""Helper method to check if specific demo records exist"""
		if not record_names:
			return False
		for name in record_names:
			if frappe.db.exists(doctype, name):
				return True
		return False

	def test_demo_data_lifecycle(self):
		from crm.demo.api import clear_demo_data, create_demo_data
		from crm.demo.users import DEMO_USERS

		DEMO_STATE_KEY = "crm_demo_data_created"
		DEMO_LEADS_KEY = "crm_demo_leads"
		DEMO_NOTES_KEY = "crm_demo_notes"
		DEMO_TASKS_KEY = "crm_demo_tasks"
		DEMO_CALL_LOGS_KEY = "crm_demo_call_logs"
		DEMO_ACTIVITIES_KEY = "crm_demo_activities"
		DEMO_DEALS_KEY = "crm_demo_deals"

		# 1. Before creation: nothing should exist
		for user in DEMO_USERS:
			self.assertFalse(frappe.db.exists("User", user["email"]))

		# Check that demo data defaults are not set
		self.assertIsNone(frappe.db.get_default(DEMO_LEADS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_NOTES_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_TASKS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_CALL_LOGS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_DEALS_KEY))

		# 2. Create demo data
		create_demo_data()

		# Users
		for user in DEMO_USERS:
			doc = frappe.get_doc("User", user["email"])
			self.assertIsNotNone(doc)
			self.assertEqual(doc.user_image, user["avatar"])
			self.assertTrue(doc.enabled)
			self.assertEqual(doc.first_name, user["first_name"])
			self.assertEqual(doc.last_name, user["last_name"])

		# Leads - check that demo leads were created
		demo_lead_names = json.loads(frappe.db.get_default(DEMO_LEADS_KEY) or "[]")
		self.assertEqual(len(demo_lead_names), 12)
		for lead_name in demo_lead_names:
			lead = frappe.get_doc("CRM Lead", lead_name)
			self.assertTrue(lead.first_name)
			self.assertTrue(lead.organization)

		# Notes, Tasks, Call Logs, Activities, Deals - check that demo data was created
		demo_note_names = json.loads(frappe.db.get_default(DEMO_NOTES_KEY) or "[]")
		demo_task_names = json.loads(frappe.db.get_default(DEMO_TASKS_KEY) or "[]")
		demo_call_log_names = json.loads(frappe.db.get_default(DEMO_CALL_LOGS_KEY) or "[]")
		demo_deal_data = json.loads(frappe.db.get_default(DEMO_DEALS_KEY) or "{}")

		self.assertGreater(len(demo_note_names), 0)
		self.assertGreater(len(demo_task_names), 0)
		self.assertGreater(len(demo_call_log_names), 0)
		if isinstance(demo_deal_data, dict):
			self.assertGreater(len(demo_deal_data.get("deals", [])), 0)

		# Avatars exist
		avatar_dir = os.path.abspath(
			os.path.join(os.path.dirname(__file__), "..", "..", "crm", "public", "images", "demo")
		)
		for user in DEMO_USERS:
			filename = user["avatar"].split("/")[-1]
			path = os.path.join(avatar_dir, filename)
			self.assertTrue(os.path.exists(path), f"Missing avatar: {path}")

		# Site defaults set
		self.assertEqual(frappe.db.get_default(DEMO_STATE_KEY), "1")
		self.assertTrue(frappe.db.get_default(DEMO_LEADS_KEY))
		self.assertTrue(frappe.db.get_default(DEMO_NOTES_KEY))
		self.assertTrue(frappe.db.get_default(DEMO_TASKS_KEY))
		self.assertTrue(frappe.db.get_default(DEMO_CALL_LOGS_KEY))
		self.assertTrue(frappe.db.get_default(DEMO_ACTIVITIES_KEY))
		self.assertTrue(frappe.db.get_default(DEMO_DEALS_KEY))

		# 3. Capture demo record names before clearing
		lead_names = json.loads(frappe.db.get_default(DEMO_LEADS_KEY) or "[]")
		note_names = json.loads(frappe.db.get_default(DEMO_NOTES_KEY) or "[]")
		task_names = json.loads(frappe.db.get_default(DEMO_TASKS_KEY) or "[]")
		call_log_names = json.loads(frappe.db.get_default(DEMO_CALL_LOGS_KEY) or "[]")
		deal_data = json.loads(frappe.db.get_default(DEMO_DEALS_KEY) or "{}")

		# Clear demo data
		clear_demo_data()

		# All demo data should be gone - check using the tracked record names

		# Users should be deleted
		for user in DEMO_USERS:
			self.assertFalse(frappe.db.exists("User", user["email"]))

		# Demo records should not exist
		self.assertFalse(self._check_demo_records_exist("CRM Lead", lead_names))
		self.assertFalse(self._check_demo_records_exist("FCRM Note", note_names))
		self.assertFalse(self._check_demo_records_exist("CRM Task", task_names))
		self.assertFalse(self._check_demo_records_exist("CRM Call Log", call_log_names))
		if isinstance(deal_data, dict) and deal_data.get("deals"):
			self.assertFalse(self._check_demo_records_exist("CRM Deal", deal_data.get("deals", [])))

		# Site defaults cleared
		self.assertIsNone(frappe.db.get_default(DEMO_STATE_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_LEADS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_NOTES_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_TASKS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_CALL_LOGS_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_ACTIVITIES_KEY))
		self.assertIsNone(frappe.db.get_default(DEMO_DEALS_KEY))


class TestDemoSeedGate(IntegrationTestCase):
	"""The setup wizard fires on production sites too, and `deploy/README.md`
	sends operators to it."""

	def test_the_wizard_hook_seeds_nothing_by_default(self):
		from unittest.mock import patch

		from crm.demo import api

		with patch.object(api, "create_demo_data") as create:
			api.seed_demo_data_if_enabled()
		create.assert_not_called()

	def test_the_wizard_hook_seeds_when_the_site_asks_for_it(self):
		from unittest.mock import patch

		from crm.demo import api

		with (
			patch.dict(frappe.conf, {api.DEMO_SEED_CONFIG_KEY: 1}),
			patch.object(api, "create_demo_data") as create,
		):
			api.seed_demo_data_if_enabled()
		create.assert_called_once()

	def test_an_explicit_call_still_seeds_regardless_of_the_flag(self):
		"""The gate belongs to the hook, not the function -- `bench execute
		crm.demo.api.create_demo_data` has to do what it says."""
		import inspect

		from crm.demo import api

		self.assertNotIn(api.DEMO_SEED_CONFIG_KEY, inspect.getsource(api.create_demo_data))


class TestDerivedDemoCleanup(IntegrationTestCase):
	"""Clearing demo data used to remove only what `crm/demo/` created. The
	proactive tier reads those records and writes its own, so the conclusions
	outlived the evidence."""

	DEMO_USERS: ClassVar[list[str]] = ["derived.demo1@crmtest.test", "derived.demo2@crmtest.test"]
	REAL_USER = "derived.real@crmtest.test"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email in (*self.DEMO_USERS, self.REAL_USER):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{
						"doctype": "User",
						"email": email,
						"first_name": email.split("@")[0],
						"send_welcome_email": 0,
					}
				).insert(ignore_permissions=True)

		# CRM Suggestion validates its dynamic link, so the deals it points at
		# have to be real ones.
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Derived Cleanup Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		status = frappe.get_all("CRM Deal Status", filters={"type": "Open"}, pluck="name")
		if not status:
			self.skipTest("site has no Open deal status")
		self.demo_deal = self.make_deal(org, status[0], self.DEMO_USERS[0])
		self.real_deal = self.make_deal(org, status[0], self.REAL_USER)

	def make_deal(self, org: str, status: str, owner: str) -> str:
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org,
				"deal_owner": owner,
				"status": status,
				"expected_deal_value": 1000,
				"probability": 50,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=deal.name: (
				frappe.db.exists("CRM Deal", n) and frappe.delete_doc("CRM Deal", n, force=True)
			)
		)
		return deal.name

	def make_snapshot(self, scope: str, user: str, date: str, month: str = "2026-08"):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Forecast Snapshot",
				"snapshot_date": date,
				"month": month,
				"scope": scope,
				"user": user,
				"forecasted": 1000,
				"actual_at_snapshot": 0,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Forecast Snapshot", doc.name, force=True)
		return doc.name

	def make_suggestion(self, user: str, reference: str):
		# reference_doctype is mandatory: a suggestion always points at something.
		doc = frappe.get_doc(
			{
				"doctype": "CRM Suggestion",
				"signal": "idle_deal",
				"title": "demo residue",
				"user": user,
				"reference_doctype": "CRM Deal",
				"reference_docname": reference,
				"status": "Open",
				"score": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: (
				frappe.db.exists("CRM Suggestion", n) and frappe.delete_doc("CRM Suggestion", n, force=True)
			)
		)
		return doc.name

	def clear(self, created_at: str | None = None):
		from crm.demo.api import DEMO_CREATED_AT_KEY, delete_derived_demo_records

		previous = frappe.db.get_default(DEMO_CREATED_AT_KEY)
		frappe.db.set_default(DEMO_CREATED_AT_KEY, created_at)
		self.addCleanup(frappe.db.set_default, DEMO_CREATED_AT_KEY, previous)
		return delete_derived_demo_records([], {"deals": [self.demo_deal]}, self.DEMO_USERS)

	def test_a_suggestion_about_a_demo_deal_is_removed(self):
		name = self.make_suggestion(self.REAL_USER, reference=self.demo_deal)
		self.clear()
		self.assertFalse(frappe.db.exists("CRM Suggestion", name))

	def test_a_suggestion_for_a_demo_rep_is_removed(self):
		"""Matching only on the reference leaves these behind: a demo user also
		collects suggestions about records that outlive them."""
		# Deliberately about a record that is *not* demo, so only the user matches.
		name = self.make_suggestion(self.DEMO_USERS[0], reference=self.real_deal)
		self.clear()
		self.assertFalse(frappe.db.exists("CRM Suggestion", name))

	def test_a_real_suggestion_survives(self):
		name = self.make_suggestion(self.REAL_USER, reference=self.real_deal)
		self.clear()
		self.assertTrue(frappe.db.exists("CRM Suggestion", name))

	def test_a_demo_rep_plan_and_its_items_are_removed(self):
		plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": self.DEMO_USERS[0],
				"week_start": "2026-08-17",
				"items": [{"activity_type": "Call", "planned_date": "2026-08-18"}],
			}
		).insert(ignore_permissions=True)
		item = plan.items[0].name

		self.clear()
		self.assertFalse(frappe.db.exists("CRM Rep Plan", plan.name))
		# delete_doc, not db.delete -- a bare row delete orphans the child table.
		self.assertFalse(frappe.db.exists("CRM Rep Plan Item", item))

	def test_demo_rep_snapshots_are_removed(self):
		name = self.make_snapshot("Rep", self.DEMO_USERS[0], "2026-08-10")
		self.clear()
		self.assertFalse(frappe.db.exists("CRM Forecast Snapshot", name))

	def test_a_real_reps_snapshot_survives(self):
		"""A demo deal belongs to a demo user, so it never entered a real rep's
		row -- their accuracy history is not collateral."""
		name = self.make_snapshot("Rep", self.REAL_USER, "2026-08-10")
		self.clear()
		self.assertTrue(frappe.db.exists("CRM Forecast Snapshot", name))

	def test_aggregates_taken_while_demo_data_existed_are_removed(self):
		"""These counted demo deals into a site or team total and cannot be
		recomputed -- the forecast is what was believed on that date."""
		site = self.make_snapshot("Site", "", "2026-08-12")
		team = self.make_snapshot("Team", self.REAL_USER, "2026-08-12")
		self.clear(created_at="2026-08-11 09:00:00")
		self.assertFalse(frappe.db.exists("CRM Forecast Snapshot", site))
		self.assertFalse(frappe.db.exists("CRM Forecast Snapshot", team))

	def test_aggregates_from_before_the_demo_data_survive(self):
		name = self.make_snapshot("Site", "", "2026-08-01")
		self.clear(created_at="2026-08-11 09:00:00")
		self.assertTrue(frappe.db.exists("CRM Forecast Snapshot", name))

	def test_without_a_recorded_date_every_aggregate_goes(self):
		"""A site seeded before the timestamp was tracked cannot distinguish a
		clean aggregate from a contaminated one, and a wrong stored total is
		worse than a missing one."""
		site = self.make_snapshot("Site", "", "2026-08-01")
		rep = self.make_snapshot("Rep", self.REAL_USER, "2026-08-01")
		self.clear(created_at=None)
		self.assertFalse(frappe.db.exists("CRM Forecast Snapshot", site))
		self.assertTrue(frappe.db.exists("CRM Forecast Snapshot", rep))
