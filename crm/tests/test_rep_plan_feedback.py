# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The planner as MBP's reps asked for it after their first week on it.

Who they are meeting goes on the activity, a note has room for more than a
line, a done visit's outcome can be added to from a desk, and Customers and
Contacts can be narrowed to the rep's own.
"""

from __future__ import annotations

import frappe

from crm.api.doc import my_customer_names
from crm.api.rep_plan import (
	TEXT_LIMIT,
	cancel_item,
	complete_item,
	get_plan,
	log_unplanned_visit,
	save_plan,
	update_outcome,
)
from crm.tests.test_rep_plan_outcomes import OTHER, REP, OutcomeTestCase, this_monday, today


class FeedbackTestCase(OutcomeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.org.db_set("account_owner", REP)
		self.other_org.db_set("account_owner", OTHER)
		self.contact = self.contact_at(self.org.name, "Jaco", "Gouws")
		self.their_contact = self.contact_at(self.other_org.name, "Barend", "Groenewald")
		frappe.set_user(REP)

	def contact_at(self, organization, first, last):
		return (
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": first,
					"last_name": last,
					"company_name": organization,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def plan(self, **row):
		item = {
			"activity_type": "Visit",
			"planned_date": today(),
			"note": "Deliveries",
			"organization": self.org.name,
			**row,
		}
		return save_plan(this_monday(), [item])["items"][0]


class ContactOnTheActivityTest(FeedbackTestCase):
	def test_the_person_met_is_kept_on_the_item(self):
		row = self.plan(contact=self.contact)
		self.assertEqual(row["contact"], self.contact)
		self.assertEqual(get_plan(this_monday())["items"][0]["contact"], self.contact)

	def test_the_visit_event_names_the_person_beside_the_customer(self):
		row = self.plan(contact=self.contact)
		event = complete_item(row["name"], "Quote for four gate valves to follow")["items"][0]["fulfilled_by"]
		participants = {
			(p.reference_doctype, p.reference_docname)
			for p in frappe.get_doc("Event", event).event_participants
		}
		self.assertEqual(participants, {("CRM Organization", self.org.name), ("Contact", self.contact)})

	def test_a_cancelled_visit_names_them_too(self):
		row = self.plan(contact=self.contact)
		event = cancel_item(row["name"], "Plant shut")["items"][0]["fulfilled_by"]
		names = [p.reference_docname for p in frappe.get_doc("Event", event).event_participants]
		self.assertIn(self.contact, names)

	def test_a_contact_at_another_reps_customer_is_refused(self):
		with self.assertRaises(frappe.PermissionError):
			self.plan(contact=self.their_contact)

	def test_a_logged_visit_keeps_its_contact(self):
		plan = log_unplanned_visit(self.org.name, "Called to site for a breakdown", contact=self.contact)
		logged = [i for i in plan["items"] if i["contact"] == self.contact]
		self.assertEqual(len(logged), 1)

	def test_a_deleted_contact_is_dropped_not_fatal(self):
		row = self.plan(contact=self.contact)
		frappe.set_user("Administrator")
		frappe.delete_doc("Contact", self.contact, force=True, ignore_permissions=True)
		frappe.set_user(REP)
		plan = save_plan(this_monday(), [{**row, "note": "Deliveries, rescheduled"}])
		self.assertIsNone(plan["items"][0]["contact"])


class RoomToWriteTest(FeedbackTestCase):
	def test_a_note_longer_than_a_line_is_kept_whole(self):
		note = "Deliveries. " * 30
		self.assertGreater(len(note), 140)
		self.assertEqual(self.plan(note=note)["note"], note)

	def test_a_note_is_still_bounded(self):
		with self.assertRaises(frappe.ValidationError):
			self.plan(note="x" * (TEXT_LIMIT + 1))


class EditTheOutcomeTest(FeedbackTestCase):
	def test_a_done_visits_outcome_is_added_to_and_the_calendar_says_the_same(self):
		row = self.plan()
		event = complete_item(row["name"], "Deliveries done")["items"][0]["fulfilled_by"]
		longer = "Deliveries done.\nQuote for 4 gate valves to follow."
		after = update_outcome(row["name"], longer)["items"][0]
		self.assertEqual(after["outcome"], longer)
		# the status and the record behind it stay as they were
		self.assertEqual((after["status"], after["fulfilled_by"]), ("Done", event))
		self.assertEqual(
			frappe.db.get_value("Event", event, "description"),
			"Deliveries done.<br>Quote for 4 gate valves to follow.",
		)

	def test_a_cancellation_reason_can_be_corrected(self):
		row = self.plan()
		cancel_item(row["name"], "Plant shut")
		after = update_outcome(row["name"], "Plant shut for the strike; rebooked for next week")
		self.assertEqual(after["items"][0]["status"], "Cancelled")

	def test_an_item_not_yet_closed_has_no_outcome_to_edit(self):
		row = self.plan()
		with self.assertRaises(frappe.ValidationError):
			update_outcome(row["name"], "Not there yet")

	def test_the_outcome_is_never_emptied(self):
		row = self.plan()
		complete_item(row["name"], "Deliveries done")
		with self.assertRaises(frappe.ValidationError):
			update_outcome(row["name"], "  ")

	def test_another_reps_outcome_cannot_be_edited(self):
		row = self.plan()
		complete_item(row["name"], "Deliveries done")
		frappe.set_user(OTHER)
		with self.assertRaises(frappe.PermissionError):
			update_outcome(row["name"], "I was there too")

	def test_an_event_the_matcher_found_is_not_rewritten(self):
		row = self.plan()
		complete_item(row["name"], "Deliveries done")
		event = frappe.db.get_value("CRM Rep Plan Item", row["name"], "fulfilled_by")
		# as if the matcher had found it: the rep's word did not write it
		frappe.db.set_value("CRM Rep Plan Item", row["name"], "manual_override", 0)
		update_outcome(row["name"], "Deliveries done, and more")
		self.assertEqual(frappe.db.get_value("Event", event, "description"), "Deliveries done")


class MyCustomersTest(FeedbackTestCase):
	def test_only_the_callers_own_customers_and_every_name_they_go_by(self):
		names = my_customer_names()
		self.assertIn(self.org.name, names)
		self.assertIn(self.org.organization_name, names)
		self.assertNotIn(self.other_org.name, names)

	def test_a_user_with_no_customers_gets_none(self):
		frappe.set_user("Administrator")
		frappe.db.set_value("CRM Organization", self.org.name, "account_owner", None)
		frappe.set_user(REP)
		self.assertEqual(
			[n for n in my_customer_names() if n in (self.org.name, self.org.organization_name)], []
		)


class DealQuoteSearchTest(FeedbackTestCase):
	def test_the_quote_number_is_a_deal_search_field_and_an_admins_are_kept(self):
		from frappe.custom.doctype.property_setter.property_setter import make_property_setter

		from crm.integrations.acumatica.install import ensure_deal_quote_search

		frappe.set_user("Administrator")
		if not frappe.get_meta("CRM Deal").has_field("acumatica_sales_quote"):
			self.skipTest("the Acumatica fields are not on this site")
		make_property_setter("CRM Deal", None, "search_fields", "lead_name", "Data", for_doctype=True)
		frappe.clear_cache(doctype="CRM Deal")
		ensure_deal_quote_search()
		ensure_deal_quote_search()
		frappe.clear_cache(doctype="CRM Deal")
		self.assertEqual(frappe.get_meta("CRM Deal").search_fields, "acumatica_sales_quote,lead_name")
