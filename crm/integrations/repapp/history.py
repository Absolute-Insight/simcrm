"""Import the old rep app's activity history.

The app MBP's reps used before Vectora was a Firestore-backed visit planner. Its
per-rep export (``report_<First>_<Last>_<date>.csv``) is one row per activity:
what kind, for which company and person, when, the closing note, and whether it
was completed, cancelled or is still scheduled. In MBP's vocabulary every one of
these is a "call", which is why the file Bianca sent is called call information;
only the ``Phone Call`` rows are telephone calls.

Each row becomes a **plan item** in the rep's week, so the Planner shows the
history the reps already have and the plan-vs-actual rollups start from real
numbers rather than a blank January. A completed or cancelled visit also gets
the calendar **Event** (category Visit, the organization as a participant) that
the matcher would have looked for and that the client-reliability and
cancellation reports count. Calls and emails are recorded as done on the rep's
word, exactly as ``mark_fulfilled`` allows, because the old app kept no phone
number or message to hang a Call Log or Communication on.

Every imported item is ``manual_override`` so the daily matcher never revisits
it; a row still *scheduled* is imported as a live Planned item instead, so the
visits a rep already has in the diary for next week carry across and get
matched like anything they plan from now on.

The old app's company names are free text ("Impala - Shaft 14", "Harmony
Avgold Limited") and only a third match an Acumatica customer name exactly, so
the importer takes a reviewed ``company-map.json``; ``build_company_map`` drafts
it from the site's organizations. A row whose company is unmapped is still
imported -- the event names the company in its subject -- and reported, so
nothing Bianca sent is dropped.

Re-running is safe: a manifest beside the CSVs records which Firestore ids have
landed, and a dry run does all the work inside the transaction and rolls it
back, so its report is real.
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from difflib import get_close_matches
from pathlib import Path
from zoneinfo import ZoneInfo

import frappe

from crm.rep_planning import week_of

# plans written between commits; a rep's whole year is ~40 plans, so this is a
# few reps per transaction
COMMIT_EVERY = 25
MANIFEST_NAME = "history-manifest.json"
COMPANY_MAP_NAME = "company-map.json"
CANDIDATES_NAME = "company-map-candidates.json"
REPORT_GLOB = "report_*.csv"
# CRM Rep Plan Item.note is a Data field
NOTE_LIMIT = 140
VISIT_LENGTH = timedelta(hours=1)

# the old app's activity type -> the planner's
PLAN_KIND = {
	"Visit": "Visit",
	"Unplanned Meeting": "Visit",
	"Phone Call": "Call",
	"WhatsApp": "Call",
	"E-Mail": "Email",
}

# the old app's status -> (plan item status, Event status or None, manual_override)
STATUS = {
	"Completed": ("Done", "Completed", 1),
	"Canceled": ("Missed", "Cancelled", 1),
	"Scheduled": ("Planned", None, 0),
	"Rescheduled": ("Planned", None, 0),
}

# the closing note the old app appended when a rep completed an activity
CONCLUSION_MARKER = "--- Conclusion ---"
# the wall-clock zone the old app's ``date`` column is written in
SOURCE_TIMEZONE = "Africa/Johannesburg"


# --- pure transforms ---------------------------------------------------------


def parse_when(text: str) -> datetime:
	"""``22/09/2026 09:00`` in the site's local time. The export's other two
	timestamps are UTC ISO strings and are not used: ``date`` is the one the rep
	chose and the one the old app displayed."""
	return datetime.strptime(text.strip(), "%d/%m/%Y %H:%M")


def normalise_name(text: str) -> str:
	"""Case, punctuation and spacing folded away so ``Esizayo Contruction (PTY) LTD``
	and ``Esizayo Construction (Pty) Ltd`` are one typo apart rather than four."""
	return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def read_reports(directory) -> list[dict]:
	"""Every ``report_*.csv`` in ``directory``, each row tagged with its file."""
	rows: list[dict] = []
	for path in sorted(Path(directory).glob(REPORT_GLOB)):
		with path.open(newline="", encoding="utf-8-sig") as fh:
			for row in csv.DictReader(fh):
				row["_file"] = path.name
				rows.append(row)
	return rows


def to_site_time(when: datetime, source_tz: str, site_tz: str) -> datetime:
	"""The export's wall-clock time as the site's wall-clock time. A no-op on the
	site the export was made for; on any other (a rehearsal stack still on
	frappe's +05:30 default) every timestamp would otherwise land hours adrift
	of that site's own clock with nothing to say so."""
	if source_tz == site_tz:
		return when
	return when.replace(tzinfo=ZoneInfo(source_tz)).astimezone(ZoneInfo(site_tz)).replace(tzinfo=None)


def shape_row(
	row: dict, owners: dict[str, str], source_tz: str | None = None, site_tz: str | None = None
) -> dict:
	"""One export row as the importer wants it. Raises ``ValueError`` naming the
	problem for a row that cannot be placed -- the reason lands in the report."""
	code = (row.get("Rep Code") or "").strip()
	user = owners.get(code)
	if not user:
		raise ValueError(f"rep code {code!r} is not in owners")
	kind = PLAN_KIND.get((row.get("activityType") or "").strip())
	if not kind:
		raise ValueError(f"activity type {row.get('activityType')!r} is not mapped")
	mapped = STATUS.get((row.get("status") or "").strip())
	if not mapped:
		raise ValueError(f"status {row.get('status')!r} is not mapped")
	item_status, event_status, override = mapped
	try:
		when = parse_when(row.get("date") or "")
	except ValueError as exc:
		raise ValueError(f"date {row.get('date')!r} is not dd/mm/yyyy HH:MM") from exc
	if source_tz and site_tz:
		when = to_site_time(when, source_tz, site_tz)
	note = (row.get("notes") or "").strip()
	return {
		"id": (row.get("id") or "").strip(),
		"user": user,
		"kind": kind,
		"source_type": (row.get("activityType") or "").strip(),
		"when": when,
		"week_start": week_of(when.date())[0],
		"item_status": item_status,
		"event_status": event_status,
		"manual_override": override,
		"company": (row.get("company") or "").strip(),
		"contact": " ".join((row.get("contactPerson") or "").split()),
		"note": note,
	}


def short_note(note: str) -> str:
	"""What goes on the plan item, a one-line Data field. When the old app
	appended a conclusion, that is the line worth keeping: the text above it is
	the plan ("Routine visit per agreement with customer ..."), the conclusion is
	what happened. The full note is kept on the visit's event."""
	if CONCLUSION_MARKER in note:
		plan, conclusion = (part.strip() for part in note.split(CONCLUSION_MARKER, 1))
		note = conclusion or plan
	note = " ".join(note.split())
	if len(note) <= NOTE_LIMIT:
		return note
	return note[: NOTE_LIMIT - 1].rstrip() + "…"


def suggest_company_map(names: list[str], organizations: list[str]) -> dict[str, dict]:
	"""For each old-app company name: the organization it matches once
	normalised, or the closest few candidates for a person to choose from."""
	by_norm: dict[str, str] = {}
	for org in organizations:
		by_norm.setdefault(normalise_name(org), org)
	out: dict[str, dict] = {}
	for name in sorted(set(names)):
		key = normalise_name(name)
		match = by_norm.get(key)
		candidates = (
			[] if match else [by_norm[k] for k in get_close_matches(key, list(by_norm), n=4, cutoff=0.6)]
		)
		out[name] = {"match": match, "candidates": candidates}
	return out


# --- site side ----------------------------------------------------------------


def build_company_map(reports_dir, overwrite: bool = False) -> dict:
	"""Draft ``company-map.json`` beside the reports from the site's organizations.

	Exact (normalised) matches are filled in; everything else is ``null`` with
	its candidates listed in ``company-map-candidates.json`` for a person to
	resolve by hand. Refuses to overwrite a reviewed map unless told to."""
	reports_dir = Path(reports_dir)
	map_path = reports_dir / COMPANY_MAP_NAME
	if map_path.exists() and not overwrite:
		raise ValueError(f"{map_path} exists; pass overwrite=True to redraft it")
	names = [(row.get("company") or "").strip() for row in read_reports(reports_dir)]
	organizations = frappe.get_all("CRM Organization", pluck="name")
	suggestions = suggest_company_map([n for n in names if n], organizations)
	map_path.write_text(
		json.dumps({n: s["match"] for n, s in suggestions.items()}, indent=1, ensure_ascii=False)
	)
	(reports_dir / CANDIDATES_NAME).write_text(
		json.dumps(
			{n: s["candidates"] for n, s in suggestions.items() if not s["match"]},
			indent=1,
			ensure_ascii=False,
		)
	)
	matched = sum(1 for s in suggestions.values() if s["match"])
	return {"companies": len(suggestions), "matched": matched, "unmatched": len(suggestions) - matched}


def _load_json(value, default=None):
	if value is None:
		return default
	if isinstance(value, dict):
		return value
	return json.loads(Path(value).read_text())


def _read_manifest(path: Path) -> dict[str, dict]:
	if not path.exists():
		return {}
	return json.loads(path.read_text()).get("rows", {})


def _write_manifest(path: Path, manifest: dict[str, dict]) -> None:
	path.write_text(json.dumps({"rows": manifest}, indent=1))


def _commit_every(done: int) -> None:
	# never under test (one rolled-back transaction) and never on a dry run
	if done % COMMIT_EVERY == 0 and not (frappe.flags.in_test or frappe.flags.repapp_import_dry_run):
		frappe.db.commit()  # nosemgrep: frappe-manual-commit


def _description(shaped: dict) -> str:
	"""The event body: the contact the rep saw and the full note, as HTML."""
	parts = []
	if shaped["contact"]:
		parts.append(html.escape(shaped["contact"]))
	if shaped["note"]:
		parts.append(html.escape(shaped["note"]).replace("\n", "<br>"))
	return "<br>".join(parts)


class _Contacts:
	"""Contacts per organization, fetched once each; matched on the whole name."""

	def __init__(self):
		self._by_org: dict[str, dict[str, str]] = {}

	def find(self, text: str, organization: str | None) -> str | None:
		if not (text and organization):
			return None
		if organization not in self._by_org:
			rows = frappe.get_all(
				"Contact", filters={"company_name": organization}, fields=["name", "full_name"]
			)
			self._by_org[organization] = {normalise_name(r.full_name): r.name for r in rows if r.full_name}
		return self._by_org[organization].get(normalise_name(text))


def _insert_event(shaped: dict, organization: str | None, contact: str | None) -> str:
	"""The Event as the rep: frappe stamps ``owner`` from the session on insert,
	and every report and the calendar credit an event to its owner."""
	label = organization or shaped["company"] or shaped["source_type"]
	participants = []
	if organization:
		participants.append({"reference_doctype": "CRM Organization", "reference_docname": organization})
	if contact:
		participants.append({"reference_doctype": "Contact", "reference_docname": contact})
	previous = frappe.session.user
	# the rep named in the export, never the caller: an operator runs this from
	# bench, and the value comes from owners.json checked against tabUser above
	frappe.set_user(shaped["user"])  # nosemgrep: frappe-setuser -- restored in finally
	try:
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": f"Visit: {label}",
				"starts_on": shaped["when"],
				"ends_on": shaped["when"] + VISIT_LENGTH,
				"event_type": "Private",
				"event_category": "Visit",
				"status": shaped["event_status"],
				"description": _description(shaped),
				"send_reminder": 0,
				"event_participants": participants,
			}
		).insert(ignore_permissions=True)
	finally:
		frappe.set_user(previous)  # nosemgrep: frappe-setuser
	return event.name


def _plan_for(user: str, week_start):
	name = frappe.db.exists("CRM Rep Plan", {"user": user, "week_start": week_start})
	if name:
		return frappe.get_doc("CRM Rep Plan", name)
	return frappe.new_doc("CRM Rep Plan", user=user, week_start=week_start)


def import_history(
	reports_dir, owners, company_map=None, dry_run: bool = False, source_tz: str = SOURCE_TIMEZONE
) -> dict:
	"""Entry point for ``bench --site <site> execute
	crm.integrations.repapp.history.import_history --kwargs '{...}'``.

	``owners`` maps the export's ``Rep Code`` to a User (a dict or a JSON path);
	``company_map`` maps the old app's company names to CRM Organization names
	(defaults to ``company-map.json`` beside the reports; a missing or ``null``
	entry imports the row without an organization and reports it);
	``source_tz`` is the zone the export's ``date`` column is written in, and is
	converted to the site's zone when the two differ.
	"""
	reports_dir = Path(reports_dir)
	site_tz = frappe.utils.get_system_timezone()
	owners_map = {str(k): v for k, v in _load_json(owners).items()}
	for user in set(owners_map.values()):
		if not frappe.db.exists("User", user):
			raise ValueError(f"owner {user} is not a User on this site; create the users first")
	map_path = reports_dir / COMPANY_MAP_NAME
	companies = _load_json(company_map, default=None)
	if companies is None:
		companies = _load_json(map_path, default={}) if map_path.exists() else {}
	for org in {v for v in companies.values() if v}:
		if not frappe.db.exists("CRM Organization", org):
			raise ValueError(f"company map names {org!r}, which is not a CRM Organization")

	manifest_path = reports_dir / MANIFEST_NAME
	manifest = _read_manifest(manifest_path)
	rejected: list[dict] = []
	unmapped: dict[str, int] = defaultdict(int)
	by_rep: dict[str, dict[str, dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
	summary: dict = {"dry_run": dry_run, "rows": 0, "imported": 0, "skipped": 0, "plans": 0, "events": 0}
	summary["source_tz"], summary["site_tz"] = source_tz, site_tz
	summary["contacts_matched"] = 0
	summary["notes_shortened"] = 0

	# group first so each (rep, week) plan is saved once
	weeks: dict[tuple[str, object], list[dict]] = defaultdict(list)
	for row in read_reports(reports_dir):
		summary["rows"] += 1
		try:
			shaped = shape_row(row, owners_map, source_tz, site_tz)
		except ValueError as exc:
			rejected.append({"file": row["_file"], "id": row.get("id"), "reason": str(exc)})
			continue
		if not shaped["id"]:
			rejected.append({"file": row["_file"], "id": None, "reason": "row has no id"})
			continue
		landed = manifest.get(shaped["id"])
		if landed and frappe.db.exists("CRM Rep Plan Item", landed["item"]):
			summary["skipped"] += 1
			continue
		weeks[(shaped["user"], shaped["week_start"])].append(shaped)

	contacts = _Contacts()
	frappe.flags.repapp_import_dry_run = dry_run
	done = 0
	try:
		for (user, week_start), shaped_rows in sorted(
			weeks.items(), key=lambda kv: (kv[0][0], str(kv[0][1]))
		):
			plan = _plan_for(user, week_start)
			pending: list[tuple[dict, str | None]] = []
			for shaped in sorted(shaped_rows, key=lambda s: (s["when"], s["id"])):
				organization = companies.get(shaped["company"]) if shaped["company"] else None
				if shaped["company"] and not organization:
					unmapped[shaped["company"]] += 1
				contact = contacts.find(shaped["contact"], organization)
				if contact:
					summary["contacts_matched"] += 1
				event = None
				if shaped["kind"] == "Visit" and shaped["event_status"]:
					event = _insert_event(shaped, organization, contact)
					summary["events"] += 1
				note = short_note(shaped["note"])
				if note != shaped["note"]:
					summary["notes_shortened"] += 1
				plan.append(
					"items",
					{
						"activity_type": shaped["kind"],
						"planned_date": shaped["when"].date(),
						"note": note,
						"status": shaped["item_status"],
						"manual_override": shaped["manual_override"],
						"fulfilled_by_doctype": "Event"
						if event and shaped["item_status"] == "Done"
						else None,
						"fulfilled_by": event if shaped["item_status"] == "Done" else None,
					},
				)
				pending.append((shaped, event))
				by_rep[user][shaped["kind"]][shaped["item_status"]] += 1
			plan.save(ignore_permissions=True)
			# the child rows now have names, in the order they were appended
			new_items = plan.items[-len(pending) :]
			for (shaped, event), item in zip(pending, new_items, strict=True):
				manifest[shaped["id"]] = {"item": item.name, "event": event}
			summary["imported"] += len(pending)
			summary["plans"] += 1
			done += 1
			_commit_every(done)
		if dry_run:
			frappe.db.rollback()
		elif not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: frappe-manual-commit
	finally:
		frappe.flags.repapp_import_dry_run = False
		# written even after a crash: the plans committed so far are on the site,
		# and without their ids the next run would append every item again
		if not dry_run:
			_write_manifest(manifest_path, manifest)

	summary["rejected"] = rejected
	summary["unmapped_companies"] = dict(sorted(unmapped.items(), key=lambda kv: -kv[1]))
	summary["unmapped_rows"] = sum(unmapped.values())
	summary["by_rep"] = {u: {k: dict(v) for k, v in kinds.items()} for u, kinds in by_rep.items()}
	return summary
