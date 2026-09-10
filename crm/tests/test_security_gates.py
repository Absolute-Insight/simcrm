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
		with patch("crm.fcrm.doctype.fcrm_settings.fcrm_settings.restore_install_defaults") as install:
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


class DirectoryLeakTest(IntegrationTestCase):
	"""The helpers that answer "who works here" and "what does the team look at".

	``get_user_info`` resolved any 200 User names a caller cared to name, so a
	rep could confirm and put a name to arbitrary system accounts by guessing
	addresses; ``get_views`` had no CRM gate at all; and ``update_profile`` let a
	rep attach anyone's Email Account to their own profile, advertising someone
	else's mailbox as a From address in the composer.
	"""

	OUTSIDER = "secgate-outsider@crmtest.test"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Rep", "Sales User")
		ensure_user(NOBODY, "Nobody", None)
		ensure_user(self.OUTSIDER, "Outsider", None)
		self.addCleanup(frappe.set_user, "Administrator")

	# --- get_user_info ---------------------------------------------------

	def test_a_rep_cannot_resolve_a_non_crm_account(self):
		from crm.api.session import get_user_info

		frappe.set_user(REP)
		self.assertEqual(get_user_info([self.OUTSIDER]), [])

	def test_a_rep_still_resolves_their_colleagues(self):
		from crm.api.session import get_user_info

		frappe.set_user(REP)
		self.assertEqual([row["name"] for row in get_user_info([REP])], [REP])

	def test_a_system_manager_still_resolves_everyone(self):
		from crm.api.session import get_user_info

		frappe.set_user("Administrator")
		self.assertEqual([row["name"] for row in get_user_info([self.OUTSIDER])], [self.OUTSIDER])

	def test_a_user_without_a_crm_role_gets_nothing(self):
		from crm.api.session import get_user_info

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_user_info([REP])

	# --- get_views -------------------------------------------------------

	def test_a_user_without_a_crm_role_cannot_read_the_teams_views(self):
		from crm.api.views import get_views

		frappe.set_user(NOBODY)
		with self.assertRaises(frappe.PermissionError):
			get_views("CRM Deal")

	def test_a_rep_still_reads_views(self):
		from crm.api.views import get_views

		frappe.set_user(REP)
		self.assertIsInstance(get_views("CRM Deal"), list)

	# --- update_profile --------------------------------------------------

	def _email_account(self, name: str, address: str):
		if frappe.db.exists("Email Account", name):
			return frappe.get_doc("Email Account", name)
		account = frappe.get_doc(
			{
				"doctype": "Email Account",
				"email_account_name": name,
				"email_id": address,
				"enable_outgoing": 1,
			}
		)
		account.flags.ignore_mandatory = True
		account.flags.ignore_validate = True
		account.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: (
				frappe.db.exists("Email Account", account.name)
				and frappe.delete_doc("Email Account", account.name, force=True, ignore_permissions=True)
			)
		)
		return account

	def test_a_rep_cannot_attach_someone_elses_mailbox(self):
		from crm.api.user import update_profile

		# The address has to answer to a real account for this to be somebody
		# else's mailbox rather than a shared one -- see the test below.
		other = "secgate-someone-else@crmtest.test"
		ensure_user(other, "Secgate Someone", "Sales User")
		theirs = self._email_account("Secgate Someone Else", other)
		frappe.set_user(REP)
		with self.assertRaises(frappe.PermissionError):
			update_profile({"user_emails": [{"email_account": theirs.name, "email_id": theirs.email_id}]})
		frappe.set_user("Administrator")
		self.assertFalse(frappe.db.exists("User Email", {"parent": REP, "email_account": theirs.name}))

	def test_a_rep_may_attach_a_shared_mailbox(self):
		"""sales@ and support@ answer to no user account, and linking one is
		what those accounts are for -- the rule is about claiming a colleague's
		mailbox, not about the address matching your own."""
		from crm.api.user import update_profile

		shared = self._email_account("Secgate Shared Desk", "secgate-shared@crmtest.test")
		frappe.set_user(REP)
		update_profile({"user_emails": [{"email_account": shared.name, "email_id": shared.email_id}]})
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("User Email", {"parent": REP, "email_account": shared.name}))

	def test_a_rep_may_attach_their_own_mailbox(self):
		from crm.api.user import update_profile

		mine = self._email_account("Secgate Rep Mailbox", REP)
		frappe.set_user(REP)
		update_profile({"user_emails": [{"email_account": mine.name, "email_id": mine.email_id}]})
		frappe.set_user("Administrator")
		self.assertTrue(frappe.db.exists("User Email", {"parent": REP, "email_account": mine.name}))


class KanbanColumnEnumerationTest(IntegrationTestCase):
	"""A kanban's columns are the rows of the field it groups by, and they used to
	be read with ``frappe.get_all`` -- so asking for the deal board grouped by
	``lead`` handed a rep every lead name on the site."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_user(REP, "Rep", "Sales User")
		ensure_user(NOBODY, "Nobody", None)
		self.addCleanup(frappe.set_user, "Administrator")
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Kanban", "lead_owner": "Administrator"}
		).insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("CRM Lead", self.lead.name, force=True, ignore_permissions=True)
		)

	def test_a_rep_does_not_get_leads_they_cannot_see_as_columns(self):
		from crm.api.doc import kanban_link_columns

		frappe.set_user(REP)
		self.assertNotIn(self.lead.name, [row["name"] for row in kanban_link_columns("CRM Lead")])

	def test_the_owner_still_gets_their_own_lead_as_a_column(self):
		from crm.api.doc import kanban_link_columns

		frappe.set_user("Administrator")
		self.assertIn(self.lead.name, [row["name"] for row in kanban_link_columns("CRM Lead")])

	def test_user_columns_are_the_crm_users_not_the_whole_user_table(self):
		from crm.api.doc import kanban_link_columns

		frappe.set_user(REP)
		names = [row["name"] for row in kanban_link_columns("User")]
		self.assertIn(REP, names)
		self.assertNotIn(NOBODY, names)
