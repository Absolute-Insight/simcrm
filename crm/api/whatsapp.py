import json
import re

import frappe
from frappe import _
from frappe.permissions import add_permission, update_permission_property
from frappe.utils import get_fullname

from crm.api.doc import assigned_users
from crm.fcrm.doctype.crm_notification.crm_notification import notify_user
from crm.integrations.api import lookup_contact_lead_or_deal_from_number
from crm.integrations.whatsapp.lines import get_line_user, get_sending_account, require_sending_account
from crm.utils import canonical_whatsapp_number, is_same_whatsapp_number

ALLOWED_WHATSAPP_ROLES = ["System Manager", "Sales Manager", "Sales User"]


def validate_access(reference_doctype=None, reference_name=None, permtype="read"):
	if not any(role in ALLOWED_WHATSAPP_ROLES for role in frappe.get_roles()):
		frappe.throw(_("Only sales users can access WhatsApp features."), frappe.PermissionError)

	if reference_doctype and reference_name:
		if not frappe.db.exists(reference_doctype, reference_name):
			frappe.throw(
				_("Reference document {0} {1} does not exist.").format(reference_doctype, reference_name),
				frappe.DoesNotExistError,
			)
		reference_doc = frappe.get_doc(reference_doctype, reference_name)
		if not reference_doc.has_permission(permtype):
			frappe.throw(
				_("Not permitted to access reference document {0} {1}.").format(
					reference_doctype, reference_name
				),
				frappe.PermissionError,
			)
		return reference_doc

	return None


def _record_numbers(reference_doc) -> list[str]:
	"""Every number the record itself names: its own mobile_no and phone, and on
	a deal those of its contacts. The record's own mobile_no comes first, because
	that is the one the composer sends and so the one a blank ``to`` means."""
	numbers = [reference_doc.get("mobile_no"), reference_doc.get("phone")]
	for row in reference_doc.get("contacts") or []:
		numbers.extend((row.get("mobile_no"), row.get("phone")))
	return [number for number in dict.fromkeys(numbers) if number]


def _digits(number: str) -> str:
	return re.sub(r"\D", "", number or "")


def _is_same_number(number: str, other: str) -> bool:
	"""Digit for digit, or as the same number in two spellings: the composer sends
	what the record holds, and a contact row may hold the +27 form of an 082."""
	if _digits(number) == _digits(other):
		return True
	canonical = canonical_whatsapp_number(other)
	return bool(canonical) and is_same_whatsapp_number(number, canonical)


def _meta_number(number: str, from_meta: bool = False) -> str:
	"""A record's number the way Meta needs it. A stored 082 number, passed on as
	it is, would be refused or dialled in another country.

	phonenumbers' tables lag the network, so a number Meta itself sent us, or one
	written with its country code, is taken at its word if it is the right length
	to be real. A local spelling cannot be: there is no country to read it in.
	"""
	canonical = canonical_whatsapp_number(number)
	if canonical:
		return canonical
	if (from_meta or number.strip().startswith("+")) and 8 <= len(_digits(number)) <= 15:
		return _digits(number)
	frappe.throw(
		_("{0} is not a valid phone number. Add the country code to the record.").format(number),
		frappe.ValidationError,
	)


def resolve_destination(reference_doc, to: str | None = None) -> str:
	"""The number a message about ``reference_doc`` may go to.

	The composer only ever sends the record's own ``mobile_no``, but the server
	took whatever ``to`` it was given: a rep with read on any lead could send
	business-account messages, approved templates included, to any number and
	have them filed on that lead's thread. The destination now comes from the
	record: blank means its primary number, and anything else has to be one of
	the numbers the record carries, compared digit-for-digit so that a differently
	formatted spelling of the same number is still accepted.
	"""
	numbers = _record_numbers(reference_doc)
	if not numbers:
		frappe.throw(
			_("{0} {1} has no phone number to message.").format(reference_doc.doctype, reference_doc.name),
			frappe.ValidationError,
		)
	if not to:
		return numbers[0]
	match = next((number for number in numbers if _digits(to) and _is_same_number(number, to)), None)
	if not match:
		frappe.throw(
			_("{0} is not a phone number of {1} {2}.").format(to, reference_doc.doctype, reference_doc.name),
			frappe.ValidationError,
		)
	return match


def validate(doc, method):
	# An outgoing message was sent from a record's thread and stays filed there.
	# Matching its number instead re-filed it -- on every status save, too --
	# onto whichever lead or deal the lookup found first, so a message sent from
	# one deal of a contact who is primary on two turned up on the other one.
	# An incoming one likewise: a status or media save must not move it.
	if doc.reference_doctype and doc.reference_name:
		return
	phone_number = doc.get("from") if doc.type == "Incoming" else doc.get("to")
	if phone_number:
		try:
			prefer_user = get_line_user(doc.get("whatsapp_account"))
			name, doctype = lookup_contact_lead_or_deal_from_number(phone_number, prefer_user=prefer_user)
			if doctype and name is not None:
				doc.reference_doctype = doctype
				doc.reference_name = name
		except Exception:
			frappe.log_error(frappe.get_traceback(), "CRM WhatsApp: failed to resolve contact from number")


def on_update(doc, method):
	# Addressed to the record's own room rather than the whole site. This is a
	# "reload this thread" ping and only clients looking at that lead or deal
	# can act on it; unscoped, it told every logged-in session which records
	# were receiving WhatsApp messages and woke all of them to do nothing.
	frappe.publish_realtime(
		"whatsapp_message",
		{
			"reference_doctype": doc.reference_doctype,
			"reference_name": doc.reference_name,
		},
		doctype=doc.reference_doctype,
		docname=doc.reference_name,
	)

	notify_agent(doc)


def get_record_title(doctype: str, name: str) -> str:
	"""The name people know a lead or deal by, as mention notifications show it."""
	if doctype == "CRM Lead":
		title = frappe.db.get_value(doctype, name, "lead_name")
	elif doctype == "CRM Deal":
		deal = frappe.db.get_value(doctype, name, ["organization", "lead_name"], as_dict=True)
		title = deal and (deal.organization or deal.lead_name)
	else:
		title = None
	return title or name


def notify_agent(doc):
	if doc.type == "Incoming":
		if not doc.reference_doctype or not doc.reference_name:
			return
		doctype = doc.reference_doctype
		if doctype and doctype.startswith("CRM "):
			doctype = doctype[4:].lower()
		safe_reference_title = frappe.utils.escape_html(
			get_record_title(doc.reference_doctype, doc.reference_name)
		)
		notification_text = f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{_("You")}</span>
                <span>{_("received a whatsapp message in {0}").format(doctype)}</span>
                <span class="font-medium text-ink-gray-9">{safe_reference_title}</span>
            </div>
        """
		# The rep whose number it arrived on is told even when the record is
		# another rep's. Row scoping still holds: they get neither its title nor
		# a link to a page that would refuse them.
		unnamed_text = f"""
            <div class="mb-2 leading-5 text-ink-gray-5">
                <span class="font-medium text-ink-gray-9">{_("You")}</span>
                <span>{_("received a whatsapp message on your number")}</span>
            </div>
        """
		for user in recipients_of(doc):
			readable = frappe.has_permission(doc.reference_doctype, "read", doc=doc.reference_name, user=user)
			notify_user(
				{
					"owner": doc.owner,
					"assigned_to": user,
					"notification_type": "WhatsApp",
					"message": doc.message,
					"notification_text": notification_text if readable else unnamed_text,
					"reference_doctype": "WhatsApp Message",
					"reference_docname": doc.name,
					"redirect_to_doctype": doc.reference_doctype if readable else None,
					"redirect_to_docname": doc.reference_name if readable else None,
				}
			)


def recipients_of(doc) -> list[str]:
	"""Who hears about an incoming message: the record's assignees and owner, and
	the rep whose number it arrived on, who may be none of those."""
	owner_field = {"CRM Lead": "lead_owner", "CRM Deal": "deal_owner"}.get(doc.reference_doctype)
	users = set(assigned_users(doc.reference_doctype, doc.reference_name))
	if owner_field:
		users.add(frappe.db.get_value(doc.reference_doctype, doc.reference_name, owner_field))
	users.add(get_line_user(doc.get("whatsapp_account")))
	return sorted(user for user in users if user and user != "Guest")


@frappe.whitelist()
def is_whatsapp_enabled():
	"""Whether the site has WhatsApp at all: one active number turns it on for
	everyone, because a rep with no number of their own may still read a thread.
	Whether this user can send is ``can_send_whatsapp``."""
	if not frappe.db.exists("DocType", "WhatsApp Account"):
		return False
	return bool(frappe.db.exists("WhatsApp Account", {"status": "Active"}))


@frappe.whitelist()
def can_send_whatsapp():
	return bool(get_sending_account())


@frappe.whitelist()
def is_whatsapp_installed():
	if not frappe.db.exists("DocType", "WhatsApp Settings"):
		return False
	return True


@frappe.whitelist()
def get_whatsapp_messages(reference_doctype: str, reference_name: str):
	reference_doc = validate_access(reference_doctype, reference_name)
	# twilio integration app is not compatible with crm app
	# crm has its own twilio integration in built
	if "twilio_integration" in frappe.get_installed_apps():
		return []
	if not frappe.db.exists("DocType", "WhatsApp Message"):
		return []
	messages = []

	if reference_doctype == "CRM Deal":
		lead = reference_doc.get("lead")
		# Same rule as crm.api.activities.get_deal_activities: the lead's thread is
		# included when the reader may see the lead, and skipped -- not fatal --
		# when they may not. The deal itself was permission-checked above.
		if lead and frappe.has_permission("CRM Lead", "read", lead):
			messages = frappe.get_all(
				"WhatsApp Message",
				filters={
					"reference_doctype": "CRM Lead",
					"reference_name": lead,
				},
				fields=[
					"name",
					"owner",
					"type",
					"to",
					"from",
					"content_type",
					"message_type",
					"attach",
					"template",
					"use_template",
					"message_id",
					"is_reply",
					"reply_to_message_id",
					"creation",
					"message",
					"status",
					"reference_doctype",
					"reference_name",
					"template_parameters",
					"template_header_parameters",
				],
			)

	messages += frappe.get_all(
		"WhatsApp Message",
		filters={
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		},
		fields=[
			"name",
			"owner",
			"type",
			"to",
			"from",
			"content_type",
			"message_type",
			"attach",
			"template",
			"use_template",
			"message_id",
			"is_reply",
			"reply_to_message_id",
			"creation",
			"message",
			"status",
			"reference_doctype",
			"reference_name",
			"template_parameters",
			"template_header_parameters",
		],
	)

	# Filter messages to get only Template messages
	template_messages = [message for message in messages if message["message_type"] == "Template"]

	# Each template once per thread, not once per message that uses it. The
	# parameters are filled into copies of its text, never into the shared doc,
	# or the second message on a template would read the first one's values.
	templates = {}
	for name in {message["template"] for message in template_messages}:
		if frappe.db.exists("WhatsApp Templates", name):
			templates[name] = frappe.get_doc("WhatsApp Templates", name)

	# Iterate through template messages
	for template_message in template_messages:
		# Find the template that this message is using
		template = templates.get(template_message["template"])

		if template:
			body, header = template.template, template.header
			template_message["template_name"] = template.template_name
			if template_message["template_parameters"]:
				parameters = json.loads(template_message["template_parameters"])
				body = parse_template_parameters(body, parameters)

			template_message["template"] = body
			if template_message["template_header_parameters"]:
				header_parameters = json.loads(template_message["template_header_parameters"])
				header = parse_template_parameters(header, header_parameters)
			template_message["header"] = header
			template_message["footer"] = template.footer

	# Filter messages to get only reaction messages
	reaction_messages = [message for message in messages if message["content_type"] == "reaction"]
	reaction_messages.reverse()

	# Iterate through reaction messages
	for reaction_message in reaction_messages:
		# Find the message that this reaction is reacting to
		reacted_message = next(
			(m for m in messages if m["message_id"] == reaction_message["reply_to_message_id"]),
			None,
		)

		# If the reacted message is found, add the reaction to it
		if reacted_message:
			reacted_message["reaction"] = reaction_message["message"]

	# A thread is about one record (two, with a deal's lead): load each once,
	# rather than the whole document again for every message and every reply.
	names_by_record = {}

	def from_name_of(message):
		record = (message["reference_doctype"], message["reference_name"])
		if record not in names_by_record:
			names_by_record[record] = get_from_name(message)
		return names_by_record[record]

	for message in messages:
		message["from_name"] = from_name_of(message) if message["from"] else sender_name(message)
	# Filter messages to get only replies
	reply_messages = [message for message in messages if message["is_reply"]]

	# Iterate through reply messages
	for reply_message in reply_messages:
		# Find the message that this message is replying to
		replied_message = next(
			(m for m in messages if m["message_id"] == reply_message["reply_to_message_id"]),
			None,
		)

		# If the replied message is found, add the reply details to the reply message
		if replied_message:
			from_name = (
				from_name_of(reply_message) if replied_message["from"] else sender_name(replied_message)
			)
			message = replied_message["message"]
			if replied_message["message_type"] == "Template":
				message = replied_message["template"]
			reply_message["reply_message"] = message
			reply_message["header"] = replied_message.get("header") or ""
			reply_message["footer"] = replied_message.get("footer") or ""
			reply_message["reply_to"] = replied_message["name"]
			reply_message["reply_to_type"] = replied_message["type"]
			reply_message["reply_to_from"] = from_name

	return [message for message in messages if message["content_type"] != "reaction"]


@frappe.whitelist()
def create_whatsapp_message(
	reference_doctype: str,
	reference_name: str,
	message: str,
	to: str | None = None,
	attach: str | None = None,
	reply_to: str | None = None,
	content_type: str = "text",
):
	# sending on a record's behalf is a write to its thread, not a read of it
	reference_doc = validate_access(reference_doctype, reference_name, permtype="write")
	if not ((message or "").strip() or attach):
		frappe.throw(_("Type a message or attach a file."), frappe.ValidationError)
	to = _meta_number(resolve_destination(reference_doc, to))
	account = require_sending_account()
	doc = frappe.new_doc("WhatsApp Message")

	if reply_to:
		if not frappe.db.exists("WhatsApp Message", reply_to):
			frappe.throw(_("Referenced WhatsApp message does not exist."), frappe.DoesNotExistError)
		reply_doc = frappe.get_doc("WhatsApp Message", reply_to)
		if not reply_doc.has_permission("read"):
			frappe.throw(
				_("Not permitted to access the referenced WhatsApp message."), frappe.PermissionError
			)
		validate_access(reply_doc.reference_doctype, reply_doc.reference_name)
		doc.update(
			{
				"is_reply": True,
				"reply_to_message_id": reply_doc.message_id,
			}
		)

	doc.update(
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"message": message or attach,
			"to": to,
			"attach": attach,
			"content_type": content_type,
			"type": "Outgoing",
			"whatsapp_account": account,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def send_whatsapp_template(reference_doctype: str, reference_name: str, template: str, to: str | None = None):
	reference_doc = validate_access(reference_doctype, reference_name, permtype="write")
	to = _meta_number(resolve_destination(reference_doc, to))
	account = require_sending_account()
	doc = frappe.new_doc("WhatsApp Message")
	doc.update(
		{
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"message_type": "Template",
			"message": "Template message",
			"content_type": "text",
			"use_template": True,
			"template": template,
			"to": to,
			"type": "Outgoing",
			"whatsapp_account": account,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def react_on_whatsapp_message(emoji: str, reply_to_name: str):
	validate_access()
	if not frappe.db.exists("WhatsApp Message", reply_to_name):
		frappe.throw(_("Referenced WhatsApp message does not exist."), frappe.DoesNotExistError)
	reply_to_doc = frappe.get_doc("WhatsApp Message", reply_to_name)

	if not reply_to_doc.has_permission("read"):
		frappe.throw(_("Not permitted to access the referenced WhatsApp message."), frappe.PermissionError)

	# a reaction is a message sent to the customer, so it is a write to the
	# record's thread like any other send, not a read of it
	validate_access(reply_to_doc.reference_doctype, reply_to_doc.reference_name, permtype="write")

	from_meta = reply_to_doc.type == "Incoming"
	to = _meta_number((from_meta and reply_to_doc.get("from")) or reply_to_doc.to, from_meta=from_meta)
	account = require_sending_account()
	doc = frappe.new_doc("WhatsApp Message")
	doc.update(
		{
			"reference_doctype": reply_to_doc.reference_doctype,
			"reference_name": reply_to_doc.reference_name,
			"message": emoji,
			"to": to,
			"reply_to_message_id": reply_to_doc.message_id,
			"content_type": "reaction",
			"type": "Outgoing",
			"whatsapp_account": account,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def parse_template_parameters(string, parameters):
	for i, parameter in enumerate(parameters, start=1):
		placeholder = "{{" + str(i) + "}}"
		string = string.replace(placeholder, str(parameter))

	return string


def sender_name(message):
	"""The rep who sent an outgoing message: a record has several, and the reader
	of a thread is not always one of them. get_fullname caches per request."""
	return get_fullname(message.get("owner")) if message.get("owner") else _("You")


def get_from_name(message):
	doc = frappe.get_doc(message["reference_doctype"], message["reference_name"])
	from_name = ""
	if message["reference_doctype"] == "CRM Deal":
		if doc.get("contacts"):
			for c in doc.get("contacts"):
				if c.is_primary:
					from_name = c.full_name or c.mobile_no
					break
		else:
			from_name = doc.get("lead_name")
	else:
		from_name = " ".join(name for name in [doc.get("first_name"), doc.get("last_name")] if name)
	return from_name


#: What each CRM role is given on frappe_whatsapp's doctypes: what the CRM's
#: pages read through the document API, and the settings pane for a manager.
#: Every send goes through the endpoints above, which ask for write on the record
#: and take the destination from it, and insert with ignore_permissions. Create,
#: write and delete here were a REST door around both: a POST to
#: /api/resource/WhatsApp Message sends to any number, and a list read every
#: rep's conversations. WhatsApp Message rows are scoped to the record they are
#: on by crm.permissions.linked_records.
WHATSAPP_PERMISSIONS = {
	"WhatsApp Message": {"Sales Manager": ("read",), "Sales User": ("read",)},
	"WhatsApp Templates": {"Sales Manager": ("read",), "Sales User": ("read",)},
	"WhatsApp Settings": {"Sales Manager": ("read", "write")},
}


def after_app_install(app: str):
	if app == "frappe_whatsapp":
		add_roles()


def add_roles():
	if "frappe_whatsapp" not in frappe.get_installed_apps():
		return

	for doctype, roles in WHATSAPP_PERMISSIONS.items():
		for role, ptypes in roles.items():
			if frappe.db.exists("Custom DocPerm", {"parent": doctype, "role": role}):
				continue
			add_permission(doctype, role, 0, ptypes[0])
			for ptype in ptypes[1:]:
				update_permission_property(doctype, role, 0, ptype, 1)
