# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Built-in reports — pure consumption of the metrics layer.

Every report is a registry entry producing ``{title, columns, rows}`` from the
same functions the dashboard uses, so a report can never disagree with the
dashboard (PLAN.md: one source of numbers). Nothing here builds its own
aggregate: where a report needs a different shape from a tile, the shared
function in ``crm.api.dashboard`` grows a parameter and both call sites pass it.
No custom-report builder until these prove the layer.

Registry strings are untranslated literals; ``_()`` is applied per request in
:func:`list_reports` and :func:`get_report`, because a module is imported once
per worker and would otherwise freeze every label to the language of whoever
happened to make the first request.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.rate_limiter import rate_limit

from crm.utils import sales_user_only


def _pipeline_by_stage(from_date, to_date, user, territory=None):
	from crm.api.dashboard import pipeline_by_stage

	# Deals created in the period, the same basis the dashboard's by-stage chart
	# uses -- the report and the chart answer one question, not two.
	rows = pipeline_by_stage(from_date, to_date, user, date_field="creation", territory=territory)
	for row in rows:
		row.pop("status_type", None)
	return rows


def _open_pipeline(from_date, to_date, user, territory=None):
	"""The same rows for the pipeline as it stands, whatever the period.

	What the dashboard's "open deals right now" panel and a digest ask for: a digest
	cannot choose its window, and a daily one would otherwise read "no data" on any
	day nobody opened a deal.
	"""
	from crm.api.dashboard import pipeline_by_stage

	rows = pipeline_by_stage(user=user, territory=territory)
	for row in rows:
		row.pop("status_type", None)
	return rows


def _funnel_conversion(from_date, to_date, user, territory=None):
	from crm.api.dashboard import get_funnel_conversion

	data = get_funnel_conversion(from_date, to_date, user, territory)["data"]
	rows = []
	first = data[0]["count"] if data and data[0]["count"] else 0
	for entry in data:
		conversion = round(entry["count"] / first * 100, 1) if first else 0
		rows.append({"stage": entry["stage"], "count": entry["count"], "conversion": conversion})
	return rows


def _rep_display(rows: list[dict]) -> list[dict]:
	"""Add the human name next to each row's ``user`` key.

	The Rep column shows ``rep``; ``user`` stays in the row because it is the
	stable key — the dashboard panels join on it, and two reps can share a full
	name. So the screen, the CSV and the digest all read "Jane Sales" while
	anything programmatic still gets the email.
	"""
	for row in rows:
		user = row.get("user")
		# ``get_fullname`` answers with the *session* user's name when handed
		# nothing, so a row nobody owns read as the viewer's own -- an
		# administrator saw their name against a team's unassigned cancellations
		row["rep"] = (frappe.utils.get_fullname(user) or user) if user else _("Unassigned")
	return rows


def _plan_adherence_by_rep(from_date, to_date, user, territory=None):
	from crm.api.dashboard import plan_adherence

	return _rep_display(plan_adherence(from_date, to_date, user, group_by_user=True))


def _forecast_vs_actual(from_date, to_date, user, territory=None):
	from crm.api.dashboard import get_forecasted_revenue

	data = get_forecasted_revenue(from_date, to_date, user, territory=territory)["data"]
	return [
		{
			"month": (row.get("month") or "")[:7],
			"forecasted": row.get("forecasted") or 0,
			# None for a month still ahead, as the dashboard has it: 0 there read
			# as "closed nothing" on screen, in the CSV and on the printed sheet
			"actual": row.get("actual"),
		}
		for row in data
	]


def _forecast_notice(from_date, to_date, user, territory=None):
	"""Why the forward-looking money columns are all zero, when they are.

	``expected_deal_value`` is only mandatory while FCRM Settings
	``enable_forecasting`` is on, and it ships off -- so on a site that has
	never turned it on, every forward-looking column sums to nothing while the
	realised ones show real revenue. "Forecasted $0 / Actual $71,500,000" in
	one row does not read as a setting being off, it reads as broken.

	The dashboard already says so: ``forecast_empty_state`` exists for exactly
	this and is documented for exactly this ("a blank chart beside tiles
	showing real money reads as a bug"). Reports simply never asked it. Same
	helper, so the two surfaces cannot start explaining it differently.
	"""
	from crm.api.dashboard import forecast_empty_state

	return forecast_empty_state()


def _pipeline_by_segment(from_date, to_date, user, territory=None):
	"""Open pipeline sliced two ways at once: industry, then company size.

	One report rather than two because the interesting question is the pair --
	"we win mid-market fintech and lose enterprise fintech" is invisible in either
	dimension alone. Rows are the cross-product that actually has deals in it, so
	an empty combination never takes up a line.
	"""
	from crm.api.dashboard import get_deals_by_company_size, get_deals_by_industry

	# Reuse the charts' own aggregates so the report and the dashboard cannot
	# disagree about the same number -- the one-source-of-numbers rule.
	industries = get_deals_by_industry(from_date, to_date, user, territory)["data"]
	sizes = get_deals_by_company_size(from_date, to_date, user, territory)["data"]

	rows = [
		{
			"segment": _("Industry"),
			"value_of": row.get("industry") or _("Unset"),
			"deals": row.get("deals") or 0,
			"value": row.get("value") or 0,
		}
		for row in industries
	]
	rows += [
		{
			"segment": _("Company size"),
			"value_of": row.get("company_size") or _("Unset"),
			"deals": row.get("deals") or 0,
			"value": row.get("value") or 0,
		}
		for row in sizes
	]
	return rows


def _quota_attainment_by_rep(from_date, to_date, user, territory=None):
	from crm.api.dashboard import quota_by_user, visible_reps, won_value_by_user

	reps = set(frappe.get_all("CRM Quota", pluck="user", distinct=True))
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")
	won_owners = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.where(
			(Deal.closed_date >= from_date)
			& (Deal.closed_date <= to_date)
			& (Status.type == "Won")
			& Deal.deal_owner.isnotnull()
		)
		.select(Deal.deal_owner)
		.distinct()
		.run(pluck=True)
	)
	reps.update(won_owners)
	if user:
		reps &= {user}
	else:
		visible = visible_reps()
		if visible is not None:
			reps &= set(visible)

	# one grouped read each for quota and closed-won, not two queries per rep
	quotas = quota_by_user(list(reps), from_date, to_date)
	actuals = won_value_by_user(list(reps), from_date, to_date)
	rows = []
	for rep in sorted(reps):
		quota = quotas.get(rep, 0.0)
		actual = actuals.get(rep, 0.0)
		rows.append(
			{
				"user": rep,
				"quota": round(quota, 2),
				"actual": round(actual, 2),
				"gap": round(actual - quota, 2),
				# no target is not 0% of one: a rep who closed business before a
				# target was set has nothing to attain, and 0 ranked them worst
				"attainment": round(actual / quota * 100) if quota else None,
			}
		)
	return _rep_display(rows)


def _client_reliability(from_date, to_date, user, territory=None):
	from crm.api.dashboard import client_reliability

	return client_reliability(from_date, to_date, user)


def _rep_summary(from_date, to_date, user, territory=None):
	from crm.api.dashboard import rep_summary

	return _rep_display(rep_summary(from_date, to_date, user))


def _rep_summary_notice(from_date, to_date, user, territory=None):
	return _(
		"Invoices are not in Vectora yet: the Acumatica connection does not read invoices, so there is no invoice figure per rep. Quotes and orders are the ones Vectora holds from Acumatica."
	)


def _visits_by_rep(from_date, to_date, user, territory=None):
	from crm.api.dashboard import visits_by_rep

	return _rep_display(visits_by_rep(from_date, to_date, user))


def _activities_by_type(from_date, to_date, user, territory=None):
	from crm.api.dashboard import activities_by_type

	return _rep_display(activities_by_type(from_date, to_date, user))


def _customer_interaction(from_date, to_date, user, territory=None):
	"""The customers someone dealt with in the period.

	The zeros have their own report. Listed here as well, ~1,100 untouched
	customers sorted least-contact-first sat above every rep's actual visits,
	so choosing a rep looked like it filtered nothing."""
	from crm.api.dashboard import customer_interaction

	return [row for row in customer_interaction(from_date, to_date, user) if row["total"]]


def _customers_without_interaction(from_date, to_date, user, territory=None):
	"""The same rows as customer interaction, kept to the customers with none.

	Only the columns that can differ between them are shown: every count on
	these rows is zero by definition."""
	from crm.api.dashboard import customer_interaction

	keep = ("organization", "last_interaction", "last_rep", "days_since")
	return [
		{key: row[key] for key in keep}
		for row in customer_interaction(from_date, to_date, user, only_without=True)
	]


REPORTS = {
	"pipeline_by_stage": {
		"title": "Pipeline by stage",
		"description": "Open deals created in the period: deal count, expected value and probability-weighted expected value per stage",
		"columns": [
			{"key": "stage", "label": "Stage", "type": "text"},
			{"key": "deals", "label": "Deals", "type": "number"},
			{
				"key": "total_value",
				"label": "Expected value",
				"type": "currency",
				"description": "Sum of expected deal value, in the base currency",
			},
			{
				"key": "weighted_value",
				"label": "Weighted expected value",
				"type": "currency",
				"description": "Expected deal value multiplied by stage probability",
			},
		],
		"get_rows": _pipeline_by_stage,
		"get_snapshot_rows": _open_pipeline,
		"get_notice": _forecast_notice,
	},
	"funnel_conversion": {
		"title": "Funnel conversion",
		"description": "Lead-to-won conversion through the pipeline, including the deals that leaked out",
		"columns": [
			{"key": "stage", "label": "Stage", "type": "text"},
			{"key": "count", "label": "Count", "type": "number"},
			{"key": "conversion", "label": "Conversion %", "type": "percent"},
		],
		"get_rows": _funnel_conversion,
	},
	"plan_adherence_by_rep": {
		"title": "Plan adherence by rep",
		"description": "Planned activities due in the period, and how many were done",
		"columns": [
			{"key": "rep", "label": "Rep", "type": "text"},
			{"key": "planned", "label": "Planned (due)", "type": "number"},
			{"key": "done", "label": "Done", "type": "number"},
			{"key": "missed", "label": "Missed", "type": "number"},
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
			{"key": "adherence", "label": "Adherence %", "type": "percent"},
		],
		"get_rows": _plan_adherence_by_rep,
	},
	"forecast_vs_actual": {
		"title": "Forecast vs actual",
		"description": "Probability-weighted forecast against closed revenue per month",
		"columns": [
			{"key": "month", "label": "Month", "type": "text"},
			{"key": "forecasted", "label": "Forecasted", "type": "currency"},
			{"key": "actual", "label": "Actual", "type": "currency"},
		],
		"get_rows": _forecast_vs_actual,
		"get_notice": _forecast_notice,
	},
	"pipeline_by_segment": {
		"title": "Pipeline by segment",
		"description": "Deal count and value per industry and per company size",
		"columns": [
			{"key": "segment", "label": "Segment", "type": "text"},
			{"key": "value_of", "label": "Value", "type": "text"},
			{"key": "deals", "label": "Deals", "type": "number"},
			{"key": "value", "label": "Deal value", "type": "currency"},
		],
		"get_rows": _pipeline_by_segment,
	},
	"quota_attainment_by_rep": {
		"title": "Quota attainment by rep",
		"description": "Closed-won revenue against quota for the period, per rep",
		"columns": [
			{"key": "rep", "label": "Rep", "type": "text"},
			{"key": "quota", "label": "Quota", "type": "currency"},
			{"key": "actual", "label": "Closed won", "type": "currency"},
			{"key": "gap", "label": "Gap", "type": "currency"},
			{"key": "attainment", "label": "Attainment %", "type": "percent"},
		],
		"get_rows": _quota_attainment_by_rep,
	},
	"client_reliability": {
		"title": "Client reliability",
		"description": "Activity outcomes by client, most rescheduled and cancelled first",
		"columns": [
			{"key": "organization", "label": "Client", "type": "text"},
			{"key": "total", "label": "Activities", "type": "number"},
			{"key": "done", "label": "Done", "type": "number"},
			{"key": "rescheduled", "label": "Rescheduled", "type": "number"},
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
		],
		"get_rows": _client_reliability,
	},
	"visits_by_rep": {
		"title": "Visits against target",
		"description": "Planned customer visits per rep in the period: scheduled, completed, cancelled and missed, against each rep's weekly visit target. Calls, emails and other activities are not counted; unplanned meetings are shown beside the target",
		"columns": [
			{"key": "rep", "label": "Rep", "type": "text"},
			{
				"key": "target",
				"label": "Target",
				"type": "number",
				"description": "Weekly visit target pro-rated to the working days in the period",
			},
			{
				"key": "target_to_date",
				"label": "Target to date",
				"type": "number",
				"description": "The part of the target already due, up to yesterday",
			},
			{"key": "scheduled", "label": "Scheduled", "type": "number"},
			{"key": "completed", "label": "Completed", "type": "number"},
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
			{"key": "missed", "label": "Missed", "type": "number"},
			{"key": "open", "label": "Still planned", "type": "number"},
			{"key": "attainment", "label": "% of target", "type": "percent"},
			{"key": "on_track", "label": "Status", "type": "text"},
			{
				"key": "unplanned",
				"label": "Unplanned",
				"type": "number",
				"description": "Unplanned meetings logged in the period; not counted against the target",
			},
		],
		"get_rows": _visits_by_rep,
	},
	"rep_summary": {
		"title": "Rep summary",
		"description": "Per rep: visits, unplanned meetings, deliveries, calls and emails done in the period, beside the quotes and orders",
		"columns": [
			{"key": "rep", "label": "Rep", "type": "text"},
			{"key": "visits", "label": "Visits", "type": "number"},
			{"key": "unplanned", "label": "Unplanned meetings", "type": "number"},
			{"key": "deliveries", "label": "Deliveries", "type": "number"},
			{"key": "calls", "label": "Calls", "type": "number"},
			{"key": "emails", "label": "Emails", "type": "number"},
			{
				"key": "quotes",
				"label": "Quotes",
				"type": "number",
				"description": "Sales quotes created in the period",
			},
			{"key": "quote_value", "label": "Quote value", "type": "currency"},
			{
				"key": "orders",
				"label": "Orders",
				"type": "number",
				"description": "Quotes turned into a sales order in the period",
			},
			{"key": "order_value", "label": "Order value", "type": "currency"},
		],
		"get_rows": _rep_summary,
		"get_notice": _rep_summary_notice,
	},
	"activities_by_type": {
		"title": "Activities by type",
		"description": "Planned and logged activities per rep and type — visits, deliveries, calls, admin — and what became of them",
		"columns": [
			{"key": "rep", "label": "Rep", "type": "text"},
			{"key": "activity_type", "label": "Type", "type": "text"},
			{"key": "scheduled", "label": "Scheduled", "type": "number"},
			{"key": "done", "label": "Done", "type": "number"},
			{"key": "cancelled", "label": "Cancelled", "type": "number"},
			{"key": "missed", "label": "Missed", "type": "number"},
			{"key": "open", "label": "Still planned", "type": "number"},
			{
				"key": "overdue",
				"label": "Overdue",
				"type": "number",
				"description": "Still planned, and the day has passed",
			},
		],
		"get_rows": _activities_by_type,
	},
	"customer_interaction": {
		"title": "Customer interaction",
		"description": "Customers visited, delivered to, called or emailed in the period, least contact first. The ones nobody contacted are in Customers with no interaction",
		"columns": [
			{"key": "organization", "label": "Customer", "type": "text"},
			{"key": "visits", "label": "Visits", "type": "number"},
			{"key": "deliveries", "label": "Deliveries", "type": "number"},
			{"key": "calls", "label": "Calls", "type": "number"},
			{"key": "emails", "label": "Emails", "type": "number"},
			{"key": "other", "label": "Other", "type": "number"},
			{"key": "total", "label": "Total", "type": "number"},
			{
				"key": "last_interaction",
				"label": "Last interaction",
				"type": "text",
				"description": "The latest interaction on or before the end of the period, at any time",
			},
			{"key": "last_rep", "label": "Last rep", "type": "text"},
			{"key": "days_since", "label": "Days since", "type": "number"},
		],
		"get_rows": _customer_interaction,
	},
	"customers_without_interaction": {
		"title": "Customers with no interaction",
		"description": "Customers nobody visited, delivered to, called or emailed in the period, longest neglected first",
		"columns": [
			{"key": "organization", "label": "Customer", "type": "text"},
			{"key": "last_interaction", "label": "Last interaction", "type": "text"},
			{"key": "last_rep", "label": "Last rep", "type": "text"},
			{"key": "days_since", "label": "Days since", "type": "number"},
		],
		"get_rows": _customers_without_interaction,
	},
}


# The report-side twin of ``dashboard.TERRITORY_BLIND``, and for the same
# reasons: a rep plan has no territory, and quota is per rep per month so
# filtering only the closed-won side would divide one region's revenue by the
# global target. ``client_reliability`` joins ``CRM Deal`` already (for the
# organization) but the query never accepts or applies ``territory`` -- worth
# doing, not done yet. Reported rather than silently ignored. The visit and
# activity reports read rep plans, which have no territory; customer
# interaction could narrow by the organization's territory, and does not yet.
TERRITORY_BLIND = frozenset(
	{
		"plan_adherence_by_rep",
		"quota_attainment_by_rep",
		"client_reliability",
		"visits_by_rep",
		"rep_summary",
		"activities_by_type",
		"customer_interaction",
		"customers_without_interaction",
	}
)


def _translated_columns(report: dict) -> list[dict]:
	return [{**column, "label": _(column["label"])} for column in report["columns"]]


@frappe.whitelist()
@sales_user_only
def list_reports():
	return [
		{
			"name": key,
			"title": _(report["title"]),
			"description": _(report["description"]),
			"period": report.get("period", True),
		}
		for key, report in REPORTS.items()
	]


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=60, seconds=60)
def get_report(
	name: str,
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	territory: str | None = None,
	snapshot: bool = False,
):
	"""``snapshot`` asks a report that has one for its state right now rather than
	over the period; it means nothing to a report that does not."""
	from crm.api.dashboard import check_user_rate

	# per-account on top of the per-IP decorator; a report is a full aggregate
	# pass, so the user budget is the same 60 rather than the dashboard's double
	check_user_rate("report", 60)
	if name not in REPORTS:
		frappe.throw(_("Unknown report: {0}").format(name))
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(frappe.utils.nowdate())

	# Same rule as the dashboard: a plain Sales User is pinned to themselves, and
	# anyone else may only name a rep inside their own subtree. Trusting the
	# parameter for any Sales Manager let an in-tree one read another team's
	# quota_attainment_by_rep row -- compensation data, one query string away.
	from crm.api.dashboard import pin_user

	user = pin_user(user)

	report = REPORTS[name]
	get_rows = (snapshot and report.get("get_snapshot_rows")) or report["get_rows"]
	return {
		"name": name,
		"title": _(report["title"]),
		"description": _(report["description"]),
		"period": False if get_rows is report.get("get_snapshot_rows") else report.get("period", True),
		"columns": _translated_columns(report),
		"rows": get_rows(str(from_date), str(to_date), user, territory),
		# Optional, and None for most reports: a line explaining why the numbers
		# below are the shape they are, when we know. Already-translated, since
		# the producer builds it per request.
		"notice": (
			report["get_notice"](str(from_date), str(to_date), user, territory)
			if report.get("get_notice")
			else None
		),
		"territory": territory or None,
		"territory_filtered": bool(territory) and name not in TERRITORY_BLIND,
	}
