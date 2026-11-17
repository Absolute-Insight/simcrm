"""Photos and voice recordings on a note, captured in field mode.

A rep at a client takes a photo or records a voice note, often with no signal.
The phone keeps the files with the note in its outbox; when it is back online
it uploads each file here first (:func:`stage_media`), then replays the note,
which claims them (:func:`claim_media`). Two steps because a replayed entry is
kept small (``crm.api.offline.MAX_PAYLOAD_BYTES``) and a photo is not.

A staged file is a private File attached to its uploader's own User record and
named after the id the phone gave it, so a retry finds it rather than storing it
twice, and nobody else can claim it. One that is never claimed -- the rep
discarded the note -- is removed after the outbox's own horizon
(:func:`purge_unclaimed_media`).
"""

from __future__ import annotations

import re
from datetime import timedelta

import frappe
from frappe import _

from crm.agent.media import MediaRejected, _check_image_size, _image_mime, decode_base64
from crm.fcrm.doctype.crm_offline_receipt.crm_offline_receipt import RECEIPT_DAYS
from crm.utils import sales_user_only, user_rate_limited

MAX_PHOTOS = 4
MAX_RECORDINGS = 1
# what the phone sends after scaling a photo down to 1600 px; a raw camera
# file is several times this, and is not what a note needs
MAX_PHOTO_BYTES = 2 * 1024 * 1024
# three minutes of the browser's own compressed audio, with room to spare
MAX_VOICE_BYTES = 4 * 1024 * 1024
MEDIA_RATE_SCOPE = "note_media"
MEDIA_RATE_LIMIT = 30
PREFIX = "field-media-"
_MEDIA_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{15,63}$")
# the notes one listing may ask about: a page of cards
MAX_LISTED_NOTES = 100

_AUDIO = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mp4": ".m4a", "audio/wav": ".wav"}
_IMAGE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_KIND_OF_EXTENSION = {
	**{ext: "photo" for ext in _IMAGE.values()},
	**{ext: "voice" for ext in _AUDIO.values()},
}


def _audio_mime(data: bytes) -> str | None:
	if data.startswith(b"\x1a\x45\xdf\xa3"):
		return "audio/webm"
	if data.startswith(b"OggS"):
		return "audio/ogg"
	if data[4:8] == b"ftyp":
		return "audio/mp4"
	if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
		return "audio/wav"
	return None


def _media_id(value) -> str:
	media_id = frappe.utils.cstr(value).strip()
	if not _MEDIA_ID.match(media_id):
		frappe.throw(_("That photo or recording has no usable id."), frappe.ValidationError)
	return media_id


def _staged(media_id: str, user: str):
	"""The caller's own staged file for ``media_id``, or None."""
	return frappe.db.get_value(
		"File",
		{
			"file_name": ("like", f"{PREFIX}{media_id}.%"),
			"owner": user,
			"attached_to_doctype": "User",
			"attached_to_name": user,
		},
		"name",
	)


def _read(kind: str, data) -> tuple[bytes, str]:
	"""The bytes and extension of one upload, or a refusal in words for the rep."""
	try:
		if kind == "photo":
			content = decode_base64(data, MAX_PHOTO_BYTES, "photo")
			mime = _image_mime(content)
			if not mime:
				raise MediaRejected("That photo is not a JPEG, PNG or WebP image.")
			_check_image_size(content)
			return content, _IMAGE[mime]
		if kind == "voice":
			content = decode_base64(data, MAX_VOICE_BYTES, "recording")
			mime = _audio_mime(content)
			if not mime:
				raise MediaRejected("That recording could not be read.")
			return content, _AUDIO[mime]
	except MediaRejected as e:
		frappe.throw(_(str(e)), frappe.ValidationError)
	frappe.throw(_("A note takes photos and voice recordings only."), frappe.ValidationError)


@frappe.whitelist(methods=["POST"])
@sales_user_only
def stage_media(media_id: str, kind: str, data: str) -> dict:
	"""Keep one photo or recording until the note it belongs to arrives.

	Idempotent on ``media_id``: the phone sends it again until it hears back,
	and a second copy is answered with the first."""
	if user_rate_limited(MEDIA_RATE_SCOPE, MEDIA_RATE_LIMIT):
		frappe.throw(_("Too many requests. Try again shortly."), frappe.TooManyRequestsError)
	media_id = _media_id(media_id)
	user = frappe.session.user
	if _staged(media_id, user):
		return {"media_id": media_id, "status": "duplicate"}
	content, extension = _read(frappe.utils.cstr(kind), data)
	frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{PREFIX}{media_id}{extension}",
			"content": content,
			"is_private": 1,
			"attached_to_doctype": "User",
			"attached_to_name": user,
		}
	).insert(ignore_permissions=True)
	return {"media_id": media_id, "status": "staged"}


def media_ids(value) -> list[str]:
	"""The ids a replayed note names, checked; at most a note's worth."""
	if value in (None, ""):
		return []
	if not isinstance(value, list) or len(value) > MAX_PHOTOS + MAX_RECORDINGS:
		frappe.throw(_("That note has too many photos or recordings."), frappe.ValidationError)
	ids = [_media_id(item) for item in value]
	return list(dict.fromkeys(ids))


def claim_media(note: str, ids: list[str]) -> None:
	"""Move the caller's staged files onto ``note``. Every one must be there:
	a note missing a photo the rep took is not the note they saved, so the
	replay is refused and the phone uploads what is missing and sends it again."""
	user = frappe.session.user
	files = []
	for media_id in ids:
		name = _staged(media_id, user)
		if not name:
			frappe.throw(
				_("A photo or recording on this note has not arrived yet. It will be sent again."),
				frappe.ValidationError,
			)
		files.append(name)
	kinds = [_kind(frappe.db.get_value("File", name, "file_name")) for name in files]
	if kinds.count("photo") > MAX_PHOTOS or kinds.count("voice") > MAX_RECORDINGS:
		frappe.throw(_("That note has too many photos or recordings."), frappe.ValidationError)
	for name in files:
		frappe.db.set_value(
			"File",
			name,
			{"attached_to_doctype": "FCRM Note", "attached_to_name": note},
			update_modified=False,
		)


def _kind(file_name: str | None) -> str | None:
	name = (file_name or "").lower()
	dot = name.rfind(".")
	return _KIND_OF_EXTENSION.get(name[dot:]) if dot > 0 else None


@frappe.whitelist()
def get_note_media(notes: list | str) -> dict:
	"""The photos and recordings on each of ``notes`` the caller can read."""
	names = frappe.parse_json(notes) if isinstance(notes, str) else notes
	if not isinstance(names, list):
		frappe.throw(_("Name the notes to look at."), frappe.ValidationError)
	names = [frappe.utils.cstr(n) for n in names[:MAX_LISTED_NOTES] if isinstance(n, str | int)]
	if not names:
		return {}
	readable = frappe.get_list("FCRM Note", filters={"name": ("in", names)}, pluck="name")
	if not readable:
		return {}
	rows = frappe.get_all(
		"File",
		filters={"attached_to_doctype": "FCRM Note", "attached_to_name": ("in", readable)},
		fields=["name", "file_url", "file_name", "attached_to_name", "creation"],
		order_by="creation asc",
	)
	media: dict[str, list] = {}
	for row in rows:
		kind = _kind(row.file_name)
		if kind:
			media.setdefault(row.attached_to_name, []).append(
				{"name": row.name, "url": row.file_url, "kind": kind}
			)
	return media


def purge_unclaimed_media() -> None:
	"""Daily: remove staged files no note claimed while a phone could still send it."""
	cutoff = frappe.utils.now_datetime() - timedelta(days=RECEIPT_DAYS + 1)
	for name in frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "User",
			"file_name": ("like", f"{PREFIX}%"),
			"creation": ("<", cutoff),
		},
		pluck="name",
	):
		frappe.delete_doc("File", name, ignore_permissions=True, force=True)
