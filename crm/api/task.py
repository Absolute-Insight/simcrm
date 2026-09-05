import json

import frappe
from frappe import _


@frappe.whitelist()
def get_history(name: str | int) -> list[dict]:
	"""What changed on a task, and who did it, newest first.

	The old rep app showed the edit trail inside the activity dialog beside the
	note that came with each change; ``track_changes`` already records exactly
	that as Version rows, so this only reshapes them.

	CRM Task autoincrements, so the browser sends ``{"name": 7}`` -- a bare
	``str`` annotation made Frappe's type validation answer 417 to every real
	call and the History block never had anything to show."""
	name = str(name)
	frappe.has_permission("CRM Task", "read", doc=name, throw=True)
	labels = {f.fieldname: f.label for f in frappe.get_meta("CRM Task").fields}
	rows = frappe.get_all(
		"Version",
		filters={"ref_doctype": "CRM Task", "docname": name},
		fields=["creation", "owner", "data"],
		order_by="creation desc",
	)
	history = []
	for row in rows:
		data = json.loads(row.data or "{}")
		changes = [
			{"field": field, "label": _(labels.get(field) or field), "old": old, "new": new}
			for field, old, new in data.get("changed", [])
			if old != new
		]
		if changes:
			history.append({"creation": row.creation, "owner": row.owner, "changes": changes})
	return history
