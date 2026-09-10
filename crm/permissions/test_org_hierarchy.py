# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils.nestedset import rebuild_tree

from crm.permissions.org_hierarchy import (
	get_lead_permission_query_conditions,
	has_deal_permission,
	has_lead_permission,
	hierarchy_enabled,
)


class TestOrgHierarchy(IntegrationTestCase):
	"""
	Hierarchy structure used in tests:
	  manager@hier.test  (root)
	  ├── rep1@hier.test
	  └── rep2@hier.test
	  outsider@hier.test  (not in the hierarchy)
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# Create test users
		make_user("manager@hier.test", roles=["Sales Manager"])
		make_user("rep1@hier.test", roles=["Sales User"])
		make_user("rep2@hier.test", roles=["Sales User"])
		make_user("outsider@hier.test", roles=["Sales User"])

		# Build hierarchy
		mgr = make_hierarchy_node("manager@hier.test", is_group=1)
		make_hierarchy_node("rep1@hier.test", reports_to=mgr.name)
		make_hierarchy_node("rep2@hier.test", reports_to=mgr.name)
		rebuild_tree("CRM Sales Hierarchy")

		settings = frappe.get_single("FCRM Settings")
		settings.enable_sales_hierarchy = 1
		settings.save(ignore_permissions=True)

	@classmethod
	def tearDownClass(cls):
		super().tearDownClass()

	def setUp(self):
		frappe.db.savepoint("test_org_hierarchy")

	def tearDown(self):
		frappe.db.rollback(save_point="test_org_hierarchy")

	# ------------------------------------------------------------------
	# hierarchy_enabled
	# ------------------------------------------------------------------

	def test_hierarchy_is_enabled(self):
		self.assertTrue(hierarchy_enabled())

	# ------------------------------------------------------------------
	# Lead permissions -- owner-based
	# ------------------------------------------------------------------

	def test_owner_can_read_own_lead(self):
		lead = make_lead("rep1@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "rep1@hier.test"))

	def test_manager_can_read_direct_report_lead(self):
		lead = make_lead("rep1@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "manager@hier.test"))

	def test_manager_can_read_any_report_lead(self):
		lead = make_lead("rep2@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "manager@hier.test"))

	def test_sibling_cannot_read_peer_lead(self):
		lead = make_lead("rep1@hier.test")
		self.assertFalse(has_lead_permission(lead, "read", "rep2@hier.test"))

	def test_outsider_cannot_read_team_lead(self):
		lead = make_lead("rep1@hier.test")
		self.assertFalse(has_lead_permission(lead, "read", "outsider@hier.test"))

	def test_administrator_always_has_permission(self):
		lead = make_lead("rep1@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "Administrator"))

	def test_sales_user_can_create_lead(self):
		new_lead = frappe.get_doc({"doctype": "CRM Lead", "lead_owner": "rep1@hier.test"})
		self.assertTrue(has_lead_permission(new_lead, "create", "rep1@hier.test"))

	# ------------------------------------------------------------------
	# Lead permissions -- ToDo-based
	# ------------------------------------------------------------------

	def test_direct_assignee_can_read_lead(self):
		lead = make_lead("rep1@hier.test")
		assign_todo("CRM Lead", lead.name, "outsider@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "outsider@hier.test"))

	def test_cancelled_todo_does_not_grant_access(self):
		lead = make_lead("rep1@hier.test")
		assign_todo("CRM Lead", lead.name, "outsider@hier.test", status="Cancelled")
		self.assertFalse(has_lead_permission(lead, "read", "outsider@hier.test"))

	def test_manager_can_read_lead_assigned_to_report(self):
		lead = make_lead("outsider@hier.test")
		assign_todo("CRM Lead", lead.name, "rep1@hier.test")
		self.assertTrue(has_lead_permission(lead, "read", "manager@hier.test"))

	# ------------------------------------------------------------------
	# Deal permissions
	# ------------------------------------------------------------------

	def test_manager_can_read_report_deal(self):
		deal = make_deal("rep2@hier.test")
		self.assertTrue(has_deal_permission(deal, "read", "manager@hier.test"))

	def test_peer_cannot_read_sibling_deal(self):
		deal = make_deal("rep2@hier.test")
		self.assertFalse(has_deal_permission(deal, "read", "rep1@hier.test"))

	# ------------------------------------------------------------------
	# Permission query conditions
	# ------------------------------------------------------------------

	def test_query_conditions_empty_for_administrator(self):
		self.assertFalse(get_lead_permission_query_conditions("Administrator"))

	def test_query_conditions_non_empty_for_regular_user(self):
		self.assertTrue(get_lead_permission_query_conditions("rep1@hier.test"))

	def test_report_with_child_table_field_does_not_raise(self):
		make_lead("rep1@hier.test")
		self.assertTrue(get_lead_permission_query_conditions("rep1@hier.test"))
		frappe.set_user("rep1@hier.test")
		try:
			frappe.get_list(
				"CRM Lead",
				fields=["name", "`tabCRM Products`.`amount`"],
				limit_page_length=5,
			)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------
	# Hierarchy disabled
	# ------------------------------------------------------------------

	def test_hierarchy_disabled_sales_user_still_restricted_to_own(self):
		# "Sees everything" is the "All records" boundary. A fresh install (CI) sets
		# the out-of-tree manager to "Own records only" (crm.install), so the test
		# has to say which boundary it is asserting rather than inherit the site's.
		saved_scope = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.addCleanup(
			frappe.db.set_single_value,
			"CRM Access Settings",
			"manager_outside_hierarchy",
			saved_scope or "All records",
		)
		settings = frappe.get_single("FCRM Settings")
		settings.enable_sales_hierarchy = 0
		settings.save(ignore_permissions=True)
		try:
			lead = make_lead("rep1@hier.test")
			# Sales User default: cannot read another user's lead even when feature is off
			self.assertFalse(has_lead_permission(lead, "read", "outsider@hier.test"))
			# Sales Manager at the "All records" boundary: sees everything when feature is off
			self.assertTrue(has_lead_permission(lead, "read", "manager@hier.test"))
		finally:
			settings.enable_sales_hierarchy = 1
			settings.save(ignore_permissions=True)

	def test_query_conditions_when_hierarchy_disabled(self):
		# "Sees everything" is the "All records" boundary. A fresh install (CI) sets
		# the out-of-tree manager to "Own records only" (crm.install), so the test
		# has to say which boundary it is asserting rather than inherit the site's.
		saved_scope = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.addCleanup(
			frappe.db.set_single_value,
			"CRM Access Settings",
			"manager_outside_hierarchy",
			saved_scope or "All records",
		)
		settings = frappe.get_single("FCRM Settings")
		settings.enable_sales_hierarchy = 0
		settings.save(ignore_permissions=True)
		try:
			# Sales User still gets a filter (own + assigned)
			self.assertTrue(get_lead_permission_query_conditions("rep1@hier.test"))
			# Sales Manager at the "All records" boundary has no filter (sees everything)
			self.assertFalse(get_lead_permission_query_conditions("manager@hier.test"))
		finally:
			settings.enable_sales_hierarchy = 1
			settings.save(ignore_permissions=True)


def make_user(email, roles=None):
	if frappe.db.exists("User", email):
		return frappe.get_doc("User", email)
	u = frappe.get_doc(
		{
			"doctype": "User",
			"email": email,
			"first_name": email.split("@")[0],
			"send_welcome_email": 0,
		}
	).insert(ignore_permissions=True)
	for role in roles or []:
		u.add_roles(role)
	return u


def make_hierarchy_node(user, reports_to=None, is_group=0):
	existing = frappe.db.get_value("CRM Sales Hierarchy", {"user": user}, "name")
	if existing:
		return frappe.get_doc("CRM Sales Hierarchy", existing)
	return frappe.get_doc(
		{
			"doctype": "CRM Sales Hierarchy",
			"user": user,
			"reports_to": reports_to,
			"is_group": is_group,
		}
	).insert(ignore_permissions=True)


def make_lead(owner_email):
	doc = frappe.get_doc({"doctype": "CRM Lead", "lead_owner": owner_email, "first_name": "Test"})
	doc.flags.ignore_mandatory = True
	return doc.insert(ignore_permissions=True)


def make_deal(owner_email):
	doc = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": owner_email, "organization": "Test Org"})
	doc.flags.ignore_mandatory = True
	doc.flags.ignore_links = True
	return doc.insert(ignore_permissions=True)


def assign_todo(doctype, docname, allocated_to, status="Open"):
	return frappe.get_doc(
		{
			"doctype": "ToDo",
			"reference_type": doctype,
			"reference_name": docname,
			"allocated_to": allocated_to,
			"status": status,
			"description": f"Test assignment to {allocated_to}",
		}
	).insert(ignore_permissions=True)


class ManagerOutsideHierarchyTest(IntegrationTestCase):
	"""The out-of-tree manager used to be hardcoded to "sees everything".

	That is a fair escape hatch for a manager who runs the whole book, and it is
	also what every manager got on a site whose tree nobody had built -- so
	defaulting the hierarchy on, alone, just moved the problem. It is now a
	setting, and this is the test that it is actually read.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		email = "outside-manager@crmtest.test"
		if not frappe.db.exists("User", email):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": email,
					"first_name": "Outside Manager",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True).add_roles("Sales Manager")
		self.manager = email

		self.saved_hierarchy = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.saved_scope = frappe.db.get_single_value("CRM Access Settings", "manager_outside_hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.set_user("Administrator")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", self.saved_hierarchy or 0)
		frappe.db.set_single_value(
			"CRM Access Settings", "manager_outside_hierarchy", self.saved_scope or "All records"
		)

	def test_all_records_leaves_an_out_of_tree_manager_unrestricted(self):
		from crm.permissions.org_hierarchy import get_deal_permission_query_conditions

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.assertEqual(get_deal_permission_query_conditions(self.manager), "")

	def test_own_records_only_scopes_an_out_of_tree_manager(self):
		from crm.permissions.org_hierarchy import get_deal_permission_query_conditions

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "Own records only")
		condition = get_deal_permission_query_conditions(self.manager)
		self.assertNotEqual(condition, "")
		self.assertIn(self.manager, condition)

	def test_the_setting_also_governs_direct_deal_access(self):
		"""get_deal_permission_query_conditions governs list and report views; a
		deal opened directly by name goes through has_deal_permission instead.
		Both anchors read the same setting, so they must scope the same way -- a
		manager who cannot list a deal but can still open it by name/URL is a
		worse failure than an inconsistent list."""
		make_user("someone-else@crmtest.test")
		deal = make_deal("someone-else@crmtest.test")

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "All records")
		self.assertTrue(has_deal_permission(deal, "read", self.manager))

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", "Own records only")
		self.assertFalse(has_deal_permission(deal, "read", self.manager))

	def test_an_unsaved_setting_reads_as_all_records(self):
		"""get_single_value casts a Single that was never saved to the fieldtype's
		zero value -- "" for this Select field, not None -- which is falsy, so an
		existing site upgrading into this feature must not change behaviour."""
		from crm.api.access import manager_outside_hierarchy_sees_all

		frappe.db.set_single_value("CRM Access Settings", "manager_outside_hierarchy", None)
		self.assertTrue(manager_outside_hierarchy_sees_all())
