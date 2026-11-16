"""Attendees typed onto an event by address (crm.api.attendees).

A rep who meets another rep's customer must not give that person a second
Contact -- and must not learn, from anything the event shows them, that the
address belongs to somebody else's customer."""

import json
import threading

import frappe
from frappe.tests import IntegrationTestCase

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

	def test_an_unknown_address_makes_no_contact_and_waits(self):
		email = self.email("fresh")
		event = self.event_as(REP_A, email)
		self.assertEqual(contacts_with(email), set(), "a Contact was made for nobody's address")
		self.assertEqual(self.attendees(event["name"]), {email: None})

	def test_a_contact_saved_later_with_the_address_is_linked(self):
		email = self.email("later")
		event = self.event_as(REP_A, email)["name"]
		frappe.set_user(REP_B)
		later = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": "Later",
				"company_name": self.org_b,
				"email_ids": [{"email_id": email.upper(), "is_primary": 1}],
			}
		).insert()
		frappe.set_user("Administrator")
		self.assertEqual(self.attendees(event), {email: later.name})
		row = frappe.get_doc("Event", event).event_participants[0]
		self.assertEqual(row.reference_docname, "", "the event the rep reads is unchanged")

	def test_a_contact_the_rep_can_read_is_named_on_the_row(self):
		email = self.email("mine")
		mine = self.contact(self.org_a, email)
		event = self.event_as(REP_A, email)
		self.assertEqual(event["event_participants"][0]["reference_docname"], mine.name)
		self.assertEqual(self.attendees(event["name"]), {})

	def rep_view(self, email, event):
		"""Everything a rep can read that could tell the cases apart, with this
		case's own address and event name taken out."""
		from frappe.client import get as client_get
		from frappe.desk.form.load import get_versions

		def contacts_found(user):
			frappe.set_user(user)
			return frappe.get_list(
				"Contact", filters=[["Contact Email", "email_id", "=", email]], pluck="name"
			) + frappe.get_list("Contact", filters={"email_id": email}, pluck="name")

		frappe.set_user(REP_A)
		doc = frappe.get_doc("Event", event)
		doc.subject = "Meeting (moved)"
		doc.save()
		view = {
			"save": doc.as_dict(),
			"get": client_get("Event", event),
			"participants": frappe.get_list(
				"Event Participants", parent_doctype="Event", filters={"parent": event}, fields=["*"]
			),
			"versions": [json.loads(v.data) for v in get_versions(doc)],
			"contacts_rep": contacts_found(REP_A),
			"contacts_third_rep": contacts_found(REP_C),
		}
		for user in (REP_A, REP_C):
			frappe.set_user(user)
			view[f"event_seen_by_{user}"] = event in frappe.get_list(
				"Event", pluck="name", limit_page_length=0
			)
		frappe.set_user("Administrator")
		text = json.dumps(view, default=str, sort_keys=True)
		return text.replace(email.upper(), "<email>").replace(email, "<email>").replace(event, "<event>")

	def test_every_read_is_the_same_whether_a_hidden_contact_existed_or_not(self):
		import re

		hidden_email, fresh_email = self.email("hidden"), self.email("nobody")
		hidden = self.contact(self.org_b, hidden_email, first_name="Secret Buyer")
		hidden_event = self.event_as(REP_A, hidden_email)
		fresh_event = self.event_as(REP_A, fresh_email)

		def scrub(text):
			# row names, timestamps and version names differ from save to save
			text = re.sub(r'"(name|creation|modified|parent|docname)": "[^"]*"', r'"\1": "-"', text)
			return re.sub(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(\.\d+)?", "<ts>", text)

		self.assertEqual(
			scrub(
				json.dumps(hidden_event, default=str, sort_keys=True)
				.replace(hidden_email, "<email>")
				.replace(hidden_event["name"], "<event>")
			),
			scrub(
				json.dumps(fresh_event, default=str, sort_keys=True)
				.replace(fresh_email, "<email>")
				.replace(fresh_event["name"], "<event>")
			),
			"the save response",
		)
		hidden_view = self.rep_view(hidden_email, hidden_event["name"])
		fresh_view = self.rep_view(fresh_email, fresh_event["name"])
		self.assertEqual(scrub(hidden_view), scrub(fresh_view))
		for secret in (hidden.name, "Secret Buyer", self.org_b, REP_B):
			self.assertNotIn(secret, hidden_view)

	def test_a_rep_who_may_not_create_contacts_can_still_add_any_address(self):
		"""Nothing is created on their behalf, so the two cases cannot differ in
		whether the save is refused."""
		from unittest.mock import patch

		import frappe.permissions as perms

		original = perms.has_permission

		def no_contact_create(doctype, ptype="read", *args, **kwargs):
			if doctype == "Contact" and ptype == "create":
				return False
			return original(doctype, ptype, *args, **kwargs)

		hidden_email, fresh_email = self.email("nc-hidden"), self.email("nc-fresh")
		self.contact(self.org_b, hidden_email)
		with patch.object(perms, "has_permission", no_contact_create):
			hidden = self.event_as(REP_A, hidden_email)
			fresh = self.event_as(REP_A, fresh_email)
		self.assertTrue(hidden["name"] and fresh["name"])

	def test_nothing_the_rep_reads_names_the_hidden_contact(self):
		from frappe.client import get as client_get
		from frappe.desk.form.load import get_versions

		email = self.email("leak")
		hidden = self.contact(self.org_b, email, first_name="Secret Buyer")
		event = self.event_as(REP_A, email)["name"]

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

	def test_the_contacts_owner_has_the_event_on_their_contact(self):
		email = self.email("owner")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]
		self.assertEqual(self.attendees(event), {email: hidden.name})
		frappe.set_user(REP_B)
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

	def test_deleting_the_contact_leaves_the_attendee_waiting_and_the_event_drops_it(self):
		email = self.email("gone")
		hidden = self.contact(self.org_b, email)
		event = self.event_as(REP_A, email)["name"]
		frappe.delete_doc("Contact", hidden.name)
		self.assertEqual(self.attendees(event), {email: None})

		frappe.delete_doc("Event", event)
		self.assertEqual(self.attendees(event), {})


class TestAttendeeScopes(AttendeeCase):
	"""Who may read a CRM Event Attendee row, beyond reps (who may not at all)."""

	def row(self, company):
		email = self.email(f"scope-{frappe.scrub(company)[-6:]}")
		self.contact(company, email)
		# by a rep with no customers, so the contact is hidden and recorded apart
		event = self.event_as(REP_C, email)["name"]
		return frappe.get_doc("CRM Event Attendee", {"event": event})

	def test_an_out_of_tree_manager_scoped_to_own_records_reads_none_of_a_reps(self):
		from crm.permissions.customers import has_event_attendee_permission

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "Own records only")
		row = self.row(self.org_b)
		self.assertFalse(has_event_attendee_permission(row, "read", MANAGER))
		frappe.set_user(MANAGER)
		self.assertNotIn(row.name, frappe.get_list("CRM Event Attendee", pluck="name"))

	def test_an_in_tree_manager_reads_their_teams_only(self):
		from frappe.utils.nestedset import rebuild_tree

		from crm.permissions.customers import has_event_attendee_permission
		from crm.permissions.test_org_hierarchy import make_hierarchy_node

		mgr = make_hierarchy_node(MANAGER, is_group=1)
		make_hierarchy_node(REP_A, reports_to=mgr.name)
		rebuild_tree("CRM Sales Hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		theirs, not_theirs = self.row(self.org_a), self.row(self.org_b)
		self.assertTrue(has_event_attendee_permission(theirs, "read", MANAGER))
		self.assertFalse(has_event_attendee_permission(not_theirs, "read", MANAGER))
		frappe.set_user(MANAGER)
		listed = set(frappe.get_list("CRM Event Attendee", pluck="name"))
		self.assertIn(theirs.name, listed)
		self.assertNotIn(not_theirs.name, listed)


class TestConcurrentAttendees(IntegrationTestCase):
	def test_a_contact_saved_while_the_event_saves_is_not_left_waiting(self):
		"""Each in its own connection, as two web workers would be: whichever
		commits first, the attendee ends with the Contact."""
		email = f"race-{frappe.generate_hash(length=8)}@client.test"
		site, sites_path = frappe.local.site, frappe.local.sites_path
		barrier = threading.Barrier(2)
		events, contacts, errors = [], [], []

		def run(work):
			frappe.init(site, sites_path=sites_path)
			frappe.connect()
			try:
				frappe.set_user(REP_A)
				barrier.wait(timeout=30)
				work()
				frappe.db.commit()  # nosemgrep: frappe-manual-commit
			except Exception as e:
				errors.append(e)
			finally:
				frappe.destroy()

		def save_event():
			doc = frappe.get_doc(
				{
					"doctype": "Event",
					"subject": "Race",
					"starts_on": "2026-11-20 09:00:00",
					"event_participants": [{"email": email, "reference_doctype": "Contact"}],
				}
			).insert()
			events.append(doc.name)

		def save_contact():
			doc = frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": "Race",
					"email_ids": [{"email_id": email, "is_primary": 1}],
				}
			).insert()
			contacts.append(doc.name)

		# the race under test is the attendee's, not the naming series': two first
		# inserts of a series that has no row yet deadlock on it in frappe itself
		from crm.utils.autonomous import autonomous_db

		with autonomous_db() as db:
			db.sql("insert ignore into `tabSeries` (name, current) values ('EV', 0)")

		threads = [threading.Thread(target=run, args=(work,)) for work in (save_event, save_contact)]
		try:
			for thread in threads:
				thread.start()
			for thread in threads:
				thread.join(timeout=60)
			self.assertEqual(errors, [])
			with autonomous_db() as db:
				named = db.sql(
					"select reference_docname from `tabEvent Participants` where parent = %s", events[0]
				)[0][0]
				linked = db.sql("select contact from `tabCRM Event Attendee` where event = %s", events[0])
			# named on the row when the Contact was there first (it is the rep's own),
			# recorded off it otherwise -- never left waiting
			self.assertTrue(named == contacts[0] or [r[0] for r in linked] == [contacts[0]], (named, linked))
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
