import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

FORM_SCRIPT_NAME = "Create Sales Quote from CRM Deal"
MAX_SYNC_ISSUES = 200


class CRMAcumaticaSettings(Document):
	def validate(self):
		from crm.integrations.acumatica.quotes import validate_settings

		# checked enabled or not: the mapping is read the moment the integration is on
		validate_settings(self)
		self.validate_customer_push()
		if not self.enabled:
			return
		if not self.instance_url:
			frappe.throw(_("Instance URL is required to enable the Acumatica integration"))
		self.instance_url = self.instance_url.rstrip("/")
		if frappe.db.get_single_value("ERPNext CRM Settings", "enabled"):
			frappe.throw(
				_("Disable the SIMERP integration first — one ERP integration may be active at a time")
			)

	def validate_customer_push(self):
		for field in ("new_customer_class", "tax_zone_home", "tax_zone_abroad"):
			self.set(field, (self.get(field) or "").strip())
		# the class is what supplies terms, credit limit and statement cycle -- the push
		# never sends those -- so a customer without one is not one to create
		if self.create_customer_on_status_change and not self.new_customer_class:
			frappe.throw(
				_("Set New Customer Class before turning on creating customers in Acumatica"),
				title=_("Missing customer class"),
			)

	def on_update(self):
		# The identity custom fields are schema, installed by after_install and
		# after_migrate whether or not the integration is on (#166) -- enabling
		# only arms the write paths. Disabling has to undo the one visible thing
		# enabling did, or the Deal form keeps a dead button forever.
		#
		# Turning it on is what puts the button and the Acumatica section in front
		# of a rep. Any other save only refreshes the script's text: an admin who
		# then disabled the script or removed the section meant it.
		if self.enabled:
			from crm.integrations.acumatica.install import ensure_layout_fields

			turned_on = self.has_value_changed("enabled")
			self.create_crm_form_script(enable=turned_on)
			if turned_on:
				ensure_layout_fields()
		else:
			self.disable_crm_form_script()

	def disable_crm_form_script(self):
		if frappe.db.get_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled"):
			frappe.db.set_value("CRM Form Script", FORM_SCRIPT_NAME, "enabled", 0)

	def create_crm_form_script(self, enable: bool = False):
		"""Install the quote button's script, or bring its text up to date.

		``enabled`` is the one thing a site may change on a standard form script,
		so an existing script is only switched back on when ``enable`` says the
		integration itself was just turned on -- not on every settings save, and
		not on every migrate.
		"""
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
		if enable and not current.enabled:
			# re-enabling the integration after a disable brings the button back
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


def record_sync_issue(
	entity: str, remote_id: str, kind: str, detail: str, candidates: list | None = None
) -> None:
	"""Append a row to the sync-issues table without touching the rest of the doc.

	``candidates`` (Possible Duplicate rows) is what the settings panel offers to link
	the organization to, kept as JSON beside the human-readable detail."""
	doc = frappe.get_doc("CRM Acumatica Settings")
	doc.append(
		"sync_issues",
		{
			"entity": entity,
			"remote_id": remote_id,
			"kind": kind,
			"detail": detail[:500],
			"candidates": json.dumps(candidates) if candidates else None,
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


def has_open_sync_issue(entity: str, remote_id: str, kind: str, detail: str | None = None) -> bool:
	"""Whether an undismissed row already says this. ``detail`` None matches any."""
	for row in frappe.get_doc("CRM Acumatica Settings").sync_issues:
		if row.dismissed or row.entity != entity or row.remote_id != remote_id or row.kind != kind:
			continue
		if detail is None or row.detail == detail[:500]:
			return True
	return False


def dismiss_sync_issues(entity: str, remote_id: str, kinds) -> int:
	"""Dismiss every open row for ``remote_id`` of one of ``kinds``; how many it did."""
	doc = frappe.get_doc("CRM Acumatica Settings")
	count = 0
	for row in doc.sync_issues:
		if not row.dismissed and row.entity == entity and row.remote_id == remote_id and row.kind in kinds:
			row.dismissed = 1
			count += 1
	if count:
		# same reason as record_sync_issue: a log write must not trip the config checks
		doc.flags.ignore_validate = True
		doc.save(ignore_permissions=True)
	return count
