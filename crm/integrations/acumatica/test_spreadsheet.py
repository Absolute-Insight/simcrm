"""Spreadsheet import tests.

The transforms are pure -- values in, values out -- so the corruption rules live
here without a site. The importers run against the test site further down,
against small workbooks the tests build themselves: the MBP files are the
client's data and are never committed.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from frappe.tests import UnitTestCase

from crm.integrations.acumatica import spreadsheet as ss

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
