# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""An attachment is listed only to those who can see what it is attached to.

frappe lists a private File to anyone holding read on the *doctype* it is
attached to, and every rep holds read on CRM Deal, CRM Lead, CRM Organization
and Contact. Opening the file was already refused -- frappe's File check follows
the attached record -- but ``frappe.client.get_list("File")`` named it: the file
name, its size, who uploaded it and which record it hangs off. The scoping had
been added for WhatsApp Message alone.

  file-manager  (in the tree, over file-owner)
  file-other    (a rep on nobody's team)
  file-outside  (a Sales Manager outside the tree, at "All records")
  file-sysadmin (System Manager)
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

OWNER = "file-owner@crmtest.test"
OTHER = "file-other@crmtest.test"
TEAM_MANAGER = "file-manager@crmtest.test"
OUTSIDE_MANAGER = "file-outside@crmtest.test"
SYSADMIN = "file-sysadmin@crmtest.test"


def ensure_user(email: str, name: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)


class FileRowScopingTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		ensure_user(OWNER, "File Owner", "Sales User")
		ensure_user(OTHER, "File Other", "Sales User")
		ensure_user(TEAM_MANAGER, "File Manager", "Sales Manager")
		ensure_user(OUTSIDE_MANAGER, "File Outside", "Sales Manager")
		ensure_user(SYSADMIN, "File Sysadmin", "System Manager", "Sales User")

		# say which boundaries this asserts rather than inherit the shared site's
		for doctype, field, value in (
			("CRM Access Settings", "manager_outside_hierarchy", "All records"),
			("CRM Access Settings", "rep_customer_scope", "Own and unclaimed customers"),
			("FCRM Settings", "enable_sales_hierarchy", 1),
		):
			saved = frappe.db.get_single_value(doctype, field)
			frappe.db.set_single_value(doctype, field, value)
			self.addCleanup(frappe.db.set_single_value, doctype, field, saved or value)
		people = [OWNER, OTHER, TEAM_MANAGER, OUTSIDE_MANAGER, SYSADMIN]
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", people)})
		self.addCleanup(frappe.db.delete, "CRM Sales Hierarchy", {"user": ("in", people)})
		top = self.make({"doctype": "CRM Sales Hierarchy", "user": TEAM_MANAGER})
		self.make({"doctype": "CRM Sales Hierarchy", "user": OWNER, "reports_to": top.name})

		org = self.make(
			{"doctype": "CRM Organization", "organization_name": f"File Org {frappe.generate_hash(length=6)}"}
		)
		frappe.db.set_value("CRM Organization", org.name, "account_owner", OWNER)
		deal = self.make({"doctype": "CRM Deal", "organization": org.name, "deal_owner": OWNER})
		lead = self.make({"doctype": "CRM Lead", "first_name": "File", "lead_owner": OWNER, "status": "New"})
		contact = self.make({"doctype": "Contact", "first_name": "File", "company_name": org.name})
		on_deal = {"reference_doctype": "CRM Deal", "reference_docname": deal.name}
		note = self.make({"doctype": "FCRM Note", "title": "Pricing", **on_deal})
		task = self.make(
			{
				"doctype": "CRM Task",
				"title": "Send quote",
				"status": "Backlog",
				"assigned_to": OWNER,
				**on_deal,
			}
		)
		self.deal, self.lead = deal, lead
		#: by the doctype each is attached to
		self.files = {
			doc.doctype: self.attach(f"Quote_{doc.doctype.replace(' ', '_')}_R2.5M.txt", doc)
			for doc in (deal, lead, org, contact, note, task)
		}

	def make(self, payload: dict):
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		self.addCleanup(
			lambda dt=doc.doctype, dn=doc.name: (
				frappe.db.exists(dt, dn) and frappe.delete_doc(dt, dn, force=True, ignore_permissions=True)
			)
		)
		return doc

	def attach(self, file_name: str, doc=None, is_private: int = 1, user: str = "Administrator") -> str:
		frappe.set_user(user)
		try:
			return self.make(
				{
					"doctype": "File",
					"file_name": file_name,
					# distinct content: frappe refuses the same file twice on one record
					"content": f"{file_name} {frappe.generate_hash(length=8)}",
					"is_private": is_private,
					"attached_to_doctype": doc.doctype if doc else None,
					"attached_to_name": doc.name if doc else None,
				}
			).name
		finally:
			frappe.set_user("Administrator")

	def listed_to(self, user: str, **filters) -> set[str]:
		frappe.set_user(user)
		try:
			return set(frappe.get_list("File", filters=filters, pluck="name", limit_page_length=0))
		finally:
			frappe.set_user("Administrator")

	def opens_for(self, user: str, file: str) -> bool:
		return bool(frappe.get_doc("File", file).has_permission("read", user=user))

	# --- the leak -----------------------------------------------------------

	def test_a_rep_cannot_list_the_attachments_of_records_they_cannot_see(self):
		listed = self.listed_to(OTHER)
		for doctype, file in self.files.items():
			with self.subTest(attached_to=doctype):
				self.assertNotIn(file, listed)
				self.assertFalse(self.opens_for(OTHER, file))

	def test_asking_for_a_hidden_deals_attachments_by_name_returns_nothing(self):
		"""The request from the finding: the filter names the deal outright."""
		self.assertEqual(
			self.listed_to(OTHER, attached_to_doctype="CRM Deal", attached_to_name=self.deal.name), set()
		)

	def test_a_public_attachment_on_a_hidden_record_is_not_listed_either(self):
		"""Public means the URL needs no login, not that the list should say which
		deal it is on and what it is called."""
		public = self.attach("Public_brochure_for_the_deal.txt", self.deal, is_private=0)
		self.assertNotIn(public, self.listed_to(OTHER))
		self.assertIn(public, self.listed_to(OWNER))

	def test_every_scoped_doctype_is_covered(self):
		"""The WhatsApp fix closed one parent doctype and left its siblings. The
		clause is built from the hooks, so a doctype scoped later is covered too."""
		from crm import hooks
		from crm.permissions.linked_records import OPTIONAL_DOCTYPES, get_file_permission_query_conditions

		conditions = get_file_permission_query_conditions(OTHER)
		for doctype in hooks.permission_query_conditions:
			if doctype == "File" or (
				doctype in OPTIONAL_DOCTYPES and not frappe.db.exists("DocType", doctype)
			):
				continue
			with self.subTest(doctype=doctype):
				self.assertIn(f"!= '{doctype}'", conditions)

	# --- what must still be listed ------------------------------------------

	def assert_lists_all(self, user: str):
		listed = self.listed_to(user)
		for doctype, file in self.files.items():
			with self.subTest(user=user, attached_to=doctype):
				self.assertIn(file, listed)
				self.assertTrue(self.opens_for(user, file))

	def test_the_owner_lists_the_attachments_on_their_records(self):
		self.assert_lists_all(OWNER)
		self.assertEqual(
			self.listed_to(OWNER, attached_to_doctype="CRM Deal", attached_to_name=self.deal.name),
			{self.files["CRM Deal"]},
		)

	def test_the_team_manager_lists_the_teams_attachments(self):
		self.assert_lists_all(TEAM_MANAGER)

	def assert_records_unscoped(self, user: str):
		"""No clause for a record doctype. What is each user's own -- their
		notifications, their saved views -- stays theirs for a manager too."""
		from crm.permissions.linked_records import get_file_permission_query_conditions

		conditions = get_file_permission_query_conditions(user)
		for doctype in self.files:
			with self.subTest(user=user, doctype=doctype):
				self.assertNotIn(f"!= '{doctype}'", conditions)

	def test_a_manager_outside_the_tree_lists_everything(self):
		self.assert_records_unscoped(OUTSIDE_MANAGER)
		self.assert_lists_all(OUTSIDE_MANAGER)

	def test_a_system_manager_lists_everything(self):
		for user in (SYSADMIN, "Administrator"):
			self.assert_records_unscoped(user)
			self.assert_lists_all(user)

	def test_a_rep_assigned_by_todo_lists_that_records_attachments(self):
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"reference_type": "CRM Deal",
				"reference_name": self.deal.name,
				"allocated_to": OTHER,
				"description": "Help with this deal",
			}
		).insert(ignore_permissions=True)
		listed = self.listed_to(OTHER)
		# the deal, and what hangs off it
		for doctype in ("CRM Deal", "FCRM Note", "CRM Task"):
			with self.subTest(attached_to=doctype):
				self.assertIn(self.files[doctype], listed)
				self.assertTrue(self.opens_for(OTHER, self.files[doctype]))
		# the lead is a different record, and still not theirs
		self.assertNotIn(self.files["CRM Lead"], listed)

	def test_a_rep_keeps_their_own_uploads(self):
		own_deal = self.make({"doctype": "CRM Deal", "deal_owner": OTHER})
		unattached = self.attach("my-scratch.txt", user=OTHER)
		on_own_deal = self.attach("my-quote.txt", own_deal, user=OTHER)
		by_a_manager = self.attach("from-the-manager.txt", own_deal)
		listed = self.listed_to(OTHER)
		for file in (unattached, on_own_deal, by_a_manager):
			self.assertIn(file, listed)
