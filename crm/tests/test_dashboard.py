# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt


import frappe
from frappe.tests import IntegrationTestCase
from frappe.tests.utils import make_test_records
from frappe.utils import add_days, get_first_day, get_last_day, nowdate

from crm.api.dashboard import (
	blank_label,
	get_average_deal_value,
	get_average_ongoing_deal_value,
	get_average_time_to_close_a_deal,
	get_average_time_to_close_a_lead,
	get_average_won_deal_value,
	get_base_currency_symbol,
	get_chart,
	get_dashboard,
	get_deal_status_change_counts,
	get_deals_by_industry,
	get_deals_by_salesperson,
	get_deals_by_source,
	get_deals_by_stage_axis,
	get_deals_by_stage_donut,
	get_deals_by_territory,
	get_forecasted_revenue,
	get_funnel_conversion,
	get_leads_by_source,
	get_lost_deal_reasons,
	get_ongoing_deals,
	get_sales_trend,
	get_total_leads,
	get_won_deals,
)


class TestDashboard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		"""Set up test records once for all tests"""
		super().setUpClass()

		# Mark timestamp before creating test data
		cls.test_start_time = frappe.utils.now()

		cls.from_date = get_first_day(nowdate())
		cls.to_date = get_last_day(nowdate())
		cls.user = "crm.manager@example.com"  # CRM manager from test_records.json
		cls.user2_email = "crm.user1@example.com"  # Test user from test_records.json

		# Load test records from test_records.json files in dependency order
		make_test_records("CRM Lead Status")
		make_test_records("CRM Deal Status")
		make_test_records("CRM Lead Source")
		make_test_records("CRM Lost Reason")
		make_test_records("CRM Organization")  # Load organizations before deals
		make_test_records("CRM Lead")
		make_test_records("CRM Deal")

	# `make_test_records` commits its fixtures rather than rolling them back, and
	# frappe caches them for the whole run — so on a shared site the row count
	# drifts by another 35 leads each time, and in a whole-app run the fixtures
	# may already exist before this class even starts. Absolute counts cannot
	# hold under either condition.
	#
	# What these tests are actually for is the aggregate layer, so they assert
	# that: each metric must equal an independently computed count over the same
	# predicate. The fixture facts (35 leads, 3 of them crm.user1's) are asserted
	# separately against the fixture *definition*, which is a file and does not
	# drift. A number that disagrees with the database still fails; a database
	# that happens to hold other people's rows no longer does.

	@classmethod
	def defined_records(cls, doctype: str) -> list[dict]:
		"""The fixture definition for ``doctype`` — the file, not the rows."""
		import json
		from pathlib import Path

		slug = doctype.lower().replace(" ", "_")
		path = Path(frappe.get_app_path("crm", "fcrm", "doctype", slug, "test_records.json"))
		return json.loads(path.read_text())

	def leads_in_period(self, user: str | None = None) -> int:
		filters = {"creation": ("between", [self.from_date, self.to_date])}
		if user:
			filters["lead_owner"] = user
		return frappe.db.count("CRM Lead", filters)

	def deals_in_period(self, status_type: str, user: str | None = None) -> int:
		statuses = frappe.db.get_list("CRM Deal Status", {"type": status_type}, pluck="name")
		filters = {"status": ("in", statuses)}
		if status_type == "Won":
			filters["closed_date"] = ("between", [self.from_date, self.to_date])
		else:
			filters["creation"] = ("between", [self.from_date, self.to_date])
		if user:
			filters["deal_owner"] = user
		return frappe.db.count("CRM Deal", filters)

	def deal_values_in_period(self, scope: str, user: str | None = None) -> list[float]:
		"""The values a deal-value average should be averaging, re-derived through
		frappe.db instead of the dashboard's own query builder.

		Mirrors the dashboard's predicates exactly, which are not as symmetric as
		the names suggest: ``won`` is the Won status type dated by ``closed_date``;
		``ongoing`` is anything that is neither Won nor Lost; ``non_lost`` is
		everything except Lost. The last two are dated by ``creation``, so
		``non_lost`` is not ``ongoing`` plus ``won``.
		"""
		if scope == "won":
			status_filter = {"type": "Won"}
			date_field = "closed_date"
		elif scope == "ongoing":
			status_filter = {"type": ("not in", ["Won", "Lost"])}
			date_field = "creation"
		elif scope == "non_lost":
			status_filter = {"type": ("!=", "Lost")}
			date_field = "creation"
		else:
			raise ValueError(f"unknown scope {scope!r}")

		statuses = frappe.db.get_list("CRM Deal Status", status_filter, pluck="name")
		filters = {
			"status": ("in", statuses),
			date_field: ("between", [self.from_date, self.to_date]),
		}
		if user:
			filters["deal_owner"] = user

		rows = frappe.db.get_all("CRM Deal", filters=filters, fields=["deal_value", "exchange_rate"])
		return [(r.deal_value or 0) * (r.exchange_rate or 1) for r in rows]

	def expected_mean(self, scope: str, user: str | None = None) -> float:
		values = self.deal_values_in_period(scope, user)
		return sum(values) / len(values) if values else 0

	def assertAverages(self, result, scope: str, user: str | None = None):
		"""The metric must equal the mean of the rows matching the same predicate."""
		values = self.deal_values_in_period(scope, user)
		expected = sum(values) / len(values) if values else 0
		self.assertAlmostEqual(
			result["value"],
			expected,
			places=2,
			msg=f"{scope} average over {len(values)} deals" + (f" owned by {user}" if user else ""),
		)

	@classmethod
	def tearDownClass(cls):
		"""Clean up test records after all tests"""
		frappe.db.rollback()
		super().tearDownClass()

	def test_get_total_leads(self):
		"""Test get_total_leads returns correct lead count and delta calculation"""
		result = get_total_leads(self.from_date, self.to_date)

		# Verify actual count from test data
		self.assertEqual(result["title"], "Total leads")
		self.assertEqual(len(self.defined_records("CRM Lead")), 35)  # the fixture defines 35
		self.assertEqual(result["value"], self.leads_in_period())
		self.assertIsInstance(result["delta"], (int, float))
		self.assertEqual(result["deltaSuffix"], "%")

		# Test with user filter - crm.user1@example.com owns 3 leads
		result_user = get_total_leads(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(result_user["value"], self.leads_in_period(self.user2_email))
		self.assertLessEqual(result_user["value"], result["value"])

		# Verify user's leads are subset of total
		self.assertGreater(result["value"], result_user["value"])

	def test_get_ongoing_deals(self):
		"""Test get_ongoing_deals returns correct non-won/lost deal count"""
		result = get_ongoing_deals(self.from_date, self.to_date)

		# Verify actual count: 13 Qualification + 8 Negotiation = 21
		self.assertEqual(result["title"], "Ongoing deals")
		self.assertEqual(result["value"], self.deals_in_period("Open") + self.deals_in_period("Ongoing"))

		# Verify it's not counting won/lost deals
		all_deals = frappe.db.count("CRM Deal")
		self.assertLess(result["value"], all_deals)

		# Test with user filter - crm.user1@example.com owns 2 ongoing deals
		result_user = get_ongoing_deals(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(
			result_user["value"],
			self.deals_in_period("Open", self.user2_email)
			+ self.deals_in_period("Ongoing", self.user2_email),
		)

		# Verify user owns subset of ongoing deals
		self.assertLess(result_user["value"], result["value"])

	def test_get_average_ongoing_deal_value(self):
		"""Test get_average_ongoing_deal_value calculates correct average"""
		result = get_average_ongoing_deal_value(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Avg. ongoing deal value")
		self.assertAverages(result, "ongoing")
		self.assertIsNotNone(result["prefix"])  # Should have currency symbol
		self.assertIsInstance(result["delta"], (int, float))

		# Test with user filter - crm.user1@example.com owns 2 ongoing deals
		result_user = get_average_ongoing_deal_value(self.from_date, self.to_date, self.user2_email)
		self.assertAverages(result_user, "ongoing", self.user2_email)

		# Both should have same currency symbol
		self.assertEqual(result["prefix"], result_user["prefix"])

	def test_get_won_deals(self):
		"""Test get_won_deals returns correct won deal count"""
		result = get_won_deals(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Won deals")
		self.assertEqual(result["value"], self.deals_in_period("Won"))
		self.assertIsNotNone(result.get("tooltip"))

		# Verify won deals is less than total deals
		ongoing_result = get_ongoing_deals(self.from_date, self.to_date)
		total_won_and_ongoing = result["value"] + ongoing_result["value"]
		all_deals = frappe.db.count("CRM Deal")
		self.assertLessEqual(total_won_and_ongoing, all_deals)

		# Test with user filter - crm.user1@example.com owns 0 won deals
		result_user = get_won_deals(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(result_user["value"], self.deals_in_period("Won", self.user2_email))

		# User owns no won deals but has ongoing deals
		ongoing_user = get_ongoing_deals(self.from_date, self.to_date, self.user2_email)
		self.assertGreater(ongoing_user["value"], result_user["value"])

	def test_get_average_won_deal_value(self):
		"""Test get_average_won_deal_value calculates correct average for won deals"""
		result = get_average_won_deal_value(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Avg. won deal value")
		self.assertAverages(result, "won")

		# Test with user filter - user2 has no won deals
		result_user = get_average_won_deal_value(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(result_user["value"], 0)  # No won deals = 0 average
		self.assertAverages(result_user, "won", self.user2_email)

		# Verify currency consistency
		self.assertEqual(result["prefix"], result_user["prefix"])

	def test_get_average_deal_value(self):
		"""Test get_average_deal_value for all non-lost deals includes won + ongoing"""
		result = get_average_deal_value(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Avg. deal value")
		self.assertAverages(result, "non_lost")

		self.assertIn(
			"ongoing & won", result["tooltip"].lower()
		)  # Verify tooltip describes ongoing & won deals

		# Test with user filter - crm.user1@example.com owns 2 ongoing deals (no won)
		result_user = get_average_deal_value(self.from_date, self.to_date, self.user2_email)
		self.assertAverages(result_user, "non_lost", self.user2_email)

	def test_get_average_time_to_close_a_lead(self):
		"""Test get_average_time_to_close_a_lead calculates time from lead creation"""
		result = get_average_time_to_close_a_lead(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Avg. time to close a lead")
		self.assertEqual(result["value"], 0)  # Test records created on same day
		self.assertEqual(result["suffix"], " days")

		# Test with user filter
		result_user = get_average_time_to_close_a_lead(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(result_user["value"], 0)  # Test records created on same day

	def test_get_average_time_to_close_a_deal(self):
		"""Test get_average_time_to_close_a_deal calculates time from deal creation"""
		result = get_average_time_to_close_a_deal(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Avg. time to close a deal")
		self.assertEqual(result["value"], 0)  # Test records created on same day
		self.assertEqual(result.get("suffix", ""), " days")

		# Test with user filter
		result_user = get_average_time_to_close_a_deal(self.from_date, self.to_date, self.user2_email)
		self.assertEqual(result_user["value"], 0)  # Test records created on same day

	def test_get_sales_trend(self):
		"""Test get_sales_trend returns correct time series data"""
		result = get_sales_trend(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Sales trend")
		self.assertEqual(len(result["series"]), 3)  # leads, deals, won_deals
		self.assertEqual(result["series"][0]["name"], "leads")
		self.assertEqual(result["series"][1]["name"], "deals")
		self.assertEqual(result["series"][2]["name"], "won_deals")

		# Verify data points exist
		self.assertIsInstance(result["data"], list)
		if len(result["data"]) > 0:
			# Each data point should have date and values
			first_point = result["data"][0]
			self.assertIsInstance(first_point, dict)

		# Test with user filter
		result_user = get_sales_trend(self.from_date, self.to_date, self.user2_email)
		self.assertIn("data", result_user)
		self.assertEqual(len(result_user["series"]), 3)

		# User data should be subset of total data
		self.assertLessEqual(len(result_user["data"]), len(result["data"]) if result["data"] else 0)

	def test_get_forecasted_revenue(self):
		"""Test get_forecasted_revenue returns forecasted vs actual revenue comparison"""
		result = get_forecasted_revenue(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Forecasted revenue")

		# Should have both forecasted and actual series
		if result["series"]:
			series_names = [s["name"] for s in result["series"]]
			self.assertIn("forecasted", series_names)
			self.assertIn("actual", series_names)

		result_user = get_forecasted_revenue(self.from_date, self.to_date, self.user2_email)
		self.assertIn("data", result_user)
		self.assertIn("series", result_user)

	def test_get_funnel_conversion(self):
		"""Test get_funnel_conversion returns correct pipeline funnel data"""
		result = get_funnel_conversion(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Funnel conversion")
		self.assertGreater(len(result["data"]), 0)

		# Verify funnel starts with Leads
		self.assertEqual(result["data"][0]["stage"], "Leads")
		self.assertEqual(result["data"][0]["count"], self.leads_in_period())

		# Verify funnel stages are in order and counts decrease or stay same (funnel effect)
		for i in range(len(result["data"]) - 1):
			current_count = result["data"][i]["count"]
			next_count = result["data"][i + 1]["count"]
			# Each stage should have equal or fewer than previous (funnel narrows)
			self.assertGreaterEqual(
				current_count,
				next_count,
				f"Funnel should narrow or stay same: {result['data'][i]['stage']} ({current_count}) should be >= {result['data'][i + 1]['stage']} ({next_count})",
			)

		# Test with user filter - crm.user1@example.com owns 3 leads
		result_user = get_funnel_conversion(self.from_date, self.to_date, self.user2_email)
		self.assertIn("data", result_user)
		self.assertGreater(len(result_user["data"]), 0)
		self.assertEqual(result_user["data"][0]["stage"], "Leads")
		self.assertEqual(result_user["data"][0]["count"], self.leads_in_period(self.user2_email))

		# User's funnel should be subset of total
		for i in range(min(len(result["data"]), len(result_user["data"]))):
			self.assertLessEqual(result_user["data"][i]["count"], result["data"][i]["count"])

	def test_get_deals_by_stage_axis(self):
		"""Test get_deals_by_stage_axis returns deal distribution by stage"""
		result = get_deals_by_stage_axis(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Deals by ongoing & won stage")

		# Should have data for stages
		if result["data"]:
			# Each entry should have stage name and count
			for entry in result["data"]:
				self.assertIn("stage", entry)
				self.assertIn("count", entry)  # API uses 'count' not 'deals'
				self.assertGreater(entry["count"], 0)

		result_user = get_deals_by_stage_axis(self.from_date, self.to_date, self.user2_email)
		self.assertIsInstance(result_user["data"], list)

	def test_get_deals_by_stage_donut(self):
		"""Test get_deals_by_stage_donut returns proper donut chart data"""
		result = get_deals_by_stage_donut(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Deals by stage")

		# Donut chart should have proper structure
		if result["data"]:
			total_count = sum(
				entry.get("count", 0) for entry in result["data"]
			)  # API uses 'count' not 'deals'
			self.assertGreater(total_count, 0)

		result_user = get_deals_by_stage_donut(self.from_date, self.to_date, self.user2_email)
		self.assertIsInstance(result_user["data"], list)

	def test_get_lost_deal_reasons(self):
		"""Test get_lost_deal_reasons returns distribution of loss reasons"""
		result = get_lost_deal_reasons(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Lost deal reasons")

		# Lost reasons only apply to lost deals
		if result["data"]:
			for entry in result["data"]:
				self.assertIn("reason", entry)
				self.assertIn("count", entry)

		result_user = get_lost_deal_reasons(self.from_date, self.to_date, self.user2_email)
		self.assertIsInstance(result_user["data"], list)

	def test_get_leads_by_source(self):
		"""Test get_leads_by_source returns source distribution"""
		result = get_leads_by_source(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Leads by source")

		# Should have source data
		if result["data"]:
			total_leads = sum(entry.get("count", 0) for entry in result["data"])  # API uses 'count'
			self.assertEqual(total_leads, self.leads_in_period())

		result_user = get_leads_by_source(self.from_date, self.to_date, self.user2_email)
		if result_user["data"]:
			user_total = sum(entry.get("count", 0) for entry in result_user["data"])  # API uses 'count'
			self.assertEqual(user_total, self.leads_in_period(self.user2_email))

	def test_get_deals_by_source(self):
		"""Test get_deals_by_source returns source distribution"""
		result = get_deals_by_source(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Deals by source")
		self.assertIsInstance(result["data"], list)

		result_user = get_deals_by_source(self.from_date, self.to_date, self.user2_email)
		self.assertIsInstance(result_user["data"], list)

	def test_get_deals_by_territory(self):
		"""Test get_deals_by_territory returns geographic distribution"""
		result = get_deals_by_territory(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Deals by territory")
		self.assertIsInstance(result["data"], list)

		result_user = get_deals_by_territory(self.from_date, self.to_date, self.user2_email)
		self.assertIsInstance(result_user["data"], list)

	def test_get_deals_by_salesperson(self):
		"""Test get_deals_by_salesperson returns per-user performance"""
		result = get_deals_by_salesperson(self.from_date, self.to_date)

		self.assertEqual(result["title"], "Deals by salesperson")

		# Should show different salespeople
		if result["data"]:
			for entry in result["data"]:
				self.assertIn("salesperson", entry)
				self.assertIn("deals", entry)

		result_user = get_deals_by_salesperson(self.from_date, self.to_date, self.user2_email)
		self.assertIn("data", result_user)

	def test_get_base_currency_symbol(self):
		"""Test get_base_currency_symbol returns correct currency symbol"""
		# Set USD as base currency
		if not frappe.db.exists("FCRM Settings"):
			frappe.get_doc(
				{
					"doctype": "FCRM Settings",
					"currency": "USD",
				}
			).insert()
		else:
			frappe.db.set_single_value("FCRM Settings", "currency", "USD")

		symbol = get_base_currency_symbol()

		self.assertIsNotNone(symbol)
		self.assertIsInstance(symbol, str)
		self.assertGreater(len(symbol), 0)  # Should not be empty
		# Common currency symbols
		self.assertIn(symbol, ["$", "€", "£", "¥", "₹", "USD"])

	def test_get_dashboard(self):
		"""Test get_dashboard returns complete layout with valid data"""
		result = get_dashboard(self.from_date, self.to_date)

		self.assertIsInstance(result, list)
		self.assertGreater(len(result), 0)  # Should have layout items

		# Each layout item should have required fields
		for item in result:
			self.assertIn("name", item)
			self.assertIsInstance(item["name"], str)
			self.assertTrue(item["name"])  # Name should not be empty

	def test_get_chart(self):
		"""Test get_chart returns correct chart data for valid chart names"""
		result = get_chart("total_leads", "number", self.from_date, self.to_date)

		self.assertEqual(result["value"], self.leads_in_period())  # must match get_total_leads
		self.assertIsInstance(result["value"], (int, float))
		self.assertIsNotNone(result.get("title"))

	def test_get_chart_invalid_name(self):
		"""Test get_chart returns proper error for invalid chart name"""
		result = get_chart("invalid_chart_name", "number", self.from_date, self.to_date)

		self.assertIsNotNone(result.get("error"))
		self.assertGreater(len(result["error"]), 0)

	def test_get_deal_status_change_counts(self):
		"""Test get_deal_status_change_counts returns status transition data"""
		result = get_deal_status_change_counts(self.from_date, self.to_date)

		self.assertIsInstance(result, list)
		# May be empty if no status changes recorded
		if result:
			for entry in result:
				self.assertIsInstance(entry, dict)

	def test_user_filtering_isolation(self):
		"""Test that user filtering correctly isolates data across metrics"""
		result_crm_user = get_total_leads(self.from_date, self.to_date, self.user2_email)
		result_all = get_total_leads(self.from_date, self.to_date, "")

		self.assertEqual(result_crm_user["value"], self.leads_in_period(self.user2_email))
		self.assertEqual(result_all["value"], self.leads_in_period())
		self.assertGreater(result_all["value"], result_crm_user["value"])

	def test_date_range_filtering(self):
		"""Test that date range filtering works correctly"""
		result_current = get_total_leads(self.from_date, self.to_date)

		self.assertIsNotNone(result_current["value"])
		self.assertGreater(result_current["value"], 0)  # Should have leads created

	# ============================================================
	# EDGE CASE TESTS - Testing boundary conditions and errors
	# ============================================================

	def test_empty_date_range(self):
		"""Test behavior with empty/future date range"""
		# Future date range with no data
		future_start = add_days(nowdate(), 365)
		future_end = add_days(nowdate(), 400)

		result = get_total_leads(future_start, future_end)
		self.assertEqual(result["value"], 0)

		# Should handle gracefully without errors
		result_deals = get_ongoing_deals(future_start, future_end)
		self.assertEqual(result_deals["value"], 0)

	def test_invalid_date_order(self):
		"""Test with end date before start date"""
		# Swap dates - end before start
		result = get_total_leads(self.to_date, self.from_date)

		# Should still work (function handles it)
		self.assertIsInstance(result["value"], (int, float))

	def test_nonexistent_user_filter(self):
		"""Test filtering by non-existent user"""
		result = get_total_leads(self.from_date, self.to_date, "nonexistent@example.com")

		# Should return 0 for non-existent user
		self.assertEqual(result["value"], 0)

	def test_chart_with_empty_name(self):
		"""Test get_chart with empty chart name"""
		result = get_chart("", "number", self.from_date, self.to_date)

		self.assertIsNotNone(result.get("error"))

	def test_chart_with_none_values(self):
		"""Test get_chart handles None parameters gracefully"""
		result = get_chart("total_leads", "number", None, None)

		# Should handle gracefully
		self.assertTrue("value" in result or "error" in result)

	# ============================================================
	# BUSINESS LOGIC VALIDATION TESTS
	# ============================================================

	def test_deal_counts_consistency(self):
		"""Test that ongoing + won + lost deals = total deals"""
		ongoing = get_ongoing_deals(self.from_date, self.to_date)["value"]
		won = get_won_deals(self.from_date, self.to_date)["value"]

		# Get lost deals count
		lost_deals = frappe.db.count(
			"CRM Deal",
			{
				"creation": ["between", [self.from_date, self.to_date]],
				"status": ["in", frappe.db.get_list("CRM Deal Status", {"type": "Lost"}, pluck="name")],
			},
		)

		total_deals_by_type = ongoing + won + lost_deals
		total_deals = frappe.db.count("CRM Deal", {"creation": ["between", [self.from_date, self.to_date]]})

		# Total should match sum of all deal types
		self.assertEqual(
			total_deals_by_type,
			total_deals,
			f"Deal count mismatch: ongoing({ongoing}) + won({won}) + lost({lost_deals}) = {total_deals_by_type}, but total is {total_deals}",
		)

	def test_the_three_averages_agree_with_each_other(self):
		"""All three metrics, and their ordering, against independently derived means.

		The ordering used to be asserted as fixed facts -- won above ongoing, all
		between the two. Those are properties of the fixture, not of the code, and
		they stop holding the moment the site has other deals on it. Asserted
		against the same rows the metrics claim to be summarising instead, so the
		test still fails if a metric picks the wrong status set or the wrong date
		column, and no longer fails just because someone else's deals are here.
		"""
		metrics = {
			"ongoing": get_average_ongoing_deal_value(self.from_date, self.to_date),
			"won": get_average_won_deal_value(self.from_date, self.to_date),
			"non_lost": get_average_deal_value(self.from_date, self.to_date),
		}
		for scope, result in metrics.items():
			with self.subTest(scope=scope):
				self.assertAverages(result, scope)

		expected_order = sorted(metrics, key=self.expected_mean)
		actual_order = sorted(metrics, key=lambda s: metrics[s]["value"])
		self.assertEqual(actual_order, expected_order)

	def test_the_won_average_is_dated_by_when_the_deal_closed_not_when_it_opened(self):
		"""A deal created this month but closed last month is not this month's win.

		The fixture cannot tell those two predicates apart -- its won deals were
		created and closed in the same month, so `get_average_won_deal_value`
		returns the same number whichever date column it filters on. Swapping
		closed_date for creation in that query passes every other test in this
		file. This deal is built to separate them.
		"""
		won_status = frappe.db.get_value("CRM Deal Status", {"type": "Won"}, "name")
		before = get_average_won_deal_value(self.from_date, self.to_date)["value"]

		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"status": won_status,
				"deal_value": 9_999_999,
				"probability": 100,
			}
		).insert(ignore_permissions=True)
		# validate() forces closed_date to today whenever the status becomes Won,
		# so backdate it underneath the controller.
		frappe.db.set_value(
			"CRM Deal", deal.name, "closed_date", add_days(self.from_date, -1), update_modified=False
		)

		after = get_average_won_deal_value(self.from_date, self.to_date)["value"]
		self.assertAlmostEqual(
			after,
			before,
			places=2,
			msg="a deal closed before the period is being counted in it -- is the query using creation?",
		)

	def test_the_fixture_defines_the_averages_these_tests_were_written_around(self):
		"""The fixture file, which cannot drift -- unlike the site it is loaded into.

		This is where the original hard-coded numbers belong: they describe
		``crm_deal/test_records.json``, so if someone edits that file the arithmetic
		in the comments above stops being a lie quietly.
		"""
		deals = self.defined_records("CRM Deal")
		by_status = {}
		for deal in deals:
			count, total = by_status.get(deal["status"], (0, 0))
			by_status[deal["status"]] = (count + 1, total + (deal.get("deal_value") or 0))

		ongoing = [by_status["Qualification"], by_status["Negotiation"]]
		ongoing_count = sum(c for c, _ in ongoing)
		ongoing_total = sum(t for _, t in ongoing)
		won_count, won_total = by_status["Won"]

		self.assertEqual((ongoing_count, ongoing_total), (21, 1_875_000))
		self.assertAlmostEqual(ongoing_total / ongoing_count, 89285.71, places=2)

		self.assertEqual((won_count, won_total), (8, 1_300_000))
		self.assertAlmostEqual(won_total / won_count, 162500.0, places=2)

		non_lost_count = ongoing_count + won_count
		non_lost_total = ongoing_total + won_total
		self.assertEqual((non_lost_count, non_lost_total), (29, 3_175_000))
		self.assertAlmostEqual(non_lost_total / non_lost_count, 109482.76, places=2)

		# Every fixture deal is in the base currency, which is what lets the
		# arithmetic above ignore exchange_rate.
		self.assertEqual({d.get("exchange_rate") for d in deals}, {1})

	def test_delta_calculation_logic(self):
		"""Test that delta values represent actual change"""
		result = get_total_leads(self.from_date, self.to_date)

		# Delta should exist and be a number
		self.assertIn("delta", result)
		self.assertIsInstance(result["delta"], (int, float))

		# Delta suffix should indicate percentage
		if "deltaSuffix" in result:
			self.assertEqual(result["deltaSuffix"], "%")

	def test_currency_symbol_consistency(self):
		"""Test that all value-based metrics use same currency symbol"""
		symbol1 = get_average_ongoing_deal_value(self.from_date, self.to_date).get("prefix")
		symbol2 = get_average_won_deal_value(self.from_date, self.to_date).get("prefix")
		symbol3 = get_average_deal_value(self.from_date, self.to_date).get("prefix")
		symbol4 = get_base_currency_symbol()

		# All should use same currency
		self.assertEqual(symbol1, symbol2)
		self.assertEqual(symbol2, symbol3)
		self.assertEqual(symbol3, symbol4)

	def test_user_isolation_across_multiple_metrics(self):
		"""Test that user filtering works consistently across all metrics"""
		user = self.user2_email

		# Get counts for user
		user_leads = get_total_leads(self.from_date, self.to_date, user)["value"]
		user_ongoing = get_ongoing_deals(self.from_date, self.to_date, user)["value"]
		user_won = get_won_deals(self.from_date, self.to_date, user)["value"]

		# Get total counts
		total_leads = get_total_leads(self.from_date, self.to_date)["value"]
		total_ongoing = get_ongoing_deals(self.from_date, self.to_date)["value"]
		total_won = get_won_deals(self.from_date, self.to_date)["value"]

		# User counts should be subset of totals
		self.assertLessEqual(user_leads, total_leads)
		self.assertLessEqual(user_ongoing, total_ongoing)
		self.assertLessEqual(user_won, total_won)

		# Verify specific user data matches expected
		self.assertEqual(user_leads, self.leads_in_period(self.user2_email))
		self.assertEqual(
			user_ongoing,
			self.deals_in_period("Open", self.user2_email)
			+ self.deals_in_period("Ongoing", self.user2_email),
		)
		self.assertEqual(user_won, self.deals_in_period("Won", self.user2_email))

	def test_time_to_close_calculations(self):
		"""Test that time to close metrics calculate correctly"""
		lead_time = get_average_time_to_close_a_lead(self.from_date, self.to_date)
		deal_time = get_average_time_to_close_a_deal(self.from_date, self.to_date)

		# Should have correct structure
		self.assertIn("value", lead_time)
		self.assertIn("suffix", lead_time)
		self.assertEqual(lead_time["suffix"], " days")

		self.assertIn("value", deal_time)
		self.assertIn("suffix", deal_time)
		self.assertEqual(deal_time["suffix"], " days")

		# Values should be non-negative
		self.assertGreaterEqual(lead_time["value"], 0)
		self.assertGreaterEqual(deal_time["value"], 0)

		# negativeIsBetter flag should be present (faster is better)
		if "negativeIsBetter" in lead_time:
			self.assertTrue(lead_time["negativeIsBetter"])
		if "negativeIsBetter" in deal_time:
			self.assertTrue(deal_time["negativeIsBetter"])

	def test_chart_data_types(self):
		"""Test that chart types return appropriate data structures"""
		# Number chart
		number_chart = get_chart("total_leads", "number", self.from_date, self.to_date)
		self.assertIn("value", number_chart)
		self.assertIsInstance(number_chart["value"], (int, float))

		# Test with different chart names
		charts = ["ongoing_deals", "won_deals", "total_leads"]
		for chart_name in charts:
			result = get_chart(chart_name, "number", self.from_date, self.to_date)
			self.assertIn("value", result, f"Chart {chart_name} missing value")
			self.assertIsInstance(result["value"], (int, float), f"Chart {chart_name} value not numeric")

	def test_dashboard_layout_structure(self):
		"""Test that dashboard returns valid layout with all required fields"""
		dashboard = get_dashboard(self.from_date, self.to_date)

		# Should be list of layout items
		self.assertIsInstance(dashboard, list)

		# Each item should have required fields
		for item in dashboard:
			self.assertIn("name", item)
			# Validate name is not empty
			self.assertTrue(item["name"])


class TestBlankGroupingLabels(IntegrationTestCase):
	"""Rows whose grouping dimension is not set must still be named.

	Every chart here groups by an optional field. They used to disagree about
	the blank bucket: five charts hard-coded the literal "Empty" across six
	call sites, and deals-by-salesperson had no final fallback at all -- it
	dropped to ``deal_owner``, itself null for an unowned deal, so the label
	came out null and the bar rendered nameless.
	"""

	ORG = "Blank Label Co"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.from_date = add_days(nowdate(), -3)
		self.to_date = add_days(nowdate(), 1)
		if not frappe.db.exists("CRM Organization", self.ORG):
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": self.ORG}).insert(
				ignore_permissions=True
			)

	def make_deal(self, **kwargs):
		doc = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.ORG, "deal_value": 1000, **kwargs}
		).insert(ignore_permissions=True)
		return doc

	def test_an_unowned_deal_is_labelled_not_left_nameless(self):
		"""The regression: a null deal_owner produced a bar with no label."""
		self.make_deal(deal_owner=None)

		rows = get_deals_by_salesperson(self.from_date, self.to_date)["data"]

		labels = [row["salesperson"] for row in rows]
		self.assertTrue(rows, "expected at least the deal just created")
		for label in labels:
			self.assertIsNotNone(label, f"a nameless bar: {rows}")
			self.assertNotEqual(str(label).strip(), "")
		self.assertIn(blank_label(), labels)

	def test_an_owned_deal_still_shows_its_owner(self):
		"""The control: the fallback must not swallow real names."""
		self.make_deal(deal_owner="Administrator")

		rows = get_deals_by_salesperson(self.from_date, self.to_date)["data"]

		self.assertIn("Administrator", [row["salesperson"] for row in rows])

	def test_blank_dimensions_agree_on_one_label(self):
		"""The point of the shared helper: no chart invents its own word."""
		self.make_deal(deal_owner=None, territory=None, industry=None, source=None)

		charts = {
			"territory": (get_deals_by_territory, "territory"),
			"industry": (get_deals_by_industry, "industry"),
			"source": (get_deals_by_source, "source"),
			"salesperson": (get_deals_by_salesperson, "salesperson"),
		}
		for name, (fn, key) in charts.items():
			with self.subTest(chart=name):
				labels = [row[key] for row in fn(self.from_date, self.to_date)["data"]]
				self.assertNotIn("Empty", labels, f"{name} still uses the old literal")

	def test_the_label_is_translated_per_call(self):
		"""Not frozen at import: a module is evaluated once per worker."""
		self.assertEqual(blank_label(), frappe._("Unassigned"))
