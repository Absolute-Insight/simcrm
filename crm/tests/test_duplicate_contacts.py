"""The manager's review of contacts that share an email address
(crm.api.contact.get_duplicate_contacts / merge_duplicate_contacts)."""

import json

import frappe

from crm.tests.test_event_attendees import MANAGER, REP_A, REP_B, AttendeeCase


class TestDuplicateContacts(AttendeeCase):
	def list_as(self, user, **kwargs):
		from crm.api.contact import get_duplicate_contacts

		frappe.set_user(user)
		try:
			return get_duplicate_contacts(**kwargs)
		finally:
			frappe.set_user("Administrator")

	def group_for(self, result, email):
		return next((g for g in result["groups"] if g["email"] == email), None)

	def test_a_rep_cannot_list_or_merge(self):
		from crm.api.contact import merge_duplicate_contacts

		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.call("crm.api.contact.get_duplicate_contacts")
		with self.assertRaises(frappe.PermissionError):
			merge_duplicate_contacts("x", ["y"])

	def test_contacts_sharing_an_address_are_grouped_whatever_its_case(self):
		email = self.email("dup")
		first = self.contact(self.org_a, email, first_name="Dup One")
		second = self.contact(self.org_b, f" {email.upper()}", first_name="Dup Two")
		self.contact(self.org_b, self.email("single"))

		seen = []
		start = 0
		while True:
			page = self.list_as(MANAGER, start=start, page_length=50)
			seen += page["groups"]
			start += 50
			if start >= page["total"]:
				break
		group = next(g for g in seen if g["email"] == email)
		self.assertEqual({c["name"] for c in group["contacts"]}, {first.name, second.name})
		by_name = {c["name"]: c for c in group["contacts"]}
		self.assertEqual(by_name[second.name]["customer_owner"], REP_B)
		self.assertFalse(any(g["email"] == self.email("single") for g in seen))

	def test_the_page_length_is_capped(self):
		page = self.list_as(MANAGER, page_length=10_000)
		self.assertLessEqual(len(page["groups"]), 50)

	def test_merging_keeps_every_link(self):
		from crm.api.contact import merge_duplicate_contacts

		email = self.email("merge")
		kept = self.contact(self.org_a, email, first_name="Kept")
		gone = self.contact(self.org_b, email, self.email("extra"), first_name="Gone")
		frappe.db.set_value("Contact", gone.name, "mobile_no", "")
		gone.reload()
		gone.append("phone_nos", {"phone": "+27 11 555 0101"})
		gone.save(ignore_permissions=True)

		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org_b,
				"deal_owner": REP_B,
				"status": "Qualification",
			}
		)
		deal.append("contacts", {"contact": gone.name})
		deal.append("contacts", {"contact": kept.name})
		deal.insert(ignore_permissions=True)
		named = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Named",
				"starts_on": "2026-11-20 09:00:00",
				"event_participants": [{"reference_doctype": "Contact", "reference_docname": gone.name}],
			}
		).insert(ignore_permissions=True)
		typed = self.event_as(REP_A, self.email("extra"))["name"]
		self.assertEqual(self.attendees(typed), {self.email("extra"): gone.name})
		call = frappe.get_doc(
			{
				"doctype": "CRM Call Log",
				"id": frappe.generate_hash(length=10),
				"type": "Outgoing",
				"from": "+27115550100",
				"to": "+27115550101",
				"status": "Completed",
				"reference_doctype": "Contact",
				"reference_docname": gone.name,
			}
		).insert(ignore_permissions=True)

		frappe.set_user(MANAGER)
		self.assertEqual(merge_duplicate_contacts(kept.name, json.dumps([gone.name])), kept.name)
		frappe.set_user("Administrator")

		self.assertFalse(frappe.db.exists("Contact", gone.name))
		self.assertEqual(
			[r.contact for r in frappe.get_doc("CRM Deal", deal.name).contacts], [kept.name], "deal rows"
		)
		self.assertEqual(
			frappe.get_doc("Event", named.name).event_participants[0].reference_docname, kept.name
		)
		self.assertEqual(self.attendees(typed), {self.email("extra"): kept.name})
		self.assertEqual(frappe.db.get_value("CRM Call Log", call.name, "reference_docname"), kept.name)
		self.assertFalse(
			frappe.db.exists("Communication Link", {"link_doctype": "Contact", "link_name": gone.name})
		)
		kept.reload()
		self.assertIn(self.email("extra"), {r.email_id for r in kept.email_ids})
		self.assertIn("+27 11 555 0101", {r.phone for r in kept.phone_nos})

	def test_only_contacts_sharing_an_address_merge(self):
		from crm.api.contact import merge_duplicate_contacts

		kept = self.contact(self.org_a, self.email("one"))
		other = self.contact(self.org_a, self.email("two"))
		frappe.set_user(MANAGER)
		with self.assertRaises(frappe.ValidationError):
			merge_duplicate_contacts(kept.name, [other.name])
		with self.assertRaises(frappe.PermissionError):
			merge_duplicate_contacts(kept.name, ["No Such Contact"])
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("Contact", other.name))
