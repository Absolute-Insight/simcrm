"""Photos and voice notes on a note taken in field mode.

Each file is uploaded first and kept for its uploader only, then the note's
replay claims it. A retry stores nothing twice, a file can only be claimed by
the rep who sent it, and only real images and recordings are kept.
"""

from __future__ import annotations

import base64
import io
from datetime import timedelta

import frappe

from crm.api.note_media import (
	MAX_PHOTOS,
	MAX_UNCLAIMED_FILES,
	PREFIX,
	UNCLAIMED_DAYS,
	get_note_media,
	purge_unclaimed_media,
	release_media,
	stage_media,
)
from crm.api.offline import replay
from crm.tests.test_offline_replay import OTHER, REP, ReplayTestCase, new_id


def jpeg(width=40, height=30) -> str:
	from PIL import Image

	out = io.BytesIO()
	Image.new("RGB", (width, height), (200, 80, 40)).save(out, "JPEG")
	return base64.b64encode(out.getvalue()).decode()


# the first bytes of a WebM file (an EBML header), as MediaRecorder writes it
WEBM = base64.b64encode(b"\x1a\x45\xdf\xa3" + b"\x00" * 64).decode()


def media_id() -> str:
	return frappe.generate_hash(length=24)


class NoteMediaTest(ReplayTestCase):
	def note(self, media, content="") -> dict:
		return {
			"reference_doctype": "CRM Organization",
			"reference_docname": self.org,
			"content": content,
			"media": media,
		}

	def files_on(self, note: str) -> list[str]:
		return frappe.get_all(
			"File", filters={"attached_to_doctype": "FCRM Note", "attached_to_name": note}, pluck="file_name"
		)

	def last_note(self):
		return frappe.get_last_doc("FCRM Note", {"reference_docname": self.org})

	def test_a_photo_and_a_voice_note_end_up_on_the_note(self):
		photo, voice = media_id(), media_id()
		self.assertEqual(stage_media(photo, "photo", jpeg())["status"], "staged")
		self.assertEqual(stage_media(voice, "voice", WEBM)["status"], "staged")
		replay(new_id(), "add_note", self.note([photo, voice]))
		note = self.last_note()
		self.assertEqual(note.title, "Photos and voice note")
		self.assertEqual(
			sorted(self.files_on(note.name)), sorted([f"{PREFIX}{photo}.jpg", f"{PREFIX}{voice}.webm"])
		)
		self.assertTrue(all(frappe.get_all("File", {"attached_to_name": note.name}, pluck="is_private")))

	def test_a_retried_upload_is_kept_once(self):
		photo = media_id()
		stage_media(photo, "photo", jpeg())
		self.assertEqual(stage_media(photo, "photo", jpeg())["status"], "duplicate")
		self.assertEqual(frappe.db.count("File", {"file_name": ("like", f"{PREFIX}{photo}%")}), 1)

	def test_a_note_whose_file_has_not_arrived_is_refused_whole(self):
		before = frappe.db.count("FCRM Note")
		name, _message = self.refusal(replay, new_id(), "add_note", self.note([media_id()], "x"))
		self.assertEqual(name, "ValidationError")
		self.assertEqual(frappe.db.count("FCRM Note"), before)

	def test_another_reps_upload_cannot_be_claimed(self):
		photo = media_id()
		frappe.set_user(OTHER)
		stage_media(photo, "photo", jpeg())
		frappe.set_user(REP)
		name, _message = self.refusal(replay, new_id(), "add_note", self.note([photo], "x"))
		self.assertEqual(name, "ValidationError")

	def test_only_images_and_recordings_are_kept(self):
		text = base64.b64encode(b"<script>alert(1)</script>").decode()
		for kind in ("photo", "voice"):
			name, _message = self.refusal(stage_media, media_id(), kind, text)
			self.assertEqual(name, "ValidationError")
		name, _message = self.refusal(stage_media, media_id(), "document", jpeg())
		self.assertEqual(name, "ValidationError")

	def test_an_id_that_is_not_an_id_is_refused(self):
		name, _message = self.refusal(stage_media, "../../etc/passwd", "photo", jpeg())
		self.assertEqual(name, "ValidationError")

	def test_too_many_photos_are_refused(self):
		ids = [media_id() for _ in range(MAX_PHOTOS + 1)]
		for one in ids:
			stage_media(one, "photo", jpeg())
		name, _message = self.refusal(replay, new_id(), "add_note", self.note(ids))
		self.assertEqual(name, "ValidationError")

	def test_a_file_already_on_its_note_is_not_stored_again(self):
		photo = media_id()
		stage_media(photo, "photo", jpeg())
		replay(new_id(), "add_note", self.note([photo]))
		self.assertEqual(stage_media(photo, "photo", jpeg())["status"], "duplicate")
		self.assertEqual(frappe.db.count("File", {"file_name": ("like", f"{PREFIX}{photo}%")}), 1)

	def test_a_size_claimed_by_the_request_is_not_believed(self):
		frappe.form_dict.file_size = 1
		self.addCleanup(frappe.form_dict.pop, "file_size", None)
		photo = media_id()
		data = jpeg()
		stage_media(photo, "photo", data)
		size = frappe.db.get_value("File", {"file_name": ("like", f"{PREFIX}{photo}%")}, "file_size")
		self.assertEqual(size, len(base64.b64decode(data)))

	def test_a_discarded_note_releases_its_uploads(self):
		photo = media_id()
		stage_media(photo, "photo", jpeg())
		frappe.set_user(OTHER)
		self.assertEqual(release_media([photo])["released"], 0)
		frappe.set_user(REP)
		self.assertEqual(release_media([photo])["released"], 1)
		self.assertFalse(frappe.db.exists("File", {"file_name": ("like", f"{PREFIX}{photo}%")}))

	def test_a_rep_cannot_pile_up_uploads_no_note_claims(self):
		for _ in range(MAX_UNCLAIMED_FILES):
			stage_media(media_id(), "photo", jpeg())
		name, _message = self.refusal(stage_media, media_id(), "photo", jpeg())
		self.assertEqual(name, "ValidationError")

	def test_an_empty_note_with_nothing_attached_is_still_refused(self):
		name, _message = self.refusal(replay, new_id(), "add_note", self.note([]))
		self.assertEqual(name, "ValidationError")

	def test_the_media_listing_names_only_notes_the_caller_can_read(self):
		photo = media_id()
		stage_media(photo, "photo", jpeg())
		replay(new_id(), "add_note", self.note([photo]))
		note = self.last_note().name
		media = get_note_media([note])
		self.assertEqual([m["kind"] for m in media[note]], ["photo"])
		frappe.set_user(OTHER)
		self.assertEqual(get_note_media([note]), {})

	def test_a_photos_thumbnail_is_not_listed_as_another_photo(self):
		from crm.utils.thumbnails import make_thumbnail

		photo = media_id()
		stage_media(photo, "photo", jpeg(1200, 900))
		replay(new_id(), "add_note", self.note([photo]))
		note = self.last_note().name
		source = frappe.db.get_value("File", {"file_name": f"{PREFIX}{photo}.jpg"}, "name")
		self.assertTrue(make_thumbnail(source))
		# the thumbnail sits on the note beside its photo
		self.assertEqual(len(self.files_on(note)), 2)
		self.assertEqual([m["name"] for m in get_note_media([note])[note]], [source])

	def test_unclaimed_uploads_are_removed_after_the_outbox_horizon(self):
		old, fresh = media_id(), media_id()
		stage_media(old, "photo", jpeg())
		stage_media(fresh, "photo", jpeg())
		frappe.set_user("Administrator")
		stale = frappe.utils.now_datetime() - timedelta(days=UNCLAIMED_DAYS + 1)
		frappe.db.set_value(
			"File", {"file_name": f"{PREFIX}{old}.jpg"}, "creation", stale, update_modified=False
		)
		purge_unclaimed_media()
		self.assertFalse(frappe.db.exists("File", {"file_name": f"{PREFIX}{old}.jpg"}))
		self.assertTrue(frappe.db.exists("File", {"file_name": f"{PREFIX}{fresh}.jpg"}))
