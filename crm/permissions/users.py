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


def _filter_fieldname(condition: Any) -> str | None:
	"""The column a list-form filter names: ``[field, op, value]`` or
	``[doctype, field, op, value]``."""
	if isinstance(condition, list | tuple):
		if len(condition) >= 4:
			return condition[1]
		if condition:
			return condition[0]
	return None


def _picker_filters(filters: Any) -> tuple[list, bool]:
	"""The caller's filters, refused if any names a column outside the picker's
	set. Returns the conditions and whether ``ignore_user_type`` was asked for."""
	if not filters:
		return [], False
	if isinstance(filters, str):
		filters = frappe.parse_json(filters)

	ignore_user_type = False
	conditions: list = []
	if isinstance(filters, dict):
		filters = dict(filters)
		ignore_user_type = bool(filters.pop("ignore_user_type", False))
		items = list(filters.items())
		for fieldname, _value in items:
			if fieldname not in PICKER_FILTER_FIELDS:
				raise frappe.PermissionError(_("Not permitted to filter users on {0}").format(fieldname))
		conditions = [
			[fieldname, "=", value] if not isinstance(value, list | tuple) else [fieldname, *value]
			for fieldname, value in items
		]
	elif isinstance(filters, list | tuple):
		for condition in filters:
			fieldname = _filter_fieldname(condition)
			if fieldname not in PICKER_FILTER_FIELDS:
				raise frappe.PermissionError(_("Not permitted to filter users on {0}").format(fieldname))
			conditions.append(list(condition[-3:]))
	else:
		raise frappe.PermissionError(_("Not permitted"))
	return conditions, ignore_user_type


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
		limit_start=start,
		limit_page_length=page_len,
		order_by="name asc",
		as_list=True,
	)
