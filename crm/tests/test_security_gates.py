# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Role and row gates on whitelisted endpoints that used to trust the caller.

Each test calls the endpoint as a plain Sales User (or a user with no CRM role)
and asserts it is refused; the happy path is covered by the feature tests.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

REP = "secgate-rep@crmtest.test"
NOBODY = "secgate-nobody@crmtest.test"


def ensure_user(email: str, name: str, role: str | None) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		if role:
			user.add_roles(role)


class SecurityGateTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Rep", "Sales User")
		ensure_user(NOBODY, "Nobody", None)
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Sec Gate Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert(
			ignore_permissions=True
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		super().tearDown()

	# --- FCRM Settings doc methods ------------------------------------

	def test_rep_cannot_restore_defaults(self):
		frappe.set_user(REP)
		settings = frappe.get_single("FCRM Settings")
		with patch("crm.fcrm.doctype.fcrm_settings.fcrm_settings.after_install") as install:
			with self.assertRaises(frappe.PermissionError):
				settings.restore_defaults()
			install.assert_not_called()

	def test_rep_cannot_restore_demo_data(self):
		frappe.set_user(REP)
		settings = frappe.get_single("FCRM Settings")
		with patch("crm.fcrm.doctype.fcrm_settings.fcrm_settings.create_demo_data") as seed:
			with self.assertRaises(frappe.PermissionError):
				settings.restore_demo_data()
			seed.assert_not_called()

	# --- site-wide writes -----------------------------------------------

	def test_rep_cannot_update_quick_filters(self):
		from crm.api.doc import update_quick_filters

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			update_quick_filters("[]", "[]", "CRM Lead")

	def test_rep_cannot_create_email_account(self):
		from crm.api.settings import create_email_account

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			create_email_account({"service": "GMail"})

	def test_rep_cannot_manage_facebook_pages(self):
		from crm.lead_syncing.doctype.lead_sync_source.facebook import (
			fetch_and_store_pages_from_facebook,
			get_pages_with_forms,
		)

		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			get_pages_with_forms()
		with self.assertRaises(frappe.PermissionError):
			fetch_and_store_pages_from_facebook("token")

	def test_rep_cannot_run_erpnext_admin_actions(self):
		frappe.set_user(REP)
		settings = frappe.get_single("ERPNext CRM Settings")
		for method in ("reset_erpnext_form_script", "get_external_companies", "run_product_sync"):
			with self.assertRaises(frappe.PermissionError, msg=method):
				getattr(settings, method)()

	# --- row-level reads ------------------------------------------------

	def test_user_without_crm_role_cannot_read_deal_contacts(self):
		from crm.fcrm.doctype.crm_deal.api import get_deal_contacts

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_deal_contacts(self.deal.name)

	def test_a_contacts_linked_deals_are_read_through_the_deal_permission_query(self):
		"""``get_linked_deals`` used to ``get_cached_doc`` every deal the contact
		sits on, so a rep who could read the contact read deals outside their
		subtree. It now lists them, and the hierarchy decides which come back."""
		from crm.api.contact import get_linked_deals

		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Gate Contact"}).insert(
			ignore_permissions=True
		)
		self.deal.append("contacts", {"contact": contact.name, "is_primary": 1})
		self.deal.deal_owner = "Administrator"
		self.deal.save(ignore_permissions=True)
		self.addCleanup(frappe.delete_doc, "Contact", contact.name, force=True, ignore_permissions=True)

		# REP alone in the tree: the hierarchy scopes deals to their own subtree
		was_enabled = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		self.addCleanup(
			frappe.db.set_single_value, "FCRM Settings", "enable_sales_hierarchy", was_enabled or 0
		)
		self.addCleanup(frappe.cache.delete_value, "crm_sales_hierarchy_subtree")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		frappe.db.delete("CRM Sales Hierarchy", {"user": REP})
		node = frappe.get_doc({"doctype": "CRM Sales Hierarchy", "user": REP}).insert(ignore_permissions=True)
		self.addCleanup(frappe.db.delete, "CRM Sales Hierarchy", {"name": node.name})
		frappe.cache.delete_value("crm_sales_hierarchy_subtree")

		self.assertIn(self.deal.name, [d.name for d in get_linked_deals(contact.name)])
		frappe.set_user(REP)
		self.assertEqual(get_linked_deals(contact.name), [])

	def test_user_without_crm_role_cannot_list_linked_docs(self):
		from crm.api.doc import get_linked_docs_of_document

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_linked_docs_of_document("CRM Deal", self.deal.name)

	def test_user_without_crm_role_cannot_resolve_phone_numbers(self):
		from crm.integrations.api import (
			get_contact_by_phone_number,
			get_contact_lead_or_deal_from_number,
		)

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_contact_by_phone_number("+1 415 555 0100")
		with self.assertRaises(frappe.PermissionError):
			get_contact_lead_or_deal_from_number("+1 415 555 0100")

	def test_user_without_crm_role_cannot_list_assignment_rules(self):
		from crm.api.assignment_rule import get_assignment_rules_list

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_assignment_rules_list()

	# --- input validation -----------------------------------------------

	def test_phone_lookup_strips_like_wildcards(self):
		from crm.integrations.api import get_contact

		# A bare "%" used to match every contact on the site.
		self.assertEqual(get_contact("%", "IN", exact_match=True), {"mobile_no": "%"})
		self.assertEqual(get_contact("_", "IN", exact_match=True), {"mobile_no": "_"})

	def test_exchange_rate_rejects_unknown_currency_and_bad_date(self):
		from crm.api.exchange_rate import get_exchange_rate

		with patch("crm.api.exchange_rate._fetch_exchange_rate") as fetch:
			with self.assertRaises(frappe.ValidationError):
				get_exchange_rate("USD", "../etc")
			with self.assertRaises(frappe.ValidationError):
				get_exchange_rate("USD", "INR", date="latest?x=1")
			fetch.assert_not_called()

	def test_user_signature_is_sanitized(self):
		from crm.api import get_user_signature

		frappe.set_user("Administrator")
		frappe.db.set_value("User", "Administrator", "email_signature", "<b>Hi</b><script>alert(1)</script>")
		try:
			signature = get_user_signature()
		finally:
			frappe.db.set_value("User", "Administrator", "email_signature", None)
		self.assertIn("<b>Hi</b>", signature)
		self.assertNotIn("<script>", signature)
