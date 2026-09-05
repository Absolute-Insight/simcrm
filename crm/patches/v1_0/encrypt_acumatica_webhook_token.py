import frappe


def execute():
	# webhook_verify_token was a Data field readable by every Sales User through
	# frappe.client.get_single_value; it is a Password field now. A plaintext value
	# left in tabSingles would fail to decrypt, so move it into the encrypted store.
	value = frappe.db.get_single_value("CRM Acumatica Settings", "webhook_verify_token")
	if not value or value.startswith("*"):
		return
	settings = frappe.get_doc("CRM Acumatica Settings")
	settings.webhook_verify_token = value
	settings.flags.ignore_validate = True
	settings.save(ignore_permissions=True)
