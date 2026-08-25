import frappe


def execute():
	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
