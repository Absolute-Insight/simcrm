# Copyright (c) 2025, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.exchange_rate import (
	_fetch_from_exchangerate_api,
	_fetch_from_exchangerate_host,
	_fetch_from_fawaz_api,
	_fetch_from_frankfurter,
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
