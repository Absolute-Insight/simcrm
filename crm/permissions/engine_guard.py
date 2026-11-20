"""Three things a request could ask of a list, and no longer can.

All three come down to frappe letting the caller of a list say whose permissions
apply to it. ``frappe.database.query.Engine`` is the builder ``frappe.get_list``
and the report view use on the pinned frappe (17.0.0-dev).

1. **A borrowed parent.** A caller names a ``parent_doctype`` for a list, and
   permissions are then taken from that parent. When the parent is a Single none
   are added at all: ``Engine.add_permission_conditions`` returns early with
   "permissions are already checked by has_permission". Nothing checks that the
   listed doctype is a child table of that parent, and for a doctype that is not
   a child table ``frappe.has_permission`` ignores the parent altogether. So
   ``frappe.client.get_list("CRM Deal", parent="System Settings")`` listed every
   deal to anyone with the role-level right: past User Permissions, ``if_owner``,
   shares, and every ``permission_query_conditions`` in hooks.py, which is how
   this app keeps one rep's leads, deals and customers from another. The parent
   arrives as a request parameter (``frappe.client.get_list`` / ``get_value``,
   ``frappe.desk.reportview.get`` / ``get_count`` / ``export_query``,
   ``/api/resource/<doctype>?parent=``) or inside a number card or dashboard
   chart the request describes (``parent_document_type``). ``install`` wraps
   ``Engine.check_select_permission``: a list whose parent has no table field
   for the listed doctype is refused before anything else is checked.

2. **A child table shared with a Single.** The same early return also leaves out
   *which* parent a row belongs to. A child doctype used by a Single and by an
   ordinary doctype (``Event Notifications``: FCRM Settings and Event) passed
   check 1 honestly under the Single, and the list then held every Event's rows
   too. ``install`` wraps ``Engine.add_permission_conditions``: under a Single
   parent the rows are limited to ``parenttype`` = that Single.

3. **``ignore_user_permissions`` from the request.** ``frappe.desk.reportview``
   does not strip it, so the report view, its count and export, and the kanban
   read it from the request and skip User Permission conditions. This app mirrors
   User Permissions between Item and CRM Product, so an administrator's
   restriction was one parameter deep. ``guard_request`` deletes that one key
   from ``frappe.form_dict`` unless the method called is in
   ``frappe.desk.search``, which honours it only after checking that the link
   field named has the option set. It touches nothing else of the request.

What this does not do. A virtual doctype's list never reaches the builder (its
controller answers), so nothing here applies to one. A System Manager who adds a
Table custom field makes a real parent of that doctype, and check 1 passes for
it; that is theirs to do. And ``frappe.model.db_query.DatabaseQuery``, the older
builder, only gets check 1: frappe no longer calls it and neither does this app,
it never joined a child to its parent for any parent, and it may be removed, in
which case there is nothing of it to guard.

Runs as ``before_request`` and ``before_job`` rather than at import, for the
reason document_guard gives: hooks are served from cache and nothing of this app
is imported in a process until one of its hooks runs. That cache also outlives a
restart onto new code until a migrate clears it, so
``document_guard.reserve_action``, which older hook lists already name, calls
this too. ``ensure_installed`` fails a migrate when an ``Engine`` method is no
longer there to wrap, so a frappe that renamed one is noticed on the day of the
upgrade and not by a rep reading another's pipeline. Remove each part once the
frappe pin does it itself; ``test_engine_guard`` has a test per part that fails
on that day.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

_MARK = "_crm_parent_guard"
_FLAG = "ignore_user_permissions"
_SEARCH = "frappe.desk.search."
# /api/method/<method> and /api/v1/method/<method> call the first segment;
# /api/v2/method/<method> calls it only when it is the whole path
_RPC_PATH = re.compile(r"/api/(?:(?:v1/)?method/(?P<v1>[^/]+)(?:/.*)?|v2/method/(?P<v2>[^/]+))")


def belongs(doctype: str | None, parent: str | None) -> bool:
	"""Whether ``doctype`` may be listed as rows of ``parent``: only its own child tables."""
	if not parent or parent == doctype:
		return True
	if not isinstance(parent, str):
		# a parent is a doctype's name; anything else is nobody's honest list
		return False
	try:
		# computed tables too, as frappe's own check of a child's parent counts them
		fields = frappe.get_meta(parent).get_table_fields(include_computed=True)
	except frappe.DoesNotExistError:
		# not a doctype at all; any other failure is its own error, not a refusal
		return False
	return any(field.options == doctype for field in fields)


def _refuse() -> None:
	frappe.throw(_("That list names a parent it does not belong to."), frappe.PermissionError)


def _checks_the_parent(check_select):
	def check_select_permission(self):
		# only ever called for a query that applies permissions
		if not belongs(self.doctype, self.parent_doctype):
			_refuse()
		return check_select(self)

	return check_select_permission


def _keeps_to_a_single_parent(add_conditions):
	def add_permission_conditions(self):
		result = add_conditions(self)
		if (
			self.apply_permissions
			and self.permission_doctype != self.doctype
			and frappe.get_meta(self.permission_doctype).issingle
		):
			# frappe added nothing for this parent; a Single's rows carry its name
			self.query = self.query.where(self.table.parenttype == self.permission_doctype)
		return result

	return add_permission_conditions


def _checks_the_parent_legacy(check_read):
	def check_read_permission(self, doctype, parent_doctype=None):
		# a caller inside the server that set permissions aside is not a request
		if not self.flags.ignore_permissions and not belongs(doctype, parent_doctype):
			_refuse()
		return check_read(self, doctype, parent_doctype=parent_doctype)

	return check_read_permission


def _engine_wraps():
	from frappe.database.query import Engine

	return (
		(Engine, "check_select_permission", _checks_the_parent),
		(Engine, "add_permission_conditions", _keeps_to_a_single_parent),
	)


def _legacy_wraps():
	"""The older builder's, or nothing once frappe has dropped it or the method."""
	try:
		from frappe.model.db_query import DatabaseQuery
	except ImportError:
		return ()
	if not hasattr(DatabaseQuery, "check_read_permission"):
		return ()
	return ((DatabaseQuery, "check_read_permission", _checks_the_parent_legacy),)


def install(**_job) -> None:
	"""Wrap the builders' permission methods. Idempotent, and it only ever narrows.

	Raises if ``Engine`` or one of its two methods is gone: a list that cannot be
	guarded should not be served. ``before_job`` hands over the job's details,
	hence the keyword arguments.
	"""
	for owner, name, wrap in (*_engine_wraps(), *_legacy_wraps()):
		current = getattr(owner, name)
		if getattr(current, _MARK, False):
			continue
		guarded = wrap(current)
		setattr(guarded, _MARK, True)
		guarded.__wrapped__ = current
		# frappe offers no hook into the builder
		setattr(owner, name, guarded)


def installed() -> bool:
	"""Whether every method there is to wrap is wrapped in this process."""
	try:
		wraps = (*_engine_wraps(), *_legacy_wraps())
	except ImportError:
		return False
	return all(getattr(getattr(owner, name, None), _MARK, False) for owner, name, _wrap in wraps)


def ensure_installed() -> None:
	"""Fail the migrate if frappe's query builder cannot be guarded.

	``install`` wraps frappe methods by name. An upgrade that renames one of
	``Engine``'s would leave every row-level rule open to a borrowed parent with
	nothing to show for it; this is where that is noticed. Runs from after_migrate.
	"""
	message = _("Vectora could not guard the query builders of this Frappe.")
	message += " See crm/permissions/engine_guard.py."
	try:
		install()
	except (ImportError, AttributeError):
		frappe.throw(message)
	if not installed():
		frappe.throw(message)


def _method_called() -> str | None:
	"""The method this request will run, as frappe.app decides it: ``cmd`` first."""
	cmd = frappe.form_dict.get("cmd")
	if cmd:
		return cmd if isinstance(cmd, str) else None
	request = getattr(frappe.local, "request", None)
	match = _RPC_PATH.fullmatch(getattr(request, "path", None) or "")
	return (match["v1"] or match["v2"]) if match else None


def drop_request_flag() -> None:
	"""Delete ``ignore_user_permissions`` from the request, unless it is a link search."""
	form = getattr(frappe.local, "form_dict", None)
	if not form or _FLAG not in form:
		return
	if (_method_called() or "").startswith(_SEARCH):
		return
	del form[_FLAG]


def guard_request() -> None:
	"""The ``before_request`` hook: the wraps, then the request's own flag."""
	install()
	drop_request_flag()
