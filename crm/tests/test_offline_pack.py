# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The field pack: what a rep's phone is allowed to carry off the network.

The pack is a second way out of the database for everything a rep can see, so
the tests that matter are the ones about what it leaves out: another rep's
customers and the people at them, closed deals, old history, and anyone
without a sales role.
"""

from __future__ import annotations

from datetime import timedelta

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.offline import HISTORY_DAYS, TEXT_LIMIT, get_pack, handshake
from crm.api.rep_plan import complete_item, save_plan
from crm.install import ensure_visit_event_category

REP = "pack-rep@crmtest.test"
OTHER = "pack-other@crmtest.test"
OUTSIDER = "pack-outsider@crmtest.test"


def make_user(email: str, role: str | None) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		if role:
			user.add_roles(role)


def this_monday() -> str:
	today = frappe.utils.getdate()
	return str(today - timedelta(days=today.weekday()))


class FieldPackTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_visit_event_category()
		make_user(REP, "Sales User")
		make_user(OTHER, "Sales User")
		make_user(OUTSIDER, None)
		# committed: each test rolls back, and the users must outlive the first
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		# pinned: the scoping under test is "a rep carries their own customers"
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 0)
		frappe.db.set_single_value("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers")
		self.mine = self.org("Mine", REP)
		self.theirs = self.org("Theirs", OTHER)
		self.addCleanup(frappe.set_user, "Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def org(self, label: str, owner: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Pack {label} {frappe.generate_hash(length=6)}",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", doc.name, "account_owner", owner)
		return doc.name

	def contact(self, first_name: str, organization: str) -> str:
		return (
			frappe.get_doc({"doctype": "Contact", "first_name": first_name, "company_name": organization})
			.insert(ignore_permissions=True)
			.name
		)

	def deal(self, organization: str, owner: str, status: str | None = None) -> str:
		doc = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": organization, "deal_owner": owner}
		).insert(ignore_permissions=True)
		if status:
			frappe.db.set_value("CRM Deal", doc.name, "status", status)
		return doc.name

	def pack(self, user: str = REP, **kwargs) -> dict:
		frappe.set_user(user)
		try:
			return get_pack(**kwargs)
		finally:
			frappe.set_user("Administrator")

	# --- what a rep carries ---------------------------------------------------------

	def test_a_rep_carries_their_own_customers_and_not_another_reps(self):
		names = {row["name"] for row in self.pack()["organizations"]}
		self.assertIn(self.mine, names)
		self.assertNotIn(self.theirs, names)

	def test_the_people_at_another_reps_customer_stay_off_the_phone(self):
		mine = self.contact("Packmine", self.mine)
		theirs = self.contact("Packtheirs", self.theirs)
		names = {row["name"] for row in self.pack()["contacts"]}
		self.assertIn(mine, names)
		self.assertNotIn(theirs, names)

	def test_open_deals_come_along_and_closed_ones_do_not(self):
		won = frappe.get_all("CRM Deal Status", filters={"type": "Won"}, pluck="name", limit=1)
		self.assertTrue(won, "the site has no Won status to test against")
		open_deal = self.deal(self.mine, REP)
		closed_deal = self.deal(self.mine, REP, won[0])
		foreign = self.deal(self.theirs, OTHER)
		names = {row["name"] for row in self.pack()["deals"]}
		self.assertIn(open_deal, names)
		self.assertNotIn(closed_deal, names)
		self.assertNotIn(foreign, names)

	def test_the_customers_address_travels_inside_its_row(self):
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": "Pack shaft 4",
				"address_type": "Office",
				"address_line1": "Shaft 4 Road",
				"city": "Rustenburg",
				"country": "South Africa",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", self.mine, "address", address.name)
		row = next(row for row in self.pack()["organizations"] if row["name"] == self.mine)
		self.assertEqual(row["address"]["city"], "Rustenburg")
		self.assertNotIn("name", row["address"])

	def test_three_weeks_of_the_callers_own_plan(self):
		frappe.set_user(REP)
		save_plan(
			this_monday(),
			[
				{
					"activity_type": "Visit",
					"planned_date": str(frappe.utils.getdate()),
					"organization": self.mine,
				}
			],
		)
		plans = self.pack()["plans"]
		self.assertEqual([plan["user"] for plan in plans], [REP, REP, REP])
		self.assertEqual(plans[1]["week_start"], this_monday())
		self.assertEqual(len(plans[1]["items"]), 1)
		self.assertEqual(self.pack(OTHER)["plans"][1]["items"], [])

	def test_history_is_what_the_caller_did_with_what_they_wrote(self):
		frappe.set_user(REP)
		plan = save_plan(
			this_monday(),
			[
				{
					"activity_type": "Visit",
					"planned_date": str(frappe.utils.getdate()),
					"organization": self.mine,
				}
			],
		)
		complete_item(plan["items"][0]["name"], "Replaced the 350mm knife gate")
		history = self.pack()["history"]
		self.assertEqual(
			[(row["organization"], row["status"], row["outcome"]) for row in history],
			[(self.mine, "Done", "Replaced the 350mm knife gate")],
		)
		self.assertEqual(self.pack(OTHER)["history"], [])

	def test_history_stops_at_the_window(self):
		frappe.set_user(REP)
		old = frappe.utils.getdate() - timedelta(days=HISTORY_DAYS + 20)
		monday = old - timedelta(days=old.weekday())
		plan = frappe.get_doc({"doctype": "CRM Rep Plan", "user": REP, "week_start": monday})
		plan.append(
			"items",
			{
				"activity_type": "Visit",
				"planned_date": old,
				"organization": self.mine,
				"status": "Done",
				"outcome": "Long ago",
			},
		)
		plan.insert(ignore_permissions=True)
		self.assertEqual(self.pack()["history"], [])

	def test_a_note_arrives_as_text_and_cut_to_length(self):
		deal = self.deal(self.mine, REP)
		frappe.set_user(REP)
		frappe.get_doc(
			{
				"doctype": "FCRM Note",
				"title": "Site contact",
				"content": "<p>Ask for <b>Thabo</b></p><script>alert(1)</script>" + "x" * (TEXT_LIMIT * 2),
				"reference_doctype": "CRM Deal",
				"reference_docname": deal,
			}
		).insert()
		note = next(row for row in self.pack()["notes"] if row["title"] == "Site contact")
		self.assertNotIn("<", note["content"])
		self.assertIn("Ask for Thabo", note["content"])
		self.assertLessEqual(len(note["content"]), TEXT_LIMIT)

	def test_only_the_callers_open_tasks(self):
		def task(title, assigned_to, status="Todo"):
			return (
				frappe.get_doc(
					{"doctype": "CRM Task", "title": title, "assigned_to": assigned_to, "status": status}
				)
				.insert(ignore_permissions=True)
				.name
			)

		mine = task("Pack mine", REP)
		task("Pack theirs", OTHER)
		titles = {row["title"] for row in self.pack()["tasks"]}
		self.assertIn("Pack mine", titles)
		self.assertNotIn("Pack theirs", titles)
		frappe.db.set_value("CRM Task", mine, "status", "Done")
		self.assertNotIn("Pack mine", {row["title"] for row in self.pack()["tasks"]})

	# --- the envelope ---------------------------------------------------------------

	def test_a_pack_already_held_is_not_sent_again(self):
		first = self.pack()
		self.assertFalse(first["unchanged"])
		again = self.pack(known_hash=first["hash"])
		self.assertTrue(again["unchanged"])
		self.assertNotIn("organizations", again)
		self.assertEqual(again["hash"], first["hash"])

	def test_a_change_moves_the_hash(self):
		first = self.pack()
		self.org("Newly mine", REP)
		again = self.pack(known_hash=first["hash"])
		self.assertFalse(again["unchanged"])
		self.assertNotEqual(again["hash"], first["hash"])

	def test_the_pack_names_its_owner_and_its_shelf_life(self):
		pack = self.pack()
		self.assertEqual(pack["user"], REP)
		self.assertEqual(pack["today"], str(frappe.utils.getdate()))
		self.assertGreater(pack["max_age_days"], 0)
		self.assertIn("Visit", pack["rules"]["activity_types"])

	# --- who may ask ----------------------------------------------------------------

	def test_someone_without_a_sales_role_gets_no_pack(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			get_pack()

	def test_someone_without_a_sales_role_gets_no_token(self):
		frappe.set_user(OUTSIDER)
		with self.assertRaises(frappe.PermissionError):
			handshake()

	def test_the_handshake_returns_this_sessions_token_and_the_clock(self):
		frappe.set_user(REP)
		out = handshake()
		self.assertEqual(out["user"], REP)
		self.assertEqual(out["csrf_token"], frappe.sessions.get_csrf_token())
		self.assertAlmostEqual(out["server_epoch"], frappe.utils.now_datetime().timestamp(), delta=86400)
