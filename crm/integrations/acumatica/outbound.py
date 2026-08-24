import frappe
from frappe import _

from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
	get_settings,
	record_sync_issue,
)
from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v


def create_customer_in_acumatica(doc, method):
	"""CRM Deal on_update handler. Mirrors the ERPNext integration's trigger shape:
	fires once when the deal reaches the configured status."""
	settings = get_settings()
	if (
		not settings.enabled
		or not settings.create_customer_on_status_change
		or doc.status != settings.deal_status
		or not doc.organization
	):
		return

	org = frappe.get_doc("CRM Organization", doc.organization)
	if org.get("acumatica_noteid"):
		# already linked -- record the link on the deal and stop
		if not doc.get("acumatica_customer"):
			frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", org.get("acumatica_id"))
		return

	payload = {"CustomerName": org.organization_name}
	if settings.customer_numbering == "From Organization Name":
		payload["CustomerID"] = org.organization_name[:30].upper().replace(" ", "")

	try:
		created = AcumaticaClient(settings).put("Customer", payload)
	except AcumaticaError as e:
		record_sync_issue("Customer", org.name, "Push Failed", f"{e} :: {e.body}")
		return

	frappe.db.set_value(
		"CRM Organization",
		org.name,
		{"acumatica_noteid": v(created, "NoteID"), "acumatica_id": v(created, "CustomerID")},
	)
	frappe.db.set_value("CRM Deal", doc.name, "acumatica_customer", v(created, "CustomerID"))


@frappe.whitelist()
def create_sales_quote_from_deal(crm_deal: str) -> str:
	frappe.has_permission("CRM Deal", "write", doc=crm_deal, throw=True)
	settings = get_settings()
	if not settings.enabled:
		frappe.throw(_("The Acumatica integration is not enabled"))

	deal = frappe.get_doc("CRM Deal", crm_deal)
	customer_id = deal.get("acumatica_customer") or frappe.db.get_value(
		"CRM Organization", deal.organization, "acumatica_id"
	)
	if not customer_id:
		frappe.throw(_("This deal's organization is not linked to an Acumatica customer yet"))

	details = []
	# CRM Deal's child table is `products` (CRM Products rows); the row's link to
	# the CRM Product is `product_code`, the quantity field is `qty`.
	for row in deal.get("products") or []:
		inventory_id = frappe.db.get_value("CRM Product", row.product_code, "acumatica_id")
		if not inventory_id:
			continue
		details.append({"InventoryID": inventory_id, "OrderQty": row.qty or 1})

	payload = {
		"OrderType": settings.quote_order_type,
		"CustomerID": customer_id,
		"Description": f"Vectora deal {deal.name}",
	}
	if details:
		payload["Details"] = details

	created = AcumaticaClient(settings).put("SalesOrder", payload)
	return v(created, "OrderNbr") or ""
