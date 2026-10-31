"""One rep cannot see, or take, another rep's customers."""

import frappe
from frappe.tests import IntegrationTestCase

from crm.permissions.customers import (
	get_organization_permission_query_conditions,
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

	# --- managers and the switch ---------------------------------------------

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
