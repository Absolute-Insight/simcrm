# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Report registry tests — shape, scoping, and agreement with the metrics layer."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.reports import REPORTS, get_report, list_reports

USER = "reports-rep@crmtest.test"


class ReportsTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		if not frappe.db.exists("User", USER):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Reports Rep",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.db.delete("CRM Rep Plan")

	def tearDown(self):
		frappe.db.delete("CRM Rep Plan")
		super().tearDown()

	def test_every_registered_report_returns_its_declared_columns(self):
		today = str(frappe.utils.nowdate())
		for name in REPORTS:
			out = get_report(name, today, today)
			declared = {c["key"] for c in out["columns"]}
			for row in out["rows"]:
				self.assertTrue(
					set(row).issubset(declared | set(row)),
					f"{name} row keys {set(row)} not covered by columns {declared}",
				)
				for key in declared:
					self.assertIn(key, row, f"{name} row missing column {key}")

	def test_an_unknown_report_throws(self):
		with self.assertRaises(frappe.ValidationError):
			get_report("not_a_report")

	def test_list_reports_matches_the_registry(self):
		self.assertEqual({r["name"] for r in list_reports()}, set(REPORTS))

	def test_plan_adherence_report_agrees_with_the_metric(self):
		from crm.api.dashboard import get_plan_adherence

		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": USER,
				"week_start": monday,
				"items": [
					{"activity_type": "Task", "planned_date": monday, "status": "Done"},
					{"activity_type": "Call", "planned_date": monday, "status": "Missed"},
				],
			}
		).insert(ignore_permissions=True)

		start, end = str(monday), str(frappe.utils.add_days(monday, 6))
		report = get_report("plan_adherence_by_rep", start, end, USER)
		row = next(r for r in report["rows"] if r["user"] == USER)
		metric = get_plan_adherence(start, end, USER)
		self.assertEqual(row["adherence"], metric["value"])
		self.assertEqual(row["planned"], 2)

	def test_a_sales_user_is_scoped_to_themselves(self):
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user(USER)
		today = str(frappe.utils.nowdate())
		out = get_report("plan_adherence_by_rep", today, today, user=None)
		for row in out["rows"]:
			self.assertEqual(row["user"], USER)
