# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a public form hands to an anonymous visitor.

Every CRM form is saved with ``login_required = 0``. Frappe's own
``web_form.get_link_options`` then lists, with ``frappe.get_all`` and no
permission check, every record of any doctype a Link field on a published form
points at -- the CRM's ``guest_can_select`` gate is not on that path. And the
branded page is rendered by a Jinja environment with autoescape off.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from markupsafe import escape

from crm.api import form as F

PEOPLE_AND_RECORDS = ("User", "CRM Lead", "CRM Deal", "Contact", "CRM Organization")


class PublicFormLinkTargetTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)

	def test_the_picker_offers_no_link_to_people_or_records(self):
		"""``name`` of User is the rep's email and ``name`` of CRM Organization is the
		customer; neither is a dropdown for the public internet."""
		for document_type, denied in (
			("CRM Lead", {"lead_owner"}),
			("CRM Deal", {"deal_owner", "lead", "contact", "organization"}),
		):
			offered = {f["fieldname"]: f for f in F.get_form_fields(document_type)}
			self.assertFalse(denied & set(offered), f"{document_type}: {denied & set(offered)}")
			for fieldname, field in offered.items():
				if field["fieldtype"] == "Link":
					self.assertNotIn(field["options"], PEOPLE_AND_RECORDS, fieldname)
			# reference data stays collectible
			self.assertIn("territory", offered)

	def test_save_form_rejects_a_link_to_a_denied_target(self):
		with self.assertRaises(frappe.ValidationError):
			F.save_form(
				name=None,
				form={
					"title": "Owner probe",
					"route": "owner-probe",
					"document_type": "CRM Deal",
					"fields": [{"fieldname": "deal_owner", "fieldtype": "Link", "options": "User"}],
					"hidden_fields": [],
				},
			)
		self.assertFalse(frappe.db.exists("Web Form", {"route": "owner-probe"}))

	def test_guest_select_cannot_be_granted_on_a_denied_target(self):
		for doctype in PEOPLE_AND_RECORDS:
			with self.assertRaises(frappe.ValidationError, msg=doctype):
				F.grant_guest_link_access(doctype)
			self.assertFalse(
				frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": "Guest"}),
				doctype,
			)

	def test_guest_select_is_still_grantable_on_reference_data(self):
		self.assertIn("CRM Territory", F._link_target_doctypes())
		self.assertNotIn("User", F._link_target_doctypes())


class PublicFormEscapingTest(IntegrationTestCase):
	"""The victim is the prospect on the company's own domain; the author is any
	Sales User who can name an Organization, and any manager typing a label."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.db.rollback)
		self.addCleanup(frappe.form_dict.pop, "route", None)

	def test_record_names_and_form_text_reach_the_page_escaped(self):
		from crm.www import crm_form

		hostile_record = 'Acme" onmouseover="alert(1)'
		hostile_text = 'Say hi" onfocus="alert(2)'
		name = F.save_form(
			name=None,
			form={
				"title": hostile_text,
				"route": "escape-probe",
				"description": hostile_text,
				"success_message": hostile_text,
				"submit_button_label": hostile_text,
				"document_type": "CRM Lead",
				"fields": [
					{
						"fieldname": "territory",
						"fieldtype": "Link",
						"options": "CRM Territory",
						"label": hostile_text,
						"placeholder": hostile_text,
						"field_description": hostile_text,
					},
					{"fieldname": "first_name", "fieldtype": "Data", "placeholder": hostile_text},
				],
				"hidden_fields": [],
			},
		)["name"]
		self.assertTrue(name)

		frappe.form_dict["route"] = "escape-probe"
		options = [{"value": hostile_record, "label": hostile_record}]
		with patch.object(crm_form, "_link_field_options", return_value=options):
			context = crm_form.get_context(frappe._dict())
		html = frappe.get_template("crm/www/crm_form.html").render(context)

		self.assertNotIn(hostile_record, html)
		self.assertNotIn(hostile_text, html)
		self.assertNotIn('onmouseover="', html)
		self.assertNotIn('onfocus="', html)
		self.assertIn(str(escape(hostile_record)), html)
		self.assertIn(str(escape(hostile_text)), html)
