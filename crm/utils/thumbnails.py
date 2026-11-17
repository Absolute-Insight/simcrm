"""Small, metadata-free copies of image attachments, as private as the original.

The Attachments tab draws each image 44px square, and reps attach phone photos
of 3-8 MB. frappe has ``File.make_thumbnail``, but it writes the copy under the
site's *public* folder whatever the source is -- a private site photo would get
a world-readable twin -- so it is not used here.

A thumbnail is a File row of its own:

- the same ``is_private`` as its source, and the same owner and attached record,
  so frappe's private-file route (``frappe.utils.response.download_private_file``
  -> ``File.is_downloadable`` -> frappe's File ``has_permission``) opens it to
  exactly the people the source opens to: its owner, and whoever can read the
  record. A DocShare on the source File is the one grant it does not copy, so
  it never opens to *more* people than the source; someone the photo alone was
  shared with is refused the thumbnail, and AttachmentArea's ``@error``
  fallback draws the original for them instead;
- marked with ``crm_thumbnail_of`` (the source File's name), which keeps it out
  of the attachment lists, out of a rep's File list, and from being thumbnailed;
- a JPEG re-encoded from pixels alone: no EXIF (GPS, the phone, the time), no
  XMP, no ICC profile -- a profile is applied first, so the colours stay right;
- removed with its source, and moved with it when the source is re-pointed or
  made public or private.

It is attached *after* insert, by ``db.set_value``: inserting it attached
would put an "Attachment added" line on the record's timeline, and deleting it
through ``delete_doc`` an "Attachment removed" one.

Everything that can go wrong (an unreadable or oversized file, a decompression
bomb, an unknown format) is logged and leaves ``thumbnail_url`` empty; the UI
then draws the original, as it always has.
"""

from __future__ import annotations

import io
import os
import traceback
import warnings
from contextlib import contextmanager

import frappe
from frappe.core.doctype.file.utils import get_content_hash

#: The custom field on File naming the source of a thumbnail row.
FIELD = "crm_thumbnail_of"

#: Fits inside this box: twice the largest place the UI draws one (44px today),
#: with room for a later, larger preview.
BOX = (256, 256)
JPEG_QUALITY = 80

#: Bigger than any phone photo, and frappe's own upload limit is 10 MB by default.
MAX_SOURCE_BYTES = 25 * 1024 * 1024
#: A 48 MP phone sensor is 48.8 MP. Checked from the header, before any pixel
#: is decoded, so a small file declaring a huge canvas is refused unread. A
#: JPEG (and MPO, a phone's JPEG pair) is decoded at 1/8 of that.
MAX_PIXELS = 50_000_000
#: Every other format is decoded full-size before it can be shrunk, at up to
#: four bytes a pixel and more inside libwebp: kept so a render stays well
#: inside a 512 MB worker. A screenshot or a PNG diagram is far below this.
#: Measured peak per render (VmHWM above the imports) at these caps: JPEG
#: 48 MP 14 MB, PNG RGB/RGBA 16 MP 83 MB, palette PNG/GIF 16 MP 25 MB, WebP
#: 8 MP 126 MB. Above them a file is refused from its header alone.
MAX_PIXELS_DECODED = 16_000_000
MAX_PIXELS_WEBP = 8_000_000
#: A *progressive* JPEG is the exception to draft(): libjpeg keeps every DCT
#: coefficient of the whole image, two bytes a sample, whatever scale it
#: outputs. So its cap is a budget of samples, divided by the samples a pixel
#: carries (1.5 for 4:2:0 colour, 3 for 4:4:4, 1 grey, 4 CMYK): 4:2:0 at
#: 21 MP, 4:4:4 at 10.6 MP, grey at 32 MP, CMYK at 8 MP. Measured at those
#: caps: 66-71 MB. Baseline JPEGs, which phones write, stay at MAX_PIXELS.
PROGRESSIVE_SAMPLES = 32_000_000

#: The formats Pillow may open, whatever the file is called, and each one's cap.
RASTER_FORMATS = {
	"JPEG": MAX_PIXELS,
	"MPO": MAX_PIXELS,
	"PNG": MAX_PIXELS_DECODED,
	"GIF": MAX_PIXELS_DECODED,
	"WEBP": MAX_PIXELS_WEBP,
}
RASTER_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "gif"}
HEIF_EXTENSIONS = {"heic", "heif"}

#: Existing images thumbnailed per scheduler run.
BACKFILL_BATCH = 200
BACKFILL_CURSOR = "crm_thumbnail_backfill_cursor"


class Refused(Exception):
	"""The file is not one a thumbnail is made of. Expected; not an error."""


# ------------------------------------------------------------------------------
# the field


def ensure_thumbnail_field() -> None:
	"""The ``crm_thumbnail_of`` custom field on File. Safe to repeat."""
	if frappe.get_meta("File").has_field(FIELD):
		return
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	create_custom_fields(
		{
			"File": [
				{
					"fieldname": FIELD,
					"fieldtype": "Data",
					"label": "Thumbnail Of",
					"insert_after": "thumbnail_url",
					"read_only": 1,
					"hidden": 1,
					"no_copy": 1,
				}
			]
		},
		ignore_validate=True,
	)
	frappe.clear_cache(doctype="File")


def ready() -> bool:
	"""Whether the field exists: code can be running before the patch that adds it."""
	return frappe.get_meta("File").has_field(FIELD)


def not_a_thumbnail() -> dict:
	"""Filters that leave thumbnail rows out of a File query."""
	return {FIELD: ("is", "not set")} if ready() else {}


def permission_clause() -> str:
	"""SQL leaving thumbnail rows out of a rep's File list ('' before the patch)."""
	return f"ifnull(`tabFile`.`{FIELD}`, '') = ''" if ready() else ""


# ------------------------------------------------------------------------------
# doc events


def _extension(name: str | None) -> str:
	return os.path.splitext(name or "")[1].lstrip(".").lower()


def _is_local(file_url: str | None) -> bool:
	return bool(file_url) and file_url.startswith(("/files/", "/private/files/"))


def heif_supported() -> bool:
	import importlib.util

	return importlib.util.find_spec("pillow_heif") is not None


def is_candidate(doc) -> bool:
	if doc.get("is_folder") or doc.get(FIELD) or not _is_local(doc.get("file_url")):
		return False
	extension = _extension(doc.get("file_name")) or _extension(doc.get("file_url"))
	return extension in RASTER_EXTENSIONS or extension in HEIF_EXTENSIONS


def guard_marker(doc, method=None) -> None:
	"""File ``before_insert`` and ``validate``: only this module marks a thumbnail.

	``crm_thumbnail_of`` hides a row from a rep's lists and ties it to another
	File's fate -- moved, re-owned and deleted with it -- so a value typed in
	through the REST API is dropped, on insert and on every later save.

	``thumbnail_url`` likewise. File grants write to whoever can write the
	record, the field's read-only flag is not enforced on the server, and frappe
	deletes whatever ``thumbnail_url`` names from disk when the row is deleted:
	a rep who pointed their own upload's at someone else's private file, then
	deleted the upload, deleted that file. Only this module sets it, by
	``db.set_value``, which never comes through here; a save may clear it, not
	set it. A new row starts without one -- ``File.create_attachment_copy``
	copies the original's, and deleting the copy would then delete the
	original's thumbnail file. The copy gets its own.
	"""
	if not ready() or doc.flags.crm_thumbnail:
		return
	if doc.is_new():
		doc.set(FIELD, None)
		doc.thumbnail_url = None
		return
	before = doc.get_doc_before_save() or {}
	if doc.has_value_changed(FIELD):
		doc.set(FIELD, before.get(FIELD))
	if doc.has_value_changed("thumbnail_url") and doc.thumbnail_url:
		doc.thumbnail_url = before.get("thumbnail_url")


def on_file_insert(doc, method=None) -> None:
	"""File ``after_insert``: queue a thumbnail for a new image."""
	if ready() and is_candidate(doc):
		enqueue(doc.name)


def enqueue(name: str, deduplicate: bool = True) -> None:
	"""Queue ``name``'s thumbnail.

	``deduplicate`` is decided when this is called, not at commit, and it skips a
	job that has already *started* as well as one waiting: right for a new
	upload, wrong after a change the running job may have read too early. Those
	pass False, and make_thumbnail's own checks keep the extra run harmless.
	"""
	frappe.enqueue(
		"crm.utils.thumbnails.make_thumbnail",
		queue="short",
		job_id=f"crm_thumbnail::{name}" if deduplicate else None,
		deduplicate=deduplicate,
		# the upload's own transaction has to be committed for the job to find it
		enqueue_after_commit=True,
		name=name,
	)


def on_file_update(doc, method=None) -> None:
	"""File ``on_update``: the thumbnail follows its source.

	Re-pointed at another record (or owner), the thumbnail is re-pointed too, so
	the same people can open both. Made public or private, it is remade on the
	other side: a private photo's thumbnail must not stay public, and the other
	way round would draw a broken image to the people the photo is now open to.
	"""
	if doc.get(FIELD) or not doc.get_doc_before_save() or not ready():
		# a thumbnail, or the on_update that follows an insert
		return
	if doc.has_value_changed("is_private") or doc.has_value_changed("file_url"):
		# Only this row. Another upload of the same bytes is not moved with it:
		# the pinned frappe copies the file instead (handle_is_private_changed,
		# other_refs_exist) and no longer calls update_existing_file_docs, so the
		# other row keeps its privacy and its thumbnail keeps matching it --
		# pinned by test_making_one_copy_private_leaves_the_other_copy_and_its_thumbnail.
		drop_thumbnails(doc.name)
		frappe.db.set_value("File", doc.name, "thumbnail_url", None, update_modified=False)
		if is_candidate(doc):
			enqueue(doc.name, deduplicate=False)
		return
	if any(doc.has_value_changed(f) for f in ("attached_to_doctype", "attached_to_name", "owner")):
		for thumbnail in frappe.get_all("File", filters={FIELD: doc.name}, pluck="name"):
			frappe.db.set_value("File", thumbnail, _access_of(doc), update_modified=False)


def on_file_delete(doc, method=None) -> None:
	"""File ``after_delete``: a source takes its thumbnail with it.

	A thumbnail deleted on its own (by a manager in the desk) is forgotten by its
	source, which then draws the original again.
	"""
	if not ready():
		return
	if doc.get(FIELD):
		frappe.db.set_value(
			"File",
			{"name": doc.get(FIELD), "thumbnail_url": doc.file_url},
			"thumbnail_url",
			None,
			update_modified=False,
		)
		return
	drop_thumbnails(doc.name)


def _access_of(source) -> dict:
	return {
		"attached_to_doctype": source.get("attached_to_doctype"),
		"attached_to_name": source.get("attached_to_name"),
		"owner": source.get("owner"),
	}


def drop_thumbnails(source_name: str) -> None:
	"""Delete ``source_name``'s thumbnail rows now, and their files once committed."""
	rows = frappe.get_all("File", filters={FIELD: source_name}, fields=["name", "file_url"])
	if not rows:
		return
	frappe.db.delete("File", {"name": ("in", [row.name for row in rows])})

	def unlink():
		for row in rows:
			if frappe.db.exists("File", {"file_url": row.file_url}):
				continue
			path = _local_path(row.file_url)
			if path and os.path.isfile(path):
				os.remove(path)

	frappe.db.after_commit.add(unlink)


# ------------------------------------------------------------------------------
# making one


def _local_path(file_url: str | None) -> str | None:
	"""Where ``file_url`` is on this site's disk, or None if it is not under a files folder."""
	if not _is_local(file_url):
		return None
	private = file_url.startswith("/private/files/")
	relative = file_url.split("/files/", 1)[1]
	base = os.path.realpath(frappe.get_site_path("private" if private else "public", "files"))
	path = os.path.realpath(os.path.join(base, relative))
	if os.path.commonpath([base, path]) != base:
		return None
	return path


def render(path: str) -> bytes:
	"""A JPEG fitting BOX of the image at ``path``, with no metadata. Raises Refused.

	Memory is what bounds this, not the file size: a 1 KB lossless WebP can
	declare 50 MP, and decoding is width x height x bands whatever the bytes. So
	the canvas is checked from the header against the format's own cap, a JPEG
	is decoded straight at a fraction of its size (``draft``), anything else is
	brought down to about twice BOX the moment it is decoded -- one band at a
	time, so no second full-size copy is ever made -- and every later step
	(orientation, colour profile, transparency) works on the small image.
	``test_render_stays_within_its_memory_bound`` pins the peak.
	"""
	from PIL import Image

	if os.path.getsize(path) > MAX_SOURCE_BYTES:
		raise Refused(f"larger than {MAX_SOURCE_BYTES} bytes")
	formats = RASTER_FORMATS
	if _extension(path) in HEIF_EXTENSIONS:
		if not heif_supported():
			raise Refused("HEIC/HEIF needs pillow-heif, which is not installed")
		from pillow_heif import register_heif_opener

		register_heif_opener()
		formats = {**RASTER_FORMATS, "HEIF": MAX_PIXELS_DECODED}

	with warnings.catch_warnings():
		# Pillow's own bomb guard warns before it raises: treat the warning as a refusal
		warnings.simplefilter("error", Image.DecompressionBombWarning)
		try:
			# only these parsers ever read the header: not TIFF, EPS, BMP... renamed .png
			# (MPO is not a parser of its own: the JPEG one returns it)
			image = Image.open(path, formats=sorted(set(formats) - {"MPO"}))
		except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
			raise Refused(f"decompression bomb: {e}") from e
		except (OSError, SyntaxError, ValueError) as e:
			raise Refused(f"not an image Pillow reads: {e}") from e
		with image:
			cap = formats.get(image.format)
			if cap is None:
				raise Refused(f"format {image.format} is not thumbnailed")
			if image.format in ("JPEG", "MPO") and _progressive(image):
				cap = min(cap, int(PROGRESSIVE_SAMPLES / _samples_per_pixel(image)))
			width, height = image.size
			if width * height > cap:
				raise Refused(f"{width}x{height} {image.format} is more than {cap} pixels")
			try:
				small, orientation, profile = _decode_small(image)
			except (OSError, SyntaxError, ValueError, EOFError) as e:
				# truncated or corrupt: expected of uploads, not an error to chase
				raise Refused(f"could not be decoded: {e}") from e

	small = _orient(_eight_bit(small), orientation)
	rgb = _flatten(_to_srgb(small, profile))
	rgb.thumbnail(BOX, Image.Resampling.LANCZOS)
	# a new image from the pixels alone: nothing from the source's info rides along
	clean = Image.new("RGB", rgb.size)
	clean.paste(rgb)
	out = io.BytesIO()
	clean.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
	return out.getvalue()


def _progressive(image) -> bool:
	return bool(image.info.get("progressive") or image.info.get("progression"))


def _samples_per_pixel(image) -> float:
	"""How many coefficients a pixel costs: each component, by its sampling factors."""
	layers = getattr(image, "layer", None) or []
	if not layers:
		return float(len(image.getbands()))
	h_max = max(h for _id, h, _v, _q in layers)
	v_max = max(v for _id, _h, v, _q in layers)
	return sum(h * v for _id, h, v, _q in layers) / (h_max * v_max)


#: Rough size to decode down to before the finishing resize.
WORKING = (BOX[0] * 2, BOX[1] * 2)


@contextmanager
def _whole_files_only():
	"""Have Pillow refuse a file that stops short, whatever the process has set.

	``frappe.utils.image`` turns ``LOAD_TRUNCATED_IMAGES`` on for the whole
	process the moment it is imported, and with it a photo cut off in upload
	decodes to its first rows over grey -- a thumbnail of a broken file that
	looks like a photo. Whether that import has happened yet depends on what
	the worker did before, so the answer was not even the same twice.
	"""
	from PIL import ImageFile

	before = ImageFile.LOAD_TRUNCATED_IMAGES
	ImageFile.LOAD_TRUNCATED_IMAGES = False
	try:
		yield
	finally:
		ImageFile.LOAD_TRUNCATED_IMAGES = before


def _decode_small(image):
	"""(``image`` at about WORKING size, its EXIF orientation, its ICC profile)."""
	from PIL import Image

	image.seek(0)  # an animated GIF's first frame
	# a JPEG decodes straight to 1/2, 1/4 or 1/8 of its size: never full-size
	image.draft("RGB", WORKING)
	orientation = image.getexif().get(ORIENTATION_TAG)
	profile = image.info.get("icc_profile")
	with _whole_files_only():
		image.load()

	factor = max(1, min(image.width // WORKING[0], image.height // WORKING[1]))
	if factor == 1:
		return image.copy(), orientation, profile
	if image.mode in ("1", "P") or image.mode.startswith("I"):
		# palette indices cannot be averaged, and reduce() refuses 16- and 32-bit
		# grey; NEAREST keeps the palette, the depth and the memory
		small = image.resize((image.width // factor, image.height // factor), Image.Resampling.NEAREST)
	elif len(image.getbands()) == 1:
		small = image.reduce(factor)
	else:
		# Image.reduce premultiplies RGBA into a full-size copy first; a band at a
		# time costs one byte a pixel instead
		small = Image.merge(
			image.mode, [image.getchannel(i).reduce(factor) for i in range(len(image.getbands()))]
		)
	if "transparency" in image.info:
		small.info["transparency"] = image.info["transparency"]
	return small, orientation, profile


def _eight_bit(image):
	"""16- or 32-bit grey (a PNG's ``I;16``/``I``) as 8-bit ``L``, scaled, not clipped."""
	if not image.mode.startswith("I"):
		return image
	return image.convert("I").point(lambda value: value * (1 / 256)).convert("L")


ORIENTATION_TAG = 0x0112


def _orient(image, orientation):
	"""``image`` turned the way EXIF ``orientation`` says the camera was held."""
	from PIL import Image

	method = {
		2: Image.Transpose.FLIP_LEFT_RIGHT,
		3: Image.Transpose.ROTATE_180,
		4: Image.Transpose.FLIP_TOP_BOTTOM,
		5: Image.Transpose.TRANSPOSE,
		6: Image.Transpose.ROTATE_270,
		7: Image.Transpose.TRANSVERSE,
		8: Image.Transpose.ROTATE_90,
	}.get(orientation)
	return image.transpose(method) if method is not None else image


def _flatten(image):
	"""RGB, with any transparency laid on white (a JPEG has none)."""
	from PIL import Image

	if image.mode in ("RGBA", "LA", "P", "PA") or "transparency" in image.info:
		rgba = image.convert("RGBA")
		background = Image.new("RGB", rgba.size, (255, 255, 255))
		background.paste(rgba, mask=rgba.getchannel("A"))
		return background
	return image.convert("RGB")


def _to_srgb(image, profile: bytes | None):
	"""``image`` from its embedded profile to sRGB, so it can be saved without one.

	Before flattening, so a CMYK or greyscale profile is read against the pixels
	it describes. Alpha is kept for _flatten.
	"""
	if not profile or image.mode not in ("RGB", "RGBA", "CMYK", "L"):
		return image
	try:
		from PIL import ImageCms

		source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
		output = "RGBA" if image.mode == "RGBA" else "RGB"
		return ImageCms.profileToProfile(image, source, ImageCms.createProfile("sRGB"), outputMode=output)
	except Exception:
		# an unreadable profile, or one for other pixels: as they are, still without it
		return image


SOURCE_FIELDS = [
	"name",
	"file_name",
	"file_url",
	"is_private",
	"is_folder",
	"thumbnail_url",
	"owner",
	"attached_to_doctype",
	"attached_to_name",
	FIELD,
]


def make_thumbnail(name: str) -> str | None:
	"""Make ``name``'s thumbnail and point its ``thumbnail_url`` at it. Idempotent.

	The background job. Returns the thumbnail's URL, or None when there is none.

	The render runs unlocked -- it is the slow part -- and everything after it
	under a lock on the source row, re-read: a source deleted or made public or
	private meanwhile gets nothing from this run (the change queued its own), so
	a thumbnail is never filed with privacy its source no longer has. A run that
	finds a thumbnail already made stops there.
	"""
	if not ready():
		return None
	source = frappe.db.get_value("File", name, SOURCE_FIELDS, as_dict=True)
	if not source or not is_candidate(source):
		return None
	existing = frappe.db.get_value("File", {FIELD: name}, "file_url")
	if existing and source.thumbnail_url == existing:
		return existing

	path = _local_path(source.file_url)
	content = failure = None
	try:
		if not path or not os.path.isfile(path):
			raise Refused("not on this site's disk")
		content = render(path)
	except Exception as e:
		failure = e

	locked = frappe.db.get_value("File", name, SOURCE_FIELDS, as_dict=True, for_update=True)
	if not locked:
		return None  # deleted while it was being drawn
	if (locked.file_url, locked.is_private) != (source.file_url, source.is_private):
		# made public or private while it was being drawn (which also moves the
		# file, so a failed render may have failed for that alone). on_file_update
		# has queued a fresh, undeduplicated job for the row as it is now; this
		# one files nothing.
		return None
	if isinstance(failure, Refused):
		frappe.logger("crm.thumbnails").info(f"no thumbnail for File {name}: {failure}")
		return None
	if failure is not None:
		frappe.log_error(
			title=f"Thumbnail failed for File {name}",
			message="".join(traceback.format_exception(failure)),
		)
		return None
	existing = frappe.db.get_value("File", {FIELD: name}, "file_url")
	if existing and locked.thumbnail_url == existing:
		return existing  # another run got there first

	# a half-made one from a run that died, or a thumbnail_url frappe's own
	# make_thumbnail wrote under the public folder: neither is kept
	drop_thumbnails(name)
	try:
		url = _store(locked, content)
	except Exception:
		frappe.log_error(title=f"Thumbnail failed for File {name}")
		url = None
	frappe.db.set_value("File", name, "thumbnail_url", url, update_modified=False)
	return url


def _store(source, content: bytes) -> str:
	"""Write ``content`` beside the source and file it as the source's thumbnail row.

	Under a name nobody else has: a random part, the file created exclusively,
	and no File row already naming it. Nothing on disk is ever overwritten --
	not an upload that happens to be called like a thumbnail, which would then
	serve this photo's thumbnail to whoever uploaded it.
	"""
	# private if either says so: a row whose flag and URL disagree errs closed
	private = 1 if source.is_private or source.file_url.startswith("/private/") else 0
	folder = "private" if private else "public"
	for _attempt in range(5):
		file_name = f"thumb-{source.name}-{_random_part()}.jpg"
		file_url = f"{'/private' if private else ''}/files/{file_name}"
		path = frappe.get_site_path(folder, "files", file_name)
		if frappe.db.exists("File", {"file_url": file_url}):
			continue
		try:
			# built from a docname and a random hash above: never caller input
			with open(path, "xb") as handle:  # nosemgrep: frappe-security-file-traversal
				handle.write(content)
		except FileExistsError:
			continue
		break
	else:
		raise FileExistsError("no free name for the thumbnail")

	def remove():
		if os.path.isfile(path):
			os.remove(path)

	frappe.db.after_rollback.add(remove)
	try:
		return _file_row(source, content, file_name, file_url, private)
	except Exception:
		remove()
		raise


def _random_part() -> str:
	return frappe.generate_hash(length=12)


def _file_row(source, content: bytes, file_name: str, file_url: str, private: int) -> str:
	thumbnail = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"file_url": file_url,
			"is_private": private,
			FIELD: source.name,
		}
	)
	# the bytes are on disk already: no second write, and none of frappe's
	# same-content reuse, which would let two sources share one thumbnail file
	thumbnail.flags.copy_from_existing_file = True
	thumbnail.flags.crm_thumbnail = True
	thumbnail.content_hash = get_content_hash(content)
	thumbnail.file_size = len(content)

	# Runs as whoever queued it. With "only System Managers upload public files"
	# on, a rep's public photo gets no thumbnail (logged; the original is drawn)
	# until the scheduled backfill, which runs as Administrator, reaches it.
	thumbnail.insert(ignore_permissions=True)
	frappe.db.set_value("File", thumbnail.name, _access_of(source), update_modified=False)
	return file_url


# ------------------------------------------------------------------------------
# backfill


def backfill_thumbnails(limit: int = BACKFILL_BATCH, commit: bool = True) -> int:
	"""Thumbnail up to ``limit`` existing images that have none, oldest first.

	Scheduled hourly on the long queue. A cursor (creation, name) remembers how
	far it got, and it is moved past a file -- and committed -- *before* that
	file is rendered: a file that cannot be thumbnailed, or that takes the
	worker down with it, is tried once rather than at the head of every run.
	New uploads are thumbnailed on insert; this is for what was there before.
	Returns how many files it looked at.
	"""
	if not ready():
		return 0
	cursor = frappe.db.get_global(BACKFILL_CURSOR) or ""
	after_creation, _, after_name = cursor.partition("|")

	File = frappe.qb.DocType("File")
	extensions = RASTER_EXTENSIONS | (HEIF_EXTENSIONS if heif_supported() else set())
	is_image = None
	for extension in sorted(extensions):
		like = File.file_name.like(f"%.{extension}")
		is_image = like if is_image is None else is_image | like
	query = (
		frappe.qb.from_(File)
		.select(File.name, File.creation)
		.where(File.is_folder == 0)
		.where((File[FIELD].isnull()) | (File[FIELD] == ""))
		.where((File.thumbnail_url.isnull()) | (File.thumbnail_url == ""))
		.where(File.file_url.like("/files/%") | File.file_url.like("/private/files/%"))
		.where(is_image)
		.orderby(File.creation)
		.orderby(File.name)
		.limit(limit)
	)
	if after_creation:
		query = query.where(
			(File.creation > after_creation) | ((File.creation == after_creation) & (File.name > after_name))
		)

	rows = query.run(as_dict=True)
	for row in rows:
		frappe.db.set_global(BACKFILL_CURSOR, f"{row.creation}|{row.name}")
		if commit:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
		make_thumbnail(row.name)
		if commit:
			# each file its own transaction: a run stopped half way keeps what it made
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return len(rows)
