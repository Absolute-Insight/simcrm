# ZAR Currency + SARB Rate Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ZAR a first-class currency (enabled on every site, present in the dashboard-currency and deal-currency pickers) and add the South African Reserve Bank as an exchange-rate provider.

**Architecture:** SARB's public `HomePageRates` endpoint publishes the official current ZAR fix against USD, GBP, EUR and JPY under stable timeseries codes (verified live 2026-09-01: EXCX135D/EXCZ001D/EXCZ002D/EXCZ120D, "Rand per X"). The provider answers exactly that — current-date ZAR pairs, direct or inverse — and returns `None` for everything else (historical dates, non-ZAR pairs, API failures), falling back through the existing free-provider chain (frankfurter → fawaz) the same way frankfurter and fawaz fall back to each other. ZAR enablement is an idempotent patch, since currency rows are site data.

**Tech Stack:** Existing `crm/api/exchange_rate.py` provider pattern; frappe patch framework; FCRM Settings Select + `DashboardSettings.vue` options list.

**Spec:** User request: "add ZAR to dashboard currency and south african rate provider", production-grade. The dashboard currency field is a Link to `Currency`; ZAR exists on sites but ships `enabled=0`, which is what keeps it out of pickers.

## Global Constraints

- Test command shape: `docker exec simcrm_devcontainer-frappe-1 bash -c 'cd /home/frappe/frappe-bench && PYTHONPATH=/workspace/.worktrees/zar-sarb bench --site test_site run-tests --app crm --module <one.dotted.module>'`.
- `crm/tests/test_exchange_rate.py` conventions: `FrappeTestCase`, `@patch("crm.api.exchange_rate.requests.get")`, `_make_response(ok, json_data)`.
- Providers never raise on failure — they return `None`; only missing access keys throw.
- Doctype JSON changes bump `"modified"`; patches are one dotted line appended to `crm/patches.txt`.
- SARB requires no access key: do NOT add it to `PROVIDERS_REQUIRING_KEY` in the Vue settings.

---

### Task 1: `_fetch_from_sarb` + provider wiring

**Files:**
- Modify: `crm/api/exchange_rate.py`
- Test: `crm/tests/test_exchange_rate.py`

- [ ] **Step 1: failing tests** — `TestFetchFromSarb` (direct pair USD→ZAR returns the published value; inverse ZAR→USD returns 1/value; a non-ZAR pair returns None *without any HTTP call*; a historical date returns None without any HTTP call; not-ok response → None; network error → None; missing timeseries row → None; zero value → None, no ZeroDivisionError) and `TestSarbProviderRouting` (provider `sarb` returns the SARB rate; when SARB answers None it falls back to frankfurter; when frankfurter also fails, to fawaz — mirror the existing frankfurter fallback tests' shape, patching the private fetchers).
- [ ] **Step 2: run, expect FAIL** (import error on `_fetch_from_sarb`).
- [ ] **Step 3: implement:**

```python
# The official ZAR fix, straight from the central bank. HomePageRates carries
# the current "Rand per X" rate for exactly these counterparts, keyed by
# stable timeseries codes; anything else this provider does not answer and
# the free-provider chain takes over.
SARB_HOME_PAGE_RATES_URL = "https://custom.resbank.co.za/SarbWebApi/WebIndicators/HomePageRates"
SARB_ZAR_PER = {"USD": "EXCX135D", "GBP": "EXCZ001D", "EUR": "EXCZ002D", "JPY": "EXCZ120D"}


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
		if not value:  # missing row and a zero rate are both unusable
			return None
		return 1 / value if invert else value
	except Exception:
		return None
```

Wire into `_fetch_exchange_rate` after the fawaz branch, same free-provider fallback shape:

```python
	if provider == "sarb":
		# the central bank's own current ZAR fix; everything it does not
		# answer (history, non-ZAR pairs, downtime) falls through the same
		# free chain the other free providers use
		rate = _fetch_from_sarb(from_currency, to_currency, date)
		if rate is not None:
			return rate, provider
		rate = _fetch_from_frankfurter(from_currency, to_currency, date)
		if rate is not None:
			return rate, "frankfurter"
		return _fetch_from_fawaz_api(from_currency, to_currency, date), "fawazahmed-exchange-api"
```

- [ ] **Step 4: run** `crm.tests.test_exchange_rate` + `crm.tests.test_security_gates`. Expect PASS.
- [ ] **Step 5: commit** `feat: SARB as an exchange-rate provider`

### Task 2: enable ZAR everywhere (patch) + settings option

**Files:**
- Create: `crm/patches/v1_0/enable_zar_currency.py`
- Modify: `crm/patches.txt`, `crm/fcrm/doctype/fcrm_settings/fcrm_settings.json` (options `+ "\nsarb"`, bump modified)
- Test: `crm/tests/test_exchange_rate.py` (patch test class)

- [ ] **Step 1: failing test** — disable/delete ZAR, run patch, assert enabled with symbol `R`; run twice (idempotent); patch creates the row when a site lacks it entirely.
- [ ] **Step 2: implement:**

```python
import frappe


def execute():
	"""Make ZAR selectable. The dashboard-currency picker (and every other
	Currency link) only offers enabled currencies, and frappe ships ZAR
	disabled. Idempotent; creates the row for sites whose fixture predates it."""
	if frappe.db.exists("Currency", "ZAR"):
		frappe.db.set_value("Currency", "ZAR", "enabled", 1)
		return
	frappe.get_doc(
		{
			"doctype": "Currency",
			"currency_name": "ZAR",
			"enabled": 1,
			"fraction": "Cent",
			"fraction_units": 100,
			"smallest_currency_fraction_value": 0.01,
			"symbol": "R",
			"number_format": "#,###.##",
		}
	).insert(ignore_permissions=True)
```

- [ ] **Step 3: append** `crm.patches.v1_0.enable_zar_currency` to `crm/patches.txt`; run `bench --site test_site migrate`; verify `Currency ZAR enabled=1`.
- [ ] **Step 4: run** `crm.tests.test_exchange_rate`. Expect PASS.
- [ ] **Step 5: commit** `feat: ZAR ships enabled, with sarb in the provider options`

### Task 3: settings UI

**Files:**
- Modify: `frontend/src/components/Settings/DashboardSettings.vue`

- [ ] **Step 1:** add `{ label: 'South African Reserve Bank (SARB)', value: 'sarb' }` to the provider `:options` array. Do not touch `PROVIDERS_REQUIRING_KEY` (no key) or `PROVIDER_META` (no key docs needed).
- [ ] **Step 2:** frontend suite (`yarn test:run` in the container) + eslint/prettier via hooks.
- [ ] **Step 3: commit** `feat: SARB selectable as the exchange-rate provider in settings`

## Final gate

- Full backend suite green; `bench --site dev.localhost migrate` to enable ZAR on the dev site for browser QA; live smoke test of the real SARB endpoint through `get_exchange_rate("USD", "ZAR")` on the dev site (network available here; skip gracefully if not).
- PR to develop; merge on green CI.
