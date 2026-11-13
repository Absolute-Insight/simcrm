"""One rep cannot see, or take, another rep's customers."""

import json

import frappe
from frappe.tests import IntegrationTestCase

from crm.permissions.customers import (
	get_address_permission_query_conditions,
	get_organization_permission_query_conditions,
	has_address_permission,
	has_contact_permission,
	has_organization_permission,
)

REP_A = "cust-rep-a@scope.test"
REP_B = "cust-rep-b@scope.test"
MANAGER = "cust-manager@scope.test"


def make_user(email, role):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


class TestCustomerScope(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(REP_A, "Sales User")
		make_user(REP_B, "Sales User")
		make_user(MANAGER, "Sales Manager")
		# committed: each test rolls back, and the users must outlive the first
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		# Pinned: hierarchy off and out-of-tree managers seeing everything is the
		# shape under test; another test file may have left either switched.
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.org_a = self.org("A", REP_A)
		self.org_b = self.org("B", REP_B)
		self.org_free = self.org("Free", None)
		self.org_shared = self.org("Shared", REP_B)
		# rep A holds a deal on rep B's customer from before it was B's
		self.deal(self.org_shared, REP_A)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def org(self, label, owner):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Scope {label} {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", doc.name, "account_owner", owner)
		return doc.name

	def deal(self, organization, owner):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Deal",
					"organization": organization,
					"deal_owner": owner,
					"status": "Qualification",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def visible_to(self, user):
		frappe.set_user(user)
		try:
			return set(frappe.get_list("CRM Organization", pluck="name", limit_page_length=0))
		finally:
			frappe.set_user("Administrator")

	# --- what a rep sees ----------------------------------------------------

	def test_a_rep_sees_their_own_unclaimed_and_dealt_customers_only(self):
		seen = self.visible_to(REP_A)
		self.assertIn(self.org_a, seen)
		self.assertIn(self.org_free, seen)
		self.assertIn(self.org_shared, seen, "a customer the rep has a deal on stays visible")
		self.assertNotIn(self.org_b, seen)

	def test_the_record_itself_is_refused(self):
		doc = frappe.get_doc("CRM Organization", self.org_b)
		self.assertFalse(has_organization_permission(doc, "read", REP_A))
		self.assertTrue(has_organization_permission(doc, "read", REP_B))
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("CRM Organization", self.org_b).check_permission("read")

	def test_a_link_search_does_not_offer_another_reps_customer(self):
		from frappe.desk.search import search_link

		frappe.set_user(REP_A)
		self.assertEqual(
			[o["value"] for o in search_link("CRM Organization", self.org_b)], [], "found by name in a picker"
		)

	def test_a_code_search_does_not_reveal_another_reps_customer(self):
		from crm.api.organization import find_by_code

		if not frappe.get_meta("CRM Organization").has_field("acumatica_id"):
			# creating it here would be DDL, which commits this test's rows for good
			self.skipTest("the Acumatica fields are not installed on this site")
		frappe.db.set_value("CRM Organization", self.org_b, "acumatica_id", "C-SCOPEB1")
		frappe.set_user(REP_A)
		self.assertEqual(find_by_code("C-SCOPEB"), [])

	def test_contacts_at_a_hidden_customer_are_hidden_with_it(self):
		at_b = frappe.get_doc(
			{"doctype": "Contact", "first_name": "At B", "company_name": self.org_b}
		).insert(ignore_permissions=True)
		at_a = frappe.get_doc(
			{"doctype": "Contact", "first_name": "At A", "company_name": self.org_a}
		).insert(ignore_permissions=True)
		nowhere = frappe.get_doc({"doctype": "Contact", "first_name": "Freelancer"}).insert(
			ignore_permissions=True
		)
		self.assertFalse(has_contact_permission(at_b, "read", REP_A))
		self.assertTrue(has_contact_permission(at_a, "read", REP_A))
		self.assertTrue(has_contact_permission(nowhere, "read", REP_A))
		frappe.set_user(REP_A)
		listed = set(frappe.get_list("Contact", pluck="name", limit_page_length=0))
		self.assertNotIn(at_b.name, listed)
		self.assertIn(at_a.name, listed)

	# --- what a rep cannot do -----------------------------------------------

	def test_a_rep_cannot_open_a_deal_on_another_reps_customer(self):
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "CRM Deal",
					"organization": self.org_b,
					"deal_owner": REP_A,
					"status": "Qualification",
				}
			).insert()

	def test_a_rep_cannot_move_their_deal_onto_another_reps_customer(self):
		name = self.deal(self.org_a, REP_A)
		frappe.set_user(REP_A)
		doc = frappe.get_doc("CRM Deal", name)
		doc.organization = self.org_b
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_a_rep_cannot_plan_a_visit_to_another_reps_customer(self):
		today = frappe.utils.getdate()
		monday = frappe.utils.add_days(today, -today.weekday())
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "CRM Rep Plan",
					"user": REP_A,
					"week_start": monday,
					"items": [{"activity_type": "Visit", "planned_date": today, "organization": self.org_b}],
				}
			).insert(ignore_permissions=True)

	def test_a_rep_cannot_reassign_a_customer(self):
		frappe.set_user(REP_A)
		doc = frappe.get_doc("CRM Organization", self.org_a)
		doc.account_owner = REP_B
		try:
			doc.save()
		except frappe.PermissionError:
			pass
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Organization", self.org_a, "account_owner"), REP_A)

	def test_the_first_deal_on_an_unclaimed_customer_claims_it(self):
		frappe.set_user(REP_A)
		frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org_free,
				"deal_owner": REP_A,
				"status": "Qualification",
			}
		).insert()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Organization", self.org_free, "account_owner"), REP_A)
		self.assertNotIn(self.org_free, self.visible_to(REP_B))

	def test_a_customer_a_rep_adds_is_theirs(self):
		frappe.set_user(REP_A)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Scope New {frappe.generate_hash(length=6)}",
			}
		).insert()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Organization", doc.name, "account_owner"), REP_A)

	# --- what names a customer from the side ---------------------------------

	def _contact(self, company, first_name="Person"):
		return frappe.get_doc(
			{"doctype": "Contact", "first_name": first_name, "company_name": company}
		).insert(ignore_permissions=True)

	def test_a_contact_named_by_the_customers_display_name_is_hidden_too(self):
		frappe.db.set_value("CRM Organization", self.org_b, "organization_name", "Display Name B")
		contact = self._contact("Display Name B")
		self.assertFalse(has_contact_permission(contact, "read", REP_A))

	def test_a_rep_cannot_read_a_hidden_contact_by_attaching_it_to_a_deal(self):
		hidden = self._contact(self.org_b)
		deal = self.deal(self.org_a, REP_A)
		frappe.set_user(REP_A)
		doc = frappe.get_doc("CRM Deal", deal)
		doc.append("contacts", {"contact": hidden.name})
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_a_contact_on_a_reps_own_deal_stays_readable(self):
		"""Put there by a manager, or before the customer was reassigned."""
		contact = self._contact(self.org_b)
		doc = frappe.get_doc("CRM Deal", self.deal(self.org_a, REP_A))
		doc.append("contacts", {"contact": contact.name})
		doc.save(ignore_permissions=True)
		self.assertTrue(has_contact_permission(contact, "read", REP_A))

	def test_a_lead_cannot_take_a_hidden_customers_details_or_contact(self):
		hidden = self._contact(self.org_b)
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Prospect", "lead_owner": REP_A, "status": "New"}
		).insert(ignore_permissions=True)
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			lead.create_organization(self.org_b)
		with self.assertRaises(frappe.PermissionError):
			lead.create_contact(hidden.name, False)

	def test_an_address_at_a_hidden_customer_is_hidden_with_it(self):
		def address(org, title):
			return frappe.get_doc(
				{
					"doctype": "Address",
					"address_title": title,
					"address_type": "Office",
					"address_line1": "1 Road",
					"city": "Boksburg",
					"country": "South Africa",
					"links": [{"link_doctype": "CRM Organization", "link_name": org}],
				}
			).insert(ignore_permissions=True)

		hidden, own = address(self.org_b, "B office"), address(self.org_a, "A office")
		frappe.db.set_value("CRM Organization", self.org_b, "address", None)
		frappe.set_user(REP_A)
		listed = set(frappe.get_list("Address", pluck="name", limit_page_length=0))
		self.assertNotIn(hidden.name, listed)
		self.assertIn(own.name, listed)

	def _address(self, title, **fields):
		return frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": f"{title} {frappe.generate_hash(length=6)}",
				"address_type": "Office",
				"address_line1": "1 Road",
				"city": "Boksburg",
				"country": "South Africa",
				**fields,
			}
		).insert(ignore_permissions=True)

	def _contact_with_address(self, company, **fields):
		"""As the contact page's address modal writes it: a plain Address with no
		links, named by ``Contact.address``."""
		address = self._address("Contact site")
		contact = self._contact(company)
		frappe.db.set_value("Contact", contact.name, {"address": address.name, **fields})
		return contact, address

	def addresses_for(self, user):
		frappe.set_user(user)
		try:
			return set(frappe.get_list("Address", pluck="name", limit_page_length=0))
		finally:
			frappe.set_user("Administrator")

	def test_a_hidden_contacts_own_address_is_hidden_with_it(self):
		contact, address = self._contact_with_address(self.org_b)
		self.assertFalse(has_contact_permission(contact, "read", REP_A), "control: the contact is hidden")
		self.assertNotIn(address.name, self.addresses_for(REP_A))
		self.assertFalse(has_address_permission(address, "read", REP_A))
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc("Address", address.name).check_permission("read")

	def test_an_address_linked_to_a_hidden_contact_is_hidden_with_it(self):
		"""frappe's own shape: a Dynamic Link from the Address to the Contact."""
		contact = self._contact(self.org_b)
		address = self._address("Linked site", links=[{"link_doctype": "Contact", "link_name": contact.name}])
		self.assertNotIn(address.name, self.addresses_for(REP_A))
		self.assertFalse(has_address_permission(address, "read", REP_A))

	def test_a_visible_contacts_address_stays_visible(self):
		own, own_address = self._contact_with_address(self.org_a)
		free, free_address = self._contact_with_address(self.org_free)
		nowhere, nowhere_address = self._contact_with_address(None)
		linked = self._address("Own linked", links=[{"link_doctype": "Contact", "link_name": own.name}])
		seen = self.addresses_for(REP_A)
		for address in (own_address, free_address, nowhere_address, linked):
			with self.subTest(address=address.address_title):
				self.assertIn(address.name, seen)
				self.assertTrue(has_address_permission(address, "read", REP_A))
		self.assertTrue(has_address_permission(own_address, "write", REP_A))

	def test_the_customers_own_rep_and_managers_keep_a_contacts_address(self):
		_contact, address = self._contact_with_address(self.org_b)
		self.assertIn(address.name, self.addresses_for(REP_B))
		self.assertTrue(has_address_permission(address, "write", REP_B))
		# an out-of-tree manager at "All records", and a System Manager
		self.assertEqual(get_address_permission_query_conditions(MANAGER), "")
		self.assertTrue(has_address_permission(address, "write", MANAGER))
		self.assertIn(address.name, self.addresses_for("Administrator"))

	def test_a_team_manager_sees_the_teams_contact_addresses_only(self):
		_contact, team_address = self._contact_with_address(self.org_a)
		_contact, other_address = self._contact_with_address(self.org_b)
		self._in_tree_manager()
		# the rule itself: this fixture's manager holds Sales Manager alone, and the
		# role grants no read on Address for a list to be narrowed from
		seen = set(
			frappe.db.sql_list(
				f"select name from `tabAddress` where {get_address_permission_query_conditions(MANAGER)}"
			)
		)
		self.assertIn(team_address.name, seen)
		self.assertNotIn(other_address.name, seen)
		self.assertTrue(has_address_permission(team_address, "write", MANAGER))
		self.assertFalse(has_address_permission(other_address, "read", MANAGER))

	def test_a_contact_on_a_reps_deal_brings_its_address_for_reading_only(self):
		"""A deal there gives read on the contact, so on the contact's address too."""
		contact, address = self._contact_with_address(self.org_b)
		doc = frappe.get_doc("CRM Deal", self.deal(self.org_a, REP_A))
		doc.append("contacts", {"contact": contact.name})
		doc.save(ignore_permissions=True)
		self.assertIn(address.name, self.addresses_for(REP_A))
		self.assertTrue(has_address_permission(address, "read", REP_A))
		self.assertFalse(has_address_permission(address, "write", REP_A))

	def test_a_rep_keeps_an_address_they_wrote(self):
		"""The modal saves the Address before the Contact names it."""
		frappe.set_user(REP_A)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Rep A wrote this",
				"address_type": "Office",
				"address_line1": "1 Road",
				"city": "Boksburg",
				"country": "South Africa",
			}
		).insert()
		frappe.set_user("Administrator")
		contact = self._contact(self.org_b)
		frappe.db.set_value("Contact", contact.name, "address", address.name)
		self.assertIn(address.name, self.addresses_for(REP_A))

	def test_contacts_without_an_address_do_not_hide_every_address(self):
		"""One NULL in a NOT IN subquery makes the whole test NULL."""
		self._contact(self.org_b)
		address = self._address("Nobody's")
		self.assertIn(address.name, self.addresses_for(REP_A))

	# --- the attendee lookup ---------------------------------------------------

	def _contact_with_emails(self, company, *emails):
		"""The first address is the primary one, as frappe keeps ``email_id``."""
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Attendee",
				"company_name": company,
				"email_ids": [
					{"email_id": email, "is_primary": 1 if idx == 0 else 0}
					for idx, email in enumerate(emails)
				],
			}
		).insert(ignore_permissions=True)

	def find(self, user, email):
		from crm.api.contact import find_by_email

		frappe.set_user(user)
		try:
			return find_by_email(email)
		finally:
			frappe.set_user("Administrator")

	def test_an_attendee_is_found_by_a_secondary_address(self):
		"""``Contact.email_id`` is the primary address only; looking there made a
		second Contact for somebody invited at their other one."""
		contact = self._contact_with_emails(self.org_a, "first@attendee.test", "second@attendee.test")
		self.assertEqual(frappe.db.get_value("Contact", {"email_id": "second@attendee.test"}), None)
		self.assertEqual(self.find(REP_A, "first@attendee.test"), contact.name)
		self.assertEqual(self.find(REP_A, "second@attendee.test"), contact.name)
		self.assertEqual(self.find(REP_A, " second@attendee.test "), contact.name)

	def test_the_contact_an_address_is_primary_on_is_preferred(self):
		self._contact_with_emails(self.org_a, "other@attendee.test", "shared@attendee.test")
		primary = self._contact_with_emails(self.org_a, "shared@attendee.test")
		self.assertEqual(self.find(REP_A, "shared@attendee.test"), primary.name)

	def test_the_lookup_does_not_find_a_contact_at_a_hidden_customer(self):
		"""Or an address would be a way to ask whether a colleague's customer has it."""
		hidden = self._contact_with_emails(self.org_b, "buyer@hidden.test", "also@hidden.test")
		for email in ("buyer@hidden.test", "also@hidden.test"):
			with self.subTest(email=email):
				self.assertIsNone(self.find(REP_A, email))
				self.assertEqual(self.find(REP_B, email), hidden.name)
				self.assertEqual(self.find(MANAGER, email), hidden.name)
				self.assertEqual(self.find("Administrator", email), hidden.name)

	def test_the_lookup_finds_nothing_for_an_unknown_or_blank_address(self):
		self.assertIsNone(self.find(REP_A, "nobody@attendee.test"))
		self.assertIsNone(self.find(REP_A, ""))

	def test_the_lookup_needs_read_on_contacts(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			frappe.call("crm.api.contact.find_by_email", email="first@attendee.test")

	def test_an_enrichment_run_on_a_hidden_customer_is_hidden_with_it(self):
		from crm.permissions.linked_records import get_enrichment_run_permission_query_conditions

		frappe.set_user(REP_A)
		cond = get_enrichment_run_permission_query_conditions(REP_A)
		frappe.set_user("Administrator")

		def visible(org):
			return frappe.db.sql(
				f"""select count(*) from (select 'CRM Organization' reference_doctype, %s reference_name) t
				where {cond.replace("`tabCRM Enrichment Run`.", "t.")}""",
				org,
			)[0][0]

		self.assertEqual(visible(self.org_b), 0)
		self.assertEqual(visible(self.org_a), 1)

	def test_a_public_event_at_a_hidden_customer_is_hidden_from_other_reps(self):
		def event(owner, org):
			doc = frappe.get_doc(
				{
					"doctype": "Event",
					"subject": "Site visit",
					"starts_on": frappe.utils.now_datetime(),
					"event_type": "Public",
					"event_participants": [
						{"reference_doctype": "CRM Organization", "reference_docname": org}
					],
				}
			).insert(ignore_permissions=True)
			frappe.db.set_value("Event", doc.name, "owner", owner)
			return doc.name

		at_b, at_a = event(REP_B, self.org_b), event(REP_A, self.org_a)
		frappe.set_user(REP_A)
		listed = set(frappe.get_list("Event", pluck="name", limit_page_length=0))
		self.assertNotIn(at_b, listed)
		self.assertIn(at_a, listed)

	def _event(self, owner, **fields):
		doc = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Site visit",
				"starts_on": frappe.utils.now_datetime(),
				"event_type": "Public",
				**fields,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.set_value("Event", doc.name, "owner", owner)
		return doc.name

	def events_for(self, user):
		frappe.set_user(user)
		try:
			return set(frappe.get_list("Event", pluck="name", limit_page_length=0))
		finally:
			frappe.set_user("Administrator")

	def test_saving_a_deal_contact_row_on_its_own_is_refused(self):
		"""A row saved directly skips the deal's validate, and the response carries
		the fetched name, email and mobile."""
		hidden = self._contact(self.org_b)
		deal = self.deal(self.org_a, REP_A)
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "CRM Contacts",
					"parent": deal,
					"parenttype": "CRM Deal",
					"parentfield": "contacts",
					"contact": hidden.name,
				}
			).insert()

	def test_a_rep_cannot_read_a_hidden_contact_through_an_event(self):
		"""An Event's save fills a participant's email in unchecked."""
		for doctype, name in (("Contact", self._contact(self.org_b).name), ("CRM Organization", self.org_b)):
			with self.subTest(doctype=doctype):
				frappe.set_user(REP_A)
				with self.assertRaises(frappe.PermissionError):
					frappe.get_doc(
						{
							"doctype": "Event",
							"subject": "Peek",
							"starts_on": frappe.utils.now_datetime(),
							"event_participants": [{"reference_doctype": doctype, "reference_docname": name}],
						}
					).insert()
				frappe.set_user("Administrator")

	def _forged(self, name, organization):
		"""What a request could send, had frappe's _action not been reserved."""
		from crm.permissions.document_guard import reserve_action

		reserve_action()
		return {"_action": "discard", "organization": organization, "doctype": "CRM Deal", "docname": name}

	def test_a_client_action_cannot_skip_the_customer_check(self):
		"""frappe does not reserve ``_action``: "discard" skipped validate, and with
		it every rule here."""
		name = self.deal(self.org_a, REP_A)
		forged = self._forged(name, self.org_b)
		frappe.set_user(REP_A)
		doc = frappe.get_doc("CRM Deal", name)
		doc.update(forged)
		self.assertFalse(doc.get("_action"))
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_bulk_update_cannot_keep_a_forged_write(self):
		"""It swallows exceptions, so refusing after the write would not hold."""
		from frappe.client import bulk_update

		name = self.deal(self.org_a, REP_A)
		forged = self._forged(name, self.org_b)
		frappe.set_user(REP_A)
		result = bulk_update(json.dumps([forged]))
		frappe.set_user("Administrator")
		self.assertEqual(len(result["failed_docs"]), 1)
		self.assertEqual(frappe.db.get_value("CRM Deal", name, "organization"), self.org_a)

	def test_a_single_cannot_skip_its_validate_either(self):
		from crm.permissions.document_guard import reserve_action

		reserve_action()
		doc = frappe.get_doc("FCRM Settings")
		doc.update({"_action": "x"})
		self.assertNotEqual(doc.get("_action"), "x")

	def test_the_action_is_reserved_in_every_process(self):
		"""Web and worker both: frappe's bulk routes apply client dicts in a job, and
		a worker never runs before_request."""
		for hook in ("before_request", "before_job"):
			self.assertIn("crm.permissions.document_guard.reserve_action", frappe.get_hooks(hook))
		# called as execute_job calls it: if this raised, every background job would fail
		frappe.call(
			frappe.get_attr("crm.permissions.document_guard.reserve_action"),
			method="a.job",
			kwargs={},
			transaction_type="job",
		)

	def test_frappes_event_digest_is_stopped(self):
		from crm.permissions.customers import stop_frappe_event_digest

		method = "frappe.desk.doctype.event.event.send_event_digest"
		frappe.db.set_value("Scheduled Job Type", {"method": method}, "stopped", 0)
		stop_frappe_event_digest()
		self.assertEqual(frappe.db.get_value("Scheduled Job Type", {"method": method}, "stopped"), 1)

	def test_saving_a_participant_row_on_its_own_is_refused(self):
		"""Written directly, the row looks stored when the event's own check runs."""
		hidden = self._contact(self.org_b)
		event = self._event(REP_A)
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Event Participants",
					"parent": event,
					"parenttype": "Event",
					"parentfield": "event_participants",
					"reference_doctype": "Contact",
					"reference_docname": hidden.name,
				}
			).insert()

	def test_a_stored_participant_with_no_email_is_still_checked(self):
		from unittest.mock import MagicMock

		from crm.permissions.customers import validate_event_participants

		hidden = self._contact(self.org_b)
		row = frappe._dict(reference_doctype="Contact", reference_docname=hidden.name, email=None)
		doc = MagicMock(event_participants=[row], flags=frappe._dict())
		doc.get_doc_before_save.return_value = frappe._dict(event_participants=[row])
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			validate_event_participants(doc)

	def test_the_calendar_feed_leaves_out_a_hidden_customers_events(self):
		"""frappe's get_events is raw SQL, so the row rules never reach it."""
		from crm.permissions.customers import get_events

		now = frappe.utils.now_datetime()
		fields = {"reference_doctype": "CRM Organization"}
		at_b = self._event(REP_B, starts_on=now, reference_docname=self.org_b, **fields)
		at_a = self._event(REP_A, starts_on=now, reference_docname=self.org_a, **fields)
		today = str(frappe.utils.getdate())
		frappe.set_user(REP_A)
		seen = {event.name for event in get_events(today, today)}
		self.assertNotIn(at_b, seen)
		self.assertIn(at_a, seen)

	def test_the_calendar_feed_is_overridden(self):
		self.assertEqual(
			frappe.get_hooks("override_whitelisted_methods")["frappe.desk.doctype.event.event.get_events"],
			["crm.permissions.customers.get_events"],
		)

	def test_a_deal_at_a_customer_gives_read_on_its_contacts_and_addresses_only(self):
		contact = self._contact(self.org_shared)
		self.assertTrue(has_contact_permission(contact, "read", REP_A))
		for ptype in ("write", "share", "delete"):
			with self.subTest(ptype=ptype):
				self.assertFalse(has_contact_permission(contact, ptype, REP_A))
		self.assertTrue(has_contact_permission(self._contact(self.org_a), "write", REP_A))

	def test_a_blank_contact_row_does_not_unhide_the_events_contacts(self):
		"""One NULL in the NOT over an IN would make every contact look visible."""
		hidden = self._contact(self.org_b)
		event = self._event(
			REP_B, event_participants=[{"reference_doctype": "Contact", "reference_docname": hidden.name}]
		)
		self.assertNotIn(event, self.events_for(REP_A))
		doc = frappe.get_doc("CRM Deal", self.deal(self.org_a, REP_A))
		doc.append("contacts", {"contact": None})
		doc.save(ignore_permissions=True)
		self.assertNotIn(event, self.events_for(REP_A))

	def test_an_event_added_from_a_hidden_customers_deal_is_hidden_too(self):
		deal = self.deal(self.org_b, REP_B)
		from_deal = self._event(REP_B, reference_doctype="CRM Deal", reference_docname=deal)
		on_org = self._event(REP_B, reference_doctype="CRM Organization", reference_docname=self.org_b)
		plain = self._event(REP_B)
		seen = self.events_for(REP_A)
		self.assertNotIn(from_deal, seen)
		self.assertNotIn(on_org, seen)
		self.assertIn(plain, seen, "an event naming no customer stays public")

	# --- reading a customer is not holding it ---------------------------------

	def test_a_deal_at_a_customer_lets_a_rep_read_it_but_not_edit_or_share_it(self):
		doc = frappe.get_doc("CRM Organization", self.org_shared)
		self.assertTrue(has_organization_permission(doc, "read", REP_A))
		for ptype in ("write", "share", "delete"):
			with self.subTest(ptype=ptype):
				self.assertFalse(has_organization_permission(doc, ptype, REP_A))

	def test_a_later_save_does_not_reclaim_a_customer_a_manager_cleared(self):
		name = self.deal(self.org_free, REP_A)
		frappe.db.set_value("CRM Organization", self.org_free, "account_owner", None)
		doc = frappe.get_doc("CRM Deal", name)
		doc.probability = 40
		doc.save(ignore_permissions=True)
		self.assertFalse(frappe.db.get_value("CRM Organization", self.org_free, "account_owner"))

	# --- managers and the switch ---------------------------------------------

	def _in_tree_manager(self):
		manager = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": MANAGER, "is_group": 1}).insert(
			ignore_permissions=True
		)
		frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": REP_A, "reports_to": manager.name}).insert(
			ignore_permissions=True
		)
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)

	def test_a_team_manager_can_only_move_a_customer_within_the_team(self):
		self._in_tree_manager()
		frappe.set_user(MANAGER)
		own_team = frappe.get_doc("CRM Organization", self.org_a)
		own_team.account_owner = REP_B
		with self.assertRaises(frappe.PermissionError):
			own_team.save()

	def test_a_manager_scoped_to_their_own_records_cannot_reassign(self):
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "Own records only")
		frappe.db.set_value("CRM Organization", self.org_b, "account_owner", MANAGER)
		frappe.set_user(MANAGER)
		doc = frappe.get_doc("CRM Organization", self.org_b)
		doc.account_owner = REP_A
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	def test_a_manager_scoped_to_their_own_records_sees_what_a_rep_sees(self):
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "Own records only")
		seen = self.visible_to(MANAGER)
		self.assertIn(self.org_free, seen)
		self.assertNotIn(self.org_b, seen)

	def test_a_guest_is_not_narrowed(self):
		from crm.permissions.customers import scope_applies

		self.assertFalse(scope_applies("Guest"))

	def test_a_manager_sees_every_customer_and_can_reassign_one(self):
		self.assertTrue({self.org_a, self.org_b, self.org_free} <= self.visible_to(MANAGER))
		self.assertEqual(get_organization_permission_query_conditions(MANAGER), "")
		frappe.set_user(MANAGER)
		doc = frappe.get_doc("CRM Organization", self.org_b)
		doc.account_owner = REP_A
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.get_value("CRM Organization", self.org_b, "account_owner"), REP_A)

	def test_all_customers_switches_the_rule_off(self):
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "All customers")
		self.assertIn(self.org_b, self.visible_to(REP_A))

	def test_an_unsaved_setting_scopes(self):
		"""The rule is on by default, on an upgraded site as on a new one."""
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", None)
		self.assertNotIn(self.org_b, self.visible_to(REP_A))


class TestCustomisedPermissions(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_cache(doctype="CRM Organization")

	def test_a_site_with_custom_permissions_gets_the_field_too(self):
		from crm.patches.v1_0.backfill_organization_account_owner import grant_on_customised_permissions

		frappe.db.delete("Custom DocPerm", {"parent": "CRM Organization"})
		grant_on_customised_permissions()
		self.assertFalse(
			frappe.db.exists("Custom DocPerm", {"parent": "CRM Organization"}),
			"a clean site must not gain Custom DocPerm: it freezes its permissions",
		)

		frappe.get_doc(
			{
				"doctype": "Custom DocPerm",
				"parent": "CRM Organization",
				"parenttype": "DocType",
				"parentfield": "permissions",
				"role": "Sales User",
				"read": 1,
			}
		).insert(ignore_permissions=True)
		grant_on_customised_permissions()
		grant_on_customised_permissions()
		self.assertEqual(frappe.db.count("Custom DocPerm", {"parent": "CRM Organization", "permlevel": 1}), 3)


class TestAccountOwnerBackfill(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(REP_A, "Sales User")
		make_user(REP_B, "Sales User")
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def tearDown(self):
		frappe.db.rollback()

	def test_the_rep_with_most_deals_owns_the_customer_and_admins_own_nothing(self):
		from crm.patches.v1_0.backfill_organization_account_owner import backfill

		def org():
			return (
				frappe.get_doc(
					{
						"doctype": "CRM Organization",
						"organization_name": f"Fill {frappe.generate_hash(length=6)}",
					}
				)
				.insert(ignore_permissions=True)
				.name
			)

		contested, admins_only = org(), org()
		for owner in (REP_A, REP_A, REP_B):
			frappe.get_doc(
				{
					"doctype": "CRM Deal",
					"organization": contested,
					"deal_owner": owner,
					"status": "Qualification",
				}
			).insert(ignore_permissions=True)
		frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": admins_only,
				"deal_owner": "Administrator",
				"status": "Qualification",
			}
		).insert(ignore_permissions=True)
		# the deals' on_update claim already ran; the backfill is for history that predates it
		frappe.db.sql(
			"update `tabCRM Organization` set account_owner=NULL where name in %s",
			((contested, admins_only),),
		)

		backfill()

		self.assertEqual(frappe.db.get_value("CRM Organization", contested, "account_owner"), REP_A)
		self.assertFalse(frappe.db.get_value("CRM Organization", admins_only, "account_owner"))
