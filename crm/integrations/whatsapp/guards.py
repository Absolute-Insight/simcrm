"""frappe_whatsapp's logged-in endpoints, closed to everyone but System Managers.

Upstream whitelists these with no permission check, so any logged-in rep could
resend a bulk campaign from someone's number or pull every account's templates.
None is used by the CRM; an admin in Desk keeps them. Upstream is not modified.

The overrides do not cover ``frappe.handler.upload_file``, whose ``method``
argument goes straight to get_attr. That route is shut by name, before the
handler runs, for every upstream method at once: this one, the webhook and the
Flows endpoint alike.
"""

import frappe


def _upstream(path: str):
	frappe.only_for("System Manager")
	return frappe.get_attr(path)


BULK = "frappe_whatsapp.utils.bulk_messaging"
FLOW = "frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_flow.whatsapp_flow"


def refuse_upstream_methods_via_upload():
	method = frappe.form_dict.get("method")
	if not (isinstance(method, str) and method.startswith("frappe_whatsapp.")):
		return
	# frappe dispatches on form_dict.cmd from any path, not only /api/method/...
	if frappe.request.path.endswith("upload_file") or str(frappe.form_dict.get("cmd")).endswith(
		"upload_file"
	):
		raise frappe.PermissionError


@frappe.whitelist()
def get_progress(name: str):
	return _upstream(f"{BULK}.get_progress")(name)


@frappe.whitelist()
def retry_failed(name: str):
	return _upstream(f"{BULK}.retry_failed")(name)


@frappe.whitelist()
def import_recipients(
	list_name: str,
	doctype: str,
	mobile_field: str,
	name_field: str | None = None,
	filters: str | None = None,
	limit: int | None = None,
	data_fields: str | None = None,
):
	return _upstream(f"{BULK}.import_recipients")(
		list_name, doctype, mobile_field, name_field, filters, limit, data_fields
	)


@frappe.whitelist()
def schedule_bulk_messages():
	return _upstream(f"{BULK}.schedule_bulk_messages")()


@frappe.whitelist()
def fetch():
	return _upstream("frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_templates.whatsapp_templates.fetch")()


@frappe.whitelist()
def get_whatsapp_flows(whatsapp_account: str):
	return _upstream(f"{FLOW}.get_whatsapp_flows")(whatsapp_account)


@frappe.whitelist()
def sync_all_flows(whatsapp_account: str):
	return _upstream(f"{FLOW}.sync_all_flows")(whatsapp_account)


@frappe.whitelist()
def import_flow_from_whatsapp(whatsapp_account: str, flow_id: str, flow_name: str | None = None):
	return _upstream(f"{FLOW}.import_flow_from_whatsapp")(whatsapp_account, flow_id, flow_name)


@frappe.whitelist()
def call_trigger_notifications():
	return _upstream(
		"frappe_whatsapp.frappe_whatsapp.doctype.whatsapp_notification.whatsapp_notification.call_trigger_notifications"
	)()
