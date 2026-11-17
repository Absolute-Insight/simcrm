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
	attach_media,
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
		self.assertEqual(note.title, "Photo and voice note")
		self.assertEqual(
			sorted(self.files_on(note.name)), sorted([f"{PREFIX}{photo}.jpg", f"{PREFIX}{voice}.webm"])
		)
		self.assertTrue(all(frappe.get_all("File", {"attached_to_name": note.name}, pluck="is_private")))

	def test_a_note_with_no_words_is_named_for_what_it_holds(self):
		def title_of(kinds, content=""):
			ids = [media_id() for _kind in kinds]
			for one, kind in zip(ids, kinds, strict=True):
				stage_media(one, kind, jpeg() if kind == "photo" else WEBM)
			replay(new_id(), "add_note", self.note(ids, content))
			return self.last_note().title

		self.assertEqual(title_of(["photo"]), "Photo")
		self.assertEqual(title_of(["photo", "photo"]), "Photos")
		self.assertEqual(title_of(["voice"]), "Voice note")
		self.assertEqual(title_of(["photo", "photo", "voice"]), "Photos and voice note")
		# words win: the note is named for its first line
		self.assertEqual(title_of(["photo"], "Gland leaking\nsee photo"), "Gland leaking")

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

	# --- the note dialog, online: upload, then name the note ---------------

	def own_note(self) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "FCRM Note",
					"title": "Typed at a desk",
					"reference_doctype": "CRM Organization",
					"reference_docname": self.org,
				}
			)
			.insert()
			.name
		)

	def test_a_photo_and_a_recording_are_added_to_a_note_already_written(self):
		note = self.own_note()
		photo, voice = media_id(), media_id()
		stage_media(photo, "photo", jpeg())
		stage_media(voice, "voice", WEBM)
		self.assertEqual(attach_media(note, [photo, voice])["attached"], 2)
		self.assertEqual(sorted(m["kind"] for m in get_note_media([note])[note]), ["photo", "voice"])
		# and as the browser sends a list: JSON text
		more = media_id()
		stage_media(more, "photo", jpeg())
		attach_media(note, frappe.as_json([more]))
		self.assertEqual(len(get_note_media([note])[note]), 3)

	def test_a_note_edited_later_takes_no_more_than_one_written_in_one_go(self):
		note = self.own_note()
		first = [media_id() for _ in range(MAX_PHOTOS)]
		for one in first:
			stage_media(one, "photo", jpeg())
		attach_media(note, first)
		extra = media_id()
		stage_media(extra, "photo", jpeg())
		name, _message = self.refusal(attach_media, note, [extra])
		self.assertEqual(name, "ValidationError")
		voice, second = media_id(), media_id()
		stage_media(voice, "voice", WEBM)
		attach_media(note, [voice])
		stage_media(second, "voice", WEBM)
		self.assertEqual(self.refusal(attach_media, note, [second])[0], "ValidationError")
		self.assertEqual(len(self.files_on(note)), MAX_PHOTOS + 1)

	def test_media_cannot_be_put_on_a_note_the_caller_may_not_edit(self):
		note = self.own_note()
		frappe.set_user(OTHER)
		photo = media_id()
		stage_media(photo, "photo", jpeg())
		refused = self.refusal(attach_media, note, [photo])
		self.assertEqual(refused[0], "PermissionError")
		# the same answer for a note that does not exist
		self.assertEqual(self.refusal(attach_media, "no-such-note", [photo]), refused)
		frappe.set_user(REP)
		self.assertEqual(self.files_on(note), [])

	def test_another_reps_upload_cannot_be_put_on_my_note(self):
		frappe.set_user(OTHER)
		theirs = media_id()
		stage_media(theirs, "photo", jpeg())
		frappe.set_user(REP)
		note = self.own_note()
		self.assertEqual(self.refusal(attach_media, note, [theirs])[0], "ValidationError")
		self.assertEqual(self.refusal(attach_media, note, [])[0], "ValidationError")
		self.assertEqual(self.files_on(note), [])

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
