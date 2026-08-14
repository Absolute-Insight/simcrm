# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deterministic automation: trigger -> condition -> action.

Admin-authored ``CRM Automation Rule`` records run on lead/deal lifecycle
events. This engine is model-free and must behave identically with the agent
tier disabled (PLAN.md Phase 8, constraint 3). A broken rule may never block
the save that triggered it: every rule runs inside its own try/except and
failures are logged, not raised.
"""

from __future__ import annotations

import frappe

OWNER_FIELD = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}


def run_automations(doc, method=None):
	"""doc_events entry point for CRM Lead and CRM Deal."""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	if method == "after_insert":
		trigger = "Created"
	elif method == "on_update" and doc.has_value_changed("status"):
		trigger = "Status Changed"
	else:
		return

	rules = frappe.get_all(
		"CRM Automation Rule",
		filters={"enabled": 1, "document_type": doc.doctype, "trigger": trigger},
		fields=[
			"name",
			"to_status",
			"condition",
			"action",
			"title_template",
			"description_template",
			"task_priority",
			"due_in_days",
			"assign_to_owner",
		],
	)
	for rule in rules:
		try:
			if _matches(rule, doc):
				_apply(rule, doc)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"CRM Automation Rule {rule.name} failed on {doc.doctype} {doc.name}",
			)


def _matches(rule, doc) -> bool:
	if rule.to_status and _status_label(doc) != rule.to_status:
		return False
	if rule.condition:
		return bool(frappe.safe_eval(rule.condition, eval_locals={"doc": doc.as_dict()}))
	return True


def _status_label(doc) -> str | None:
	return doc.status


def _render(template, doc) -> str:
	return frappe.render_template(template or "", {"doc": doc})


def _apply(rule, doc) -> None:
	owner = doc.get(OWNER_FIELD.get(doc.doctype)) if rule.assign_to_owner else None
	title = _render(rule.title_template, doc) or rule.name
	description = _render(rule.description_template, doc)

	if rule.action == "Create Task":
		frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": title,
				"description": description,
				"priority": rule.task_priority or "Medium",
				"status": "Todo",
				"due_date": frappe.utils.add_days(frappe.utils.now_datetime(), rule.due_in_days or 0),
				"assigned_to": owner,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
			}
		).insert(ignore_permissions=True)

	elif rule.action == "Create Suggestion":
		signal = f"rule:{rule.name}"
		# status flapping must not stack duplicates for the same record
		if frappe.db.exists(
			"CRM Suggestion",
			{
				"signal": signal,
				"reference_docname": doc.name,
				"status": "Open",
			},
		):
			return
		frappe.get_doc(
			{
				"doctype": "CRM Suggestion",
				"signal": signal,
				"title": title,
				"rationale": description or title,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"user": owner,
				"suggested_action": "create_task",
				"action_payload": frappe.as_json({"title": title}),
				"status": "Open",
				"score": 60.0,
			}
		).insert(ignore_permissions=True)
