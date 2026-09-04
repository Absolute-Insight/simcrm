import frappe
from frappe import _

MAX_MATCHES = 20


@frappe.whitelist()
def find_by_code(code: str) -> list[dict]:
	"""Organizations whose Acumatica customer code starts with ``code``.

	``acumatica_id`` is a custom field that only exists once
	``ensure_custom_fields()`` has run. As sync bookkeeping its absence was
	invisible; as a search key it would be *silent* -- an empty result set that
	reads as "search is broken" and gets debugged as one. So the absence is the
	first thing checked, and it is reported, not swallowed."""
	frappe.has_permission("CRM Organization", "read", throw=True)
	if not frappe.get_meta("CRM Organization").get_field("acumatica_id"):
		frappe.throw(
			_(
				"Searching by customer code needs the Acumatica ID field, which is not installed on this site. "
				"Run crm.integrations.acumatica.install.ensure_custom_fields."
			),
			frappe.ValidationError,
			title=_("Not set up"),
		)
	code = (code or "").strip()
	if not code:
		frappe.throw(_("Enter a customer code."), frappe.ValidationError)
	return frappe.get_all(
		"CRM Organization",
		filters={"acumatica_id": ("like", f"{code}%")},
		fields=["name", "acumatica_id"],
		order_by="acumatica_id asc",
		limit=MAX_MATCHES,
	)
