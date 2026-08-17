# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Contact and Email Template get their CRM list columns from a mixin.

These used to be `override_doctype_class`, which *replaces* the framework
controller. Only one app can hold that per DocType, so installing anything else
that overrides Contact would have silently taken the CRM's columns away and left
the list view falling back to name + modified. `extend_doctype_class` stacks.

The failure mode either way is quiet -- a list view with the wrong columns, no
error anywhere -- so it is pinned here.
"""

from __future__ import annotations

import frappe
from frappe.contacts.doctype.contact.contact import Contact
from frappe.email.doctype.email_template.email_template import EmailTemplate
from frappe.model.base_document import get_controller
from frappe.tests import IntegrationTestCase

EXPECTED_COLUMNS = {
	"Contact": ["full_name", "email_id", "mobile_no", "company_name", "modified"],
	"Email Template": ["name", "subject", "enabled", "reference_doctype", "modified"],
}


class DoctypeExtensionTest(IntegrationTestCase):
	def test_the_crm_list_columns_are_mixed_into_both_controllers(self):
		for doctype, expected in EXPECTED_COLUMNS.items():
			with self.subTest(doctype=doctype):
				controller = get_controller(doctype)
				self.assertTrue(
					hasattr(controller, "default_list_data"),
					f"{doctype} lost default_list_data -- is extend_doctype_class still in hooks.py?",
				)
				keys = [c["key"] for c in controller.default_list_data()["columns"]]
				self.assertEqual(keys, expected)

	def test_the_framework_controller_is_still_the_base(self):
		"""A mixin extends; it must not displace the real controller."""
		self.assertTrue(issubclass(get_controller("Contact"), Contact))
		self.assertTrue(issubclass(get_controller("Email Template"), EmailTemplate))

	def test_documents_still_instantiate_as_the_framework_type(self):
		self.assertIsInstance(frappe.new_doc("Contact"), Contact)
		self.assertIsInstance(frappe.new_doc("Email Template"), EmailTemplate)
