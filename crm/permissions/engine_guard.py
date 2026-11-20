"""A list may name as its parent only a doctype it is a child table of.

frappe lets a caller name a ``parent_doctype`` for a list. Permissions are then
taken from that parent, and when the parent is a Single none are added at all:
``Engine.add_permission_conditions`` returns early with "permissions are already
checked by has_permission". Nothing checks that the listed doctype is a child
table of that parent, and for a doctype that is not a child table
``frappe.has_permission`` ignores the parent altogether. So
``frappe.client.get_list("CRM Deal", parent="System Settings")`` listed every
deal to anyone with the role-level right: past User Permissions, ``if_owner``,
shares, and every ``permission_query_conditions`` in hooks.py, which is how this
app keeps one rep's leads, deals and customers from another.

The parent arrives as a request parameter (``frappe.client.get_list`` /
``get_value`` / ``get_count``, ``frappe.desk.reportview.get`` / ``get_count`` /
``export_query``, ``/api/resource/<doctype>?parent=``) or inside a number card or
dashboard chart the request describes (``parent_document_type``), and frappe's own
code passes it on. So it is refused at the one place every such list goes
through: frappe's query builders, before they check anything else.

``frappe.database.query.Engine`` is the builder ``frappe.get_list`` and the
report view use on the pinned frappe. ``frappe.model.db_query.DatabaseQuery`` is
the older one; frappe itself no longer calls it, but it is still importable and
has the same gap, so it is closed too.

Runs as ``before_request`` and ``before_job`` rather than at import, for the
reason document_guard gives: hooks are served from cache and nothing of this app
is imported in a process until one of its hooks runs. ``ensure_installed`` fails
a migrate when either method is no longer there to wrap, so a frappe that
renamed one is noticed on the day of the upgrade and not by a rep reading
another's pipeline. Remove this once the frappe pin checks the parent itself.
"""

from __future__ import annotations

import frappe
from frappe import _

_MARK = "_crm_parent_guard"


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


def _targets():
	from frappe.database.query import Engine
	from frappe.model.db_query import DatabaseQuery

	return (Engine, "check_select_permission"), (DatabaseQuery, "check_read_permission")


def install(**_job) -> None:
	"""Wrap both builders' permission checks. Idempotent.

	``before_job`` hands over the job's details, hence the keyword arguments.
	"""
	(engine, select), (query, read) = _targets()

	if not getattr(getattr(engine, select), _MARK, False):
		check_select = getattr(engine, select)

		def check_select_permission(self):
			# only ever called for a query that applies permissions
			if not belongs(self.doctype, self.parent_doctype):
				_refuse()
			return check_select(self)

		setattr(check_select_permission, _MARK, True)
		check_select_permission.__wrapped__ = check_select
		# frappe offers no hook into the builder; this only ever refuses.
		setattr(engine, select, check_select_permission)

	if not getattr(getattr(query, read), _MARK, False):
		check_read = getattr(query, read)

		def check_read_permission(self, doctype, parent_doctype=None):
			# a caller inside the server that set permissions aside is not a request
			if not self.flags.ignore_permissions and not belongs(doctype, parent_doctype):
				_refuse()
			return check_read(self, doctype, parent_doctype=parent_doctype)

		setattr(check_read_permission, _MARK, True)
		check_read_permission.__wrapped__ = check_read
		setattr(query, read, check_read_permission)


def installed() -> bool:
	"""Whether both builders are wrapped in this process."""
	try:
		return all(getattr(getattr(owner, name, None), _MARK, False) for owner, name in _targets())
	except ImportError:
		return False


def ensure_installed() -> None:
	"""Fail the migrate if frappe's query builders cannot be guarded.

	``install`` wraps two frappe methods by name. An upgrade that renames either
	would leave every row-level rule open to a borrowed parent with nothing to
	show for it; this is where that is noticed. Runs from after_migrate.
	"""
	message = _("Vectora could not guard the query builders of this Frappe.")
	message += " See crm/permissions/engine_guard.py."
	try:
		install()
	except (ImportError, AttributeError):
		frappe.throw(message)
	if not installed():
		frappe.throw(message)
