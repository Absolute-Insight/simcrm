"""Spreadsheet import tests.

The transforms are pure -- values in, values out -- so the corruption rules live
here without a site. The importers run against the test site further down,
against small workbooks the tests build themselves: the MBP files are the
client's data and are never committed.
"""

from __future__ import annotations

import json
import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase
from openpyxl import Workbook

from crm.integrations.acumatica import spreadsheet as ss
from crm.integrations.acumatica.install import ensure_custom_fields

COUNTRIES = {"za": "South Africa", "na": "Namibia", "mz": "Mozambique"}


class TransformTest(UnitTestCase):
	def test_only_the_cod_suffix_is_stripped(self):
		self.assertEqual(ss.normalise_account_name("2HK Trading (Pty) Ltd - COD"), "2HK Trading (Pty) Ltd")
		self.assertEqual(ss.normalise_account_name("ProProcess Fabrication - Cod"), "ProProcess Fabrication")
		for kept in (
			"Impala Platinum Limited - Shaft 10",
			"Sibanye Gold Ltd - Driefontein Division",
			"Nafasi Water - Mozambique",
			"Plain Name",
		):
			self.assertEqual(ss.normalise_account_name(kept), kept)

	def test_placeholder_and_list_emails_are_dropped(self):
		self.assertIsNone(ss.usable_email("no@email.co.za"))
		self.assertIsNone(ss.usable_email("a@x.co.za; statements@y.com"))
		self.assertIsNone(ss.usable_email(None))
		self.assertIsNone(ss.usable_email(""))
		self.assertEqual(ss.usable_email("  Katlego@yendelela.co.za "), "katlego@yendelela.co.za")

	def test_local_phones_become_e164(self):
		self.assertEqual(ss.normalise_phone("0792530729"), "+27792530729")
		self.assertEqual(ss.normalise_phone("011 849 1584"), "+27118491584")
		self.assertEqual(ss.normalise_phone("+27 79 253 0729"), "+27792530729")
		self.assertIsNone(ss.normalise_phone(None))
		self.assertIsNone(ss.normalise_phone("   "))
		# not a ten-digit local number: keep the digits, do not invent a country
		self.assertEqual(ss.normalise_phone("12345"), "12345")

	def test_country_codes_match_case_insensitively_and_na_is_namibia(self):
		self.assertEqual(ss.map_country("ZA", COUNTRIES), "South Africa")
		self.assertEqual(ss.map_country("na", COUNTRIES), "Namibia")
		self.assertIsNone(ss.map_country("XX", COUNTRIES))
		self.assertIsNone(ss.map_country(None, COUNTRIES))

	def test_money_goes_through_str_not_binary_float(self):
		self.assertEqual(ss.to_decimal(20359.6), Decimal("20359.6"))
		self.assertEqual(ss.to_decimal(0), Decimal("0"))
		self.assertEqual(ss.to_decimal(None), Decimal("0"))
		self.assertEqual(ss.to_decimal(Decimal("1.10")), Decimal("1.10"))

	def test_every_observed_quote_status_maps(self):
		cases = {
			("Open", None): ss.OPEN_STATUS,
			("Open", "Open"): ss.OPEN_STATUS,
			("On Hold", None): ss.OPEN_STATUS,
			("Pending Approval", None): ss.OPEN_STATUS,
			("Completed", None): "Won",
			("Open", "Lost"): "Lost",
			("Completed", "Lost"): "Lost",
			("Canceled", None): "Lost",
			("Rejected", None): "Lost",
		}
		for (status, outcome), expected in cases.items():
			self.assertEqual(ss.map_deal_status(status, outcome), expected, (status, outcome))
		self.assertIsNone(ss.map_deal_status("Shipping", None))  # unknown: caller rejects

	def test_window_boundary_is_inclusive_on_the_cutoff_day(self):
		as_of = date(2026, 9, 2)
		self.assertTrue(ss.within_window(date(2026, 6, 4), as_of, 90))  # exactly 90 days
		self.assertFalse(ss.within_window(date(2026, 6, 3), as_of, 90))  # 91 days
		self.assertTrue(ss.within_window(as_of, as_of, 0))


def write_workbook(path: Path, header: list[str], rows: list[list]) -> Path:
	"""The exports have a `Data` sheet with a header row and a `Parameters` sheet."""
	wb = Workbook()
	ws = wb.active
	ws.title = "Data"
	ws.append(header)
	for row in rows:
		ws.append(row)
	wb.create_sheet("Parameters").append(["Title:", "test"])
	wb.save(path)
	return path


class ReaderTest(UnitTestCase):
	def setUp(self):
		self.dir = Path(tempfile.mkdtemp())

	def test_rows_are_keyed_by_header_and_dates_stay_datetimes(self):
		path = write_workbook(
			self.dir / "t.xlsx",
			["Customer ID", "Created On", "Credit Limit"],
			[
				["C-1", datetime(2025, 10, 20, 9, 53), 0],
				[None, None, None],
				["C-2", datetime(2026, 1, 2), 1.5],
			],
		)
		rows = ss.read_sheet(path)
		self.assertEqual([r["Customer ID"] for r in rows], ["C-1", "C-2"])  # blank row dropped
		self.assertEqual(rows[0]["Created On"], datetime(2025, 10, 20, 9, 53))
		self.assertIsInstance(rows[1]["Credit Limit"], float)

	def test_csv_is_refused(self):
		with self.assertRaises(ValueError):
			ss.read_sheet(self.dir / "t.csv")


class RejectsTest(UnitTestCase):
	def test_rejects_are_kept_in_order_with_their_reason(self):
		rejects = ss.Rejects()
		rejects.add("sales_orders", "QT1", "unmapped salesperson 022")
		rejects.add("customers", "C-9", "no organization name")
		self.assertEqual(len(rejects), 2)
		self.assertEqual(
			rejects.rows[0], {"file": "sales_orders", "key": "QT1", "reason": "unmapped salesperson 022"}
		)


CUSTOMER_HEADER = [
	"Customer ID",
	"Customer Name",
	"Customer Class",
	"Address Line 1",
	"State",
	"City",
	"Postal Code",
	"Country",
	"Currency ID",
	"Customer Status",
	"Email",
	"Salesperson ID",
	"Sales Person",
	"Phone 1",
	"Default",
	"Created On",
	"Address Line 2",
]


def customer(**over):
	row = {
		"Customer ID": "C-2HK001",
		"Customer Name": "2HK Trading & Projects (Pty) Ltd - COD",
		"Customer Class": "COD",
		"Address Line 1": "5 Springbok Avenue",
		"State": "EC",
		"City": "Olifantsfontein - EC",
		"Postal Code": "1666",
		"Country": "ZA",
		"Currency ID": "ZAR",
		"Customer Status": "Active",
		"Email": "no@email.co.za",
		"Salesperson ID": "003",
		"Sales Person": "Simon Mofokeng",
		"Phone 1": "0792530729",
		"Default": "True",
		"Created On": datetime(2025, 10, 20, 9, 53, 43),
		"Address Line 2": "Clayville East",
	}
	row.update(over)
	return [row[h] for h in CUSTOMER_HEADER]


class DedupeTest(UnitTestCase):
	def test_duplicate_ids_keep_the_default_row(self):
		a = dict(
			zip(
				CUSTOMER_HEADER,
				customer(**{"Customer ID": "C-MET006", "Default": None, "Salesperson ID": None}),
				strict=True,
			)
		)
		b = dict(
			zip(
				CUSTOMER_HEADER,
				customer(**{"Customer ID": "C-MET006", "Default": "True", "Salesperson ID": "030"}),
				strict=True,
			)
		)
		out = ss.dedupe_customers([a, b])
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["Salesperson ID"], "030")

	def test_identical_duplicates_collapse_to_one(self):
		a = dict(zip(CUSTOMER_HEADER, customer(), strict=True))
		self.assertEqual(len(ss.dedupe_customers([a, dict(a)])), 1)


class SpreadsheetImportTestCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()  # acumatica_id / acumatica_sales_quote: absent on a fresh site

	def setUp(self):
		super().setUp()
		self.dir = Path(tempfile.mkdtemp())

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()


class ImportCustomersTest(SpreadsheetImportTestCase):
	def test_creates_organization_and_address_with_filtered_contact_details(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer()])
		rejects = ss.Rejects()
		counts = ss.import_customers(path, rejects)
		self.assertEqual(len(rejects), 0)
		self.assertEqual(counts["organizations"], 1)
		org = frappe.get_doc("CRM Organization", "2HK Trading & Projects (Pty) Ltd")  # COD stripped
		self.assertEqual(org.acumatica_id, "C-2HK001")
		self.assertEqual(org.currency, "ZAR")
		address = frappe.get_doc("Address", org.address)
		self.assertEqual(address.country, "South Africa")
		self.assertEqual(address.address_line2, "Clayville East")
		self.assertEqual(address.phone, "+27792530729")
		self.assertFalse(address.email_id)  # placeholder dropped
		self.assertEqual(address.links[0].link_name, org.name)

	def test_inactive_customers_are_skipped_and_on_hold_kept(self):
		path = write_workbook(
			self.dir / "customers.xlsx",
			CUSTOMER_HEADER,
			[
				customer(**{"Customer ID": "C-A", "Customer Name": "A Ltd", "Customer Status": "Inactive"}),
				customer(**{"Customer ID": "C-B", "Customer Name": "B Ltd", "Customer Status": "On Hold"}),
			],
		)
		counts = ss.import_customers(path, ss.Rejects())
		self.assertEqual(counts["skipped_inactive"], 1)
		self.assertFalse(frappe.db.exists("CRM Organization", "A Ltd"))
		self.assertTrue(frappe.db.exists("CRM Organization", "B Ltd"))

	def test_rerun_updates_in_place(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer()])
		ss.import_customers(path, ss.Rejects())
		ss.import_customers(path, ss.Rejects())
		self.assertEqual(frappe.db.count("CRM Organization", {"acumatica_id": "C-2HK001"}), 1)
		self.assertEqual(
			frappe.db.count(
				"Dynamic Link",
				{
					"link_doctype": "CRM Organization",
					"link_name": "2HK Trading & Projects (Pty) Ltd",
					"parenttype": "Address",
				},
			),
			1,
		)

	def test_missing_street_or_city_skips_the_address_not_the_organization(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer(**{"City": None})])
		counts = ss.import_customers(path, ss.Rejects())
		self.assertEqual(counts["organizations"], 1)
		self.assertEqual(counts["addresses_skipped"], 1)
		self.assertFalse(
			frappe.db.get_value("CRM Organization", "2HK Trading & Projects (Pty) Ltd", "address")
		)

	def test_a_bad_address_rejects_the_address_and_keeps_the_organization(self):
		path = write_workbook(self.dir / "customers.xlsx", CUSTOMER_HEADER, [customer(**{"Country": "XX"})])
		rejects = ss.Rejects()
		counts = ss.import_customers(path, rejects)
		self.assertEqual(counts["organizations"], 1)
		self.assertEqual(counts["addresses"], 0)
		org = frappe.get_doc("CRM Organization", "2HK Trading & Projects (Pty) Ltd")
		self.assertFalse(org.address)
		self.assertTrue(rejects.rows[0]["reason"].startswith("address: unknown country code"))

	def test_a_malformed_cell_rejects_one_row_and_the_run_continues(self):
		path = write_workbook(
			self.dir / "customers.xlsx",
			CUSTOMER_HEADER,
			[
				customer(**{"Customer ID": "C-BAD", "City": 123}),
				customer(**{"Customer ID": "C-GOOD", "Customer Name": "Good Ltd"}),
			],
		)
		rejects = ss.Rejects()
		ss.import_customers(path, rejects)
		self.assertEqual(len(rejects), 1)
		self.assertEqual(rejects.rows[0]["key"], "C-BAD")
		self.assertTrue(frappe.db.exists("CRM Organization", "Good Ltd"))


ORDER_HEADER = [
	"Order Type",
	"Order Nbr.",
	"Status",
	"Date",
	"Sched. Shipment",
	"Quote Outcome",
	"Created By",
	"Default Salesperson",
	"Customer",
	"Customer Name",
	"Ordered Qty.",
	"Order Total",
	"Currency",
	"Created On",
	"Est. Margin (%)",
]
AS_OF = date(2026, 9, 2)
OWNERS = {"018": "annmari@crmtest.test", "003": "simon@crmtest.test"}
RATES = {"USD": Decimal("18.2")}


def order(**over):
	row = {
		"Order Type": "QT",
		"Order Nbr.": "QT103012",
		"Status": "Open",
		"Date": datetime(2026, 9, 2),
		"Sched. Shipment": datetime(2026, 9, 2),
		"Quote Outcome": None,
		"Created By": "ReneO@mbpeng.co.za",
		"Default Salesperson": "018",
		"Customer": "C-PRO004",
		"Customer Name": "Proserve (Pty) Ltd",
		"Ordered Qty.": 30,
		"Order Total": 20359.6,
		"Currency": "ZAR",
		"Created On": datetime(2026, 9, 2, 13, 53),
		"Est. Margin (%)": 33.82,
	}
	row.update(over)
	return row


def shape(**over):
	return ss.shape_sales_order(
		order(**over),
		as_of=AS_OF,
		window_days=90,
		quote_validity_days=30,
		owners=OWNERS,
		default_owner=None,
		rates=RATES,
		base_currency="ZAR",
	)


class ShapeSalesOrderTest(UnitTestCase):
	def test_non_quote_rows_are_skipped_not_rejected(self):
		for order_type in ("SO", "TR", "CM"):
			self.assertIn("skip", shape(**{"Order Type": order_type}))

	def test_an_open_quote_becomes_an_open_deal_with_a_validity_close_date(self):
		deal = shape()
		self.assertEqual(deal["status"], ss.OPEN_STATUS)
		self.assertEqual(deal["value"], Decimal("20359.6"))
		self.assertEqual(deal["owner"], "annmari@crmtest.test")
		self.assertEqual(deal["expected_closure_date"], date(2026, 10, 2))
		self.assertIsNone(deal["closed_date"])
		self.assertEqual(deal["exchange_rate"], Decimal("1"))

	def test_a_completed_quote_is_won_on_its_own_date(self):
		deal = shape(**{"Status": "Completed", "Date": datetime(2026, 5, 1)})
		self.assertEqual(deal["status"], "Won")
		self.assertEqual(deal["closed_date"], date(2026, 5, 1))
		self.assertEqual(deal["expected_closure_date"], date(2026, 5, 1))

	def test_won_and_lost_ignore_the_window_but_open_does_not(self):
		old = {"Date": datetime(2026, 1, 15)}
		self.assertEqual(shape(**{"Status": "Completed", **old})["status"], "Won")
		self.assertEqual(shape(**{"Quote Outcome": "Lost", **old})["status"], "Lost")
		self.assertEqual(shape(**old), {"skip": "outside window"})

	def test_usd_rows_carry_their_rate_and_unknown_currencies_reject(self):
		self.assertEqual(shape(**{"Currency": "USD"})["exchange_rate"], Decimal("18.2"))
		self.assertIn("reject", shape(**{"Currency": "EUR"}))

	def test_unmapped_or_missing_salesperson_rejects_unless_a_default_is_given(self):
		self.assertEqual(shape(**{"Default Salesperson": "022"})["reject"], "unmapped salesperson 022")
		self.assertEqual(shape(**{"Default Salesperson": None})["reject"], "no salesperson")
		with_default = ss.shape_sales_order(
			order(**{"Default Salesperson": None}),
			as_of=AS_OF,
			window_days=90,
			quote_validity_days=30,
			owners=OWNERS,
			default_owner="manager@crmtest.test",
			rates=RATES,
			base_currency="ZAR",
		)
		self.assertEqual(with_default["owner"], "manager@crmtest.test")

	def test_an_unknown_status_rejects_with_the_values_seen(self):
		self.assertEqual(shape(**{"Status": "Shipping"})["reject"], "unknown quote status Shipping / None")

	def test_a_date_only_cell_is_accepted(self):
		deal = shape(**{"Date": date(2026, 9, 1)})
		self.assertEqual(deal["quote_date"], date(2026, 9, 1))


class ImportSalesOrdersTest(SpreadsheetImportTestCase):
	def setUp(self):
		super().setUp()
		# base_currency comes from FCRM Settings.currency (or "USD" undefaults); a fresh
		# test_site never sets it, and the fixtures below are ZAR-denominated. Task 7's
		# brief hits the same gap and sets this explicitly for the same reason.
		frappe.db.set_single_value("FCRM Settings", "currency", "ZAR")
		for email, first in (("annmari@crmtest.test", "Ann-Mari"), ("simon@crmtest.test", "Simon")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0}
				)
				user.insert(ignore_permissions=True)
				user.add_roles("Sales User")
		frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Proserve (Pty) Ltd",
				"acumatica_id": "C-PRO004",
			}
		).insert()

	def rows(self, *rows):
		return write_workbook(
			self.dir / "orders.xlsx", ORDER_HEADER, [[r[h] for h in ORDER_HEADER] for r in rows]
		)

	def test_open_won_and_lost_land_with_real_dates_and_reasons(self):
		path = self.rows(
			order(),
			order(**{"Order Nbr.": "QT100001", "Status": "Completed", "Date": datetime(2026, 5, 1)}),
			order(**{"Order Nbr.": "QT100002", "Quote Outcome": "Lost", "Date": datetime(2026, 4, 1)}),
		)
		rejects = ss.Rejects()
		counts = ss.import_sales_orders(path, rejects, owners=OWNERS, rates=RATES)
		self.assertEqual(len(rejects), 0, rejects.rows)
		self.assertEqual((counts["open"], counts["won"], counts["lost"]), (1, 1, 1))
		won = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT100001"})
		self.assertEqual(won.status, "Won")
		self.assertEqual(
			str(won.closed_date), "2026-05-01"
		)  # not today: validate() stamps today, we write it back
		self.assertEqual(won.deal_owner, "annmari@crmtest.test")
		self.assertEqual(won.organization, "Proserve (Pty) Ltd")
		lost = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT100002"})
		self.assertEqual(lost.lost_reason, ss.LOST_REASON)
		open_deal = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT103012"})
		self.assertEqual(str(open_deal.expected_closure_date), "2026-10-02")
		self.assertEqual(open_deal.expected_deal_value, open_deal.deal_value)

	def test_a_usd_deal_keeps_the_supplied_rate(self):
		path = self.rows(order(**{"Currency": "USD", "Order Total": 1000}))
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		deal = frappe.get_doc("CRM Deal", {"acumatica_sales_quote": "QT103012"})
		self.assertEqual(deal.currency, "USD")
		self.assertAlmostEqual(deal.exchange_rate, 18.2)

	def test_rerun_updates_and_never_duplicates(self):
		path = self.rows(order())
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		path = self.rows(order(**{"Order Total": 999}))
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		self.assertEqual(frappe.db.count("CRM Deal", {"acumatica_sales_quote": "QT103012"}), 1)
		self.assertEqual(
			frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": "QT103012"}, "deal_value"), 999
		)

	def test_a_deal_in_the_manifest_but_gone_from_the_site_is_not_resurrected(self):
		path = self.rows(order())
		manifest = {"QT103012"}  # created by an earlier run, then deleted by a rep
		counts = ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES, manifest=manifest)
		self.assertEqual(counts["skipped_deleted"], 1)
		self.assertFalse(frappe.db.exists("CRM Deal", {"acumatica_sales_quote": "QT103012"}))

	def test_a_missing_organization_rejects_the_row(self):
		path = self.rows(order(**{"Customer": "C-NOPE"}))
		rejects = ss.Rejects()
		ss.import_sales_orders(path, rejects, owners=OWNERS, rates=RATES)
		self.assertEqual(rejects.rows[0]["reason"], "customer C-NOPE has no organization on the site")

	def test_an_empty_sheet_returns_the_full_shape(self):
		path = self.rows()
		counts = ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		for key in (
			"deals",
			"won",
			"lost",
			"open",
			"outside_window",
			"skipped_deleted",
			"left_alone",
			"excluded",
			"as_of",
		):
			self.assertIn(key, counts)
		for key in ("deals", "won", "lost", "open", "outside_window", "skipped_deleted", "left_alone"):
			self.assertEqual(counts[key], 0)
		self.assertEqual(counts["excluded"], {})
		self.assertIsNone(counts["as_of"])

	def test_a_rerun_leaves_a_rep_edited_deal_alone(self):
		path = self.rows(order())
		ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		deal_name = frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": "QT103012"}, "name")
		frappe.db.set_value(
			"CRM Deal", deal_name, "modified_by", "annmari@crmtest.test", update_modified=False
		)

		path = self.rows(order(**{"Order Total": 999}))
		counts = ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)

		self.assertEqual(frappe.db.get_value("CRM Deal", deal_name, "deal_value"), 20359.6)
		self.assertEqual(counts["left_alone"], 1)
		self.assertEqual(counts["deals"], 0)

	def test_every_row_reaches_the_commit_cadence(self):
		path = self.rows(
			order(),
			order(**{"Order Type": "SO", "Order Nbr.": "SO-1"}),
			order(**{"Order Type": "TR", "Order Nbr.": "SO-2", "Customer": "JHB"}),
		)
		with patch("crm.integrations.acumatica.spreadsheet._commit_every") as commit:
			ss.import_sales_orders(path, ss.Rejects(), owners=OWNERS, rates=RATES)
		self.assertEqual(commit.call_count, 3)


INVOICE_HEADER = [
	"Type",
	"Reference Nbr.",
	"Status",
	"Date",
	"Post Period",
	"Customer",
	"Customer Name",
	"Description",
	"Customer Order Nbr.",
	"Amount",
	"Currency",
	"Created On",
]


def invoice(**over):
	row = {
		"Type": "Invoice",
		"Reference Nbr.": "IN-JHB1001418",
		"Status": "Open",
		"Date": datetime(2026, 9, 2),
		"Post Period": "04-2026",
		"Customer": "C-SURE01",
		"Customer Name": "Sure Seal SA (Pty) Ltd",
		"Description": "Ball vlv",
		"Customer Order Nbr.": "11520",
		"Amount": 430.39,
		"Currency": "ZAR",
		"Created On": datetime(2026, 9, 2, 10, 10),
	}
	row.update(over)
	return row


class RevenueTest(UnitTestCase):
	def test_credit_memos_subtract_cancelled_rows_are_ignored_and_usd_converts(self):
		rows = [
			invoice(),
			invoice(**{"Type": "Credit Memo", "Amount": 30.39}),
			invoice(**{"Status": "Canceled", "Amount": 1_000_000}),
			invoice(**{"Currency": "USD", "Amount": 10}),
		]
		totals, rejects = ss.revenue_by_customer(rows, RATES, "ZAR")
		self.assertEqual(totals["C-SURE01"], Decimal("400") + Decimal("182"))
		self.assertEqual(rejects, [])

	def test_an_unknown_currency_rejects_that_row_only(self):
		totals, rejects = ss.revenue_by_customer([invoice(), invoice(**{"Currency": "EUR"})], RATES, "ZAR")
		self.assertEqual(totals["C-SURE01"], Decimal("430.39"))
		self.assertEqual(rejects, [("IN-JHB1001418", "no exchange rate supplied for EUR")])


class ImportInvoicesTest(SpreadsheetImportTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.set_single_value("FCRM Settings", "currency", "ZAR")

	def test_writes_annual_revenue_on_the_organization(self):
		frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Sure Seal SA (Pty) Ltd",
				"acumatica_id": "C-SURE01",
			}
		).insert()
		path = write_workbook(self.dir / "inv.xlsx", INVOICE_HEADER, [[invoice()[h] for h in INVOICE_HEADER]])
		rejects = ss.Rejects()
		counts = ss.import_invoices(path, rejects, rates=RATES)
		self.assertEqual(len(rejects), 0)
		self.assertEqual(counts["organizations"], 1)
		self.assertAlmostEqual(
			frappe.db.get_value("CRM Organization", "Sure Seal SA (Pty) Ltd", "annual_revenue"), 430.39
		)

	def test_a_customer_with_no_organization_rejects(self):
		path = write_workbook(self.dir / "inv.xlsx", INVOICE_HEADER, [[invoice()[h] for h in INVOICE_HEADER]])
		rejects = ss.Rejects()
		ss.import_invoices(path, rejects, rates=RATES)
		self.assertEqual(rejects.rows[0]["key"], "C-SURE01")


class CommitCadenceTest(UnitTestCase):
	def test_a_dry_run_never_commits(self):
		with patch.object(frappe.db, "commit") as commit:
			frappe.flags.in_test = False
			try:
				frappe.flags.spreadsheet_import_dry_run = True
				ss._commit_every(50)
				self.assertEqual(commit.call_count, 0)
				frappe.flags.spreadsheet_import_dry_run = False
				ss._commit_every(50)
				self.assertEqual(commit.call_count, 1)
			finally:
				frappe.flags.in_test = True
				frappe.flags.spreadsheet_import_dry_run = False


class ImportWorkbooksTest(SpreadsheetImportTestCase):
	def setUp(self):
		super().setUp()
		# OWNERS (below) has both salespeople, and import_sales_orders pre-validates
		# every value in the owners map as an existing User -- not just ones a row
		# references -- so both must exist even though this fixture's one order row
		# only names "018". Mirrors ImportSalesOrdersTest.setUp above.
		for email, first in (("annmari@crmtest.test", "Ann-Mari"), ("simon@crmtest.test", "Simon")):
			if not frappe.db.exists("User", email):
				user = frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": first, "send_welcome_email": 0}
				)
				user.insert(ignore_permissions=True)
				user.add_roles("Sales User")
		self.customers = write_workbook(
			self.dir / "Customers.xlsx",
			CUSTOMER_HEADER,
			[customer(**{"Customer ID": "C-PRO004", "Customer Name": "Proserve (Pty) Ltd"})],
		)
		self.orders = write_workbook(
			self.dir / "Sales Orders.xlsx", ORDER_HEADER, [[order()[h] for h in ORDER_HEADER]]
		)
		self.invoices = write_workbook(
			self.dir / "Invoices.xlsx",
			INVOICE_HEADER,
			[[invoice(**{"Customer": "C-PRO004"})[h] for h in INVOICE_HEADER]],
		)
		self.owners = self.dir / "owners.json"
		self.owners.write_text(json.dumps(OWNERS))
		frappe.db.set_single_value("FCRM Settings", "currency", "ZAR")
		# a real run refuses unless emails are muted (test_a_real_run_refuses_...
		# below covers that refusal directly); every other test here runs a real
		# import and must not depend on the site's own mute_emails config.
		frappe.flags.mute_emails = True

	def tearDown(self):
		frappe.flags.mute_emails = False
		super().tearDown()

	def test_refuses_to_run_unless_the_base_currency_is_zar(self):
		frappe.db.set_single_value("FCRM Settings", "currency", "USD")
		with self.assertRaisesRegex(ValueError, "base currency"):
			ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})

	def test_a_real_run_refuses_unless_emails_are_muted(self):
		with patch("frappe.are_emails_muted", return_value=False):
			with self.assertRaisesRegex(ValueError, "not muted"):
				ss.import_workbooks(
					self.customers,
					self.orders,
					self.invoices,
					self.owners,
					rates={"USD": 18.2},
					dry_run=False,
				)
			# the dry run does not send any email itself, so it is unaffected
			ss.import_workbooks(
				self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}, dry_run=True
			)

	def test_dry_run_writes_nothing_and_still_reports(self):
		summary = ss.import_workbooks(
			self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}, dry_run=True
		)
		self.assertEqual(summary["customers"]["organizations"], 1)
		self.assertEqual(summary["sales_orders"]["deals"], 1)
		self.assertTrue(summary["dry_run"])
		self.assertFalse(frappe.db.exists("CRM Organization", "Proserve (Pty) Ltd"))
		self.assertFalse((self.dir / "import-manifest.json").exists())

	def test_a_real_run_writes_the_manifest_and_reject_report(self):
		summary = ss.import_workbooks(
			self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}
		)
		self.assertTrue(frappe.db.exists("CRM Deal", {"acumatica_sales_quote": "QT103012"}))
		self.assertEqual(json.loads((self.dir / "import-manifest.json").read_text())["deals"], ["QT103012"])
		self.assertEqual(json.loads((self.dir / "import-rejects.json").read_text()), [])
		self.assertEqual(summary["warnings"], [])

	def test_the_manifest_is_read_back_on_the_next_run(self):
		ss.import_workbooks(self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2})
		frappe.delete_doc(
			"CRM Deal",
			frappe.db.get_value("CRM Deal", {"acumatica_sales_quote": "QT103012"}, "name"),
			force=True,
		)
		summary = ss.import_workbooks(
			self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}
		)
		self.assertEqual(summary["sales_orders"]["skipped_deleted"], 1)

	def test_the_dry_run_flag_is_cleared_afterwards(self):
		ss.import_workbooks(
			self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}, dry_run=True
		)
		self.assertFalse(frappe.flags.spreadsheet_import_dry_run)

	def test_an_exception_mid_run_commits_nothing_and_writes_no_files(self):
		with patch(
			"crm.integrations.acumatica.spreadsheet.import_sales_orders", side_effect=RuntimeError("boom")
		):
			with self.assertRaises(RuntimeError):
				ss.import_workbooks(
					self.customers, self.orders, self.invoices, self.owners, rates={"USD": 18.2}
				)
		self.assertFalse(frappe.db.exists("CRM Organization", "Proserve (Pty) Ltd"))
		self.assertFalse((self.dir / "import-manifest.json").exists())
		self.assertFalse(frappe.flags.spreadsheet_import_dry_run)
