# Copyright (c) 2024, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.api.whatsapp import (
	create_whatsapp_message,
	notify_agent,
	react_on_whatsapp_message,
	resolve_destination,
	send_whatsapp_template,
	validate,
)


class TestWhatsAppHooks(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	# --- validate() ---

	def test_validate_sets_reference_when_contact_found(self):
		"""validate() links the doc when a matching Contact/Lead is found"""
		doc = MagicMock()
		doc.type = "Incoming"
		doc.get.return_value = "+15551234567"

		with patch(
			"crm.api.whatsapp.lookup_contact_lead_or_deal_from_number",
			return_value=("LEAD-0001", "CRM Lead"),
		):
			validate(doc, None)

		self.assertEqual(doc.reference_doctype, "CRM Lead")
		self.assertEqual(doc.reference_name, "LEAD-0001")

	def test_validate_skips_reference_when_no_contact_found(self):
		"""validate() leaves reference fields untouched when number is unknown"""
		doc = MagicMock()
		doc.type = "Incoming"
		doc.get.return_value = "+15559999999"
		doc.reference_doctype = None
		doc.reference_name = None

		with patch(
			"crm.api.whatsapp.lookup_contact_lead_or_deal_from_number",
			return_value=(None, None),
		):
			validate(doc, None)

		self.assertIsNone(doc.reference_doctype)
		self.assertIsNone(doc.reference_name)

	def test_validate_keeps_an_outgoing_message_on_the_record_it_was_sent_from(self):
		"""The number lookup found another deal of the same contact and re-filed
		the message there, replies and status saves included."""
		doc = MagicMock()
		doc.type = "Outgoing"
		doc.get.return_value = "+27825550199"
		doc.reference_doctype = "CRM Deal"
		doc.reference_name = "CRM-DEAL-1"

		with patch(
			"crm.api.whatsapp.lookup_contact_lead_or_deal_from_number",
			return_value=("CRM-DEAL-2", "CRM Deal"),
		) as lookup:
			validate(doc, None)

		lookup.assert_not_called()
		self.assertEqual((doc.reference_doctype, doc.reference_name), ("CRM Deal", "CRM-DEAL-1"))

	def test_validate_still_files_an_outgoing_message_with_no_reference(self):
		doc = MagicMock()
		doc.type = "Outgoing"
		doc.get.return_value = "+27825550199"
		doc.reference_doctype = None
		doc.reference_name = None

		with patch(
			"crm.api.whatsapp.lookup_contact_lead_or_deal_from_number",
			return_value=("CRM-DEAL-2", "CRM Deal"),
		):
			validate(doc, None)

		self.assertEqual((doc.reference_doctype, doc.reference_name), ("CRM Deal", "CRM-DEAL-2"))

	def test_validate_logs_error_on_exception(self):
		"""validate() catches lookup exceptions and logs them instead of raising"""
		doc = MagicMock()
		doc.type = "Incoming"
		doc.get.return_value = "invalid-number"

		with (
			patch(
				"crm.api.whatsapp.lookup_contact_lead_or_deal_from_number",
				side_effect=Exception("parse error"),
			),
			patch("frappe.log_error") as mock_log,
		):
			validate(doc, None)  # must not raise

		mock_log.assert_called_once()

	# --- notify_agent() ---

	def test_notify_agent_returns_early_when_no_reference(self):
		"""notify_agent() skips notification when reference_doctype and reference_name are absent"""
		doc = MagicMock()
		doc.type = "Incoming"
		doc.reference_doctype = None
		doc.reference_name = None

		with patch("crm.api.whatsapp.assigned_users") as mock_users:
			notify_agent(doc)  # must not raise

		mock_users.assert_not_called()

	def test_notify_agent_returns_early_when_reference_doctype_missing(self):
		"""notify_agent() skips notification when only reference_doctype is absent"""
		doc = MagicMock()
		doc.type = "Incoming"
		doc.reference_doctype = ""
		doc.reference_name = "LEAD-0001"

		with patch("crm.api.whatsapp.assigned_users") as mock_users:
			notify_agent(doc)

		mock_users.assert_not_called()

	def notification_text_for(self, doctype, name):
		doc = MagicMock()
		doc.type = "Incoming"
		doc.reference_doctype = doctype
		doc.reference_name = name
		with (
			patch("crm.api.whatsapp.assigned_users", return_value=["rep@example.com"]),
			patch("crm.api.whatsapp.notify_user") as mock_notify,
		):
			notify_agent(doc)
		return mock_notify.call_args[0][0]["notification_text"]

	def test_the_notification_names_a_lead_by_its_lead_name(self):
		"""It showed the record id (CRM-LEAD-2026-00042), which nobody knows a lead by
		(upstream frappe/crm #3034); mentions and assignments already used the name."""
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Wanda", "last_name": "Whatsapp"}).insert(
			ignore_permissions=True
		)
		text = self.notification_text_for("CRM Lead", lead.name)
		self.assertIn("Wanda Whatsapp", text)
		self.assertNotIn(lead.name, text)

	def test_the_notification_names_a_deal_by_its_organization(self):
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": "Whatsapp Org Ltd"})
		deal.flags.ignore_mandatory = True
		deal.flags.ignore_links = True
		deal.insert(ignore_permissions=True)
		text = self.notification_text_for("CRM Deal", deal.name)
		self.assertIn("Whatsapp Org Ltd", text)

	def test_the_name_in_the_notification_is_escaped(self):
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "<b>Bold</b>"}).insert(
			ignore_permissions=True
		)
		text = self.notification_text_for("CRM Lead", lead.name)
		self.assertNotIn("<b>Bold</b>", text)
		self.assertIn("&lt;b&gt;Bold&lt;/b&gt;", text)


class TestWhatsAppDestination(FrappeTestCase):
	"""The destination of an outgoing message belongs to the record, not the caller.

	``to`` used to be whatever the caller sent, and the endpoints asked only for
	read on the reference: a rep with read on any lead could send business-account
	messages -- approved templates included -- to any number in the world and have
	them filed on that lead's thread.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Whatsapp",
				"last_name": "Lead",
				"mobile_no": "+27 82 555 0101",
				"phone": "+27115550102",
			}
		).insert(ignore_permissions=True)

	def test_a_blank_destination_is_the_records_own_number(self):
		self.assertEqual(resolve_destination(self.lead), "+27 82 555 0101")

	def test_the_same_number_spelled_differently_is_still_the_records_number(self):
		self.assertEqual(resolve_destination(self.lead, "+27825550101"), "+27 82 555 0101")

	def test_a_second_number_on_the_record_is_allowed(self):
		self.assertEqual(resolve_destination(self.lead, "+27115550102"), "+27115550102")

	def test_a_number_the_record_does_not_carry_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			resolve_destination(self.lead, "+27829999999")

	def test_a_record_with_no_number_cannot_be_messaged(self):
		self.lead.mobile_no = ""
		self.lead.phone = ""
		with self.assertRaises(frappe.ValidationError):
			resolve_destination(self.lead)

	def test_a_deals_contact_numbers_count_as_the_deals_own(self):
		# a deal messages its primary contact by default, but the other people on
		# the deal are still the deal's own numbers
		deal = frappe.new_doc("CRM Deal")
		deal.mobile_no = "+27825550201"
		deal.append("contacts", {"full_name": "Second Contact", "mobile_no": "+27825550202"})
		self.assertEqual(resolve_destination(deal), "+27825550201")
		self.assertEqual(resolve_destination(deal, "+27825550202"), "+27825550202")
		with self.assertRaises(frappe.ValidationError):
			resolve_destination(deal, "+27825550203")


class TestWhatsAppSendPermission(FrappeTestCase):
	"""Sending on a record's behalf is a write to its thread, not a read of it.

	CRM Deal Status stands in for "a reference this rep may read and may not
	write": the point is that read alone no longer opens the two send endpoints.
	"""

	REP = "whatsapp-rep@crmtest.test"

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", self.REP):
			user = frappe.get_doc(
				{
					"doctype": "User",
					"email": self.REP,
					"first_name": "Whatsapp Rep",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		self.status = frappe.get_all("CRM Deal Status", limit=1, pluck="name")[0]
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_a_reference_the_rep_can_only_read_cannot_be_messaged(self):
		frappe.set_user(self.REP)
		self.assertTrue(frappe.has_permission("CRM Deal Status", doc=self.status, ptype="read"))
		with self.assertRaises(frappe.PermissionError):
			create_whatsapp_message("CRM Deal Status", self.status, "hello", to="+27825550101")
		with self.assertRaises(frappe.PermissionError):
			send_whatsapp_template("CRM Deal Status", self.status, "some_template", to="+27825550101")

	def test_a_reference_the_rep_can_only_read_cannot_be_reacted_on(self):
		"""A reaction is delivered to the customer like any other message, so it
		takes write on the record too -- it was the one send left on read."""
		incoming = MagicMock(
			type="Incoming",
			reference_doctype="CRM Deal Status",
			reference_name=self.status,
			message_id="wamid.incoming.1",
		)
		incoming.get.return_value = "+27825550101"
		incoming.has_permission.return_value = True
		real_exists, real_get_doc = frappe.db.exists, frappe.get_doc
		sent = MagicMock()

		def exists(doctype, *args, **kwargs):
			return doctype == "WhatsApp Message" or real_exists(doctype, *args, **kwargs)

		def get_doc(doctype, *args, **kwargs):
			return incoming if doctype == "WhatsApp Message" else real_get_doc(doctype, *args, **kwargs)

		frappe.set_user(self.REP)
		self.assertTrue(frappe.has_permission("CRM Deal Status", doc=self.status, ptype="read"))
		with (
			patch.object(frappe.db, "exists", side_effect=exists),
			patch("frappe.get_doc", side_effect=get_doc),
			patch("frappe.new_doc", return_value=sent),
			self.assertRaises(frappe.PermissionError),
		):
			react_on_whatsapp_message("\U0001f44d", "WA-INCOMING-1")
		sent.insert.assert_not_called()
