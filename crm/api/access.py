# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Role visibility and the data-access boundary.

Two things live here, and the difference between them is the whole design.

``get_data_access`` / ``set_data_access`` are the *real* boundary: they move
``enable_sales_hierarchy`` and ``manager_outside_hierarchy``, which change what
the database returns. Administrator only.

``get_visibility`` / ``set_visibility`` are *chrome*: which nav links and
settings panes a role is shown. A manager may set the rep row; only an
administrator may set the manager row. The invariant that makes that safe is
that every consumer composes this with the role gate it already had --
``canSee(key) && isAdmin()``, never ``canSee(key)`` alone -- so configuration
can only ever hide a surface, never reveal one. ``crm/tests/test_access_settings.py``
asserts it against a real endpoint.

There is deliberately no System Manager row: nothing is hideable from an
administrator, so an administrator cannot configure themselves out of the pane
that would undo it.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cint

from crm.api.session import CRM_ALLOWED_ROLES
from crm.fcrm.doctype.crm_access_settings.crm_access_settings import CONFIGURABLE_ROLES

SETTINGS_DOCTYPE = "CRM Access Settings"

#: Shape-validated rather than checked against an allow-list, so the surface
#: registry lives in one place (frontend/src/utils/surfaces.js) instead of two.
#: An unrecognised key is inert: because config only narrows, the worst it can
#: do is fail to hide something.
SURFACE_KEY = re.compile(r"^(nav|settings)\.[a-z0-9_]{1,48}$")

#: A bound on how much one write may store. The registry is ~40 surfaces across
#: two roles; this leaves room to grow without leaving the table unbounded.
MAX_SURFACES = 200

MANAGER_SCOPES = ("All records", "Own records only")


def _effective_role(user: str | None = None) -> str:
	"""The single role the frontend reasons with, most privileged first.

	Mirrors ``crm.api.session.get_session_role_flags``, which keeps its three
	flags mutually exclusive. A user holding both Sales Manager and Sales User
	is a manager.
	"""
	user = user or frappe.session.user
	roles = frappe.get_roles(user)
	if user == "Administrator" or "System Manager" in roles:
		return "System Manager"
	if "Sales Manager" in roles:
		return "Sales Manager"
	return "Sales User"


def _require_crm_user() -> None:
	"""Any CRM role, which is the app's own definition of access.

	Not ``crm.utils.sales_user_only``: that helper's ``is_admin()`` means the
	literal Administrator account, so a user holding only ``System Manager`` --
	reachable via ``bench add-system-manager`` or the desk, and admitted to the
	CRM by ``crm.api.session.get_session_role_flags`` -- is refused by it. These
	two endpoints gate the shell's own chrome and the pane an administrator would
	use to fix their access, so they must not be the thing that locks an
	administrator out.
	"""
	if not set(frappe.get_roles()) & set(CRM_ALLOWED_ROLES):
		frappe.throw(
			_("You are not permitted to access CRM resources."),
			frappe.PermissionError,
		)


def _hidden_for(role: str) -> list[str]:
	"""Surfaces hidden for ``role``. Always empty for an administrator."""
	if role not in CONFIGURABLE_ROLES:
		return []
	return frappe.get_all(
		"CRM Role Surface",
		filters={"parenttype": SETTINGS_DOCTYPE, "role": role},
		pluck="surface",
		# CRM Role Surface's own sort_field/sort_order is ("creation", "DESC"),
		# so an unordered fetch would silently return rows newest-first instead
		# of the child-table order the desk form (and this API's callers) expect.
		order_by="idx asc",
	)


def manager_outside_hierarchy_sees_all() -> bool:
	"""Whether a Sales Manager who is not in the tree reads the whole site.

	``get_single_value`` reads ``tabSingles`` and returns ``None`` for a Single
	that has never been saved, so the historical answer has to be the fallback
	here and not only the field default -- otherwise installing this feature
	would silently narrow every existing site on the next request.

	Deliberately uncached, for the reason ``org_hierarchy._in_hierarchy`` gives:
	``frappe.local.request_cache`` lives for a whole scheduler process, so a
	setting changed mid-run would read stale until a restart.
	"""
	value = frappe.db.get_single_value(SETTINGS_DOCTYPE, "manager_outside_hierarchy")
	return (value or "All records") == "All records"


# --- surface visibility ----------------------------------------------------


@frappe.whitelist()
def get_visibility() -> dict:
	"""What the session user's shell should hide, plus the matrix if they may see it.

	``hidden`` is the caller's own row and is all ``AppSidebar`` and ``Settings``
	need. ``matrix`` is populated for an administrator or a manager -- the pane's
	data arrives with the same call that gates the sidebar -- and ``None`` for a
	rep, who has no business holding another role's configuration.
	"""
	_require_crm_user()
	role = _effective_role()
	matrix = None
	if role in ("System Manager", "Sales Manager"):
		matrix = {configurable: _hidden_for(configurable) for configurable in CONFIGURABLE_ROLES}
	return {"role": role, "hidden": _hidden_for(role), "matrix": matrix}


def _validated_keys(hidden) -> list[str]:
	if isinstance(hidden, str):
		hidden = frappe.parse_json(hidden)
	if hidden is None:
		hidden = []
	if not isinstance(hidden, list):
		frappe.throw(_("Hidden surfaces must be a list."))
	if len(hidden) > MAX_SURFACES:
		frappe.throw(_("At most {0} surfaces may be hidden at once.").format(MAX_SURFACES))

	keys = []
	for key in hidden:
		if not isinstance(key, str) or not SURFACE_KEY.match(key):
			frappe.throw(_("{0} is not a surface key.").format(key))
		if key not in keys:
			keys.append(key)
	return keys


@frappe.whitelist()
def set_visibility(role: str, hidden: list | str) -> dict:
	"""Replace ``role``'s hidden set.

	A whole-row replace rather than add/remove: the pane posts the row it is
	showing, so there is no read-modify-write window in which two managers
	editing at once lose each other's changes.

	Saved with ``ignore_permissions`` because the doctype is administrator-only
	by design -- this endpoint *is* the manager's authorisation, and the check
	above is the rule. Same shape as ``crm.api.suggestions``, which says the
	same thing about its own state machine.
	"""
	frappe.only_for(["System Manager", "Sales Manager"], True)

	if role not in CONFIGURABLE_ROLES:
		frappe.throw(
			_("{0} is not a configurable role. Nothing can be hidden from an administrator.").format(role)
		)

	if "System Manager" not in frappe.get_roles() and role != "Sales User":
		frappe.throw(
			_("Only an administrator can change what managers see."),
			frappe.PermissionError,
		)

	keys = _validated_keys(hidden)

	settings = frappe.get_single(SETTINGS_DOCTYPE)
	settings.hidden_surfaces = [row for row in settings.hidden_surfaces if row.role != role]
	for key in keys:
		settings.append("hidden_surfaces", {"role": role, "surface": key})
	settings.save(ignore_permissions=True)

	return {"role": role, "hidden": keys}


# --- data access -----------------------------------------------------------


@frappe.whitelist()
def get_data_access() -> dict:
	"""The two switches that actually change what the database returns.

	Readable by anyone in the CRM so the pane can render for a manager as
	read-only context -- knowing the site scopes by hierarchy leaks nothing, and
	a manager seeing "your team only" explains their own numbers to them.
	"""
	_require_crm_user()
	return {
		"enable_sales_hierarchy": frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy") or 0,
		"manager_outside_hierarchy": frappe.db.get_single_value(SETTINGS_DOCTYPE, "manager_outside_hierarchy")
		or "All records",
		"hierarchy_size": frappe.db.count("CRM Sales Hierarchy"),
	}


@frappe.whitelist()
def set_data_access(
	enable_sales_hierarchy: int | str | None = None,
	manager_outside_hierarchy: str | None = None,
) -> dict:
	"""Move the real boundary. Administrator only.

	Not a Sales Manager: widening this is how a manager would reach another
	team's compensation figures, which is the invariant SECURITY.md names.
	"""
	frappe.only_for("System Manager", True)

	if enable_sales_hierarchy is not None:
		frappe.db.set_single_value(
			"FCRM Settings", "enable_sales_hierarchy", 1 if cint(enable_sales_hierarchy) else 0
		)

	if manager_outside_hierarchy is not None:
		if manager_outside_hierarchy not in MANAGER_SCOPES:
			frappe.throw(
				_("{0} is not a valid setting. Choose one of: {1}.").format(
					manager_outside_hierarchy, ", ".join(MANAGER_SCOPES)
				)
			)
		frappe.db.set_single_value(SETTINGS_DOCTYPE, "manager_outside_hierarchy", manager_outside_hierarchy)

	return get_data_access()
