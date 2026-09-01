# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Analyst's data half: run a plan against the metrics layer and the ERP.

Every CRM table comes from ``crm.api.dashboard`` or ``crm.api.reports`` --
the one place an aggregate is computed, so the Analyst can never disagree
with a dashboard tile about the same number. Reads run under the calling
admin's own session, so the metrics layer's scoping applies as it does on the
dashboard. ERP tables come from the enabled integration's own client; a
failure there yields a table marked unreachable rather than an exception, so
the CRM half of an answer survives an ERP outage.

No SQL is written here and none is accepted from the model: ``run_plan``
takes catalogue keys and dates, nothing else.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, timedelta

import frappe
import requests

from crm.agent import analyst
from crm.agent.config import get_signal_config
from crm.agent.predict import AT_RISK_BELOW, COOLING_RATIO, get_deal_health
from crm.agent.signals import (
	CADENCE_WINDOW_DAYS,
	_activity_history,
	_latest_activity,
	_working_deal_rows,
	cadence_ratio,
)

ERP_ROW_CAP = 5000
ERP_TIMEOUT = 30
OVERDUE_AFTER_DAYS = 30
QUIET_DEAL_CAP = 200


# --- which ERP -----------------------------------------------------------------


def enabled_erp() -> str | None:
	"""``"acumatica"``, ``"erpnext"`` or ``None``. The two are mutually exclusive by validation."""
	if frappe.db.get_single_value("CRM Acumatica Settings", "enabled"):
		return "acumatica"
	if frappe.db.get_single_value("ERPNext CRM Settings", "enabled"):
		return "erpnext"
	return None


ERP_LABELS = {"acumatica": "Acumatica", "erpnext": "ERPNext"}


# --- running a plan --------------------------------------------------------------


def run_plan(plan: dict, erp: str | None) -> list[dict]:
	"""Compute one table per metric in ``plan["metrics"]``, in order.

	Unknown keys are skipped (the pure half already dropped them; this is the
	belt to its braces). ERP metrics with no ERP enabled are skipped too.
	"""
	from_date, to_date = plan["from_date"], plan["to_date"]
	tables = []
	for key in plan.get("metrics", []):
		metric = analyst.CATALOGUE.get(key)
		if not metric:
			continue
		if metric["source"] == analyst.ERP:
			if not erp:
				continue
			tables.append(_erp_table(key, metric, erp, from_date, to_date))
			continue
		runner = _CRM_RUNNERS.get(key)
		if not runner:
			continue
		rows, note = runner(from_date, to_date)
		tables.append(_table(key, metric, "CRM", rows, from_date, to_date, note))
	return tables


def _table(key, metric, source, rows, from_date, to_date, note="", error=None) -> dict:
	return {
		"key": key,
		"title": metric["title"],
		"source": source,
		"columns": metric["columns"],
		"rows": rows,
		"period": {"from": from_date, "to": to_date},
		"note": note,
		"error": error,
	}


# --- CRM runners -----------------------------------------------------------------


def _won_series(from_date, to_date) -> list[tuple[str, float]]:
	from crm.api.dashboard import actual_by_month

	by_month = actual_by_month(from_date, to_date)
	return [(month, float(by_month.get(month, 0.0))) for month in analyst.months_between(from_date, to_date)]


def _won_revenue_by_month(from_date, to_date):
	rows = [{"month": month, "value": value} for month, value in _won_series(from_date, to_date)]
	return rows, "Closed-won deal value in the base currency, by the month the deal closed."


def _forecast_by_month(from_date, to_date):
	from crm.api.dashboard import forecast_by_month

	by_month = forecast_by_month(from_date, to_date)
	rows = [{"month": month, "value": float(value or 0)} for month, value in sorted(by_month.items())]
	return rows, "Open pipeline weighted by stage probability, by expected close month."


def _growth_rates(from_date, to_date):
	return analyst.growth_rates(_won_series(from_date, to_date)), "Change is against the previous month."


def _revenue_projection(from_date, to_date):
	projection = analyst.project_revenue(_won_series(from_date, to_date))
	return projection["points"], f"Projected months use a {projection['method']}; a trend, not booked deals."


def _pipeline_by_stage(from_date, to_date):
	from crm.api.dashboard import pipeline_by_stage

	rows = [
		{
			"stage": row.get("stage"),
			"deals": int(row.get("deals") or 0),
			"value": float(row.get("total_value") or 0),
			"weighted": float(row.get("weighted_value") or 0),
		}
		for row in pipeline_by_stage(from_date, to_date)
	]
	return rows, "Open deals as of now; value is expected deal value."


def _funnel_conversion(from_date, to_date):
	from crm.api.dashboard import get_funnel_conversion

	return list(get_funnel_conversion(from_date, to_date)["data"]), ""


def _quota_attainment_by_rep(from_date, to_date):
	from crm.api.reports import _quota_attainment_by_rep as report

	rows = [
		{
			"rep": row.get("rep"),
			"quota": float(row.get("quota") or 0),
			"actual": float(row.get("actual") or 0),
			"attainment_pct": row.get("attainment"),
		}
		for row in report(from_date, to_date, None)
	]
	return rows, "Only reps with a target in the period appear."


def _plan_adherence_by_rep(from_date, to_date):
	from crm.api.reports import _plan_adherence_by_rep as report

	rows = []
	for row in report(from_date, to_date, None):
		planned = int(row.get("planned") or 0)
		done = int(row.get("done") or 0)
		rows.append(
			{
				"rep": row.get("rep"),
				"planned": planned,
				"done": done,
				"missed": int(row.get("missed") or 0),
				"adherence_pct": round(done / planned * 100) if planned else None,
			}
		)
	return rows, "Only settled items (planned before today) are counted."


def _deals_at_risk(from_date, to_date):
	from crm.api.dashboard import _at_risk_deals

	scored = [row for row in _at_risk_deals(to_date) if row["score"] < AT_RISK_BELOW]
	scored.sort(key=lambda row: row["score"])
	names = [row["name"] for row in scored]
	details = (
		{
			row.name: row
			for row in frappe.get_list(
				"CRM Deal",
				filters={"name": ("in", names)},
				fields=["name", "organization", "deal_owner", "deal_value", "exchange_rate"],
				limit=len(names) or 1,
			)
		}
		if names
		else {}
	)
	rows = []
	for row in scored:
		detail = details.get(row["name"]) or {}
		rows.append(
			{
				"deal": row["name"],
				"organization": detail.get("organization") or "",
				"owner": frappe.utils.get_fullname(detail.get("deal_owner"))
				or detail.get("deal_owner")
				or "",
				"health_score": int(row["score"]),
				"value": float(detail.get("deal_value") or 0) * float(detail.get("exchange_rate") or 1),
				"reasons": "; ".join(
					factor.get("label") or factor.get("name", "") for factor in row.get("factors", [])
				),
			}
		)
	return rows, f"Health below {AT_RISK_BELOW} out of 100. Scored now, not as of the period."


def _accounts_going_quiet(from_date, to_date):
	"""Organizations whose open deals are cooling or slipping -- the maintenance list."""
	now = frappe.utils.now_datetime()
	horizon = get_signal_config().close_horizon_days
	deals = _working_deal_rows()[:QUIET_DEAL_CAP]
	names = [row["name"] for row in deals]
	latest = _latest_activity(names)
	history = _activity_history(names, now - timedelta(days=CADENCE_WINDOW_DAYS))

	by_org: dict[str, dict] = {}
	for deal in deals:
		reasons = []
		measured = cadence_ratio(history.get(deal["name"]) or [], now)
		if measured and measured[0] >= COOLING_RATIO:
			reasons.append("contact cadence slowing")
		closes = deal.get("expected_closure_date")
		if closes and (closes - now.date()).days <= horizon and (deal.get("stage_probability") or 0) < 50:
			reasons.append("close date near, stage still early")
		if not reasons:
			continue
		last = latest.get(deal["name"]) or deal["creation"]
		try:
			health = get_deal_health(deal["name"])["score"]
		except frappe.PermissionError:
			continue
		org = deal.get("organization") or "(no organization)"
		entry = by_org.setdefault(
			org,
			{
				"organization": org,
				"deals": 0,
				"days_since_contact": 0,
				"lowest_health": 100,
				"reasons": set(),
			},
		)
		entry["deals"] += 1
		entry["days_since_contact"] = max(entry["days_since_contact"], max(0, (now - last).days))
		entry["lowest_health"] = min(entry["lowest_health"], int(health))
		entry["reasons"].update(reasons)

	rows = [
		{**entry, "reason": ", ".join(sorted(entry.pop("reasons")))}
		for entry in sorted(by_org.values(), key=lambda e: (e["lowest_health"], -e["days_since_contact"]))
	]
	return rows, "From the cadence and slip-risk signals on open deals; not equipment maintenance."


def _sales_trend(from_date, to_date):
	from crm.api.dashboard import get_sales_trend

	totals: dict[str, dict] = defaultdict(lambda: {"leads": 0, "deals": 0, "won_deals": 0})
	for row in get_sales_trend(from_date, to_date)["data"]:
		month = str(row.get("date"))[:7]
		for key in ("leads", "deals", "won_deals"):
			totals[month][key] += int(row.get(key) or 0)
	rows = [{"month": month, **counts} for month, counts in sorted(totals.items())]
	return rows, ""


def _breakdown(getter_name: str, category: str):
	def run(from_date, to_date):
		from crm.api import dashboard

		data = getattr(dashboard, getter_name)(from_date, to_date)["data"]
		rows = []
		for row in data:
			out = {category: row.get(category)}
			for key in ("count", "deals", "value"):
				if key in row:
					out[key] = float(row[key]) if key == "value" else int(row[key] or 0)
			rows.append(out)
		return rows, ""

	return run


def _tile(getter_name: str, label: str, field: str):
	def run(from_date, to_date):
		from crm.api import dashboard

		tile = getattr(dashboard, getter_name)(from_date, to_date)
		value = tile.get("value") or 0
		return [{"metric": label, field: round(float(value), 2) if field == "value" else int(value)}], ""

	return run


_CRM_RUNNERS = {
	"won_revenue_by_month": _won_revenue_by_month,
	"forecast_by_month": _forecast_by_month,
	"growth_rates": _growth_rates,
	"revenue_projection": _revenue_projection,
	"pipeline_by_stage": _pipeline_by_stage,
	"funnel_conversion": _funnel_conversion,
	"quota_attainment_by_rep": _quota_attainment_by_rep,
	"deals_at_risk": _deals_at_risk,
	"accounts_going_quiet": _accounts_going_quiet,
	"sales_trend": _sales_trend,
	"leads_by_source": _breakdown("get_leads_by_source", "source"),
	"deals_by_industry": _breakdown("get_deals_by_industry", "industry"),
	"deals_by_territory": _breakdown("get_deals_by_territory", "territory"),
	"deals_by_salesperson": _breakdown("get_deals_by_salesperson", "salesperson"),
	"plan_adherence_by_rep": _plan_adherence_by_rep,
	"average_deal_value": _tile("get_average_deal_value", "Average deal value", "value"),
	"time_to_close": _tile("get_average_time_to_close_a_deal", "Average days to close", "days"),
}


# --- ERP -------------------------------------------------------------------------


def _erp_table(key, metric, erp, from_date, to_date) -> dict:
	label = ERP_LABELS[erp]
	try:
		invoices = payments = None
		if key in ("erp_invoices_by_month", "erp_receivables", "erp_cashflow_by_month"):
			invoices = _erp_invoices(erp, from_date, to_date)
		if key in ("erp_payments_by_month", "erp_cashflow_by_month"):
			payments = _erp_payments(erp, from_date, to_date)
	except Exception as exc:
		frappe.log_error(title="CRM analyst ERP read failed", message=f"{erp} {key}: {exc}")
		return _table(key, metric, label, [], from_date, to_date, "", error="unreachable")

	months = analyst.months_between(from_date, to_date)
	if key == "erp_invoices_by_month":
		rows = _sum_by_month(months, invoices, "amount", "invoiced", "invoices")
	elif key == "erp_payments_by_month":
		rows = _sum_by_month(months, payments, "amount", "received", "payments")
	elif key == "erp_receivables":
		rows = _receivables(invoices, date.fromisoformat(to_date))
	else:
		invoiced = {
			row["month"]: row["invoiced"]
			for row in _sum_by_month(months, invoices, "amount", "invoiced", "n")
		}
		received = {
			row["month"]: row["received"]
			for row in _sum_by_month(months, payments, "amount", "received", "n")
		}
		rows = [
			{
				"month": month,
				"invoiced": invoiced.get(month, 0.0),
				"received": received.get(month, 0.0),
				"net": round(received.get(month, 0.0) - invoiced.get(month, 0.0), 2),
			}
			for month in months
		]
	return _table(key, metric, label, rows, from_date, to_date, f"Figures from {label}, in its own currency.")


def _sum_by_month(months, records, amount_key, total_label, count_label) -> list[dict]:
	totals = {month: [0.0, 0] for month in months}
	for record in records or []:
		month = str(record.get("date") or "")[:7]
		if month in totals:
			totals[month][0] += float(record.get(amount_key) or 0)
			totals[month][1] += 1
	return [
		{"month": month, total_label: round(total, 2), count_label: count}
		for month, (total, count) in totals.items()
	]


def _receivables(invoices, as_of: date) -> list[dict]:
	buckets = {"Current": [0.0, 0], "Overdue": [0.0, 0]}
	for record in invoices or []:
		balance = float(record.get("balance") or 0)
		if balance <= 0:
			continue
		due = record.get("due") or record.get("date")
		overdue = bool(due) and date.fromisoformat(str(due)[:10]) < as_of - timedelta(days=OVERDUE_AFTER_DAYS)
		bucket = buckets["Overdue" if overdue else "Current"]
		bucket[0] += balance
		bucket[1] += 1
	return [
		{"bucket": name, "amount": round(total, 2), "invoices": count}
		for name, (total, count) in buckets.items()
	]


# Normalised record shapes: invoices -> {date, amount, balance, due}; payments -> {date, amount}.


def _erp_invoices(erp: str, from_date: str, to_date: str) -> list[dict]:
	if erp == "acumatica":
		return acumatica_invoices(from_date, to_date)
	return erpnext_invoices(from_date, to_date)


def _erp_payments(erp: str, from_date: str, to_date: str) -> list[dict]:
	if erp == "acumatica":
		return acumatica_payments(from_date, to_date)
	return erpnext_payments(from_date, to_date)


def _acumatica_client():
	from crm.integrations.acumatica.client import AcumaticaClient

	return AcumaticaClient(frappe.get_cached_doc("CRM Acumatica Settings"))


def _acumatica_window(field: str, from_date: str, to_date: str) -> str:
	return (
		f"{field} ge datetimeoffset'{from_date}T00:00:00Z' and {field} le datetimeoffset'{to_date}T23:59:59Z'"
	)


def acumatica_invoices(from_date: str, to_date: str) -> list[dict]:
	from crm.integrations.acumatica.client import v

	client = _acumatica_client()
	rows = []
	for record in client.iter_all(
		"SalesInvoice",
		filter=_acumatica_window("Date", from_date, to_date),
		select="Date,Amount,Balance,DueDate,Type",
	):
		if str(v(record, "Type") or "").lower().startswith("credit"):
			continue
		rows.append(
			{
				"date": str(v(record, "Date") or "")[:10],
				"amount": v(record, "Amount") or 0,
				"balance": v(record, "Balance") or 0,
				"due": str(v(record, "DueDate") or "")[:10] or None,
			}
		)
		if len(rows) >= ERP_ROW_CAP:
			break
	return rows


def acumatica_payments(from_date: str, to_date: str) -> list[dict]:
	from crm.integrations.acumatica.client import v

	client = _acumatica_client()
	rows = []
	for record in client.iter_all(
		"Payment",
		filter=_acumatica_window("ApplicationDate", from_date, to_date),
		select="ApplicationDate,PaymentAmount,Type",
	):
		if str(v(record, "Type") or "").lower() not in ("payment", "prepayment", ""):
			continue
		rows.append(
			{"date": str(v(record, "ApplicationDate") or "")[:10], "amount": v(record, "PaymentAmount") or 0}
		)
		if len(rows) >= ERP_ROW_CAP:
			break
	return rows


def _erpnext_get(doctype: str, fields: list[str], filters: list) -> list[dict]:
	settings = frappe.get_cached_doc("ERPNext CRM Settings")
	secret = settings.get_password("api_secret", raise_exception=False) or ""
	response = requests.get(
		f"{settings.erpnext_site_url.rstrip('/')}/api/resource/{doctype}",
		params={
			"fields": json.dumps(fields),
			"filters": json.dumps(filters),
			"limit_page_length": ERP_ROW_CAP,
		},
		headers={"Authorization": f"token {settings.api_key}:{secret}"},
		timeout=ERP_TIMEOUT,
	)
	response.raise_for_status()
	return response.json().get("data") or []


def erpnext_invoices(from_date: str, to_date: str) -> list[dict]:
	records = _erpnext_get(
		"Sales Invoice",
		["posting_date", "grand_total", "outstanding_amount", "due_date", "is_return"],
		[["posting_date", "between", [from_date, to_date]], ["docstatus", "=", 1]],
	)
	return [
		{
			"date": str(r.get("posting_date") or "")[:10],
			"amount": r.get("grand_total") or 0,
			"balance": r.get("outstanding_amount") or 0,
			"due": str(r.get("due_date") or "")[:10] or None,
		}
		for r in records
		if not r.get("is_return")
	]


def erpnext_payments(from_date: str, to_date: str) -> list[dict]:
	records = _erpnext_get(
		"Payment Entry",
		["posting_date", "paid_amount", "payment_type"],
		[
			["posting_date", "between", [from_date, to_date]],
			["docstatus", "=", 1],
			["payment_type", "=", "Receive"],
		],
	)
	return [
		{"date": str(r.get("posting_date") or "")[:10], "amount": r.get("paid_amount") or 0} for r in records
	]
