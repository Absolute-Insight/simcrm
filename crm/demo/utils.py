import functools
import json

import frappe
from frappe.query_builder import DocType


def resolve_owners(demo_users):
	"""Return (session_user, owner_1, owner_2, owner_3) each falling back to session_user."""
	s = frappe.session.user
	if s in ("Administrator", "Guest"):
		s = demo_users[0] if demo_users else s
	owners = [demo_users[i] if i < len(demo_users) else s for i in range(3)]
	return (s, *owners)


def build_full_names(session_user):
	"""Return {email: full_name} mapping for all demo users plus session_user."""
	from crm.demo.users import DEMO_USERS

	names = {u["email"]: f"{u['first_name']} {u['last_name']}" for u in DEMO_USERS}
	names[session_user] = frappe.utils.get_fullname(session_user)
	return names


def seeds_demo_data(fn):
	"""Run ``fn`` with ``frappe.flags.in_demo_seed`` set, for the ERP hooks to read.

	Seeding inserts deals already Won. On a site with an ERP customer push
	switched on, each one queued its fake organization for creation as a
	customer in the client's real ERP, and Clear Demo Data cannot take that back.
	"""

	@functools.wraps(fn)
	def wrapper(*args, **kwargs):
		previous = frappe.flags.in_demo_seed
		frappe.flags.in_demo_seed = True
		try:
			return fn(*args, **kwargs)
		finally:
			frappe.flags.in_demo_seed = previous

	return wrapper


def delete_unless_linked(doctype, name):
	"""Delete a demo row unless a real record has come to link to it. True if deleted.

	A trial site's real records pick demo values up: an organization filed under
	the demo's "Mining", a lead handed to a demo rep. ``delete_doc(force=True)``
	skips frappe's link check, so clearing the demo deleted those rows from under
	the records, which then refused every save ("Could not find Industry"). Without
	force the check runs -- but after ``on_trash`` has done its clean-up, so the
	attempt runs in a savepoint and is undone when refused.
	"""
	messages = len(frappe.local.message_log)
	frappe.db.savepoint("demo_delete")
	try:
		frappe.delete_doc(doctype, name, ignore_permissions=True)
	except frappe.LinkExistsError:
		frappe.db.rollback(save_point="demo_delete")
		# the refusal is for us, not a message for whoever cleared the demo
		del frappe.local.message_log[messages:]
		return False
	frappe.db.release_savepoint("demo_delete")
	return True


def backdate(doctype, name, owner, ts, *, set_creation=True):
	"""Set owner, modified_by, modified (and optionally creation) without triggering hooks."""
	fields = {"owner": owner, "modified_by": owner, "modified": ts}
	if set_creation:
		fields["creation"] = ts
	frappe.db.set_value(doctype, name, fields, update_modified=False)


def fix_auto_records(doctype, docname, owner, ts):
	"""Backdate the Version and assignment Comment auto-created with owner='Administrator' on insert."""
	Version = DocType("Version")
	(
		frappe.qb.update(Version)
		.set(Version.owner, owner)
		.set(Version.modified_by, owner)
		.set(Version.creation, ts)
		.set(Version.modified, ts)
		.where(
			(Version.ref_doctype == doctype)
			& (Version.docname == docname)
			& (Version.owner == "Administrator")
		)
		.run()
	)
	Comment = DocType("Comment")
	(
		frappe.qb.update(Comment)
		.set(Comment.owner, owner)
		.set(Comment.modified_by, owner)
		.set(Comment.comment_email, owner)
		.set(Comment.creation, ts)
		.set(Comment.modified, ts)
		.where(
			(Comment.reference_doctype == doctype)
			& (Comment.reference_name == docname)
			& (Comment.owner == "Administrator")
		)
		.run()
	)


def insert_comment(reference_doctype, reference_name, owner, content, full_names, ts):
	"""Insert a Comment, backdate it, and return its name."""
	comment = frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Comment",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"content": content,
			"comment_email": owner,
			"comment_by": full_names.get(owner, owner),
		}
	).insert(ignore_permissions=True)
	backdate("Comment", comment.name, owner, ts)
	return comment.name


def insert_communication(reference_doctype, reference_name, data, full_names, ts):
	"""Insert an email Communication, backdate it, and return its name."""
	comm = frappe.get_doc(
		{
			"doctype": "Communication",
			"communication_type": "Communication",
			"communication_medium": "Email",
			"status": "Linked",
			"sent_or_received": data["sent_or_received"],
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"subject": data["subject"],
			"content": data["content"],
			"sender": data["sender"],
			"sender_full_name": full_names.get(data["sender"], data["sender"]),
			"recipients": data["recipients"],
			"communication_date": ts,
		}
	).insert(ignore_permissions=True)
	backdate("Communication", comm.name, data["owner"], ts)
	return comm.name


def insert_version(ref_doctype, docname, owner, changed, ts):
	"""Insert a Version record, backdate it, and return its name."""
	version = frappe.get_doc(
		{
			"doctype": "Version",
			"ref_doctype": ref_doctype,
			"docname": docname,
			"data": json.dumps({"changed": changed}),
		}
	).insert(ignore_permissions=True)
	backdate("Version", version.name, owner, ts)
	return version.name
