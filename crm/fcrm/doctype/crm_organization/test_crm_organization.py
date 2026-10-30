# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase


class TestCRMOrganization(UnitTestCase):
	pass


class TestOrganizationRenameCarriesContacts(IntegrationTestCase):
	"""Contact.company_name is core's *Data* field, yet it is how a contact
	belongs to an organization here: the org page's Contacts tab filters on it.
	rename_doc rewrites Link columns only, so a rename left every contact on a
	name that no longer exists and emptied the org's Contacts tab."""

	def tearDown(self):
		frappe.db.rollback()

	def make_org(self, name):
		return frappe.get_doc({"doctype": "CRM Organization", "organization_name": name}).insert(
			ignore_permissions=True
		)

	def make_contact(self, company_name):
		return frappe.get_doc(
			{"doctype": "Contact", "first_name": "Rename", "last_name": "Probe", "company_name": company_name}
		).insert(ignore_permissions=True)

	def rename(self, old, new, merge=False):
		# what the org page's name edit sends (frappe.client.rename_doc)
		frappe.rename_doc("CRM Organization", old, new, merge=merge, show_alert=False, rebuild_search=False)

	def company_of(self, contact):
		return frappe.db.get_value("Contact", contact.name, "company_name")

	def test_contacts_follow_a_rename(self):
		org = self.make_org("Rename Probe Old")
		contact = self.make_contact(org.name)
		bystander = self.make_contact("Rename Probe Elsewhere")

		self.rename(org.name, "Rename Probe New")

		self.assertEqual(self.company_of(contact), "Rename Probe New")
		self.assertEqual(self.company_of(bystander), "Rename Probe Elsewhere")

	def test_contacts_follow_a_merge(self):
		gone = self.make_org("Merge Probe Duplicate")
		kept = self.make_org("Merge Probe Kept")
		contact = self.make_contact(gone.name)

		self.rename(gone.name, kept.name, merge=True)

		self.assertEqual(self.company_of(contact), kept.name)

	def test_patch_repoints_contacts_an_earlier_rename_stranded(self):
		from crm.patches.v1_0.repoint_contacts_stranded_by_org_rename import execute

		# A -> B -> C, renamed before after_rename existed: both contacts were left behind
		self.make_org("Strand Probe A")
		on_a = self.make_contact("Strand Probe A")
		self.rename("Strand Probe A", "Strand Probe B")
		on_b = self.make_contact("Strand Probe B")
		self.rename("Strand Probe B", "Strand Probe C")
		frappe.db.set_value("Contact", on_a.name, "company_name", "Strand Probe A")
		frappe.db.set_value("Contact", on_b.name, "company_name", "Strand Probe B")
		# a merge strands the same way
		self.make_org("Strand Probe Dupe")
		on_dupe = self.make_contact("Strand Probe Dupe")
		self.rename("Strand Probe Dupe", "Strand Probe C", merge=True)
		frappe.db.set_value("Contact", on_dupe.name, "company_name", "Strand Probe Dupe")
		# an old name a new organization has since taken belongs to that organization now
		self.make_org("Strand Probe Reused")
		self.rename("Strand Probe Reused", "Strand Probe Moved")
		self.make_org("Strand Probe Reused")
		on_reused = self.make_contact("Strand Probe Reused")

		execute()

		self.assertEqual(self.company_of(on_a), "Strand Probe C")
		self.assertEqual(self.company_of(on_b), "Strand Probe C")
		self.assertEqual(self.company_of(on_dupe), "Strand Probe C")
		self.assertEqual(self.company_of(on_reused), "Strand Probe Reused")
