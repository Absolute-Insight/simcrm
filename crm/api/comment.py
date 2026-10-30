from collections.abc import Iterable

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.desk.form.utils import add_comment as frappe_add_comment
from frappe.utils import get_fullname

from crm.api.access import _require_crm_user
from crm.fcrm.doctype.crm_notification.crm_notification import notify_user


def on_update(self, method):
	notify_mentions(self)


def notify_mentions(doc):
	"""
	Extract mentions from `content`, and notify.
	`content` must have `HTML` content.
	"""
	if doc.reference_doctype not in ["CRM Lead", "CRM Deal"]:
		return
	content = getattr(doc, "content", None)
	if not content:
		return
	mentions = extract_mentions(content)
	reference_doc = frappe.get_doc(doc.reference_doctype, doc.reference_name)
	for mention in mentions:
		owner = frappe.get_cached_value("User", doc.owner, "full_name")
		doctype = doc.reference_doctype
		if doctype.startswith("CRM "):
			doctype = doctype[4:].lower()
		name = (
			reference_doc.lead_name
			if doctype == "lead"
			else reference_doc.organization or reference_doc.lead_name
		)
		notification_text = f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{owner}</span>
                <span>{_("mentioned you in {0}").format(doctype)}</span>
                <span class="font-medium text-ink-gray-9">{name}</span>
            </div>
        """
		notify_user(
			{
				"owner": doc.owner,
				"assigned_to": mention.email,
				"notification_type": "Mention",
				"message": doc.content,
				"notification_text": notification_text,
				"reference_doctype": "Comment",
				"reference_docname": doc.name,
				"redirect_to_doctype": doc.reference_doctype,
				"redirect_to_docname": doc.reference_name,
			}
		)


def extract_mentions(html):
	if not html:
		return []
	soup = BeautifulSoup(html, "html.parser")
	mentions = []
	for d in soup.find_all("span", attrs={"data-type": "mention"}):
		mentions.append(frappe._dict(full_name=d.get("data-label"), email=d.get("data-id")))
	return mentions


@frappe.whitelist()
def add_comment(reference_doctype: str, reference_name: str, content: str, attachments: list | None = None):
	"""Add a comment to the given document

	:param reference_doctype: Reference Doctype
	:param reference_name: Reference Document Name
	:param content: Comment Content (HTML)
	:param attachments: List of File names or dicts with keys "fname" and "fcontent"
	:return: Comment Document
	"""
	comment = frappe_add_comment(
		reference_doctype,
		reference_name,
		content,
		comment_email=frappe.session.user,
		comment_by=get_fullname(frappe.session.user),
	)

	if attachments and comment.name:
		add_attachments(comment.name, attachments)

	return comment


@frappe.whitelist(methods=["POST"])
def delete_comment(name: str) -> None:
	"""Delete a comment the session user wrote.

	frappe's ``update_comment`` lets the author edit a comment, but nothing lets
	them delete it: Comment grants delete to System Manager and Website Manager, so
	``frappe.client.delete`` refused every rep. The conditions are ``update_comment``'s,
	plus a CRM role, because a website visitor's comment is owned by Guest, and only
	a written comment, because the Info and Assigned rows on the timeline are
	owned by whoever caused them.

	:param name: Comment name
	"""
	_require_crm_user()
	doc = frappe.get_doc("Comment", name)
	if doc.comment_type != "Comment" or frappe.session.user not in ("Administrator", doc.owner):
		frappe.throw(_("Comment can only be deleted by the owner"), frappe.PermissionError)
	if doc.reference_doctype and doc.reference_name:
		frappe.get_doc(doc.reference_doctype, doc.reference_name).check_permission("read")

	# A mention's notification links to the comment, which would refuse the delete
	frappe.db.delete(
		"CRM Notification", {"notification_type_doctype": "Comment", "notification_type_doc": doc.name}
	)
	doc.delete(ignore_permissions=True)


def add_attachments(name: str, attachments: Iterable[str | dict]) -> None:
	"""Add attachments to the given Comment

	:param name: Comment name
	:param attachments: File names or dicts with keys "fname" and "fcontent"
	"""
	# loop through attachments
	for a in attachments:
		if isinstance(a, str):
			frappe.has_permission("File", "read", doc=a, throw=True)
			attach = frappe.db.get_value("File", {"name": a}, ["file_url", "is_private"], as_dict=1)
			file_args = {
				"file_url": attach.file_url,
				"is_private": attach.is_private,
			}
		elif isinstance(a, dict) and "fcontent" in a and "fname" in a:
			# dict returned by frappe.attach_print()
			file_args = {
				"file_name": a["fname"],
				"content": a["fcontent"],
				"is_private": 1,
			}
		else:
			continue

		file_args.update(
			{
				"attached_to_doctype": "Comment",
				"attached_to_name": name,
				"folder": "Home/Attachments",
			}
		)

		_file = frappe.new_doc("File")
		_file.update(file_args)
		_file.save(ignore_permissions=True)
