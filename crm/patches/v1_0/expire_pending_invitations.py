import frappe


def execute():
	"""Retire every invitation that was pending when keys became hashed and private.

	Until this release the key sat in the row in clear and every Sales User could
	read the row, so a pending key may already have been copied. The accept endpoint
	now looks keys up by their hash, which no old row has anyway; expiring them makes
	that explicit on the invitation itself instead of leaving rows that look live but
	cannot be redeemed. Administrators re-send from Settings -> Invite User.
	"""
	frappe.db.set_value(
		"CRM Invitation",
		{"status": "Pending"},
		{"status": "Expired", "key": None},
		update_modified=False,
	)
