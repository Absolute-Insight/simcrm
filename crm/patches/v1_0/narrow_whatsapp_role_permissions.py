import frappe

# what crm.api.whatsapp.add_roles used to grant both CRM roles, on top of read
OLD_GRANT = ("write", "create", "delete", "share", "email", "print", "report", "export")


def execute():
	"""Take back the WhatsApp doctype rights add_roles handed every CRM role.

	add_roles gave Sales User and Sales Manager create, write and delete on
	WhatsApp Message, Templates and Settings, which opened the REST API around
	the send endpoints' checks. It now grants read (and the settings pane to a
	manager), but skips a role that already has a row, so the old rows have to
	be narrowed here. Only a row still exactly as add_roles wrote it is touched:
	one an administrator has edited since is theirs.
	"""
	if "frappe_whatsapp" not in frappe.get_installed_apps():
		return

	from crm.api.whatsapp import WHATSAPP_PERMISSIONS

	for doctype in ("WhatsApp Message", "WhatsApp Templates", "WhatsApp Settings"):
		for role in ("Sales Manager", "Sales User"):
			allowed = set(WHATSAPP_PERMISSIONS.get(doctype, {}).get(role, ()))
			rows = frappe.get_all(
				"Custom DocPerm",
				filters={"parent": doctype, "role": role, "permlevel": 0},
				fields=["name", *OLD_GRANT],
			)
			for row in rows:
				if not all(row[ptype] for ptype in OLD_GRANT):
					continue
				if not allowed:
					frappe.delete_doc("Custom DocPerm", row.name, ignore_permissions=True, force=True)
					continue
				frappe.db.set_value(
					"Custom DocPerm",
					row.name,
					{ptype: int(ptype in allowed) for ptype in ("read", *OLD_GRANT)},
					update_modified=False,
				)
		frappe.clear_cache(doctype=doctype)
