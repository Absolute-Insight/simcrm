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


def _pipeline_by_stage(from_date, to_date, user):
	from crm.api.dashboard import pipeline_by_stage

	rows = pipeline_by_stage(user=user)
	for row in rows:
		row.pop("status_type", None)
	return rows


def _funnel_conversion(from_date, to_date, user):
	from crm.api.dashboard import get_funnel_conversion

	data = get_funnel_conversion(from_date, to_date, user)["data"]
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
		row["rep"] = frappe.utils.get_fullname(row.get("user")) or row.get("user")
	return rows


def _plan_adherence_by_rep(from_date, to_date, user):
	from crm.api.dashboard import plan_adherence

	return _rep_display(plan_adherence(from_date, to_date, user, group_by_user=True))


def _forecast_vs_actual(from_date, to_date, user):
	from crm.api.dashboard import get_forecasted_revenue

	data = get_forecasted_revenue(from_date, to_date, user)["data"]
	return [
		{
			"month": (row.get("month") or "")[:7],
			"forecasted": row.get("forecasted") or 0,
			"actual": row.get("actual") or 0,
		}
		for row in data
	]


def _pipeline_by_segment(from_date, to_date, user):
	"""Open pipeline sliced two ways at once: industry, then company size.

	One report rather than two because the interesting question is the pair --
	"we win mid-market fintech and lose enterprise fintech" is invisible in either
	dimension alone. Rows are the cross-product that actually has deals in it, so
	an empty combination never takes up a line.
	"""
	from crm.api.dashboard import get_deals_by_company_size, get_deals_by_industry

	# Reuse the charts' own aggregates so the report and the dashboard cannot
	# disagree about the same number -- the one-source-of-numbers rule.
	industries = get_deals_by_industry(from_date, to_date, user)["data"]
	sizes = get_deals_by_company_size(from_date, to_date, user)["data"]

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


def _quota_attainment_by_rep(from_date, to_date, user):
	from crm.api.dashboard import quota_in_period, visible_reps, won_value_in_period

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

	rows = []
	for rep in sorted(reps):
		quota = quota_in_period(from_date, to_date, rep)
		actual = won_value_in_period(from_date, to_date, rep)
		rows.append(
			{
				"user": rep,
				"quota": round(quota, 2),
				"actual": round(actual, 2),
				"gap": round(actual - quota, 2),
				"attainment": round(actual / quota * 100) if quota else 0,
			}
		)
	return _rep_display(rows)


REPORTS = {
	"pipeline_by_stage": {
		"title": "Pipeline by stage",
		"description": "Open pipeline as it stands now: deal count, expected value and probability-weighted expected value per stage",
		# the open pipeline is a snapshot of this moment, not of a window — the
		# UI hides the date picker rather than showing one that does nothing
		"period": False,
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
}


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
def get_report(name: str, from_date: str | None = None, to_date: str | None = None, user: str | None = None):
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
	return {
		"name": name,
		"title": _(report["title"]),
		"description": _(report["description"]),
		"period": report.get("period", True),
		"columns": _translated_columns(report),
		"rows": report["get_rows"](str(from_date), str(to_date), user),
	}
