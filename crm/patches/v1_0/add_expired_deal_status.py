"""Add the Expired deal status, and move the sweep's expired quotes onto it.

Until now the nightly Acumatica sweep closed a deal whose quote ran past its
validity as Lost, reason "Quote expired". Expired is now a status of its own and
not a close -- the deal can still be won or lost -- so those deals are reopened
as Expired. A deal a person marked Lost for any other reason is left alone.
"""

import frappe

from crm.fcrm.doctype.crm_deal_status.crm_deal_status import ensure_expired_status
from crm.integrations.acumatica.outcomes import LOST_EXPIRED


def execute():
	expired = ensure_expired_status()
	lost = frappe.get_all("CRM Deal Status", filters={"type": "Lost"}, pluck="name")
	if not lost:
		return
	names = frappe.get_all(
		"CRM Deal",
		filters={"status": ["in", lost], "lost_reason": LOST_EXPIRED},
		pluck="name",
		limit=0,
	)
	for name in names:
		reopen_as_expired(name, expired)


def reopen_as_expired(name: str, expired: str) -> None:
	"""A whole-document save, so the status log records the move and the
	probability follows the stage; ``modified`` is kept, because the sweep reads
	it as "a rep touched this lately". A deal that cannot pass validation (a field
	made mandatory after it was created) is moved on the columns alone rather than
	left Lost."""
	frappe.db.savepoint("expired_status")
	try:
		doc = frappe.get_doc("CRM Deal", name)
		doc.status = expired
		doc.lost_reason = None
		doc.lost_notes = None
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.flags.notify_update = False
		modified = doc.modified
		doc.save()
		frappe.db.set_value("CRM Deal", name, "modified", modified, update_modified=False)
	except Exception:
		frappe.db.rollback(save_point="expired_status")
		frappe.db.set_value(
			"CRM Deal",
			name,
			{"status": expired, "lost_reason": None, "lost_notes": None},
			update_modified=False,
		)
