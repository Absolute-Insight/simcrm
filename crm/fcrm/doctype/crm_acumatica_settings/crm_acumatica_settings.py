import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Max, Min
from frappe.utils import now_datetime

FORM_SCRIPT_NAME = "Create Sales Quote from CRM Deal"
MAX_SYNC_ISSUES = 200


class CRMAcumaticaSettings(Document):
	def validate(self):
		from crm.integrations.acumatica.quotes import validate_settings

		# checked enabled or not: the mapping is read the moment the integration is on
		validate_settings(self)
		self.validate_customer_push()
		self.drop_sync_issues()
		if not self.enabled:
			return
		if not self.instance_url:
			frappe.throw(_("Instance URL is required to enable the Acumatica integration"))
		self.instance_url = self.instance_url.rstrip("/")
		if frappe.db.get_single_value("ERPNext CRM Settings", "enabled"):
			frappe.throw(
				_("Disable the SIMERP integration first — one ERP integration may be active at a time")
			)

	def drop_sync_issues(self):
		"""A settings save never touches the issue log. The table is written row by row
		by the jobs (record_sync_issue); a form save carries whatever copy it loaded,
		which would delete rows recorded since and undo dismissals. The rows are also
		dropped from the document, so the copy frappe.client.save / set_value hands
		back holds none -- the log is read through api.get_open_sync_issues, which
		knows who may see what."""
		if not self.flags.write_sync_issues:
			self.set("sync_issues", [])

	def update_child_table(self, fieldname, df=None):
		# with drop_sync_issues, what keeps the stale copy from deleting the log; only
		# code that means to rewrite it (a test resetting the table) sets the flag
		if fieldname == "sync_issues" and not self.flags.write_sync_issues:
			return
		super().update_child_table(fieldname, df)

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


def has_permission(doc, ptype=None, user=None, debug=False):
	"""Only those who see every customer may read the settings document.

	Its sync-issue log names organizations and quotes Acumatica's errors about any
	of them. The table is permlevel 1, which keeps it out of frappe.client.get -- but
	frappe lists a Single's child rows to anyone who can read the Single
	(``frappe.get_list(child, parent_doctype=...)`` checks the parent only, and not
	the table's permlevel), so a manager whose customers are scoped could read every
	row past it. They read the log through api.get_open_sync_issues instead, which
	filters it for them. Returning True defers to the role permissions."""
	user = user or frappe.session.user
	if user == "Administrator" or "System Manager" in frappe.get_roles(user):
		return True
	from crm.permissions.customers import scope_applies

	return not scope_applies(user)


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


SETTINGS = "CRM Acumatica Settings"
ISSUE = "CRM Acumatica Sync Issue"


def _issue_rows_filter(**extra) -> dict:
	return {"parent": SETTINGS, "parenttype": SETTINGS, "parentfield": "sync_issues", **extra}


def _touched() -> None:
	# get_settings() is a cached doc; a row written past it must not be read stale
	frappe.clear_document_cache(SETTINGS, SETTINGS)


def record_sync_issue(
	entity: str, remote_id: str, kind: str, detail: str, candidates: list | None = None
) -> None:
	"""Append a row to the sync-issues table without touching the rest of the doc.

	The row is inserted on its own, never through a save of the Single: jobs record
	issues concurrently, and a whole-document save from a stale copy either fails on
	the timestamp check or writes the stale copy back -- inside a job that may just
	have linked a customer, whose link the failure would roll back.

	``candidates`` (Possible Duplicate rows) is what the settings panel offers to link
	the organization to, kept as JSON beside the human-readable detail."""
	Issue = frappe.qb.DocType(ISSUE)
	top = (
		frappe.qb.from_(Issue)
		.select(Max(Issue.idx))
		.where((Issue.parent == SETTINGS) & (Issue.parentfield == "sync_issues"))
	).run()
	row = frappe.get_doc(
		{
			"doctype": ISSUE,
			"parent": SETTINGS,
			"parenttype": SETTINGS,
			"parentfield": "sync_issues",
			"idx": ((top and top[0][0]) or 0) + 1,
			"entity": entity,
			"remote_id": remote_id,
			"kind": kind,
			"detail": (detail or "")[:500],
			"candidates": json.dumps(candidates) if candidates else None,
			"detected_on": now_datetime(),
			"dismissed": 0,
		}
	)
	row.db_insert()
	_trim()
	_touched()


def _trim() -> None:
	"""The table is a log, and a bad backfill can write one row per record: keep the
	newest MAX_SYNC_ISSUES, renumbered from 1."""
	names = frappe.get_all(
		ISSUE, filters=_issue_rows_filter(), order_by="idx asc", pluck="name", limit=MAX_SYNC_ISSUES * 5
	)
	excess = len(names) - MAX_SYNC_ISSUES
	if excess > 0:
		frappe.db.delete(ISSUE, {"name": ("in", names[:excess])})
	Issue = frappe.qb.DocType(ISSUE)
	first = (
		frappe.qb.from_(Issue)
		.select(Min(Issue.idx))
		.where((Issue.parent == SETTINGS) & (Issue.parentfield == "sync_issues"))
	).run()
	first = first[0][0] if first else None
	if first and int(first) > 1:
		(
			frappe.qb.update(Issue)
			.set(Issue.idx, Issue.idx - (int(first) - 1))
			.where((Issue.parent == SETTINGS) & (Issue.parentfield == "sync_issues"))
		).run()


def open_sync_issues(entity: str, remote_id: str, kinds) -> list:
	"""Undismissed rows for ``remote_id`` of one of ``kinds``, newest first, read from
	the table itself rather than a cached copy of the Single."""
	return frappe.get_all(
		ISSUE,
		filters=_issue_rows_filter(entity=entity, remote_id=remote_id, kind=("in", list(kinds)), dismissed=0),
		fields=["name", "kind", "detail", "candidates", "detected_on"],
		order_by="idx desc",
	)


def has_open_sync_issue(entity: str, remote_id: str, kind: str, detail: str | None = None) -> bool:
	"""Whether an undismissed row already says this. ``detail`` None matches any."""
	return any(
		detail is None or row.detail == detail[:500] for row in open_sync_issues(entity, remote_id, (kind,))
	)


def upsert_sync_issue(
	entity: str, remote_id: str, kind: str, detail: str, candidates: list | None = None
) -> bool:
	"""One open row per record and kind: an open row is brought up to date in place,
	otherwise one is recorded. True when the row is new -- the caller's cue to tell
	somebody. Repeats (every deal save, every sweep) then neither churn the capped
	table nor evict the issues that matter."""
	rows = open_sync_issues(entity, remote_id, (kind,))
	if not rows:
		record_sync_issue(entity, remote_id, kind, detail, candidates)
		return True
	keep, *stale = rows
	frappe.db.set_value(
		ISSUE,
		keep.name,
		{
			"detail": (detail or "")[:500],
			"candidates": json.dumps(candidates) if candidates else None,
			"detected_on": now_datetime(),
		},
		update_modified=False,
	)
	for row in stale:
		frappe.db.set_value(ISSUE, row.name, "dismissed", 1, update_modified=False)
	_touched()
	return False


def dismiss_sync_issues(entity: str, remote_id: str, kinds) -> int:
	"""Dismiss every open row for ``remote_id`` of one of ``kinds``; how many it did.
	Row by row, never through a save of the Single (see record_sync_issue)."""
	rows = open_sync_issues(entity, remote_id, kinds)
	for row in rows:
		frappe.db.set_value(ISSUE, row.name, "dismissed", 1, update_modified=False)
	if rows:
		_touched()
	return len(rows)


def dismiss_sync_issue_row(name) -> bool:
	if not frappe.db.exists(ISSUE, _issue_rows_filter(name=name)):
		return False
	frappe.db.set_value(ISSUE, name, "dismissed", 1, update_modified=False)
	_touched()
	return True
