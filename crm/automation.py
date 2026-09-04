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

from datetime import timedelta

import frappe
from jinja2.sandbox import SandboxedEnvironment

from crm.agent.config import get_signal_config
from crm.agent.signals import (
	TITLE_MAX_LENGTH,
	clear_suggestions_for,
	resync_owner,
	suggestion_blocked,
	user_at_open_cap,
)
from crm.fcrm.doctype.crm_task.crm_task import TERMINAL_STATUSES

OWNER_FIELD = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}

# Urgency for a rule's suggestion when the rule does not set one. Sits between
# crm.agent.signals' NO_NEXT_STEP_SCORE (40) and SLA_BREACH_SCORE (80), because
# an admin-authored rule is a deliberate statement and should outrank a routine
# nudge -- but a breached SLA is still the more urgent thing. Rules may now say
# otherwise per rule, which is the point: this is only the default.
DEFAULT_RULE_SUGGESTION_SCORE = 60.0
MIN_RULE_SUGGESTION_SCORE = 0.0
MAX_RULE_SUGGESTION_SCORE = 100.0


def rule_suggestion_score(value) -> float:
	"""The rule's urgency, clamped into the band the inbox sorts on.

	Unset reads as the default rather than as zero: a rule saved before the field
	existed holds 0, and taking that literally would file every one of their
	suggestions below everything else without anyone having asked for it. An
	explicit 0 is still reachable -- the migration patch fills the old rows in, so
	a 0 that survives it is one somebody typed.
	"""
	if value in (None, ""):
		return DEFAULT_RULE_SUGGESTION_SCORE
	return max(MIN_RULE_SUGGESTION_SCORE, min(MAX_RULE_SUGGESTION_SCORE, frappe.utils.flt(value)))


# Rule templates get `doc` and nothing else -- see render_rule_template below.
_TEMPLATE_ENV = SandboxedEnvironment(autoescape=False)


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
			"suggestion_score",
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


def render_rule_template(template, doc_dict) -> str:
	"""Render a rule template with ``doc`` in scope and nothing else.

	``frappe.render_template`` hands the template frappe's global helpers, and
	those still include ``frappe.db.sql`` and a ``get_all`` forced to
	``ignore_permissions=True``. Rule authoring is granted to **Sales Manager** —
	a customer's line manager — so that made a title template an arbitrary
	database read: put the query in the title, read the answer off the task it
	creates. The framework's ``check_safe_sql_query`` only rejects non-SELECT,
	which is exactly the wrong half for a read.

	A plain sandboxed environment with a one-key context closes it. Nothing is
	lost: every template in this app is ``{{ doc.field }}``, which is what the
	feature is for. Autoescape stays off because these render into a task's
	title and description, which are plain-text fields — turning it on would
	start writing &amp; into people's task titles.

	The dict rather than the live Document is kept from the previous version:
	the Jinja sandbox already refuses ``doc.save()`` and friends, but a future
	sandbox regression should not be able to turn a template into a write.
	"""
	return _TEMPLATE_ENV.from_string(template or "").render(doc=doc_dict)


def _apply(rule, doc) -> None:
	doc_dict = doc.as_dict()
	owner = doc.get(OWNER_FIELD.get(doc.doctype)) if rule.assign_to_owner else None
	# CRM Suggestion.title and CRM Task.title are Data(140); a template that
	# interpolates an organization name can overflow that and raise out of the save
	title = (render_rule_template(rule.title_template, doc_dict) or rule.name)[:TITLE_MAX_LENGTH]
	description = render_rule_template(rule.description_template, doc_dict)

	if rule.action == "Create Task":
		# Status flapping must not stack duplicate tasks for the same record.
		# Keyed on the rule, not the rendered title: a template interpolating a
		# mutable field ("Follow up: {{ doc.status }}") renders a fresh title
		# per flap and walked straight past a title-keyed guard, while two
		# distinct rules that happen to render the same title are two
		# instructions and used to suppress each other. The title arm survives
		# only for rows created before the field existed.
		open_statuses = ("not in", TERMINAL_STATUSES)
		duplicate = frappe.db.exists(
			"CRM Task",
			{
				"automation_rule": rule.name,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"status": open_statuses,
			},
		) or frappe.db.exists(
			"CRM Task",
			{
				"automation_rule": ("is", "not set"),
				"title": title,
				"reference_doctype": doc.doctype,
				"reference_docname": doc.name,
				"status": open_statuses,
			},
		)
		if duplicate:
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
				"automation_rule": rule.name,
			}
		).insert(ignore_permissions=True)

	elif rule.action == "Create Suggestion":
		signal = f"rule:{rule.name}"
		# The same lifecycle the hourly signals honour, not a bare Open-only
		# check: an Open row blocks, and so do the dismiss/accept cooldowns and
		# the repeat-dismisser multiplier -- a rep who said no to this rule's
		# suggestion must not be overruled by the next status flap.
		if suggestion_blocked(signal, doc.name, owner):
			return
		# And the same ceiling: a bulk import firing Created rules must not
		# write past the rep's cap and leave the hourly trim to mop up.
		if user_at_open_cap(owner, get_signal_config().max_open_per_user):
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
				"score": rule_suggestion_score(rule.suggestion_score),
				# the same TTL the hourly signals use, or a rule's row never expires
				# and sits in the inbox until someone clears it by hand
				"expires_on": frappe.utils.now_datetime()
				+ timedelta(days=get_signal_config().suggestion_ttl_days),
			}
		).insert(ignore_permissions=True)

		if owner:
			# a rule that fires on save should light up the owner's inbox now, not
			# at their next page load — same event the hourly signal run emits
			from crm.agent.signals import publish_new_suggestions

			publish_new_suggestions({owner})
