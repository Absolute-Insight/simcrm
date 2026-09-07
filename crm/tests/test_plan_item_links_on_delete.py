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

from crm.api.doc import remove_doc_link

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
		frappe.db.delete("CRM Notification", {"reference_doctype": "CRM Deal", "reference_name": self.deal.name})
		frappe.delete_doc("CRM Deal", self.deal.name, ignore_permissions=True)

		plan = frappe.get_doc("CRM Rep Plan", self.plan.name)
		self.assertEqual(len(plan.items), 2, "the plan lost items")
		linked = next(item for item in plan.items if item.note == "Call about the valves")
		self.assertFalse(linked.reference_docname)
		self.assertFalse(linked.reference_doctype)

	def test_the_unlink_flow_refuses_a_document_linked_through_a_child_row(self):
		"""Blanking two fields the plan does not have was a no-op that the delete
		path then followed by deleting the plan itself."""
		with self.assertRaises(frappe.ValidationError):
			remove_doc_link("CRM Rep Plan", self.plan.name)
		self.assertTrue(frappe.db.exists("CRM Rep Plan", self.plan.name))
