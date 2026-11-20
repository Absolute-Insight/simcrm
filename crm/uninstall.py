# Copyright (c) 2022, Frappe Technologies Pvt. Ltd. and Contributors
# MIT License. See license.txt
import click
import frappe

from crm.permissions.users import restore_user_select


def before_uninstall():
	delete_email_template_custom_fields()
	# crm withdrew it and took over the User picker; frappe's picker needs it back
	restore_user_select()


def delete_email_template_custom_fields():
	if frappe.get_meta("Email Template").has_field("enabled"):
		click.secho("* Uninstalling Custom Fields from Email Template")

		fieldnames = (
			"enabled",
			"reference_doctype",
		)

		for fieldname in fieldnames:
			frappe.db.delete("Custom Field", {"name": "Email Template-" + fieldname})

		frappe.clear_cache(doctype="Email Template")
