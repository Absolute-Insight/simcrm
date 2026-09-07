# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Actions that change the whole site are the operator's, not the customer's
line manager's. ``crm/tests/test_security_gates.py`` covers the plain Sales User;
these are the Sales Manager, who holds read on FCRM Settings and so reaches every
whitelisted method on it through ``run_doc_method``."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

MANAGER = "adminonly-manager@crmtest.test"
PEER = "adminonly-peer@crmtest.test"
REP = "adminonly-rep@crmtest.test"


def ensure_user(email: str, name: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)


class DemoDataGateTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(MANAGER, "Manager", "Sales Manager", "Sales User")
		self.addCleanup(frappe.set_user, "Administrator")

	def test_a_sales_manager_cannot_seed_demo_data_into_the_site(self):
		"""Three fake users, eleven leads, seven deals and two years of synthetic
		history land in the live pipeline; the signals and the forecast snapshot
		count them from the next run. System Manager only."""
		frappe.set_user(MANAGER)
		settings = frappe.get_single("FCRM Settings")
		with patch("crm.fcrm.doctype.fcrm_settings.fcrm_settings.create_demo_data") as seed:
			with self.assertRaises(frappe.PermissionError):
				settings.restore_demo_data()
			seed.assert_not_called()

	def test_a_system_manager_still_can(self):
		frappe.set_user("Administrator")
		settings = frappe.get_single("FCRM Settings")
		with patch("crm.fcrm.doctype.fcrm_settings.fcrm_settings.create_demo_data") as seed:
			settings.restore_demo_data()
			seed.assert_called_once()
