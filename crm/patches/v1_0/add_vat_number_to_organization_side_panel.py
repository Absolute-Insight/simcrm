"""Put the VAT Number beside the Customer Code on the organization side panel.

``install.ensure_layout_fields`` adds the Acumatica section only when the integration
is turned on, and leaves a layout alone once it holds any Acumatica field -- so a site
that already shows the customer code (production, by its spreadsheet import) would
never show the VAT number the customer push now matches taxpayers on. One shot and
idempotent: it does nothing where the field is already placed, where the layout has
no customer code to sit beside, or where the field does not exist.
"""

import json

import frappe

LAYOUT = "CRM Organization-Side Panel"
ANCHOR = "acumatica_id"
FIELD = "tax_registration_id"


def _columns(layout):
	for section in layout:
		yield from section.get("columns", [])
		for nested in section.get("sections", []):
			yield from nested.get("columns", [])


def execute():
	# Patches run before after_migrate, which is what creates the custom field: on the
	# upgrade that ships it the field would not exist yet, and the patch, once marked
	# done, would never run again.
	from crm.integrations.acumatica.install import ensure_custom_fields

	ensure_custom_fields()
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	if not frappe.get_meta("CRM Organization").has_field(FIELD):
		return
	doc = frappe.get_doc("CRM Fields Layout", LAYOUT)
	try:
		layout = json.loads(doc.layout or "[]")
	except (ValueError, TypeError):
		return
	columns = list(_columns(layout))
	if any(FIELD in column.get("fields", []) for column in columns):
		return
	for column in columns:
		fields = column.get("fields", [])
		if ANCHOR in fields:
			fields.insert(fields.index(ANCHOR) + 1, FIELD)
			doc.layout = json.dumps(layout)
			doc.save(ignore_permissions=True)
			return
