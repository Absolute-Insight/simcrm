# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Suggestion inbox endpoint tests: ownership, status transitions, scoping."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.suggestions import accept, dismiss, get_open_count, get_suggestions

OWNER = "suggestion-owner@crmtest.test"
INTRUDER = "suggestion-intruder@crmtest.test"


def make_sales_user(email: str, first_name: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": first_name,
				"send_welcome_email": 0,
			}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


def make_suggestion(user: str | None, deal: str, **overrides) -> str:
	doc = {
		"doctype": "CRM Suggestion",
		"signal": "idle_deal",
		"title": "Re-engage Acme",
		"reference_doctype": "CRM Deal",
		"reference_docname": deal,
		"user": user,
		"status": "Open",
		"score": 50,
	}
	doc.update(overrides)
	return frappe.get_doc(doc).insert(ignore_permissions=True).name


class SuggestionApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("suggestions_api")
		self.addCleanup(frappe.db.rollback, save_point="suggestions_api")
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.db.delete("CRM Suggestion")
		make_sales_user(OWNER, "Suggestion Owner")
		make_sales_user(INTRUDER, "Suggestion Intruder")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Suggestion API Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert().name

	def test_a_sales_user_sees_only_their_own_suggestions(self):
		make_suggestion(OWNER, self.deal)
		make_suggestion(INTRUDER, self.deal, title="Someone else's")
		make_suggestion(None, self.deal, title="Unowned")
		frappe.set_user(OWNER)
		rows = get_suggestions()
		self.assertEqual([r["title"] for r in rows], ["Re-engage Acme"])

	def test_a_record_scoped_query_returns_that_records_suggestions(self):
		make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		rows = get_suggestions(reference_doctype="CRM Deal", reference_docname=self.deal)
		self.assertEqual(len(rows), 1)

	def test_the_owner_can_accept_and_the_status_flips(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		out = accept(name)
		self.assertEqual(out["status"], "Accepted")
		self.assertEqual(frappe.db.get_value("CRM Suggestion", name, "status"), "Accepted")

	def test_another_sales_user_cannot_dismiss_someone_elses(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(INTRUDER)
		with self.assertRaises(frappe.PermissionError):
			dismiss(name, reason="not mine")

	def test_dismiss_records_the_reason(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		dismiss(name, reason="already spoke to them")
		doc = frappe.db.get_value("CRM Suggestion", name, ["status", "dismiss_reason"], as_dict=True)
		self.assertEqual(doc.status, "Dismissed")
		self.assertEqual(doc.dismiss_reason, "already spoke to them")

	def test_the_open_count_is_scoped_like_the_list(self):
		make_suggestion(OWNER, self.deal)
		make_suggestion(INTRUDER, self.deal, title="Someone else's")
		frappe.set_user(OWNER)
		self.assertEqual(get_open_count(), 1)

	def test_a_non_open_suggestion_cannot_be_accepted_again(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		accept(name)
		with self.assertRaises(frappe.ValidationError):
			accept(name)
