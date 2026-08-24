import frappe
from frappe import _

# The long queue's default job timeout is 1500s. A first backfill of a real tenant
# (tens of thousands of customers, paced by request_pause) does not finish inside
# that, and run_backfill only writes last_synced_at once every entity is done -- so a
# killed run leaves no forward progress at all. Give it a working day's ceiling.
BACKFILL_TIMEOUT = 4 * 3600


@frappe.whitelist()
def start_backfill() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	if not settings.enabled:
		frappe.throw(_("Enable the Acumatica integration first"))
	frappe.enqueue(
		"crm.integrations.acumatica.importer.run_backfill",
		queue="long",
		job_id="acumatica_backfill",
		deduplicate=True,
		timeout=BACKFILL_TIMEOUT,
	)
	return {"queued": True}


@frappe.whitelist()
def get_sync_status() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	open_issues = sum(1 for row in settings.sync_issues if not row.dismissed)
	return {"last_synced_at": settings.last_synced_at, "open_issues": open_issues}


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
def get_crm_form_script():
	"""Form Script for CRM Deal -- same delivery mechanism as the ERPNext
	integration's get_crm_form_script. Additive only: it registers an action,
	it does not touch existing helpers."""
	return """class CRMDeal {
	onLoad() {
		if (this.doc.__newDocument) return
		call("frappe.client.get_single_value", {
			doctype: "CRM Acumatica Settings",
			field: "enabled",
		}).then((enabled) => {
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
