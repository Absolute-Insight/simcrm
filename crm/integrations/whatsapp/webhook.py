"""Meta's webhook, verified.

frappe_whatsapp's ``webhook`` is a guest endpoint whose POST trusts its body, so
anyone who knows the URL could file messages on any record. It is not modified;
``override_whitelisted_methods`` sends the route here first. The hook covers only
/api/method and /api/v2/method, and two other doors stay open: frappe's
``upload_file`` looks up its ``method`` argument with no override, and any module
that imports the function reaches it under another dotted name. So there is a
second lock inside upstream's own code path: ``post()`` begins by inserting a
"Webhook" WhatsApp Notification Log row, and ``refuse_unverified_log`` vetoes that
insert unless this module has verified the request.

The App Secret belongs to the Meta app, not the number, but it is stored per line
and every change in a payload must verify against a line that owns it. A secret
that leaks for one line then cannot forge messages for another.

This module also absorbs what upstream assumes away. It reads only
``entry[0].changes[0]`` and ``statuses[0]``, raises on a status for a message it
never stored, raises on message types it has no field for, and stores a retried
delivery twice. An exception here is a non-200, which Meta retries for days. Each
change therefore reaches upstream on its own, reduced to what it can handle.

Media never reaches upstream. Its download has no timeout, runs in the web worker,
loses the message on a Meta error and saves the customer's file as public, which
any Desk user can list and anyone can fetch. ``store_media`` does the same job in
a background job, private from the first byte.
"""

import hashlib
import hmac
import json
import mimetypes
import re
from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils.password import get_decrypted_password
from frappe.utils.synchronization import filelock
from werkzeug.wrappers import Response

from crm.integrations.api import lookup_contact_for_number, lookup_contact_lead_or_deal_from_number
from crm.integrations.whatsapp.lines import LINE, get_line_user
from crm.utils import canonical_whatsapp_number

SIGNATURE_HEADER = "X-Hub-Signature-256"
SIGNATURE_PREFIX = "sha256="

LEAD_SOURCE = "WhatsApp"

#: The types upstream can store as they arrive. Anything else becomes a text note,
#: so that the rep learns a message came in rather than the webhook failing.
SUPPORTED_TYPES = {"text", "reaction", "interactive", "order", "button"}

MEDIA_TYPES = {"image", "audio", "video", "document"}
#: (connect, read) per request. The job's own timeout bounds the whole download.
MEDIA_TIMEOUT = (5, 30)
MEDIA_JOB_TIMEOUT = 300
DEFAULT_MAX_MEDIA_BYTES = 25 * 1024 * 1024


def _deny() -> Response:
	# Deliberately no reason and no log row: this path is reachable by anyone,
	# and writing to the database on it would hand them a way to fill it.
	return Response(status=403)


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])  # nosemgrep: guest-whitelisted-method
def webhook():
	if "frappe_whatsapp" not in frappe.get_installed_apps():
		return Response(status=404)

	from frappe_whatsapp.utils import webhook as upstream

	if frappe.request.method == "GET":
		# A JSON list here would become a filter on the secret column: upstream
		# looks the token up by value, so ["like", "a%"] extracts it letter by letter.
		if not isinstance(frappe.form_dict.get("hub.verify_token"), str):
			return _deny()
		return upstream.webhook()

	raw = frappe.request.get_data()
	payload = _parse(raw)
	if payload is None or not _is_signed(raw, payload):
		return _deny()

	frappe.flags.whatsapp_webhook_verified = True
	_deliver(upstream, payload)
	return Response(status=200)


@frappe.whitelist(allow_guest=True)  # nosemgrep: guest-whitelisted-method
def flows_not_in_use():
	"""frappe_whatsapp's WhatsApp Flows endpoint is a second unauthenticated
	route, which writes an Error Log row per request. Flows are not used here."""
	return Response(status=404)


def refuse_unverified_log(doc, method=None):
	"""The second lock, see the module docstring."""
	if doc.template == "Webhook" and not frappe.flags.whatsapp_webhook_verified:
		frappe.throw(_("Not permitted"), frappe.PermissionError)


def _parse(raw: bytes) -> dict | None:
	try:
		payload = json.loads(raw)
	except (ValueError, RecursionError):
		return None
	return payload if isinstance(payload, dict) else None


def _changes(payload: dict) -> list[tuple[str | None, dict]]:
	"""Every (WABA id, change) in the payload. Hostile shapes yield nothing."""
	found = []
	entries = payload.get("entry")
	for entry in entries if isinstance(entries, list) else []:
		if not isinstance(entry, dict):
			continue
		changes = entry.get("changes")
		for change in changes if isinstance(changes, list) else []:
			if isinstance(change, dict) and isinstance(change.get("value"), dict):
				found.append((entry.get("id"), change))
	return found


def _phone_id(change: dict) -> str | None:
	metadata = change["value"].get("metadata")
	return metadata.get("phone_number_id") if isinstance(metadata, dict) else None


def _is_signed(raw: bytes, payload: dict) -> bool:
	header = frappe.get_request_header(SIGNATURE_HEADER) or ""
	if not header.startswith(SIGNATURE_PREFIX):
		return False
	changes = _changes(payload)
	if not changes:
		return False

	for waba, change in changes:
		if not isinstance(waba, str | None) or not isinstance(_phone_id(change), str | None):
			return False
	phone_ids = {_phone_id(change) for _waba, change in changes} - {None}
	waba_ids = {waba for waba, change in changes if not _phone_id(change)} - {None}

	# One query however many ids a forged body names.
	accounts = frappe.get_all(
		"WhatsApp Account",
		or_filters={
			"phone_id": ("in", list(phone_ids) or [""]),
			"business_id": ("in", list(waba_ids) or [""]),
		},
		fields=["name", "phone_id", "business_id"],
	)
	by_phone = {account.phone_id: account.name for account in accounts}
	by_waba: dict[str, list[str]] = {}
	for account in accounts:
		by_waba.setdefault(account.business_id, []).append(account.name)

	digests: dict[str, bool] = {}

	def verifies(account: str) -> bool:
		if account not in digests:
			digests[account] = _verifies(raw, header, account)
		return digests[account]

	for waba, change in changes:
		phone_id = _phone_id(change)
		owners = [by_phone[phone_id]] if phone_id in by_phone else [] if phone_id else by_waba.get(waba, [])
		if not any(verifies(account) for account in owners):
			return False
	return True


def _verifies(raw: bytes, header: str, account: str) -> bool:
	if not frappe.db.exists(LINE, account):
		return False
	secret = get_decrypted_password(LINE, account, "app_secret", raise_exception=False)
	if not secret:
		return False
	expected = SIGNATURE_PREFIX + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
	return hmac.compare_digest(expected.encode(), header.encode())


def _deliver(upstream, payload: dict):
	for waba, change in _changes(payload):
		for single in _reduce(change):
			frappe.local.form_dict = frappe._dict(
				object=payload.get("object"), entry=[{"id": waba, "changes": [single]}]
			)
			upstream.post()


def _reduce(change: dict) -> list[dict]:
	"""``change`` as the calls upstream can make of it."""
	value = change["value"]
	if change.get("field") == "message_template_status_update":
		return [change]
	if change.get("field") != "messages":
		return []

	reduced = []
	messages = _new_messages(value.get("messages"))
	if messages:
		_provision_senders(messages, value)
		for message in (row for row in messages if row["type"] in MEDIA_TYPES):
			_queue_media(message, value)
		rest = [row for row in messages if row["type"] not in MEDIA_TYPES]
		if rest:
			reduced.append({**change, "value": {**value, "messages": rest}})

	statuses = value.get("statuses")
	statuses = [row for row in statuses if isinstance(row, dict)] if isinstance(statuses, list) else []
	known = _stored_ids([row.get("id") for row in statuses])
	reduced.extend(
		{**change, "value": {**value, "statuses": [row], "messages": []}}
		for row in statuses
		if row.get("id") in known
	)
	return reduced


def _stored_ids(ids: list) -> set:
	ids = [value for value in ids if value and isinstance(value, str)]
	if not ids:
		return set()
	return set(frappe.get_all("WhatsApp Message", filters={"message_id": ("in", ids)}, pluck="message_id"))


def _new_messages(messages) -> list[dict]:
	"""Not yet stored, and in a shape upstream can store. Meta redelivers
	anything it believes failed and the table has no unique key to stop it."""
	if not isinstance(messages, list):
		return []
	messages = [row for row in messages if isinstance(row, dict) and row.get("id") and row.get("from")]
	stored = _stored_ids([row["id"] for row in messages])
	return [_storable(row) for row in messages if row["id"] not in stored]


def _storable(message: dict) -> dict:
	kind = message.get("type")
	unhandled_interactive = (
		kind == "interactive" and message.get("interactive", {}).get("type") not in _INTERACTIVE_TYPES
	)
	if kind in MEDIA_TYPES or (kind in SUPPORTED_TYPES and not unhandled_interactive):
		return message
	return {
		"id": message["id"],
		"from": message["from"],
		"type": "text",
		"text": {"body": _describe(message)},
	}


#: nfm_reply is a WhatsApp Flow's answer, and Flows are not in use.
_INTERACTIVE_TYPES = ("button_reply", "list_reply")


def _describe(message: dict) -> str:
	kind = message.get("type")
	if kind == "location":
		location = message.get("location") or {}
		place = location.get("name") or location.get("address")
		point = f"{location.get('latitude')},{location.get('longitude')}"
		return _("Shared a location: {0}").format(f"{place} ({point})" if place else point)
	if kind == "contacts":
		people = message.get("contacts") or []
		names = [
			(person.get("name") or {}).get("formatted_name") for person in people if isinstance(person, dict)
		]
		return _("Shared a contact: {0}").format(", ".join(name for name in names if name) or "?")
	return _("Sent a {0} message, which cannot be shown here.").format(kind or "new kind of")


def _profiles(value: dict) -> dict:
	contacts = value.get("contacts")
	return {
		contact.get("wa_id"): (contact.get("profile") or {}).get("name")
		for contact in (contacts if isinstance(contacts, list) else [])
		if isinstance(contact, dict)
	}


def _provision_senders(messages: list[dict], value: dict):
	phone_id = _phone_id({"value": value})
	account = frappe.db.get_value("WhatsApp Account", {"phone_id": phone_id}, "name")
	rep = get_line_user(account)
	profiles = _profiles(value)
	for number in {message["from"] for message in messages}:
		ensure_record_for_sender(number, account, rep, profiles.get(number))


def _queue_media(message: dict, value: dict):
	account = frappe.db.get_value("WhatsApp Account", {"phone_id": _phone_id({"value": value})}, "name")
	frappe.enqueue(
		"crm.integrations.whatsapp.webhook.store_media",
		queue="default",
		timeout=MEDIA_JOB_TIMEOUT,
		job_id=f"whatsapp_media_{message['id']}",
		deduplicate=True,
		enqueue_after_commit=True,
		account=account,
		message=message,
		profile_name=_profiles(value).get(message["from"]),
	)


def max_media_bytes() -> int:
	return frappe.conf.get("max_file_size") or DEFAULT_MAX_MEDIA_BYTES


def store_media(account: str, message: dict, profile_name: str | None = None):
	"""Fetch an inbound file and file it, or say in the thread why it could not be.

	A failure here must not cost the rep the knowledge that the customer sent
	something, so anything at all becomes a note in the thread.
	"""
	frappe.set_user("Administrator")  # nosemgrep: frappe-setuser
	if _stored_ids([message["id"]]):
		return
	caption = (message.get(message["type"]) or {}).get("caption") or ""
	frappe.db.savepoint("whatsapp_media")
	try:
		content, extension = _download(account, message)
		doc = _insert_incoming(account, message, profile_name, message["type"], caption)
		file = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"{frappe.generate_hash(length=10)}.{extension}",
				"attached_to_doctype": "WhatsApp Message",
				"attached_to_name": doc.name,
				"attached_to_field": "attach",
				"content": content,
				"is_private": 1,
			}
		).insert(ignore_permissions=True)
		doc.db_set("attach", file.file_url)
	except Exception:
		frappe.db.rollback(save_point="whatsapp_media")
		frappe.log_error(title="CRM WhatsApp: inbound media not stored")
		note = _("Sent a {0} that could not be downloaded. Open WhatsApp on your phone to see it.").format(
			message["type"]
		)
		_insert_incoming(account, message, profile_name, "text", f"{note} {caption}".strip())


def _insert_incoming(account, message, profile_name, content_type, text):
	context = message.get("context") or {}
	is_reply = bool(context) and "forwarded" not in context
	return frappe.get_doc(
		{
			"doctype": "WhatsApp Message",
			"type": "Incoming",
			"from": message["from"],
			"message": text,
			"message_id": message["id"],
			"reply_to_message_id": context.get("id") if is_reply else None,
			"is_reply": is_reply,
			"content_type": content_type,
			"profile_name": profile_name,
			"whatsapp_account": account,
		}
	).insert(ignore_permissions=True)


def _download(account: str, message: dict) -> tuple[bytes, str]:
	doc = frappe.get_doc("WhatsApp Account", account)
	headers = {"Authorization": f"Bearer {doc.get_password('token')}"}
	media_id = quote(str(message[message["type"]]["id"]), safe="")
	info = requests.get(f"{doc.url}/{doc.version}/{media_id}/", headers=headers, timeout=MEDIA_TIMEOUT)
	info.raise_for_status()
	details = info.json()

	limit = max_media_bytes()
	content = bytearray()
	with requests.get(details["url"], headers=headers, timeout=MEDIA_TIMEOUT, stream=True) as response:
		response.raise_for_status()
		for chunk in response.iter_content(chunk_size=1024 * 1024):
			content += chunk
			if len(content) > limit:
				raise ValueError(f"media is over the {limit} byte limit")
	return bytes(content), _extension(details.get("mime_type"))


def _extension(mime_type: str | None) -> str:
	"""audio/ogg; codecs=opus is ogg, and a long vnd.* subtype is what the mime
	table says it is. Upstream used everything after the slash as the extension."""
	mime = (mime_type or "").split(";")[0].strip().lower()
	subtype = mime.rpartition("/")[2]
	if re.fullmatch(r"[a-z0-9]{1,5}", subtype):
		return subtype
	return (mimetypes.guess_extension(mime) or ".bin").lstrip(".")


def ensure_record_for_sender(
	number: str, account: str | None, rep: str | None, profile_name: str | None = None
):
	"""Give a number nobody knows a lead and a WhatsApp Profile, once.

	Two workers can take the first two messages from a new number at the same
	moment. The lock alone does not stop a duplicate: the second worker's
	transaction would still read a snapshot from before the first one's insert,
	and the first would release the lock before the request commits. So the rows
	are committed inside the lock, and the checks run on a fresh snapshot. Nothing
	has been written yet at this point, so those commits take nothing with them.

	The profile is here because upstream inserts one per message if it is missing,
	on a unique column: the same race, failing the second message with a 417.
	"""

	def has_record():
		return lookup_contact_lead_or_deal_from_number(number, prefer_user=rep)[0]

	def has_profile():
		return frappe.db.exists("WhatsApp Profiles", {"number": number})

	if has_record() and has_profile():
		return
	with filelock(f"whatsapp_lead_{frappe.scrub(number)}", timeout=10):
		_new_snapshot()
		if not has_record():
			_create_lead(number, rep, profile_name)
		if not has_profile():
			frappe.get_doc(
				{
					"doctype": "WhatsApp Profiles",
					"number": number,
					"profile_name": profile_name,
					"whatsapp_account": account,
				}
			).insert(ignore_permissions=True)
		_new_snapshot()


def _new_snapshot():
	frappe.db.commit()  # nosemgrep: frappe-manual-commit


def _create_lead(number: str, rep: str | None, profile_name: str | None):
	"""A sender with a Contact keeps that identity: an imported contact on no deal
	has no thread anywhere, and a lead is the only place a rep can read it."""
	contact = lookup_contact_for_number(number) or frappe._dict()
	lead = frappe.new_doc("CRM Lead")
	lead.update(
		{
			"first_name": contact.first_name
			or frappe.utils.strip_html(profile_name or "").strip()[:140]
			or number,
			"last_name": contact.last_name,
			"organization": contact.company_name,
			"mobile_no": f"+{canonical_whatsapp_number(f'+{number}') or number}",
			"source": LEAD_SOURCE,
			"lead_owner": rep,
		}
	)
	lead.insert(ignore_permissions=True)
	if rep:
		# insert() stamps the session user, which here is Guest
		lead.db_set("owner", rep, update_modified=False)
	return lead
