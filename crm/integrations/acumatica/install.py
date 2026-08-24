import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _identity_fields(insert_after):
	return [
		{
			"fieldname": "acumatica_noteid",
			"fieldtype": "Data",
			"label": "Acumatica NoteID",
			"hidden": 1,
			"search_index": 1,
			"insert_after": insert_after,
		},
		{
			"fieldname": "acumatica_id",
			"fieldtype": "Data",
			"label": "Acumatica ID",
			"read_only": 1,
			"insert_after": "acumatica_noteid",
		},
	]


def ensure_custom_fields() -> None:
	"""Identity fields the sync keys on. NoteID is Acumatica's rename-stable GUID;
	the human-readable ID is display only. Idempotent -- create_custom_fields
	skips fields that already exist."""
	create_custom_fields(
		{
			"CRM Organization": _identity_fields("organization_name"),
			"Contact": _identity_fields("company_name"),
			"CRM Product": _identity_fields("product_code"),
			"CRM Deal": [
				{
					"fieldname": "acumatica_customer",
					"fieldtype": "Data",
					"label": "Customer in Acumatica",
					"read_only": 1,
					"insert_after": "organization",
				},
				{
					# Idempotency key for the Create Sales Quote action: Acumatica's
					# SalesOrder PUT has no key in the body, so without this every click
					# would create another order.
					"fieldname": "acumatica_sales_quote",
					"fieldtype": "Data",
					"label": "Sales Quote in Acumatica",
					"read_only": 1,
					"insert_after": "acumatica_customer",
				},
			],
		},
		ignore_validate=True,
	)
