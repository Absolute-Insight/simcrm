# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The report builder, and the assertion that keeps it from becoming a second truth.

``reports.py`` states the rule: *nothing builds its own aggregate*, because two
aggregates over the same question drift and then the dashboard and the report
disagree in front of a client. A generic builder is by construction a second
query path, so the rule cannot be kept by architecture here -- only by
measurement.

:class:`ConformanceTest` is that measurement. For every (dimension, measure)
pair an existing chart or built-in report also computes, it asserts the two
produce identical numbers over the same fixture. If the builder's query drifts
from the shared aggregate -- a different join, a different date column, a
different money basis -- these fail. They are the reason this module is allowed
to exist.

The comparisons are only worth something if the two sides are asked the *same*
question, so each one matches the built-in's own semantics exactly: the stage
report is a snapshot of open pipeline with no period, while the source and
territory charts count deals *created* in a period across every status. Getting
that wrong would produce a suite that passes by comparing two different things.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import report_builder
from crm.api.dashboard import (
	get_deals_by_industry,
	get_deals_by_source,
	get_deals_by_territory,
	pipeline_by_stage,
)
from crm.api.report_builder import DIMENSIONS, MEASURES, STATUS_SCOPES, build_rows, run

TERRITORY = "Report Builder Region"
SOURCE = "Report Builder Source"
SCOPED_REP = "builder-scoped@crmtest.test"
OTHER_REP = "builder-other@crmtest.test"
MANAGER = "builder-manager@crmtest.test"


class BuilderFixture:
	"""Deals spread across every dimension the builder groups by."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.created: list[tuple[str, str]] = []
		cls.from_date = str(frappe.utils.add_days(frappe.utils.nowdate(), -5))
		cls.to_date = str(frappe.utils.add_days(frappe.utils.nowdate(), 5))

		# Every dimension the fixture exercises is a Link, so its masters have to
		# exist before a deal can reference them.
		if not frappe.db.exists("CRM Territory", TERRITORY):
			frappe.get_doc({"doctype": "CRM Territory", "territory_name": TERRITORY}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists("CRM Lead Source", SOURCE):
			frappe.get_doc({"doctype": "CRM Lead Source", "source_name": SOURCE}).insert(
				ignore_permissions=True
			)
		for industry in ("Software", "Healthcare"):
			if not frappe.db.exists("CRM Industry", industry):
				frappe.get_doc({"doctype": "CRM Industry", "industry": industry}).insert(
					ignore_permissions=True
				)
		cls.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Report Builder Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		cls.won_status = frappe.db.get_value("CRM Deal Status", {"type": "Won"}, "name")
		cls.open_status = frappe.db.get_value(
			"CRM Deal Status", {"type": ("in", ("Open", "Ongoing"))}, "name"
		)

		# Differing values per group, so a builder that ignored the grouping and
		# returned one bucket, or summed the wrong column, could not agree by luck.
		plan = (
			("Software", "11-50", 30000, 2),
			("Healthcare", "51-200", 70000, 3),
			("", "", 5000, 1),  # the unanswered bucket -- stored as '', not NULL
		)
		for industry, size, value, count in plan:
			for _index in range(count):
				cls.make_deal(industry=industry, no_of_employees=size, expected_deal_value=value)
		cls.make_deal(
			industry="Software",
			no_of_employees="11-50",
			expected_deal_value=90000,
			deal_value=90000,
			status=cls.won_status,
		)

	@classmethod
	def make_deal(cls, **fields):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": cls.org,
				"territory": TERRITORY,
				"source": SOURCE,
				"exchange_rate": 1,
				"probability": 40,
				**{k: v for k, v in fields.items() if v not in (None,)},
			}
		).insert(ignore_permissions=True)
		cls.created.append(("CRM Deal", doc.name))
		return doc.name

	@classmethod
	def tearDownClass(cls):
		for doctype, name in reversed(cls.created):
			frappe.delete_doc(doctype, name, force=True, ignore_missing=True)
		super().tearDownClass()


class ConformanceTest(BuilderFixture, IntegrationTestCase):
	"""The builder must agree with every built-in that answers the same question.

	This is the whole justification for a second query path existing.
	"""

	def as_map(self, rows, key, value):
		return {row[key]: row[value] or 0 for row in rows}

	def builder_map(self, **kwargs):
		return {row["label"]: row["value"] or 0 for row in build_rows(**kwargs)}

	def test_stage_counts_match_the_pipeline_report(self):
		"""Open pipeline as it stands now -- no period, which is what a pipeline
		report means and what pipeline_by_stage does by default."""
		built_in = self.as_map(pipeline_by_stage(), "stage", "deals")
		built = self.builder_map(dimension="stage", measure="deals", status_scope="open")
		self.assertEqual(built, built_in)

	def test_stage_expected_value_matches_the_pipeline_report(self):
		built_in = self.as_map(pipeline_by_stage(), "stage", "total_value")
		built = self.builder_map(dimension="stage", measure="expected_value", status_scope="open")
		self.assertEqual(
			{k: round(v, 2) for k, v in built.items()},
			{k: round(v, 2) for k, v in built_in.items()},
		)

	def test_stage_weighted_value_matches_the_pipeline_report(self):
		"""The measure most likely to drift: it multiplies by probability, and
		doing that in a different place gives a different rounding."""
		built_in = self.as_map(pipeline_by_stage(), "stage", "weighted_value")
		built = self.builder_map(dimension="stage", measure="weighted_value", status_scope="open")
		self.assertEqual(
			{k: round(v, 2) for k, v in built.items()},
			{k: round(v, 2) for k, v in built_in.items()},
		)

	def test_source_counts_match_the_source_chart(self):
		"""The chart counts deals *created* in the period across every status, so
		the builder is asked exactly that -- not open pipeline."""
		built_in = self.as_map(get_deals_by_source(self.from_date, self.to_date)["data"], "source", "count")
		built = self.builder_map(
			dimension="source",
			measure="deals",
			from_date=self.from_date,
			to_date=self.to_date,
			status_scope="all",
			date_field="creation",
		)
		self.assertEqual(built.get(SOURCE), built_in.get(SOURCE))

	def test_territory_counts_match_the_territory_chart(self):
		built_in = self.as_map(
			get_deals_by_territory(self.from_date, self.to_date)["data"], "territory", "deals"
		)
		built = self.builder_map(
			dimension="territory",
			measure="deals",
			from_date=self.from_date,
			to_date=self.to_date,
			status_scope="all",
			date_field="creation",
		)
		self.assertEqual(built.get(TERRITORY), built_in.get(TERRITORY))

	def test_industry_counts_match_the_industry_chart(self):
		built_in = self.as_map(
			get_deals_by_industry(self.from_date, self.to_date)["data"], "industry", "deals"
		)
		built = self.builder_map(
			dimension="industry",
			measure="deals",
			from_date=self.from_date,
			to_date=self.to_date,
			status_scope="all",
			date_field="creation",
		)
		for industry in ("Software", "Healthcare"):
			with self.subTest(industry=industry):
				self.assertEqual(built.get(industry), built_in.get(industry))

	def test_the_conformance_comparison_can_actually_fail(self):
		"""Guards the guard. If the fixture produced one bucket, or the built-ins
		returned nothing here, every assertion above would pass vacuously."""
		stages = pipeline_by_stage()
		self.assertTrue(stages, "the fixture produced no open pipeline to compare")
		built = self.builder_map(dimension="stage", measure="deals", status_scope="open")
		self.assertTrue(built)
		# and the numbers are not all identical, so an equality check means something
		by_industry = self.builder_map(
			dimension="industry",
			measure="deals",
			from_date=self.from_date,
			to_date=self.to_date,
			status_scope="all",
			date_field="creation",
		)
		self.assertGreater(len({v for v in by_industry.values()}), 1)


class GroupingTest(BuilderFixture, IntegrationTestCase):
	def rows(self, **kwargs):
		kwargs.setdefault("status_scope", "all")
		return build_rows(**kwargs)

	def test_every_registered_dimension_groups_without_error(self):
		for key in DIMENSIONS:
			with self.subTest(dimension=key):
				self.assertIsInstance(self.rows(dimension=key, measure="deals"), list)

	def test_every_registered_measure_aggregates_without_error(self):
		for key in MEASURES:
			scope = MEASURES[key].requires_scope or "all"
			with self.subTest(measure=key):
				self.assertIsInstance(build_rows(dimension="stage", measure=key, status_scope=scope), list)

	def test_an_unanswered_field_is_named_rather_than_dropped(self):
		"""IfNull cannot see a stored empty string, and Frappe writes '' for an
		untouched Select. Left to SQL the unanswered deals joined the first band
		and read as a fact about the pipeline rather than a gap in it."""
		labels = [row["label"] for row in self.rows(dimension="industry", measure="deals")]
		self.assertIn("Unset", labels)

	def test_company_size_comes_back_in_band_order_not_by_size(self):
		"""Sorting an ordinal dimension by its measure puts '1000+' between
		'11-50' and '201-500', which reads as noise."""
		bands = report_builder._ordered_values("company_size")
		labels = [row["label"] for row in self.rows(dimension="company_size", measure="deals")]
		ranked = [label for label in labels if label in bands]
		self.assertEqual(ranked, sorted(ranked, key=bands.index))

	def test_unset_sorts_after_the_declared_bands_rather_than_vanishing(self):
		labels = [row["label"] for row in self.rows(dimension="company_size", measure="deals")]
		self.assertIn("Unset", labels)
		self.assertEqual(labels[-1], "Unset")

	def test_a_measure_and_a_total_are_different_questions(self):
		"""avg is not sum: a builder that wired both to Sum would pass every
		count-based test above."""
		total = self.rows(dimension="industry", measure="expected_value")
		average = self.rows(dimension="industry", measure="avg_expected_value")
		software_total = next(r["value"] for r in total if r["label"] == "Software")
		software_avg = next(r["value"] for r in average if r["label"] == "Software")
		self.assertNotEqual(round(software_total, 2), round(software_avg, 2))


class ScopingTest(IntegrationTestCase):
	"""The permission guard, which nothing else here can see.

	Every other test in this file runs as Administrator, who reads everything --
	so deleting ``scope_deals`` from the builder left all of them green. That was
	found by mutation, and it is the most security-sensitive line in the module:
	hand-built aggregates never pass through frappe's
	``permission_query_conditions``, so without it the builder is the one endpoint
	that hands a rep the whole company's pipeline.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email, name in ((SCOPED_REP, "Scoped"), (OTHER_REP, "Other")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True)
				user.add_roles("Sales User")

		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Scoping Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.made = []
		# One deal each, with different values, so "saw only mine" and "saw
		# everything" cannot produce the same number.
		self.mine = self.deal_for(SCOPED_REP, 11000)
		self.theirs = self.deal_for(OTHER_REP, 22000)

	def deal_for(self, owner, value):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
				"deal_owner": owner,
				"expected_deal_value": value,
				"exchange_rate": 1,
			}
		).insert(ignore_permissions=True)
		self.made.append(doc.name)
		return doc.name

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.made:
			frappe.delete_doc("CRM Deal", name, force=True, ignore_missing=True)
		super().tearDown()

	def total(self):
		rows = run(dimension="owner", measure="expected_value", status_scope="all")["rows"]
		return {row["label"]: row["value"] for row in rows}

	def test_a_rep_reads_their_own_deals_and_not_another_reps(self):
		frappe.set_user(SCOPED_REP)
		totals = self.total()
		self.assertIn(SCOPED_REP, totals)
		self.assertNotIn(OTHER_REP, totals)

	def test_the_control_still_fires(self):
		"""Without this, a builder returning nothing at all would pass the test
		above -- 'saw no one else's deals' is also what broken looks like."""
		frappe.set_user("Administrator")
		totals = self.total()
		self.assertIn(SCOPED_REP, totals)
		self.assertIn(OTHER_REP, totals)

	def test_a_manager_reads_their_own_subtree_and_not_the_company(self):
		"""The case that actually exercises ``scope_deals``.

		A plain Sales User is pinned by ``pin_user``, so ``belongs_to`` does the
		filtering and deleting ``scope_deals`` changes nothing for them -- which is
		exactly why the first version of this class missed the mutation. An
		in-hierarchy Sales Manager is pinned to nobody, so the subtree restriction
		is the only thing standing between them and the whole company's pipeline.
		"""
		from frappe.utils.nestedset import rebuild_tree

		from crm.permissions.test_org_hierarchy import make_hierarchy_node, make_user

		make_user(MANAGER, roles=["Sales Manager"])
		make_user(SCOPED_REP, roles=["Sales User"])
		node = make_hierarchy_node(MANAGER, is_group=1)
		make_hierarchy_node(SCOPED_REP, reports_to=node.name)
		rebuild_tree("CRM Sales Hierarchy")
		settings = frappe.get_single("FCRM Settings")
		was_enabled = settings.enable_sales_hierarchy
		settings.enable_sales_hierarchy = 1
		settings.save(ignore_permissions=True)
		self.addCleanup(self._restore_hierarchy, was_enabled)

		frappe.set_user(MANAGER)
		totals = self.total()
		# their own report's deals, yes; a rep outside the subtree, no
		self.assertIn(SCOPED_REP, totals)
		self.assertNotIn(OTHER_REP, totals)

	def _restore_hierarchy(self, was_enabled):
		frappe.set_user("Administrator")
		settings = frappe.get_single("FCRM Settings")
		settings.enable_sales_hierarchy = was_enabled
		settings.save(ignore_permissions=True)

	def test_naming_another_rep_does_not_get_you_their_numbers(self):
		"""``pin_user`` pins a plain Sales User to themselves rather than raising --
		raising is reserved for a manager naming someone outside their own subtree.
		Either way the parameter cannot be used to read another rep's figures, and
		this asserts the outcome rather than the mechanism."""
		frappe.set_user(SCOPED_REP)
		totals = {
			row["label"]: row["value"]
			for row in run(dimension="owner", measure="expected_value", status_scope="all", user=OTHER_REP)[
				"rows"
			]
		}
		self.assertNotIn(OTHER_REP, totals)


class ValidationTest(IntegrationTestCase):
	"""Dimension and measure become column names, so the registries are the
	boundary between a caller and the database."""

	def test_an_unknown_dimension_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			run(dimension="deal_value; drop table", measure="deals")

	def test_an_unknown_measure_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			run(dimension="stage", measure="nonsense")

	def test_an_unknown_status_scope_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			run(dimension="stage", measure="deals", status_scope="everything")

	def test_an_arbitrary_date_column_is_refused(self):
		"""date_field is a column name too."""
		with self.assertRaises(frappe.ValidationError):
			run(dimension="stage", measure="deals", date_field="modified_by")

	def test_a_realised_measure_refuses_an_open_scope_rather_than_switching_it(self):
		"""Silently switching the scope answers a different question than the one
		asked; refusing says which question the measure can answer."""
		with self.assertRaises(frappe.ValidationError):
			run(dimension="industry", measure="won_value", status_scope="open")

	def test_the_same_measure_is_allowed_in_its_own_scope(self):
		result = run(dimension="industry", measure="won_value", status_scope="won")
		self.assertIn("rows", result)

	def test_the_registries_are_closed(self):
		self.assertEqual(set(STATUS_SCOPES), {"open", "won", "lost", "all"})
		self.assertNotIn("__builtins__", DIMENSIONS)


class ResultShapeTest(BuilderFixture, IntegrationTestCase):
	def test_the_result_names_its_own_columns_and_title(self):
		result = run(dimension="industry", measure="deals", status_scope="all")
		self.assertEqual([c["key"] for c in result["columns"]], ["label", "value"])
		self.assertIn("Industry", result["columns"][0]["label"])
		self.assertIn("by industry", result["title"])

	def test_a_currency_measure_declares_itself_as_currency(self):
		result = run(dimension="industry", measure="expected_value", status_scope="all")
		self.assertEqual(result["columns"][1]["type"], "currency")

	def test_the_territory_filter_is_reported_as_reaching_every_dimension(self):
		"""Unlike two of the built-in reports, which cannot slice by territory and
		say so. Every dimension here is a column on CRM Deal."""
		result = run(dimension="industry", measure="deals", status_scope="all", territory=TERRITORY)
		self.assertTrue(result["territory_filtered"])
		self.assertEqual(result["territory"], TERRITORY)

	def test_no_territory_means_no_claim_of_filtering(self):
		result = run(dimension="industry", measure="deals", status_scope="all")
		self.assertFalse(result["territory_filtered"])
		self.assertIsNone(result["territory"])

	def test_an_unknown_territory_returns_nothing_rather_than_everything(self):
		result = run(dimension="industry", measure="deals", status_scope="all", territory="No Such Region")
		self.assertEqual(sum(row["value"] for row in result["rows"]), 0)

	def test_the_options_endpoint_describes_every_registry_entry(self):
		options = report_builder.describe()
		self.assertEqual(
			{d["key"] for d in options["dimensions"]},
			set(DIMENSIONS),
		)
		self.assertEqual({m["key"] for m in options["measures"]}, set(MEASURES))
		self.assertEqual({s["key"] for s in options["status_scopes"]}, set(STATUS_SCOPES))
