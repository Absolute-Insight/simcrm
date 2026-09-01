import frappe
from frappe import _


def validate(doc, method):
	update_deals_email_mobile_no(doc)


def update_deals_email_mobile_no(doc):
	deal_names = frappe.get_all(
		"CRM Contacts",
		filters={"contact": doc.name, "is_primary": 1, "parenttype": "CRM Deal"},
		pluck="parent",
		distinct=True,
	)
	if not deal_names:
		return

	# one read and one write for every linked deal rather than a pair per deal
	deals = frappe.get_all(
		"CRM Deal",
		filters={"name": ("in", deal_names)},
		fields=["name", "email", "mobile_no"],
	)
	to_update = [d.name for d in deals if d.email != doc.email_id or d.mobile_no != doc.mobile_no]
	if to_update:
		frappe.db.set_value(
			"CRM Deal",
			{"name": ("in", to_update)},
			{"email": doc.email_id, "mobile_no": doc.mobile_no},
		)


@frappe.whitelist()
def get_linked_deals(contact: str):
	"""Get linked deals for a contact"""

	if not frappe.has_permission("Contact", "read", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	deal_names = frappe.get_all(
		"CRM Contacts",
		filters={"contact": contact, "parenttype": "CRM Deal"},
		pluck="parent",
		distinct=True,
	)
	if not deal_names:
		return []

	# get_list, not get_cached_doc: the rows come back through the deal's own
	# permission query, so a contact shared across teams shows only the deals
	# the caller may read
	return frappe.get_list(
		"CRM Deal",
		filters={"name": ("in", deal_names)},
		fields=[
			"name",
			"organization",
			"currency",
			"deal_value",
			"status",
			"email",
			"mobile_no",
			"deal_owner",
			"modified",
		],
		order_by="modified desc",
	)


@frappe.whitelist()
def create_new(contact: str, field: str, value: str):
	"""Create new email or phone for a contact"""
	if not frappe.has_permission("Contact", "write", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	contact = frappe.get_cached_doc("Contact", contact)

	if field == "email":
		email = {"email_id": value, "is_primary": 1 if len(contact.email_ids) == 0 else 0}
		contact.append("email_ids", email)
	elif field in ("mobile_no", "phone"):
		mobile_no = {"phone": value, "is_primary_mobile_no": 1 if len(contact.phone_nos) == 0 else 0}
		contact.append("phone_nos", mobile_no)
	else:
		frappe.throw(_("Invalid field"))

	contact.save()
	return True


@frappe.whitelist()
def set_as_primary(contact: str, field: str, value: str):
	"""Set email or phone as primary for a contact"""
	if not frappe.has_permission("Contact", "write", contact):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	contact = frappe.get_doc("Contact", contact)

	if field == "email":
		for email in contact.email_ids:
			if email.email_id == value:
				email.is_primary = 1
			else:
				email.is_primary = 0
	elif field in ("mobile_no", "phone"):
		name = "is_primary_mobile_no" if field == "mobile_no" else "is_primary_phone"
		for phone in contact.phone_nos:
			if phone.phone == value:
				phone.set(name, 1)
			else:
				phone.set(name, 0)
	else:
		frappe.throw(_("Invalid field"))

	contact.save()
	return True


@frappe.whitelist()
def search_emails(txt: str):
	doctype = "Contact"
	meta = frappe.get_meta(doctype)
	filters = [["Contact", "email_id", "is", "set"]]

	if meta.get("fields", {"fieldname": "enabled", "fieldtype": "Check"}):
		filters.append([doctype, "enabled", "=", 1])
	if meta.get("fields", {"fieldname": "disabled", "fieldtype": "Check"}):
		filters.append([doctype, "disabled", "!=", 1])

	or_filters = []
	search_fields = ["full_name", "email_id", "name"]
	if txt:
		for f in search_fields:
			or_filters.append([doctype, f.strip(), "like", f"%{txt}%"])

	results = frappe.get_list(
		doctype,
		filters=filters,
		fields=search_fields,
		or_filters=or_filters,
		limit_start=0,
		limit_page_length=20,
		order_by="email_id, full_name, name",
		ignore_permissions=False,
		as_list=True,
		strict=False,
	)

	return results
