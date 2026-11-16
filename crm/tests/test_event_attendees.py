"""Attendees typed onto an event by address (crm.api.attendees).

A rep who meets another rep's customer must not give that person a second
Contact -- and must not learn, from anything the event shows them, that the
address belongs to somebody else's customer."""

import json
import threading

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.attendees import get_contact_events

REP_A = "att-rep-a@scope.test"
REP_B = "att-rep-b@scope.test"
REP_C = "att-rep-c@scope.test"
MANAGER = "att-manager@scope.test"


def make_user(email, role):
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(role)


def contacts_with(email):
	return set(
		frappe.db.sql_list(
			"""select parent from `tabContact Email` where parenttype = 'Contact'
			and lower(trim(email_id)) = %s""",
			email.strip().lower(),
		)
	)


class AttendeeCase(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		make_user(REP_A, "Sales User")
		make_user(REP_B, "Sales User")
		make_user(REP_C, "Sales User")
		make_user(MANAGER, "Sales Manager")
		# committed: each test rolls back, and the users must outlive the first
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.org_a = self.org("A", REP_A)
		self.org_b = self.org("B", REP_B)
		self.tag = frappe.generate_hash(length=8)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def org(self, label, owner):
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Att {label} {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", doc.name, "account_owner", owner)
		return doc.name

	def email(self, local):
		return f"{local}-{self.tag}@client.test"

	def contact(self, company, *emails, first_name="Hidden Person"):
		return frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"company_name": company,
				"email_ids": [
					{"email_id": e, "is_primary": 1 if i == 0 else 0} for i, e in enumerate(emails)
				],
			}
		).insert(ignore_permissions=True)

	def event_as(self, user, *emails, **fields):
		"""Inserted the way the calendar inserts it, as ``user``; returns the
		response frappe.client.insert sends back."""
		from frappe.client import insert

		frappe.set_user(user)
		try:
			return insert(
				{
					"doctype": "Event",
					"subject": "Meeting",
					"starts_on": "2026-11-20 09:00:00",
					"event_type": "Public",
					"event_participants": [
						{"email": e, "reference_doctype": "Contact", "reference_docname": ""} for e in emails
					],
					**fields,
				}
			)
		finally:
			frappe.set_user("Administrator")

	def attendees(self, event):
		return {
			r.email: r.contact
			for r in frappe.get_all(
				"CRM Event Attendee", filters={"event": event}, fields=["email", "contact"]
			)
		}


class TestTypedAttendees(AttendeeCase):
	def test_another_reps_customers_contact_is_linked_not_duplicated(self):
		email = self.email("buyer")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, f"  {email.upper()} ")

		self.assertEqual(contacts_with(email), {hidden.name}, "a second Contact was made for the person")
		self.assertEqual(self.attendees(event["name"]), {email: hidden.name})
		row = event["event_participants"][0]
		self.assertEqual((row["reference_doctype"], row["reference_docname"]), ("Contact", ""))
		self.assertEqual(row["email"], email.upper(), "kept as typed, trimmed")

	def test_a_secondary_address_finds_the_contact_too(self):
		primary, second = self.email("main"), self.email("second")
		hidden = self.contact(self.org_b, primary, second)
		event = self.event_as(REP_A, second)
		self.assertEqual(self.attendees(event["name"]), {second: hidden.name})
		self.assertEqual(contacts_with(second), {hidden.name})

	def test_an_unknown_address_gets_one_contact_of_the_reps_own(self):
		email = self.email("fresh")
		event = self.event_as(REP_A, email)
		(created,) = contacts_with(email)
		self.assertEqual(frappe.db.get_value("Contact", created, "owner"), REP_A)
		self.assertEqual(self.attendees(event["name"]), {email: created})

	def test_a_contact_the_rep_can_read_is_named_on_the_row(self):
		email = self.email("mine")
		mine = self.contact(self.org_a, email)
		event = self.event_as(REP_A, email)
		self.assertEqual(event["event_participants"][0]["reference_docname"], mine.name)
		self.assertEqual(self.attendees(event["name"]), {})

	def test_the_response_is_the_same_whether_a_hidden_contact_existed_or_not(self):
		hidden_email, fresh_email = self.email("hidden"), self.email("nobody")
		self.contact(self.org_b, hidden_email)
		hidden = self.event_as(REP_A, hidden_email)
		fresh = self.event_as(REP_A, fresh_email)

		varying = {"name", "creation", "modified", "email", "parent"}

		def shape(doc):
			return {
				**{k: v for k, v in doc.items() if k not in varying and k != "event_participants"},
				"event_participants": [
					{k: v for k, v in row.items() if k not in varying} for row in doc["event_participants"]
				],
			}

		self.assertEqual(set(hidden), set(fresh))
		self.assertEqual(
			[set(r) for r in hidden["event_participants"]], [set(r) for r in fresh["event_participants"]]
		)
		self.assertEqual(shape(hidden), shape(fresh))

	def test_nothing_the_rep_reads_names_the_hidden_contact(self):
		from frappe.client import get as client_get
		from frappe.desk.form.load import get_versions

		email = self.email("leak")
		hidden = self.contact(self.org_b, email, first_name="Secret Buyer")
		event = self.event_as(REP_A, email)["name"]

		# a later save, with the rows as the rep reads them back
		frappe.set_user(REP_A)
		doc = frappe.get_doc("Event", event)
		doc.subject = "Meeting (moved)"
		doc.save()
		reads = {
			"save": doc.as_dict(),
			"get": client_get("Event", event),
			"participants": frappe.get_list(
				"Event Participants",
				parent_doctype="Event",
				filters={"parent": event},
				fields=["*"],
			),
			"joined": frappe.get_list(
				"Event",
				filters={"name": event},
				fields=["name", "`tabEvent Participants`.reference_docname"],
			),
			"versions": get_versions(doc),
		}
		probe = frappe.get_list(
			"Event",
			filters=[["Event Participants", "reference_docname", "like", "Secret%"]],
			pluck="name",
		)
		frappe.set_user("Administrator")

		dumped = json.dumps(reads, default=str)
		for secret in (hidden.name, "Secret Buyer", self.org_b, REP_B):
			self.assertNotIn(secret, dumped)
		self.assertEqual(probe, [], "a filter on the row answers whose contact it is")
		self.assertEqual(contacts_with(email), {hidden.name}, "the save made a second Contact")
		self.assertFalse(
			frappe.db.exists(
				"Communication Link",
				{"link_doctype": "Contact", "link_name": hidden.name, "parenttype": "Communication"},
			),
			"a timeline Communication names the hidden contact",
		)

	def test_a_rep_cannot_read_the_attendee_rows(self):
		email = self.email("rows")
		self.contact(self.org_b, email)
		self.event_as(REP_A, email)
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("CRM Event Attendee", fields=["contact"])

	def test_a_rep_still_cannot_attach_a_hidden_contact_by_name(self):
		hidden = self.contact(self.org_b, self.email("byname"))
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{
					"doctype": "Event",
					"subject": "Meeting",
					"starts_on": "2026-11-20 09:00:00",
					"event_participants": [
						{"reference_doctype": "Contact", "reference_docname": hidden.name}
					],
				}
			).insert()

	def test_the_contacts_owner_sees_the_event_on_their_contact(self):
		email = self.email("owner")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]

		frappe.set_user(REP_B)
		self.assertIn(event, [e.name for e in get_contact_events(hidden.name)])
		frappe.set_user(REP_A)
		with self.assertRaises(frappe.PermissionError):
			get_contact_events(hidden.name)
		with self.assertRaises(frappe.PermissionError):
			get_contact_events("No Such Contact")

	def test_a_third_rep_does_not_see_the_event(self):
		email = self.email("third")
		self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]
		frappe.set_user(REP_C)
		self.assertNotIn(event, frappe.get_list("Event", pluck="name", limit_page_length=0))
		frappe.set_user(REP_A)
		self.assertIn(event, frappe.get_list("Event", pluck="name", limit_page_length=0))

	def test_saving_again_keeps_the_link_and_removing_the_attendee_drops_it(self):
		email = self.email("again")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]

		frappe.set_user(REP_A)
		doc = frappe.get_doc("Event", event)
		doc.append("event_participants", {"email": self.email("second"), "reference_doctype": "Contact"})
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(self.attendees(event)[email], hidden.name)
		self.assertEqual(contacts_with(email), {hidden.name})

		frappe.set_user(REP_A)
		doc = frappe.get_doc("Event", event)
		doc.event_participants = [r for r in doc.event_participants if r.email != email]
		doc.save()
		frappe.set_user("Administrator")
		self.assertNotIn(email, self.attendees(event))

	def test_deleting_the_event_or_the_contact_drops_the_row(self):
		email = self.email("gone")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]
		frappe.delete_doc("Contact", hidden.name)
		self.assertEqual(self.attendees(event), {})

		other = self.email("gone2")
		self.contact(self.org_b, other)
		event = self.event_as(REP_A, other)["name"]
		frappe.delete_doc("Event", event)
		self.assertEqual(self.attendees(event), {})


class TestConcurrentAttendees(IntegrationTestCase):
	def test_two_saves_adding_the_same_new_address_make_one_contact(self):
		"""Each in its own connection, as two web workers would be."""
		email = f"race-{frappe.generate_hash(length=8)}@client.test"
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		events, errors = [], []

		def save():
			frappe.init(site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user("Administrator")
				doc = frappe.get_doc(
					{
						"doctype": "Event",
						"subject": "Race",
						"starts_on": "2026-11-20 09:00:00",
						"event_participants": [{"email": email, "reference_doctype": "Contact"}],
					}
				)
				barrier.wait(timeout=30)
				doc.insert()
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
				events.append(doc.name)
			except Exception as e:
				errors.append(e)
			finally:
				frappe.destroy()

		# the race under test is the Contact's, not the naming series': two first
		# inserts of a series that has no row yet deadlock on it in frappe itself
		from crm.utils.autonomous import autonomous_db

		with autonomous_db() as db:
			db.sql("insert ignore into `tabSeries` (name, current) values ('EV', 0)")

		threads = [threading.Thread(target=save) for _ in range(2)]
		try:
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=60)
			self.assertEqual(errors, [])
			with autonomous_db() as db:
				made = db.sql(
					"select parent from `tabContact Email` where email_id = %s and parenttype = 'Contact'",
					email,
				)
				linked = db.sql(
					"select distinct contact from `tabCRM Event Attendee` where email = %s", email
				)
			self.assertEqual(len(made), 1, "two Contacts for one new address")
			self.assertEqual({r[0] for r in linked}, {made[0][0]})
		finally:
			self._purge(email, events)

	def _purge(self, email, events):
		"""What the threads committed, through a connection of its own: a commit
		here would also commit this test's transaction."""
		from crm.utils.autonomous import autonomous_db

		with autonomous_db() as db:
			contacts = [
				r[0] for r in db.sql("select parent from `tabContact Email` where email_id = %s", email)
			]
			for table, column, values in (
				("Contact Email", "parent", contacts),
				("Contact", "name", contacts),
				("Version", "docname", contacts + events),
				("Event Participants", "parent", events),
				("Event", "name", events),
			):
				if values:
					db.sql(f"delete from `tab{table}` where {column} in %(v)s", {"v": tuple(values)})
			db.sql("delete from `tabCRM Event Attendee` where email = %s", email)
