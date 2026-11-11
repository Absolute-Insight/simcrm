import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime


@frappe.whitelist(methods=["POST"])
def cancel_scheduled_email(name: str):
	"""Delete a scheduled email before it goes out and return it as a draft to edit."""
	communication, queues = get_scheduled_email(name)

	file_urls = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "Communication", "attached_to_name": name},
		pluck="file_url",
	)
	attachments = (
		frappe.get_all(
			"File",
			filters={
				"attached_to_doctype": communication.reference_doctype,
				"attached_to_name": communication.reference_name,
				"file_url": ["in", file_urls],
			},
			fields=["name", "file_name", "file_url"],
		)
		if file_urls
		else []
	)

	for queue in queues:
		frappe.delete_doc("Email Queue", queue, ignore_permissions=True, ignore_on_trash=True)
	communication.delete(ignore_permissions=True)

	return {
		"subject": communication.subject,
		"content": communication.content,
		"sender": communication.sender,
		"recipients": communication.recipients,
		"cc": communication.cc,
		"bcc": communication.bcc,
		"attachments": attachments,
	}


# POST only (ours, not upstream's): frappe checks the CSRF token on unsafe
# methods alone, and the send commits on its own, so a link opened by the person
# who scheduled the email was enough to send it early.
@frappe.whitelist(methods=["POST"])
def send_scheduled_email_now(name: str):
	"""Send a scheduled email right away instead of at its scheduled time."""
	communication, queues = get_scheduled_email(name)

	# frappe clears queue rows a month after they were made, whatever their
	# status. An email scheduled further out than that is still "Scheduled" here
	# with nothing left to send, and this used to answer "Email sent".
	if not queues:
		frappe.throw(_("This email is no longer queued. Delete it and send it again."))

	# frappe drops unsubscribed recipients when the email is queued and never
	# looks again. Someone who left the conversation after it was scheduled is
	# still on the queue row, and sending now is a person choosing to mail them.
	if unsubscribed := unsubscribed_recipients(communication, queues):
		frappe.throw(
			_("{0} has unsubscribed since this email was scheduled. Edit it to remove them.").format(
				", ".join(unsubscribed)
			)
		)

	communication.db_set(
		{"send_after": None, "delivery_status": "Sending", "communication_date": now_datetime()}
	)
	for queue in queues:
		frappe.db.set_value("Email Queue", queue, "send_after", None)
		# Same as sending with `now`; if it can't go out here, the queue retries it
		frappe.get_doc("Email Queue", queue).send()


def stamp_send_time(doc, method=None):
	"""Date a scheduled email by when it went out, not when it was written."""
	if doc.delivery_status != "Sent" or not doc.send_after:
		return
	# Already stamped: the send happens after send_after, so the date has moved past it
	if get_datetime(doc.communication_date) >= get_datetime(doc.send_after):
		return
	frappe.db.set_value(
		"Communication", doc.name, "communication_date", now_datetime(), update_modified=False
	)


def unsubscribed_recipients(communication, queues: list[str]) -> list[str]:
	"""Recipients on the queued email who have unsubscribed, from everything or from this record."""
	from email.utils import parseaddr

	recipients = frappe.get_all(
		"Email Queue Recipient", filters={"parent": ("in", queues)}, pluck="recipient"
	)
	emails = sorted({parseaddr(recipient)[1] or recipient for recipient in recipients if recipient})
	if not emails:
		return []

	EmailUnsubscribe = frappe.qb.DocType("Email Unsubscribe")
	return (
		frappe.qb.from_(EmailUnsubscribe)
		.select(EmailUnsubscribe.email)
		.distinct()
		.where(EmailUnsubscribe.email.isin(emails))
		.where(
			(EmailUnsubscribe.global_unsubscribe == 1)
			| (
				(EmailUnsubscribe.reference_doctype == communication.reference_doctype)
				& (EmailUnsubscribe.reference_name == communication.reference_name)
			)
		)
		.run(pluck=True)
	)


def get_scheduled_email(name: str):
	"""Return the Communication and its queued emails, if it's still waiting to be sent."""
	communication = frappe.get_doc("Communication", name)

	if communication.owner != frappe.session.user:
		frappe.throw(_("You can only change emails you scheduled"), frappe.PermissionError)

	if communication.delivery_status != "Scheduled":
		frappe.throw(_("This email is no longer scheduled"))

	# Lock the queue rows so the scheduler can't pick them up while we change them
	EmailQueue = frappe.qb.DocType("Email Queue")
	queues = (
		frappe.qb.from_(EmailQueue)
		.select(EmailQueue.name, EmailQueue.status)
		.where(EmailQueue.communication == name)
		.for_update()
		.run(as_dict=True)
	)
	if any(q.status != "Not Sent" for q in queues):
		frappe.throw(_("This email is already being sent"))

	return communication, [q.name for q in queues]
