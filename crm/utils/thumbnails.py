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
  it never opens to *more* people than the source;
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
import warnings

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
#: is decoded, so a small file declaring a huge canvas is refused unread.
MAX_PIXELS = 50_000_000

#: What Pillow is allowed to have opened, whatever the file is called.
RASTER_FORMATS = {"JPEG", "PNG", "WEBP", "GIF", "MPO"}
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
	"""
	if not ready() or doc.flags.crm_thumbnail:
		return
	if doc.is_new():
		doc.set(FIELD, None)
	elif doc.has_value_changed(FIELD):
		doc.set(FIELD, (doc.get_doc_before_save() or {}).get(FIELD))


def forget_copied_thumbnail(doc, method=None) -> None:
	"""File ``before_insert``: a new row does not take over another row's thumbnail.

	``File.create_attachment_copy`` copies every field, ``thumbnail_url`` too, and
	frappe deletes ``thumbnail_url`` from disk when a row goes: deleting the copy
	would take the original's thumbnail with it. The copy gets its own.
	"""
	guard_marker(doc)
	if doc.get(FIELD) or not doc.get("thumbnail_url") or not ready():
		return
	if frappe.db.exists("File", {"file_url": doc.thumbnail_url, FIELD: ("is", "set")}):
		doc.thumbnail_url = None


def on_file_insert(doc, method=None) -> None:
	"""File ``after_insert``: queue a thumbnail for a new image."""
	if ready() and is_candidate(doc):
		enqueue(doc.name)


def enqueue(name: str) -> None:
	frappe.enqueue(
		"crm.utils.thumbnails.make_thumbnail",
		queue="short",
		job_id=f"crm_thumbnail::{name}",
		deduplicate=True,
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
		drop_thumbnails(doc.name)
		if doc.thumbnail_url:
			frappe.db.set_value("File", doc.name, "thumbnail_url", None, update_modified=False)
		if is_candidate(doc):
			enqueue(doc.name)
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
	"""A JPEG fitting BOX of the image at ``path``, with no metadata. Raises Refused."""
	from PIL import Image, ImageOps

	if os.path.getsize(path) > MAX_SOURCE_BYTES:
		raise Refused(f"larger than {MAX_SOURCE_BYTES} bytes")
	allowed = RASTER_FORMATS
	if _extension(path) in HEIF_EXTENSIONS:
		if not heif_supported():
			raise Refused("HEIC/HEIF needs pillow-heif, which is not installed")
		from pillow_heif import register_heif_opener

		register_heif_opener()
		allowed = RASTER_FORMATS | {"HEIF"}

	with warnings.catch_warnings():
		# Pillow's own bomb guard warns before it raises: treat the warning as a refusal
		warnings.simplefilter("error", Image.DecompressionBombWarning)
		try:
			image = Image.open(path)
		except (Image.DecompressionBombError, Image.DecompressionBombWarning) as e:
			raise Refused(f"decompression bomb: {e}") from e
		except (OSError, SyntaxError, ValueError) as e:
			raise Refused(f"not an image Pillow reads: {e}") from e
		with image:
			if image.format not in allowed:
				raise Refused(f"format {image.format} is not thumbnailed")
			width, height = image.size
			if width * height > MAX_PIXELS:
				raise Refused(f"{width}x{height} is more than {MAX_PIXELS} pixels")
			image.seek(0)  # an animated GIF's first frame
			# JPEG decodes straight to a fraction of its size: far less memory and time
			image.draft("RGB", (BOX[0] * 2, BOX[1] * 2))
			profile = image.info.get("icc_profile")
			oriented = ImageOps.exif_transpose(image)
			rgb = _to_srgb(_flatten(oriented), profile)

	rgb.thumbnail(BOX, Image.Resampling.LANCZOS)
	# a new image from the pixels alone: nothing from the source's info rides along
	clean = Image.new("RGB", rgb.size)
	clean.paste(rgb)
	out = io.BytesIO()
	clean.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True)
	return out.getvalue()


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
	"""``image`` converted from its embedded profile to sRGB, so it can be saved without one."""
	if not profile:
		return image
	try:
		from PIL import ImageCms

		source = ImageCms.ImageCmsProfile(io.BytesIO(profile))
		return ImageCms.profileToProfile(image, source, ImageCms.createProfile("sRGB"), outputMode="RGB")
	except Exception:
		# an unreadable profile: the pixels as they are, still without it
		return image


def make_thumbnail(name: str) -> str | None:
	"""Make ``name``'s thumbnail and point its ``thumbnail_url`` at it. Idempotent.

	The background job. Returns the thumbnail's URL, or None when there is none.
	"""
	if not ready():
		return None
	source = frappe.db.get_value(
		"File",
		name,
		[
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
		],
		as_dict=True,
	)
	if not source or not is_candidate(source):
		return None

	existing = frappe.db.get_value("File", {FIELD: name}, "file_url")
	if existing and source.thumbnail_url == existing:
		return existing
	# a half-made one from a run that died, or a thumbnail_url frappe's own
	# make_thumbnail wrote under the public folder: neither is kept
	drop_thumbnails(name)
	if source.thumbnail_url:
		frappe.db.set_value("File", name, "thumbnail_url", None, update_modified=False)

	path = _local_path(source.file_url)
	try:
		if not path or not os.path.isfile(path):
			raise Refused("not on this site's disk")
		content = render(path)
	except Refused as e:
		frappe.logger("crm.thumbnails").info(f"no thumbnail for File {name}: {e}")
		return None
	except Exception:
		frappe.log_error(title=f"Thumbnail failed for File {name}")
		return None

	try:
		url = _store(source, content)
	except Exception:
		frappe.log_error(title=f"Thumbnail failed for File {name}")
		return None
	frappe.db.set_value("File", name, "thumbnail_url", url, update_modified=False)
	return url


def _store(source, content: bytes) -> str:
	"""Write ``content`` beside the source and file it as the source's thumbnail row."""
	# private if either says so: a row whose flag and URL disagree errs closed
	private = 1 if source.is_private or source.file_url.startswith("/private/") else 0
	file_name = f"thumb-{source.name}.jpg"
	folder = "private" if private else "public"
	path = frappe.get_site_path(folder, "files", file_name)
	file_url = f"{'/private' if private else ''}/files/{file_name}"

	# fixed name, built from a docname above: never caller input
	with open(path, "wb") as handle:  # nosemgrep: frappe-security-file-traversal
		handle.write(content)

	def remove():
		if os.path.isfile(path):
			os.remove(path)

	frappe.db.after_rollback.add(remove)
	try:
		return _file_row(source, content, file_name, file_url, private)
	except Exception:
		remove()
		raise


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
	far it got, so an image that cannot be thumbnailed is tried once rather than
	at the head of every batch, and a run cut short resumes where it stopped.
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
		make_thumbnail(row.name)
		frappe.db.set_global(BACKFILL_CURSOR, f"{row.creation}|{row.name}")
		if commit:
			# each file its own transaction: a run stopped half way keeps what it made
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
	return len(rows)
