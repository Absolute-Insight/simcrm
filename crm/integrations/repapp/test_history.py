"""Rep-app history import tests.

The transforms are pure and run without a site. The importer runs against the
test site further down, on small CSVs the tests write themselves: MBP's exports
are the client's data and are never committed.
"""

from __future__ import annotations

import csv
import json
import tempfile
from datetime import date, datetime
from pathlib import Path

import frappe
from frappe.tests import IntegrationTestCase, UnitTestCase

from crm.integrations.repapp import history as h
from crm.tests.test_rep_plan_api import make_sales_user

COLUMNS = [
	"id",
	"company",
	"contactPerson",
	"activityType",
	"date",
	"eventCreatEdit",
	"completedAt",
	"notes",
	"status",
	"Rep Code",
	"history",
]

REP = "history-rep@crmtest.test"
OTHER = "history-other@crmtest.test"
OWNERS = {"032-IO": REP, "007-TB": OTHER}
ORG = "History Import Org"
CONTACT_FIRST, CONTACT_LAST = "Johan", "de Bruin"


def row(**overrides) -> dict:
	base = {
		"id": "abc123",
		"company": ORG,
		"contactPerson": "Johan de Bruin",
		"activityType": "Visit",
		"date": "17/03/2026 09:00",
		"eventCreatEdit": "2026-03-16T10:35:24.663Z",
		"completedAt": "2026-03-17T07:00:00.000Z",
		"notes": "Routine visit\n\n--- Conclusion ---\nNo new enquiries.",
		"status": "Completed",
		"Rep Code": "032-IO",
		"history": "[object Object]",
	}
	base.update(overrides)
	return base


class TransformTest(UnitTestCase):
	def test_when_is_day_first_local_time(self):
		self.assertEqual(h.parse_when("05/01/2026 08:00"), datetime(2026, 1, 5, 8, 0))
		with self.assertRaises(ValueError):
			h.parse_when("2026-01-05")

	def test_kinds_and_statuses_map_to_the_planner(self):
		shaped = h.shape_row(row(), OWNERS)
		self.assertEqual(shaped["user"], REP)
		self.assertEqual(shaped["kind"], "Visit")
		self.assertEqual(shaped["week_start"], date(2026, 3, 16))
		self.assertEqual(
			(shaped["item_status"], shaped["event_status"], shaped["manual_override"]),
			("Done", "Completed", 1),
		)
		unplanned = h.shape_row(row(activityType="Unplanned Meeting", status="Canceled"), OWNERS)
		self.assertEqual(unplanned["kind"], "Visit")
		self.assertEqual((unplanned["item_status"], unplanned["event_status"]), ("Missed", "Cancelled"))
		self.assertEqual(h.shape_row(row(activityType="WhatsApp"), OWNERS)["kind"], "Call")
		self.assertEqual(h.shape_row(row(activityType="E-Mail"), OWNERS)["kind"], "Email")
		scheduled = h.shape_row(row(status="Rescheduled"), OWNERS)
		self.assertEqual(
			(scheduled["item_status"], scheduled["event_status"], scheduled["manual_override"]),
			("Planned", None, 0),
		)

	def test_a_row_that_cannot_be_placed_says_why(self):
		for bad, fragment in (
			(row(**{"Rep Code": "999"}), "rep code"),
			(row(activityType="Fax"), "activity type"),
			(row(status="Pending"), "status"),
			(row(date="March 17"), "date"),
		):
			with self.assertRaises(ValueError) as caught:
				h.shape_row(bad, OWNERS)
			self.assertIn(fragment, str(caught.exception))

	def test_contact_whitespace_is_folded(self):
		self.assertEqual(h.shape_row(row(contactPerson="Jaco  Peyper "), OWNERS)["contact"], "Jaco Peyper")

	def test_the_item_note_is_the_conclusion_on_one_line(self):
		short = "Quote sent"
		self.assertEqual(h.short_note(short), short)
		self.assertEqual(
			h.short_note("Routine visit\n\n--- Conclusion ---\nAttie had no new enquiries for me."),
			"Attie had no new enquiries for me.",
		)
		self.assertEqual(h.short_note("Plan only\n\n--- Conclusion ---\n"), "Plan only")
		self.assertEqual(h.short_note("line one\nline  two"), "line one line two")
		no_marker = "x" * 200
		self.assertEqual(len(h.short_note(no_marker)), h.NOTE_LIMIT)
		self.assertTrue(h.short_note(no_marker).endswith("…"))

	def test_company_suggestions_match_on_normalised_names_and_offer_candidates(self):
		orgs = [
			"Esizayo Construction (Pty) Ltd",
			"Harmony Moab Khotsong Operations (Pty) Ltd",
			"MBP Internal",
		]
		out = h.suggest_company_map(
			["Esizayo Construction (PTY) LTD", "Harmony Moab Khotsong Operations ([Pty)", "Saffy#"], orgs
		)
		self.assertEqual(out["Esizayo Construction (PTY) LTD"], {"match": orgs[0], "candidates": []})
		self.assertIsNone(out["Harmony Moab Khotsong Operations ([Pty)"]["match"])
		self.assertEqual(out["Harmony Moab Khotsong Operations ([Pty)"]["candidates"][0], orgs[1])
		self.assertEqual(out["Saffy#"], {"match": None, "candidates": []})


class ImportTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		make_sales_user(REP, "History Rep")
		make_sales_user(OTHER, "History Other")
		self.addCleanup(frappe.set_user, frappe.session.user)
		if not frappe.db.exists("CRM Organization", ORG):
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": ORG}).insert(
				ignore_permissions=True
			)
		if not frappe.db.exists(
			"Contact", {"first_name": CONTACT_FIRST, "last_name": CONTACT_LAST, "company_name": ORG}
		):
			frappe.get_doc(
				{
					"doctype": "Contact",
					"first_name": CONTACT_FIRST,
					"last_name": CONTACT_LAST,
					"company_name": ORG,
				}
			).insert(ignore_permissions=True)
		self.clear_rows()
		self.addCleanup(self.clear_rows)
		self.tmp = tempfile.TemporaryDirectory()
		self.addCleanup(self.tmp.cleanup)
		self.dir = Path(self.tmp.name)

	def clear_rows(self):
		frappe.set_user("Administrator")
		for name in frappe.get_all("CRM Rep Plan", filters={"user": ("in", (REP, OTHER))}, pluck="name"):
			frappe.delete_doc("CRM Rep Plan", name, force=True, ignore_permissions=True)
		for name in frappe.get_all("Event", filters={"owner": ("in", (REP, OTHER))}, pluck="name"):
			frappe.delete_doc("Event", name, force=True, ignore_permissions=True)

	def write(self, rows: list[dict], name: str = "report_Test_Rep_2026-09-22.csv") -> None:
		with (self.dir / name).open("w", newline="", encoding="utf-8") as fh:
			writer = csv.DictWriter(fh, fieldnames=COLUMNS)
			writer.writeheader()
			writer.writerows(rows)

	def run_import(self, **kwargs) -> dict:
		return h.import_history(self.dir, OWNERS, kwargs.pop("company_map", {ORG: ORG}), **kwargs)

	def items_of(self, user: str) -> list:
		return frappe.get_all(
			"CRM Rep Plan Item",
			filters={
				"parenttype": "CRM Rep Plan",
				"parent": ("in", frappe.get_all("CRM Rep Plan", {"user": user}, pluck="name") or [""]),
			},
			fields=[
				"name",
				"activity_type",
				"planned_date",
				"status",
				"manual_override",
				"fulfilled_by_doctype",
				"fulfilled_by",
				"note",
			],
			order_by="planned_date asc, idx asc",
		)

	def test_a_completed_visit_becomes_a_done_item_fulfilled_by_the_reps_event(self):
		self.write([row()])
		summary = self.run_import()
		self.assertEqual((summary["imported"], summary["plans"], summary["events"]), (1, 1, 1))
		self.assertEqual(summary["contacts_matched"], 1)
		items = self.items_of(REP)
		self.assertEqual(len(items), 1)
		item = items[0]
		self.assertEqual(
			(item.activity_type, str(item.planned_date), item.status, item.manual_override),
			("Visit", "2026-03-17", "Done", 1),
		)
		self.assertEqual(item.note, "No new enquiries.")
		self.assertEqual(item.fulfilled_by_doctype, "Event")
		event = frappe.get_doc("Event", item.fulfilled_by)
		self.assertEqual(
			(event.owner, event.event_category, event.status, event.subject),
			(REP, "Visit", "Completed", f"Visit: {ORG}"),
		)
		self.assertEqual(str(event.starts_on), "2026-03-17 09:00:00")
		self.assertEqual(
			{(p.reference_doctype, p.reference_docname) for p in event.event_participants},
			{
				("CRM Organization", ORG),
				("Contact", frappe.db.get_value("Contact", {"company_name": ORG}, "name")),
			},
		)
		self.assertIn("No new enquiries.", event.description)
		self.assertEqual(frappe.db.get_value("CRM Rep Plan", {"user": REP}, "week_start"), date(2026, 3, 16))

	def test_a_cancelled_visit_is_missed_with_a_cancelled_event_and_no_fulfilment(self):
		self.write([row(status="Canceled", notes="Office locked")])
		self.run_import()
		item = self.items_of(REP)[0]
		self.assertEqual((item.status, item.manual_override, item.fulfilled_by), ("Missed", 1, None))
		event = frappe.get_all("Event", filters={"owner": REP}, fields=["status", "event_category"])
		self.assertEqual([(e.status, e.event_category) for e in event], [("Cancelled", "Visit")])

	def test_a_scheduled_row_is_a_live_planned_item_the_matcher_owns(self):
		self.write([row(status="Scheduled", completedAt="", date="22/09/2026 09:00")])
		summary = self.run_import()
		item = self.items_of(REP)[0]
		self.assertEqual((item.status, item.manual_override, item.fulfilled_by), ("Planned", 0, None))
		self.assertEqual(summary["events"], 0)

	def test_calls_and_emails_are_done_on_the_reps_word_without_a_record(self):
		self.write(
			[
				row(id="c1", activityType="Phone Call", notes="Rang about the quote"),
				row(id="e1", activityType="E-Mail"),
			]
		)
		summary = self.run_import()
		self.assertEqual(summary["events"], 0)
		self.assertEqual(
			{(i.activity_type, i.status, i.fulfilled_by) for i in self.items_of(REP)},
			{("Call", "Done", None), ("Email", "Done", None)},
		)

	def test_an_unmapped_company_is_still_imported_and_reported(self):
		self.write([row(company="Impala - Shaft 14", contactPerson="Nobody")])
		summary = self.run_import(company_map={})
		self.assertEqual(summary["imported"], 1)
		self.assertEqual(summary["unmapped_companies"], {"Impala - Shaft 14": 1})
		self.assertEqual(summary["contacts_matched"], 0)
		event = frappe.get_doc("Event", self.items_of(REP)[0].fulfilled_by)
		self.assertEqual(event.subject, "Visit: Impala - Shaft 14")
		self.assertEqual(event.event_participants, [])

	def test_rows_group_into_one_plan_per_rep_week_and_reps_do_not_mix(self):
		self.write(
			[
				row(id="a", date="16/03/2026 09:00"),
				row(id="b", date="19/03/2026 10:00", activityType="Phone Call"),
				row(id="c", date="24/03/2026 09:00"),
				row(id="d", date="17/03/2026 09:00", **{"Rep Code": "007-TB"}),
			]
		)
		summary = self.run_import()
		self.assertEqual(summary["plans"], 3)
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 2)
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": OTHER}), 1)
		self.assertEqual(summary["by_rep"][REP], {"Visit": {"Done": 2}, "Call": {"Done": 1}})
		self.assertEqual(frappe.db.get_value("Event", {"owner": OTHER}, "owner"), OTHER)

	def test_a_rerun_lands_nothing_twice(self):
		self.write([row(id="a"), row(id="b", date="18/03/2026 09:00")])
		first = self.run_import()
		manifest = json.loads((self.dir / h.MANIFEST_NAME).read_text())["rows"]
		self.assertEqual(set(manifest), {"a", "b"})
		second = self.run_import()
		self.assertEqual((first["imported"], second["imported"], second["skipped"]), (2, 0, 2))
		self.assertEqual(len(self.items_of(REP)), 2)
		self.assertEqual(frappe.db.count("Event", {"owner": REP}), 2)

	def test_a_new_row_for_an_existing_week_is_appended_not_duplicated(self):
		self.write([row(id="a")])
		self.run_import()
		self.write([row(id="a"), row(id="b", date="18/03/2026 09:00")])
		summary = self.run_import()
		self.assertEqual((summary["imported"], summary["skipped"]), (1, 1))
		self.assertEqual(len(self.items_of(REP)), 2)
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 1)

	def test_a_dry_run_reports_and_writes_nothing(self):
		self.write([row(id="a"), row(id="bad", **{"Rep Code": "999"})])
		summary = self.run_import(dry_run=True)
		self.assertTrue(summary["dry_run"])
		self.assertEqual(summary["imported"], 1)
		self.assertEqual([r["reason"] for r in summary["rejected"]], ["rep code '999' is not in owners"])
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 0)
		self.assertEqual(frappe.db.count("Event", {"owner": REP}), 0)
		self.assertFalse((self.dir / h.MANIFEST_NAME).exists())

	def test_an_unknown_owner_or_organization_stops_the_run_before_it_writes(self):
		self.write([row()])
		with self.assertRaises(ValueError):
			h.import_history(self.dir, {"032-IO": "nobody@crmtest.test"}, {})
		with self.assertRaises(ValueError):
			h.import_history(self.dir, OWNERS, {ORG: "No Such Org"})
		self.assertEqual(frappe.db.count("CRM Rep Plan", {"user": REP}), 0)

	def test_build_company_map_drafts_matches_and_candidates(self):
		self.write([row(company="history import org"), row(id="b", company="Histori Import Org")])
		summary = h.build_company_map(self.dir)
		self.assertEqual((summary["companies"], summary["matched"], summary["unmatched"]), (2, 1, 1))
		drafted = json.loads((self.dir / h.COMPANY_MAP_NAME).read_text())
		self.assertEqual(drafted["history import org"], ORG)
		self.assertIsNone(drafted["Histori Import Org"])
		candidates = json.loads((self.dir / h.CANDIDATES_NAME).read_text())
		self.assertIn(ORG, candidates["Histori Import Org"])
		with self.assertRaises(ValueError):
			h.build_company_map(self.dir)
