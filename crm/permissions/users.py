"""Who may query the User table, and what a user picker may ask of it.

Frappe grants every desk user ``select`` on User so link pickers can list
colleagues. User is one of frappe's core doctypes, and for those the query layer
skips field-level read checks (``frappe.model.get_permitted_fields`` returns every
column). So ``select`` was a full read: a rep could ask ``frappe.client.get_list``
for any colleague's ``last_login``, ``last_ip``, ``last_active``, phone or birth
date, or probe them through a filter. permlevel cannot help, because the query
layer never looks at it for User.

So the right is withdrawn (``close_user_select``) and the one thing it was for,
the user picker, goes through ``user_link_query`` instead. That query returns a
name and a full name only, and filters only on columns that say no more than that.
The CRM's own reads of User run server-side through ``frappe.get_all`` and never
needed the right.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, sbool

# The role frappe gives every desk user, and with it select on User.
DESK_USER_ROLE = "Desk User"

# Columns a picker may filter or search on. Each one says no more than the name
# and full name the picker shows anyway, or which kind of account it is.
PICKER_FILTER_FIELDS = frozenset(
	{"name", "email", "full_name", "first_name", "middle_name", "last_name", "enabled", "user_type"}
)
SEARCH_FIELDS = ("name", "full_name", "first_name", "middle_name", "last_name")


def close_user_select() -> None:
	"""Withdraw the desk-user ``select`` right on User.

	Frappe reads a doctype's permissions from Custom DocPerm once any row exists
	for it, so the standard rules are copied there first (the same step the Role
	Permission Manager takes) and the Desk User row is dropped. System Manager
	keeps its rows. Idempotent; runs from after_install and after_migrate. The
	copied rules are frozen at the frappe version that first ran this, so a later
	frappe change to User's standard rules will not reach the site on its own.
	"""
	from frappe.permissions import setup_custom_perms

	created = setup_custom_perms("User")
	rows = frappe.get_all("Custom DocPerm", filters={"parent": "User", "role": DESK_USER_ROLE}, pluck="name")
	for name in rows:
		frappe.delete_doc("Custom DocPerm", name, ignore_permissions=True, force=True)
	if created or rows:
		frappe.clear_cache(doctype="User")


# Operators a picker filter may use; anything else is refused.
PICKER_OPERATORS = frozenset({"=", "!=", "in", "not in", "like", "not like"})
# The most a picker may ask for in one call, whatever page_len says.
MAX_PAGE_LENGTH = 100


def restore_user_select() -> None:
	"""Put the desk-user ``select`` rule back, for uninstall: without crm's
	``user_link_query`` frappe's own picker needs it, and every User link field on
	the site would otherwise come back empty. Other rows an admin set are kept."""
	if not frappe.db.exists("Custom DocPerm", {"parent": "User"}):
		return
	if frappe.db.exists("Custom DocPerm", {"parent": "User", "role": DESK_USER_ROLE, "permlevel": 0}):
		return
	frappe.get_doc(
		{
			"doctype": "Custom DocPerm",
			"parent": "User",
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": DESK_USER_ROLE,
			"permlevel": 0,
			"select": 1,
		}
	).insert(ignore_permissions=True)
	frappe.clear_cache(doctype="User")


def _refuse(what: Any) -> None:
	raise frappe.PermissionError(_("Not permitted to filter users on {0}").format(frappe.as_json(what)))


def _condition(fieldname: Any, operator: Any, value: Any) -> list:
	"""One checked ``[field, op, value]``. The field and operator checked are the
	ones returned: nothing the caller sent is passed on unchecked."""
	if not isinstance(fieldname, str) or fieldname not in PICKER_FILTER_FIELDS:
		_refuse(fieldname)
	if not isinstance(operator, str) or operator.lower() not in PICKER_OPERATORS:
		_refuse(operator)
	return [fieldname, operator.lower(), value]


def _list_condition(condition: Any) -> list:
	"""``[field, value]``, ``[field, op, value]`` or ``["User", field, op, value]``,
	and no other shape: a longer row once let the checked element differ from the
	one queried."""
	if not isinstance(condition, list | tuple):
		_refuse(condition)
	if len(condition) == 2:
		return _condition(condition[0], "=", condition[1])
	if len(condition) == 3:
		return _condition(*condition)
	if len(condition) == 4 and condition[0] == "User":
		return _condition(*condition[1:])
	_refuse(condition)


def _picker_filters(filters: Any) -> tuple[list, bool]:
	"""The caller's filters as checked conditions, refused if any names a column
	outside ``PICKER_FILTER_FIELDS``, an operator outside ``PICKER_OPERATORS``, or
	has any other shape. Returns the conditions and whether ``ignore_user_type``
	was asked for."""
	if not filters:
		return [], False
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)

	if isinstance(filters, dict):
		filters = dict(filters)
		ignore_user_type = sbool(filters.pop("ignore_user_type", False)) is True
		conditions = []
		for fieldname, value in filters.items():
			if isinstance(value, list | tuple):
				if len(value) != 2:
					_refuse({fieldname: value})
				conditions.append(_condition(fieldname, value[0], value[1]))
			else:
				conditions.append(_condition(fieldname, "=", value))
		return conditions, ignore_user_type
	if isinstance(filters, list | tuple):
		return [_list_condition(condition) for condition in filters], False
	_refuse(filters)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def user_link_query(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: Any):
	"""The User link search, in place of frappe's ``user_query``.

	Same rows as frappe's: enabled accounts, not website users unless a desk user
	asks with ``ignore_user_type``. Read with ``get_all`` because the caller no
	longer holds select on User, so this function is the access check: desk users
	only, a fixed pair of columns out, and filters only on ``PICKER_FILTER_FIELDS``.
	"""
	# frappe gives Desk User to every account of type System User, and only to those
	if DESK_USER_ROLE not in frappe.get_roles():
		raise frappe.PermissionError(_("Not permitted"))

	conditions, ignore_user_type = _picker_filters(filters)
	conditions += [["enabled", "=", 1], ["docstatus", "<", 2]]
	if not ignore_user_type:
		conditions.append(["user_type", "!=", "Website User"])

	or_filters = None
	if txt:
		fields = SEARCH_FIELDS if searchfield in SEARCH_FIELDS else ("name",)
		or_filters = [[field, "like", f"%{txt}%"] for field in fields]

	return frappe.get_all(
		"User",
		filters=conditions,
		or_filters=or_filters,
		fields=["name", "full_name"],
		limit_start=max(cint(start), 0),
		# 0 means "no limit" to get_all
		limit_page_length=min(max(cint(page_len), 1), MAX_PAGE_LENGTH),
		order_by="name asc",
		as_list=True,
	)
