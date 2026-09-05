import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

FORM_SCRIPT_NAME = "Create Sales Quote from CRM Deal"
MAX_SYNC_ISSUES = 200


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
		# The identity custom fields are schema, installed by after_install and
		# after_migrate whether or not the integration is on (#166) -- enabling
		# only arms the write paths. Disabling has to undo the one visible thing
		# enabling did, or the Deal form keeps a dead button forever.
		if self.enabled:
			self.create_crm_form_script()
		else:
			self.disable_crm_form_script()

	def disable_crm_form_script(self):
		if frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"):
			frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled", 0)

	def create_crm_form_script(self):
		from crm.integrations.acumatica.api import get_crm_form_script

		script = get_crm_form_script()
		if not frappe.db.exists("CRM Form Script", FORM_SCRIPT_NAME):
			frappe.get_doc(
				{
					"doctype": "CRM Form Script",
					"name": FORM_SCRIPT_NAME,
					"dt": "CRM Deal",
					"view": "Form",
					"script": script,
					"enabled": 1,
					"is_standard": 1,
				}
			).insert(ignore_permissions=True)
			return

		# The script ships with the app, not with the record: an install that predates a
		# fix would otherwise run the frozen first-install string forever. Same idiom as
		# ERPNext CRM Settings' reset_erpnext_form_script.
		current = frappe.db.get_value(
			"CRM Form Script", FORM_SCRIPT_NAME, ["script", "enabled"], as_dict=True
		)
		if current.script != script:
			frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "script", script)
		if not current.enabled:
			# re-enabling after a disable brings the button back
			frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled", 1)


def get_settings():
	return frappe.get_cached_doc("CRM Acumatica Settings")


def get_pending_retries() -> dict:
	"""The importer's retry queue: ``{"<entity>": {"<NoteID>": attempts}}``.

	A JSON field rather than a child table because it is a work list, not a log: the
	sweep rewrites it whole every run and nobody reads it in the UI. What an admin
	reads is the sync-issues table, which is where a record ends up once its attempts
	run out."""
	raw = frappe.db.get_single_value("CRM Acumatica Settings", "pending_retries")
	return json.loads(raw) if raw else {}


def set_pending_retries(pending: dict) -> None:
	# set_single_value, not doc.save(): this runs at the end of a sweep that has been
	# appending sync issues through their own saves, and a whole-document write would
	# carry a stale copy of everything else back with it.
	frappe.db.set_single_value("CRM Acumatica Settings", "pending_retries", json.dumps(pending))


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
	if len(doc.sync_issues) > MAX_SYNC_ISSUES:
		# The table is a log, and a bad backfill can write one row per record: unbounded
		# growth makes every later append rewrite the whole table. Keep the newest rows.
		del doc.sync_issues[0 : len(doc.sync_issues) - MAX_SYNC_ISSUES]
		for idx, row in enumerate(doc.sync_issues, start=1):
			row.idx = idx
	# This save runs inside whatever transaction hit the failure -- often a user's deal
	# save. validate() would re-run the mutual-exclusion check and could throw a
	# ValidationError from there, turning a logged sync issue into a failed save.
	doc.flags.ignore_validate = True
	doc.save(ignore_permissions=True)
