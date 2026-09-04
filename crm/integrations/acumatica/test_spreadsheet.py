"""Spreadsheet import tests.

The transforms are pure -- values in, values out -- so the corruption rules live
here without a site. The importers run against the test site further down,
against small workbooks the tests build themselves: the MBP files are the
client's data and are never committed.
"""

from __future__ import annotations

import tempfile
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

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
