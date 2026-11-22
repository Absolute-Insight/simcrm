import frappe

from crm.integrations.acumatica.importer import person_name


def execute():
	"""Contacts the Acumatica import named twice over ("Ana Diaz Ana Diaz").

	Where Acumatica held the whole name in LastName, the import copied it into the
	first name as well. The import no longer does; this repairs the rows it wrote.
	Only contacts that came from Acumatica: a hand-entered "Thomas Thomas" is left.
	The record's docname is not changed, so every link to it stands."""
	if not frappe.db.has_column("Contact", "acumatica_noteid"):
		return
	rows = frappe.db.sql(
		"""select name, first_name, middle_name from `tabContact`
		where ifnull(acumatica_noteid, '') != '' and first_name = last_name and first_name != ''""",
		as_dict=True,
	)
	for row in rows:
		first, last = person_name(None, row.first_name)
		if not first:
			continue
		full_name = " ".join(part for part in (first, (row.middle_name or "").strip(), last) if part)
		frappe.db.set_value(
			"Contact",
			row.name,
			{"first_name": first, "last_name": last, "full_name": full_name},
			update_modified=False,
		)
		# the copy a deal's contact row fetched when the deal was last saved
		frappe.db.set_value(
			"CRM Contacts", {"contact": row.name}, "full_name", full_name, update_modified=False
		)
