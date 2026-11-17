"""Show each customer's head account, and fill it in from Acumatica once.

MBP keeps a mine's plants and shafts as customers of their own under a head
account (Customer.ParentRecord). The sync now records it on every customer it
reads, but it reads only customers modified since its last run, so the sites
already imported would wait for an edit in Acumatica. This queues one read of
every customer's parent (``importer.link_head_accounts``, GETs only) on a site
with the integration on, and puts the field beside the customer code on the
organization side panel where the Acumatica section already is -- the same
reasoning as ``add_vat_number_to_organization_side_panel``. Idempotent.
"""

import json

import frappe

LAYOUT = "CRM Organization-Side Panel"
ANCHOR = "tax_registration_id"
FALLBACK_ANCHOR = "acumatica_id"
FIELD = "head_account"


def _columns(layout):
	for section in layout:
		yield from section.get("columns", [])
		for nested in section.get("sections", []):
			yield from nested.get("columns", [])


def _place_on_side_panel():
	if not frappe.db.exists("CRM Fields Layout", LAYOUT):
		return
	doc = frappe.get_doc("CRM Fields Layout", LAYOUT)
	try:
		layout = json.loads(doc.layout or "[]")
	except (ValueError, TypeError):
		return
	columns = list(_columns(layout))
	if any(FIELD in column.get("fields", []) for column in columns):
		return
	for anchor in (ANCHOR, FALLBACK_ANCHOR):
		for column in columns:
			fields = column.get("fields", [])
			if anchor in fields:
				fields.insert(fields.index(anchor) + 1, FIELD)
				doc.layout = json.dumps(layout)
				doc.save(ignore_permissions=True)
				return


def execute():
	# Patches run before after_migrate, which is what creates the custom fields.
	from crm.integrations.acumatica.install import ensure_custom_fields

	ensure_custom_fields()
	if not frappe.get_meta("CRM Organization").has_field(FIELD):
		return
	_place_on_side_panel()
	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		frappe.enqueue(
			"crm.integrations.acumatica.importer.link_head_accounts",
			queue="long",
			enqueue_after_commit=True,
		)
