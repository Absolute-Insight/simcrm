import frappe
from frappe.query_builder import Order
from frappe.utils import now_datetime

# The panel lists the newest notifications only. The unread badge counts the
# whole inbox through get_unread_count, so it is not capped at this page.
PAGE_LENGTH = 50


@frappe.whitelist()
def get_notifications():
	# Bounded, with the sender's name joined in. This runs on every app load and
	# on every crm_notification event, and it returned the whole inbox with one
	# User query per row: hundreds of each for a rep the deal import assigned.
	Notification = frappe.qb.DocType("CRM Notification")
	User = frappe.qb.DocType("User")
	notifications = (
		frappe.qb.from_(Notification)
		.left_join(User)
		.on(User.name == Notification.from_user)
		.select(
			Notification.creation,
			Notification.from_user,
			User.full_name.as_("from_user_full_name"),
			Notification.type,
			Notification.to_user,
			Notification.read,
			Notification.message,
			Notification.notification_text,
			Notification.notification_type_doctype,
			Notification.notification_type_doc,
			Notification.reference_doctype,
			Notification.reference_name,
		)
		.where(Notification.to_user == frappe.session.user)
		.orderby(Notification.creation, order=Order.desc)
		.limit(PAGE_LENGTH)
	).run(as_dict=True)

	_notifications = []
	for notification in notifications:
		_notifications.append(
			{
				"creation": notification.creation,
				"from_user": {
					"name": notification.from_user,
					"full_name": notification.from_user_full_name,
				},
				"type": notification.type,
				"to_user": notification.to_user,
				"read": notification.read,
				"hash": get_hash(notification),
				"notification_text": notification.notification_text,
				"notification_type_doctype": notification.notification_type_doctype,
				"notification_type_doc": notification.notification_type_doc,
				"reference_doctype": ("deal" if notification.reference_doctype == "CRM Deal" else "lead"),
				"reference_name": notification.reference_name,
				"route_name": get_route_name(notification),
			}
		)

	return _notifications


@frappe.whitelist()
def get_unread_count() -> int:
	return frappe.db.count("CRM Notification", {"to_user": frappe.session.user, "read": 0})


@frappe.whitelist()
def mark_as_read(doc: str | None = None):
	user = frappe.session.user
	Notification = frappe.qb.DocType("CRM Notification")
	condition = (Notification.to_user == user) & (Notification.read == 0)
	if doc:
		condition &= (Notification.comment == doc) | (Notification.notification_type_doc == doc)

	if not frappe.qb.from_(Notification).select(Notification.name).where(condition).limit(1).run():
		return

	# One UPDATE and one event. A get_doc and save per row cost a few queries
	# each, and each save's on_update published crm_notification, which every
	# open tab answered by reloading the inbox: "mark all" on a few hundred rows
	# was a few hundred reloads of a few hundred rows. The rows are scoped to
	# the session user, which is all the per-document permission check allowed.
	(
		frappe.qb.update(Notification)
		.set(Notification.read, 1)
		.set(Notification.modified, now_datetime())
		.set(Notification.modified_by, user)
		.where(condition)
	).run()
	frappe.publish_realtime("crm_notification", user=user, after_commit=True)


def get_route_name(notification):
	# A task can be assigned with no lead or deal behind it. Naming the Lead
	# route for it sent the client to /leads/None, which vue-router refuses to
	# build, so the row never rendered.
	if not notification.reference_name:
		return None
	return "Deal" if notification.reference_doctype == "CRM Deal" else "Lead"


def get_hash(notification):
	_hash = ""
	if notification.type == "Mention" and notification.notification_type_doc:
		_hash = "#" + notification.notification_type_doc

	if notification.type == "WhatsApp":
		_hash = "#whatsapp"

	if notification.type == "Assignment" and notification.notification_type_doctype == "CRM Task":
		_hash = "#tasks"
		if "has been removed by" in notification.message:
			_hash = ""
	return _hash
