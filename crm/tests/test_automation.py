# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Automation engine tests: triggers, conditions, actions, failure isolation."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

LEAD_OWNER = "automation-owner@crmtest.test"


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


def ensure_user(email: str, first_name: str) -> str:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": first_name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")
	return email


class AutomationRuleTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.delete("CRM Automation Rule")
		frappe.db.delete("CRM Suggestion", {"signal": ("like", "rule:%")})
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
		frappe.db.delete("CRM Suggestion", {"signal": ("like", "rule:%")})
		for doctype, name in self._made:
			frappe.delete_doc(doctype, name, force=True, ignore_missing=True)
		super().tearDown()

	def make_deal(self, **kwargs):
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": self.org, **kwargs}).insert()
		self._made.append(("CRM Deal", deal.name))
		return deal

	def make_lead(self, **kwargs):
		lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Automation", "last_name": "Lead", **kwargs}
		).insert()
		self._made.append(("CRM Lead", lead.name))
		return lead

	def tasks_for(self, doc):
		return frappe.get_all(
			"CRM Task",
			filters={"reference_doctype": doc.doctype, "reference_docname": doc.name},
			fields=["title", "priority", "assigned_to", "due_date"],
			order_by="creation asc",
		)

	def suggestions_for(self, doc):
		return frappe.get_all(
			"CRM Suggestion",
			filters={"reference_docname": doc.name, "signal": ("like", "rule:%")},
			fields=["name", "title", "user", "status"],
		)

	def test_a_created_trigger_creates_the_task(self):
		make_rule()
		deal = self.make_deal(deal_owner=ensure_user(LEAD_OWNER, "Automation Owner"))
		tasks = self.tasks_for(deal)
		self.assertEqual(len(tasks), 1)
		self.assertEqual(tasks[0].title, "Follow up with Automation Org")
		self.assertEqual(tasks[0].priority, "High")
		self.assertEqual(tasks[0].assigned_to, LEAD_OWNER)

	def test_a_lead_rule_uses_the_lead_owner_and_the_due_date_offset(self):
		owner = ensure_user(LEAD_OWNER, "Automation Owner")
		make_rule(
			title="Lead rule",
			document_type="CRM Lead",
			title_template="Call {{ doc.first_name }}",
			due_in_days=2,
			assign_to_owner=1,
		)
		lead = self.make_lead(lead_owner=owner)
		tasks = self.tasks_for(lead)
		self.assertEqual(len(tasks), 1)
		self.assertEqual(tasks[0].assigned_to, owner)
		self.assertEqual(
			frappe.utils.getdate(tasks[0].due_date),
			frappe.utils.getdate(frappe.utils.add_days(frappe.utils.nowdate(), 2)),
		)

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
		self.assertEqual(len(self.suggestions_for(deal)), 0)
		deal.status = statuses[1]
		deal.save()
		self.assertEqual(len(self.suggestions_for(deal)), 1)
		# saving again without a status change must not duplicate
		deal.reload()
		deal.probability = 50
		deal.save()
		self.assertEqual(len(self.suggestions_for(deal)), 1)

	def test_an_insert_does_not_also_fire_the_status_changed_rules(self):
		"""frappe runs on_update during the insert and has_value_changed answers True
		with no previous document, so every new record used to fire both rule sets."""
		make_rule(
			title="Any status change",
			trigger="Status Changed",
			to_status=None,
			action="Create Suggestion",
			title_template="Changed {{ doc.organization }}",
		)
		deal = self.make_deal()
		self.assertEqual(self.suggestions_for(deal), [])

	def test_a_task_is_not_stacked_by_a_flapping_status(self):
		statuses = frappe.get_all(
			"CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name", limit=2
		)
		make_rule(
			title="On any change", trigger="Status Changed", title_template="Chase {{ doc.organization }}"
		)
		deal = self.make_deal(status=statuses[0])
		for status in (statuses[1], statuses[0], statuses[1]):
			deal.status = status
			deal.save()
			deal.reload()
		self.assertEqual(len(self.tasks_for(deal)), 1)

	def test_rules_run_in_priority_order(self):
		# created low-priority-first, so the default `modified desc` sort would run
		# them the other way round -- which is the bug the priority field fixes
		make_rule(title="First", priority=1, title_template="A for {{ doc.organization }}")
		make_rule(title="Second", priority=10, title_template="B for {{ doc.organization }}")
		deal = self.make_deal()
		titles = [t.title for t in self.tasks_for(deal)]
		self.assertEqual(titles, ["A for Automation Org", "B for Automation Org"])

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

	def test_an_invalid_template_is_rejected_at_save(self):
		"""The engine swallows rule failures, so a template that will not compile is
		invisible to its author unless save says so."""
		with self.assertRaises(frappe.ValidationError):
			make_rule(title="Bad template", title_template="{{ doc.organization ")

	def test_a_template_cannot_call_methods_on_the_live_document(self):
		"""Templates render against as_dict(), like conditions already did — a title
		field is not a place from which doc.delete() should be reachable.

		Saved past the syntax check the way a rule broken in place would be, so what
		is under test is the render, not the validation in front of it."""
		rule = make_rule(title="Mutating")
		frappe.db.set_value(
			"CRM Automation Rule",
			rule.name,
			"title_template",
			"{{ doc.db_set('probability', 99) }}",
		)
		deal = self.make_deal(probability=10)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "probability"), 10)
		self.assertEqual(self.tasks_for(deal), [])


class SuggestionOwnershipTest(IntegrationTestCase):
	"""Reassignment moves the record's open suggestions with it."""

	def setUp(self):
		super().setUp()
		self.first = ensure_user("automation-rep-a@crmtest.test", "Rep A")
		self.second = ensure_user("automation-rep-b@crmtest.test", "Rep B")
		org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Reassign Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": org, "deal_owner": self.first}
		).insert()
		self.addCleanup(frappe.delete_doc, "CRM Deal", self.deal.name, force=True, ignore_missing=True)
		self.addCleanup(frappe.db.delete, "CRM Suggestion", {"reference_docname": self.deal.name})

	def make_suggestion(self, status="Open"):
		return (
			frappe.get_doc(
				{
					"doctype": "CRM Suggestion",
					"signal": "idle_deal",
					"title": "Re-engage",
					"reference_doctype": "CRM Deal",
					"reference_docname": self.deal.name,
					"user": self.first,
					"status": status,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	def test_reassigning_a_deal_moves_its_open_suggestions(self):
		name = self.make_suggestion()
		self.deal.deal_owner = self.second
		self.deal.save()
		self.assertEqual(frappe.db.get_value("CRM Suggestion", name, "user"), self.second)

	def test_a_settled_suggestion_stays_with_whoever_settled_it(self):
		name = self.make_suggestion(status="Dismissed")
		self.deal.deal_owner = self.second
		self.deal.save()
		self.assertEqual(frappe.db.get_value("CRM Suggestion", name, "user"), self.first)

	def test_deleting_the_deal_takes_its_suggestions_with_it(self):
		"""The Dynamic Link used to make the deal undeletable; now it deletes and
		leaves nothing pointing at a record that is gone.

		An unassigned deal, so the delete is not blocked by the notification an
		assignment leaves behind -- the suggestion link is what is under test.
		"""
		org = frappe.db.get_value("CRM Deal", self.deal.name, "organization")
		deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org}).insert()
		name = (
			frappe.get_doc(
				{
					"doctype": "CRM Suggestion",
					"signal": "idle_deal",
					"title": "Re-engage",
					"reference_doctype": "CRM Deal",
					"reference_docname": deal.name,
					"status": "Open",
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
		frappe.delete_doc("CRM Deal", deal.name)
		self.assertFalse(frappe.db.exists("CRM Suggestion", name))


class AutomationTemplateSandboxTest(IntegrationTestCase):
	"""Rule templates are authored by Sales Managers, so they get `doc` only.

	frappe.render_template hands a template the framework's globals, which still
	include frappe.db.sql and a get_all forced to ignore_permissions -- turning a
	title template into an arbitrary database read for a customer's line manager.
	"""

	def test_a_template_cannot_reach_the_database(self):
		"""`frappe` is not merely neutered in the context, it is absent -- so this
		raises rather than quietly rendering nothing."""
		from jinja2.exceptions import UndefinedError

		from crm.automation import render_rule_template

		with self.assertRaises(UndefinedError):
			render_rule_template("{{ frappe.db.sql('select 1') }}", frappe._dict())

	def test_a_template_cannot_reach_get_all(self):
		from jinja2.exceptions import UndefinedError

		from crm.automation import render_rule_template

		with self.assertRaises(UndefinedError):
			render_rule_template("{{ frappe.get_all('User', pluck='name') }}", frappe._dict())

	def test_doc_fields_still_render(self):
		"""The restriction must not cost the feature anything: every template in
		this app is {{ doc.field }}, which is what it is for."""
		from crm.automation import render_rule_template

		rendered = render_rule_template(
			"Follow up with {{ doc.organization }}", frappe._dict(organization="Acme")
		)
		self.assertEqual(rendered, "Follow up with Acme")

	def test_a_rule_reaching_for_frappe_is_refused_at_save(self):
		"""Because validation shares the renderer, the author is told at save
		time instead of the rule failing silently on somebody's deal later."""
		with self.assertRaises(frappe.ValidationError):
			make_rule(title="Exfiltrate", title_template="{{ frappe.db.sql('select 1') }}")
