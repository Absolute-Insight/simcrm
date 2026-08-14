# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Built-in reports — pure consumption of the metrics layer.

Every report is a registry entry producing ``{title, columns, rows}`` from the
same functions the dashboard uses, so a report can never disagree with the
dashboard (PLAN.md: one source of numbers). No custom-report builder until
these four prove the layer.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Count, IfNull, Sum

from crm.utils import sales_user_only


def _pipeline_by_stage(from_date, to_date, user):
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")
	value = Deal.expected_deal_value * IfNull(Deal.exchange_rate, 1)
	weighted = value * IfNull(Deal.probability, 0) / 100

	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.where(Status.type.isin(["Open", "Ongoing"]))
		.select(
			Deal.status.as_("stage"),
			Count(Deal.name).as_("deals"),
			Sum(value).as_("total_value"),
			Sum(weighted).as_("weighted_value"),
			Status.position.as_("position"),
		)
		.groupby(Deal.status, Status.position)
		.orderby(Status.position)
	)
	if user:
		query = query.where(Deal.deal_owner == user)
	rows = query.run(as_dict=True)
	for row in rows:
		row.pop("position", None)
		row["total_value"] = round(row["total_value"] or 0, 2)
		row["weighted_value"] = round(row["weighted_value"] or 0, 2)
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


def _plan_adherence_by_rep(from_date, to_date, user):
	today = frappe.utils.nowdate()
	cutoff = min(str(to_date), today)

	PlanItem = DocType("CRM Rep Plan Item")
	Plan = DocType("CRM Rep Plan")
	done = frappe.qb.terms.Case().when(PlanItem.status == "Done", 1).else_(None)
	missed = frappe.qb.terms.Case().when(PlanItem.status == "Missed", 1).else_(None)

	query = (
		frappe.qb.from_(PlanItem)
		.join(Plan)
		.on(PlanItem.parent == Plan.name)
		.where((PlanItem.planned_date >= from_date) & (PlanItem.planned_date <= cutoff))
		.select(
			Plan.user.as_("user"),
			Count(PlanItem.name).as_("planned"),
			Count(done).as_("done"),
			Count(missed).as_("missed"),
		)
		.groupby(Plan.user)
		.orderby(Plan.user)
	)
	if user:
		query = query.where(Plan.user == user)
	rows = query.run(as_dict=True)
	for row in rows:
		row["adherence"] = round(row["done"] / row["planned"] * 100) if row["planned"] else 0
	return rows


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


def _quota_attainment_by_rep(from_date, to_date, user):
	from crm.api.dashboard import quota_in_period, won_value_in_period

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
	return rows


REPORTS = {
	"pipeline_by_stage": {
		"title": _("Pipeline by stage"),
		"description": _("Open pipeline: deal count, value and probability-weighted value per stage"),
		"columns": [
			{"key": "stage", "label": _("Stage"), "type": "text"},
			{"key": "deals", "label": _("Deals"), "type": "number"},
			{"key": "total_value", "label": _("Total value"), "type": "currency"},
			{"key": "weighted_value", "label": _("Weighted value"), "type": "currency"},
		],
		"get_rows": _pipeline_by_stage,
	},
	"funnel_conversion": {
		"title": _("Funnel conversion"),
		"description": _("Lead-to-won conversion through the pipeline"),
		"columns": [
			{"key": "stage", "label": _("Stage"), "type": "text"},
			{"key": "count", "label": _("Count"), "type": "number"},
			{"key": "conversion", "label": _("Conversion %"), "type": "percent"},
		],
		"get_rows": _funnel_conversion,
	},
	"plan_adherence_by_rep": {
		"title": _("Plan adherence by rep"),
		"description": _("Planned activities due in the period, and how many were done"),
		"columns": [
			{"key": "user", "label": _("Rep"), "type": "text"},
			{"key": "planned", "label": _("Planned (due)"), "type": "number"},
			{"key": "done", "label": _("Done"), "type": "number"},
			{"key": "missed", "label": _("Missed"), "type": "number"},
			{"key": "adherence", "label": _("Adherence %"), "type": "percent"},
		],
		"get_rows": _plan_adherence_by_rep,
	},
	"forecast_vs_actual": {
		"title": _("Forecast vs actual"),
		"description": _("Probability-weighted forecast against closed revenue per month"),
		"columns": [
			{"key": "month", "label": _("Month"), "type": "text"},
			{"key": "forecasted", "label": _("Forecasted"), "type": "currency"},
			{"key": "actual", "label": _("Actual"), "type": "currency"},
		],
		"get_rows": _forecast_vs_actual,
	},
	"quota_attainment_by_rep": {
		"title": _("Quota attainment by rep"),
		"description": _("Closed-won revenue against quota for the period, per rep"),
		"columns": [
			{"key": "user", "label": _("Rep"), "type": "text"},
			{"key": "quota", "label": _("Quota"), "type": "currency"},
			{"key": "actual", "label": _("Closed won"), "type": "currency"},
			{"key": "gap", "label": _("Gap"), "type": "currency"},
			{"key": "attainment", "label": _("Attainment %"), "type": "percent"},
		],
		"get_rows": _quota_attainment_by_rep,
	},
}


@frappe.whitelist()
@sales_user_only
def list_reports():
	return [
		{"name": key, "title": report["title"], "description": report["description"]}
		for key, report in REPORTS.items()
	]


@frappe.whitelist()
@sales_user_only
def get_report(name: str, from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	if name not in REPORTS:
		frappe.throw(_("Unknown report: {0}").format(name))
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(frappe.utils.nowdate())

	roles = frappe.get_roles()
	if "Sales Manager" not in roles and "System Manager" not in roles:
		user = frappe.session.user

	report = REPORTS[name]
	return {
		"name": name,
		"title": report["title"],
		"description": report["description"],
		"columns": report["columns"],
		"rows": report["get_rows"](str(from_date), str(to_date), user),
	}
