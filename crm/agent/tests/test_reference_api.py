# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Reference sheets end to end: the pack importer, and ``ask_assistant`` answering
from rows -- the model's answer when every figure is on a row, the rows
themselves when not. The client is stubbed; nothing here contacts a model."""

from __future__ import annotations

import base64
import json
import os
import shutil
import tempfile
from unittest import mock

import frappe
from frappe.tests import IntegrationTestCase
from pypdf import PdfWriter

from crm.agent import api as api_mod
from crm.agent.config import AgentConfig
from crm.agent.errors import AgentUnavailable
from crm.agent.schemas import AssistantAnswer, ReferenceAnswer
from crm.api import reference as reference_api

ENABLED = AgentConfig(enabled=True, base_url="http://x/v1", model="m", timeout=5, max_tokens=64)
REP = "reference.rep@example.com"

# A real 1x1 PNG: the File doctype opens images it stores.
PNG = base64.b64decode(
	"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

ROWS = [
	{
		"page": 1,
		"section": "Flange drilling",
		"label": '150 mm (6") · SABS 1123 1600/3 (1600 kPa)',
		"search": '150 mm 6" flange drilling SABS 1123 1600/3 1600 kPa PN16',
		"bbox": [10, 20, 300, 30],
		"cells": [
			{
				"label": "Flange OD",
				"value": "285.0",
				"unit": "mm",
				"status": "ok",
				"bbox": [100, 20, 110, 30],
			},
			{"label": "PCD (bolt circle diameter)", "value": "240.0", "unit": "mm", "status": "ok"},
			{"label": "Bolt size", "value": "M20", "status": "ok"},
			{
				"label": "Bolt hole diameter (d1)",
				"value": "36.0",
				"unit": "mm",
				"status": "questioned",
				"note": "Errata 8",
			},
		],
	},
	{
		"page": 1,
		"section": "Flange drilling",
		"label": '100 mm (4") · ASME B16.5 Class 150',
		"search": '100 mm 4" flange drilling ASME ANSI class 150 150 lb',
		"bbox": [10, 40, 300, 50],
		"cells": [{"label": "PCD (bolt circle diameter)", "value": "190.5", "unit": "mm", "status": "ok"}],
	},
]


def write_pack(directory: str, rows=None, key: str = "flange-drilling", **sheet) -> str:
	with open(os.path.join(directory, f"{key}.pdf"), "wb") as handle:
		# a real one-page PDF: the File doctype parses every PDF it stores (and
		# refuses one that carries JavaScript)
		writer = PdfWriter()
		writer.add_blank_page(width=595, height=842)
		writer.write(handle)
	with open(os.path.join(directory, f"{key}-1.png"), "wb") as handle:
		handle.write(PNG)
	manifest = {
		"version": 1,
		"sheets": [
			{
				"key": key,
				"title": "Flange Drilling Tables",
				"note": "",
				"file": f"{key}.pdf",
				"pages": [{"page": 1, "width": 595.0, "height": 842.0, "image": f"{key}-1.png"}],
				"entries": ROWS if rows is None else rows,
				**sheet,
			}
		],
	}
	with open(os.path.join(directory, "manifest.json"), "w") as handle:
		json.dump(manifest, handle)
	return directory


def make_sales_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Reference Rep", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class ReferenceApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("reference_api")
		self.addCleanup(frappe.db.rollback, save_point="reference_api")
		self.addCleanup(reference_api.clear_cache)
		frappe.db.delete("CRM Knowledge Article")
		for name in frappe.get_all("CRM Reference Sheet", pluck="name"):
			frappe.delete_doc("CRM Reference Sheet", name, ignore_permissions=True)
		self.pack = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, self.pack, True)
		make_sales_user(REP)

	def load(self, **kwargs) -> dict:
		result = reference_api.import_pack(write_pack(self.pack, **kwargs))
		reference_api.clear_cache()  # the importer moves it after commit; a test never commits
		return result

	def ask(self, question: str, reply=None, side_effect=None, throttled=False) -> tuple[dict, mock.Mock]:
		with (
			mock.patch.object(api_mod, "get_config", return_value=ENABLED),
			mock.patch.object(api_mod, "_throttled", return_value="rate_limited" if throttled else None),
			mock.patch.object(
				api_mod.client, "complete", return_value=reply, side_effect=side_effect
			) as complete,
		):
			return api_mod.ask_assistant(question), complete

	# --- import --------------------------------------------------------------------

	def test_import_writes_the_sheet_its_rows_and_private_files(self):
		result = self.load()
		self.assertEqual(result, {"sheets": [{"key": "flange-drilling", "rows": 2, "questioned": 1}]})

		sheet = frappe.get_doc("CRM Reference Sheet", "flange-drilling")
		self.assertEqual((sheet.entry_count, sheet.questioned_count), (2, 1))
		self.assertTrue(sheet.source_file.startswith("/private/files/"))
		pages = json.loads(sheet.pages)
		self.assertTrue(pages[0]["image"].startswith("/private/files/"))
		files = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "CRM Reference Sheet", "attached_to_name": sheet.name},
			fields=["is_private"],
		)
		self.assertEqual([f.is_private for f in files], [1, 1])
		labels = frappe.get_all(
			"CRM Reference Entry", filters={"sheet": sheet.name}, pluck="label", order_by="position"
		)
		self.assertEqual(labels, [row["label"] for row in ROWS])

	def test_a_second_import_replaces_rows_and_files(self):
		self.load()
		self.load(rows=ROWS[1:])
		self.assertEqual(frappe.db.count("CRM Reference Entry", {"sheet": "flange-drilling"}), 1)
		self.assertEqual(
			frappe.db.count(
				"File", {"attached_to_doctype": "CRM Reference Sheet", "attached_to_name": "flange-drilling"}
			),
			2,
		)
		self.assertEqual(frappe.db.get_value("CRM Reference Sheet", "flange-drilling", "questioned_count"), 0)

	def test_a_failed_reimport_keeps_the_old_files_on_disk(self):
		self.load()
		old = frappe.get_all(
			"File",
			filters={"attached_to_doctype": "CRM Reference Sheet", "attached_to_name": "flange-drilling"},
			fields=["name", "file_url"],
		)
		frappe.db.savepoint("before_reimport")
		with mock.patch.object(reference_api.frappe.db, "bulk_insert", side_effect=RuntimeError("boom")):
			with self.assertRaises(RuntimeError):
				reference_api.import_pack(write_pack(self.pack))
		frappe.db.rollback(save_point="before_reimport")
		for row in old:
			path = frappe.get_site_path("private", "files", os.path.basename(row.file_url))
			self.assertTrue(os.path.isfile(path), row.file_url)
			self.assertTrue(frappe.db.exists("File", row.name))

	def test_a_broken_pack_writes_nothing(self):
		for change in (
			{"file": "../outside.pdf"},
			{"rows": [{**ROWS[0], "cells": [{**ROWS[0]["cells"][0], "status": "maybe"}]}]},
			{"rows": [{**ROWS[0], "page": 2}]},
			{"rows": [{**ROWS[0], "bbox": [1, 2, 3]}]},
			{"file": "a" * 130 + ".pdf"},
		):
			with self.subTest(change=list(change)):
				with self.assertRaises(frappe.ValidationError):
					reference_api.import_pack(write_pack(self.pack, **change))
				self.assertFalse(frappe.db.exists("CRM Reference Sheet", "flange-drilling"))

	# --- answering -----------------------------------------------------------------

	def test_a_supported_answer_comes_back_with_its_row(self):
		self.load()
		reply = ReferenceAnswer(answer="The PCD is 240.0 mm (see R1).", cited_rows=["R1"])
		result, complete = self.ask("PCD of a 6 inch SABS 1600 flange?", reply)

		self.assertEqual(result["status"], "ok")
		self.assertFalse(result["from_sheet"])
		self.assertEqual(result["answer"], "The PCD is 240.0 mm.")
		self.assertEqual([ref["label"] for ref in result["references"]], [ROWS[0]["label"]])
		ref = result["references"][0]
		self.assertEqual(ref["page"], 1)
		self.assertTrue(ref["page_image"].startswith("/private/files/"))
		self.assertEqual(ref["highlight"], [1])

		# the model saw the row, not the withheld value, and answered to the reference schema
		schema, messages = complete.call_args.args[1], complete.call_args.args[2]
		self.assertIs(schema, ReferenceAnswer)
		self.assertIn("[R1]", messages[0]["content"])
		self.assertNotIn("36.0", messages[0]["content"])

	def test_a_questioned_value_never_leaves_the_server(self):
		self.load()
		reply = ReferenceAnswer(answer="The bolt hole is awaiting confirmation.", cited_rows=["R1"])
		result, _ = self.ask("hole diameter 6 inch SABS 1600", reply)
		cell = result["references"][0]["cells"][3]
		self.assertEqual((cell["status"], cell["value"]), ("questioned", ""))
		self.assertNotIn("36.0", json.dumps(result))
		self.assertEqual(cell["note"], "")

	def test_a_questioned_value_in_a_label_never_leaves_the_server(self):
		"""Audit M-20: the label '1/4" = 6 mm' carried the questioned 6 mm out."""
		line = {
			"page": 1,
			"section": "Line sizes",
			"label": '1/4" = 6 mm',
			"search": '1/4" 6 mm line size nominal bore inch to mm',
			"bbox": None,
			"cells": [
				{"label": "Inches", "value": '1/4"', "unit": "", "status": "ok"},
				{"label": "Millimetres", "value": "6", "unit": "mm", "status": "questioned"},
			],
		}
		self.load(rows=[line])
		for reply, side_effect in (
			(ReferenceAnswer(answer='A 1/4" line is 6 mm.', cited_rows=["R1"]), None),
			(ReferenceAnswer(answer='A 1/4" line is 6 mm.'), None),
			(ReferenceAnswer(answer='The 1/4" size is awaiting confirmation.', cited_rows=["R1"]), None),
			(None, AgentUnavailable("down")),
		):
			with self.subTest(reply=reply):
				result, complete = self.ask("what is 1/4 inch in mm?", reply, side_effect=side_effect)
				self.assertEqual(result["status"], "ok")
				self.assertEqual(result["references"][0]["label"], '1/4" = (awaiting confirmation)')
				self.assertNotIn("6 mm", json.dumps(result))
				self.assertNotIn("6 mm", complete.call_args.args[2][0]["content"])

	def test_a_figure_not_on_the_rows_is_replaced_by_the_rows(self):
		self.load()
		for answer in ("The PCD is 241.3 mm.", "The hole is 36.0 mm."):
			with self.subTest(answer=answer):
				result, _ = self.ask("PCD of a 6 inch SABS 1600 flange?", ReferenceAnswer(answer=answer))
				self.assertTrue(result["from_sheet"])
				self.assertTrue(result["answer"].startswith("Here is what the sheet says:"))
				self.assertIn("PCD (bolt circle diameter): 240.0 mm", result["answer"])
				self.assertNotIn("36.0", result["answer"])

	def test_rows_still_answer_when_the_model_cannot(self):
		self.load()
		result, _ = self.ask("PCD 4 inch class 150", side_effect=AgentUnavailable("down"))
		self.assertEqual(result["status"], "ok")
		self.assertTrue(result["from_sheet"])
		self.assertIn("190.5", result["answer"])

		result, complete = self.ask("PCD 4 inch class 150", throttled=True)
		self.assertTrue(result["from_sheet"])
		complete.assert_not_called()

	def test_a_question_no_row_matches_goes_the_article_way(self):
		self.load()
		frappe.get_doc(
			{
				"doctype": "CRM Knowledge Article",
				"title": "Lead times",
				"category": "Test",
				"available_to_assistant": 1,
				"body": "Stock items ship in two days.",
			}
		).insert()
		result, complete = self.ask(
			"what are our lead times?", AssistantAnswer(answer="Two days for stock.", related_articles=[])
		)
		self.assertIs(complete.call_args.args[1], AssistantAnswer)
		self.assertNotIn("references", result)

	def test_a_sheet_switched_off_is_not_quoted(self):
		self.load()
		reference_api.set_available("flange-drilling", 0)
		reference_api.clear_cache()
		result, complete = self.ask("PCD of a 6 inch SABS 1600 flange?")
		self.assertEqual(result, {"status": "empty"})
		complete.assert_not_called()

	def test_a_rep_reads_the_rows_but_cannot_switch_a_sheet(self):
		self.load()
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user(REP)
		entries, _index = reference_api.load_entries()
		self.assertEqual(len(entries), 2)
		self.assertEqual(len(reference_api.list_sheets()["sheets"]), 1)
		with self.assertRaises(frappe.PermissionError):
			reference_api.set_available("flange-drilling", 0)
		# the stored cells hold unconfirmed values: no REST read for a rep
		self.assertFalse(frappe.has_permission("CRM Reference Entry", "read"))
