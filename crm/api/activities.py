import json

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.desk.form.load import add_comments, get_communication_data
from frappe.model.utils.mask import mask_version_data
from frappe.query_builder import JoinType
from frappe.translate import get_translated_doctypes
from frappe.utils import cint

from crm.fcrm.doctype.crm_call_log.crm_call_log import parse_call_logs, redact_hidden_references

# Saves and emails per record on one page of the timeline; "load older" asks for
# the next page by asking for a longer one.
TIMELINE_PAGE_LENGTH = 100
MAX_TIMELINE_PAGE_LENGTH = 1000


@frappe.whitelist()
def get_activities(name: str, page_length: int = TIMELINE_PAGE_LENGTH):
	"""The record's timeline: ``[activities, calls, notes, tasks, attachments, has_more]``.

	``has_more`` says the record has saves or emails older than this page.
	"""
	page_length = min(max(cint(page_length), 1), MAX_TIMELINE_PAGE_LENGTH)
	if frappe.db.exists("CRM Deal", name):
		return get_deal_activities(name, page_length)
	elif frappe.db.exists("CRM Lead", name):
		return get_lead_activities(name, page_length)
	else:
		frappe.throw(_("Document not found"), frappe.DoesNotExistError)


def get_timeline_docinfo(doctype: str, name: str, page_length: int) -> frappe._dict:
	"""The comments, saves and emails the timeline draws, newest first.

	This used to be frappe's ``get_docinfo``, which is a desk form's first screen:
	the latest 10 versions and 21 emails. On a deal saved twelve times the
	Activity tab showed ten, with "created this deal" still at the bottom, and
	nothing said the rest were missing. It also left the whole docinfo in
	``frappe.response``, so every email body went over the wire twice.
	"""
	docinfo = frappe._dict()
	add_comments(frappe._dict(doctype=doctype, name=name), docinfo)

	# One past the page says whether there is another.
	versions = frappe.get_all(
		"Version",
		filters={"ref_doctype": doctype, "docname": str(name)},
		fields=["name", "owner", "creation", "data"],
		order_by="creation desc",
		limit=page_length + 1,
	)
	communications = get_communication_data(doctype, name, limit=page_length + 1)
	docinfo.has_more = len(versions) > page_length or len(communications) > page_length

	docinfo.versions = mask_version_data(versions[:page_length], doctype)
	communications = communications[:page_length]
	docinfo.communications = [c for c in communications if c.communication_type != "Automated Message"]
	docinfo.automated_messages = [c for c in communications if c.communication_type == "Automated Message"]
	return docinfo


def get_deal_activities(name: str, page_length: int = TIMELINE_PAGE_LENGTH):
	if not frappe.has_permission("CRM Deal", "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	docinfo = get_timeline_docinfo("CRM Deal", name, page_length)
	has_more = docinfo.has_more
	deal_meta = frappe.get_meta("CRM Deal")
	deal_fields = {
		field.fieldname: {"label": field.label, "options": field.options} for field in deal_meta.fields
	}
	avoid_fields = [
		"lead",
		"response_by",
		"sla_creation",
		"sla",
		"first_response_time",
		"first_responded_on",
	]

	doc = frappe.db.get_values("CRM Deal", name, ["creation", "owner", "lead"])[0]
	lead = doc[2]

	activities = []
	calls = []
	notes = []
	tasks = []
	attachments = []
	creation_text = _("created this deal")

	if lead:
		creation_text = _("converted the lead to this deal")
		# The lead's history joins the deal timeline only when the reader may see
		# the lead. Lead ownership never follows the deal: a deal reassigned after
		# conversion, or converted from a web-form or imported lead nobody owns,
		# points at a lead its owner cannot read, and get_lead_activities throws
		# PermissionError for it -- which used to take the deal's own emails,
		# comments, tasks and notes down with it. The deal was permission-checked
		# above; the lead is a bonus, not a gate.
		if frappe.has_permission("CRM Lead", "read", lead):
			activities, calls, notes, tasks, attachments, lead_has_more = get_lead_activities(
				lead, page_length
			)
			has_more = has_more or lead_has_more

	activities.append(
		{
			"activity_type": "creation",
			"creation": doc[0],
			"owner": doc[1],
			"data": creation_text,
			"is_lead": False,
		}
	)

	docinfo.versions.reverse()
	# once per call: uncached, it is two queries, and it ran for every change
	translated_doctypes = set(get_translated_doctypes()) if docinfo.versions else set()

	for version in docinfo.versions:
		version_data = json.loads(version.data)
		# Every entry, not just the first: one save that changes the status and
		# the owner together is two activities, and reading only changed[0] left
		# the owner change off the timeline altogether.
		for change in version_data.get("changed") or []:
			if not change:
				continue
			field = deal_fields.get(change[0], None)

			if not field or change[0] in avoid_fields or (not change[1] and not change[2]):
				continue

			field_label = field.get("label") or change[0]
			field_option = field.get("options") or None

			activity_type = "changed"
			data = {
				"field": change[0],
				"field_label": field_label,
				"old_value": change[1],
				"value": change[2],
			}

			if not change[1] and change[2]:
				activity_type = "added"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[2],
				}
			elif change[1] and not change[2]:
				activity_type = "removed"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[1],
				}

			if data.get("value") and field_option and field_option in translated_doctypes:
				data["value"] = _(data["value"])

				if data.get("old_value"):
					data["old_value"] = _(data["old_value"])

			activity = {
				"activity_type": activity_type,
				"creation": version.creation,
				"owner": version.owner,
				"data": data,
				"is_lead": False,
				"options": field_option,
			}
			activities.append(activity)

	comment_attachments = get_attachments_by_name("Comment", [c.name for c in docinfo.comments])
	for comment in docinfo.comments:
		activity = {
			"name": comment.name,
			"activity_type": "comment",
			"creation": comment.creation,
			"owner": comment.owner,
			"content": comment.content,
			"attachments": comment_attachments.get(comment.name, []),
			"is_lead": False,
		}
		activities.append(activity)

	communications = docinfo.communications + docinfo.automated_messages
	communication_attachments = get_attachments_by_name("Communication", [c.name for c in communications])
	communication_directions = get_communication_directions([c.name for c in communications])
	for communication in communications:
		activity = {
			"activity_type": "communication",
			"communication_type": communication.communication_type,
			"communication_date": communication.communication_date or communication.creation,
			"creation": communication.creation,
			"data": {
				"subject": communication.subject,
				"content": communication.content,
				"sender_full_name": communication.sender_full_name,
				"sender": communication.sender,
				"recipients": communication.recipients,
				"sent_or_received": communication_directions.get(communication.name),
				"cc": communication.cc,
				"bcc": communication.bcc,
				"attachments": communication_attachments.get(communication.name, []),
				"read_by_recipient": communication.read_by_recipient,
				"delivery_status": communication.delivery_status,
			},
			"is_lead": False,
		}
		activities.append(activity)

	for attachment_log in docinfo.attachment_logs:
		activity = {
			"name": attachment_log.name,
			"activity_type": "attachment_log",
			"creation": attachment_log.creation,
			"owner": attachment_log.owner,
			"data": parse_attachment_log(attachment_log.content, attachment_log.comment_type),
			"is_lead": False,
		}
		activities.append(activity)

	linked_calls = get_linked_calls(name, "CRM Deal")
	calls = calls + linked_calls.get("calls", [])
	notes = notes + get_linked_notes(name, "CRM Deal") + linked_calls.get("notes", [])
	tasks = tasks + get_linked_tasks(name, "CRM Deal") + linked_calls.get("tasks", [])
	attachments = attachments + get_attachments("CRM Deal", name)

	activities.sort(key=lambda x: x["creation"], reverse=True)
	activities = handle_multiple_versions(activities)

	return activities, calls, notes, tasks, attachments, has_more


def get_lead_activities(name: str, page_length: int = TIMELINE_PAGE_LENGTH):
	if not frappe.has_permission("CRM Lead", "read", name):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	docinfo = get_timeline_docinfo("CRM Lead", name, page_length)
	lead_meta = frappe.get_meta("CRM Lead")
	lead_fields = {
		field.fieldname: {"label": field.label, "options": field.options} for field in lead_meta.fields
	}
	avoid_fields = [
		"converted",
		"response_by",
		"sla_creation",
		"sla",
		"first_response_time",
		"first_responded_on",
	]

	doc = frappe.db.get_values("CRM Lead", name, ["creation", "owner"])[0]
	activities = [
		{
			"activity_type": "creation",
			"creation": doc[0],
			"owner": doc[1],
			"data": _("created this lead"),
			"is_lead": True,
		}
	]

	docinfo.versions.reverse()
	# once per call: uncached, it is two queries, and it ran for every change
	translated_doctypes = set(get_translated_doctypes()) if docinfo.versions else set()

	for version in docinfo.versions:
		version_data = json.loads(version.data)
		# Every entry, not just the first: one save that changes the status and
		# the owner together is two activities, and reading only changed[0] left
		# the owner change off the timeline altogether.
		for change in version_data.get("changed") or []:
			if not change:
				continue
			field = lead_fields.get(change[0], None)

			if not field or change[0] in avoid_fields or (not change[1] and not change[2]):
				continue

			field_label = field.get("label") or change[0]
			field_option = field.get("options") or None

			activity_type = "changed"
			data = {
				"field": change[0],
				"field_label": field_label,
				"old_value": change[1],
				"value": change[2],
			}

			if not change[1] and change[2]:
				activity_type = "added"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[2],
				}
			elif change[1] and not change[2]:
				activity_type = "removed"
				data = {
					"field": change[0],
					"field_label": field_label,
					"value": change[1],
				}

			if data.get("value") and field_option and field_option in translated_doctypes:
				data["value"] = _(data["value"])

				if data.get("old_value"):
					data["old_value"] = _(data["old_value"])

			activity = {
				"activity_type": activity_type,
				"creation": version.creation,
				"owner": version.owner,
				"data": data,
				"is_lead": True,
				"options": field_option,
			}
			activities.append(activity)

	comment_attachments = get_attachments_by_name("Comment", [c.name for c in docinfo.comments])
	for comment in docinfo.comments:
		activity = {
			"name": comment.name,
			"activity_type": "comment",
			"creation": comment.creation,
			"owner": comment.owner,
			"content": comment.content,
			"attachments": comment_attachments.get(comment.name, []),
			"is_lead": True,
		}
		activities.append(activity)

	communications = docinfo.communications + docinfo.automated_messages
	communication_attachments = get_attachments_by_name("Communication", [c.name for c in communications])
	communication_directions = get_communication_directions([c.name for c in communications])
	for communication in communications:
		activity = {
			"activity_type": "communication",
			"communication_type": communication.communication_type,
			"communication_date": communication.communication_date or communication.creation,
			"creation": communication.creation,
			"data": {
				"subject": communication.subject,
				"content": communication.content,
				"sender_full_name": communication.sender_full_name,
				"sender": communication.sender,
				"recipients": communication.recipients,
				"sent_or_received": communication_directions.get(communication.name),
				"cc": communication.cc,
				"bcc": communication.bcc,
				"attachments": communication_attachments.get(communication.name, []),
				"read_by_recipient": communication.read_by_recipient,
				"delivery_status": communication.delivery_status,
			},
			"is_lead": True,
		}
		activities.append(activity)

	for attachment_log in docinfo.attachment_logs:
		activity = {
			"name": attachment_log.name,
			"activity_type": "attachment_log",
			"creation": attachment_log.creation,
			"owner": attachment_log.owner,
			"data": parse_attachment_log(attachment_log.content, attachment_log.comment_type),
			"is_lead": True,
		}
		activities.append(activity)

	linked_calls = get_linked_calls(name, "CRM Lead")
	calls = linked_calls.get("calls", [])
	notes = get_linked_notes(name, "CRM Lead") + linked_calls.get("notes", [])
	tasks = get_linked_tasks(name, "CRM Lead") + linked_calls.get("tasks", [])
	attachments = get_attachments("CRM Lead", name)

	activities.sort(key=lambda x: x["creation"], reverse=True)
	activities = handle_multiple_versions(activities)

	return activities, calls, notes, tasks, attachments, docinfo.has_more


ATTACHMENT_FIELDS = [
	"name",
	"file_name",
	"file_type",
	"file_url",
	"file_size",
	"is_private",
	"modified",
	"creation",
	"owner",
]


def get_attachments(doctype: str, name: str):
	return (
		frappe.db.get_all(
			"File",
			filters={"attached_to_doctype": doctype, "attached_to_name": name},
			fields=ATTACHMENT_FIELDS,
		)
		or []
	)


def get_attachments_by_name(doctype: str, names: list[str]) -> dict[str, list]:
	"""Attachments for many records of one doctype in a single query, keyed by record name.

	Each list has the same rows, fields and order `get_attachments` returns for
	that record; a record with no files is simply absent.
	"""
	if not names:
		return {}

	grouped: dict[str, list] = {}
	for row in frappe.db.get_all(
		"File",
		filters={"attached_to_doctype": doctype, "attached_to_name": ("in", names)},
		fields=[*ATTACHMENT_FIELDS, "attached_to_name"],
		order_by="modified desc",
	):
		attached_to = row.pop("attached_to_name")
		grouped.setdefault(attached_to, []).append(row)
	return grouped


def get_communication_directions(names: list[str]) -> dict[str, str]:
	"""Whether each communication was Sent or Received, keyed by name, in one query.

	frappe's docinfo leaves ``sent_or_received`` out, and Reply needs it: mail
	the rep sent is answered to its recipients, not to its sender (the rep).
	"""
	if not names:
		return {}

	return dict(
		frappe.db.get_all(
			"Communication",
			filters={"name": ("in", names)},
			fields=["name", "sent_or_received"],
			as_list=True,
		)
	)


def handle_multiple_versions(versions: list):
	activities = []
	grouped_versions = []
	old_version = None
	for version in versions:
		is_version = version["activity_type"] in ["changed", "added", "removed"]
		if not is_version:
			activities.append(version)
		if not old_version:
			old_version = version
			if is_version:
				grouped_versions.append(version)
			continue
		if is_version and old_version.get("owner") and version["owner"] == old_version["owner"]:
			grouped_versions.append(version)
		else:
			if grouped_versions:
				activities.append(parse_grouped_versions(grouped_versions))
			grouped_versions = []
			if is_version:
				grouped_versions.append(version)
		old_version = version
		if version == versions[-1] and grouped_versions:
			activities.append(parse_grouped_versions(grouped_versions))

	return activities


def parse_grouped_versions(versions: list):
	version = versions[0]
	if len(versions) == 1:
		return version
	other_versions = versions[1:]
	version["other_versions"] = other_versions
	return version


def _record_filters(link_field: str, name: str, doctype_field: str, doctype: str | None) -> dict:
	"""Filter on the record's doctype as well as its name.

	The name alone finds the same rows -- names are unique per naming series --
	but every index on these tables leads with the doctype column, so without it
	each timeline load scanned the whole table, four times over.
	"""
	filters = {link_field: name}
	if doctype:
		filters[doctype_field] = doctype
	return filters


def get_linked_calls(name: str, doctype: str | None = None):
	calls = frappe.db.get_all(
		"CRM Call Log",
		filters=_record_filters("reference_docname", name, "reference_doctype", doctype),
		fields=[
			"name",
			"caller",
			"receiver",
			"from",
			"to",
			"duration",
			"start_time",
			"end_time",
			"status",
			"type",
			"recording_url",
			"creation",
			"note",
			"reference_doctype",
			"reference_docname",
		],
	)

	linked_calls = frappe.db.get_all(
		"Dynamic Link",
		filters={
			**_record_filters("link_name", name, "link_doctype", doctype),
			"parenttype": "CRM Call Log",
		},
		pluck="parent",
	)

	notes = []
	tasks = []

	if linked_calls:
		CallLog = frappe.qb.DocType("CRM Call Log")
		Link = frappe.qb.DocType("Dynamic Link")
		query = (
			frappe.qb.from_(CallLog)
			.select(
				CallLog.name,
				CallLog.caller,
				CallLog.receiver,
				CallLog["from"],
				CallLog.to,
				CallLog.duration,
				CallLog.start_time,
				CallLog.end_time,
				CallLog.status,
				CallLog.type,
				CallLog.recording_url,
				CallLog.creation,
				CallLog.note,
				CallLog.reference_doctype,
				CallLog.reference_docname,
				Link.link_doctype,
				Link.link_name,
			)
			.join(Link, JoinType.inner)
			.on(Link.parent == CallLog.name)
			.where(CallLog.name.isin(linked_calls))
		)
		_calls = query.run(as_dict=True)

		for call in _calls:
			if call.get("link_doctype") == "FCRM Note":
				notes.append(call.link_name)
			elif call.get("link_doctype") == "CRM Task":
				tasks.append(call.link_name)

		_calls = [call for call in _calls if call.get("link_doctype") not in ["FCRM Note", "CRM Task"]]
		# A call on this record may also reference or link another lead or deal the
		# viewer can't read; its row comes back without that record's name.
		redact_hidden_references(_calls)
		if _calls:
			calls = calls + _calls

	if notes:
		notes = frappe.db.get_all(
			"FCRM Note",
			filters={"name": ("in", notes)},
			fields=["name", "title", "content", "owner", "modified"],
		)

	if tasks:
		tasks = frappe.db.get_all(
			"CRM Task",
			filters={"name": ("in", tasks)},
			fields=[
				"name",
				"title",
				"description",
				"assigned_to",
				"due_date",
				"priority",
				"status",
				"modified",
			],
		)

	calls = parse_call_logs(calls) if calls else []

	return {"calls": calls, "notes": notes, "tasks": tasks}


def get_linked_notes(name: str, doctype: str | None = None):
	notes = frappe.db.get_all(
		"FCRM Note",
		filters=_record_filters("reference_docname", name, "reference_doctype", doctype),
		fields=["name", "title", "content", "owner", "modified", "creation"],
	)
	return notes or []


def get_linked_tasks(name: str, doctype: str | None = None):
	tasks = frappe.db.get_all(
		"CRM Task",
		filters=_record_filters("reference_docname", name, "reference_doctype", doctype),
		fields=[
			"name",
			"title",
			"description",
			"assigned_to",
			"due_date",
			"priority",
			"status",
			"modified",
			"creation",
		],
	)
	return tasks or []


def parse_attachment_log(html: str, type: str):
	soup = BeautifulSoup(html, "html.parser")
	a_tag = soup.find("a")
	type = "added" if type == "Attachment" else "removed"
	if not a_tag:
		return {
			"type": type,
			"file_name": html.replace("Removed ", ""),
			"file_url": "",
			"is_private": False,
		}

	is_private = False
	if "private/files" in a_tag["href"]:
		is_private = True

	return {
		"type": type,
		"file_name": a_tag.text,
		"file_url": a_tag["href"],
		"is_private": is_private,
	}
