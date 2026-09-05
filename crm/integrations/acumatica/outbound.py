import re

import frappe
import requests
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
		# Acumatica's default CUSTOMER ID segment is 10; the setting exists for
		# tenants that widened it.
		limit = int(settings.get("customer_id_max_length") or 10)
		payload["CustomerID"] = re.sub(r"[^A-Z0-9]", "", org.organization_name.upper())[:limit]

	try:
		created = AcumaticaClient(settings).put("Customer", payload)
	except (AcumaticaError, requests.RequestException, ValueError) as e:
		# This runs inside the user's deal save. A DNS blip, a read timeout or an HTML
		# error page from a proxy (json() raises ValueError/JSONDecodeError) must land in
		# the sync-issues table like any other push failure -- never fail the save.
		record_sync_issue("Customer", org.name, "Push Failed", f"{e} :: {getattr(e, 'body', '')}")
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
	existing_quote = deal.get("acumatica_sales_quote")
	if existing_quote:
		# SalesOrder is a PUT-upsert with no key in the body, so every click would create
		# ANOTHER order in the client's ERP. The stored OrderNbr is the idempotency key.
		frappe.throw(_("Sales quote {0} already exists in Acumatica").format(existing_quote))

	customer_id = deal.get("acumatica_customer") or frappe.db.get_value(
		"CRM Organization", deal.organization, "acumatica_id"
	)
	if not customer_id:
		frappe.throw(_("This deal's organization is not linked to an Acumatica customer yet"))

	products = deal.get("products") or []
	details = []
	# CRM Deal's child table is `products` (CRM Products rows); the row's link to
	# the CRM Product is `product_code`, the quantity field is `qty`.
	for row in products:
		inventory_id = frappe.db.get_value("CRM Product", row.product_code, "acumatica_id")
		if not inventory_id:
			continue
		line = {
			"InventoryID": inventory_id,
			"OrderQty": row.qty or 1,
			"UnitPrice": row.rate,
			"DiscountPercent": row.discount_percentage,
		}
		# Acumatica reprices any line whose price keys are absent; send what the deal
		# negotiated, and only the keys the row actually carries.
		details.append({key: value for key, value in line.items() if value is not None})

	if products and not details:
		frappe.throw(
			_("None of this deal's products are linked to Acumatica inventory items — run a backfill first")
		)

	payload = {
		"OrderType": settings.quote_order_type,
		"CustomerID": customer_id,
		"Description": f"Vectora deal {deal.name}",
	}
	if details:
		payload["Details"] = details

	created = AcumaticaClient(settings).put("SalesOrder", payload)
	order_nbr = v(created, "OrderNbr") or ""
	if order_nbr:
		frappe.db.set_value("CRM Deal", deal.name, "acumatica_sales_quote", order_nbr)
	return order_nbr
