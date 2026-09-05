import hmac

import frappe
from frappe import _

# Paste into Acumatica's Push Notifications (SM302000) webhook destination:
# https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification?key=<webhook_verify_token>
# The payload is deliberately ignored: this endpoint only triggers a pull
# through the authenticated client, so its worst-case abuse is a redundant sweep.


# POST only: Acumatica's push notifications POST, and a GET endpoint carrying the
# verify token in the query string is the shape that ends up in proxy access logs
# and browser history.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: guest-whitelisted-method
def handle_notification():
	key = frappe.request.args.get("key") if frappe.request else None
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	stored = settings.get_password("webhook_verify_token", raise_exception=False)
	if not (key and stored and hmac.compare_digest(key, stored)):
		frappe.throw(_("Invalid webhook key"), frappe.PermissionError)

	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		frappe.enqueue(
			"crm.integrations.acumatica.importer.nightly_sweep",
			queue="long",
			job_id="acumatica_webhook_sweep",
			deduplicate=True,  # a burst of notifications collapses to one sweep
		)
	return {"ok": True}
