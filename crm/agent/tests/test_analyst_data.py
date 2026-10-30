# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""``analyst_data.run_plan``: CRM tables come from the metrics layer, ERP tables
from stubbed adapters, and an ERP failure marks its table rather than raising."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import ClassVar
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase

from crm.agent import analyst, analyst_data
from crm.integrations.acumatica.client import AcumaticaError


def make_won_deal(organization: str, value: float, closed_on: str) -> str:
	won = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name", limit=1)
	deal = frappe.get_doc(
		{
			"doctype": "CRM Deal",
			"organization": organization,
			"status": won[0],
			"deal_value": value,
			"exchange_rate": 1,
		}
	).insert()
	frappe.db.set_value("CRM Deal", deal.name, "closed_date", closed_on)
	return deal.name


def _instant(value: str) -> datetime:
	moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
	return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


class FakeAcumatica:
	"""An Acumatica client over a fixed ledger, honouring the two filters the readers
	send: a ``datetimeoffset`` window on the document date, compared as instants the
	way the server compares them, and ``Status eq '...'``."""

	def __init__(self, records: dict[str, list[dict]]):
		self.records = records
		self.reads: list[tuple[str, str]] = []

	def iter_all(self, entity, filter=None, select=None, **_kw):
		self.reads.append((entity, filter or ""))
		window = [_instant(bound) for bound in re.findall(r"datetimeoffset'([^']+)'", filter or "")]
		status = re.search(r"Status eq '([^']+)'", filter or "")
		for record in self.records.get(entity, []):
			when = _instant(record.get("Date") or record.get("ApplicationDate"))
			if window and not (window[0] <= when <= window[1]):
				continue
			if status and record.get("Status") != status.group(1):
				continue
			yield {field: {"value": value} for field, value in record.items()}


class RunPlanTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("analyst_data")
		self.addCleanup(frappe.db.rollback, save_point="analyst_data")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Analyst Data Org"})
			.insert()
			.name
		)

	def test_won_revenue_is_zero_filled_per_month_and_comes_from_the_metrics_layer(self):
		make_won_deal(self.org, 1500, "2026-05-15")
		with mock.patch.object(analyst_data, "data_start", return_value="2026-01"):
			tables = analyst_data.run_plan(
				{
					"metrics": ["won_revenue_by_month", "nope"],
					"from_date": "2026-04-01",
					"to_date": "2026-06-30",
				},
				None,
			)
		self.assertEqual([t["key"] for t in tables], ["won_revenue_by_month"])
		table = tables[0]
		self.assertEqual(table["source"], "CRM")
		self.assertEqual([row["month"] for row in table["rows"]], ["2026-04", "2026-05", "2026-06"])
		self.assertGreaterEqual(table["rows"][1]["value"], 1500)
		self.assertEqual(table["rows"][0]["value"], 0.0)
		self.assertIsNone(table["error"])

	def test_months_before_the_sites_history_are_dropped_not_shown_as_zero(self):
		"""An admin asked about 2024 on a site whose history starts in December 2025
		and was told the business sold nothing that year."""
		make_won_deal(self.org, 1500, "2026-05-15")
		with mock.patch.object(analyst_data, "data_start", return_value="2026-05"):
			table = analyst_data.run_plan(
				{"metrics": ["won_revenue_by_month"], "from_date": "2026-03-01", "to_date": "2026-06-30"},
				None,
			)[0]
		self.assertEqual([row["month"] for row in table["rows"]], ["2026-05", "2026-06"])
		self.assertIn("Vectora holds deal history from May 2026 only.", table["note"])

	def test_every_table_carries_its_computed_lines(self):
		make_won_deal(self.org, 1500, "2026-05-15")
		with mock.patch.object(analyst_data, "data_start", return_value="2026-01"):
			table = analyst_data.run_plan(
				{"metrics": ["won_revenue_by_month"], "from_date": "2026-04-01", "to_date": "2026-06-30"},
				None,
			)[0]
		self.assertTrue(table["facts"][0].startswith("Q2 2026 (April to June 2026): "), table["facts"])

	def test_the_history_starts_at_the_earliest_deal_created_or_closed(self):
		make_won_deal(self.org, 10, "2019-03-10")
		self.assertLessEqual(analyst_data.data_start(), "2019-03")

	def test_a_window_that_reaches_today_says_the_current_month_is_partial(self):
		"""Eighteen days of a month next to whole ones reads as a collapse unless
		the table says so; a window that ends before this month says nothing."""
		today = frappe.utils.getdate(frappe.utils.nowdate())
		label = f"{today.strftime('%B')} {today.year}"
		for key in ("won_revenue_by_month", "growth_rates"):
			table = analyst_data.run_plan(
				{
					"metrics": [key],
					"from_date": str(frappe.utils.add_months(today, -3)),
					"to_date": str(today),
				},
				None,
			)[0]
			self.assertIn(f"{label} is month to date.", table["note"], key)
			table = analyst_data.run_plan(
				{"metrics": [key], "from_date": "2025-01-01", "to_date": "2025-03-31"}, None
			)[0]
			self.assertNotIn("month to date", table["note"], key)

	def test_every_crm_metric_runs_without_error(self):
		"""The catalogue promises these; a runner that raises on an empty site is a bug."""
		keys = [key for key in analyst_data._CRM_RUNNERS]
		for start in range(0, len(keys), 4):
			plan = {"metrics": keys[start : start + 4], "from_date": "2026-01-01", "to_date": "2026-09-01"}
			tables = analyst_data.run_plan(plan, None)
			self.assertEqual([t["key"] for t in tables], plan["metrics"])
			for table in tables:
				self.assertIsInstance(table["rows"], list, table["key"])
				self.assertTrue(table["columns"], table["key"])

	def test_erp_metrics_are_skipped_without_an_erp(self):
		tables = analyst_data.run_plan(
			{"metrics": ["erp_cashflow_by_month"], "from_date": "2026-01-01", "to_date": "2026-03-31"}, None
		)
		self.assertEqual(tables, [])

	def test_erp_cashflow_sums_invoices_and_payments_per_month(self):
		invoices = [
			{"date": "2026-01-10", "amount": 100.0, "balance": 0.0, "due": "2026-02-09"},
			{"date": "2026-01-20", "amount": 50.0, "balance": 50.0, "due": "2026-02-19"},
			{"date": "2026-03-01", "amount": 70.0, "balance": 70.0, "due": "2026-03-31"},
		]
		payments = [{"date": "2026-01-15", "amount": 100.0}, {"date": "2026-02-02", "amount": 25.0}]
		with (
			mock.patch.object(analyst_data, "acumatica_invoices", return_value=(invoices, False)),
			mock.patch.object(analyst_data, "acumatica_payments", return_value=(payments, False)),
		):
			(cashflow,) = analyst_data.run_plan(
				{"metrics": ["erp_cashflow_by_month"], "from_date": "2026-01-01", "to_date": "2026-03-31"},
				"acumatica",
			)
		self.assertEqual(cashflow["source"], "Acumatica")
		self.assertEqual(
			cashflow["rows"],
			[
				{"month": "2026-01", "invoiced": 150.0, "received": 100.0, "net": -50.0},
				{"month": "2026-02", "invoiced": 0.0, "received": 25.0, "net": 25.0},
				{"month": "2026-03", "invoiced": 70.0, "received": 0.0, "net": -70.0},
			],
		)

	def test_receivables_are_every_open_balance_aged_against_today(self):
		"""Receivables were read through the period's invoice query and aged against its
		to_date: an invoice unpaid since before the period was missing, and on a period
		ending in December one not yet due was already overdue."""
		today = frappe.utils.getdate("2026-10-30")
		client = FakeAcumatica(
			{
				"SalesInvoice": [
					{
						"Date": "2025-06-01",
						"Amount": 1000.0,
						"Balance": 1000.0,
						"DueDate": "2025-07-01",
						"Type": "Invoice",
						"Status": "Open",
					},
					{
						"Date": "2026-09-20",
						"Amount": 500.0,
						"Balance": 500.0,
						"DueDate": "2026-11-15",
						"Type": "Invoice",
						"Status": "Open",
					},
					{
						"Date": "2026-08-01",
						"Amount": 80.0,
						"Balance": 0.0,
						"DueDate": "2026-08-31",
						"Type": "Invoice",
						"Status": "Closed",
					},
				]
			}
		)
		with mock.patch.object(analyst_data, "_acumatica_client", return_value=client):
			for from_date, to_date in (("2025-10-30", "2026-10-30"), ("2026-01-01", "2026-12-31")):
				with self.subTest(period=(from_date, to_date)):
					(table,) = analyst_data.run_plan(
						{"metrics": ["erp_receivables"], "from_date": from_date, "to_date": to_date},
						"acumatica",
						today=today,
					)
					self.assertEqual(
						table["rows"],
						[
							{"bucket": "Current", "amount": 500.0, "invoices": 1},
							{"bucket": "Overdue", "amount": 1000.0, "invoices": 1},
						],
					)
					self.assertIn("as of today", table["note"])

	def test_erpnext_receivables_are_read_by_outstanding_amount_not_by_date(self):
		with mock.patch.object(analyst_data, "_erpnext_get", return_value=[]) as get:
			analyst_data.run_plan(
				{"metrics": ["erp_receivables"], "from_date": "2026-01-01", "to_date": "2026-03-31"},
				"erpnext",
			)
		filters = get.call_args.args[2]
		self.assertIn(["outstanding_amount", ">", 0], filters)
		self.assertNotIn("posting_date", str(filters))

	def test_erp_months_stop_at_today_and_start_at_the_first_document(self):
		"""A "this year" plan listed November and December as nothing invoiced, and the
		months before the ERP's first document as nothing invoiced too."""
		today = frappe.utils.getdate("2026-10-30")
		invoices = [{"date": "2026-03-10", "amount": 100.0, "balance": 0.0, "due": None}]
		with mock.patch.object(analyst_data, "acumatica_invoices", return_value=(invoices, False)) as read:
			table = analyst_data.run_plan(
				{"metrics": ["erp_invoices_by_month"], "from_date": "2026-01-01", "to_date": "2026-12-31"},
				"acumatica",
				today=today,
			)[0]
		self.assertEqual(read.call_args.args[:2], ("2026-01-01", "2026-10-30"))
		self.assertEqual(
			[row["month"] for row in table["rows"]],
			["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09", "2026-10"],
		)
		self.assertEqual(table["rows"][0], {"month": "2026-03", "invoiced": 100.0, "invoices": 1})
		self.assertIn("before March 2026", table["note"])

	def test_a_plan_running_to_the_year_9999_is_answered_not_a_500(self):
		from crm.agent.schemas import AnalystPlan

		today = frappe.utils.getdate("2026-10-30")
		plan = analyst.normalise_plan(
			AnalystPlan(
				metrics=["erp_cashflow_by_month"], from_date="2026-01-01", to_date="9999-12-31", reasoning=""
			),
			analyst.available_keys(erp_enabled=True),
			today,
		)
		with (
			mock.patch.object(analyst_data, "acumatica_invoices", return_value=([], False)),
			mock.patch.object(analyst_data, "acumatica_payments", return_value=([], False)),
		):
			table = analyst_data.run_plan(plan, "acumatica", today=today)[0]
		self.assertIsNone(table["error"])
		self.assertEqual(table["rows"], [])

	def test_an_unreachable_erp_marks_its_table_and_the_crm_table_still_runs(self):
		with mock.patch.object(analyst_data, "acumatica_invoices", side_effect=AcumaticaError("boom")):
			tables = analyst_data.run_plan(
				{
					"metrics": ["won_revenue_by_month", "erp_invoices_by_month"],
					"from_date": "2026-01-01",
					"to_date": "2026-02-28",
				},
				"acumatica",
			)
		self.assertEqual([t["key"] for t in tables], ["won_revenue_by_month", "erp_invoices_by_month"])
		self.assertIsNone(tables[0]["error"])
		self.assertEqual(tables[1]["error"], "unreachable")
		self.assertEqual(tables[1]["rows"], [])

	def test_enabled_erp_is_none_when_both_integrations_are_off(self):
		with mock.patch.object(frappe.db, "get_single_value", return_value=0):
			self.assertIsNone(analyst_data.enabled_erp())


class AcumaticaDocumentsTest(IntegrationTestCase):
	"""Which Acumatica documents are money invoiced or received, and on which days."""

	STATUSES = ("Open", "Closed", "On Hold", "Balanced", "Voided", "Canceled")

	def read(self, client, from_date="2026-01-01", to_date="2026-03-31"):
		with mock.patch.object(analyst_data, "_acumatica_client", return_value=client):
			invoices, _partial = analyst_data.acumatica_invoices(from_date, to_date)
			payments, _partial = analyst_data.acumatica_payments(from_date, to_date)
		return invoices, payments

	def test_only_released_documents_count(self):
		"""Only the document Type was checked: a cancelled, voided or held invoice
		counted as invoiced -- twenty cancelled ones, R439,698, in MBP's export."""
		client = FakeAcumatica(
			{
				"SalesInvoice": [
					{
						"Date": "2026-02-10",
						"Amount": 100.0,
						"Balance": 0.0,
						"DueDate": "2026-03-12",
						"Type": "Invoice",
						"Status": status,
					}
					for status in self.STATUSES
				],
				"Payment": [
					{
						"ApplicationDate": "2026-02-11",
						"PaymentAmount": 10.0,
						"Type": "Payment",
						"Status": status,
					}
					for status in self.STATUSES
				],
			}
		)
		invoices, payments = self.read(client)
		self.assertEqual((len(invoices), len(payments)), (2, 2))

	def test_the_window_is_the_tenants_own_days(self):
		"""Acumatica stamps a document date as local midnight with the tenant's offset
		and compares a "Z" bound in UTC, so the window lost its first local day and
		took in the day after its last."""
		days = (
			"2025-12-31T00:00:00+02:00",
			"2026-01-01T00:00:00+02:00",
			"2026-03-31T00:00:00+02:00",
			"2026-04-01T00:00:00+02:00",
		)
		client = FakeAcumatica(
			{
				"SalesInvoice": [
					{"Date": day, "Amount": 1.0, "Balance": 0.0, "Type": "Invoice", "Status": "Closed"}
					for day in days
				],
				"Payment": [
					{"ApplicationDate": day, "PaymentAmount": 1.0, "Type": "Payment", "Status": "Closed"}
					for day in days
				],
			}
		)
		invoices, payments = self.read(client)
		self.assertEqual([row["date"] for row in invoices], ["2026-01-01", "2026-03-31"])
		self.assertEqual([row["date"] for row in payments], ["2026-01-01", "2026-03-31"])


class QuietAccountsTest(IntegrationTestCase):
	"""``accounts_going_quiet`` used to look at ``_working_deal_rows()[:200]``.
	That list comes back in CRM Deal's default order, ``modified desc``, so the
	slice kept the 200 deals touched most recently -- the ones least likely to
	be going quiet -- and silently dropped every other open deal on the site.

	The padding rows here stand in for 200 recently edited deals ahead of the
	one that matters; they are never flagged (no close date, no cadence), so
	the only question is whether the deal behind them is still scanned."""

	PADDING = 200

	def setUp(self):
		super().setUp()
		frappe.db.savepoint("quiet_accounts")
		self.addCleanup(frappe.db.rollback, save_point="quiet_accounts")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Quiet Accounts Org"})
			.insert()
			.name
		)
		early = frappe.get_all(
			"CRM Deal Status",
			filters={"type": ("in", ("Open", "Ongoing")), "probability": ("<", 50)},
			pluck="name",
			limit=1,
		)
		self.deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
				"status": early[0],
				# closing inside the horizon while the stage is still early: the
				# slip-risk reason, which needs no activity history to fire
				"expected_closure_date": frappe.utils.add_days(frappe.utils.today(), 2),
			}
		).insert()

	def test_a_quiet_deal_behind_two_hundred_fresher_ones_is_still_reported(self):
		real_rows = analyst_data._working_deal_rows()
		quiet = [row for row in real_rows if row["name"] == self.deal.name]
		self.assertEqual(len(quiet), 1)
		padding = [
			{
				**quiet[0],
				"name": f"QUIET-PAD-{index:04d}",
				"organization": "Padding Org",
				"expected_closure_date": None,
			}
			for index in range(self.PADDING)
		]
		with mock.patch.object(analyst_data, "_working_deal_rows", return_value=[*padding, *quiet]):
			tables = analyst_data.run_plan(
				{
					"metrics": ["accounts_going_quiet"],
					"from_date": "2026-01-01",
					"to_date": frappe.utils.today(),
				},
				None,
			)
		rows = tables[0]["rows"]
		self.assertIn(self.org, [row["organization"] for row in rows])
		entry = next(row for row in rows if row["organization"] == self.org)
		self.assertEqual(entry["deals"], 1)
		self.assertIn("close date near", entry["reason"])


class DeadlineTest(IntegrationTestCase):
	"""#27: the step between the two completions used to have no clock at all.

	Invoice and payment reads page 100 rows at a time up to 5,000, each page a
	30-second request, while deal scoring runs in the same worker. One cashflow
	question could hold a web worker and one of four site-wide model slots for
	minutes -- long after nginx had returned a 504 and the admin had been told
	the model could not be reached.
	"""

	PLAN: ClassVar[dict] = {
		"metrics": ["won_revenue_by_month", "erp_invoices_by_month"],
		"from_date": "2026-01-01",
		"to_date": "2026-02-28",
	}

	def test_without_a_deadline_everything_runs(self):
		with mock.patch.object(analyst_data, "acumatica_invoices", return_value=([], False)):
			tables = analyst_data.run_plan(self.PLAN, "acumatica")
		self.assertEqual([table["error"] for table in tables], [None, None])

	def test_a_passed_deadline_reports_the_remaining_tables_rather_than_computing_them(self):
		with (
			mock.patch.object(analyst_data, "acumatica_invoices", return_value=([], False)) as read,
			mock.patch.object(analyst_data.time, "monotonic", return_value=1000.0),
		):
			tables = analyst_data.run_plan(self.PLAN, "acumatica", deadline=999.0)
		self.assertEqual(
			[table["key"] for table in tables], ["won_revenue_by_month", "erp_invoices_by_month"]
		)
		self.assertEqual([table["error"] for table in tables], [analyst_data.SKIPPED_NOTE] * 2)
		read.assert_not_called()

	def test_a_partial_erp_read_is_flagged_in_the_figures(self):
		"""The answer prompt carries a table's note into the FIGURES block, so a
		floor can be described as a floor instead of read as a total."""
		with mock.patch.object(analyst_data, "acumatica_invoices", return_value=([], True)):
			tables = analyst_data.run_plan({**self.PLAN, "metrics": ["erp_invoices_by_month"]}, "acumatica")
		self.assertIn(analyst_data.PARTIAL_NOTE, tables[0]["note"])
		self.assertIsNone(tables[0]["error"])

	def test_pagination_stops_when_less_than_one_page_of_time_is_left(self):
		"""Checked before the fetch, because the generator has already paid for a
		page by the time its rows arrive."""
		pages = [
			{
				"Date": {"value": "2026-01-10"},
				"Amount": {"value": 10},
				"Balance": {"value": 0},
				"Status": {"value": "Closed"},
			}
			for _ in range(250)
		]
		clock = iter([0.0] + [float(index) for index in range(1, 400)])
		client = mock.Mock()
		client.iter_all.return_value = iter(pages)
		with (
			mock.patch.object(analyst_data, "_acumatica_client", return_value=client),
			mock.patch.object(analyst_data.time, "monotonic", side_effect=lambda: next(clock)),
		):
			# 60 seconds of budget: the first rows are read, and the read stops
			# once fewer than ERP_TIMEOUT seconds remain
			rows, partial = analyst_data.acumatica_invoices("2026-01-01", "2026-02-28", deadline=60.0)
		self.assertTrue(partial)
		self.assertLess(len(rows), len(pages))

	def test_an_erpnext_request_is_bounded_by_the_time_left(self):
		self.assertEqual(analyst_data._erpnext_timeout(None), analyst_data.ERP_TIMEOUT)
		with mock.patch.object(analyst_data.time, "monotonic", return_value=100.0):
			self.assertEqual(analyst_data._erpnext_timeout(105.0), 5.0)
			self.assertEqual(analyst_data._erpnext_timeout(1000.0), float(analyst_data.ERP_TIMEOUT))
			# never zero or negative: requests reads that as "no timeout at all"
			self.assertEqual(analyst_data._erpnext_timeout(50.0), 1.0)


class RowCapTest(IntegrationTestCase):
	"""A read stopped at ERP_ROW_CAP used to report itself complete: the totals of a
	long window on a big tenant fell short with nothing to say so."""

	CAP = 5

	def setUp(self):
		super().setUp()
		patcher = mock.patch.object(analyst_data, "ERP_ROW_CAP", self.CAP)
		patcher.start()
		self.addCleanup(patcher.stop)

	def acumatica(self, documents: int):
		return FakeAcumatica(
			{
				"SalesInvoice": [
					{
						"Date": "2026-01-10",
						"Amount": 100.0,
						"Balance": 0.0,
						"Type": "Invoice",
						"Status": "Closed",
					}
				]
				* documents,
				"Payment": [
					{
						"ApplicationDate": "2026-01-10",
						"PaymentAmount": 100.0,
						"Type": "Payment",
						"Status": "Closed",
					}
				]
				* documents,
			}
		)

	def test_an_acumatica_read_stopped_at_the_cap_is_partial(self):
		with mock.patch.object(analyst_data, "_acumatica_client", return_value=self.acumatica(self.CAP + 3)):
			invoices = analyst_data.acumatica_invoices("2026-01-01", "2026-01-31")
			payments = analyst_data.acumatica_payments("2026-01-01", "2026-01-31")
		self.assertEqual((len(invoices[0]), invoices[1]), (self.CAP, True))
		self.assertEqual((len(payments[0]), payments[1]), (self.CAP, True))

	def test_an_acumatica_window_holding_exactly_the_cap_is_complete(self):
		with mock.patch.object(analyst_data, "_acumatica_client", return_value=self.acumatica(self.CAP)):
			invoices = analyst_data.acumatica_invoices("2026-01-01", "2026-01-31")
			payments = analyst_data.acumatica_payments("2026-01-01", "2026-01-31")
		self.assertEqual((len(invoices[0]), invoices[1]), (self.CAP, False))
		self.assertEqual((len(payments[0]), payments[1]), (self.CAP, False))

	def test_an_erpnext_read_past_the_cap_is_partial(self):
		invoice = {"posting_date": "2026-01-10", "grand_total": 100.0, "outstanding_amount": 0.0}
		payment = {"posting_date": "2026-01-10", "paid_amount": 100.0}
		for documents, partial in ((self.CAP + 1, True), (self.CAP, False)):
			with self.subTest(documents=documents):
				with mock.patch.object(analyst_data, "_erpnext_get", return_value=[invoice] * documents):
					rows, cut = analyst_data.erpnext_invoices("2026-01-01", "2026-01-31")
				self.assertEqual((len(rows), cut), (self.CAP, partial))
				with mock.patch.object(analyst_data, "_erpnext_get", return_value=[payment] * documents):
					rows, cut = analyst_data.erpnext_payments("2026-01-01", "2026-01-31")
				self.assertEqual((len(rows), cut), (self.CAP, partial))

	def test_the_erpnext_request_asks_for_one_row_past_the_cap(self):
		"""Asking for the cap itself, a window holding exactly the cap and one holding
		more come back alike."""
		response = mock.Mock()
		response.json.return_value = {"data": []}
		settings = mock.Mock(erpnext_site_url="https://erp.test", api_key="key")
		settings.get_password.return_value = "secret"
		with (
			mock.patch.object(frappe, "get_cached_doc", return_value=settings),
			mock.patch.object(analyst_data.requests, "get", return_value=response) as get,
		):
			analyst_data.erpnext_invoices("2026-01-01", "2026-01-31")
		self.assertEqual(get.call_args.kwargs["params"]["limit_page_length"], self.CAP + 1)

	def test_a_capped_table_says_its_figures_are_a_floor(self):
		with mock.patch.object(analyst_data, "_acumatica_client", return_value=self.acumatica(self.CAP + 3)):
			(table,) = analyst_data.run_plan(
				{"metrics": ["erp_invoices_by_month"], "from_date": "2026-01-01", "to_date": "2026-01-31"},
				"acumatica",
				today=frappe.utils.getdate("2026-10-30"),
			)
		self.assertIn(analyst_data.PARTIAL_NOTE, table["note"])
		self.assertEqual(table["rows"][0]["invoiced"], 100.0 * self.CAP)


class TileTest(IntegrationTestCase):
	"""The single-figure tables read a dashboard tile, which used to lose both the
	comparison the catalogue promises and the fraction of a day."""

	def test_average_deal_value_carries_the_period_before(self):
		def tile(from_date, to_date):
			current = str(frappe.utils.getdate(from_date)) == "2026-07-01"
			return {"value": 120000.0 if current else 90000.0, "delta": 30000.0 if current else 0}

		with mock.patch("crm.api.dashboard.get_average_deal_value", side_effect=tile) as read:
			rows, note = analyst_data._CRM_RUNNERS["average_deal_value"]("2026-07-01", "2026-09-30")
		self.assertEqual(
			rows,
			[
				{"metric": "Average deal value", "value": 120000.0},
				{"metric": "Average deal value, period before", "value": 90000.0},
				{"metric": "Change against the period before", "value": 30000.0},
			],
		)
		# the period before is the same length, ending the day before
		self.assertEqual(
			[tuple(str(frappe.utils.getdate(day)) for day in call.args) for call in read.call_args_list],
			[("2026-07-01", "2026-09-30"), ("2026-03-31", "2026-06-30")],
		)
		self.assertIn("2026-03-31 to 2026-06-30", note)

	def test_with_nothing_before_it_says_so_rather_than_reporting_no_change(self):
		def tile(from_date, to_date):
			current = str(frappe.utils.getdate(from_date)) == "2026-07-01"
			# the tile's delta is 0 here too: "no change" and "nothing to compare" look alike
			return {"value": 120000.0 if current else 0, "delta": 0}

		with mock.patch("crm.api.dashboard.get_average_deal_value", side_effect=tile):
			rows, note = analyst_data._CRM_RUNNERS["average_deal_value"]("2026-07-01", "2026-09-30")
		self.assertEqual(rows, [{"metric": "Average deal value", "value": 120000.0}])
		self.assertIn("Nothing to compare against", note)

	def test_days_to_close_are_rounded_not_truncated(self):
		with mock.patch(
			"crm.api.dashboard.get_average_time_to_close_a_deal", return_value={"value": 12.9, "delta": 0}
		):
			rows, _note = analyst_data._CRM_RUNNERS["time_to_close"]("2026-07-01", "2026-09-30")
		self.assertEqual(rows, [{"metric": "Average days to close", "days": 13}])


class ProjectionTest(IntegrationTestCase):
	def test_a_window_ending_in_the_past_projects_the_months_after_today(self):
		"""Continued from the window's last month, "the next three months" of a plan
		for January to June were July to September -- months that had happened."""

		def won(from_date, to_date):
			return {month: 100000.0 for month in analyst.months_between(str(from_date), str(to_date))}

		with (
			mock.patch("frappe.utils.nowdate", return_value="2026-10-30"),
			mock.patch("crm.api.dashboard.actual_by_month", side_effect=won),
		):
			points, note = analyst_data._revenue_projection("2026-01-01", "2026-06-30")
		self.assertEqual(
			[point["month"] for point in points if point["kind"] == "projected"],
			["2026-11", "2026-12", "2027-01"],
		)
		self.assertEqual(
			[point["month"] for point in points if point["kind"] == "actual"],
			["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"],
		)
		self.assertIn("after October 2026", note)
		self.assertNotIn("shown to date", note)


class OwnerlessDealTest(IntegrationTestCase):
	"""#24: get_fullname() substitutes the session user when its argument is falsy."""

	def test_an_unowned_at_risk_deal_is_not_reported_under_the_asker_s_name(self):
		scored = [{"name": "CRM-DEAL-OWNERLESS", "score": 10, "factors": []}]
		detail = frappe._dict(
			{"name": "CRM-DEAL-OWNERLESS", "organization": "Acme", "deal_owner": None, "deal_value": 100}
		)
		with (
			mock.patch("crm.api.dashboard._at_risk_deals", return_value=scored),
			mock.patch.object(frappe, "get_list", return_value=[detail]),
		):
			rows, _note = analyst_data._deals_at_risk("2026-01-01", "2026-02-28")
		self.assertEqual(rows[0]["owner"], "")
		self.assertNotIn(frappe.utils.get_fullname(frappe.session.user), rows[0]["owner"])
