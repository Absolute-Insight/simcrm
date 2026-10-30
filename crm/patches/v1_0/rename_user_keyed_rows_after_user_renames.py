import frappe

from crm.api.user import USER_KEYED_DOCTYPES, rename_user_keyed_row


def execute():
	"""Rename the visit targets and telephony agents a User rename left behind.

	Until the User ``after_rename`` hook, renaming a user rewrote the ``user``
	column of these rows but left them named after the old address, and every
	lookup is by name: the target could no longer be changed or cleared, and the
	agent's number was no longer found. Production renamed its placeholder rep
	logins once already.
	"""
	for doctype in USER_KEYED_DOCTYPES:
		for row in frappe.get_all(doctype, fields=["name", "user"]):
			if row.user and row.name != row.user:
				rename_user_keyed_row(doctype, row.name, row.user)
