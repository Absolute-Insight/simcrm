import hmac

import frappe
from frappe import _

from crm.integrations.acumatica.importer import SYNC_JOB_ID

# Paste into Acumatica's Push Notifications (SM302000) webhook destination:
# https://<site>/api/method/crm.integrations.acumatica.webhook.handle_notification
# with header X-Vectora-Key: <webhook_verify_token>. If the destination cannot set a
# header, ?key=<webhook_verify_token> on the URL still works.
# The payload is deliberately ignored: this endpoint only triggers a pull
# through the authenticated client, so its worst-case abuse is a redundant sweep.


# POST only: Acumatica's push notifications POST, and a GET endpoint carrying the
# verify token in the query string is the shape that ends up in proxy access logs
# and browser history.
@frappe.whitelist(allow_guest=True, methods=["POST"])  # nosemgrep: guest-whitelisted-method
def handle_notification():
	# The header is the primary channel: a query-string key lands in every access
	# log between Acumatica and this process. ?key= stays for destinations that
	# cannot set a header.
	key = None
	if frappe.request:
		key = frappe.request.headers.get("X-Vectora-Key") or frappe.request.args.get("key")
	settings = frappe.get_cached_doc("CRM Acumatica Settings")
	stored = settings.get_password("webhook_verify_token", raise_exception=False)
	if not (key and stored and hmac.compare_digest(key, stored)):
		frappe.throw(_("Invalid webhook key"), frappe.PermissionError)

	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		frappe.enqueue(
			"crm.integrations.acumatica.importer.nightly_sweep",
			queue="long",
			# the sweep, the scheduler and the manual backfill share one job id, so a
			# burst of notifications collapses to one sweep -- and cannot queue one
			# behind a backfill an admin started by hand
			job_id=SYNC_JOB_ID,
			deduplicate=True,
		)
	return {"ok": True}
