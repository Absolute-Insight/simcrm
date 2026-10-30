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
import time
from collections import defaultdict
from datetime import date, timedelta

import frappe
import requests

from crm.agent import analyst, analyst_facts
from crm.agent.config import get_signal_config
from crm.agent.predict import AT_RISK_BELOW, COOLING_RATIO
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

# What a table says about itself when a read stopped part-way: the clock ran out,
# or the read reached ERP_ROW_CAP with documents still to come. It goes in the
# table's ``note``, which the answer prompt carries into the figures block, so the
# narrative can say the number is a floor rather than a total.
PARTIAL_NOTE = (
	"PARTIAL: this source was not read to the end -- the request ran out of time, or the "
	f"read reached its limit of {ERP_ROW_CAP:,} documents; the figures below cover only what had been read."
)
SKIPPED_NOTE = "the request ran out of time before this table was computed"


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


def run_plan(
	plan: dict, erp: str | None, deadline: float | None = None, today: date | None = None
) -> list[dict]:
	"""Compute one table per metric in ``plan["metrics"]``, in order.

	Unknown keys are skipped (the pure half already dropped them; this is the
	belt to its braces). ERP metrics with no ERP enabled are skipped too.

	``deadline`` is the caller's absolute ``time.monotonic()`` limit for the
	whole web request -- the same one the two completions share. This step used
	to run with no clock at all between them: invoice and payment reads page 100
	rows at a time up to 5,000, each page a 30-second request, while deal
	scoring runs in the same worker. One cashflow question could hold a worker
	and one of four site-wide model slots for minutes, long after nginx had
	returned a 504 and the admin had been told the model could not be reached.

	Past the deadline a table is reported as unavailable rather than computed,
	and an ERP read that is already running stops paging; either way the answer
	is a partial one that says so, which is a better answer than a timeout.

	Each table carries ``facts``: its totals, quarters, extremes and ranking,
	worked out here so the model quotes them instead of adding rows up
	(:func:`analyst_facts.table_facts`). ``today`` is the caller's: pass the one
	the grounding check will use.
	"""
	# the caller's today, read once: the grounding check decides which month is
	# partial from the same value, and a second read can land after midnight
	today = today or frappe.utils.getdate()
	tables = _run_tables(plan, erp, deadline, today)
	for table in tables:
		table["facts"] = analyst_facts.table_facts(table, today)
	return tables


def data_start() -> str | None:
	"""``YYYY-MM`` of the earliest deal the site holds, by creation or close; ``None`` with no deals.

	Site-wide on purpose: it describes what the CRM knows, not what this admin may
	see, and the Analyst is System Manager only.
	"""
	created, closed = frappe.db.sql("select min(creation), min(closed_date) from `tabCRM Deal`")[0]
	dates = [frappe.utils.getdate(value) for value in (created, closed) if value]
	return analyst.month_key(min(dates)) if dates else None


# Monthly CRM history tables: months before the site's data are dropped, not shown as 0.
_HISTORY_TABLES = ("won_revenue_by_month", "growth_rates")


def _run_tables(plan: dict, erp: str | None, deadline: float | None, today: date) -> list[dict]:
	from_date, to_date = plan["from_date"], plan["to_date"]
	starts = data_start()
	tables = []
	for key in plan.get("metrics", []):
		metric = analyst.CATALOGUE.get(key)
		if not metric:
			continue
		is_erp = metric["source"] == analyst.ERP
		if is_erp and not erp:
			continue
		runner = None if is_erp else _CRM_RUNNERS.get(key)
		if not is_erp and not runner:
			continue
		label = ERP_LABELS[erp] if is_erp else "CRM"
		if _out_of_time(deadline):
			tables.append(_table(key, metric, label, [], from_date, to_date, "", error=SKIPPED_NOTE))
			continue
		if is_erp:
			tables.append(_erp_table(key, metric, erp, from_date, to_date, today, deadline))
			continue
		rows, note = runner(from_date, to_date)
		if key in _HISTORY_TABLES:
			rows, coverage = analyst_facts.trim_to_coverage(rows, starts)
			note = f"{note} {coverage}".strip()
		table = _table(key, metric, "CRM", rows, from_date, to_date, note)
		if key in _ROW_LISTS:
			# the model gets the counting done for it and the head of the list; the
			# screen gets every row (#237)
			table["model_rows"] = analyst.ROW_LIST_MODEL_ROWS
			summarise = _ROW_LISTS[key]
			if summarise:
				table["summary"] = summarise(rows)
		tables.append(table)
	return tables


def _out_of_time(deadline: float | None) -> bool:
	return deadline is not None and time.monotonic() >= deadline


def _time_for_a_page(deadline: float | None) -> bool:
	"""Whether there is room for one more ERP page before the deadline.

	One page is one HTTP request bounded by :data:`ERP_TIMEOUT`, so a page
	started with less than that left is a page that can outlive the request it
	belongs to. Checking *before* the fetch is the only check that helps: the
	generator has already paid for a page by the time its rows arrive.
	"""
	return deadline is None or (deadline - time.monotonic()) >= ERP_TIMEOUT


# Tables that are lists of records rather than aggregates, and what counts them.
_ROW_LISTS = {"deals_at_risk": analyst.summarise_at_risk, "accounts_going_quiet": None}


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

	# history only: a month that has not happened is unknown, not zero
	to_date = min(str(to_date), frappe.utils.nowdate())
	by_month = actual_by_month(from_date, to_date)
	return [(month, float(by_month.get(month, 0.0))) for month in analyst.months_between(from_date, to_date)]


def _to_date_note(series) -> str:
	"""A current-month figure is a partial month; a table that shows it next to
	whole months has to say so, or a -44% for eighteen days reads as a collapse."""
	current = analyst.month_key(frappe.utils.getdate(frappe.utils.nowdate()))
	if any(month == current for month, _ in series):
		return f" {analyst.month_label(current)} is month to date."
	return ""


def _won_revenue_by_month(from_date, to_date):
	series = _won_series(from_date, to_date)
	rows = [{"month": month, "value": value} for month, value in series]
	return rows, "Closed-won deal value in the base currency, by the month the deal closed." + _to_date_note(
		series
	)


def _forecast_by_month(from_date, to_date):
	from crm.api.dashboard import forecast_by_month

	by_month = forecast_by_month(from_date, to_date)
	rows = [{"month": month, "value": float(value or 0)} for month, value in sorted(by_month.items())]
	return rows, "Open pipeline weighted by stage probability, by expected close month."


def _history(from_date, to_date) -> tuple[str, str]:
	return analyst.history_window(str(from_date), str(to_date), frappe.utils.getdate(frappe.utils.nowdate()))


def _growth_rates(from_date, to_date):
	series = _won_series(*_history(from_date, to_date))
	return analyst.growth_rates(series), "Change is against the previous month." + _to_date_note(series)


def _revenue_projection(from_date, to_date):
	today = frappe.utils.getdate(frappe.utils.nowdate())
	window = analyst.history_window(
		str(from_date), str(to_date), today, min_months=analyst.PROJECTION_MIN_MONTHS
	)
	series = _won_series(*window)
	fit = analyst.trend_series(series, today)
	current = analyst.month_key(today)
	to_date_row = next(
		({"month": m, "value": v, "kind": "month to date"} for m, v in series if m == current), None
	)
	projection = analyst.project_revenue(fit, after=current if to_date_row else None)
	points = projection["points"]
	if to_date_row:
		# the current month is shown for what it is, and averaged into nothing
		points = (
			[p for p in points if p["kind"] == "actual"]
			+ [to_date_row]
			+ [p for p in points if p["kind"] == "projected"]
		)
	note = (
		f"Projected months are the {projection['method']}; the current month is shown to date "
		"and not included. A run rate, not booked deals."
	)
	return points, note


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
				# get_fullname() substitutes the *session* user when its argument is
				# falsy, so an ownerless deal used to be reported under the name of
				# whoever asked -- an admin reading "twelve of your deals are at
				# risk" about deals nobody owns.
				"owner": frappe.utils.get_fullname(detail.get("deal_owner"))
				if detail.get("deal_owner")
				else "",
				"health_score": int(row["score"]),
				"value": float(detail.get("deal_value") or 0) * float(detail.get("exchange_rate") or 1),
				"reasons": "; ".join(
					factor.get("label") or factor.get("name", "") for factor in row.get("factors", [])
				),
			}
		)
	return rows, f"Health below {AT_RISK_BELOW} out of 100. Scored now, not as of the period."


def _accounts_going_quiet(from_date, to_date):
	"""Organizations whose open deals are cooling or slipping -- the maintenance list.

	Every working deal is scanned. This used to take the first 200 rows of
	``_working_deal_rows()``, which come back in CRM Deal's default order
	(``modified desc``): the 200 deals touched most recently -- precisely the
	ones not going quiet -- and the answer then presented that sample as the
	whole site. The activity helpers are batched and the health scores come from
	the dashboard's one-pass scorer, so the full scan costs what ``deals_at_risk``
	already costs.
	"""
	from crm.api.dashboard import _at_risk_deals

	now = frappe.utils.now_datetime()
	horizon = get_signal_config().close_horizon_days
	deals = _working_deal_rows()
	names = [row["name"] for row in deals]
	latest = _latest_activity(names)
	history = _activity_history(names, now - timedelta(days=CADENCE_WINDOW_DAYS))
	# Scored under the caller's own permission scope (get_list), like the
	# dashboard tile: a deal the admin may not read has no score and is skipped,
	# which is what the per-deal get_deal_health PermissionError used to do.
	health_by_deal = {row["name"]: row["score"] for row in _at_risk_deals()}

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
		health = health_by_deal.get(deal["name"])
		if health is None:
			continue
		last = latest.get(deal["name"]) or deal["creation"]
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
	return rows, (
		f"From the cadence and slip-risk signals on all {len(deals)} open deals, scored now; "
		"not equipment maintenance."
	)


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


def _tile(getter_name: str, label: str, field: str, compare: bool = False):
	def run(from_date, to_date):
		from crm.api import dashboard

		getter = getattr(dashboard, getter_name)
		value = _tile_value(getter(from_date, to_date), field)
		rows = [{"metric": label, field: value}]
		if not compare:
			return rows, ""
		# The comparison the catalogue promises. The tile's own delta is 0 both when
		# nothing changed and when the period before had nothing to average, so that
		# period is read through the same tile rather than inferred from the delta.
		prev_from, _ = dashboard.period_windows(from_date, to_date)
		prev_to = frappe.utils.add_days(from_date, -1)
		previous = _tile_value(getter(prev_from, prev_to), field)
		window = f"{frappe.utils.getdate(prev_from)} to {frappe.utils.getdate(prev_to)}"
		if not previous:
			return rows, f"Nothing to compare against: the period before ({window}) has no deals."
		rows += [
			{"metric": f"{label}, period before", field: previous},
			{"metric": "Change against the period before", field: round(value - previous, 2)},
		]
		return rows, f"The period before is {window}, the same length."

	return run


def _tile_value(tile: dict, field: str):
	value = float(tile.get("value") or 0)
	# whole days, rounded rather than truncated: an average of 12.9 days is 13
	return round(value, 2) if field == "value" else round(value)


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
	"average_deal_value": _tile("get_average_deal_value", "Average deal value", "value", compare=True),
	"time_to_close": _tile("get_average_time_to_close_a_deal", "Average days to close", "days"),
}


# --- ERP -------------------------------------------------------------------------


def _erp_table(key, metric, erp, from_date, to_date, today: date, deadline=None) -> dict:
	label = ERP_LABELS[erp]
	# documents exist up to today: a month after it is unknown, not one with nothing in it
	end = min(str(to_date), today.isoformat())
	months = analyst.months_between(from_date, end) if from_date <= end else []
	partial = False
	try:
		invoices = payments = None
		if key == "erp_receivables":
			# a balance now, not a flow inside the period: every open invoice, whatever its date
			invoices, cut = _erp_open_invoices(erp, deadline)
			partial = partial or cut
		if months and key in ("erp_invoices_by_month", "erp_cashflow_by_month"):
			invoices, cut = _erp_invoices(erp, from_date, end, deadline)
			partial = partial or cut
		if months and key in ("erp_payments_by_month", "erp_cashflow_by_month"):
			payments, cut = _erp_payments(erp, from_date, end, deadline)
			partial = partial or cut
	except Exception as exc:
		frappe.log_error(title="CRM analyst ERP read failed", message=f"{erp} {key}: {exc}")
		return _table(key, metric, label, [], from_date, to_date, "", error="unreachable")

	note = f"Figures from {label}, in its own currency."
	if key != "erp_receivables":
		months, coverage = _from_first_document(months, invoices, payments, label)
		note = f"{note} {coverage}".strip()
	if key == "erp_invoices_by_month":
		rows = _sum_by_month(months, invoices, "amount", "invoiced", "invoices")
	elif key == "erp_payments_by_month":
		rows = _sum_by_month(months, payments, "amount", "received", "payments")
	elif key == "erp_receivables":
		rows = _receivables(invoices, today)
		note = (
			f"{note} Unpaid balances as of today, whatever the invoice date; overdue means more than "
			f"{OVERDUE_AFTER_DAYS} days past due."
		)
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
	if partial:
		note = f"{PARTIAL_NOTE} {note}"
	return _table(key, metric, label, rows, from_date, to_date, note)


def _from_first_document(months: list[str], invoices, payments, label: str) -> tuple[list[str], str]:
	"""``months`` from the first one any document falls in, and a note when that cut some.

	The ERP's history starts somewhere, and a month before it is unknown: shown as
	0 it reads as "nothing invoiced", the way the CRM's months before its imported
	history did (``analyst_facts.trim_to_coverage``).
	"""
	dated = {str(record.get("date") or "")[:7] for record in [*(invoices or []), *(payments or [])]}
	first = next((index for index, month in enumerate(months) if month in dated), len(months))
	if not first:
		return months, ""
	if first == len(months):
		return [], f"{label} holds no documents for this period."
	return months[first:], (
		f"{label} holds no documents in this period before {analyst.month_label(months[first])}; "
		"earlier months are not shown rather than shown as 0."
	)


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
# Each reader returns ``(rows, partial)``: ``partial`` is True when the read was
# stopped by the request deadline or by ERP_ROW_CAP rather than by the end of the data.


def _erp_invoices(erp: str, from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	if erp == "acumatica":
		return acumatica_invoices(from_date, to_date, deadline)
	return erpnext_invoices(from_date, to_date, deadline)


def _erp_open_invoices(erp: str, deadline=None) -> tuple[list[dict], bool]:
	if erp == "acumatica":
		return acumatica_open_invoices(deadline)
	return erpnext_open_invoices(deadline)


def _erp_payments(erp: str, from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	if erp == "acumatica":
		return acumatica_payments(from_date, to_date, deadline)
	return erpnext_payments(from_date, to_date, deadline)


def _acumatica_client():
	from crm.integrations.acumatica.client import AcumaticaClient

	return AcumaticaClient(frappe.get_cached_doc("CRM Acumatica Settings"))


# Released documents. On Hold, Balanced and the pending states are drafts the ERP
# has not posted; Voided and Canceled were posted and taken back. None of them is
# money invoiced or received -- the spreadsheet import draws the same line.
_ACUMATICA_RELEASED = ("open", "closed")


def _acumatica_window(field: str, from_date: str, to_date: str) -> str:
	"""The server-side filter for a document-date window, a day wider at each end.

	Acumatica holds a document date as local midnight with the tenant's offset
	(``2026-01-01T00:00:00+02:00``) and compares a ``Z`` literal as UTC, so exact
	bounds dropped the window's first local day and took in the day after its last.
	The readers cut the widened read back to the window on each document's own
	local date (:func:`_acumatica_dated`), which needs no offset at all.
	"""
	start = (date.fromisoformat(from_date) - timedelta(days=1)).isoformat()
	end = (date.fromisoformat(to_date) + timedelta(days=1)).isoformat()
	return f"{field} ge datetimeoffset'{start}T00:00:00Z' and {field} le datetimeoffset'{end}T23:59:59Z'"


def _acumatica_dated(record, field: str, window: tuple[str, str] | None) -> str | None:
	"""The document's local date when it is a released one inside ``window``, else None."""
	from crm.integrations.acumatica.client import v

	if str(v(record, "Status") or "").strip().lower() not in _ACUMATICA_RELEASED:
		return None
	day = str(v(record, field) or "")[:10]
	if window and not window[0] <= day <= window[1]:
		return None
	return day


def acumatica_invoices(from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	return _acumatica_invoices(_acumatica_window("Date", from_date, to_date), deadline, (from_date, to_date))


def acumatica_open_invoices(deadline=None) -> tuple[list[dict], bool]:
	"""Every invoice still carrying a balance, whatever its date. Open is Acumatica's
	status for a released document with a balance; a paid one is Closed."""
	return _acumatica_invoices("Status eq 'Open'", deadline)


def _acumatica_invoices(filter_: str, deadline=None, window=None) -> tuple[list[dict], bool]:
	from crm.integrations.acumatica.client import v

	client = _acumatica_client()
	rows = []
	partial = False
	for record in client.iter_all(
		"SalesInvoice", filter=filter_, select="Date,Amount,Balance,DueDate,Type,Status"
	):
		# the cap reached with documents still to come: what was read is a floor
		if len(rows) >= ERP_ROW_CAP:
			partial = True
			break
		# Checked per row, which is per *page* in effect: breaking out of the
		# generator is what stops it fetching the next page, and one page is one
		# 30-second request. Up to fifty of them fit inside a plan the caller
		# thinks it has bounded.
		if not _time_for_a_page(deadline):
			partial = True
			break
		day = _acumatica_dated(record, "Date", window)
		if day is None or str(v(record, "Type") or "").lower().startswith("credit"):
			continue
		rows.append(
			{
				"date": day,
				"amount": v(record, "Amount") or 0,
				"balance": v(record, "Balance") or 0,
				"due": str(v(record, "DueDate") or "")[:10] or None,
			}
		)
	return rows, partial


def acumatica_payments(from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	from crm.integrations.acumatica.client import v

	client = _acumatica_client()
	rows = []
	partial = False
	for record in client.iter_all(
		"Payment",
		filter=_acumatica_window("ApplicationDate", from_date, to_date),
		select="ApplicationDate,PaymentAmount,Type,Status",
	):
		if len(rows) >= ERP_ROW_CAP or not _time_for_a_page(deadline):
			partial = True
			break
		day = _acumatica_dated(record, "ApplicationDate", (from_date, to_date))
		if day is None or str(v(record, "Type") or "").lower() not in ("payment", "prepayment", ""):
			continue
		rows.append({"date": day, "amount": v(record, "PaymentAmount") or 0})
	return rows, partial


def _erpnext_get(doctype: str, fields: list[str], filters: list, deadline=None) -> list[dict]:
	"""One request for the whole window -- ERPNext pages server-side under
	``limit_page_length``, so there is nothing to stop half-way. The deadline
	bounds the single request instead of the paging.

	One row past :data:`ERP_ROW_CAP` is asked for, so :func:`_within_cap` can tell
	a window that holds exactly the cap from one that holds more."""
	settings = frappe.get_cached_doc("ERPNext CRM Settings")
	secret = settings.get_password("api_secret", raise_exception=False) or ""
	response = requests.get(
		f"{settings.erpnext_site_url.rstrip('/')}/api/resource/{doctype}",
		params={
			"fields": json.dumps(fields),
			"filters": json.dumps(filters),
			"limit_page_length": ERP_ROW_CAP + 1,
		},
		headers={"Authorization": f"token {settings.api_key}:{secret}"},
		timeout=_erpnext_timeout(deadline),
	)
	response.raise_for_status()
	return response.json().get("data") or []


def _within_cap(records: list[dict]) -> tuple[list[dict], bool]:
	"""``records`` cut to :data:`ERP_ROW_CAP`, and whether that cut any: a read the
	cap stopped is a floor, not a total."""
	return records[:ERP_ROW_CAP], len(records) > ERP_ROW_CAP


def _erpnext_timeout(deadline) -> float:
	"""``ERP_TIMEOUT``, or the time actually left, whichever is smaller."""
	if deadline is None:
		return ERP_TIMEOUT
	return max(1.0, min(float(ERP_TIMEOUT), deadline - time.monotonic()))


def erpnext_invoices(from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	return _erpnext_invoices(
		[["posting_date", "between", [from_date, to_date]], ["docstatus", "=", 1]], deadline
	)


def erpnext_open_invoices(deadline=None) -> tuple[list[dict], bool]:
	"""Every submitted invoice with something outstanding, whatever its date."""
	return _erpnext_invoices([["outstanding_amount", ">", 0], ["docstatus", "=", 1]], deadline)


def _erpnext_invoices(filters: list, deadline=None) -> tuple[list[dict], bool]:
	records, partial = _within_cap(
		_erpnext_get(
			"Sales Invoice",
			["posting_date", "grand_total", "outstanding_amount", "due_date", "is_return"],
			filters,
			deadline,
		)
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
	], partial


def erpnext_payments(from_date: str, to_date: str, deadline=None) -> tuple[list[dict], bool]:
	records, partial = _within_cap(
		_erpnext_get(
			"Payment Entry",
			["posting_date", "paid_amount", "payment_type"],
			[
				["posting_date", "between", [from_date, to_date]],
				["docstatus", "=", 1],
				["payment_type", "=", "Receive"],
			],
			deadline,
		)
	)
	return [
		{"date": str(r.get("posting_date") or "")[:10], "amount": r.get("paid_amount") or 0} for r in records
	], partial
