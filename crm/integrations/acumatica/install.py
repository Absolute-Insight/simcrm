import json

import frappe
from frappe import _
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _identity_fields(insert_after, permlevel=0, **id_field):
	return [
		{
			"fieldname": "acumatica_noteid",
			"fieldtype": "Data",
			"label": "Acumatica NoteID",
			"hidden": 1,
			"search_index": 1,
			"insert_after": insert_after,
			"permlevel": permlevel,
		},
		{
			"fieldname": "acumatica_id",
			"fieldtype": "Data",
			"label": "Acumatica ID",
			"read_only": 1,
			"insert_after": "acumatica_noteid",
			"permlevel": permlevel,
			**id_field,
		},
	]


# An organization's Acumatica ID is the customer code the sales team knows the
# account by (C-SIB001F), so on organizations and deals it carries that name and
# is a list column and a search key. Read-only still: the sync
# matches organizations on it, so a hand-edited code would split one customer
# in two at the next pull.
CUSTOMER_CODE = "Customer Code"


def ensure_custom_fields() -> None:
	"""Identity fields the sync keys on. NoteID is Acumatica's rename-stable GUID;
	the human-readable ID is the customer code. Idempotent, and an existing field
	is updated to the properties below (create_custom_fields' ``update``), so a
	relabel reaches existing sites at their next migrate."""
	create_custom_fields(
		{
			"CRM Organization": [
				# permlevel 1, which CRM Organization lets a Sales User read and only a
				# manager write: read_only and hidden are the form's, and the server does
				# not enforce them -- a rep could otherwise set_value an organization
				# onto another customer's code, or off its own to have it pushed again.
				# The sync and the push write past it with ignore_permissions.
				*_identity_fields(
					"organization_name",
					permlevel=1,
					label=CUSTOMER_CODE,
					in_list_view=1,
					search_index=1,
				),
				{
					# Acumatica's TaxRegistrationID: pulled in by the sync, sent with a new
					# customer, and the one sure sign two organizations are one taxpayer
					"fieldname": "tax_registration_id",
					"fieldtype": "Data",
					"label": "VAT Number",
					"insert_after": "acumatica_id",
				},
				{
					# A manager looked at the possible duplicates and said this one is new:
					# the fingerprint (outbound.confirmation_hash) of the name, VAT number
					# and primary-contact email they saw. The push skips the duplicate
					# checks only while the organization still matches it, so a rename
					# after the confirmation is checked afresh. Set only by
					# api.confirm_new_customer; permlevel 1 keeps reps from setting it.
					"fieldname": "acumatica_confirmed_for",
					"fieldtype": "Data",
					"label": "Confirmed New Acumatica Customer",
					"hidden": 1,
					"read_only": 1,
					"permlevel": 1,
					"insert_after": "tax_registration_id",
				},
			],
			"Contact": _identity_fields("company_name"),
			"CRM Product": _identity_fields("product_code"),
			"CRM Deal": [
				{
					"fieldname": "acumatica_customer",
					"fieldtype": "Data",
					"label": CUSTOMER_CODE,
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
	ensure_customer_code_search()


# Defaults a new field on the settings Single would never get on an existing site:
# frappe applies a Single's defaults only while nothing at all is stored for it.
CUSTOMER_PUSH_DEFAULTS = {"new_customer_class": "COD", "home_country": "South Africa"}


def ensure_customer_push_defaults() -> None:
	"""after_migrate: give a saved settings Single the customer-push defaults it
	predates. Only a field with no stored row at all is filled -- saving the Single
	stores every field, cleared ones included, so an admin's blank survives -- and
	nothing is written to a Single that was never saved, which still reads its
	defaults from the doctype (writing one row would end that)."""
	# tabSingles has no creation column, so not frappe.get_all (which orders by it)
	Singles = frappe.qb.DocType("Singles")
	stored = set(
		frappe.qb.from_(Singles)
		.select(Singles.field)
		.where(Singles.doctype == "CRM Acumatica Settings")
		.run(pluck=True)
	)
	if not stored:
		return
	for field, value in CUSTOMER_PUSH_DEFAULTS.items():
		if field in stored:
			continue
		if field == "home_country" and not frappe.db.exists("Country", value):
			continue
		frappe.db.set_single_value("CRM Acumatica Settings", field, value)


def ensure_customer_code_search() -> None:
	"""Make the customer code a search field of CRM Organization.

	A link search then matches "C-SIB" as well as the name, and returns the code
	as the option's description, so every organization picker shows it under the
	name. A Property Setter rather than the doctype JSON: the field is custom,
	and the doctype syncs before after_migrate creates it. Any search field an
	admin already set is kept.
	"""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	current = frappe.get_meta("CRM Organization").search_fields or ""
	fields = [f.strip() for f in current.split(",") if f.strip()]
	if "acumatica_id" in fields:
		return
	make_property_setter(
		"CRM Organization",
		None,
		"search_fields",
		",".join(["acumatica_id", *fields]),
		"Data",
		for_doctype=True,
		validate_fields_for_doctype=False,
	)


# layout -> the ids a rep needs to find the record in Acumatica
LAYOUT_FIELDS = {
	"CRM Deal-Side Panel": ["acumatica_customer", "acumatica_sales_quote"],
	"CRM Deal-Data Fields": ["acumatica_customer", "acumatica_sales_quote"],
	"CRM Organization-Side Panel": ["acumatica_id", "tax_registration_id"],
}
LAYOUT_SECTION = {"label": "Acumatica", "name": "acumatica_section", "opened": True}


def _layout_fields(layout) -> set:
	present = set()
	for section in layout:
		for column in section.get("columns", []):
			present.update(column.get("fields", []))
		for nested in section.get("sections", []):
			for column in nested.get("columns", []):
				present.update(column.get("fields", []))
	return present


def ensure_layout_fields() -> None:
	"""Put the Acumatica ids on the deal and organization pages.

	The custom fields exist on every site but a page layout is a saved record,
	so a site that enabled the integration after install showed none of them --
	a rep whose deal has a quote in Acumatica had no way to read its number.
	Adds an "Acumatica" section to each layout when the integration is turned on,
	and leaves a layout alone when an admin has already placed any of the fields."""
	if not frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		return
	for name, wanted in LAYOUT_FIELDS.items():
		if not frappe.db.exists("CRM Fields Layout", name):
			continue
		doc = frappe.get_doc("CRM Fields Layout", name)
		meta = frappe.get_meta(doc.dt)
		fields = [f for f in wanted if meta.has_field(f)]
		if not fields:
			continue
		try:
			layout = json.loads(doc.layout or "[]")
		except (ValueError, TypeError):
			continue
		if any(f in _layout_fields(layout) for f in fields):
			continue
		section = {
			**LAYOUT_SECTION,
			"columns": [{"name": "column_acumatica", "fields": fields}],
		}
		# the Data tab nests its sections under a tab; the side panels do not
		target = layout[0]["sections"] if layout and "sections" in layout[0] else layout
		target.append(section)
		doc.layout = json.dumps(layout)
		doc.save(ignore_permissions=True)


def refresh_integration() -> None:
	"""after_migrate: the form script ships with the app, not with the site, so an
	upgrade brings its text up to date on a site that has the integration on.

	Only its text. Whether the script is enabled, and whether the Acumatica
	section is on a layout, are the admin's from the moment the integration is
	turned on (CRMAcumaticaSettings.on_update); re-applying either here undid a
	deliberate removal or disable on every migrate.
	"""
	if not frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		return
	frappe.get_doc("CRM Acumatica Settings").create_crm_form_script()


def block_dual_erp(doc, method=None) -> None:
	"""Reciprocal of CRM Acumatica Settings.validate: one ERP integration at a time.

	Enabling Acumatica already refuses while SIMERP is on; without this, enabling
	SIMERP from the other side silently leaves both running and both pushing
	customers. It lives here, wired through this app's doc_events, because
	crm/integrations/erpnext and the ERPNext settings doctype are not ours to edit."""
	if doc.enabled and frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		frappe.throw(
			_("Disable the Acumatica integration first — one ERP integration may be active at a time")
		)
