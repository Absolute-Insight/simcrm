import html
import re

import frappe

# What rename_doc writes on the surviving organization, with the old name first.
# Both comments move with any later rename (Comment.reference_name is a Dynamic
# Link), so a chain A -> B -> C leaves both on C.
RENAME_COMMENT = re.compile(r"^(?:renamed from|merged) <strong>(.+?)</strong> (?:to|into) <strong>")


def execute():
	"""Re-point contacts that an organization rename left behind.

	Contact.company_name is a Data field, so renaming or merging an organization
	never rewrote it until CRM Organization.after_rename did. The old name is
	recovered from the "renamed from" / "merged" comment frappe adds to the
	renamed record. An old name that an organization holds again today belongs to
	that organization, so its contacts are left alone; re-running changes nothing.
	"""
	comments = frappe.get_all(
		"Comment",
		filters={
			"reference_doctype": "CRM Organization",
			"comment_type": "Edit",
			"content": ("like", "%<strong>%"),
		},
		fields=["reference_name", "content"],
		order_by="creation asc",
	)
	for comment in comments:
		match = RENAME_COMMENT.match(comment.content or "")
		if not match:
			continue
		old_name = html.unescape(match.group(1))
		if frappe.db.exists("CRM Organization", old_name):
			continue
		if not frappe.db.exists("CRM Organization", comment.reference_name):
			continue
		frappe.db.set_value(
			"Contact",
			{"company_name": old_name},
			"company_name",
			comment.reference_name,
			update_modified=False,
		)
