import re

import frappe
import requests
from frappe import _
from frappe.rate_limiter import rate_limit

from crm.fcrm.doctype.fcrm_settings.fcrm_settings import FCRMSettings
from crm.utils import user_rate_limited

# Limited twice, like every other outbound-fetch endpoint in this app (the agent
# tier and domain enrichment). ``@rate_limit`` is frappe's limiter and keys on the
# request IP, so it is one bucket for an office behind NAT and a fresh bucket for
# every address one user can borrow; ``user_rate_limited`` keys on the session
# user and is the layer that actually bounds what one account can do. The cache
# key varies per currency pair and date, so a loop over distinct pairs misses the
# cache every time and holds a worker for up to two provider timeouts per call;
# only uncached fetches count against the user bucket. 30/min is far above any
# real use: the UI fetches on a currency change.
EXCHANGE_RATE_LIMIT = 30
EXCHANGE_RATE_SCOPE = "exchange_rate"

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# The official ZAR fix, straight from the central bank. HomePageRates carries
# the current "Rand per X" rate for exactly these counterparts, keyed by stable
# timeseries codes (verified live 2026-09-01); anything else this provider does
# not answer, and the free-provider chain takes over.
SARB_HOME_PAGE_RATES_URL = "https://custom.resbank.co.za/SarbWebApi/WebIndicators/HomePageRates"
SARB_ZAR_PER = {"USD": "EXCX135D", "GBP": "EXCZ001D", "EUR": "EXCZ002D", "JPY": "EXCZ120D"}


def _validate_inputs(from_currency: str, to_currency: str, date: str):
	"""Every value here is interpolated into a provider URL; only accept known
	currency codes and an ISO date so nothing else can reach the path or query."""
	for currency in (from_currency, to_currency):
		if not currency or not frappe.db.exists("Currency", currency):
			frappe.throw(_("Invalid currency: {0}").format(frappe.bold(currency)))
	if date != "latest" and not DATE_PATTERN.match(date):
		frappe.throw(_("Invalid date: {0}. Use YYYY-MM-DD.").format(frappe.bold(date)))


def _get_access_key(settings: FCRMSettings):
	access_key = settings.get_password("access_key", raise_exception=False)
	if not access_key:
		frappe.throw(
			_("Access Key is required for Service Provider: {0}").format(
				frappe.bold(settings.service_provider)
			)
		)
	return access_key


@frappe.whitelist()
@rate_limit(limit=EXCHANGE_RATE_LIMIT, seconds=60)
def get_exchange_rate(from_currency: str, to_currency: str, date: str | None = None):
	if not date:
		date = "latest"
	_validate_inputs(from_currency, to_currency, date)

	# "latest" is keyed by today's date so tomorrow's call automatically misses the cache
	cache_date = frappe.utils.today() if date == "latest" else date
	cache_key = f"exchange_rate_{from_currency}_{to_currency}_{cache_date}"

	cached_rate = frappe.cache().get_value(cache_key)
	if cached_rate is not None:
		return cached_rate

	if user_rate_limited(EXCHANGE_RATE_SCOPE, EXCHANGE_RATE_LIMIT):
		# The same shape as every other refusal here: callers on the deal save path
		# already catch it and keep the previous rate.
		frappe.throw(_("Too many exchange rate requests. Try again shortly."), frappe.ValidationError)

	rate, api_used = _fetch_exchange_rate(from_currency, to_currency, date)

	if rate is not None:
		frappe.cache().set_value(cache_key, rate)
		return rate

	_raise_exchange_rate_error(from_currency, to_currency, date, api_used)


def _fetch_exchange_rate(from_currency: str, to_currency: str, date: str):
	settings = frappe.get_single("FCRM Settings")
	provider = settings.service_provider

	# Paid providers — no fallback, fail explicitly
	if provider == "exchangerate.host":
		return _fetch_from_exchangerate_host(settings, from_currency, to_currency, date), provider

	if provider == "exchangerate-api":
		return _fetch_from_exchangerate_api(settings, from_currency, to_currency), provider

	# Free providers — try both as fallbacks, regardless of which is "primary"
	if provider == "frankfurter.app":
		rate = _fetch_from_frankfurter(from_currency, to_currency, date)
		if rate is not None:
			return rate, provider
		# Frankfurter is down — silently fall back to fawaz
		rate = _fetch_from_fawaz_api(from_currency, to_currency, date)
		return rate, "fawazahmed-exchange-api"

	if provider == "fawazahmed-exchange-api":
		rate = _fetch_from_fawaz_api(from_currency, to_currency, date)
		if rate is not None:
			return rate, provider
		# fawaz is down — silently fall back to frankfurter
		rate = _fetch_from_frankfurter(from_currency, to_currency, date)
		return rate, "frankfurter"

	if provider == "sarb":
		# the central bank's own current ZAR fix; everything it does not answer
		# (history, non-ZAR pairs, downtime) falls through the same free chain
		# the other free providers use
		rate = _fetch_from_sarb(from_currency, to_currency, date)
		if rate is not None:
			return rate, provider
		rate = _fetch_from_frankfurter(from_currency, to_currency, date)
		if rate is not None:
			return rate, "frankfurter"
		return _fetch_from_fawaz_api(from_currency, to_currency, date), "fawazahmed-exchange-api"

	# Unknown provider — try both free ones
	rate = _fetch_from_frankfurter(from_currency, to_currency, date)
	if rate is not None:
		return rate, "frankfurter"
	return _fetch_from_fawaz_api(from_currency, to_currency, date), "fawazahmed-exchange-api"


def _fetch_from_sarb(from_currency: str, to_currency: str, date: str):
	"""ZAR pairs only, current rate only — the SARB publishes today's official
	fix, not history, so a dated request is the fallback chain's to answer."""
	if date != "latest":
		return None
	if from_currency == "ZAR" and to_currency in SARB_ZAR_PER:
		code, invert = SARB_ZAR_PER[to_currency], True
	elif to_currency == "ZAR" and from_currency in SARB_ZAR_PER:
		code, invert = SARB_ZAR_PER[from_currency], False
	else:
		return None
	try:
		res = requests.get(SARB_HOME_PAGE_RATES_URL, timeout=5)
		if not res.ok:
			return None
		value = next((row.get("Value") for row in res.json() if row.get("TimeseriesCode") == code), None)
		if not value:  # a missing row and a zero rate are both unusable
			return None
		return 1 / value if invert else value
	except Exception:
		return None


def _fetch_from_frankfurter(from_currency: str, to_currency: str, date: str):
	try:
		res = requests.get(
			f"https://api.frankfurter.app/{date}?from={from_currency}&to={to_currency}", timeout=5
		)
		if res.ok:
			return res.json().get("rates", {}).get(to_currency)
	except Exception:
		pass
	return None


def _fetch_from_fawaz_api(from_currency: str, to_currency: str, date: str):
	from_lower = from_currency.lower()
	to_lower = to_currency.lower()
	date_str = "latest" if date == "latest" else date
	urls = [
		f"https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@{date_str}/v1/currencies/{from_lower}.json",
		f"https://{date_str}.currency-api.pages.dev/v1/currencies/{from_lower}.json",
	]
	for url in urls:
		try:
			res = requests.get(url, timeout=5)
			if res.ok:
				return res.json()[from_lower][to_lower]
		except Exception:
			continue
	return None


def _fetch_from_exchangerate_host(settings: FCRMSettings, from_currency: str, to_currency: str, date: str):
	access_key = _get_access_key(settings)
	params = {"access_key": access_key, "from": from_currency, "to": to_currency, "amount": 1}
	if date != "latest":
		params["date"] = date
	res = requests.get("https://api.exchangerate.host/convert", params=params, timeout=5)
	if res.ok:
		return res.json()["result"]
	return None


def _fetch_from_exchangerate_api(settings: FCRMSettings, from_currency: str, to_currency: str):
	access_key = _get_access_key(settings)
	res = requests.get(
		f"https://v6.exchangerate-api.com/v6/{access_key}/pair/{from_currency}/{to_currency}",
		timeout=5,
	)
	if res.ok:
		data = res.json()
		if data["result"] == "success":
			return data["conversion_rate"]
	return None


def _raise_exchange_rate_error(from_currency: str, to_currency: str, date: str, api_used: str):
	frappe.log_error(
		title="Exchange Rate Fetch Error",
		message=f"Failed to fetch exchange rate from {from_currency} to {to_currency} using {api_used} API.",
	)

	if api_used == "frankfurter":
		user = frappe.session.user
		is_manager = (
			"System Manager" in frappe.get_roles(user)
			or "Sales Manager" in frappe.get_roles(user)
			or user == "Administrator"
		)
		if not is_manager:
			frappe.throw(
				_(
					"Ask your manager to set up the Exchange Rate Provider, as default provider does not support currency conversion for {0} to {1}."
				).format(from_currency, to_currency)
			)
		frappe.throw(
			_(
				"Setup the Exchange Rate Provider other than 'Frankfurter' in settings, as default provider does not support currency conversion for {0} to {1}."
			).format(from_currency, to_currency)
		)

	frappe.throw(
		_(
			"Failed to fetch exchange rate from {0} to {1} on {2}. Please check your internet connection or try again later."
		).format(from_currency, to_currency, date)
	)
