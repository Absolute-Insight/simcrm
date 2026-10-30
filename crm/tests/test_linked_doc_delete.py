# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deleting a record that other records point at.

The "Unlink" choice in the delete modals has to take away only the link to the
record going.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import _unlink_linked_docs, get_linked_docs_of_document


def make_contact(first_name: str) -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": f"Unlink {frappe.generate_hash(length=6)}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def make_org() -> str:
	return (
		frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": f"Unlink Org {frappe.generate_hash(length=6)}",
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


class UnlinkOneContactTest(IntegrationTestCase):
	"""frappe reports a CRM Contacts child row as its parent deal, so the unlink is
	handed the deal. It used to clear the deal's whole contacts table -- and with
	no primary contact left, the deal's email and phone -- for one contact going.
	"""

	def setUp(self):
		frappe.set_user("Administrator")
		self.a, self.b, self.c = (make_contact(name) for name in ("Alpha", "Bravo", "Charlie"))
		self.deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": make_org(),
				"contacts": [
					{"contact": self.b, "is_primary": 1},
					{"contact": self.a},
					{"contact": self.c},
				],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.db.rollback()

	def contacts_left(self) -> list[str]:
		return sorted(frappe.get_all("CRM Contacts", filters={"parent": self.deal.name}, pluck="contact"))

	def test_the_delete_modal_unlink_keeps_the_deals_other_contacts(self):
		linked = get_linked_docs_of_document("Contact", self.a)
		items = [{"doctype": d["reference_doctype"], "docname": d["reference_docname"]} for d in linked]
		self.assertIn({"doctype": "CRM Deal", "docname": self.deal.name}, items)

		# through frappe.call, as the HTTP handler calls it: arguments the
		# function does not take are dropped rather than raising
		result = frappe.call(
			"crm.api.doc.remove_linked_doc_reference",
			items=items,
			remove_contact=True,
			contact=self.a,
		)

		self.assertIn(self.deal.name, result["unlinked"])
		self.assertEqual(self.contacts_left(), sorted([self.b, self.c]))
		deal = frappe.get_doc("CRM Deal", self.deal.name)
		self.assertEqual([row.contact for row in deal.contacts if row.is_primary], [self.b])

	def test_the_bulk_unlink_keeps_the_deals_other_contacts(self):
		_unlink_linked_docs("Contact", [self.a])

		self.assertEqual(self.contacts_left(), sorted([self.b, self.c]))

	def test_unlinking_a_contact_without_naming_it_is_refused(self):
		with self.assertRaises(frappe.ValidationError):
			frappe.call(
				"crm.api.doc.remove_linked_doc_reference",
				items=[{"doctype": "CRM Deal", "docname": self.deal.name}],
				remove_contact=True,
			)
		self.assertEqual(len(self.contacts_left()), 3)
