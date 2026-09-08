# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A rep's planned week must never block, nor be destroyed by, deleting a deal.

``CRM Rep Plan Item.reference_docname`` is a Dynamic Link. Left to frappe's link
check, a deal any rep had planned work against could not be deleted; the app's
"delete linked" flow, which only knows how to blank reference fields on a
top-level document, then deleted the *plan* -- the whole week -- to free it.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import get_linked_docs_of_document, remove_doc_link

REP = "plan-links-rep@crmtest.test"


class PlanItemLinksOnDeleteTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", REP):
			user = frappe.get_doc(
				{"doctype": "User", "email": REP, "first_name": "Plan Links", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		frappe.db.delete("CRM Rep Plan", {"user": REP})
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Plan Links Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "deal_owner": REP}
		).insert(ignore_permissions=True)
		monday = frappe.utils.getdate()
		monday = frappe.utils.add_days(monday, -monday.weekday())
		self.plan = frappe.get_doc(
			{
				"doctype": "CRM Rep Plan",
				"user": REP,
				"week_start": monday,
				"items": [
					{
						"activity_type": "Call",
						"planned_date": monday,
						"note": "Call about the valves",
						"reference_doctype": "CRM Deal",
						"reference_docname": self.deal.name,
					},
					{"activity_type": "Task", "planned_date": monday, "note": "Unrelated admin"},
				],
			}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.delete("CRM Rep Plan", {"user": REP})
		if frappe.db.exists("CRM Deal", self.deal.name):
			frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_deleting_the_deal_keeps_the_plan_and_unlinks_the_item(self):
		# The assignment notification is its own dynamic link, which the app's
		# delete flow clears through the linked-docs modal; not what is under test.
		frappe.db.delete(
			"CRM Notification", {"reference_doctype": "CRM Deal", "reference_name": self.deal.name}
		)
		frappe.delete_doc("CRM Deal", self.deal.name, ignore_permissions=True)

		plan = frappe.get_doc("CRM Rep Plan", self.plan.name)
		self.assertEqual(len(plan.items), 2, "the plan lost items")
		linked = next(item for item in plan.items if item.note == "Call about the valves")
		self.assertFalse(linked.reference_docname)
		self.assertFalse(linked.reference_doctype)

	def test_the_plan_is_never_offered_as_a_linked_document_of_the_deal(self):
		"""The protection that actually holds. CRM Rep Plan and CRM Rep Plan Item
		are in ``ignore_links_on_delete``, which frappe's get_linked_docs and
		get_dynamic_linked_docs both honour, so the plan never reaches the
		"delete linked document(s)" list -- and cannot be deleted to free one
		deal."""
		linked = get_linked_docs_of_document("CRM Deal", self.deal.name)
		self.assertNotIn("CRM Rep Plan", {row["reference_doctype"] for row in linked})

	def test_unlinking_a_document_with_no_reference_fields_leaves_it_alone(self):
		"""``remove_doc_link`` has nothing to clear on a document whose link is one
		of its own fields or a child row, so it does nothing -- quietly. It used to
		throw, which blocked the caller from deleting a converted lead's deal (see
		ConvertedLeadDeleteTest below)."""
		remove_doc_link("CRM Rep Plan", self.plan.name)
		plan = frappe.get_doc("CRM Rep Plan", self.plan.name)
		self.assertEqual(len(plan.items), 2)
		self.assertEqual(
			frappe.db.get_value(
				"CRM Rep Plan Item",
				{"parent": self.plan.name, "note": "Call about the valves"},
				"reference_docname",
			),
			self.deal.name,
		)


class ConvertedLeadDeleteTest(IntegrationTestCase):
	"""A converted lead's deal must stay deletable through "delete linked document(s)".

	CRM Deal has no reference_doctype/reference_docname pair -- its link to the
	lead is its own top-level ``lead`` field -- so a blanket refusal to unlink
	such a document stopped the deal being removed, and the lead's own delete
	then failed on the link that was left behind while the bulk path reported
	success.
	"""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Convert", "last_name": "Delete", "converted": 1}
		).insert(ignore_permissions=True)
		self.deal = frappe.get_doc({"doctype": "CRM Deal", "lead": self.lead.name}).insert(
			ignore_permissions=True
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		for doctype, name in (("CRM Deal", self.deal.name), ("CRM Lead", self.lead.name)):
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_the_deal_is_listed_as_a_linked_document_of_its_lead(self):
		linked = get_linked_docs_of_document("CRM Lead", self.lead.name)
		self.assertIn(
			(self.deal.name, "CRM Deal"),
			{(row["reference_docname"], row["reference_doctype"]) for row in linked},
		)

	def test_unlinking_the_deal_does_not_refuse_and_the_deal_can_then_be_deleted(self):
		remove_doc_link("CRM Deal", self.deal.name)
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("CRM Deal", self.deal.name))

		# and with it gone the lead itself is deletable, which is the point of
		# "delete linked document(s)"
		frappe.delete_doc("CRM Lead", self.lead.name, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("CRM Lead", self.lead.name))
