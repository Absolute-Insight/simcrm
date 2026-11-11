import frappe

from crm.fcrm.doctype.crm_product.sync_utils import payload_differs
from crm.integrations.erpnext.utils import (
	CASCADE_FLAG,
	cascade_rename,
	crm_company,
	in_cascade,
	item_open_to_company,
	set_links,
	should_sync,
	validate_rename_conflict,
)

CATALOGUE_FIELDS = ("standard_rate", "image", "disabled", "description")


def _should_sync(doc) -> bool:
	return should_sync() and not doc.flags.get("ignore_crm_sync")


def get_item_price_rate(item_code: str, uom: str | None = None):
	from erpnext.stock.get_item_details import get_item_price

	price_list = frappe.db.get_single_value("Selling Settings", "selling_price_list")
	if not price_list:
		return None
	pctx = frappe._dict({"price_list": price_list, "uom": uom, "transaction_date": frappe.utils.nowdate()})
	rows = get_item_price(pctx, item_code)
	if not rows:
		return None
	row = rows[0]

	return row.price_list_rate if isinstance(row, dict) else row[1]


def _catalogue_data(doc) -> dict:
	data = {f: doc.get(f) for f in CATALOGUE_FIELDS}
	# Give preference to Item Price over standard rate
	# keep standard_rate as fallback
	rate = get_item_price_rate(doc.name, doc.get("stock_uom"))
	if rate is not None:
		data["standard_rate"] = rate
	# An Item with neither an Item Price nor a standard rate leaves this None,
	# and on_update writes the payload with frappe.db.set_value, which passes
	# raw values straight to the column (no flt coercion, unlike doc.insert).
	# standard_rate is a NOT NULL Currency, so the write raised IntegrityError.
	# Coercing here also stops payload_differs seeing None != 0.0 forever and
	# rewriting the row on every Item save.
	data["standard_rate"] = frappe.utils.flt(data["standard_rate"])
	# An Item restricted away from the CRM's company stays linked but is switched
	# off here, whatever its own `disabled` says: the link is what carries a
	# rename or a delete across, and a deal may already hold the product.
	if not item_open_to_company(doc, crm_company()):
		data["disabled"] = 1
	return data


def after_insert(doc, method=None):
	if not _should_sync(doc):
		return
	# Not mirrored at all: a product row, even a disabled one, would publish the
	# name and price of an Item ERPNext shows only to other companies.
	if not item_open_to_company(doc, crm_company()):
		return
	if frappe.db.get_value("CRM Product", {"erpnext_item_code": doc.name}):
		return
	_create_product(doc)


def _create_product(doc):
	product = frappe.get_doc(
		{
			"doctype": "CRM Product",
			"product_code": doc.item_code,
			"product_name": doc.item_name,
			**_catalogue_data(doc),
		}
	)
	product.flags.ignore_erpnext_sync = True
	product.insert(ignore_permissions=True)
	set_links(doc.name, product.name)


def on_update(doc, method=None):
	if not _should_sync(doc):
		return
	product_name = frappe.db.get_value("CRM Product", {"erpnext_item_code": doc.name})
	if not product_name:
		if _restriction_lifted(doc):
			_create_product(doc)
		return
	data = {
		"product_name": doc.item_name,
		**_catalogue_data(doc),
	}
	current = frappe.db.get_value("CRM Product", product_name, list(data.keys()), as_dict=True) or {}
	if not payload_differs(data, current):
		return
	frappe.db.set_value("CRM Product", product_name, data)


def _restriction_lifted(doc) -> bool:
	"""True when this save opened to the CRM's company an Item that was closed to it.

	Only that edge creates the product an insert would have. Any other save of
	an Item with no product leaves it alone, as before: one made while the sync
	was off is for the reconciliation to pick up, not for the next edit.
	"""
	before = doc.get_doc_before_save()
	if not before:
		return False
	company = crm_company()
	return item_open_to_company(doc, company) and not item_open_to_company(before, company)


def before_rename(doc, method=None, olddn=None, newdn=None, merge=False):
	validate_rename_conflict("Item", olddn, newdn, merge)


def after_rename(doc, method=None, olddn=None, newdn=None, merge=False):
	cascade_rename("Item", olddn, newdn, merge)


def on_trash(doc, method=None):
	if in_cascade() or not _should_sync(doc):
		return
	product = frappe.db.get_value("CRM Product", {"erpnext_item_code": doc.name})
	if not product:
		return
	# Clear back link first so CRMProduct.on_trash won't try to delete this Item
	frappe.db.set_value("CRM Product", product, "erpnext_item_code", None)
	frappe.flags[CASCADE_FLAG] = True
	try:
		frappe.delete_doc("CRM Product", product, ignore_permissions=True)
	finally:
		frappe.flags[CASCADE_FLAG] = False
