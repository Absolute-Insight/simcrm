import frappe


@frappe.whitelist()
def get_deal_contacts(name: str):
	frappe.has_permission("CRM Deal", "read", doc=name, throw=True)
	contacts = frappe.get_all(
		"CRM Contacts",
		filters={"parenttype": "CRM Deal", "parent": name},
		fields=["contact", "is_primary"],
		order_by="is_primary desc, idx asc",
		distinct=True,
	)
	# One read for all of them. This was a get_doc per contact -- the row and
	# every child table of each -- for five columns that live on tabContact. Like
	# the get_doc it replaces it is not row-scoped: the deal was permission-checked
	# above, and its own contacts are part of what that deal shows.
	names = [contact.contact for contact in contacts if contact.contact]
	details = (
		{
			row.name: row
			for row in frappe.get_all(
				"Contact",
				filters={"name": ("in", names)},
				fields=["name", "image", "full_name", "email_id", "mobile_no"],
				limit=len(names),
			)
		}
		if names
		else {}
	)

	deal_contacts = []
	for contact in contacts:
		detail = details.get(contact.contact)
		# no contact on the row, or one that has since been deleted
		if not detail:
			continue

		deal_contacts.append(
			{
				"name": detail.name,
				"image": detail.image,
				"full_name": detail.full_name,
				"email": detail.email_id,
				"mobile_no": detail.mobile_no,
				"is_primary": contact.is_primary,
			}
		)
	return deal_contacts
