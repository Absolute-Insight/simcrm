# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Automation engine tests: triggers, conditions, actions, failure isolation."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


def make_rule(**overrides):
	rule = {
		"doctype": "CRM Automation Rule",
		"title": overrides.pop("title", "Test Rule"),
		"enabled": 1,
		"document_type": "CRM Deal",
		"trigger": "Created",
		"action": "Create Task",
		"title_template": "Follow up with {{ doc.organization }}",
		"task_priority": "High",
		"due_in_days": 2,
		"assign_to_owner": 1,
	}
	rule.update(overrides)
	return frappe.get_doc(rule).insert(ignore_permissions=True)


class AutomationRuleTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Automation Rule")
		frappe.db.delete("CRM Suggestion")
		# error-log commits inside the engine can persist earlier test records on
		# this shared site, and rolled-back naming counters then reuse deal names —
		# clear this suite's own artifacts so assertions see only the current test
		frappe.db.delete("CRM Task", {"title": ("like", "%Automation Org%")})
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Automation Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self._made = []

	def tearDown(self):
		frappe.db.delete("CRM Automation Rule")
		frappe.db.delete("CRM Suggestion")
		for doctype, name in self._made:
			frappe.delete_doc(doctype, name, force=True, ignore_missing=True)
		super().tearDown()

	def make_deal(self, **kwargs):
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org, **kwargs}).insert()
		self._made.append(("CRM Deal", deal.name))
		return deal

	def tasks_for(self, deal):
		return frappe.get_all(
			"CRM Task",
			filters={"reference_doctype": "CRM Deal", "reference_docname": deal.name},
			fields=["title", "priority", "assigned_to"],
		)

	def test_a_created_trigger_creates_the_task(self):
		make_rule()
		deal = self.make_deal()
		tasks = self.tasks_for(deal)
		self.assertEqual(len(tasks), 1)
		self.assertEqual(tasks[0].title, "Follow up with Automation Org")
		self.assertEqual(tasks[0].priority, "High")

	def test_a_disabled_rule_does_nothing(self):
		make_rule(enabled=0)
		deal = self.make_deal()
		self.assertEqual(self.tasks_for(deal), [])

	def test_a_status_changed_trigger_fires_only_on_the_target_status(self):
		# Lost-type statuses demand a lost reason on save; stay in working statuses
		statuses = frappe.get_all(
			"CRM Deal Status",
			filters={"type": ("in", ("Open", "Ongoing"))},
			pluck="name",
			limit=2,
		)
		make_rule(
			title="On status",
			trigger="Status Changed",
			to_status=statuses[1],
			action="Create Suggestion",
			title_template="Status moved on {{ doc.organization }}",
		)
		deal = self.make_deal(status=statuses[0])
		self.assertEqual(frappe.db.count("CRM Suggestion", {"reference_docname": deal.name}), 0)
		deal.status = statuses[1]
		deal.save()
		self.assertEqual(frappe.db.count("CRM Suggestion", {"reference_docname": deal.name}), 1)
		# saving again without a status change must not duplicate
		deal.reload()
		deal.probability = 50
		deal.save()
		self.assertEqual(frappe.db.count("CRM Suggestion", {"reference_docname": deal.name}), 1)

	def test_a_false_condition_suppresses_the_rule(self):
		make_rule(condition="doc.annual_revenue > 1000000")
		deal = self.make_deal(annual_revenue=5)
		self.assertEqual(self.tasks_for(deal), [])

	def test_a_true_condition_fires_the_rule(self):
		make_rule(condition="doc.annual_revenue > 1000000")
		deal = self.make_deal(annual_revenue=2000000)
		self.assertEqual(len(self.tasks_for(deal)), 1)

	def test_a_broken_condition_never_blocks_the_save(self):
		# bypass save-time syntax validation to simulate a rule broken in place
		rule = make_rule()
		frappe.db.set_value("CRM Automation Rule", rule.name, "condition", "doc.nonexistent.deeper == 1")
		deal = self.make_deal()  # must not raise
		self.assertTrue(deal.name)
		self.assertEqual(self.tasks_for(deal), [])

	def test_an_unsupported_doctype_is_rejected_at_save(self):
		with self.assertRaises(frappe.ValidationError):
			make_rule(title="Bad target", document_type="CRM Task")

	def test_an_invalid_condition_is_rejected_at_save(self):
		with self.assertRaises(frappe.ValidationError):
			make_rule(title="Bad condition", condition="doc.status ==")
