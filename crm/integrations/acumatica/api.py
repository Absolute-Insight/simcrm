import frappe
from frappe import _
from frappe.utils.background_jobs import is_job_enqueued

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import get_pending_retries
from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError

# Both describe the sync rather than this button -- the timeout is how long one takes,
# and the job id is shared with the sweep and the webhook so only one can be queued --
# so they live with the importer.
from crm.integrations.acumatica.importer import BACKFILL_TIMEOUT, SYNC_JOB_ID


@frappe.whitelist()
def start_backfill() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	if not settings.enabled:
		frappe.throw(_("Enable the Acumatica integration first"))
	frappe.enqueue(
		"crm.integrations.acumatica.importer.run_backfill",
		queue="long",
		job_id=SYNC_JOB_ID,
		deduplicate=True,
		timeout=BACKFILL_TIMEOUT,
	)
	return {"queued": True}


@frappe.whitelist()
def get_sync_status() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	open_issues = sum(1 for row in settings.sync_issues if not row.dismissed)
	# a count, not the queue itself -- the retry list is a work list for the sweep,
	# not something the panel walks entity by entity
	pending_retries = sum(len(attempts) for attempts in get_pending_retries().values())
	return {
		"last_synced_at": settings.last_synced_at,
		"open_issues": open_issues,
		"running": is_job_enqueued(SYNC_JOB_ID),
		"last_sync_error": settings.last_sync_error,
		"pending_retries": pending_retries,
	}


@frappe.whitelist()
def test_connection() -> dict:
	"""Never raises: a transport failure is exactly what an admin clicking this button
	is trying to see, not a stack trace on the panel."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_doc("CRM Acumatica Settings")  # the saved doc -- the operator just saved it
	if not settings.instance_url:
		return {"ok": False, "error": _("Instance URL is required")}
	client = AcumaticaClient(settings)
	# the operator may have just changed the credentials; a cached token from the old
	# ones would test those, not the ones on screen
	frappe.cache().delete_value(client._cache_key())
	try:
		return client.ping()
	except AcumaticaError as e:
		if e.status_code:
			error = f"{e.status_code}: {(e.body or '')[:300]}"
		else:
			error = str(e)
		return {"ok": False, "error": error}
	except Exception as e:
		return {"ok": False, "error": str(e)}


@frappe.whitelist()
def get_open_sync_issues() -> list[dict]:
	"""The counter alone tells an admin something broke but not what."""
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	return [
		{
			"name": issue.name,
			"entity": issue.entity,
			"remote_id": issue.remote_id,
			"kind": issue.kind,
			"detail": issue.detail,
			"detected_on": issue.detected_on,
		}
		for issue in settings.sync_issues
		if not issue.dismissed
	]


@frappe.whitelist()
def dismiss_sync_issue(issue_name: str) -> bool:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_doc("CRM Acumatica Settings")
	for issue in settings.sync_issues:
		# child rows autoincrement, so the name arrives from the client as a string
		if str(issue.name) == str(issue_name):
			issue.dismissed = 1
			# clearing a log row must not be blocked by the config validations
			settings.flags.ignore_validate = True
			settings.save(ignore_permissions=True)
			return True
	return False


@frappe.whitelist()
def is_enabled() -> bool:
	"""The one bit the Deal form script needs. The settings document itself holds the
	webhook secret and the API identity, so reps get this and nothing else."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	return bool(frappe.db.get_single_value("CRM Acumatica Settings", "enabled"))


@frappe.whitelist()
def get_crm_form_script():
	"""Form Script for CRM Deal -- same delivery mechanism as the ERPNext
	integration's get_crm_form_script. Additive only: it registers an action,
	it does not touch existing helpers."""
	return """class CRMDeal {
	onLoad() {
		if (this.doc.__newDocument) return
		call("crm.integrations.acumatica.api.is_enabled").then((enabled) => {
			if (enabled) this.doc.trigger("setAcumaticaActions")
		}).catch(() => {})
	}
	setAcumaticaActions() {
		this.actions.push({
			label: __("Create Sales Quote"),
			onClick: () => {
				call("crm.integrations.acumatica.outbound.create_sales_quote_from_deal", {
					crm_deal: this.doc.name,
				}).then((order_nbr) => {
					toast.success(__("Sales quote {0} created in Acumatica", [order_nbr]))
				}).catch((e) => {
					toast.error(e.messages?.[0] || __("Error while creating sales quote in Acumatica. Check error log for more details"))
				})
			},
		})
	}
}"""
