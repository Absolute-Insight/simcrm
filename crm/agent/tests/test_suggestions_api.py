# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Suggestion inbox endpoint tests: ownership, status transitions, scoping."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.suggestions import (
	accept,
	dismiss,
	get_dismissal_stats,
	get_open_count,
	get_suggestions,
)

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
		make_sales_user(OWNER, "Suggestion Owner")
		make_sales_user(INTRUDER, "Suggestion Intruder")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Suggestion API Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		# the deal belongs to OWNER: acting on a suggestion means acting on the
		# record behind it, so the endpoints check access to that record too
		self.deal = (
			frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": OWNER}).insert().name
		)
		frappe.db.delete("CRM Suggestion", {"reference_docname": self.deal})

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

	def test_a_record_scoped_query_still_hides_other_reps_rows(self):
		"""Naming a record you can read is not a way to read another rep's queue for
		it -- the reference filter is additive, not a replacement for the owner one."""
		make_suggestion(OWNER, self.deal)
		make_suggestion(INTRUDER, self.deal, title="Someone else's")
		frappe.set_user(OWNER)
		rows = get_suggestions(reference_doctype="CRM Deal", reference_docname=self.deal)
		self.assertEqual([r["title"] for r in rows], ["Re-engage Acme"])

	def test_a_record_scoped_query_needs_access_to_the_record(self):
		make_suggestion(OWNER, self.deal)
		frappe.set_user(INTRUDER)
		with self.assertRaises(frappe.PermissionError):
			get_suggestions(reference_doctype="CRM Deal", reference_docname=self.deal)

	def test_an_unsupported_reference_type_is_rejected(self):
		frappe.set_user(OWNER)
		with self.assertRaises(frappe.ValidationError):
			get_suggestions(reference_doctype="User", reference_docname=OWNER)

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

	def test_an_unowned_suggestion_is_manager_only(self):
		"""An unowned row is a team-wide signal. It is invisible to every rep, so
		letting whichever rep names it accept or dismiss it is a one-sided door.

		The suggestion sits on the intruder's *own* deal, so record access is not
		what is being tested here -- only the null owner is.
		"""
		org = frappe.db.get_value("CRM Deal", self.deal, "organization")
		theirs = (
			frappe.get_doc({"doctype": "CRM Deal", "organization": org, "deal_owner": INTRUDER}).insert().name
		)
		name = make_suggestion(None, theirs)
		frappe.set_user(INTRUDER)
		with self.assertRaises(frappe.PermissionError):
			dismiss(name, reason="not mine either")

	def test_dismiss_records_the_reason(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		dismiss(name, reason="already spoke to them")
		doc = frappe.db.get_value("CRM Suggestion", name, ["status", "dismiss_reason"], as_dict=True)
		self.assertEqual(doc.status, "Dismissed")
		self.assertEqual(doc.dismiss_reason, "already spoke to them")

	def test_dismissals_are_readable_per_signal_with_their_reasons(self):
		"""The counts are what stretches the cooldown in the signal engine; this is
		the same data made legible, so the field is no longer write-only."""
		first = make_suggestion(OWNER, self.deal)
		second = make_suggestion(OWNER, self.deal, signal="no_next_step", title="Next step")
		frappe.set_user(OWNER)
		dismiss(first, reason="already spoke to them")
		dismiss(second, reason="not how we work")
		stats = {row["signal"]: row for row in get_dismissal_stats()}
		self.assertEqual(stats["idle_deal"]["dismissals"], 1)
		self.assertIn("already spoke to them", stats["idle_deal"]["reasons"])

	def test_a_rep_cannot_read_another_reps_dismissals(self):
		frappe.set_user(INTRUDER)
		with self.assertRaises(frappe.PermissionError):
			get_dismissal_stats(user=OWNER)

	def test_an_in_tree_manager_cannot_read_dismissals_outside_their_subtree(self):
		"""A flat "is a manager" test let any Sales Manager read every rep's
		dismissals; the check is now the same subtree that scopes the inbox."""
		manager = "suggestion-manager@crmtest.test"
		make_sales_user(manager, "Suggestion Manager")
		frappe.get_doc("User", manager).add_roles("Sales Manager")
		self.make_hierarchy(manager, OWNER)
		frappe.set_user(manager)
		self.assertEqual(get_dismissal_stats(user=OWNER), [])
		with self.assertRaises(frappe.PermissionError):
			get_dismissal_stats(user=INTRUDER)

	def test_the_open_count_is_scoped_like_the_list(self):
		make_suggestion(OWNER, self.deal)
		make_suggestion(INTRUDER, self.deal, title="Someone else's")
		frappe.set_user(OWNER)
		self.assertEqual(get_open_count(), 1)

	def test_an_in_tree_manager_is_badged_with_their_subtree_not_the_site(self):
		"""``db.count`` skips the doctype's permission query, so a manager scoped to a
		subtree was badged with every open row on the site while the inbox behind the
		badge showed only their team's."""
		manager = "suggestion-manager@crmtest.test"
		make_sales_user(manager, "Suggestion Manager")
		frappe.get_doc("User", manager).add_roles("Sales Manager")
		self.make_hierarchy(manager, OWNER)

		make_suggestion(OWNER, self.deal)
		make_suggestion(INTRUDER, self.deal, title="Outside the subtree")
		frappe.set_user(manager)
		self.assertEqual(get_open_count(), 1)
		self.assertEqual([s.user for s in get_suggestions()], [OWNER])

	def test_an_in_tree_manager_cannot_clear_an_orphan_outside_their_subtree(self):
		"""An orphan (its record already deleted) skips the record-access check, so
		a flat "is a manager" test was the only thing between any Sales Manager and
		every orphan on the site."""
		manager = "suggestion-manager@crmtest.test"
		make_sales_user(manager, "Suggestion Manager")
		frappe.get_doc("User", manager).add_roles("Sales Manager")
		self.make_hierarchy(manager, OWNER)

		orphan = make_suggestion(INTRUDER, self.deal)
		frappe.db.set_value("CRM Suggestion", orphan, "reference_docname", "CRM-DEAL-GONE-0000")
		frappe.set_user(manager)
		with self.assertRaises(frappe.PermissionError):
			dismiss(orphan, reason="not my team")

	def make_hierarchy(self, manager: str, *reports: str):
		"""A one-level sales tree, the same structure that scopes leads and deals."""
		self.addCleanup(frappe.db.set_single_value, "FCRM Settings", "enable_sales_hierarchy", 0)
		self.addCleanup(frappe.cache.delete_value, "crm_sales_hierarchy_subtree")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", [manager, *reports])})
		top = frappe.get_doc(
			{"doctype": "CRM Sales Hierarchy", "user": manager, "full_name": "Suggestion Manager"}
		).insert(ignore_permissions=True)
		for report in reports:
			frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": report, "reports_to": top.name}).insert(
				ignore_permissions=True
			)
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")

	def test_a_non_open_suggestion_cannot_be_accepted_again(self):
		name = make_suggestion(OWNER, self.deal)
		frappe.set_user(OWNER)
		accept(name)
		with self.assertRaises(frappe.ValidationError):
			accept(name)

	def test_a_user_without_a_sales_role_is_turned_away(self):
		outsider = "suggestion-outsider@crmtest.test"
		if not frappe.db.exists("User", outsider):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": outsider,
					"first_name": "Outsider",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
		frappe.set_user(outsider)
		with self.assertRaises(frappe.PermissionError):
			get_suggestions()


class SuggestionDoctypePermissionTest(IntegrationTestCase):
	"""The doctype block itself, not the endpoints.

	The API saves with ``ignore_permissions``, so a rep needs no write bit —
	leaving one granted keeps ``frappe.client.set_value`` as a way around the
	accept/dismiss state machine.
	"""

	def test_a_sales_user_has_no_write_on_the_doctype(self):
		perms = [p for p in frappe.get_meta("CRM Suggestion").permissions if p.role == "Sales User"]
		self.assertTrue(perms)
		self.assertFalse(perms[0].write)
		self.assertTrue(perms[0].read)
