import json

import frappe
from frappe.utils.telemetry import capture

DEMO_STATE_KEY = "crm_demo_data_created"
DEMO_CREATED_AT_KEY = "crm_demo_data_created_at"
DEMO_SEED_CONFIG_KEY = "crm_seed_demo_data"
DEMO_LEADS_KEY = "crm_demo_leads"
DEMO_NOTES_KEY = "crm_demo_notes"
DEMO_TASKS_KEY = "crm_demo_tasks"
DEMO_CALL_LOGS_KEY = "crm_demo_call_logs"
DEMO_ACTIVITIES_KEY = "crm_demo_activities"
DEMO_DEALS_KEY = "crm_demo_deals"
DEMO_HISTORY_KEY = "crm_demo_history"


def seed_demo_data_if_enabled(_args: dict | None = None):
	"""``setup_wizard_complete`` target: seed demo data only where it was asked for.

	This hook fires when an operator finishes the desk setup wizard, which is a
	step ``deploy/README.md`` sends them to on a *production* site. Seeding there
	puts eleven fake leads, seven fake deals and three fake users into a real
	CRM, and the derived tier then treats them as real: hourly signals score
	them, the weekly forecast snapshot folds their value into the site total,
	and a snapshot is a record of what was believed on a date -- it cannot be
	corrected afterwards, only discarded.

	So seeding is opt-in via ``crm_seed_demo_data`` in site config. The gate is
	here rather than in :func:`create_demo_data` so that an explicit
	``bench execute crm.demo.api.create_demo_data`` still does what it says.
	"""
	if not frappe.conf.get(DEMO_SEED_CONFIG_KEY):
		return
	create_demo_data(_args)


def create_demo_data(_args: dict | None = None):
	if frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.activities import create_demo_activities
	from crm.demo.call_logs import create_demo_call_logs
	from crm.demo.deals import create_demo_deals
	from crm.demo.leads import create_demo_leads
	from crm.demo.notes import create_demo_notes
	from crm.demo.tasks import create_demo_tasks
	from crm.demo.users import create_demo_users

	demo_users = create_demo_users()
	lead_names = create_demo_leads(demo_users)
	note_names = create_demo_notes(lead_names, demo_users)
	task_names = create_demo_tasks(lead_names, demo_users)
	call_log_names = create_demo_call_logs(lead_names, demo_users)
	activity_data = create_demo_activities(lead_names, demo_users)

	from crm.demo.leads import rebackdate_demo_leads

	rebackdate_demo_leads(lead_names, demo_users)

	deal_data = create_demo_deals(lead_names, demo_users)
	# Two years of pipeline behind the hand-written records, so every
	# dashboard, report and forecast has a series to draw. Tracked by name and
	# removed with the rest.
	from crm.demo.history import create_demo_history

	history = create_demo_history(demo_users)
	frappe.db.set_default(DEMO_HISTORY_KEY, json.dumps(history))
	frappe.db.set_default(DEMO_LEADS_KEY, json.dumps(lead_names))
	frappe.db.set_default(DEMO_NOTES_KEY, json.dumps(note_names))
	frappe.db.set_default(DEMO_TASKS_KEY, json.dumps(task_names))
	frappe.db.set_default(DEMO_CALL_LOGS_KEY, json.dumps(call_log_names))
	frappe.db.set_default(DEMO_ACTIVITIES_KEY, json.dumps(activity_data))
	frappe.db.set_default(DEMO_DEALS_KEY, json.dumps(deal_data))
	# Which snapshots and suggestions are suspect is a question about *when*, and
	# nothing else records it: demo leads are deliberately backdated, so their
	# creation timestamps cannot stand in for this.
	frappe.db.set_default(DEMO_CREATED_AT_KEY, frappe.utils.now())
	frappe.db.set_default(DEMO_STATE_KEY, "1")

	capture("demo_data_created", "crm")


@frappe.whitelist()
def clear_demo_data():
	frappe.only_for(["Sales Manager", "System Manager"], True)

	if not frappe.db.get_default(DEMO_STATE_KEY):
		return

	from crm.demo.activities import delete_demo_activities
	from crm.demo.call_logs import delete_demo_call_logs
	from crm.demo.deals import delete_demo_deals
	from crm.demo.history import delete_demo_history
	from crm.demo.leads import delete_demo_leads
	from crm.demo.notes import delete_demo_notes
	from crm.demo.tasks import delete_demo_tasks
	from crm.demo.users import DEMO_USER_EMAILS, delete_demo_users

	lead_names = json.loads(frappe.db.get_default(DEMO_LEADS_KEY) or "[]")
	note_names = json.loads(frappe.db.get_default(DEMO_NOTES_KEY) or "[]")
	task_names = json.loads(frappe.db.get_default(DEMO_TASKS_KEY) or "[]")
	call_log_names = json.loads(frappe.db.get_default(DEMO_CALL_LOGS_KEY) or "[]")
	activity_data = json.loads(frappe.db.get_default(DEMO_ACTIVITIES_KEY) or "{}")
	deal_data = json.loads(frappe.db.get_default(DEMO_DEALS_KEY) or "{}")
	history = json.loads(frappe.db.get_default(DEMO_HISTORY_KEY) or "{}")
	# Before the base records go: the derived tier is keyed on their names, and
	# once a deal is deleted there is nothing left to match a suggestion against.
	delete_derived_demo_records(lead_names + list(history.get("leads", [])), deal_data, DEMO_USER_EMAILS)
	delete_demo_history(history)
	delete_demo_deals(deal_data, lead_names)
	delete_demo_activities(activity_data)
	delete_demo_notes(note_names)
	delete_demo_tasks(task_names)
	delete_demo_call_logs(call_log_names)
	delete_demo_leads(lead_names)
	delete_demo_users(DEMO_USER_EMAILS)
	frappe.db.set_default(DEMO_LEADS_KEY, None)
	frappe.db.set_default(DEMO_NOTES_KEY, None)
	frappe.db.set_default(DEMO_TASKS_KEY, None)
	frappe.db.set_default(DEMO_CALL_LOGS_KEY, None)
	frappe.db.set_default(DEMO_ACTIVITIES_KEY, None)
	frappe.db.set_default(DEMO_DEALS_KEY, None)
	frappe.db.set_default(DEMO_HISTORY_KEY, None)
	frappe.db.set_default(DEMO_CREATED_AT_KEY, None)
	frappe.db.set_default(DEMO_STATE_KEY, None)

	capture("demo_data_cleared", "crm")


def delete_derived_demo_records(lead_names: list, deal_data: dict, demo_users: list) -> dict:
	"""Remove what the proactive tier inferred *from* demo data.

	``clear_demo_data`` used to delete only what ``crm/demo/`` created, but the
	hourly signal run, the planner and the weekly forecast job all read those
	records and write their own. Clearing the source left the conclusions: a
	suggestion pointing at a deleted deal, a rep plan for a user who no longer
	exists, and forecast history built partly on fiction.

	Returns a count per doctype so the caller can say what it removed.
	"""
	deal_names = set(deal_data.get("deals") or [])
	if lead_names:
		deal_names.update(frappe.get_all("CRM Deal", filters={"lead": ["in", lead_names]}, pluck="name"))
	references = sorted(deal_names | set(lead_names or []))
	removed = {}

	# A suggestion is demo-derived if it is *about* a demo record or *for* a demo
	# rep. Either alone leaves rows behind: signals raised on a demo deal are
	# assigned to whoever owns it, and a demo user also collects suggestions
	# about records that outlive them.
	suggestions = set()
	if references:
		suggestions.update(
			frappe.get_all("CRM Suggestion", filters={"reference_docname": ["in", references]}, pluck="name")
		)
	if demo_users:
		suggestions.update(
			frappe.get_all("CRM Suggestion", filters={"user": ["in", demo_users]}, pluck="name")
		)
	for name in suggestions:
		frappe.delete_doc("CRM Suggestion", name, ignore_permissions=True, force=True)
	removed["CRM Suggestion"] = len(suggestions)

	# delete_doc, not db.delete: a plan owns a child table, and deleting the
	# parent row directly would orphan every CRM Rep Plan Item under it.
	plans = frappe.get_all("CRM Rep Plan", filters={"user": ["in", demo_users]}, pluck="name")
	for name in plans:
		frappe.delete_doc("CRM Rep Plan", name, ignore_permissions=True, force=True)
	removed["CRM Rep Plan"] = len(plans)

	removed["CRM Forecast Snapshot"] = _delete_contaminated_snapshots(demo_users)
	return removed


def _delete_contaminated_snapshots(demo_users: list) -> int:
	"""Forecast rows that counted demo deals, which cannot be recomputed.

	A snapshot stores what was forecast on a past date. Once demo deals are gone
	the number cannot be rebuilt, and a stored aggregate that silently includes
	fiction is worse than no history -- the same reasoning as the
	``clear_contaminated_forecast_snapshots`` patch.

	Only Site and Team rows mix populations. A real rep's Rep row never counted a
	demo deal (a demo deal belongs to a demo user), so real per-rep accuracy
	history survives this untouched.
	"""
	deleted = 0
	if demo_users:
		rows = frappe.get_all("CRM Forecast Snapshot", filters={"user": ["in", demo_users]}, pluck="name")
		if rows:
			frappe.db.delete("CRM Forecast Snapshot", {"name": ["in", rows]})
			deleted += len(rows)

	aggregate = {"scope": ["in", ["Site", "Team"]]}
	created_at = frappe.db.get_default(DEMO_CREATED_AT_KEY)
	if created_at:
		# Rows taken before the demo data existed are clean; keep them.
		aggregate["snapshot_date"] = [">=", str(created_at)[:10]]
	# Without a recorded timestamp -- a site seeded before this was tracked --
	# there is no way to tell a clean aggregate from a contaminated one, so all
	# of them go. Rep rows are untouched either way.
	rows = frappe.get_all("CRM Forecast Snapshot", filters=aggregate, pluck="name")
	if rows:
		frappe.db.delete("CRM Forecast Snapshot", {"name": ["in", rows]})
		deleted += len(rows)
	return deleted


@frappe.whitelist()
def get_demo_state():
	return {"demo_data_created": bool(frappe.db.get_default(DEMO_STATE_KEY))}
