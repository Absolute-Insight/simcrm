"""Add the Expired deal status, and move the sweep's expired quotes onto it.

Until now the nightly Acumatica sweep closed a deal whose quote ran past its
validity as Lost, reason "Quote expired". Expired is now a status of its own and
not a close -- the deal can still be won or lost -- so those deals are reopened
as Expired.

Only the sweep's own closes move. "Quote expired" is an ordinary lost reason a
rep can pick, so the reason alone proves nothing: the status log has to show
Administrator, who the sync runs as, took the deal to Lost, and a deal carrying
lost notes is left alone because the sweep never writes any. Those are a
person's decision, and they stand.
"""

import json

import frappe
from frappe.utils import add_to_date, now_datetime

from crm.fcrm.doctype.crm_deal_status.crm_deal_status import (
	EXPIRED,
	ensure_expired_status,
	expired_status_is_usable,
)
from crm.integrations.acumatica.outcomes import LOST_EXPIRED, REREAD_ALL_QUOTES


def execute():
	expired = ensure_expired_status()
	add_to_saved_boards(expired)
	if not expired_status_is_usable():
		print(f"CRM Deal Status {expired} is a Won or Lost status on this site: no deals were moved onto it.")
		return
	lost = frappe.get_all("CRM Deal Status", filters={"type": "Lost"}, pluck="name")
	if not lost:
		return
	names = frappe.get_all(
		"CRM Deal",
		filters={"status": ["in", lost], "lost_reason": LOST_EXPIRED},
		pluck="name",
		limit=0,
	)
	moved = kept = 0
	for name in names:
		if not swept_by_the_sync(name, lost):
			kept += 1
			continue
		reopen_as_expired(name, expired)
		moved += 1
	print(f"Expired deal status: reopened {moved} swept quotes as Expired, left {kept} lost by a person.")
	if moved:
		# Their quotes were skipped while they sat Lost, and the high-water mark has
		# moved on, so an outcome decided in that time would never be read.
		frappe.db.set_default(REREAD_ALL_QUOTES, 1)


def swept_by_the_sync(name: str, lost: list[str]) -> bool:
	if frappe.db.get_value("CRM Deal", name, "lost_notes"):
		return False
	rows = frappe.get_all(
		"CRM Status Change Log",
		filters={"parent": name, "parenttype": "CRM Deal", "to": ["in", lost]},
		fields=["log_owner"],
		order_by="idx desc",
		limit=1,
	)
	return bool(rows) and rows[0].log_owner == "Administrator"


def reopen_as_expired(name: str, expired: str) -> None:
	"""A whole-document save, so the status log records the move and the
	probability follows the stage. ``modified`` and ``modified_by`` are put back:
	the sweep reads the first as "a rep touched this lately" and the spreadsheet
	import the second as who last wrote the deal. A deal that cannot pass validation
	(forecasting switched on over a zero-value deal) is moved on the columns and
	named in the Error Log, rather than left Lost."""
	before = frappe.db.get_value("CRM Deal", name, ["modified", "modified_by"], as_dict=True)
	frappe.db.savepoint("expired_status")
	try:
		doc = frappe.get_doc("CRM Deal", name)
		doc.status = expired
		doc.lost_reason = None
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.flags.notify_update = False
		doc.save()
	except Exception:
		frappe.db.rollback(save_point="expired_status")
		frappe.db.set_value(
			"CRM Deal",
			name,
			{
				"status": expired,
				"lost_reason": None,
				"probability": frappe.db.get_value("CRM Deal Status", expired, "probability"),
			},
			update_modified=False,
		)
		add_log_row(name, expired)
		frappe.log_error(frappe.get_traceback(), f"Expired status: {name} moved without validation")
	frappe.db.set_value("CRM Deal", name, dict(before), update_modified=False)


def add_log_row(name: str, expired: str) -> None:
	"""What the save would have written: close the open row and start Expired's."""
	doc = frappe.get_doc("CRM Deal", name)
	now = now_datetime()
	if doc.status_change_log:
		last = doc.status_change_log[-1]
		frappe.db.set_value(
			"CRM Status Change Log",
			last.name,
			{"to": expired, "to_type": "On Hold", "to_date": now},
			update_modified=False,
		)
	frappe.get_doc(
		{
			"doctype": "CRM Status Change Log",
			"parent": name,
			"parenttype": "CRM Deal",
			"parentfield": "status_change_log",
			"idx": len(doc.status_change_log) + 1,
			"from": expired,
			"from_type": "On Hold",
			"from_date": add_to_date(now, seconds=1),
			"log_owner": "Administrator",
		}
	).db_insert()


def add_to_saved_boards(expired: str) -> None:
	"""A board's columns are saved with it, so one saved before this status would
	never draw it, and an expired deal would drop off the board with no column to
	be in. Placed before Won, as a new board has it."""
	views = frappe.get_all(
		"CRM View Settings",
		filters={"dt": "CRM Deal", "type": "kanban", "column_field": "status"},
		fields=["name", "kanban_columns"],
		limit=0,
	)
	for view in views:
		try:
			columns = json.loads(view.kanban_columns or "[]")
		except (TypeError, ValueError):
			continue
		if not columns or any(column.get("name") == expired for column in columns):
			continue
		closed = [i for i, column in enumerate(columns) if column.get("name") in ("Won", "Lost")]
		columns.insert(closed[0] if closed else len(columns), {"name": expired})
		frappe.db.set_value(
			"CRM View Settings", view.name, "kanban_columns", json.dumps(columns), update_modified=False
		)
