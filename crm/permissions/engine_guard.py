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
   for the listed doctype is refused before anything else is checked. So is a
   doctype or parent named in any spelling but its own: ``frappe.get_meta("crm
   deal")`` finds CRM Deal, because the database compares names without case,
   while the ``permission_query_conditions`` hooks are keyed on the exact
   string and would find nothing. Only a database that keeps table names
   case-sensitive turned that into an error (no table ``tabcrm deal``); now
   the builder refuses it whatever the database does.

2. **A child table shared between parents.** frappe never asks *which* kind of
   parent a row belongs to. Under a Single the early return adds nothing, so a
   child doctype used by a Single and by an ordinary doctype (``Event
   Notifications``: FCRM Settings and Event) passed check 1 honestly under the
   Single and the list held every Event's rows too. Under an ordinary parent
   frappe joins on ``child.parent = parent.name`` alone, so a reader of one
   parent also got the rows of any other doctype's document that happens to
   carry the same name as one they can read. ``install`` wraps
   ``Engine.add_permission_conditions``: whenever a parent is named, the rows
   are limited to ``parenttype`` = that parent. A child row always carries the
   doctype whose table field holds it, so an honest list loses nothing.

3. **``ignore_user_permissions`` from the request.** ``frappe.desk.reportview``
   does not strip it, so the report view, its count and export, and the kanban
   read it from the request and skip User Permission conditions. This app mirrors
   User Permissions between Item and CRM Product, so an administrator's
   restriction was one parameter deep. ``guard_request`` deletes that one key
   from ``frappe.form_dict`` unless the method called is one of the two the
   desk's link control sends it to: anything in ``frappe.desk.search``, and
   ``frappe.client.validate_link_and_fetch``, which hands it to the same
   ``search_widget``. That honours it only after checking that the link field
   named has the option set, and neither does anything else with it. Dropping
   it from the second made the desk clear a value its own search had just
   offered. It touches nothing else of the request. ``install`` also adds the
   key to ``frappe.desk.reportview.DISALLOWED_PARAMS``, which the report view,
   its count and export, and the kanban strip from their arguments on every
   call, so they drop it however the arguments came to be there. The link
   search does not read its arguments through that list.

4. **frappe's MCP endpoint.** Newer frappe serves ``/api/v2/mcp``, whose
   ``call_method`` tool replaces ``frappe.form_dict`` with the tool's arguments
   after the request hooks have run, so a flag inside them would pass check 3.
   The pinned frappe has no such endpoint and nothing in this app serves or
   calls one, so ``guard_request`` refuses the path: it answers 403 where it
   answered 404, and stays shut if the pin moves. Whoever comes to want it
   has to apply check 3 to the tool's arguments first.

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
# the link control's second call; it passes the flag on to search_widget and nowhere else
_LINK_VALIDATION = "frappe.client.validate_link_and_fetch"
_MCP_PATH = re.compile(r"/api/(?:v\d+/)?mcp(?:/.*)?", re.IGNORECASE)
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


def spelled_as_named(doctype: str | None) -> bool:
	"""Whether ``doctype`` is the doctype's own name, not a variant the database also finds."""
	if not doctype or not isinstance(doctype, str):
		return True
	try:
		# cached, and frappe's own check loads it next anyway
		return frappe.get_meta(doctype).name == doctype
	except frappe.DoesNotExistError:
		# not a doctype: frappe's own check says so
		return True


def _refuse_spelling() -> None:
	frappe.throw(_("That list names a doctype by another spelling."), frappe.PermissionError)


def _checks_the_parent(check_select):
	def check_select_permission(self):
		# only ever called for a query that applies permissions
		if not (spelled_as_named(self.doctype) and spelled_as_named(self.parent_doctype)):
			_refuse_spelling()
		if not belongs(self.doctype, self.parent_doctype):
			_refuse()
		return check_select(self)

	return check_select_permission


def _keeps_to_the_parent_named(add_conditions):
	def add_permission_conditions(self):
		result = add_conditions(self)
		if self.apply_permissions and self.permission_doctype != self.doctype:
			# frappe matches a row to its parent by name alone, and under a Single
			# by nothing; a row carries the doctype it belongs to
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
		(Engine, "add_permission_conditions", _keeps_to_the_parent_named),
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


def _report_view_strips_the_flag(add: bool = False) -> bool:
	"""Whether the report view drops the flag from its arguments; ``add`` makes it so.

	``clean_params`` reads the tuple from its module on every call, so it is
	replaced, not changed. A frappe without it is reported, never raised on.
	"""
	try:
		from frappe.desk import reportview
	except ImportError:
		return False
	params = getattr(reportview, "DISALLOWED_PARAMS", None)
	if not isinstance(params, tuple | list):
		return False
	if add and _FLAG not in params:
		reportview.DISALLOWED_PARAMS = (*params, _FLAG)
	return _FLAG in reportview.DISALLOWED_PARAMS


def install(**_job) -> None:
	"""Wrap the builders' permission methods. Idempotent, and it only ever narrows.

	Raises if ``Engine`` or one of its two methods is gone: a list that cannot be
	guarded should not be served. A report view whose list of stripped arguments
	is gone does not raise here; ``ensure_installed`` reports it at migrate.
	``before_job`` hands over the job's details, hence the keyword arguments.
	"""
	_report_view_strips_the_flag(add=True)
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
	"""Whether every method there is to wrap is wrapped in this process, and the
	report view strips the flag."""
	try:
		wraps = (*_engine_wraps(), *_legacy_wraps())
	except ImportError:
		return False
	if not all(getattr(getattr(owner, name, None), _MARK, False) for owner, name, _wrap in wraps):
		return False
	return _report_view_strips_the_flag()


def ensure_installed() -> None:
	"""Fail the migrate if frappe's query builder cannot be guarded.

	``install`` wraps frappe methods by name. An upgrade that renames one of
	``Engine``'s would leave every row-level rule open to a borrowed parent with
	nothing to show for it; this is where that is noticed, and likewise a report
	view that no longer keeps the list the flag is added to. Runs from after_migrate.
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
	"""Delete ``ignore_user_permissions`` from the request, unless a link field is asking."""
	form = getattr(frappe.local, "form_dict", None)
	if not form or _FLAG not in form:
		return
	called = _method_called() or ""
	if called.startswith(_SEARCH) or called == _LINK_VALIDATION:
		return
	del form[_FLAG]


def refuse_mcp() -> None:
	"""Refuse frappe's MCP endpoint, which sets a call's arguments after this hook has run."""
	request = getattr(frappe.local, "request", None)
	if _MCP_PATH.fullmatch(getattr(request, "path", None) or ""):
		frappe.throw(_("This endpoint is not available."), frappe.PermissionError)


def guard_request() -> None:
	"""The ``before_request`` hook: the wraps, then what this request itself carries."""
	install()
	refuse_mcp()
	drop_request_flag()
