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
import math
import os
import subprocess
import sys
import tempfile
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
MANAGER = "thumb-manager@crmtest.test"

#: What one render may add to a worker's resident memory, at each format's cap.
#: queue-short runs in 512 MB; measured peaks are 14-126 MB.
RENDER_MEMORY_BOUND_MB = 160

MEASURE = """
import sys
from crm.utils import thumbnails

def peak_kb(key):
    with open("/proc/self/status") as status:
        return int(next(line for line in status if line.startswith(key)).split()[1])

with open("/proc/self/clear_refs", "w") as refs:
    refs.write("5")  # resets VmHWM to what is resident now
before = peak_kb("VmRSS:")
try:
    thumbnails.render(sys.argv[1])
    result = "made"
except thumbnails.Refused:
    result = "refused"
print(result, (peak_kb("VmHWM:") - before) // 1024)
"""

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
		ensure_user(MANAGER, "Thumb Manager", "Sales Manager")
		people = [OWNER, OTHER, ASSIGNEE, MANAGER]
		frappe.db.delete("CRM Sales Hierarchy", {"user": ("in", people)})
		top = self.make({"doctype": "CRM Sales Hierarchy", "user": MANAGER})
		self.make({"doctype": "CRM Sales Hierarchy", "user": OWNER, "reports_to": top.name})

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

	def attach(self, content: bytes, file_name=None, is_private=1, doc=None, user=OWNER):
		doc = doc or self.lead
		# unique: a file moved between public and private refuses a name already there
		file_name = file_name or f"site-{frappe.generate_hash(length=8)}.jpg"
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

	# -- review follow-ups ------------------------------------------------------

	def files_on_disk(self, source_name: str, private=True) -> list[str]:
		folder = frappe.get_site_path("private" if private else "public", "files")
		return sorted(f for f in os.listdir(folder) if f.startswith(f"thumb-{source_name}"))

	def test_render_stays_within_its_memory_bound(self):
		"""Decoding is width x height x bands whatever the file size: pinned per format at its cap."""
		if not os.path.exists("/proc/self/clear_refs"):
			self.skipTest("peak memory is read from /proc")
		samples = thumbnails.PROGRESSIVE_SAMPLES
		progressive = {"progressive": True}
		cases = [
			("JPEG at the cap", "RGB", thumbnails.MAX_PIXELS, "JPEG", {}),
			("CMYK JPEG at the cap", "CMYK", thumbnails.MAX_PIXELS, "JPEG", {}),
			# draft() does not shrink a progressive JPEG's coefficient buffer
			("progressive 4:2:0", "RGB", samples / 1.5, "JPEG", {**progressive, "subsampling": 2}),
			("progressive 4:4:4", "RGB", samples / 3, "JPEG", {**progressive, "subsampling": 0}),
			("progressive grey", "L", samples, "JPEG", progressive),
			("progressive CMYK", "CMYK", samples / 4, "JPEG", progressive),
			("RGBA PNG at the cap", "RGBA", thumbnails.MAX_PIXELS_DECODED, "PNG", {}),
			("16-bit grey PNG at the cap", "I;16", thumbnails.MAX_PIXELS_DECODED, "PNG", {}),
			("lossless WebP at the cap", "RGBA", thumbnails.MAX_PIXELS_WEBP, "WEBP", {"lossless": True}),
			("palette GIF at the cap", "P", thumbnails.MAX_PIXELS_DECODED, "GIF", {}),
		]
		root = os.path.dirname(os.path.dirname(thumbnails.__file__))
		env = {**os.environ, "PYTHONPATH": os.pathsep.join([root, os.environ.get("PYTHONPATH", "")])}
		with tempfile.TemporaryDirectory() as folder:
			for label, mode, pixels, fmt, options in cases:
				with self.subTest(label):
					side = int(math.sqrt(pixels / 12)) - 1
					path = os.path.join(folder, f"image.{fmt.lower()}")
					Image.new(mode, (side * 4, side * 3)).save(path, fmt, **options)
					out = subprocess.run(
						[sys.executable, "-c", MEASURE, path],
						env=env,
						capture_output=True,
						text=True,
						check=True,
					)
					result, peak = out.stdout.split()
					self.assertEqual(result, "made")
					self.assertLess(int(peak), RENDER_MEMORY_BOUND_MB, f"{label}: {peak} MB")

	def test_a_large_progressive_jpeg_is_refused_from_its_header(self):
		with tempfile.TemporaryDirectory() as folder:
			for mode, options in (("RGB", {"subsampling": 2}), ("RGB", {"subsampling": 0}), ("CMYK", {})):
				with self.subTest(mode=mode, **options):
					path = os.path.join(folder, "progressive.jpg")
					Image.new(mode, (8000, 6000)).save(path, "JPEG", progressive=True, **options)
					with self.assertRaises(thumbnails.Refused):
						thumbnails.render(path)
					# the same canvas, baseline, decodes at 1/8 and is made
					Image.new(mode, (8000, 6000)).save(path, "JPEG", **options)
					self.assertTrue(thumbnails.render(path))

	def test_a_16_bit_grey_png_is_scaled_not_refused(self):
		with tempfile.TemporaryDirectory() as folder:
			path = os.path.join(folder, "depth.png")
			for size in ((3000, 2000), (400, 300)):  # reduced first, and drawn as it is
				Image.new("I;16", size, 32768).save(path, "PNG")
				with Image.open(io.BytesIO(thumbnails.render(path))) as image:
					# mid-grey, not clipped to white
					self.assertAlmostEqual(image.getpixel((0, 0))[0], 128, delta=2)

	def test_a_tiny_file_declaring_a_huge_canvas_is_refused_from_its_header(self):
		with tempfile.TemporaryDirectory() as folder:
			for fmt, options in (("WEBP", {"lossless": True}), ("PNG", {})):
				with self.subTest(fmt):
					path = os.path.join(folder, f"bomb.{fmt.lower()}")
					Image.new("RGBA", (8000, 6000)).save(path, fmt, **options)
					self.assertLess(os.path.getsize(path), 300_000)
					with self.assertRaises(thumbnails.Refused):
						thumbnails.render(path)

	def test_only_the_allowed_parsers_read_the_file(self):
		out = io.BytesIO()
		Image.new("RGB", (40, 40)).save(out, "TIFF")
		source = self.attach(out.getvalue(), file_name="scan.png")
		self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))

	def test_a_truncated_photo_is_logged_not_filed_as_an_error(self):
		source = self.attach(photo(size=(1200, 900))[:2000], file_name="cut.jpg")
		errors = frappe.db.count("Error Log")
		self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertEqual(frappe.db.count("Error Log"), errors)

	def test_a_truncated_photo_is_refused_whatever_the_process_has_told_pillow(self):
		from PIL import ImageFile

		# frappe.utils.image turns this on at import, for every later decode
		before = ImageFile.LOAD_TRUNCATED_IMAGES
		ImageFile.LOAD_TRUNCATED_IMAGES = True
		self.addCleanup(setattr, ImageFile, "LOAD_TRUNCATED_IMAGES", before)
		source = self.attach(photo(size=(1200, 900))[:2000], file_name="cut.jpg")
		self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))
		# and the process's own setting is put back
		self.assertTrue(ImageFile.LOAD_TRUNCATED_IMAGES)

	def test_the_backfill_moves_its_cursor_before_it_renders(self):
		source = self.attach(photo())
		saved = frappe.db.get_global(thumbnails.BACKFILL_CURSOR)
		self.addCleanup(frappe.db.set_global, thumbnails.BACKFILL_CURSOR, saved)
		frappe.db.set_global(thumbnails.BACKFILL_CURSOR, f"{source.creation}|")

		def worker_killed(name):
			raise SystemExit("OOM")

		with patch.object(thumbnails, "make_thumbnail", worker_killed), self.assertRaises(SystemExit):
			thumbnails.backfill_thumbnails(limit=5, commit=False)
		# the next run starts after it, not on it again
		self.assertEqual(frappe.db.get_global(thumbnails.BACKFILL_CURSOR), f"{source.creation}|{source.name}")

	def test_making_one_copy_private_leaves_the_other_copy_and_its_thumbnail(self):
		"""Older frappe moved every row with the same bytes by raw SQL, no hooks run,
		which would have left the other copy's thumbnail public. The pinned frappe
		copies the file instead; if that ever changes back, this fails."""
		content = photo()
		other_lead = self.make({"doctype": "CRM Lead", "first_name": "Twin", "lead_owner": OWNER})
		twin = f"twin-{frappe.generate_hash(length=8)}.jpg"
		first = self.attach(content, file_name=twin, is_private=0)
		second = self.attach(content, file_name=twin, is_private=0, doc=other_lead)
		self.assertEqual(first.file_url, second.file_url, "frappe stores the same bytes once")
		thumbnails.make_thumbnail(first.name)
		public_twin = thumbnails.make_thumbnail(second.name)

		first.reload()
		first.is_private = 1
		first.save(ignore_permissions=True)

		self.assertEqual(
			frappe.db.get_value("File", second.name, ["is_private", "thumbnail_url"]), (0, public_twin)
		)
		self.assertTrue(thumbnails.make_thumbnail(first.name).startswith("/private/files/"))

	def test_a_photo_made_public_while_it_is_drawn_is_left_to_the_job_that_change_queued(self):
		source = self.attach(photo())
		real_render = thumbnails.render
		calls = []

		def render_while_privacy_changes(path):
			doc = frappe.get_doc("File", source.name)
			doc.is_private = 0
			doc.save(ignore_permissions=True)
			calls.append(path)
			return real_render(path)

		with patch.object(thumbnails, "render", render_while_privacy_changes):
			self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertEqual(len(calls), 1, "no second render while the source row is locked")
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}), "nothing filed as private")
		self.assertEqual(self.files_on_disk(source.name), [])
		# the change queued its own job, not deduplicated against the running one
		[job] = [
			job for job in self.thumbnail_jobs() if job["name"] == source.name and not job["deduplicate"]
		]
		self.assertIsNone(job["job_id"])
		self.assertTrue(thumbnails.make_thumbnail(source.name).startswith("/files/"))

	def test_a_photo_deleted_while_it_is_drawn_leaves_nothing_behind(self):
		source = self.attach(photo())
		real_render = thumbnails.render

		def render_while_deleted(path):
			content = real_render(path)
			frappe.delete_doc("File", source.name, ignore_permissions=True)
			return content

		with patch.object(thumbnails, "render", render_while_deleted):
			self.assertIsNone(thumbnails.make_thumbnail(source.name))
		self.assertFalse(frappe.db.exists("File", {FIELD: source.name}))
		self.assertEqual(self.files_on_disk(source.name), [])

	def test_a_file_already_at_the_chosen_name_is_never_overwritten(self):
		source = self.attach(photo())
		taken = frappe.get_site_path("private", "files", f"thumb-{source.name}-taken.jpg")
		with open(taken, "wb") as handle:
			handle.write(b"someone else's upload")
		self.addCleanup(lambda: os.path.exists(taken) and os.remove(taken))

		names = iter(["taken", "free"])
		with patch.object(thumbnails, "_random_part", lambda: next(names)):
			url = thumbnails.make_thumbnail(source.name)

		self.assertEqual(url, f"/private/files/thumb-{source.name}-free.jpg")
		with open(taken, "rb") as handle:
			self.assertEqual(handle.read(), b"someone else's upload")

	def test_a_rep_cannot_point_a_thumbnail_url_at_someone_elses_file(self):
		victim = self.attach(
			b"quote for the customer", file_name=f"quote-{frappe.generate_hash(length=6)}.txt"
		)
		victim_path = frappe.get_site_path("private", "files", os.path.basename(victim.file_url))
		frappe.set_user(OTHER)
		try:
			mine = frappe.get_doc(
				{"doctype": "File", "file_name": "mine.txt", "content": "mine", "is_private": 1}
			).insert()
			frappe.client.set_value("File", mine.name, "thumbnail_url", victim.file_url)
			self.assertFalse(frappe.db.get_value("File", mine.name, "thumbnail_url"))
			frappe.client.delete("File", mine.name)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(os.path.isfile(victim_path), "deleting their upload deleted the victim's file")

	def test_a_thumbnail_url_may_still_be_cleared(self):
		source = self.attach(photo())
		thumbnails.make_thumbnail(source.name)
		frappe.set_user(OWNER)
		try:
			frappe.client.set_value("File", source.name, "thumbnail_url", None)
		finally:
			frappe.set_user("Administrator")
		self.assertFalse(frappe.db.get_value("File", source.name, "thumbnail_url"))

	def test_after_a_move_the_thumbnail_opens_to_the_new_records_readers_and_still_to_its_uploader(self):
		source = self.attach(photo())
		url = thumbnails.make_thumbnail(source.name)
		other = self.make({"doctype": "CRM Lead", "first_name": "Moved", "lead_owner": OTHER})
		source.reload()
		source.attached_to_name = other.name
		source.save(ignore_permissions=True)

		for user, allowed in ((OWNER, True), (OTHER, True), (ASSIGNEE, False)):
			with self.subTest(user=user):
				self.assertEqual(bool(self.opened_by(user, source.file_url)), allowed)
				self.assertEqual(bool(self.opened_by(user, url)), allowed)

	def test_a_sales_manager_over_the_rep_lists_the_photo_not_its_thumbnail(self):
		source = self.attach(photo())
		thumbnails.make_thumbnail(source.name)
		frappe.set_user(MANAGER)
		try:
			listed = frappe.get_list("File", filters={"attached_to_name": self.lead.name}, pluck="name")
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(listed, [source.name])

	def test_the_upgrade_clears_thumbnail_urls_this_app_did_not_set(self):
		from crm.patches.v1_0.clear_untrusted_thumbnail_urls import execute

		victim = self.attach(b"quote", file_name=f"quote-{frappe.generate_hash(length=6)}.txt")
		planted = self.attach(b"mine", file_name=f"mine-{frappe.generate_hash(length=6)}.txt", user=OTHER)
		frappe.db.set_value("File", planted.name, "thumbnail_url", victim.file_url)
		# what frappe's own make_thumbnail used to leave: a public _small copy only this row uses
		legacy = self.attach(photo(), is_private=0)
		small = frappe.get_site_path("public", "files", f"legacy-{legacy.name}_small.jpg")
		with open(small, "wb") as handle:
			handle.write(b"old public thumbnail")
		self.addCleanup(lambda: os.path.exists(small) and os.remove(small))
		frappe.db.set_value("File", legacy.name, "thumbnail_url", f"/files/{os.path.basename(small)}")
		ours = self.attach(photo())
		our_url = thumbnails.make_thumbnail(ours.name)
		# another File may not borrow ours either
		frappe.db.set_value("File", planted.name, "thumbnail_url", our_url)
		frappe.db.set_value("File", victim.name, "thumbnail_url", victim.file_url)

		execute()
		execute()  # idempotent

		self.assertEqual(frappe.db.get_value("File", ours.name, "thumbnail_url"), our_url)
		for row in (planted, legacy, victim):
			self.assertFalse(frappe.db.get_value("File", row.name, "thumbnail_url"), row.file_name)
		# only references are dropped: no file is deleted
		self.assertTrue(os.path.isfile(small))
		self.assertTrue(
			os.path.isfile(frappe.get_site_path("private", "files", os.path.basename(victim.file_url)))
		)
		self.assertTrue(os.path.isfile(frappe.get_site_path("private", "files", os.path.basename(our_url))))
