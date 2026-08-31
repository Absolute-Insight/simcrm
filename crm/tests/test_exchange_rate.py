# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from typing import ClassVar
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.exchange_rate import (
	_fetch_exchange_rate,
	_fetch_from_exchangerate_api,
	_fetch_from_exchangerate_host,
	_fetch_from_fawaz_api,
	_fetch_from_frankfurter,
	_fetch_from_sarb,
	get_exchange_rate,
)


def _make_response(ok: bool, json_data: dict) -> MagicMock:
	"""Helper: build a fake requests.Response."""
	mock = MagicMock()
	mock.ok = ok
	mock.json.return_value = json_data
	return mock


def _mock_settings(provider: str, access_key: str = "") -> MagicMock:
	"""Helper: build a fake FCRM Settings single document."""
	settings = MagicMock()
	settings.service_provider = provider
	settings.access_key = access_key
	settings.get_password.return_value = access_key
	return settings


class TestFetchFromFrankfurter(FrappeTestCase):
	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_rate_on_success(self, mock_get):
		mock_get.return_value = _make_response(True, {"rates": {"INR": 83.5}})

		rate = _fetch_from_frankfurter("USD", "INR", "latest")

		self.assertEqual(rate, 83.5)
		mock_get.assert_called_once()

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_when_response_not_ok(self, mock_get):
		mock_get.return_value = _make_response(False, {})

		rate = _fetch_from_frankfurter("USD", "INR", "latest")

		self.assertIsNone(rate)

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_on_missing_currency_key(self, mock_get):
		# response is ok but to_currency key is absent — should not raise KeyError
		mock_get.return_value = _make_response(True, {"rates": {}})

		rate = _fetch_from_frankfurter("USD", "INR", "latest")

		self.assertIsNone(rate)

	@patch(
		"crm.api.exchange_rate.requests.get",
		side_effect=Exception("Connection refused"),
	)
	def test_returns_none_on_network_error(self, mock_get):
		rate = _fetch_from_frankfurter("USD", "INR", "latest")

		self.assertIsNone(rate)


class TestFetchFromFawazApi(FrappeTestCase):
	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_rate_on_success(self, mock_get):
		mock_get.return_value = _make_response(True, {"usd": {"inr": 83.5}})

		rate = _fetch_from_fawaz_api("USD", "INR", "latest")

		self.assertEqual(rate, 83.5)

	@patch("crm.api.exchange_rate.requests.get")
	def test_falls_back_to_second_url_when_first_fails(self, mock_get):
		# First URL raises, second URL succeeds
		mock_get.side_effect = [
			Exception("CDN timeout"),
			_make_response(True, {"usd": {"inr": 83.5}}),
		]

		rate = _fetch_from_fawaz_api("USD", "INR", "latest")

		self.assertEqual(rate, 83.5)
		self.assertEqual(mock_get.call_count, 2)

	@patch(
		"crm.api.exchange_rate.requests.get",
		side_effect=Exception("Network error"),
	)
	def test_returns_none_when_all_urls_fail(self, mock_get):
		rate = _fetch_from_fawaz_api("USD", "INR", "latest")

		self.assertIsNone(rate)


class TestFetchFromExchangeRateHost(FrappeTestCase):
	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_rate_on_success(self, mock_get):
		mock_get.return_value = _make_response(True, {"result": 83.5})
		settings = _mock_settings("exchangerate.host", access_key="test_key")

		rate = _fetch_from_exchangerate_host(settings, "USD", "INR", "latest")

		self.assertEqual(rate, 83.5)

	def test_raises_when_access_key_missing(self):
		settings = _mock_settings("exchangerate.host", access_key="")

		with self.assertRaises(frappe.exceptions.ValidationError):
			_fetch_from_exchangerate_host(settings, "USD", "INR", "latest")

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_when_response_not_ok(self, mock_get):
		mock_get.return_value = _make_response(False, {})
		settings = _mock_settings("exchangerate.host", access_key="test_key")

		rate = _fetch_from_exchangerate_host(settings, "USD", "INR", "latest")

		self.assertIsNone(rate)


class TestFetchFromExchangeRateApi(FrappeTestCase):
	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_rate_on_success(self, mock_get):
		mock_get.return_value = _make_response(True, {"result": "success", "conversion_rate": 83.5})
		settings = _mock_settings("exchangerate-api", access_key="test_key")

		rate = _fetch_from_exchangerate_api(settings, "USD", "INR")

		self.assertEqual(rate, 83.5)

	def test_raises_when_access_key_missing(self):
		settings = _mock_settings("exchangerate-api", access_key="")

		with self.assertRaises(frappe.exceptions.ValidationError):
			_fetch_from_exchangerate_api(settings, "USD", "INR")

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_when_api_result_is_not_success(self, mock_get):
		mock_get.return_value = _make_response(True, {"result": "error", "error-type": "invalid-key"})
		settings = _mock_settings("exchangerate-api", access_key="bad_key")

		rate = _fetch_from_exchangerate_api(settings, "USD", "INR")

		self.assertIsNone(rate)


class TestGetExchangeRate(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value("exchange_rate_USD_INR_latest")
		frappe.cache().delete_value(f"exchange_rate_USD_INR_{frappe.utils.today()}")

	@patch("crm.api.exchange_rate._fetch_exchange_rate")
	def test_returns_rate_on_success(self, mock_fetch):
		mock_fetch.return_value = (83.5, "frankfurter")

		rate = get_exchange_rate("USD", "INR")

		self.assertEqual(rate, 83.5)

	@patch("crm.api.exchange_rate._fetch_exchange_rate")
	def test_caches_result_and_skips_second_fetch(self, mock_fetch):
		mock_fetch.return_value = (83.5, "frankfurter")

		get_exchange_rate("USD", "INR")
		get_exchange_rate("USD", "INR")

		# _fetch_exchange_rate should only be called once; second call hits cache
		mock_fetch.assert_called_once()

	@patch("crm.api.exchange_rate._fetch_exchange_rate")
	def test_raises_when_all_providers_fail(self, mock_fetch):
		mock_fetch.return_value = (None, "frankfurter")

		with self.assertRaises(frappe.exceptions.ValidationError):
			get_exchange_rate("USD", "XYZ")


class TestDealSurvivesAnUnreachableProvider(FrappeTestCase):
	"""A deal must save when the FX providers are down.

	``update_exchange_rate`` runs inside ``validate`` and ``get_exchange_rate``
	throws when no provider answers, so this used to fail every save of a
	non-base-currency deal — on a host with no outbound internet, that is every
	such save, forever. A stale rate is a wrong number in a report; an
	unsaveable deal is a rep who cannot work.
	"""

	def setUp(self):
		super().setUp()
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "FX Test Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.base = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
		self.foreign = "EUR" if self.base != "EUR" else "GBP"

	@patch("crm.api.exchange_rate._fetch_exchange_rate")
	def test_a_foreign_currency_deal_saves_when_no_provider_answers(self, mock_fetch):
		mock_fetch.return_value = (None, "frankfurter")

		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "currency": self.foreign}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)

		self.assertTrue(frappe.db.exists("CRM Deal", deal.name))

	@patch("crm.api.exchange_rate._fetch_exchange_rate")
	def test_a_base_currency_deal_never_calls_a_provider(self, mock_fetch):
		"""The rate is 1 by definition, so reaching for the network at all was
		an outbound call on the save path of the most common case."""
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "currency": self.base}
		).insert(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "CRM Deal", deal.name, force=True)

		mock_fetch.assert_not_called()
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "exchange_rate"), 1)


class TestFetchFromSarb(FrappeTestCase):
	"""The SARB provider answers exactly what the central bank publishes: the
	current official ZAR fix against USD, GBP, EUR and JPY. Everything else is
	None, so the free-provider chain takes over."""

	PAYLOAD: ClassVar = [
		{"Name": "CPI", "TimeseriesCode": "CPI1000F", "Value": 4.3},
		{"Name": "Rand per US Dollar", "TimeseriesCode": "EXCX135D", "Value": 16.0},
		{"Name": "Rand per Euro", "TimeseriesCode": "EXCZ002D", "Value": 18.0},
	]

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_the_published_rate_for_a_direct_pair(self, mock_get):
		mock_get.return_value = _make_response(True, self.PAYLOAD)

		self.assertEqual(_fetch_from_sarb("USD", "ZAR", "latest"), 16.0)

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_the_inverse_for_the_reversed_pair(self, mock_get):
		mock_get.return_value = _make_response(True, self.PAYLOAD)

		self.assertEqual(_fetch_from_sarb("ZAR", "USD", "latest"), 1 / 16.0)

	@patch("crm.api.exchange_rate.requests.get")
	def test_a_non_zar_pair_is_declined_without_a_network_call(self, mock_get):
		self.assertIsNone(_fetch_from_sarb("USD", "EUR", "latest"))
		mock_get.assert_not_called()

	@patch("crm.api.exchange_rate.requests.get")
	def test_a_historical_date_is_declined_without_a_network_call(self, mock_get):
		"""SARB publishes today's fix, not history — a dated request belongs to
		the fallback chain, which has ECB history for ZAR."""
		self.assertIsNone(_fetch_from_sarb("USD", "ZAR", "2026-01-15"))
		mock_get.assert_not_called()

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_when_response_not_ok(self, mock_get):
		mock_get.return_value = _make_response(False, [])

		self.assertIsNone(_fetch_from_sarb("USD", "ZAR", "latest"))

	@patch("crm.api.exchange_rate.requests.get", side_effect=Exception("Connection refused"))
	def test_returns_none_on_network_error(self, mock_get):
		self.assertIsNone(_fetch_from_sarb("USD", "ZAR", "latest"))

	@patch("crm.api.exchange_rate.requests.get")
	def test_returns_none_when_the_timeseries_row_is_missing(self, mock_get):
		mock_get.return_value = _make_response(True, [{"TimeseriesCode": "CPI1000F", "Value": 4.3}])

		self.assertIsNone(_fetch_from_sarb("GBP", "ZAR", "latest"))

	@patch("crm.api.exchange_rate.requests.get")
	def test_a_zero_rate_is_unusable_not_a_division_error(self, mock_get):
		mock_get.return_value = _make_response(True, [{"TimeseriesCode": "EXCX135D", "Value": 0}])

		self.assertIsNone(_fetch_from_sarb("ZAR", "USD", "latest"))


class TestSarbProviderRouting(FrappeTestCase):
	"""provider == 'sarb' behaves like the other free providers: authoritative
	when it can answer, silent fallback through the free chain when it cannot."""

	@patch("crm.api.exchange_rate.frappe.get_single")
	@patch("crm.api.exchange_rate._fetch_from_sarb")
	def test_the_sarb_rate_wins_when_it_answers(self, mock_sarb, mock_single):
		mock_single.return_value = _mock_settings("sarb")
		mock_sarb.return_value = 16.0

		rate, api_used = _fetch_exchange_rate("USD", "ZAR", "latest")

		self.assertEqual((rate, api_used), (16.0, "sarb"))

	@patch("crm.api.exchange_rate.frappe.get_single")
	@patch("crm.api.exchange_rate._fetch_from_frankfurter")
	@patch("crm.api.exchange_rate._fetch_from_sarb")
	def test_falls_back_to_frankfurter_when_sarb_cannot_answer(self, mock_sarb, mock_frank, mock_single):
		mock_single.return_value = _mock_settings("sarb")
		mock_sarb.return_value = None
		mock_frank.return_value = 0.052

		rate, api_used = _fetch_exchange_rate("ZAR", "EUR", "2026-01-15")

		self.assertEqual((rate, api_used), (0.052, "frankfurter"))

	@patch("crm.api.exchange_rate.frappe.get_single")
	@patch("crm.api.exchange_rate._fetch_from_fawaz_api")
	@patch("crm.api.exchange_rate._fetch_from_frankfurter")
	@patch("crm.api.exchange_rate._fetch_from_sarb")
	def test_falls_all_the_way_to_fawaz(self, mock_sarb, mock_frank, mock_fawaz, mock_single):
		mock_single.return_value = _mock_settings("sarb")
		mock_sarb.return_value = None
		mock_frank.return_value = None
		mock_fawaz.return_value = 16.1

		rate, api_used = _fetch_exchange_rate("USD", "ZAR", "latest")

		self.assertEqual((rate, api_used), (16.1, "fawazahmed-exchange-api"))


class TestEnableZarPatch(FrappeTestCase):
	"""The dashboard-currency picker offers only enabled currencies, and frappe
	ships ZAR disabled — which is what 'ZAR is missing' means in practice."""

	def setUp(self):
		super().setUp()
		self.had_row = frappe.db.exists("Currency", "ZAR")
		self.was_enabled = self.had_row and frappe.db.get_value("Currency", "ZAR", "enabled")

	def tearDown(self):
		if self.had_row:
			frappe.db.set_value("Currency", "ZAR", "enabled", self.was_enabled or 0)
		else:
			frappe.delete_doc("Currency", "ZAR", force=True, ignore_missing=True)
		super().tearDown()

	def test_a_disabled_zar_is_enabled(self):
		from crm.patches.v1_0.enable_zar_currency import execute

		if not self.had_row:
			self.skipTest("site has no ZAR row; covered by the creation test")
		frappe.db.set_value("Currency", "ZAR", "enabled", 0)
		execute()
		self.assertEqual(frappe.db.get_value("Currency", "ZAR", "enabled"), 1)

	def test_the_patch_is_idempotent(self):
		from crm.patches.v1_0.enable_zar_currency import execute

		execute()
		execute()
		self.assertEqual(frappe.db.get_value("Currency", "ZAR", "enabled"), 1)

	def test_a_site_without_the_row_gets_a_complete_one(self):
		from crm.patches.v1_0.enable_zar_currency import execute

		frappe.delete_doc("Currency", "ZAR", force=True, ignore_missing=True)
		execute()
		row = frappe.db.get_value("Currency", "ZAR", ["enabled", "symbol", "fraction"], as_dict=True)
		self.assertEqual(row.enabled, 1)
		self.assertEqual(row.symbol, "R")
		self.assertEqual(row.fraction, "Cent")
