# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Segment analytics: the pipeline by industry and by company size.

The dashboard could say *where* deals were (territory) and *who* owned them, but
not *who we sell to*. These two charts and the report built on them answer that.

The one that needs watching is company size. Its values are labels
(``1-10``, ``201-500``, ``1000+``) and sorting them as strings gives
``1-10, 1000+, 11-50, 201-500, 51-200`` — an axis that reads as a size ordering
and is not one. Every individual number stays correct while the shape of the
chart lies, which is the worst kind of wrong for a chart. Ordering comes from the
Select's own declared option order instead, and the test below fails on the
alphabetical version.

Assertions are scoped to this suite's own deals: the site is shared, so any
site-wide total would be a coin toss.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.dashboard import (
	CHARTS,
	blank_label,
	company_size_bands,
	get_deals_by_company_size,
	get_deals_by_industry,
)
from crm.api.reports import REPORTS, get_report

ORG = "Segment Analytics Org"
INDUSTRY = "Segment Analytics Industry"


class SegmentAnalyticsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.from_date = frappe.utils.get_first_day(frappe.utils.nowdate())
		self.to_date = frappe.utils.get_last_day(frappe.utils.nowdate())
		self.deals: list[str] = []

		if not frappe.db.exists("CRM Industry", INDUSTRY):
			frappe.get_doc({"doctype": "CRM Industry", "industry": INDUSTRY}).insert(ignore_permissions=True)
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": ORG})
			.insert(ignore_if_duplicate=True)
			.name
		)

	def tearDown(self):
		for name in self.deals:
			frappe.delete_doc("CRM Deal", name, force=True, ignore_missing=True)
		super().tearDown()

	def make_deal(self, *, employees=None, industry=None, value=1000):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
				"no_of_employees": employees,
				"industry": industry,
				"deal_value": value,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		self.deals.append(doc.name)
		return doc.name

	def rows_by(self, chart, key):
		return {row[key]: row for row in chart(self.from_date, self.to_date)["data"]}

	# --- registry ---------------------------------------------------------

	def test_both_charts_are_reachable_from_the_dashboard(self):
		"""An unregistered chart cannot be rendered, however good the query is."""
		self.assertIs(CHARTS["deals_by_industry"], get_deals_by_industry)
		self.assertIs(CHARTS["deals_by_company_size"], get_deals_by_company_size)

	def test_the_segment_report_is_published(self):
		self.assertIn("pipeline_by_segment", REPORTS)

	# --- company size ordering, the interesting one -----------------------

	def test_the_bands_come_from_the_field_not_from_a_copy_in_the_code(self):
		bands = company_size_bands()
		declared = frappe.get_meta("CRM Deal").get_field("no_of_employees").options.split("\n")
		self.assertEqual(bands, [b.strip() for b in declared if b.strip()])

	def test_company_sizes_are_ordered_small_to_large_not_alphabetically(self):
		"""The regression. Alphabetically, 1000+ sorts second."""
		for band in ("1-10", "1000+", "11-50", "201-500", "51-200"):
			self.make_deal(employees=band)

		order = [
			row["company_size"] for row in get_deals_by_company_size(self.from_date, self.to_date)["data"]
		]
		bands = company_size_bands()
		mine = [band for band in order if band in bands]

		self.assertEqual(mine, [band for band in bands if band in mine])
		self.assertNotEqual(mine, sorted(mine), "the axis is in string order — the size ordering is a lie")

	def test_an_unanswered_employee_count_is_not_silently_recorded_as_the_smallest_band(self):
		"""Frappe pre-selects the first option of a Select that declares no default,
		so ``no_of_employees`` stored ``1-10`` for every deal where nobody answered.
		Building a company-size chart on that would have put the whole unanswered
		pipeline in the SMB bar and called it a finding. The field now leads with a
		blank option, so unset stays unset."""
		name = self.make_deal(employees=None)
		self.assertEqual(frappe.db.get_value("CRM Deal", name, "no_of_employees"), "")

	def test_deals_with_no_company_size_land_after_every_real_band(self):
		self.make_deal(employees="1-10")
		self.make_deal(employees=None)

		order = [
			row["company_size"] for row in get_deals_by_company_size(self.from_date, self.to_date)["data"]
		]
		self.assertIn(blank_label(), order)
		self.assertEqual(order[-1], blank_label())

	def test_an_unset_company_size_is_labelled_rather_than_blank(self):
		"""A stored empty string is not NULL, so IfNull alone leaves a nameless bar."""
		name = self.make_deal(employees=None)
		frappe.db.set_value("CRM Deal", name, "no_of_employees", "", update_modified=False)

		labels = [
			row["company_size"] for row in get_deals_by_company_size(self.from_date, self.to_date)["data"]
		]
		self.assertNotIn("", labels)
		self.assertNotIn(None, labels)

	# --- the numbers ------------------------------------------------------

	def test_the_industry_chart_counts_and_sums_its_deals(self):
		self.make_deal(industry=INDUSTRY, value=1000)
		self.make_deal(industry=INDUSTRY, value=2500)

		row = self.rows_by(get_deals_by_industry, "industry")[INDUSTRY]
		self.assertEqual(row["deals"], 2)
		self.assertEqual(row["value"], 3500)

	def test_the_company_size_chart_counts_and_sums_its_deals(self):
		self.make_deal(employees="51-200", value=400)
		self.make_deal(employees="51-200", value=600)

		row = self.rows_by(get_deals_by_company_size, "company_size")["51-200"]
		self.assertEqual(row["deals"], 2)
		self.assertEqual(row["value"], 1000)

	def test_deal_value_is_converted_at_the_stored_exchange_rate(self):
		"""Every other money aggregate does; a segment chart in mixed currencies
		would otherwise add dollars to rupees and call it a total."""
		name = self.make_deal(industry=INDUSTRY, value=100)
		frappe.db.set_value("CRM Deal", name, "exchange_rate", 3, update_modified=False)

		self.assertEqual(self.rows_by(get_deals_by_industry, "industry")[INDUSTRY]["value"], 300)

	# --- the report -------------------------------------------------------

	def test_the_report_reports_the_same_numbers_as_the_charts(self):
		"""One source of numbers: a report that recomputed would drift from the
		dashboard it sits beside, and both would look authoritative."""
		self.make_deal(industry=INDUSTRY, employees="51-200", value=1200)
		self.make_deal(industry=INDUSTRY, employees="51-200", value=800)

		rows = get_report("pipeline_by_segment", str(self.from_date), str(self.to_date))["rows"]
		by_value = {(row["segment"], row["value_of"]): row for row in rows}

		industry_row = by_value[("Industry", INDUSTRY)]
		self.assertEqual(industry_row["deals"], 2)
		self.assertEqual(industry_row["value"], 2000)

		size_row = by_value[("Company size", "51-200")]
		self.assertEqual(size_row["deals"], 2)
		self.assertEqual(size_row["value"], 2000)

	def test_the_report_covers_both_dimensions(self):
		self.make_deal(industry=INDUSTRY, employees="1-10")
		segments = {
			row["segment"]
			for row in get_report("pipeline_by_segment", str(self.from_date), str(self.to_date))["rows"]
		}
		self.assertIn("Industry", segments)
		self.assertIn("Company size", segments)

	def test_the_report_declares_a_column_for_every_key_its_rows_carry(self):
		"""A key with no column is invisible on the page and in the digest."""
		self.make_deal(industry=INDUSTRY, employees="1-10")
		report = get_report("pipeline_by_segment", str(self.from_date), str(self.to_date))
		declared = {column["key"] for column in report["columns"]}
		for row in report["rows"]:
			self.assertEqual(set(row) - declared, set())
