import json
import re
from html.parser import HTMLParser

import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.core.doctype.communication.communication import (
	has_permission as communication_has_permission,
)
from frappe.desk.form.load import add_comments, get_communication_data
from frappe.model.utils.mask import mask_version_data
from frappe.query_builder import JoinType
from frappe.translate import get_translated_doctypes
from frappe.utils import cint, get_datetime, sanitize_html

from crm.fcrm.doctype.crm_call_log.crm_call_log import parse_call_logs, redact_hidden_references

# Saves and emails per record on one page of the timeline; "load older" asks for
# the next page by asking for a longer one.
TIMELINE_PAGE_LENGTH = 100
MAX_TIMELINE_PAGE_LENGTH = 1000

# The records whose timeline shows emails, and the kinds of email it shows.
TIMELINE_DOCTYPES = ("CRM Deal", "CRM Lead")
TIMELINE_COMMUNICATION_TYPES = ("Communication", "Automated Message")

# An email's body is not part of the timeline: an Outlook thread is 20-100 KB of
# html, and a page of 100 of them was megabytes on every load and reload. Each
# row carries a plain-text snippet instead, and the body is fetched when the rep
# opens it (get_email_body). The newest few open by default, so theirs ride along.
SNIPPET_LENGTH = 200
# The snippet is read from the start of the html only. A mail whose <head> is
# longer than this (giant Outlook style sheets) gets no snippet, not a slow page.
SNIPPET_SOURCE_CHARS = 16384
EXPANDED_EMAILS = 2

# frappe's docinfo columns, less the body.
COMMUNICATION_FIELDS = f"""
	C.name, C.communication_type, C.communication_medium,
	C.communication_date, LEFT(C.content, {SNIPPET_SOURCE_CHARS}) AS content_head,
	C.sender, C.sender_full_name, C.cc, C.bcc,
	C.creation AS creation, C.subject, C.delivery_status,
	C._liked_by, C.reference_doctype, C.reference_name,
	C.read_by_recipient, C.recipients
"""


@frappe.whitelist()
def get_activities(name: str, page_length: int = TIMELINE_PAGE_LENGTH):
	"""The record's timeline: ``[activities, calls, notes, tasks, attachments, has_more]``.

	``has_more`` says the record has saves or emails older than this page.
	"""
	page_length = min(max(cint(page_length), 1), MAX_TIMELINE_PAGE_LENGTH)
	if frappe.db.exists("CRM Deal", name):
		result = get_deal_activities(name, page_length)
	elif frappe.db.exists("CRM Lead", name):
		result = get_lead_activities(name, page_length)
	else:
		frappe.throw(_("Document not found"), frappe.DoesNotExistError)
	inline_newest_email_bodies(result[0])
	return result


@frappe.whitelist()
def get_email_body(name: str) -> dict:
	"""One timeline email's body, sanitised, for the reader who can see it there.

	Visible means what the timeline means: the email is of a kind the timeline
	shows, it belongs to a deal or lead the reader may open (as its reference or
	through a timeline link), and frappe's own rule for the Communication -- its
	reference document is readable -- holds as well. A missing email and a hidden
	one get the same answer, so the endpoint cannot be used to probe for names.
	"""
	communication = None
	if isinstance(name, str) and name:
		communication = frappe.db.get_value(
			"Communication",
			name,
			["name", "communication_type", "reference_doctype", "reference_name", "content"],
			as_dict=True,
		)
	if not communication or not _can_read_email(communication):
		frappe.throw(_("Email not found"), frappe.DoesNotExistError)
	return {"name": communication.name, "content": sanitize_email_body(communication.content)}


def _can_read_email(communication) -> bool:
	if communication.communication_type not in TIMELINE_COMMUNICATION_TYPES:
		return False
	if not communication_has_permission(communication, "read"):
		return False

	parents = []
	if communication.reference_doctype in TIMELINE_DOCTYPES and communication.reference_name:
		parents.append((communication.reference_doctype, communication.reference_name))
	parents += frappe.db.get_all(
		"Communication Link",
		filters={"parent": communication.name, "link_doctype": ("in", TIMELINE_DOCTYPES)},
		fields=["link_doctype", "link_name"],
		as_list=True,
	)
	return any(frappe.has_permission(doctype, "read", parent) for doctype, parent in parents)


def sanitize_email_body(html: str | None) -> str:
	"""frappe's html sanitiser, always applied: plain text is escaped, not trusted."""
	return sanitize_html(html or "", always_sanitize=True)


def get_hidden_communications(communications: list, doctype: str, name: str) -> set[str]:
	"""Emails on this timeline whose content the reader may not see.

	The timeline lists an email referenced to this record, or linked to it from
	another. The first kind passed the record's own check; the second also has
	to pass frappe's rule for the Communication -- its reference is readable --
	which is what get_email_body asks. Checked once per referenced record.
	"""
	readable: dict[tuple[str, str], bool] = {}
	hidden = set()
	for communication in communications:
		reference = (communication.reference_doctype, communication.reference_name)
		if reference == (doctype, name) or not all(reference):
			continue
		if reference not in readable:
			readable[reference] = communication_has_permission(communication, "read")
		if not readable[reference]:
			hidden.add(communication.name)
	return hidden


def hide_email_content(activity: dict) -> None:
	"""Keep the row -- who wrote to whom, and when -- but none of what it says.

	CC and BCC go too: the row shows sender and To only, and a blind copy is
	exactly what a reader without access to the email should not learn."""
	data = activity["data"]
	data.pop("snippet", None)
	data.pop("content", None)
	data.pop("cc", None)
	data.pop("bcc", None)
	data["attachments"] = []
	data["hidden"] = True


def inline_newest_email_bodies(activities: list[dict], count: int = EXPANDED_EMAILS) -> None:
	"""Put the body on the newest ``count`` emails, which the timeline opens by default.

	It saves those a round trip and lets them paint at full height at once, which
	is what keeps "scroll to the newest" from landing short. One query for all.
	"""
	# an email the reader may not open never takes one of the places
	emails = [
		a for a in activities if a.get("activity_type") == "communication" and not a["data"].get("hidden")
	]
	newest = sorted(emails, key=lambda a: a["creation"], reverse=True)[:count]
	if not newest:
		return
	rows = {
		row.name: row
		for row in frappe.db.get_all(
			"Communication",
			filters={"name": ("in", [a["name"] for a in newest])},
			fields=["name", "reference_doctype", "reference_name", "content"],
		)
	}
	for activity in newest:
		row = rows.get(activity["name"])
		# the timeline's reader passed the record's check already; this is the
		# Communication's own, the same one get_email_body asks
		if row and communication_has_permission(row, "read"):
			activity["data"]["content"] = sanitize_email_body(row.content)


class _TextOnly(HTMLParser):
	"""The words of an html fragment, without what a mail client does not show."""

	HIDDEN = frozenset({"script", "style", "title", "template", "noscript"})
	# What may sit in a <head>. Any other tag starts the body, as it does in a
	# browser, so an unclosed <head> does not hide the whole mail.
	HEAD_CONTENT = frozenset({"head", "meta", "link", "base", *HIDDEN})
	# Tags that separate words. Inline ones (span, b, a, font) do not:
	# "Than<span>ks</span>" is one word.
	BLOCKS = frozenset(
		{
			"address", "article", "aside", "blockquote", "br", "center", "dd", "div", "dl",
			"dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
			"h5", "h6", "header", "hr", "img", "li", "main", "nav", "ol", "p", "pre", "section",
			"table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
		}
	)  # fmt: skip

	def __init__(self, limit: int):
		super().__init__(convert_charrefs=True)
		self.parts: list[str] = []
		self.visible = 0
		self.hidden = 0
		self.in_head = False
		self.limit = limit

	def handle_starttag(self, tag, attrs):
		if tag == "head":
			self.in_head = True
		elif tag == "body" or (self.in_head and tag not in self.HEAD_CONTENT):
			self.in_head = False
			self.hidden = 0
		if tag in self.HIDDEN:
			self.hidden += 1
		elif tag in self.BLOCKS:
			self.parts.append(" ")

	def handle_endtag(self, tag):
		if tag == "head":
			self.in_head = False
			self.hidden = 0
		elif tag in self.HIDDEN:
			self.hidden = max(self.hidden - 1, 0)
		elif tag in self.BLOCKS:
			self.parts.append(" ")

	def handle_data(self, data):
		if self.hidden or self.in_head:
			return
		self.parts.append(data)
		# Only what shows counts toward the cut-off: indentation, &nbsp; and
		# preheader padding are stripped later and used to end the read before
		# the first word. The 16 KB read bounds the work either way.
		self.visible += len(_NOT_VISIBLE.sub("", data))
		if self.visible > self.limit * 2:
			raise _Enough


class _Enough(Exception):
	pass


# Zero-width characters Outlook and marketing mail pad their preheaders with.
INVISIBLE = re.compile("[\u200b-\u200f\u034f\u2060\ufeff\u00ad]")
_NOT_VISIBLE = re.compile("[\\s\u200b-\u200f\u034f\u2060\ufeff\u00ad]")


def email_snippet(html: str | None, limit: int = SNIPPET_LENGTH) -> str:
	"""Plain text of the start of an email: tags gone, entities decoded, one line.

	Never html: the timeline draws it as text. At most ``limit`` characters.
	"""
	if not html:
		return ""
	parser = _TextOnly(limit)
	try:
		parser.feed(html)
	except _Enough:
		pass
	text = INVISIBLE.sub("", "".join(parser.parts))
	text = re.sub(r"\s+", " ", text).strip()
	if len(text) > limit:
		text = text[: limit - 1].rstrip() + "…"
	return text


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
	communications = get_communication_data(doctype, name, limit=page_length + 1, fields=COMMUNICATION_FIELDS)
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
	hidden_emails = get_hidden_communications(communications, "CRM Deal", name)
	for communication in communications:
		activity = {
			"activity_type": "communication",
			"name": communication.name,
			"communication_type": communication.communication_type,
			"communication_date": communication.communication_date or communication.creation,
			# a scheduled email belongs where it was sent, not where it was written
			"creation": max(
				communication.creation,
				get_datetime(communication.communication_date or communication.creation),
			),
			"data": {
				"subject": communication.subject,
				# the body is fetched on expand: get_email_body
				"snippet": email_snippet(communication.content_head),
				"sender_full_name": communication.sender_full_name,
				"sender": communication.sender,
				"recipients": communication.recipients,
				"sent_or_received": communication_directions.get(communication.name),
				"cc": communication.cc,
				"bcc": communication.bcc,
				"attachments": communication_attachments.get(communication.name, []),
				"read_by_recipient": communication.read_by_recipient,
				"delivery_status": communication.delivery_status,
				**get_schedule(communication),
			},
			"is_lead": False,
		}
		if communication.name in hidden_emails:
			hide_email_content(activity)
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
	hidden_emails = get_hidden_communications(communications, "CRM Lead", name)
	for communication in communications:
		activity = {
			"activity_type": "communication",
			"name": communication.name,
			"communication_type": communication.communication_type,
			"communication_date": communication.communication_date or communication.creation,
			# a scheduled email belongs where it was sent, not where it was written
			"creation": max(
				communication.creation,
				get_datetime(communication.communication_date or communication.creation),
			),
			"data": {
				"subject": communication.subject,
				# the body is fetched on expand: get_email_body
				"snippet": email_snippet(communication.content_head),
				"sender_full_name": communication.sender_full_name,
				"sender": communication.sender,
				"recipients": communication.recipients,
				"sent_or_received": communication_directions.get(communication.name),
				"cc": communication.cc,
				"bcc": communication.bcc,
				"attachments": communication_attachments.get(communication.name, []),
				"read_by_recipient": communication.read_by_recipient,
				"delivery_status": communication.delivery_status,
				**get_schedule(communication),
			},
			"is_lead": True,
		}
		if communication.name in hidden_emails:
			hide_email_content(activity)
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
	# The small copy frappe keeps for an image, when it has made one: the
	# Attachments tab draws a 44px square and should not fetch a phone photo for it.
	"thumbnail_url",
	"file_size",
	"is_private",
	"modified",
	"creation",
	"owner",
]


def get_schedule(communication) -> dict:
	"""When a still-scheduled email goes out, and whether this user may change that.

	docinfo fetches neither field, and only an email that is still waiting needs
	them, so the one lookup is spent on those alone. Whoever can read the record
	sees the email and its time; only the person who scheduled it is offered the
	actions, which is also all :mod:`crm.api.email` will allow.
	"""
	if communication.delivery_status != "Scheduled":
		return {}
	send_after, owner = frappe.db.get_value("Communication", communication.name, ["send_after", "owner"])
	return {"send_after": send_after, "scheduled_by_me": owner == frappe.session.user}


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
