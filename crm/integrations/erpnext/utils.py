import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

CASCADE_FLAG = "crm_product_item_cascade_in_progress"
ALLOWED_DOCTYPES = ("CRM Product", "Item")


def should_sync() -> bool:
	"""ERPNext Item to CRM Product sync runs when same-site integration is enabled."""
	if "erpnext" not in frappe.get_installed_apps():
		return False
	settings = frappe.get_cached_doc("ERPNext CRM Settings")
	return bool(settings.enabled) and not settings.is_erpnext_in_different_site


def should_push_to_erpnext() -> bool:
	"""CRM Product to ERPNext Item sync is optional until CRM supports ERPNext tax details."""
	if not should_sync():
		return False
	settings = frappe.get_cached_doc("ERPNext CRM Settings")
	return bool(settings.sync_products)


def in_cascade() -> bool:
	return bool(frappe.flags.get(CASCADE_FLAG))


def set_links(item_code: str, crm_product_name: str) -> None:
	"""Permission-bypassing link bookkeeping. Mirrors HD's set_links."""
	frappe.db.set_value(
		"CRM Product", crm_product_name, "erpnext_item_code", item_code, update_modified=False
	)
	frappe.db.set_value("Item", item_code, "crm_product_code", crm_product_name, update_modified=False)


def _other_side(self_doctype: str) -> tuple[str, str]:
	if self_doctype == "CRM Product":
		return "Item", "crm_product_code"
	return "CRM Product", "erpnext_item_code"


def find_target_for(doctype: str | None, value: str | None) -> tuple[str, str] | None:
	if not doctype or not value:
		return None
	if doctype == "CRM Product":
		item = frappe.db.get_value("Item", {"crm_product_code": value}, "name")
		return ("Item", item) if item else None
	if doctype == "Item":
		prod = frappe.db.get_value("CRM Product", {"erpnext_item_code": value}, "name")
		return ("CRM Product", prod) if prod else None
	return None


def validate_rename_conflict(self_doctype, olddn, newdn, merge):
	if in_cascade() or not _should_sync_direction(self_doctype):
		return
	other_doctype, other_link_field = _other_side(self_doctype)
	linked = frappe.db.get_value(other_doctype, {other_link_field: olddn}, "name")
	if not linked:
		return
	if merge:
		surviving = frappe.db.get_value(other_doctype, {other_link_field: newdn}, "name")
		if surviving:
			return
	if linked == newdn:
		return
	if frappe.db.exists(other_doctype, newdn):
		existing_link = frappe.db.get_value(other_doctype, newdn, other_link_field)
		if existing_link != olddn:
			frappe.throw(
				_(
					"Cannot rename: an unrelated {0} '{1}' already exists on the "
					"other side. Resolve manually first."
				).format(other_doctype, newdn)
			)


def cascade_rename(self_doctype, olddn, newdn, merge):
	if in_cascade() or not _should_sync_direction(self_doctype):
		return
	other_doctype, other_link_field = _other_side(self_doctype)
	linked = frappe.db.get_value(other_doctype, {other_link_field: olddn}, "name")
	if not linked:
		return
	frappe.flags[CASCADE_FLAG] = True
	try:
		if merge:
			surviving = frappe.db.get_value(other_doctype, {other_link_field: newdn}, "name")
			if surviving and surviving != linked:
				rename_doc(other_doctype, linked, surviving, merge=True, ignore_permissions=True)
				target = surviving
			else:
				if linked != newdn:
					rename_doc(other_doctype, linked, newdn, ignore_permissions=True)
				target = newdn
		else:
			if linked != newdn:
				rename_doc(other_doctype, linked, newdn, ignore_permissions=True)
			target = newdn
		_resync_links(self_doctype, newdn, target)
	finally:
		frappe.flags[CASCADE_FLAG] = False


def _resync_links(self_doctype, self_name, other_name):
	if self_doctype == "CRM Product":
		prod, item = self_name, other_name
	else:
		prod, item = other_name, self_name
	if frappe.db.exists("CRM Product", prod):
		frappe.db.set_value("CRM Product", prod, "erpnext_item_code", item, update_modified=False)
	if frappe.db.exists("Item", item):
		frappe.db.set_value("Item", item, "crm_product_code", prod, update_modified=False)


def _should_sync_direction(self_doctype):
	if self_doctype == "CRM Product":
		return should_push_to_erpnext()
	return should_sync()


def crm_company() -> str | None:
	"""The ERPNext company this CRM quotes and invoices as."""
	return frappe.get_cached_doc("ERPNext CRM Settings").erpnext_company or None


def item_open_to_company(item, company: str | None) -> bool:
	"""Whether ERPNext lets ``company`` transact with this Item.

	ERPNext can restrict an Item to a list of companies (``restrict_to_companies``
	with ``allowed_companies`` rows). A transaction for any other company that
	names the Item is refused on save, and users of other companies do not see
	it at all. The CRM catalogue has no company dimension, so an Item closed to
	the CRM's company must not be offered in it: a rep would add it to a deal
	and only learn at the quotation that it cannot be sold, having seen the
	name and price of something ERPNext hides from them.

	With no company configured there is nothing to match the list against, and a
	restricted Item is treated as closed: the restriction says "these companies
	only", and we cannot show we are one of them.

	Reads the document it is given, so the Item hooks can ask about the row in
	hand (and about the one before the save) without a query.
	"""
	if not item.get("restrict_to_companies"):
		return True
	if not company:
		return False
	return any(row.get("company") == company for row in item.get("allowed_companies") or [])


def items_closed_to_crm(item_codes: list[str] | None = None) -> set[str]:
	"""Of ``item_codes`` (or of every Item), those restricted away from the CRM's company.

	The set-based twin of :func:`item_open_to_company`, for callers holding names
	rather than documents. Two queries whatever the number of items. An ERPNext
	that predates company restrictions has no such field, and nothing is closed.
	"""
	if not frappe.db.exists("DocType", "Item") or not frappe.get_meta("Item").has_field(
		"restrict_to_companies"
	):
		return set()

	filters = {"restrict_to_companies": 1}
	if item_codes is not None:
		item_codes = [code for code in item_codes if code]
		if not item_codes:
			return set()
		filters["name"] = ("in", item_codes)

	restricted = set(frappe.get_all("Item", filters=filters, pluck="name"))
	company = crm_company()
	if not restricted or not company:
		return restricted

	allowed = frappe.get_all(
		"Company Restriction",
		filters={
			"parenttype": "Item",
			"parentfield": "allowed_companies",
			"parent": ("in", sorted(restricted)),
			"company": company,
		},
		pluck="parent",
	)
	return restricted - set(allowed)
