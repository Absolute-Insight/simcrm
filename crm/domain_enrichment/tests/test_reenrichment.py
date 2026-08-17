# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The scheduled sweep that keeps enriched records from going stale.

Nothing here crawls: `enqueue_enrichment` is patched, so what is asserted is
*which* records the sweep decides are due and in what order. The crawl itself is
covered by the pipeline tests.

The selection rules that matter, and that the tests below hold to:

* never-enriched records are **not** swept in -- ticking one checkbox must not
  crawl every website in the CRM that night;
* the newest run counts whatever its status, so a site that cannot be crawled is
  retried on the sweep's cadence rather than every night;
* oldest first, capped, so a backlog is worked through instead of the same
  records being re-picked;
* off by default.
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.domain_enrichment import tasks

SETTINGS = "CRM Enrichment Settings"
ORG_PREFIX = "Reenrich Test"


class ReenrichStaleRecordsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.saved = {
			field: frappe.db.get_single_value(SETTINGS, field)
			for field in (
				"enabled",
				"enable_organization",
				"enable_lead",
				"enable_deal",
				"scheduled_reenrichment",
				"reenrich_after_days",
				"reenrich_batch_size",
			)
		}
		self.configure(
			enabled=1,
			enable_organization=1,
			enable_lead=0,
			enable_deal=0,
			scheduled_reenrichment=1,
			reenrich_after_days=90,
			reenrich_batch_size=25,
		)
		self.orgs: list[str] = []

	def tearDown(self):
		for name in self.orgs:
			frappe.db.delete("CRM Enrichment Run", {"reference_name": name})
			frappe.delete_doc("CRM Organization", name, force=True, ignore_missing=True)
		self.configure(**self.saved)
		super().tearDown()

	def configure(self, **values):
		for field, value in values.items():
			frappe.db.set_single_value(SETTINGS, field, value)
		frappe.clear_cache()

	def make_org(self, label: str, website: str | None = "https://example.test") -> str:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"{ORG_PREFIX} {label}",
				"website": website,
			}
		).insert(ignore_permissions=True)
		self.orgs.append(doc.name)
		return doc.name

	def add_run(self, name: str, days_ago: int, status: str = "Completed"):
		started = frappe.utils.add_days(frappe.utils.now_datetime(), -days_ago)
		run = frappe.get_doc(
			{
				"doctype": "CRM Enrichment Run",
				"reference_doctype": "CRM Organization",
				"reference_name": name,
				"source_website": "https://example.test",
				"status": status,
				"started_on": started,
			}
		).insert(ignore_permissions=True)
		# insert() stamps started_on from the field we set, but a Datetime that the
		# controller may normalise is safer written straight through.
		frappe.db.set_value("CRM Enrichment Run", run.name, "started_on", started, update_modified=False)
		return run.name

	def sweep(self):
		"""Run the sweep with the enqueue stubbed; return the records it chose, in order."""
		with mock.patch.object(tasks, "enqueue_enrichment") as enqueue:
			queued = tasks.reenrich_stale_records()
		chosen = [call.args[1] for call in enqueue.call_args_list]
		self.assertEqual(queued, len(chosen))
		return chosen

	def mine(self, chosen):
		"""Only this suite's records — the site is shared and carries other runs."""
		return [name for name in chosen if name in self.orgs]

	def assertNotDue(self, name: str):
		"""``name`` is not swept, and the sweep was working when it declined it.

		A bare "the sweep returned nothing" would also pass if the sweep were
		broken outright, so a record that is unambiguously stale goes in beside it
		and has to come back.
		"""
		control = self.make_org("control")
		self.add_run(control, days_ago=365)

		chosen = self.mine(self.sweep())
		self.assertIn(control, chosen, "the sweep found nothing at all — this test proves nothing")
		self.assertNotIn(name, chosen)

	def test_a_record_enriched_long_ago_is_due(self):
		stale = self.make_org("stale")
		self.add_run(stale, days_ago=200)
		self.assertIn(stale, self.mine(self.sweep()))

	def test_a_recently_enriched_record_is_left_alone(self):
		fresh = self.make_org("fresh")
		self.add_run(fresh, days_ago=3)
		self.assertNotDue(fresh)

	def test_a_record_that_has_never_been_enriched_is_not_swept_in(self):
		"""The dangerous one. If untouched records counted as stale, turning this
		on would crawl every website in the CRM the same night."""
		self.assertNotDue(self.make_org("untouched"))

	def test_only_the_newest_run_decides(self):
		"""An old run plus a recent one is a fresh record, not a stale one."""
		name = self.make_org("re-run")
		self.add_run(name, days_ago=200)
		self.add_run(name, days_ago=2)
		self.assertNotDue(name)

	def test_a_failed_run_still_counts_as_having_been_tried(self):
		"""Otherwise a site that cannot be crawled is retried every single night."""
		name = self.make_org("failing")
		self.add_run(name, days_ago=1, status="Failed")
		self.assertNotDue(name)

	def test_the_oldest_are_taken_first(self):
		oldest = self.make_org("oldest")
		middle = self.make_org("middle")
		newest = self.make_org("newest")
		self.add_run(oldest, days_ago=300)
		self.add_run(middle, days_ago=200)
		self.add_run(newest, days_ago=100)

		chosen = self.mine(self.sweep())
		self.assertEqual(chosen, [oldest, middle, newest])

	def test_the_batch_size_caps_the_sweep(self):
		for index in range(4):
			name = self.make_org(f"batch-{index}")
			self.add_run(name, days_ago=300 - index)
		self.configure(reenrich_batch_size=2)

		self.assertLessEqual(len(self.sweep()), 2)

	def test_a_record_whose_website_has_been_cleared_is_skipped(self):
		name = self.make_org("no-website", website=None)
		self.add_run(name, days_ago=200)
		self.assertNotDue(name)

	def test_it_is_off_unless_switched_on(self):
		name = self.make_org("stale-but-disabled")
		self.add_run(name, days_ago=200)
		self.configure(scheduled_reenrichment=0)
		self.assertEqual(self.sweep(), [])

	def test_turning_enrichment_off_entirely_stops_the_sweep(self):
		name = self.make_org("stale-but-feature-off")
		self.add_run(name, days_ago=200)
		self.configure(enabled=0)
		self.assertEqual(self.sweep(), [])

	def test_a_doctype_that_is_switched_off_is_not_swept(self):
		name = self.make_org("org-disabled")
		self.add_run(name, days_ago=200)
		self.configure(enable_organization=0)
		self.assertEqual(self.mine(self.sweep()), [])

	def test_the_sweep_does_not_depend_on_auto_enrich(self):
		"""An admin can decline to crawl every new record and still keep the ones
		they have already enriched up to date."""
		name = self.make_org("no-auto-enrich")
		self.add_run(name, days_ago=200)
		self.configure(auto_enrich=0)
		self.assertIn(name, self.mine(self.sweep()))

	def test_it_queues_through_the_shared_path_so_a_manual_run_is_not_doubled(self):
		"""enqueue_enrichment carries the per-document job_id + deduplicate that
		stops a scheduled sweep racing a rep who just pressed Enrich."""
		name = self.make_org("dedupe")
		self.add_run(name, days_ago=200)

		with mock.patch.object(tasks, "enqueue_enrichment") as enqueue:
			tasks.reenrich_stale_records()

		call = next(c for c in enqueue.call_args_list if c.args[1] == name)
		self.assertEqual(call.args[0], "CRM Organization")
		self.assertEqual(call.kwargs.get("trigger"), "scheduled")

	def test_one_unqueueable_record_does_not_cost_the_rest_of_the_sweep(self):
		first = self.make_org("explodes")
		second = self.make_org("survives")
		self.add_run(first, days_ago=300)
		self.add_run(second, days_ago=200)

		def explode_once(doctype, name, *args, **kwargs):
			if name == first:
				raise ValueError("redis said no")
			return {"queued": True}

		with mock.patch.object(tasks, "enqueue_enrichment", side_effect=explode_once) as enqueue:
			queued = tasks.reenrich_stale_records()

		attempted = [c.args[1] for c in enqueue.call_args_list]
		self.assertIn(second, attempted)
		self.assertGreaterEqual(queued, 1)


class ScheduledRunIsSilentTest(IntegrationTestCase):
	"""A sweep has no audience, and must not invent one.

	`run_enrichment` streams progress to a user. On a scheduled run that user is
	whoever the job runs as, who never asked — and publishing to no user at all is
	a site-wide broadcast, which is the failure this codebase has been pulling out
	of other realtime calls all along.
	"""

	def run_and_capture(self, trigger):
		published = []
		with (
			mock.patch.object(tasks, "_publish", side_effect=lambda *a, **k: published.append(k)),
			mock.patch.object(tasks, "get_config", side_effect=RuntimeError("stop before crawling")),
			mock.patch.object(tasks, "write_run"),
		):
			tasks.run_enrichment(
				"CRM Organization",
				"does-not-matter",
				"https://example.test",
				user="Administrator",
				trigger=trigger,
			)
		return published

	def test_a_manual_run_still_reports_to_the_user_who_asked(self):
		published = self.run_and_capture("manual")
		self.assertTrue(published)
		self.assertTrue(all(event["user"] == "Administrator" for event in published))

	def test_a_scheduled_run_publishes_nothing(self):
		self.assertEqual(self.run_and_capture("scheduled"), [])
