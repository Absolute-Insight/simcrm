# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The dashboard's territory filter, and the three charts that cannot honour it.

The obvious way to build this was to hang the filter off ``scope_deals``, which
almost every chart calls. Almost: ``plan_adherence``, ``quota_attainment``,
``forecasted_revenue``, ``forecast_accuracy`` and ``deals_by_stage_axis`` do not.
A filter hung there would have applied to seventeen charts of twenty-four and
silently skipped the rest, putting one region's pipeline beside the whole
company's quota attainment with both looking equally authoritative.

So ``territory`` is an explicit parameter on every chart, and the three that
genuinely cannot slice by it are named in ``TERRITORY_BLIND`` and reported as
``territory_filtered: false`` rather than quietly returning global numbers.

The test that matters is :meth:`TerritoryFilterTest.test_every_chart_that_claims_to_filter_actually_filters`.
A list of exceptions is worth nothing if nobody checks it is accurate, and the
failure it guards against — a chart that accepts the parameter and ignores it —
is invisible from the outside.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.dashboard import CHARTS, TERRITORY_BLIND, get_chart
from crm.api.reports import REPORTS, get_report
from crm.api.reports import TERRITORY_BLIND as REPORT_TERRITORY_BLIND

NORTH = "Territory Filter North"
SOUTH = "Territory Filter South"

# Charts whose value is a rate, a count of something structural, or otherwise
# legitimately unchanged by narrowing to one of two territories that both hold
# deals. They still have to *accept* and *apply* the filter, which the row-level
# assertions below check; they just cannot be detected by "the number moved".
NOT_DETECTABLE_BY_VALUE = frozenset(
	{
		"deals_by_territory",  # already grouped by territory; a filter drops rows, not totals
	}
)


class TerritoryFixture:
	"""North and South, populated so every chart can tell them apart."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.from_date = str(frappe.utils.add_days(frappe.utils.nowdate(), -30))
		cls.to_date = str(frappe.utils.add_days(frappe.utils.nowdate(), 30))
		cls.created: list[tuple[str, str]] = []

		for territory in (NORTH, SOUTH):
			if not frappe.db.exists("CRM Territory", territory):
				frappe.get_doc({"doctype": "CRM Territory", "territory_name": territory}).insert(
					ignore_permissions=True
				)

		cls.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Territory Filter Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)

		# The fixture has to be able to *tell the two apart* for every chart, or
		# the honesty test below passes on charts that ignore the parameter. So
		# each territory gets a different number of leads and of deals, in every
		# status a chart reads, with the dates the date-based aggregates group on.
		cls.won_status = frappe.db.get_value("CRM Deal Status", {"type": "Won"}, "name")
		cls.lost_status = frappe.db.get_value("CRM Deal Status", {"type": "Lost"}, "name")
		# A Lost deal needs a reason, and the reason cannot be borrowed from the
		# site: sampling the first CRM Lost Reason row picked "Not interested"
		# locally and "Other" in CI, and "Other" additionally demands lost_notes.
		# So the fixture owns its reason and depends on no site data.
		cls.lost_reason = (
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Territory Filter Reason"})
			.insert(ignore_permissions=True, ignore_if_duplicate=True)
			.name
		)
		cls.created.append(("CRM Lost Reason", cls.lost_reason))
		closing = frappe.utils.add_days(frappe.utils.nowdate(), 10)

		# Counts *and* dates differ, because several charts answer with an average
		# rather than a total and two equal-sized samples would agree by accident.
		plan = (
			# territory, value, open, won, lost, leads, days since the wins closed
			(NORTH, 90000, 3, 2, 2, 2, 3),
			(SOUTH, 1000, 1, 1, 1, 1, 12),
		)
		for territory, value, open_deals, won, lost, leads, closed_days in plan:
			closed = frappe.utils.add_days(frappe.utils.nowdate(), -closed_days)
			for _ in range(open_deals):
				name = cls.make_deal(territory, value, expected_closure_date=closing)
				if territory == NORTH:
					# deals_at_risk gates on the timestamp, not the score
					frappe.db.set_value(
						"CRM Deal",
						name,
						{"health_score": 10, "health_scored_on": frappe.utils.now_datetime()},
						update_modified=False,
					)
			for _ in range(won):
				cls.make_deal(territory, value * 2, status=cls.won_status, closed_date=closed)
			for _ in range(lost):
				cls.make_deal(territory, value * 3, status=cls.lost_status, lost_reason=cls.lost_reason)
			for index in range(leads):
				lead = frappe.get_doc(
					{
						"doctype": "CRM Lead",
						"first_name": f"Territory {territory} {index}",
						"territory": territory,
					}
				).insert(ignore_permissions=True)
				cls.created.append(("CRM Lead", lead.name))

	@classmethod
	def make_deal(cls, territory, value, **extra):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": cls.org,
				"territory": territory,
				"deal_value": value,
				"exchange_rate": 1,
				**{k: v for k, v in extra.items() if v},
			}
		).insert(ignore_permissions=True)
		# validate() stamps closed_date to today whenever the status becomes Won
		if extra.get("closed_date"):
			frappe.db.set_value(
				"CRM Deal", doc.name, "closed_date", extra["closed_date"], update_modified=False
			)
		cls.created.append(("CRM Deal", doc.name))
		return doc.name

	@classmethod
	def tearDownClass(cls):
		# Reversed, so a row is gone before whatever it depends on: the lost
		# reason is registered before the deals that link to it.
		for doctype, name in reversed(cls.created):
			frappe.delete_doc(doctype, name, force=True, ignore_missing=True)
		super().tearDownClass()


class TerritoryFilterTest(TerritoryFixture, IntegrationTestCase):
	# Titles, axes and the territory echo are the same whatever the filter; only
	# these keys carry an answer, and a number tile answers in "value" rather
	# than "data" — comparing "data" alone silently passed every tile.
	PAYLOAD_KEYS = ("data", "value", "rows", "series")

	def payload(self, name, territory):
		result = self.chart(name, territory)
		return {key: result[key] for key in self.PAYLOAD_KEYS if key in result}

	def chart(self, name, territory=None):
		return get_chart(
			name=name,
			type="axis_chart",
			from_date=self.from_date,
			to_date=self.to_date,
			territory=territory,
		)

	# --- the contract -----------------------------------------------------

	def test_every_registered_chart_accepts_a_territory(self):
		"""A chart that does not take the parameter would raise the moment an
		admin picked a territory, and only for that one chart."""
		for name in CHARTS:
			with self.subTest(chart=name):
				result = self.chart(name, NORTH)
				self.assertIsInstance(result, dict)
				self.assertNotIn("error", result)

	def test_a_chart_says_whether_the_filter_reached_it(self):
		for name in CHARTS:
			with self.subTest(chart=name):
				self.assertIs(self.chart(name, NORTH)["territory_filtered"], name not in TERRITORY_BLIND)

	def test_no_chart_claims_to_be_filtered_when_no_territory_is_set(self):
		for name in CHARTS:
			with self.subTest(chart=name):
				self.assertFalse(self.chart(name)["territory_filtered"])

	def test_the_blind_list_only_names_charts_that_exist(self):
		self.assertEqual(TERRITORY_BLIND - set(CHARTS), set())

	# --- the one that keeps the list honest -------------------------------

	def test_every_chart_that_claims_to_filter_actually_filters(self):
		"""The assertion the whole design rests on.

		A chart can accept ``territory``, advertise ``territory_filtered: true``
		and drop it on the floor, and nothing outside would show it. North holds
		three deals at 90,000 and South one at 1,000, so a chart reading deals
		must answer differently for the two.
		"""
		ignored = []
		for name in CHARTS:
			if name in TERRITORY_BLIND or name in NOT_DETECTABLE_BY_VALUE:
				continue
			if self.payload(name, NORTH) == self.payload(name, SOUTH):
				ignored.append(name)

		self.assertEqual(
			ignored,
			[],
			"these charts claim territory_filtered but return the same data for two "
			"different territories — either they ignore the parameter, or they belong "
			"in TERRITORY_BLIND",
		)

	def test_a_blind_chart_really_is_unchanged_by_the_filter(self):
		"""The other direction: if one of these started honouring a territory,
		TERRITORY_BLIND would be lying in the opposite direction and the client
		would be told to distrust a number that is in fact filtered."""
		for name in TERRITORY_BLIND:
			with self.subTest(chart=name):
				self.assertEqual(self.payload(name, NORTH), self.payload(name, SOUTH))

	# --- the numbers ------------------------------------------------------

	def test_a_deal_aggregate_narrows_to_the_territory(self):
		north = self.chart("deals_by_source", NORTH)["data"]
		south = self.chart("deals_by_source", SOUTH)["data"]
		self.assertEqual(sum(row["count"] for row in north) - sum(row["count"] for row in south), 4)

	def test_a_lead_aggregate_narrows_to_the_territory(self):
		"""Leads carry their own territory; a filter that only reached deals would
		leave the lead tiles global and nothing would say so."""
		self.assertEqual(self.chart("total_leads", NORTH)["value"], 2)
		self.assertEqual(self.chart("total_leads", SOUTH)["value"], 1)
		self.assertGreaterEqual(self.chart("total_leads")["value"], 3)

	def test_the_territory_is_echoed_back_so_the_client_can_label_the_view(self):
		self.assertEqual(self.chart("deals_by_source", NORTH)["territory"], NORTH)
		self.assertIsNone(self.chart("deals_by_source")["territory"])

	def test_an_unknown_territory_returns_nothing_rather_than_everything(self):
		"""Failing open here would show a manager the whole company's pipeline
		under a heading naming a territory they cannot see."""
		rows = self.chart("deals_by_source", "Territory That Does Not Exist")["data"]
		self.assertEqual(sum(row["count"] for row in rows), 0)


class ReportTerritoryFilterTest(TerritoryFixture, IntegrationTestCase):
	"""The same contract on the Reports page, with its own blind list.

	Reports were the other half of the gap: a manager could scope the dashboard
	to a region and then export a CSV covering the whole company from the page
	next door.
	"""

	def report(self, name, territory=None):
		return get_report(name, self.from_date, self.to_date, territory=territory)

	def test_every_report_accepts_a_territory(self):
		for name in REPORTS:
			with self.subTest(report=name):
				self.assertIn("rows", self.report(name, NORTH))

	def test_a_report_says_whether_the_filter_reached_it(self):
		for name in REPORTS:
			with self.subTest(report=name):
				self.assertIs(
					self.report(name, NORTH)["territory_filtered"],
					name not in REPORT_TERRITORY_BLIND,
				)

	def test_every_report_that_claims_to_filter_actually_filters(self):
		"""The report-side twin of the chart honesty test, and for the same
		reason: a list of exceptions nobody checks is worth nothing."""
		ignored = [
			name
			for name in REPORTS
			if name not in REPORT_TERRITORY_BLIND
			and self.report(name, NORTH)["rows"] == self.report(name, SOUTH)["rows"]
		]
		self.assertEqual(
			ignored,
			[],
			"these reports claim territory_filtered but return identical rows for two different territories",
		)

	def test_a_blind_report_really_is_unchanged(self):
		for name in REPORT_TERRITORY_BLIND:
			with self.subTest(report=name):
				self.assertEqual(self.report(name, NORTH)["rows"], self.report(name, SOUTH)["rows"])

	def test_the_blind_list_only_names_reports_that_exist(self):
		self.assertEqual(REPORT_TERRITORY_BLIND - set(REPORTS), set())


class FunnelTerritoryTest(TerritoryFixture, IntegrationTestCase):
	"""Every funnel row must narrow, not just the lead row.

	Only the Leads count used to be territory-scoped: the stage rows and the
	Lost row were company-wide, while territory_filtered still read true — so
	one region's leads appeared to convert into the whole company's deals, with
	the response vouching for the lie.
	"""

	def rows(self, territory):
		result = get_chart(
			name="funnel_conversion",
			type="axis_chart",
			from_date=self.from_date,
			to_date=self.to_date,
			territory=territory,
		)
		return {row["stage"]: row["count"] for row in result["data"]}

	def test_the_lost_row_narrows_to_the_territory(self):
		self.assertEqual(self.rows(NORTH)["Lost"], 2)
		self.assertEqual(self.rows(SOUTH)["Lost"], 1)

	def test_the_stage_rows_narrow_to_the_territory(self):
		"""A deal logs a ``to`` row only on a real transition (insert writes the
		initial status into ``from``), so make one transition in North: its stage
		row must count there and not in South's funnel."""
		deal_name = next(name for doctype, name in self.created if doctype == "CRM Deal")
		deal = frappe.get_doc("CRM Deal", deal_name)
		deal.status = frappe.db.get_value(
			"CRM Deal Status", {"name": ("!=", deal.status), "type": ("in", ("Open", "Ongoing"))}
		)
		deal.save(ignore_permissions=True)

		def stage_total(rows):
			return sum(count for stage, count in rows.items() if stage not in ("Leads", "Lost"))

		self.assertGreater(stage_total(self.rows(NORTH)), stage_total(self.rows(SOUTH)))
