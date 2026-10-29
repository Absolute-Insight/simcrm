# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Reference sheets: the company's PDFs the Assistant answers from row by row.

A sheet arrives as a **pack** built offline for its layout (rows, labelled
cells, their boxes, page images and the PDF itself) and is loaded with
:func:`import_pack` from ``bench execute`` -- there is no upload endpoint, so
no request can write rows. Reads follow the doctypes' own permission (any CRM
user, like knowledge articles); the availability switch is System Manager
only, checked here so the gate is visible where a reviewer reads it.

The Assistant reads every available row on every question, so the rows and
their search index are kept per worker process, keyed by a version stamp in
the site cache that every write moves (:func:`clear_cache`).
"""

from __future__ import annotations

import json
import os
import re

import frappe
from frappe import _

from crm.agent import reference

SHEET = "CRM Reference Sheet"
ENTRY = "CRM Reference Entry"

VERSION_KEY = "crm_reference_version"

# Bounds on a pack. A sheet is a few pages and a few hundred rows; these are
# far past that and exist so a malformed pack fails loudly, not slowly.
MAX_SHEETS = 50
MAX_PAGES = 50
MAX_ENTRIES = 5000
MAX_CELLS = 40
MAX_TEXT = 2000
MAX_FILE_BYTES = 25 * 1024 * 1024
DATA_FIELD_MAX = 140

STATUSES = {"ok", reference.QUESTIONED}
_FILE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")
IMAGE_TYPES = (".png", ".jpg", ".jpeg")

ENTRY_FIELDS = ["name", "sheet", "page", "position", "label", "section", "search", "cells", "bbox"]

# site -> (version, entries, index). Rebuilt when the site's version moves.
_LOADED: dict[str, tuple[str, list[dict], list]] = {}


def clear_cache() -> None:
	"""Move the version stamp: every worker reloads the rows on its next question."""
	frappe.cache().set_value(VERSION_KEY, frappe.generate_hash(length=12))


def clear_cache_after_commit() -> None:
	"""Move the stamp once this transaction is committed. Moved before, a
	worker could reload the old rows between the move and the commit and keep
	them until the next write."""
	frappe.db.after_commit.add(clear_cache)


def _version() -> str:
	stamp = frappe.cache().get_value(VERSION_KEY)
	if not stamp:
		stamp = frappe.generate_hash(length=12)
		frappe.cache().set_value(VERSION_KEY, stamp)
	return stamp


def load_entries() -> tuple[list[dict], list]:
	"""Every row of every available sheet, with the search index beside them.

	Returns ``([], [])`` to a user who may not read the sheets. The rows carry
	no per-user scoping -- every reader sees every row -- so one load serves
	every user once the sheet permission has been checked.

	Entries themselves are System Manager only: their stored cells hold the
	unconfirmed values, and a rep reading them over ``/api/resource`` would
	get what this module strips. Reps reach rows only through here.
	"""
	if not frappe.has_permission(SHEET, "read"):
		return [], []
	site = frappe.local.site
	version = _version()
	cached = _LOADED.get(site)
	if cached and cached[0] == version:
		return cached[1], cached[2]
	entries = _read_entries()
	index = reference.build_index(entries)
	_LOADED[site] = (version, entries, index)
	return entries, index


def _read_entries() -> list[dict]:
	sheets = {
		row.name: row
		for row in frappe.get_all(
			SHEET,
			filters={"available_to_assistant": 1},
			fields=["name", "title", "source_file", "pages"],
			limit=MAX_SHEETS,
		)
	}
	if not sheets:
		return []
	rows = frappe.get_all(
		ENTRY,
		filters={"sheet": ["in", list(sheets)]},
		fields=ENTRY_FIELDS,
		order_by="sheet asc, position asc",
		limit=MAX_ENTRIES * len(sheets),
	)
	pages = {name: {page["page"]: page for page in _json(sheet.pages, [])} for name, sheet in sheets.items()}
	entries = []
	for row in rows:
		sheet = sheets[row.sheet]
		page = pages[row.sheet].get(row.page) or {}
		entries.append(
			{
				"name": row.name,
				"sheet": row.sheet,
				"sheet_title": sheet.title,
				"file_url": sheet.source_file or "",
				"page": row.page,
				"page_image": page.get("image", ""),
				"page_width": page.get("width"),
				"page_height": page.get("height"),
				"label": row.label or "",
				"section": row.section or "",
				"search": row.search or "",
				"cells": _json(row.cells, []),
				"bbox": _json(row.bbox, None),
			}
		)
	return entries


def _json(value, default):
	if value in (None, ""):
		return default
	if isinstance(value, list | dict):
		return value
	try:
		return json.loads(value)
	except ValueError:
		return default


def entry_payload(entry: dict, answer: str = "", show_all: bool = False) -> dict:
	"""A row as it leaves the server: questioned values withheld, quoted cells marked."""
	cells = entry.get("cells") or []
	return {
		"name": entry["name"],
		"sheet": entry["sheet"],
		"sheet_title": entry["sheet_title"],
		"file_url": entry.get("file_url", ""),
		"page": entry["page"],
		"page_image": entry.get("page_image", ""),
		"page_width": entry.get("page_width"),
		"page_height": entry.get("page_height"),
		"label": entry["label"],
		"section": entry["section"],
		"bbox": entry.get("bbox"),
		"cells": [reference.public_cell(cell) for cell in cells],
		"highlight": list(range(len(cells))) if show_all else reference.highlight(answer, entry),
	}


# --- settings -----------------------------------------------------------------------


@frappe.whitelist()
def list_sheets() -> dict:
	frappe.has_permission(SHEET, "read", throw=True)
	rows = frappe.get_list(
		SHEET,
		fields=[
			"name",
			"title",
			"note",
			"available_to_assistant",
			"entry_count",
			"questioned_count",
			"source_file",
			"pages",
			"modified",
		],
		order_by="title asc",
		limit=MAX_SHEETS,
	)
	for row in rows:
		row["pages"] = _json(row.get("pages"), [])
	return {"sheets": rows}


@frappe.whitelist()
def set_available(name: str, available: int | str | bool) -> dict:
	frappe.only_for("System Manager", True)
	sheet = frappe.get_doc(SHEET, name)
	sheet.available_to_assistant = 1 if frappe.utils.cint(available) else 0
	sheet.save()
	return {"name": sheet.name, "available_to_assistant": sheet.available_to_assistant}


# --- import -------------------------------------------------------------------------


def import_pack(path: str) -> dict:
	"""Load a pack directory into the site: ``bench --site S execute
	crm.api.reference.import_pack --kwargs '{"path": "/tmp/pack"}'``.

	Not whitelisted: a pack is files on the server, put there by whoever runs
	the bench. Each sheet replaces the sheet with the same key -- its rows,
	PDF and page images -- in one transaction, so a corrected pack is simply
	imported again. The whole pack is validated before anything is written.
	"""
	root = os.path.realpath(path)
	# not whitelisted: the path comes from whoever runs bench execute
	manifest_path = os.path.join(root, "manifest.json")
	with open(manifest_path, encoding="utf-8") as handle:  # nosemgrep: frappe-security-file-traversal
		manifest = json.load(handle)
	sheets = validate_manifest(manifest)
	files = {name: _read_file(root, name) for sheet in sheets for name in _files_of(sheet)}

	summary = [_import_sheet(sheet, files) for sheet in sheets]
	# bench execute commits when the function returns
	clear_cache_after_commit()
	return {"sheets": summary}


def _files_of(sheet: dict) -> list[str]:
	return [sheet["file"]] + [page["image"] for page in sheet["pages"]]


def _read_file(root: str, name: str) -> bytes:
	full = os.path.realpath(os.path.join(root, name))
	if os.path.dirname(full) != root:
		frappe.throw(_("Pack file {0} is outside the pack.").format(name))
	if os.path.getsize(full) > MAX_FILE_BYTES:
		frappe.throw(_("Pack file {0} is too large.").format(name))
	# contained above: the real path must sit directly in the pack directory
	with open(full, "rb") as handle:  # nosemgrep: frappe-security-file-traversal
		return handle.read()


def _drop_old_files(key: str) -> None:
	"""Remove a sheet's old File rows now, and their files on disk only once committed.

	``delete_doc("File")`` unlinks the file from disk at once, while the rows
	come back on rollback: a re-import that failed half way left a sheet whose
	rows pointed at images that were gone. Rows go in the transaction; disk
	files go after the commit, and only those no File row still names (a new
	upload with the same content reuses the old file's path).
	"""
	old = frappe.get_all(
		"File",
		filters={"attached_to_doctype": SHEET, "attached_to_name": key},
		fields=["name", "file_url", "is_private"],
	)
	if not old:
		return
	frappe.db.delete("File", {"name": ["in", [row.name for row in old]]})

	def unlink():
		for row in old:
			if frappe.db.exists("File", {"file_url": row.file_url}):
				continue
			path = frappe.get_site_path(
				"private" if row.is_private else "public", "files", os.path.basename(row.file_url or "")
			)
			if os.path.isfile(path):
				os.remove(path)

	frappe.db.after_commit.add(unlink)


def _import_sheet(sheet: dict, files: dict[str, bytes]) -> dict:
	key = sheet["key"]
	if frappe.db.exists(SHEET, key):
		doc = frappe.get_doc(SHEET, key)
		_drop_old_files(key)
		frappe.db.delete(ENTRY, {"sheet": key})
	else:
		doc = frappe.get_doc({"doctype": SHEET, "sheet_key": key, "title": sheet["title"]})
		doc.insert(ignore_permissions=True)

	def attach(name: str, field: str | None = None) -> str:
		return (
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": stored_file_name(key, name),
					"attached_to_doctype": SHEET,
					"attached_to_name": key,
					# named for the Attach field, or saving the sheet attaches a copy
					"attached_to_field": field,
					"is_private": 1,
					"content": files[name],
				}
			)
			.insert(ignore_permissions=True)
			.file_url
		)

	pages = [{**page, "image": attach(page["image"])} for page in sheet["pages"]]
	questioned = sum(
		1 for entry in sheet["entries"] for cell in entry["cells"] if cell["status"] == reference.QUESTIONED
	)
	doc.update(
		{
			"title": sheet["title"],
			"note": sheet.get("note") or "",
			"source_file": attach(sheet["file"], "source_file"),
			"pages": json.dumps(pages),
			"entry_count": len(sheet["entries"]),
			"questioned_count": questioned,
		}
	)
	doc.save(ignore_permissions=True)

	now = frappe.utils.now()
	user = frappe.session.user
	values = [
		(
			frappe.generate_hash(length=12),
			now,
			now,
			user,
			user,
			key,
			entry["page"],
			position,
			entry["label"],
			entry["section"],
			entry["search"],
			json.dumps(entry["cells"], ensure_ascii=False),
			json.dumps(entry["bbox"]) if entry["bbox"] else None,
		)
		for position, entry in enumerate(sheet["entries"])
	]
	frappe.db.bulk_insert(
		ENTRY,
		# a row can carry 40 cells of 2,000 characters; keep a statement well
		# under max_allowed_packet
		chunk_size=200,
		fields=[
			"name",
			"creation",
			"modified",
			"owner",
			"modified_by",
			"sheet",
			"page",
			"position",
			"label",
			"section",
			"search",
			"cells",
			"bbox",
		],
		values=values,
	)
	return {"key": key, "rows": len(values), "questioned": questioned}


# --- validation ---------------------------------------------------------------------


def _fail(message: str):
	frappe.throw(_("Invalid reference pack: {0}").format(message))


def _text(value, where: str, limit: int = MAX_TEXT, required: bool = False) -> str:
	if value is None:
		value = ""
	if not isinstance(value, str | int | float) or isinstance(value, bool):
		_fail(f"{where} is not text")
	value = str(value).strip()
	if required and not value:
		_fail(f"{where} is empty")
	if len(value) > limit:
		_fail(f"{where} is longer than {limit} characters")
	return value


def _box(value, where: str):
	if value is None:
		return None
	if (
		not isinstance(value, list)
		or len(value) != 4
		or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in value)
	):
		_fail(f"{where} is not a box of four numbers")
	x0, top, x1, bottom = (float(v) for v in value)
	if x1 < x0 or bottom < top:
		_fail(f"{where} is inside out")
	return [round(v, 2) for v in (x0, top, x1, bottom)]


def _file_name(value, where: str, extensions: tuple[str, ...]) -> str:
	if not isinstance(value, str) or not _FILE_NAME.match(value) or ".." in value:
		_fail(f"{where} is not a bare file name")
	if not value.lower().endswith(extensions):
		_fail(f"{where} must end in {' or '.join(extensions)}")
	return value


def stored_file_name(key: str, name: str) -> str:
	"""The File name a pack file is stored under: prefixed with its sheet key."""
	return name if name.startswith(key) else f"{key}-{name}"


def _stored_name(key: str, name: str, where: str) -> str:
	# File.file_name is a 140-character Data field; caught here, not half way
	# through an import
	if len(stored_file_name(key, name)) > DATA_FIELD_MAX:
		_fail(f"{where} file name is too long once prefixed with the sheet key")
	return name


def validate_manifest(manifest) -> list[dict]:
	"""The pack's sheets, normalised; throws on the first thing that is wrong.

	Pure of the site: reads nothing and writes nothing, so a broken pack never
	half-imports.
	"""
	if not isinstance(manifest, dict) or manifest.get("version") != 1:
		_fail("manifest version must be 1")
	raw_sheets = manifest.get("sheets")
	if not isinstance(raw_sheets, list) or not raw_sheets or len(raw_sheets) > MAX_SHEETS:
		_fail(f"sheets must be a list of 1 to {MAX_SHEETS}")
	sheets, keys = [], set()
	for s, raw in enumerate(raw_sheets):
		where = f"sheet {s + 1}"
		if not isinstance(raw, dict):
			_fail(f"{where} is not an object")
		key = raw.get("key")
		if not isinstance(key, str) or not _KEY.match(key) or key in keys:
			_fail(f"{where} key must be unique, lower-case letters, digits and dashes")
		keys.add(key)
		pages_raw = raw.get("pages")
		if not isinstance(pages_raw, list) or not pages_raw or len(pages_raw) > MAX_PAGES:
			_fail(f"{where} pages must be a list of 1 to {MAX_PAGES}")
		pages = []
		for p, page in enumerate(pages_raw):
			pw = f"{where} page {p + 1}"
			if not isinstance(page, dict) or page.get("page") != p + 1:
				_fail(f"{pw} must be numbered {p + 1}")
			width, height = page.get("width"), page.get("height")
			if not all(
				isinstance(v, int | float) and not isinstance(v, bool) and v > 0 for v in (width, height)
			):
				_fail(f"{pw} needs a positive width and height")
			pages.append(
				{
					"page": p + 1,
					"width": float(width),
					"height": float(height),
					"image": _stored_name(key, _file_name(page.get("image"), f"{pw} image", IMAGE_TYPES), pw),
				}
			)
		entries_raw = raw.get("entries")
		if not isinstance(entries_raw, list) or len(entries_raw) > MAX_ENTRIES:
			_fail(f"{where} entries must be a list of at most {MAX_ENTRIES}")
		entries = []
		for e, entry in enumerate(entries_raw):
			ew = f"{where} row {e + 1}"
			if not isinstance(entry, dict):
				_fail(f"{ew} is not an object")
			page_no = entry.get("page")
			if not isinstance(page_no, int) or isinstance(page_no, bool) or not 1 <= page_no <= len(pages):
				_fail(f"{ew} page is not one of the sheet's pages")
			cells_raw = entry.get("cells")
			if not isinstance(cells_raw, list) or not cells_raw or len(cells_raw) > MAX_CELLS:
				_fail(f"{ew} cells must be a list of 1 to {MAX_CELLS}")
			cells = []
			for c, cell in enumerate(cells_raw):
				cw = f"{ew} cell {c + 1}"
				if not isinstance(cell, dict):
					_fail(f"{cw} is not an object")
				status = cell.get("status", "ok")
				if status not in STATUSES:
					_fail(f"{cw} status must be one of {sorted(STATUSES)}")
				normalised = {
					"label": _text(cell.get("label"), f"{cw} label", DATA_FIELD_MAX, required=True),
					"value": _text(cell.get("value"), f"{cw} value"),
					"unit": _text(cell.get("unit"), f"{cw} unit", 20),
					"status": status,
				}
				if box := _box(cell.get("bbox"), f"{cw} box"):
					normalised["bbox"] = box
				if note := _text(cell.get("note"), f"{cw} note", 500):
					normalised["note"] = note
				cells.append(normalised)
			entries.append(
				{
					"page": page_no,
					"label": _text(entry.get("label"), f"{ew} label", DATA_FIELD_MAX, required=True),
					"section": _text(entry.get("section"), f"{ew} section", DATA_FIELD_MAX),
					"search": _text(entry.get("search"), f"{ew} search"),
					"bbox": _box(entry.get("bbox"), f"{ew} box"),
					"cells": cells,
				}
			)
		sheets.append(
			{
				"key": key,
				"title": _text(raw.get("title"), f"{where} title", DATA_FIELD_MAX, required=True),
				"note": _text(raw.get("note"), f"{where} note", 500),
				"file": _stored_name(key, _file_name(raw.get("file"), f"{where} file", (".pdf",)), where),
				"pages": pages,
				"entries": entries,
			}
		)
	return sheets
