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

	def test_the_dropped_contacts_own_address_goes_with_the_kept_one(self):
		"""The address modal writes an Address with no links; once its contact was
		deleted it was tied to nothing hidden, and every rep could read it."""
		from crm.api.contact import merge_duplicate_contacts
		from crm.permissions.customers import has_address_permission

		email = self.email("addr")
		kept = self.contact(self.org_a, email, first_name="Kept")
		gone = self.contact(self.org_a, email, first_name="Gone")
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"Gone {frappe.generate_hash(length=6)}",
				"address_line1": "1 Gone St",
				"city": "Durban",
				"country": "South Africa",
				"address_type": "Office",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Contact", gone.name, "address", address.name)
		self.assertFalse(has_address_permission(address, "read", REP_B), "control: hidden with its contact")

		frappe.set_user(MANAGER)
		merge_duplicate_contacts(kept.name, [gone.name])
		frappe.set_user("Administrator")

		self.assertEqual(frappe.db.get_value("Contact", kept.name, "address"), address.name)
		self.assertTrue(frappe.get_doc("Address", address.name).has_link("Contact", kept.name))
		self.assertFalse(has_address_permission(frappe.get_doc("Address", address.name), "read", REP_B))

	def test_a_merge_leaves_no_repeated_event_row(self):
		from crm.api.contact import merge_duplicate_contacts

		email = self.email("evrow")
		kept = self.contact(self.org_a, email, first_name="Kept")
		gone = self.contact(self.org_a, email, first_name="Gone")
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Both",
				"starts_on": "2026-11-20 09:00:00",
				"event_participants": [
					{"reference_doctype": "Contact", "reference_docname": kept.name},
					{"reference_doctype": "Contact", "reference_docname": gone.name},
				],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(MANAGER)
		merge_duplicate_contacts(kept.name, [gone.name])
		frappe.set_user("Administrator")
		rows = frappe.get_doc("Event", event.name).event_participants
		self.assertEqual([r.reference_docname for r in rows], [kept.name])

	def test_a_team_manager_sees_their_scope_only(self):
		"""Neither the contacts, the account owner of a customer outside the team,
		nor deals they cannot read."""
		from frappe.utils.nestedset import rebuild_tree

		from crm.permissions.test_org_hierarchy import make_hierarchy_node

		mgr = make_hierarchy_node(MANAGER, is_group=1)
		make_hierarchy_node(REP_A, reports_to=mgr.name)
		rebuild_tree("CRM Sales Hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)

		email = self.email("team")
		mine = self.contact(self.org_a, email, first_name="Mine")
		also = self.contact(None, email, first_name="Unclaimed")
		outside = self.contact(self.org_b, email, first_name="Outside")
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org_b,
				"deal_owner": REP_B,
				"status": "Qualification",
			}
		)
		deal.append("contacts", {"contact": also.name})
		deal.insert(ignore_permissions=True)

		seen = []
		start = 0
		while True:
			page = self.list_as(MANAGER, start=start, page_length=50)
			seen += page["groups"]
			start += 50
			if start >= page["total"]:
				break
		group = next(g for g in seen if g["email"] == email)
		names = {c["name"] for c in group["contacts"]}
		self.assertEqual(names, {mine.name, also.name})
		self.assertNotIn(outside.name, json.dumps(seen, default=str))
		by_name = {c["name"]: c for c in group["contacts"]}
		self.assertEqual(by_name[also.name]["deals"], 0, "a deal outside the team was counted")
		self.assertEqual(by_name[mine.name]["customer_owner"], REP_A)
