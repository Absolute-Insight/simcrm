import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class CRMAcumaticaSettings(Document):
	def validate(self):
		if not self.enabled:
			return
		if not self.instance_url:
			frappe.throw(_("Instance URL is required to enable the Acumatica integration"))
		self.instance_url = self.instance_url.rstrip("/")
		if frappe.db.get_single_value("ERPNext CRM Settings", "enabled"):
			frappe.throw(
				_("Disable the SIMERP integration first — one ERP integration may be active at a time")
			)

	def on_update(self):
		if self.enabled:
			from crm.integrations.acumatica.install import ensure_custom_fields

			ensure_custom_fields()


def get_settings():
	return frappe.get_cached_doc("CRM Acumatica Settings")


def record_sync_issue(entity: str, remote_id: str, kind: str, detail: str) -> None:
	"""Append a row to the sync-issues table without touching the rest of the doc."""
	doc = frappe.get_doc("CRM Acumatica Settings")
	doc.append(
		"sync_issues",
		{
			"entity": entity,
			"remote_id": remote_id,
			"kind": kind,
			"detail": detail[:500],
			"detected_on": now_datetime(),
		},
	)
	doc.save(ignore_permissions=True)
