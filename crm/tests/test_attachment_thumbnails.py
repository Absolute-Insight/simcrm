# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Thumbnails of image attachments: as private as the photo, and nothing more.

frappe's own ``File.make_thumbnail`` writes the copy under the public folder
whatever the source is, so a private site photo would have had a world-readable
twin. ``crm.utils.thumbnails`` makes its own, and these pin what it promises:
who can open one, what it carries, what it refuses, and that it stays out of the
lists a rep reads.
"""

from __future__ import annotations

import io
import os
from unittest.mock import patch

import frappe
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.tests import IntegrationTestCase
from PIL import Image

from crm.api.activities import get_attachments, get_attachments_by_name
from crm.utils import thumbnails
from crm.utils.thumbnails import FIELD

OWNER = "thumb-owner@crmtest.test"
OTHER = "thumb-other@crmtest.test"
ASSIGNEE = "thumb-assignee@crmtest.test"

GPS_IFD = 0x8825
ORIENTATION = 0x0112


def ensure_user(email: str, name: str, *roles: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles(*roles)


def photo(size=(400, 200), orientation: int | None = None, gps: bool = True, fmt="JPEG") -> bytes:
	"""A small image with a GPS position and, optionally, an EXIF orientation."""
	image = Image.new("RGB", size, (200, 40, 40))
	# a distinct pixel per call: frappe refuses the same content twice on a record
	image.putpixel((0, 0), tuple(int(x, 16) * 16 for x in frappe.generate_hash(length=3)))
	exif = Image.Exif()
	if orientation:
		exif[ORIENTATION] = orientation
	if gps:
		position = exif.get_ifd(GPS_IFD)
		position[1] = "S"
		position[2] = (26.0, 12.0, 30.0)
		position[3] = "E"
		position[4] = (28.0, 2.0, 15.0)
	out = io.BytesIO()
	image.save(out, fmt, exif=exif.tobytes())
	return out.getvalue()


class AttachmentThumbnailTest(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		# installed with the app; here in case this site predates the patch (DDL commits)
		thumbnails.ensure_thumbnail_field()

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		ensure_user(OWNER, "Thumb Owner", "Sales User")
		ensure_user(OTHER, "Thumb Other", "Sales User")
		ensure_user(ASSIGNEE, "Thumb Assignee", "Sales User")

		for doctype, field, value in (
			("FCRM Settings", "enable_sales_hierarchy", 1),
			# frappe would strip the source's EXIF itself, and the GPS test would prove nothing
			("System Settings", "strip_exif_metadata_from_uploaded_images", 0),
		):
			saved = frappe.db.get_single_value(doctype, field)
			frappe.db.set_single_value(doctype, field, value)
			self.addCleanup(frappe.db.set_single_value, doctype, field, saved)
		people = [OWNER, OTHER, ASSIGNEE]
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", people)})

		# the insert hook queues a job after commit; here the job is run by hand
		enqueue = patch("crm.utils.thumbnails.frappe.enqueue")
		self.enqueued = enqueue.start()
		self.addCleanup(enqueue.stop)

		self.lead = self.make({"doctype": "CRM Lead", "first_name": "Thumb", "lead_owner": OWNER})
		self.make(
			{
				"doctype": "ToDo",
				"allocated_to": ASSIGNEE,
				"reference_type": "CRM Lead",
				"reference_name": self.lead.name,
				"status": "Open",
				"description": "Look at the site photos",
			}
		)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		super().tearDown()

	def make(self, payload: dict):
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	def attach(self, content: bytes, file_name="site.jpg", is_private=1, doc=None, user=OWNER):
		doc = doc or self.lead
		frappe.set_user(user)
		try:
			return frappe.get_doc(
				{
					"doctype": "File",
					"file_name": file_name,
					"content": content,
					"is_private": is_private,
					"attached_to_doctype": doc.doctype,
					"attached_to_name": doc.name,
				}
			).insert(ignore_permissions=True)
		finally:
			frappe.set_user("Administrator")

	def thumbnail_jobs(self) -> list[dict]:
		"""The thumbnail jobs queued so far (frappe.enqueue is patched for everyone)."""
		return [
			call.kwargs
			for call in self.enqueued.call_args_list
			if call.args and call.args[0] == "crm.utils.thumbnails.make_thumbnail"
		]

	def thumbnail_of(self, source):
		return frappe.get_doc("File", {FIELD: source.name})

	def opened_by(self, user: str, file_url: str):
		"""What the private-file route would hand ``user`` for ``file_url``."""
		frappe.set_user(user)
		try:
			return find_file_by_url(file_url)
		finally:
			frappe.set_user("Administrator")

	# ------------------------------------------------------------------------

	def test_a_private_photo_gets_a_private_thumbnail_on_the_same_record(self):
		source = self.attach(photo())
		url = thumbnails.make_thumbnail(source.name)

		thumb = self.thumbnail_of(source)
		self.assertEqual(url, thumb.file_url)
		self.assertTrue(url.startswith("/private/files/"))
		self.assertEqual(thumb.is_private, 1)
		self.assertEqual(
			(thumb.attached_to_doctype, thumb.attached_to_name, thumb.owner),
			("CRM Lead", self.lead.name, OWNER),
		)
		self.assertEqual(frappe.db.get_value("File", source.name, "thumbnail_url"), url)
		path = frappe.get_site_path("private", "files", os.path.basename(url))
		self.assertTrue(os.path.isfile(path))
		self.assertFalse(os.path.exists(frappe.get_site_path("public", "files", os.path.basename(url))))
		with Image.open(path) as image:
			self.assertEqual(image.format, "JPEG")
			self.assertLessEqual(max(image.size), 256)

	def test_a_public_photo_gets_a_public_thumbnail(self):
		source = self.attach(photo(), is_private=0)
		url = thumbnails.make_thumbnail(source.name)
		self.assertTrue(url.startswith("/files/"))
		self.assertEqual(self.thumbnail_of(source).is_private, 0)

	def test_the_thumbnail_opens_to_exactly_who_the_photo_opens_to(self):
		source = self.attach(photo())
		url = thumbnails.make_thumbnail(source.name)

		for user, allowed in ((OWNER, True), (ASSIGNEE, True), (OTHER, False)):
			with self.subTest(user=user):
				self.assertEqual(bool(self.opened_by(user, source.file_url)), allowed)
				self.assertEqual(bool(self.opened_by(user, url)), allowed)

	def test_location_and_camera_metadata_do_not_reach_the_thumbnail(self):
		source = self.attach(photo(orientation=6))
		with Image.open(frappe.get_site_path("private", "files", source.file_name)) as original:
			self.assertIn(GPS_IFD, original.getexif(), "the source must carry GPS for this to mean anything")

		url = thumbnails.make_thumbnail(source.name)
		with Image.open(frappe.get_site_path("private", "files", os.path.basename(url))) as image:
			self.assertNotIn(GPS_IFD, image.getexif())
			self.assertEqual(len(image.getexif()), 0)
			self.assertNotIn("exif", image.info)
			self.assertNotIn("icc_profile", image.info)
			self.assertNotIn("xmp", image.info)
			# orientation 6 is a quarter turn: the 400x200 landscape is drawn upright, portrait
			self.assertGreater(image.height, image.width)

	def test_a_decompression_bomb_is_refused_before_it_is_decoded(self):
		big = Image.new("1", (9000, 9000))  # 81 MP, a few kilobytes as PNG
		out = io.BytesIO()
		big.save(out, "PNG")
		source = self.attach(out.getvalue(), file_name="bomb.png")

		self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertFalse(frappe.db.get_value("File", source.name, "thumbnail_url"))
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))

	def test_a_file_over_the_size_cap_is_refused(self):
		source = self.attach(photo())
		with patch.object(thumbnails, "MAX_SOURCE_BYTES", 100):
			self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))

	def test_svg_and_a_disguised_svg_are_skipped(self):
		svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
		real = self.attach(svg, file_name="logo.svg")
		disguised = self.attach(svg + b"<!-- x -->", file_name="logo.png")

		self.assertFalse(thumbnails.is_candidate(real))
		# the .png only; the .svg was never queued
		self.assertEqual([job["name"] for job in self.thumbnail_jobs()], [disguised.name])
		for source in (real, disguised):
			self.assertIsNone(thumbnails.make_thumbnail(source.name))
			self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))

	def test_an_upload_queues_one_deduplicated_job_and_a_rerun_makes_no_second_copy(self):
		source = self.attach(photo())
		[kwargs] = self.thumbnail_jobs()
		self.assertEqual(kwargs["job_id"], f"crm_thumbnail::{source.name}")
		self.assertTrue(kwargs["deduplicate"])
		self.assertTrue(kwargs["enqueue_after_commit"])

		first = thumbnails.make_thumbnail(source.name)
		second = thumbnails.make_thumbnail(source.name)
		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("File", {FIELD: source.name}), 1)
		# the thumbnail itself queued nothing
		self.assertEqual(len(self.thumbnail_jobs()), 1)

	def test_deleting_the_photo_deletes_its_thumbnail(self):
		source = self.attach(photo())
		url = thumbnails.make_thumbnail(source.name)
		path = frappe.get_site_path("private", "files", os.path.basename(url))

		frappe.delete_doc("File", source.name, ignore_permissions=True)

		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))
		self.assertFalse(os.path.exists(path))
		# and no "Attachment removed" line for the thumbnail on the record
		removed = frappe.get_all(
			"Comment",
			filters={"reference_name": self.lead.name, "comment_type": "Attachment Removed"},
			pluck="content",
		)
		self.assertEqual(removed, [source.file_name])

	def test_moving_the_photo_moves_its_thumbnail(self):
		source = self.attach(photo())
		thumbnails.make_thumbnail(source.name)
		other = self.make({"doctype": "CRM Lead", "first_name": "Elsewhere", "lead_owner": OTHER})

		source.reload()
		source.attached_to_name = other.name
		source.save(ignore_permissions=True)

		self.assertEqual(self.thumbnail_of(source).attached_to_name, other.name)

	def test_making_the_photo_public_remakes_its_thumbnail_public(self):
		source = self.attach(photo())
		thumbnails.make_thumbnail(source.name)

		source.reload()
		source.is_private = 0
		source.save(ignore_permissions=True)

		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))
		self.assertFalse(frappe.db.get_value("File", source.name, "thumbnail_url"))
		self.assertEqual(self.thumbnail_jobs()[-1]["name"], source.name)
		url = thumbnails.make_thumbnail(source.name)
		self.assertTrue(url.startswith("/files/"))

	def test_a_copy_of_the_photo_does_not_take_over_its_thumbnail(self):
		source = self.attach(photo())
		url = thumbnails.make_thumbnail(source.name)
		comment = self.make(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "see photo",
			}
		)
		copy = frappe.get_doc("File", source.name).create_attachment_copy(
			"Comment", comment.name, ignore_permissions=True
		)
		self.assertFalse(copy.thumbnail_url)
		frappe.delete_doc("File", copy.name, ignore_permissions=True)
		self.assertTrue(os.path.isfile(frappe.get_site_path("private", "files", os.path.basename(url))))

	def test_thumbnails_are_not_listed_as_attachments(self):
		source = self.attach(photo())
		thumbnails.make_thumbnail(source.name)
		comment = self.make(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "CRM Lead",
				"reference_name": self.lead.name,
				"content": "photo",
			}
		)
		on_comment = self.attach(photo(), doc=comment)
		thumbnails.make_thumbnail(on_comment.name)

		self.assertEqual([row.name for row in get_attachments("CRM Lead", self.lead.name)], [source.name])
		self.assertEqual(
			[row.name for row in get_attachments_by_name("Comment", [comment.name])[comment.name]],
			[on_comment.name],
		)
		for user in (OWNER, ASSIGNEE):
			with self.subTest(user=user):
				frappe.set_user(user)
				listed = frappe.get_list("File", filters={"attached_to_name": self.lead.name}, pluck="name")
				frappe.set_user("Administrator")
				self.assertEqual(listed, [source.name])

	def test_a_rep_cannot_mark_a_file_as_someone_elses_thumbnail(self):
		victim = self.attach(photo())
		frappe.set_user(OTHER)
		try:
			mine = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "mine.txt",
					"content": "hidden?",
					"is_private": 1,
					FIELD: victim.name,
				}
			).insert()
			self.assertFalse(mine.get(FIELD))
			mine.set(FIELD, victim.name)
			mine.save()
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("File", mine.name, FIELD))

	def test_the_backfill_works_in_batches_and_resumes_where_it_stopped(self):
		first = self.attach(photo())
		broken = self.attach(b"not really a jpeg", file_name="broken.jpg")
		third = self.attach(photo(), file_name="third.png")
		saved = frappe.db.get_global(thumbnails.BACKFILL_CURSOR)
		self.addCleanup(frappe.db.set_global, thumbnails.BACKFILL_CURSOR, saved)
		# start just before these three: the shared test site has images of its own
		frappe.db.set_global(thumbnails.BACKFILL_CURSOR, f"{first.creation}|")

		self.assertEqual(thumbnails.backfill_thumbnails(limit=2, commit=False), 2)
		self.assertTrue(frappe.db.get_value("File", first.name, "thumbnail_url"))
		self.assertFalse(frappe.db.get_value("File", third.name, "thumbnail_url"))

		# the broken one is behind the cursor now, not at the head of every batch
		self.assertEqual(thumbnails.backfill_thumbnails(limit=2, commit=False), 1)
		self.assertTrue(frappe.db.get_value("File", third.name, "thumbnail_url"))
		self.assertFalse(frappe.db.get_value("File", broken.name, "thumbnail_url"))

		self.assertEqual(thumbnails.backfill_thumbnails(limit=2, commit=False), 0)
		self.assertEqual(frappe.db.count("File", {FIELD: ("in", [first.name, third.name])}), 2)
