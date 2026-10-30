"""What the command palette reads: records, the ones opened recently, and what is due.

Every record comes through ``frappe.get_list`` and every due item is filtered to
the session user, so the palette names no record that user could not open.
"""

from collections import defaultdict

import frappe
from frappe.utils import add_days, add_to_date, now_datetime, nowdate

from crm.api.access import _require_crm_user

SEARCH_LIMIT = 5
UPCOMING_LIMIT = 5
MAX_QUERY_LENGTH = 140
MIN_QUERY_LENGTH = 2

UPCOMING_TASK_DAYS = 7
# Anything older than this is backlog, not something to surface as upcoming.
OVERDUE_GRACE_DAYS = 3
CLOSED_TASK_STATUSES = ["Done", "Canceled"]

# `detail` tells apart rows that share a title: a customer's deals all carry its
# name. The acumatica_* columns are custom fields, so they are read through
# _existing_fields rather than assumed.
SEARCH_TYPES = {
	"CRM Lead": {
		"route": "Lead",
		"title": "lead_name",
		"detail": "organization",
		"search": ["lead_name", "organization", "email", "mobile_no"],
	},
	"CRM Deal": {
		"route": "Deal",
		"title": "organization",
		"detail": "acumatica_sales_quote",
		"search": [
			"organization",
			"lead_name",
			"email",
			"mobile_no",
			"acumatica_sales_quote",
			"acumatica_customer",
		],
	},
	"Contact": {
		"route": "Contact",
		"title": "full_name",
		"detail": "company_name",
		"search": ["full_name", "email_id", "mobile_no", "company_name", "acumatica_id"],
	},
	"CRM Organization": {
		"route": "Organization",
		"title": "organization_name",
		"detail": "acumatica_id",
		"search": ["organization_name", "website", "acumatica_id"],
	},
}


@frappe.whitelist()
def search(query: str = "", recent_names: str | None = None):
	"""Records matching ``query``; with no query, recent records and what is due."""
	_require_crm_user()
	query = (query or "").strip()[:MAX_QUERY_LENGTH]
	return {
		"matches": _search_all(query) if len(query) >= MIN_QUERY_LENGTH else [],
		"recent": _readable_records(_parse_recent(recent_names)) if not query else [],
		"upcoming": _get_upcoming() if not query else [],
	}


def _search_all(query: str):
	results = []
	for doctype, config in SEARCH_TYPES.items():
		if frappe.has_permission(doctype, "read"):
			results.extend(_search_doctype(doctype, config, query))
	return results


def _search_doctype(doctype: str, config: dict, query: str):
	search_fields = _existing_fields(doctype, config["search"])
	rows = frappe.get_list(
		doctype,
		fields=_record_fields(doctype, config, search_fields),
		or_filters=[[field, "like", f"%{query}%"] for field in ["name", *search_fields]],
		order_by="modified desc",
		limit_page_length=SEARCH_LIMIT,
	)
	return [{**_record(row, doctype, config), "keywords": _keywords(row, search_fields)} for row in rows]


def _existing_fields(doctype: str, fields: list[str]) -> list[str]:
	meta = frappe.get_meta(doctype)
	return [field for field in fields if meta.has_field(field)]


def _record_fields(doctype: str, config: dict, search_fields: list[str] | None = None) -> list[str]:
	fields = ["name", config["title"], *_existing_fields(doctype, [config["detail"]]), *(search_fields or [])]
	return list(dict.fromkeys(fields))


def _keywords(row, search_fields: list[str]) -> str:
	"""Every matchable value, so the client can rank a title hit above the rest."""
	return " ".join(str(row.get(field)) for field in ["name", *search_fields] if row.get(field))


def _record(row, doctype: str, config: dict) -> dict:
	return {
		"doctype": doctype,
		"name": row.name,
		"title": row.get(config["title"]) or row.name,
		"detail": row.get(config["detail"]),
		"route": config["route"],
	}


def _parse_recent(value: str | None) -> dict:
	try:
		recent = frappe.parse_json(value or "{}")
	except (TypeError, ValueError):
		return {}
	return recent if isinstance(recent, dict) else {}


def _readable_records(names_by_doctype: dict) -> list[dict]:
	"""The named records the session user can read; anything else simply does not come back."""
	results = []
	for doctype, names in names_by_doctype.items():
		if doctype in SEARCH_TYPES and isinstance(names, list) and frappe.has_permission(doctype, "read"):
			results.extend(_records_of(doctype, [n for n in names if isinstance(n, str)][:SEARCH_LIMIT]))
	return results


def _records_of(doctype: str, names: list[str]) -> list[dict]:
	if not names:
		return []
	config = SEARCH_TYPES[doctype]
	rows = frappe.get_list(
		doctype,
		fields=_record_fields(doctype, config),
		filters={"name": ["in", names]},
		limit_page_length=SEARCH_LIMIT,
	)
	by_name = {row.name: row for row in rows}
	return [_record(by_name[name], doctype, config) for name in names if name in by_name]


def _get_upcoming() -> list[dict]:
	"""The session user's planned activity, then their tasks due soon.

	Not merged by date: a backlog of overdue tasks would push today's visits off a
	shared list, and the plan is what a rep's day is built around.
	"""
	return _planned_activity() + _upcoming_tasks()


def _planned_activity() -> list[dict]:
	today = nowdate()
	tomorrow = add_days(today, 1)
	plan = frappe.qb.DocType("CRM Rep Plan")
	item = frappe.qb.DocType("CRM Rep Plan Item")
	rows = (
		frappe.qb.from_(item)
		.join(plan)
		.on(item.parent == plan.name)
		.select(item.name, item.activity_type, item.planned_date, item.organization, item.note)
		.where(plan.user == frappe.session.user)
		.where(item.status == "Planned")
		.where(item.planned_date.between(today, tomorrow))
		.orderby(item.planned_date)
		.limit(UPCOMING_LIMIT)
	).run(as_dict=True)
	return [
		{
			"kind": "plan",
			"name": row.name,
			"title": row.organization or row.note or row.activity_type,
			"label": row.activity_type,
			"due": str(row.planned_date),
			"when": "Today" if str(row.planned_date) == today else "Tomorrow",
			"route": "Planner",
			"route_name": None,
		}
		for row in rows
	]


def _upcoming_tasks() -> list[dict]:
	if not frappe.has_permission("CRM Task", "read"):
		return []
	now = now_datetime()
	rows = frappe.get_list(
		"CRM Task",
		fields=["name", "title", "due_date", "reference_doctype", "reference_docname"],
		filters={
			"status": ["not in", CLOSED_TASK_STATUSES],
			"assigned_to": frappe.session.user,
			"due_date": [
				"between",
				[add_days(now, -OVERDUE_GRACE_DAYS), add_to_date(now, days=UPCOMING_TASK_DAYS)],
			],
		},
		order_by="due_date asc",
		limit_page_length=UPCOMING_LIMIT,
	)
	openable = _openable_references(rows)
	return [_upcoming_task(row, openable) for row in rows]


def _openable_references(rows) -> set[tuple[str, str]]:
	"""Which task references the session user can open. A rep can hold a task on a
	record they cannot read, and a forced delete leaves a reference to nothing."""
	names = defaultdict(list)
	for row in rows:
		if row.reference_docname:
			names[row.reference_doctype].append(row.reference_docname)
	return {(record["doctype"], record["name"]) for record in _readable_records(names)}


def _upcoming_task(row, openable: set[tuple[str, str]]) -> dict:
	opens_record = (row.reference_doctype, row.reference_docname) in openable
	return {
		"kind": "task",
		"name": row.name,
		"title": row.title,
		"label": "Task",
		"due": str(row.due_date),
		"route": SEARCH_TYPES[row.reference_doctype]["route"] if opens_record else "Tasks",
		"route_name": row.reference_docname if opens_record else None,
	}
