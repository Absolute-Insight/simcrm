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

from crm.agent.signals import clear_suggestions_for, resync_owner

OWNER_FIELD = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}


def run_automations(doc, method=None):
	"""doc_events entry point for CRM Lead and CRM Deal."""
	if frappe.flags.in_install or frappe.flags.in_migrate or frappe.flags.in_patch:
		return

	if method == "on_update":
		_resync_suggestion_owner(doc)

	if method == "after_insert":
		trigger = "Created"
	elif method == "on_update" and _status_just_changed(doc):
		trigger = "Status Changed"
	else:
		return

	rules = frappe.get_all(
		"CRM Automation Rule",
		filters={"enabled": 1, "document_type": doc.doctype, "trigger": trigger},
		fields=[
			"name",
			"priority",
			"to_status",
			"condition",
			"action",
			"title_template",
			"description_template",
			"task_priority",
			"due_in_days",
			"assign_to_owner",
		],
		# without an explicit order the runner inherits `modified desc`, so editing
		# any rule silently reorders every other rule's effects
		order_by="priority asc, name asc",
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


def _status_just_changed(doc) -> bool:
	"""True only for a real transition on an existing record.

	frappe runs ``on_update`` as part of the insert too, and ``has_value_changed``
	answers True there because there is no previous document to compare against --
	so every new record used to fire the Created *and* the Status Changed rules.
	"""
	if doc.flags.in_insert or not doc.get_doc_before_save():
		return False
	return doc.has_value_changed("status")


def _resync_suggestion_owner(doc) -> None:
	"""Follow a reassignment with the record's open suggestions.

	Nothing else moves them: a reassigned deal kept nagging the previous rep for
	the rest of the suggestion TTL while staying invisible to the rep who
	inherited it.
	"""
	field = OWNER_FIELD.get(doc.doctype)
	if not field or doc.flags.in_insert or not doc.get_doc_before_save():
		return
	if doc.has_value_changed(field):
		resync_owner(doc.doctype, doc.name, doc.get(field))


def clear_suggestions(doc, method=None) -> None:
	"""on_trash entry point: a deleted record leaves no suggestions behind."""
	clear_suggestions_for(doc.doctype, doc.name)


def _matches(rule, doc) -> bool:
	if rule.to_status and _status_label(doc) != rule.to_status:
		return False
	if rule.condition:
		return bool(frappe.safe_eval(rule.condition, eval_locals={"doc": doc.as_dict()}))
	return True


def _status_label(doc) -> str | None:
	return doc.status


def _render(template, doc_dict) -> str:
	"""Render against a plain dict, never the live Document.

	Measured on this frappe version, the Jinja sandbox already refuses
	``doc.delete()``, ``doc.save()`` and ``doc.db_set()`` on a live Document, so
	this is defence in depth rather than the only thing standing in the way. It
	is still worth doing: it matches the condition path, which passes
	``as_dict()`` too, and it means a future sandbox regression cannot turn a
	template field into a write primitive.
	"""
	# nosemgrep: the template is authored by a Sales Manager, validated at save,
	# and rendered against a plain dict rather than the live Document
	return frappe.render_template(template or "", {"doc": doc_dict})


def _apply(rule, doc) -> None:
	doc_dict = doc.as_dict()
	owner = doc.get(OWNER_FIELD.get(doc.doctype)) if rule.assign_to_owner else None
	title = _render(rule.title_template, doc_dict) or rule.name
	description = _render(rule.description_template, doc_dict)

	if rule.action == "Create Task":
		# status flapping must not stack duplicate tasks for the same record
		if frappe.db.exists(
			"CRM Task",
			{
				"title": title,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"status": ("not in", ("Done", "Canceled")),
			},
		):
			return
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

		if owner:
			# a rule that fires on save should light up the owner's inbox now, not
			# at their next page load — same event the hourly signal run emits
			from crm.agent.signals import publish_new_suggestions

			publish_new_suggestions({owner})
