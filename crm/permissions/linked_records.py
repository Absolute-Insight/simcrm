# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Row scoping for the records that hang off a lead or a deal.

FCRM Note, CRM Task and CRM Call Log grant Sales User full CRUD and carried no
scoping of their own, so the Notes, Tasks and Call Logs pages -- and
``frappe.client.get_list`` straight from the browser -- read every note, task
description, phone number and recording URL on the site, whatever the hierarchy
hid on the deal itself. A rep could also delete a manager's task.

A row is visible when the lead or deal it hangs off is visible to the user
under :mod:`crm.permissions.org_hierarchy`, or when the row is the user's own:
its author, the task's assignee, the call's caller or receiver. That second
clause is not merely a fallback for unlinked rows -- a task is assigned to a rep
on a deal only their manager owns, and a call is logged against the agent who
took it -- so it has to hold even when the referenced record does not.

Two link shapes count, because both are in use: ``reference_doctype`` /
``reference_docname``, which the CRM writes when a note or task is created on a
record, and the ``links`` child table, which the Twilio and Exotel handlers
write when they match an incoming number to a lead or deal.

CRM Enrichment Run hangs off a record the same way but belongs to no user: it
is what a crawl found for that lead or deal -- emails, phones, the raw
extraction -- so it follows the record alone, and a run on a doctype with no row
scoping of its own (an organization) stays as visible as that doctype.
frappe_whatsapp's WhatsApp Message follows its record alone too: it is the
record's conversation, and a message matched to no lead or deal is nobody's to
read but a manager who sees everything.

The document check reads the *stored* row, not the in-memory document: frappe
checks write on the mutated document, so a check against ``doc.reference_docname``
would let a rep re-point a hidden note at their own deal and read it.

The in-memory document is read for one thing only, and it is the opposite
question: where the row is being *put*. A new row, or one whose reference the
caller has changed, has to name a record they can read -- otherwise a rep files
a note, a task or a call onto a colleague's deal by typing its name.
"""

from __future__ import annotations

import frappe
from pypika import Criterion

from crm.permissions.org_hierarchy import _permission_query_conditions, sees_everything

#: Per doctype, the fields that name a user as the row's own.
OWN_FIELDS = {
	"FCRM Note": ("owner",),
	"CRM Task": ("owner", "assigned_to"),
	"CRM Call Log": ("owner", "caller", "receiver"),
	"CRM Enrichment Run": (),
	"WhatsApp Message": (),
}

#: Per doctype, the Dynamic Link field naming the referenced record.
REFERENCE_FIELD = {"CRM Enrichment Run": "reference_name", "WhatsApp Message": "reference_name"}

#: Doctypes whose rows on an unscoped (or no) reference are visible to anyone
#: holding the role permission, rather than only to the row's own users.
#: "Unscoped" means not in SCOPED_REFERENCES: if Organization or Contact ever
#: gains row scoping in org_hierarchy, add it there too, or its runs stay open.
OPEN_WHEN_UNSCOPED = ("CRM Enrichment Run",)

#: The referenced doctypes that carry row scoping of their own.
SCOPED_REFERENCES = ("CRM Lead", "CRM Deal")

#: The doctypes a row may only be filed onto when the user can read the record:
#: the two above, and the customer and the people there, which
#: :mod:`crm.permissions.customers` scopes.
FILED_ON = (*SCOPED_REFERENCES, "CRM Organization", "Contact")

#: What only looks at a row. Anything else may be carrying a changed reference.
READ_PTYPES = ("read", "select", "print", "email", "export", "report")


def _visible(user: str, reference: str):
	"""Sub-select of the ``reference`` rows this user may read."""
	Ref = frappe.qb.DocType(reference)
	query = frappe.qb.from_(Ref).select(Ref.name)
	conditions = _permission_query_conditions(user, reference)
	return query.where(conditions) if conditions else query


def _conditions(user: str, doctype: str):
	DT = frappe.qb.DocType(doctype)
	clauses = [DT[field] == user for field in OWN_FIELDS[doctype]]
	reference_name = DT[REFERENCE_FIELD.get(doctype, "reference_docname")]

	if doctype in OPEN_WHEN_UNSCOPED:
		# An organization's run carries its name and what enrichment found there.
		# Customer scoping is its own rule, not org_hierarchy's, so it is added here.
		from crm.permissions.customers import visible_organization_condition

		org_cond = visible_organization_condition(user)
		scoped = SCOPED_REFERENCES if org_cond is None else (*SCOPED_REFERENCES, "CRM Organization")
		clauses.append(DT.reference_doctype.isnull() | DT.reference_doctype.notin(scoped))
		if org_cond is not None:
			Org = frappe.qb.DocType("CRM Organization")
			clauses.append(
				(DT.reference_doctype == "CRM Organization")
				& reference_name.isin(frappe.qb.from_(Org).select(Org.name).where(org_cond))
			)

	for reference in SCOPED_REFERENCES:
		visible = _visible(user, reference)
		clauses.append((DT.reference_doctype == reference) & reference_name.isin(visible))

		if doctype == "CRM Call Log":
			Link = frappe.qb.DocType("Dynamic Link").as_("_call_link")
			clauses.append(
				DT.name.isin(
					frappe.qb.from_(Link)
					.select(Link.parent)
					.where(
						(Link.parenttype == doctype)
						& (Link.link_doctype == reference)
						& Link.link_name.isin(_visible(user, reference))
					)
				)
			)

	return Criterion.any(clauses)


def get_permission_query_conditions(doctype: str, user: str | None = None) -> str:
	user = user or frappe.session.user
	if sees_everything(user):
		return ""
	return _conditions(user, doctype).get_sql(with_namespace=True, quote_char="`", secondary_quote_char="'")


def has_permission(doc, ptype: str, user: str | None, doctype: str) -> bool:
	user = user or frappe.session.user
	if sees_everything(user):
		return True
	if ptype == "create" or not doc.name or doc.get("__islocal"):
		return _may_file_on(_references(doc, doctype), user)

	DT = frappe.qb.DocType(doctype)
	visible = bool(
		frappe.qb.from_(DT)
		.select(DT.name)
		.where(DT.name == doc.name)
		.where(_conditions(user, doctype))
		.limit(1)
		.run()
	)
	if not visible or ptype in READ_PTYPES:
		return visible
	# a write is judged on the document as the caller has changed it
	# (frappe.client.set_value updates, then saves), so this is where a row
	# being moved onto another record is caught
	moved_to = _references(doc, doctype)
	return not moved_to or _may_file_on(moved_to - _stored_references(doc.name, doctype), user)


def _references(doc, doctype: str) -> set[tuple[str, str]]:
	"""The scoped records ``doc`` names: its reference, and a call log's links.

	By their stored names. frappe checks permission *before* it validates links,
	and link validation then rewrites what the caller typed to the stored
	spelling -- which the database matches without regard to case, accents or
	trailing spaces. Compared as typed, ``crm deal`` named no scoped doctype
	here and was saved as ``CRM Deal`` a moment later.
	"""
	found = {(doc.get("reference_doctype"), doc.get(REFERENCE_FIELD.get(doctype, "reference_docname")))}
	if doctype == "CRM Call Log":
		found |= {(row.get("link_doctype"), row.get("link_name")) for row in doc.get("links") or []}
	return _stored_names(found)


def _stored_references(name, doctype: str) -> set[tuple[str, str]]:
	stored = frappe.db.get_value(
		doctype, name, ["reference_doctype", REFERENCE_FIELD.get(doctype, "reference_docname")]
	)
	found = {tuple(stored)} if stored else set()
	if doctype == "CRM Call Log":
		found |= {
			(row.link_doctype, row.link_name)
			for row in frappe.get_all(
				"Dynamic Link",
				filters={"parenttype": doctype, "parent": name},
				fields=["link_doctype", "link_name"],
			)
		}
	return _stored_names(found)


def _stored_names(references) -> set[tuple[str, str]]:
	"""``references`` as the database spells them, less what is not scoped.

	The lookup is the database's own comparison, the one link validation will
	make: lower-casing here would be a second opinion on what it treats as equal.
	A doctype or a record that does not exist is dropped, and left to link
	validation to refuse.
	"""
	canonical = set()
	for reference_doctype, name in references:
		if not reference_doctype or not name:
			continue
		if reference_doctype not in FILED_ON:
			# not typed exactly: ask how the database spells it
			reference_doctype = frappe.db.get_value("DocType", str(reference_doctype), "name")
		if reference_doctype not in FILED_ON:
			continue
		name = frappe.db.get_value(reference_doctype, str(name), "name")
		if name:
			canonical.add((reference_doctype, str(name)))
	return canonical


def _may_file_on(references: set[tuple[str, str]], user: str) -> bool:
	"""Whether ``user`` can read every record in ``references``.

	Read, as for a comment (``frappe.desk.form.utils.add_comment``).
	"""
	return all(
		frappe.has_permission(reference_doctype, "read", doc=name, user=user)
		for reference_doctype, name in references
	)


def validate_filing(doc, method=None) -> None:
	"""The same question as the permission hook, asked again at validate.

	By then frappe has validated the links and written the stored spelling back
	onto the document, so this sees exactly what is about to be saved. The hook
	refuses first and reads the same names; this is here so that the two cannot
	drift apart -- whatever the hook is one day talked past, the row still does
	not land. Server code that files on a rep's behalf is trusted, as it is by
	the hook, which ``ignore_permissions`` never reaches.
	"""
	user = frappe.session.user
	if doc.flags.ignore_permissions or sees_everything(user):
		return
	named = _references(doc, doc.doctype)
	before = None if doc.is_new() else doc.get_doc_before_save()
	if before:
		named -= _references(before, doc.doctype)
	if not _may_file_on(named, user):
		frappe.throw(
			frappe._("You cannot file this on a record you do not have access to."), frappe.PermissionError
		)


def get_note_permission_query_conditions(user=None):
	return get_permission_query_conditions("FCRM Note", user)


def get_task_permission_query_conditions(user=None):
	return get_permission_query_conditions("CRM Task", user)


def get_call_log_permission_query_conditions(user=None):
	return get_permission_query_conditions("CRM Call Log", user)


def has_note_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "FCRM Note")


def has_task_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "CRM Task")


def has_call_log_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "CRM Call Log")


def get_enrichment_run_permission_query_conditions(user=None):
	return get_permission_query_conditions("CRM Enrichment Run", user)


def has_enrichment_run_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "CRM Enrichment Run")


def get_whatsapp_message_permission_query_conditions(user=None):
	return get_permission_query_conditions("WhatsApp Message", user)


def has_whatsapp_message_permission(doc, ptype, user):
	return has_permission(doc, ptype, user, "WhatsApp Message")


#: Scoped doctypes another app owns, which may not be installed.
OPTIONAL_DOCTYPES = ("WhatsApp Message",)


def get_file_permission_query_conditions(user=None):
	"""A file is listed only to those who can see the record it is attached to.

	Frappe's own rule lists a private file to anyone with read on the doctype it is
	attached to, and every rep has read on CRM Deal, CRM Lead, CRM Organization,
	Contact and the rest: opening the file was scoped (frappe's File check follows
	the attached record), finding out it exists and what it is called -- a quote
	named after the customer and the amount -- was not.

	Every doctype this app scopes with a ``permission_query_conditions`` hook is
	covered, read from the hooks themselves so that one added later is covered on
	the day it is added. A file attached to anything else, or to nothing, is left
	to frappe's rule, as is one that names a doctype and no record. The uploader
	keeps their own: frappe's File check opens a file to its owner whatever became
	of the record, and a list that left it out would disagree with that.

	Each doctype's clause is the same for every File query a request makes, so it
	is built once per request and user. Never across requests: it is made of who
	is on whose team and what the access settings say, right now. Which doctypes
	have files at all is asked every time, in the transaction the list itself
	runs in, so a file cannot arrive between the question and the list.
	"""
	import crm.hooks

	user = user or frappe.session.user
	scoped = [doctype for doctype in crm.hooks.permission_query_conditions if doctype != "File"]
	built = _request_memo(user)
	clauses = []
	for doctype in _doctypes_with_files(scoped):
		if doctype not in built:
			built[doctype] = _file_clauses(doctype, user)
		clauses += built[doctype]
	if not clauses:
		return ""
	return f"(`tabFile`.`owner` = {frappe.db.escape(user)} or ({' and '.join(clauses)}))"


def _request_memo(user: str) -> dict:
	"""This request's clauses for ``user``, by doctype; a fresh dict outside one.

	A scheduler job or a test has no request and ``frappe.local`` outlives the
	settings there, so nothing is kept.
	"""
	request = _current_request()
	if request is None:
		return {}
	memo = getattr(frappe.local, "crm_file_clauses", None)
	if not memo or memo["request"] is not request:
		memo = frappe.local.crm_file_clauses = {"request": request, "by_user": {}}
	return memo["by_user"].setdefault(user, {})


def _current_request():
	return getattr(frappe.local, "request", None)


def _file_clauses(doctype: str, user: str) -> list[str]:
	import crm.hooks

	if doctype in OPTIONAL_DOCTYPES and not frappe.db.exists("DocType", doctype, cache=True):
		return []
	methods = crm.hooks.permission_query_conditions[doctype]
	clauses = []
	for method in [methods] if isinstance(methods, str) else methods:
		# nosemgrep: frappe-semgrep-rules.rules.security.frappe-codeinjection-eval -- dotted paths from crm.hooks, never caller input
		conditions = frappe.call(frappe.get_attr(method), user, doctype=doctype)
		if not conditions:
			continue
		table = f"`tab{doctype}`"
		clauses.append(
			f"(ifnull(`tabFile`.`attached_to_doctype`, '') != {frappe.db.escape(doctype)}"
			# NULL IN (...) is NULL, which would unlist the file from everyone
			" or ifnull(`tabFile`.`attached_to_name`, '') = ''"
			" or `tabFile`.`attached_to_name` in"
			f" (select {table}.`name` from {table} where {conditions}))"
		)
	return clauses


def _doctypes_with_files(doctypes: list[str]) -> list[str]:
	"""Those of ``doctypes`` that have a file attached at all, in the order given.

	Most scoped doctypes never carry an attachment -- a quota, a notification, a
	saved view -- and a clause for one costs its hook's lookups and a sub-select
	the database then has to plan, to hide nothing. One read of the
	(attached_to_doctype, attached_to_name) index frappe keeps on File says which.
	"""
	File = frappe.qb.DocType("File")
	present = set(
		frappe.qb.from_(File)
		.select(File.attached_to_doctype)
		.distinct()
		.where(File.attached_to_doctype.isin(doctypes))
		.run(pluck=True)
	)
	return [doctype for doctype in doctypes if doctype in present]
