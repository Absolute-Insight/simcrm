# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _, generate_hash
from frappe.model.document import Document

from crm.integrations.api import get_contact_by_phone_number
from crm.utils import seconds_to_duration

#: Referenced doctypes with row scoping of their own. A call log is readable by its
#: caller and receiver even when the lead or deal it hangs off is not
#: (crm.permissions.linked_records), so it must never name one the viewer can't read.
SCOPED_REFERENCES = ("CRM Lead", "CRM Deal")


class CRMCallLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.core.doctype.dynamic_link.dynamic_link import DynamicLink
		from frappe.types import DF

		caller: DF.Link | None
		duration: DF.Duration | None
		end_time: DF.Datetime | None
		id: DF.Data | None
		links: DF.Table[DynamicLink]
		medium: DF.Data | None
		note: DF.Link | None
		receiver: DF.Link | None
		recording_url: DF.SmallText | None
		reference_docname: DF.DynamicLink | None
		reference_doctype: DF.Link | None
		start_time: DF.Datetime | None
		status: DF.Literal[
			"Initiated",
			"Ringing",
			"In Progress",
			"Completed",
			"Failed",
			"Busy",
			"No Answer",
			"Queued",
			"Canceled",
		]
		telephony_medium: DF.Literal["", "Manual", "Twilio", "Exotel"]
		to: DF.Data
		type: DF.Literal["Incoming", "Outgoing"]
	# end: auto-generated types

	def validate(self):
		self.keep_hidden_references()

	def keep_hidden_references(self):
		"""A viewer gets this call with its hidden lead or deal blanked out (see
		redact_hidden_references), so a save of what they were served must not
		write that blank back and detach the call from the record."""
		before = self.get_doc_before_save()
		if not before:
			return
		hidden = hidden_references(call_references(before))
		if not hidden:
			return
		if (
			(before.reference_doctype, before.reference_docname) in hidden
			and not self.reference_docname
			and self.reference_doctype == before.reference_doctype
		):
			self.reference_docname = before.reference_docname
		for link in before.get("links") or []:
			key = (link.link_doctype, link.link_name)
			if key in hidden and not self.has_link(*key):
				# Back where it was: the first lead link is the call's lead to
				# get_linked_lead and get_call_log, so appending would let a
				# rep's save change which lead readable users see.
				row = self.append("links", {"link_doctype": link.link_doctype, "link_name": link.link_name})
				self.links.remove(row)
				self.links.insert(min(link.idx - 1, len(self.links)), row)
		for idx, row in enumerate(self.links, start=1):
			row.idx = idx

	def on_change(self):
		"""frappe.client.save / set_value and the v1 resource PUT return the saved
		document without apply_fieldlevel_read_permissions, so the reference put
		back by validate must come out again before the response. on_change is
		the last post-save hook, after the version has been written from the
		restored document."""
		if self.flags.ignore_permissions or frappe.session.user == "Guest":
			return
		redact_hidden_references([self])

	def apply_fieldlevel_read_permissions(self):
		"""Every single-document read path frappe serves calls this before it hands
		the document over: /api/resource and /api/v2/document GET,
		frappe.client.get and frappe.desk.form.load.getdoc."""
		super().apply_fieldlevel_read_permissions()
		redact_hidden_references([self])

	def before_insert(self):
		if not self.id:
			self.id = generate_hash(length=12)
		if not self.telephony_medium:
			self.telephony_medium = "Manual"
		self.default_manual_participant()

	def default_manual_participant(self):
		"""A call logged by hand is the logger's own: the quick entry leaves caller
		and receiver blank, and the planner credits calls by exactly those fields.
		Telephony logs are written by the integration user and name the rep
		themselves, so they are left alone."""
		if self.telephony_medium != "Manual" or self.caller or self.receiver:
			return
		if frappe.session.user == "Guest":
			return
		if self.type == "Incoming":
			self.receiver = frappe.session.user
		else:
			self.caller = frappe.session.user

	@staticmethod
	def default_list_data():
		columns = [
			{
				"label": "Caller",
				"type": "Link",
				"key": "caller",
				"options": "User",
				"width": "9rem",
			},
			{
				"label": "Receiver",
				"type": "Link",
				"key": "receiver",
				"options": "User",
				"width": "9rem",
			},
			{
				"label": "Type",
				"type": "Select",
				"key": "type",
				"width": "9rem",
			},
			{
				"label": "Status",
				"type": "Select",
				"key": "status",
				"width": "9rem",
			},
			{
				"label": "Duration",
				"type": "Duration",
				"key": "duration",
				"width": "6rem",
			},
			{
				"label": "From (number)",
				"type": "Data",
				"key": "from",
				"width": "9rem",
			},
			{
				"label": "To (number)",
				"type": "Data",
				"key": "to",
				"width": "9rem",
			},
			{
				"label": "Created On",
				"type": "Datetime",
				"key": "creation",
				"width": "8rem",
			},
		]
		rows = [
			"name",
			"caller",
			"receiver",
			"type",
			"status",
			"duration",
			"from",
			"to",
			"note",
			"recording_url",
			"reference_doctype",
			"reference_docname",
			"creation",
		]
		return {"columns": columns, "rows": rows}

	def parse_list_data(calls):
		if not calls:
			return []
		redact_hidden_references(calls)
		return parse_call_logs(calls)

	def has_link(self, doctype, name):
		for link in self.links:
			if link.link_doctype == doctype and link.link_name == name:
				return True

	def link_with_reference_doc(self, reference_doctype, reference_name):
		if self.has_link(reference_doctype, reference_name):
			return

		self.append("links", {"link_doctype": reference_doctype, "link_name": reference_name})

	def as_dict(self, *args, **kwargs):
		d = super().as_dict(*args, **kwargs)
		if self.flags.has_hidden_reference:
			d["_has_hidden_reference"] = 1
		recording_url = d.get("recording_url")
		if not recording_url:
			return d

		# A recording uploaded to this site plays straight from its file path, where
		# frappe's own file permission applies; the proxy only fetches recordings
		# hosted elsewhere, and has no host to fetch a site path from. A path that
		# climbs out of /files/ is not a file, so it still goes through the proxy.
		if is_site_file_path(recording_url):
			d["recording_url_path"] = recording_url
		else:
			d["recording_url_path"] = (
				f"/api/method/crm.integrations.api.get_recording_url?call_log_name={d.get('name')}"
			)
		return d


def _candidates(doctype, name) -> list[tuple[str, str]]:
	"""The (doctype, name) pairs a name may stand for. A list row asked for
	``reference_docname`` without ``reference_doctype`` still carries the name, so a
	bare name is tried under every scoped doctype; one that exists nowhere hides
	nothing."""
	if not name:
		return []
	if doctype:
		return [(doctype, name)]
	return [(scoped, name) for scoped in SCOPED_REFERENCES]


def _is_hidden(hidden, doctype, name) -> bool:
	return any(pair in hidden for pair in _candidates(doctype, name))


def call_references(call) -> list[tuple[str, str]]:
	"""The (doctype, name) pairs a call log or call-log row points at, by reference
	and by link row. Works on a Document, on a dict, and on a timeline row, where
	the record's call query joins one link row flat into ``link_doctype`` /
	``link_name`` instead of nesting a ``links`` table."""
	pairs = _candidates(call.get("reference_doctype"), call.get("reference_docname"))
	for link in call.get("links") or []:
		pairs += _candidates(link.get("link_doctype"), link.get("link_name"))
	pairs += _candidates(call.get("link_doctype"), call.get("link_name"))
	return pairs


def hidden_references(pairs) -> set[tuple[str, str]]:
	"""Of these (doctype, name) pairs, the leads and deals the session user can't read.

	Read through frappe.get_list, so it is the same row scoping the Leads and Deals
	lists apply. A name that no longer exists hides nothing and is left alone."""
	existing, readable = existing_and_readable_references(pairs)
	return existing - readable


def existing_and_readable_references(pairs) -> tuple[set, set]:
	"""Of these (doctype, name) pairs, the leads and deals that exist, and those of
	them the session user can read: one query per doctype for each, however many
	pairs there are. :func:`hidden_references` is the difference."""
	by_doctype: dict[str, set] = {}
	for doctype, name in pairs:
		if doctype in SCOPED_REFERENCES and name:
			by_doctype.setdefault(doctype, set()).add(name)

	existing_pairs, readable_pairs = set(), set()
	for doctype, names in by_doctype.items():
		existing = set(frappe.get_all(doctype, filters={"name": ("in", list(names))}, pluck="name"))
		if not existing:
			continue
		readable = set()
		if frappe.has_permission(doctype, "read"):
			readable = set(
				frappe.get_list(
					doctype,
					filters={"name": ("in", list(existing))},
					pluck="name",
					limit=len(existing),
				)
			)
		existing_pairs.update((doctype, name) for name in existing)
		readable_pairs.update((doctype, name) for name in readable)
	return existing_pairs, readable_pairs


def redact_hidden_references(calls) -> None:
	"""Blank the reference and drop the link rows that name a lead or deal the session
	user can't read, in place, and mark each call that had one so the UI can say so
	rather than offer to create a lead over it. Takes Documents or dicts."""
	hidden = hidden_references(pair for call in calls for pair in call_references(call))
	if not hidden:
		return

	for call in calls:
		is_doc = isinstance(call, Document)
		redacted = False
		if _is_hidden(hidden, call.get("reference_doctype"), call.get("reference_docname")):
			_set(call, "reference_docname", None)
			redacted = True
		links = call.get("links")
		if links:
			kept = [
				link
				for link in links
				if not _is_hidden(hidden, link.get("link_doctype"), link.get("link_name"))
			]
			if len(kept) != len(links):
				_set(call, "links", kept)
				redacted = True
		if _is_hidden(hidden, call.get("link_doctype"), call.get("link_name")):
			_set(call, "link_name", None)
			redacted = True
		if redacted:
			if is_doc:
				call.flags.has_hidden_reference = True
			else:
				call["_has_hidden_reference"] = 1


def _set(call, key, value):
	if isinstance(call, Document):
		setattr(call, key, value)
	else:
		call[key] = value


def is_site_file_path(url: str) -> bool:
	# Browsers resolve "..", "%2e%2e" and backslashes as path segments.
	lowered = url.lower()
	return url.startswith(("/files/", "/private/files/")) and not any(
		token in lowered for token in ("..", "%2e", "\\")
	)


def parse_call_logs(calls):
	""":func:`parse_call_log` for a page of calls, resolving who each was with in a
	fixed number of queries however many calls there are."""
	parties = CallParties(calls)
	return [parse_call_log(call, parties) for call in calls]


def parse_call_log(call, parties=None):
	parties = parties or CallParties([call])
	call["show_recording"] = False
	call["_duration"] = seconds_to_duration(call.get("duration"))
	if call.get("type") == "Incoming":
		call["activity_type"] = "incoming_call"
		contact = parties.contact(call, call.get("from"))
		receiver = parties.user(call.get("receiver"))
		call["_caller"] = {
			"label": contact.get("full_name", "Unknown"),
			"image": contact.get("image"),
		}
		call["_receiver"] = {
			"label": receiver[0],
			"image": receiver[1],
		}
	elif call.get("type") == "Outgoing":
		call["activity_type"] = "outgoing_call"
		contact = parties.contact(call, call.get("to"))
		caller = parties.user(call.get("caller"))
		call["_caller"] = {
			"label": caller[0],
			"image": caller[1],
		}
		call["_receiver"] = {
			"label": contact.get("full_name", "Unknown"),
			"image": contact.get("image"),
		}

	return call


class CallParties:
	"""Who the calls in one batch were with, read once for the whole batch.

	parse_call_log used to resolve every row on its own -- the record's existence,
	its permission, its contact and the rep, each a query or more -- so a list page
	or timeline of a hundred calls ran several hundred. This reads each doctype
	once for every call in the batch, and looks each distinct unlinked number up
	once."""

	def __init__(self, calls):
		self.users = self._users(calls)
		self.records = self._records(calls)
		self.numbers = {}

	def user(self, name) -> tuple:
		"""(full_name, user_image) of a caller or receiver."""
		return self.users.get(name, (None, None)) if name else (None, None)

	def contact(self, call, phone_number) -> dict:
		"""The lead or deal the call points to, or the best match for the number when
		it points to neither. Two records can share a number, so once the call points
		to a record the number is never used to guess who it was."""
		doctype, name = call.get("reference_doctype"), call.get("reference_docname")
		if doctype not in SCOPED_REFERENCES or not name:
			# redact_hidden_references has already blanked a record the viewer can't
			# read; matching the number now would hand them its name after all.
			if call.get("_has_hidden_reference"):
				return {}
			# A call that points at nothing is named by its number, but only from the
			# records the viewer may read: the unrestricted lookup is for webhooks.
			if phone_number not in self.numbers:
				self.numbers[phone_number] = get_contact_by_phone_number(phone_number)
			return self.numbers[phone_number]

		# A record that is gone (a forced delete leaves the reference dangling) and
		# one the viewer can't read answer the same, so this does not tell the
		# caller whether the record exists.
		return self.records.get((doctype, name)) or {}

	@staticmethod
	def _users(calls) -> dict:
		names = {
			call.get("receiver") if call.get("type") == "Incoming" else call.get("caller") for call in calls
		} - {None, ""}
		if not names:
			return {}
		rows = frappe.get_all(
			"User", filters={"name": ("in", list(names))}, fields=["name", "full_name", "user_image"]
		)
		return {row.name: (row.full_name, row.user_image) for row in rows}

	@staticmethod
	def _records(calls) -> dict:
		"""{(doctype, name): {"full_name", "image"}} for every readable lead and deal
		the calls point to."""
		pairs = [(call.get("reference_doctype"), call.get("reference_docname")) for call in calls]
		_existing, readable = existing_and_readable_references(pairs)
		leads = [name for doctype, name in readable if doctype == "CRM Lead"]
		deals = [name for doctype, name in readable if doctype == "CRM Deal"]

		records = {}
		if leads:
			for lead in frappe.get_all(
				"CRM Lead", filters={"name": ("in", leads)}, fields=["name", "lead_name", "image"]
			):
				records[("CRM Lead", lead.name)] = {"full_name": lead.lead_name, "image": lead.image}
		if deals:
			records.update(_deal_contacts(deals))
		return records


def _deal_contacts(deals) -> dict:
	"""A deal is labelled by its primary contact, or by its lead or organisation
	name when it has none."""
	primary = {}
	for row in frappe.get_all(
		"CRM Contacts",
		filters={"parenttype": "CRM Deal", "parent": ("in", deals), "is_primary": 1},
		fields=["parent", "contact"],
		order_by="idx asc",
	):
		if row.contact:
			primary.setdefault(row.parent, row.contact)

	records = {}
	if primary:
		contacts = {
			row.name: {"full_name": row.full_name, "image": row.image}
			for row in frappe.get_all(
				"Contact",
				filters={"name": ("in", list(set(primary.values())))},
				fields=["name", "full_name", "image"],
			)
		}
		for deal, contact in primary.items():
			if contact in contacts:
				records[("CRM Deal", deal)] = contacts[contact]

	without_contact = [deal for deal in deals if deal not in primary]
	if without_contact:
		for deal in frappe.get_all(
			"CRM Deal",
			filters={"name": ("in", without_contact)},
			fields=["name", "lead_name", "organization", "organization_name"],
		):
			label = deal.lead_name or deal.organization or deal.organization_name
			if label:
				records[("CRM Deal", deal.name)] = {"full_name": label}
	return records


@frappe.whitelist()
def get_call_log(name: str):
	call_doc = frappe.get_cached_doc("CRM Call Log", name)
	call_doc.check_permission("read")
	call = call_doc.as_dict()
	# Only what the viewer may read is left to resolve into _lead/_deal below.
	redact_hidden_references([call])

	call = parse_call_log(call)

	notes = []
	tasks = []

	def readable(doctype, docname):
		# Linked notes and tasks are omitted, not fatal, when the caller can't read them.
		return frappe.has_permission(doctype, "read", doc=docname)

	if call.get("note") and readable("FCRM Note", call.get("note")):
		note = frappe.get_cached_doc("FCRM Note", call.get("note")).as_dict()
		notes.append(note)

	if call.get("reference_doctype") and call.get("reference_docname"):
		if call.get("reference_doctype") == "CRM Lead":
			call["_lead"] = call.get("reference_docname")
		elif call.get("reference_doctype") == "CRM Deal":
			call["_deal"] = call.get("reference_docname")

	if call.get("links"):
		for link in call.get("links"):
			if link.get("link_doctype") == "CRM Task":
				if readable("CRM Task", link.get("link_name")):
					task = frappe.get_cached_doc("CRM Task", link.get("link_name")).as_dict()
					tasks.append(task)
			elif link.get("link_doctype") == "FCRM Note":
				if readable("FCRM Note", link.get("link_name")):
					note = frappe.get_cached_doc("FCRM Note", link.get("link_name")).as_dict()
					notes.append(note)
			elif link.get("link_doctype") == "CRM Lead":
				# The reference is the record the call was logged against; a link
				# added later must not displace it.
				call.setdefault("_lead", link.get("link_name"))
			elif link.get("link_doctype") == "CRM Deal":
				call.setdefault("_deal", link.get("link_name"))

	# A note or task made from this call by someone who could see the record
	# points at it too; blank that the same way, without hiding the note or task.
	redact_hidden_references(notes + tasks)
	call["_tasks"] = tasks
	call["_notes"] = notes
	return call


@frappe.whitelist()
def create_lead_from_call_log(call_log: str | dict, lead_details: str | dict | None = None):
	call_log_data = frappe.parse_json(call_log or {})

	if isinstance(call_log_data, str):
		call_log_name = call_log_data
	elif isinstance(call_log_data, dict):
		call_log_name = call_log_data.get("name")
	else:
		call_log_name = None

	if not call_log_name:
		frappe.throw(_("A valid call log is required."), frappe.ValidationError)

	# Lock the call log row before reading it, so a second click on a slow server waits
	# for the first request to commit and then sees the lead it linked, instead of both
	# reading an unlinked call and creating a lead each.
	frappe.db.get_value("CRM Call Log", call_log_name, "modified", for_update=True)

	call_doc = frappe.get_doc("CRM Call Log", call_log_name)

	if not call_doc.has_permission("write"):
		frappe.throw(_("You are not permitted to update this call log."), frappe.PermissionError)

	# A readable lead the call already has is the answer, whatever else it links.
	references = call_references(call_doc)
	hidden = hidden_references(references)
	existing_lead = get_linked_lead(call_doc)
	if existing_lead and ("CRM Lead", existing_lead) not in hidden:
		return existing_lead

	# A call filed under a lead or deal the caller can't read is already some record's:
	# creating a lead would duplicate it, and returning it would name it. The message
	# deliberately does not say which record.
	if hidden:
		frappe.throw(
			_("This call is already linked to a record you don't have access to."),
			frappe.PermissionError,
		)

	if any(doctype == "CRM Deal" for doctype, _name in references):
		frappe.throw(_("This call is already linked to a deal."), frappe.ValidationError)

	if not frappe.has_permission("CRM Lead", "create"):
		frappe.throw(_("You are not permitted to create leads."), frappe.PermissionError)

	lead_details_data = frappe.parse_json(lead_details or {})
	if lead_details_data and not isinstance(lead_details_data, dict):
		frappe.throw(_("Invalid lead details supplied."), frappe.ValidationError)

	lead = frappe.new_doc("CRM Lead")
	meta = frappe.get_meta("CRM Lead")
	valid_fieldnames = [df.fieldname for df in meta.fields]

	sanitized_details = {
		key: value for key, value in (lead_details_data or {}).items() if key in valid_fieldnames
	}

	if "lead_owner" in valid_fieldnames and not sanitized_details.get("lead_owner"):
		sanitized_details["lead_owner"] = frappe.session.user

	if "mobile_no" in valid_fieldnames and not sanitized_details.get("mobile_no"):
		# The customer's end of the call, read the way parse_call_log reads it: on
		# an outgoing call ``from`` is the rep's own line.
		customer_number = call_doc.get("to") if call_doc.type == "Outgoing" else call_doc.get("from")
		sanitized_details["mobile_no"] = customer_number or ""

	if "first_name" in valid_fieldnames and not sanitized_details.get("first_name"):
		reference_label = sanitized_details.get("mobile_no") or call_doc.name
		sanitized_details["first_name"] = _("Lead from call {0}").format(reference_label)

	lead.update(sanitized_details)
	lead.insert()

	call_doc.link_with_reference_doc("CRM Lead", lead.name)
	call_doc.save()

	return lead.name


def get_linked_lead(call_doc):
	"""The lead this call is already attached to, by reference or by link row, or None."""
	if call_doc.get("reference_doctype") == "CRM Lead" and call_doc.get("reference_docname"):
		return call_doc.reference_docname
	for link in call_doc.get("links") or []:
		if link.link_doctype == "CRM Lead" and link.link_name:
			return link.link_name
	return None


def on_doctype_update():
	"""Indexes for the per-record activity feed and for the planner's per-rep
	call matching, which reads by caller or receiver over a week of start_time."""
	frappe.db.add_index("CRM Call Log", ["reference_doctype", "reference_docname"])
	frappe.db.add_index("CRM Call Log", ["caller", "start_time"])
	frappe.db.add_index("CRM Call Log", ["receiver", "start_time"])
