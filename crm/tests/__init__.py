import json
import os

import frappe


def before_tests():
	align_global_currency_default()
	load_crm_user_test_records()


def align_global_currency_default():
	"""Make the site's global currency default agree with the CRM's base currency.

	``CRM Deal.currency`` is a plain Link with no default, so frappe fills an
	empty one from the global ``currency`` user default -- before ``validate``
	ever runs, which is why this cannot be fixed in the doctype. On a bare site
	that default is unset and a fixture deal is simply base-currency. Install
	ERPNext, which the release lanes do, and its Company sets that global to the
	company's currency: every fixture deal that names no currency silently
	becomes INR, ``update_exchange_rate`` fetches a real INR->USD rate, and the
	money suites measure the day's exchange rate instead of the code. 25,000
	came back as 263.25 (#145).

	The deals are not wrong -- 25,000 INR really is about 263 USD. The fixtures
	are: they mean base currency and never say so. Rather than pin ``currency``
	in the ten separate ``make_deal`` helpers and in every one written after
	this, align the ambient default they inherit, once, here.

	This does not stop a suite testing conversion: one that wants a foreign
	currency still sets it explicitly and mocks the rate, as test_exchange_rate
	does. It only stops the ones that never mentioned currency from being
	quietly redenominated.
	"""
	from crm.api.dashboard import get_base_currency

	frappe.db.set_default("currency", get_base_currency())


def load_crm_user_test_records():
	"""Load CRM user test records from crm/tests/test_records.json"""
	test_records_path = os.path.join(os.path.dirname(__file__), "test_records.json")

	if os.path.exists(test_records_path):
		with open(test_records_path) as f:
			test_records = json.load(f)

		for record in test_records:
			if not frappe.db.exists("User", record.get("email")):
				doc = frappe.get_doc(record)
				doc.insert(ignore_permissions=True, ignore_if_duplicate=True)
