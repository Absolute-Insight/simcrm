import frappe
from frappe import _


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
	)
	return {"queued": True}


@frappe.whitelist()
def get_sync_status() -> dict:
	frappe.only_for(["System Manager", "Sales Manager"], True)
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	open_issues = sum(1 for row in settings.sync_issues if not row.dismissed)
	return {"last_synced_at": settings.last_synced_at, "open_issues": open_issues}


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
		})
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
					toast.error(e.messages[0] || __("Error while creating sales quote in Acumatica. Check error log for more details"))
				})
			},
		})
	}
}"""
