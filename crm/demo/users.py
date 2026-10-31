from datetime import datetime, timedelta

import frappe
from frappe.query_builder import DocType

from crm.demo.utils import delete_unless_linked

DEMO_USERS = [
	{
		"email": "sarah.demo@example.com",
		"first_name": "Sarah",
		"last_name": "Connor",
		"mobile_no": "+1 555 100 0002",
		"roles": ["Sales Manager", "Sales User"],
		"avatar": "/assets/crm/images/demo/sarah-connor.png",
	},
	{
		"email": "john.demo@example.com",
		"first_name": "John",
		"last_name": "Parker",
		"mobile_no": "+1 555 100 0003",
		"roles": ["Sales User"],
		"avatar": "/assets/crm/images/demo/john-parker.png",
	},
	{
		"email": "emily.demo@example.com",
		"first_name": "Emily",
		"last_name": "Chen",
		"mobile_no": "+1 555 100 0004",
		"roles": ["Sales User"],
		"avatar": "/assets/crm/images/demo/emily-chen.png",
	},
]

DEMO_USER_EMAILS = [u["email"] for u in DEMO_USERS]


def create_demo_users():
	for user_data in DEMO_USERS:
		if not frappe.db.exists("User", user_data["email"]):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": user_data["email"],
					"first_name": user_data["first_name"],
					"last_name": user_data["last_name"],
					"send_welcome_email": 0,
					"user_type": "System User",
					"mobile_no": user_data["mobile_no"],
					"user_image": user_data["avatar"],
					"roles": [{"role": r} for r in user_data["roles"]],
				}
			).insert(ignore_permissions=True)

	# Backdate auto-created contacts and set their image
	_ts = datetime.now() - timedelta(days=70)
	_avatar_by_email = {u["email"]: u["avatar"] for u in DEMO_USERS}
	contact_names = frappe.get_all(
		"Contact", filters={"user": ["in", DEMO_USER_EMAILS]}, fields=["name", "user"]
	)
	for row in contact_names:
		frappe.db.set_value(
			"Contact",
			row.name,
			{"image": _avatar_by_email.get(row.user, ""), "creation": _ts, "modified": _ts},
			update_modified=False,
		)

	return DEMO_USER_EMAILS


def delete_demo_users(demo_user_emails):
	# delete notifications first — they link to users and block deletion
	Notification = DocType("CRM Notification")
	frappe.qb.from_(Notification).delete().where(
		(Notification.from_user.isin(demo_user_emails)) | (Notification.to_user.isin(demo_user_emails))
	).run()

	contact_names = []
	for email in demo_user_emails:
		if not frappe.db.exists("User", email):
			continue
		# collect before deleting -- User.on_trash NULLs contact.user
		contacts = frappe.get_all("Contact", filters={"user": email}, pluck="name")
		if delete_unless_linked("User", email):
			contact_names.extend(contacts)
			continue
		# A real record adopted this demo rep -- a lead they own, say -- and would
		# refuse every save with the user gone. Disabled, it cannot sign in.
		user = frappe.get_doc("User", email)
		user.enabled = 0
		user.save(ignore_permissions=True)

	if contact_names:
		for child_doctype in ("Contact Email", "Contact Phone", "Dynamic Link"):
			Child = DocType(child_doctype)
			frappe.qb.from_(Child).delete().where(Child.parent.isin(contact_names)).run()
		Contact = DocType("Contact")
		frappe.qb.from_(Contact).delete().where(Contact.name.isin(contact_names)).run()
