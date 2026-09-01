# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The Analyst's pure half: what it may compute, how a model's plan is tamed,
and the prompts. Rows in, messages out. No frappe.

The Analyst never writes SQL and never invents a number. It works in two
model calls around one deterministic step:

1. *Plan* -- the model picks metrics from :data:`CATALOGUE` and a period
   (guided decoding into ``AnalystPlan``). :func:`normalise_plan` then drops
   anything not in the catalogue, caps the count, and defaults the period,
   so an unusable plan degrades to :func:`fallback_plan` instead of failing.
2. *Run* -- the caller (``analyst_data``) computes the tables from the
   metrics layer under the admin's own permissions.
3. *Answer* -- the model narrates the figures block. The system prompt says
   every number must come from it. The UI shows the computed tables beside
   the narrative, so the words are the model's and the numbers are not.

Everything a user reads as a figure therefore traces to code; the model only
chooses and explains. That is the whole design, and the reason this module
may not import anything that knows a site exists.
"""

from __future__ import annotations

import calendar
import json
import re
from datetime import date

# --- the catalogue -----------------------------------------------------------

CRM = "crm"
ERP = "erp"


def _col(key: str, label: str, kind: str) -> dict:
	return {"key": key, "label": label, "type": kind}


CATALOGUE: dict[str, dict] = {
	"won_revenue_by_month": {
		"title": "Revenue from won deals by month",
		"description": "Closed-won deal value per month it closed in, in the base currency. "
		"The CRM's realised revenue; not invoices or cash.",
		"source": CRM,
		"columns": [_col("month", "Month", "month"), _col("value", "Won value", "currency")],
	},
	"forecast_by_month": {
		"title": "Weighted forecast by month",
		"description": "Open pipeline per expected-close month, weighted by stage probability.",
		"source": CRM,
		"columns": [_col("month", "Month", "month"), _col("value", "Weighted pipeline", "currency")],
	},
	"growth_rates": {
		"title": "Month-over-month revenue growth",
		"description": "Won revenue per month with the percentage change from the month before.",
		"source": CRM,
		"columns": [
			_col("month", "Month", "month"),
			_col("value", "Won value", "currency"),
			_col("change_pct", "Change", "percent"),
		],
	},
	"revenue_projection": {
		"title": "Revenue projection",
		"description": "A straight-line projection of won revenue for the next three months, "
		"fitted to the months in the period. A trend, not a forecast of specific deals.",
		"source": CRM,
		"columns": [
			_col("month", "Month", "month"),
			_col("value", "Value", "currency"),
			_col("kind", "Actual or projected", "text"),
		],
	},
	"pipeline_by_stage": {
		"title": "Open pipeline by stage",
		"description": "Open deals, their value and probability-weighted value per stage, as of now.",
		"source": CRM,
		"columns": [
			_col("stage", "Stage", "text"),
			_col("deals", "Deals", "int"),
			_col("value", "Value", "currency"),
			_col("weighted", "Weighted", "currency"),
		],
	},
	"funnel_conversion": {
		"title": "Funnel conversion",
		"description": "How many records reached each stage of the lead-to-won funnel in the period.",
		"source": CRM,
		"columns": [_col("stage", "Stage", "text"), _col("count", "Count", "int")],
	},
	"quota_attainment_by_rep": {
		"title": "Quota attainment by rep",
		"description": "Each rep's closed-won revenue against their monthly targets for the period.",
		"source": CRM,
		"columns": [
			_col("rep", "Rep", "text"),
			_col("quota", "Target", "currency"),
			_col("actual", "Won", "currency"),
			_col("attainment_pct", "Attainment", "percent"),
		],
	},
	"deals_at_risk": {
		"title": "Deals at risk",
		"description": "Open deals whose health score is below the at-risk line, with the reasons.",
		"source": CRM,
		"columns": [
			_col("deal", "Deal", "text"),
			_col("organization", "Organization", "text"),
			_col("owner", "Owner", "text"),
			_col("health_score", "Health", "int"),
			_col("value", "Value", "currency"),
			_col("reasons", "Reasons", "text"),
		],
	},
	"accounts_going_quiet": {
		"title": "Accounts going quiet",
		"description": "Organizations whose open deals show a slowing contact cadence or a close date "
		"at risk -- the accounts to maintain before they go cold.",
		"source": CRM,
		"columns": [
			_col("organization", "Organization", "text"),
			_col("deals", "Open deals", "int"),
			_col("days_since_contact", "Days since contact", "int"),
			_col("lowest_health", "Lowest health", "int"),
			_col("reason", "Reason", "text"),
		],
	},
	"sales_trend": {
		"title": "Leads, deals and wins by month",
		"description": "New leads, new deals and won deals per month in the period.",
		"source": CRM,
		"columns": [
			_col("month", "Month", "month"),
			_col("leads", "Leads", "int"),
			_col("deals", "Deals", "int"),
			_col("won_deals", "Won", "int"),
		],
	},
	"leads_by_source": {
		"title": "Leads by source",
		"description": "Where the period's leads came from.",
		"source": CRM,
		"columns": [_col("source", "Source", "text"), _col("count", "Leads", "int")],
	},
	"deals_by_industry": {
		"title": "Deals by industry",
		"description": "Deal count and value per industry for the period.",
		"source": CRM,
		"columns": [
			_col("industry", "Industry", "text"),
			_col("deals", "Deals", "int"),
			_col("value", "Value", "currency"),
		],
	},
	"deals_by_territory": {
		"title": "Deals by territory",
		"description": "Deal count and value per territory for the period.",
		"source": CRM,
		"columns": [
			_col("territory", "Territory", "text"),
			_col("deals", "Deals", "int"),
			_col("value", "Value", "currency"),
		],
	},
	"deals_by_salesperson": {
		"title": "Deals by rep",
		"description": "Deal count and value per rep for the period.",
		"source": CRM,
		"columns": [
			_col("salesperson", "Rep", "text"),
			_col("deals", "Deals", "int"),
			_col("value", "Value", "currency"),
		],
	},
	"plan_adherence_by_rep": {
		"title": "Plan adherence by rep",
		"description": "Planned activities done versus missed per rep for the period.",
		"source": CRM,
		"columns": [
			_col("rep", "Rep", "text"),
			_col("planned", "Planned", "int"),
			_col("done", "Done", "int"),
			_col("missed", "Missed", "int"),
			_col("adherence_pct", "Adherence", "percent"),
		],
	},
	"average_deal_value": {
		"title": "Average deal value",
		"description": "Average value of deals in the period, and the change against the period before.",
		"source": CRM,
		"columns": [_col("metric", "Metric", "text"), _col("value", "Value", "currency")],
	},
	"time_to_close": {
		"title": "Average time to close a deal",
		"description": "Average days from a deal's creation to its close for deals closed in the period.",
		"source": CRM,
		"columns": [_col("metric", "Metric", "text"), _col("days", "Days", "int")],
	},
	# --- ERP: present only when an integration is enabled -------------------
	"erp_invoices_by_month": {
		"title": "Invoiced by month (ERP)",
		"description": "Sales invoices issued per month in the ERP: amount and count.",
		"source": ERP,
		"columns": [
			_col("month", "Month", "month"),
			_col("invoiced", "Invoiced", "currency"),
			_col("invoices", "Invoices", "int"),
		],
	},
	"erp_payments_by_month": {
		"title": "Cash received by month (ERP)",
		"description": "Customer payments received per month in the ERP.",
		"source": ERP,
		"columns": [
			_col("month", "Month", "month"),
			_col("received", "Received", "currency"),
			_col("payments", "Payments", "int"),
		],
	},
	"erp_receivables": {
		"title": "Open receivables (ERP)",
		"description": "Unpaid invoice balances in the ERP, split into current and overdue.",
		"source": ERP,
		"columns": [
			_col("bucket", "Bucket", "text"),
			_col("amount", "Outstanding", "currency"),
			_col("invoices", "Invoices", "int"),
		],
	},
	"erp_cashflow_by_month": {
		"title": "Cashflow by month (ERP)",
		"description": "Invoiced out against cash received in per month, and the net, from the ERP.",
		"source": ERP,
		"columns": [
			_col("month", "Month", "month"),
			_col("invoiced", "Invoiced", "currency"),
			_col("received", "Received", "currency"),
			_col("net", "Net", "currency"),
		],
	},
}

MAX_METRICS = 4
DEFAULT_PERIOD_MONTHS = 12
PROJECTION_HORIZON = 3

# How much of a table the answer prompt carries. Enough to narrate a year by
# month or a team of reps; past this the model is being asked to read a
# report, not summarise one, and the UI shows the full table anyway.
FIGURES_ROW_CAP = 60


def available_keys(erp_enabled: bool) -> list[str]:
	"""Catalogue keys this site can run, in catalogue order."""
	return [key for key, metric in CATALOGUE.items() if erp_enabled or metric["source"] != ERP]


# --- dates -------------------------------------------------------------------


def add_months(day: date, months: int) -> date:
	"""``day`` moved by ``months``, clamped to the target month's last day."""
	month_index = day.month - 1 + months
	year = day.year + month_index // 12
	month = month_index % 12 + 1
	last = calendar.monthrange(year, month)[1]
	return date(year, month, min(day.day, last))


def month_key(day: date) -> str:
	return f"{day.year:04d}-{day.month:02d}"


def months_between(from_date: str, to_date: str) -> list[str]:
	"""Every ``YYYY-MM`` from the first date's month to the last's, inclusive."""
	start = date.fromisoformat(from_date).replace(day=1)
	end = date.fromisoformat(to_date).replace(day=1)
	months = []
	cursor = start
	while cursor <= end:
		months.append(month_key(cursor))
		cursor = add_months(cursor, 1)
	return months


def _parse_date(value) -> date | None:
	if not isinstance(value, str) or not value.strip():
		return None
	try:
		return date.fromisoformat(value.strip()[:10])
	except ValueError:
		return None


# --- plans -------------------------------------------------------------------

# Keyword -> metrics, first match wins per keyword group, in this order. A
# question that names nothing gets the two tables anyone asking about "the
# business" wants: what we won, and what is open.
_KEYWORD_PLANS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
	(
		("cash", "cashflow", "receivable", "invoice", "payment", "paid"),
		("erp_cashflow_by_month", "erp_receivables"),
	),
	(("quota", "target", "behind", "attainment"), ("quota_attainment_by_rep",)),
	(
		("project", "projection", "next quarter", "next month", "forecast"),
		("revenue_projection", "forecast_by_month"),
	),
	(
		("risk", "slip", "quiet", "maintain", "maintenance", "cold", "cooling"),
		("deals_at_risk", "accounts_going_quiet"),
	),
	(("grow", "growth", "trend"), ("growth_rates", "sales_trend")),
	(("pipeline", "stage"), ("pipeline_by_stage",)),
	(("funnel", "conversion", "convert"), ("funnel_conversion",)),
	(("industry", "industries", "sector"), ("deals_by_industry",)),
	(("territory", "territories", "region"), ("deals_by_territory",)),
	(("rep", "reps", "salesperson", "team"), ("deals_by_salesperson",)),
	(("source", "sources", "campaign"), ("leads_by_source",)),
	(("plan", "adherence", "planned"), ("plan_adherence_by_rep",)),
	(("average", "avg", "deal size", "deal value"), ("average_deal_value",)),
	(("close", "cycle", "how long"), ("time_to_close",)),
	(("revenue", "sales", "won", "sold"), ("won_revenue_by_month",)),
]

_DEFAULT_PLAN = ("won_revenue_by_month", "pipeline_by_stage")


def fallback_plan(question: str, available: list[str]) -> list[str]:
	"""Metrics chosen by keyword when the model's plan was unusable."""
	text = (question or "").lower()
	chosen: list[str] = []
	for keywords, metrics in _KEYWORD_PLANS:
		if any(re.search(rf"\b{re.escape(word)}", text) for word in keywords):
			for metric in metrics:
				if metric in available and metric not in chosen:
					chosen.append(metric)
	if not chosen:
		chosen = [metric for metric in _DEFAULT_PLAN if metric in available]
	return chosen[:MAX_METRICS]


def normalise_plan(plan, available: list[str], today: date, question: str = "") -> dict:
	"""A model's ``AnalystPlan`` (or ``None``) into something the data layer can run.

	Unknown or unavailable metrics are dropped, duplicates collapse, the list is
	capped at :data:`MAX_METRICS`; an empty selection falls back to keywords.
	Dates default to the last :data:`DEFAULT_PERIOD_MONTHS` months ending today,
	a reversed pair is swapped, and an unparseable one takes the default.
	"""
	requested = list(getattr(plan, "metrics", None) or [])
	metrics: list[str] = []
	for key in requested:
		if key in available and key not in metrics:
			metrics.append(key)
	if not metrics:
		metrics = fallback_plan(question, available)
	metrics = metrics[:MAX_METRICS]

	default_to = today
	default_from = add_months(today, -DEFAULT_PERIOD_MONTHS)
	start = _parse_date(getattr(plan, "from_date", "")) or default_from
	end = _parse_date(getattr(plan, "to_date", "")) or default_to
	if start > end:
		start, end = end, start
	return {"metrics": metrics, "from_date": start.isoformat(), "to_date": end.isoformat()}


# --- arithmetic --------------------------------------------------------------


def growth_rates(series: list[tuple[str, float]]) -> list[dict]:
	"""``[(month, value)]`` -> rows with the percentage change from the previous month.

	``change_pct`` is ``None`` for the first month and for any month whose base
	is zero -- a jump from nothing is not a percentage.
	"""
	rows = []
	previous = None
	for month, value in series:
		change = None
		if previous is not None and previous != 0:
			change = round((value - previous) / abs(previous) * 100, 1)
		rows.append({"month": month, "value": value, "change_pct": change})
		previous = value
	return rows


def project_revenue(series: list[tuple[str, float]], horizon: int = PROJECTION_HORIZON) -> dict:
	"""Least-squares line over a monthly series, continued ``horizon`` months.

	Returns the actual points followed by the projected ones, the fitted slope
	per month, and a one-line description of the method for the caveats. With
	fewer than two points there is no line, so nothing is projected. Values are
	clamped at zero: revenue does not go negative, and a falling line that
	crosses the axis is telling you the trend is down, not that you will pay
	customers.
	"""
	points = [{"month": month, "value": float(value), "kind": "actual"} for month, value in series]
	n = len(series)
	if n < 2:
		return {"points": points, "slope_per_month": 0.0, "method": "not enough months to fit a trend"}

	xs = list(range(n))
	ys = [float(value) for _month, value in series]
	mean_x = sum(xs) / n
	mean_y = sum(ys) / n
	denominator = sum((x - mean_x) ** 2 for x in xs)
	slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / denominator
	intercept = mean_y - slope * mean_x

	last = date.fromisoformat(f"{series[-1][0]}-01")
	for step in range(1, horizon + 1):
		projected = max(0.0, intercept + slope * (n - 1 + step))
		points.append(
			{"month": month_key(add_months(last, step)), "value": round(projected, 2), "kind": "projected"}
		)
	return {
		"points": points,
		"slope_per_month": round(slope, 2),
		"method": f"least squares over {n} months",
	}


# --- prompts -----------------------------------------------------------------

PLAN_SYSTEM_PROMPT = (
	"You are the Analyst for Vectora, a CRM. An administrator asks a question about the "
	"business. Choose which of the available calculations answer it, and the date range. "
	"You cannot run queries or see data at this step: you only pick from the list. Pick the "
	"fewest calculations that answer the question (at most {max_metrics}). Dates are "
	"YYYY-MM-DD; today is {today}. If the question names no period, leave both dates empty "
	"and the last twelve months are used. Reply only with JSON matching the schema: "
	"`metrics` is a list of calculation keys exactly as listed, `from_date` and `to_date` "
	"are dates or empty strings, `reasoning` is one short sentence."
)

ANSWER_SYSTEM_PROMPT = (
	"You are the Analyst for Vectora, a CRM. Vectora has already computed the figures below "
	"for the administrator's question; they are the only truth you have. Write a short, "
	"plain-language analysis for a business owner. Every number in your answer must appear "
	"in the FIGURES block; do not compute new totals, do not estimate, and do not describe "
	"data that is not there. If the figures do not answer the question, say 'The data does "
	"not cover that.' and say what they do show. Where a table is marked unavailable, say "
	"that source could not be reached. Figures from the CRM are realised deal value, not "
	"cash; figures marked ERP are invoices and payments from the accounting system. "
	"Reply only with JSON matching the schema: `answer` is plain text (no markdown "
	"headings, no tables); `highlights` are up to 5 one-line findings, each carrying its "
	"figure; `caveats` are up to 3 one-line limits of the data."
)

HISTORY_TURN_LIMIT = 6
HISTORY_CHAR_CAP = 1500


def build_plan_messages(
	question: str, available_metrics: list[dict], today: date, history: list[dict] | None = None
) -> list[dict]:
	"""System prompt with the catalogue, prior turns, then the question."""
	listing = "\n".join(
		f"- `{metric['key']}` ({'ERP' if metric['source'] == ERP else 'CRM'}): {metric['description']}"
		for metric in available_metrics
	)
	system = PLAN_SYSTEM_PROMPT.format(max_metrics=MAX_METRICS, today=today.isoformat())
	messages = [{"role": "system", "content": f"{system}\n\n# Available calculations\n{listing}"}]
	messages.extend(_usable_history(history))
	messages.append({"role": "user", "content": question})
	return messages


def catalogue_entries(keys: list[str]) -> list[dict]:
	"""Catalogue rows for the prompt, with their keys."""
	return [{"key": key, **CATALOGUE[key]} for key in keys if key in CATALOGUE]


def build_answer_messages(
	question: str, tables: list[dict], period: dict, history: list[dict] | None = None
) -> list[dict]:
	"""System prompt with the figures block, prior turns, then the question."""
	figures = _figures_block(tables, period)
	messages = [{"role": "system", "content": f"{ANSWER_SYSTEM_PROMPT}\n\n{figures}"}]
	messages.extend(_usable_history(history))
	messages.append({"role": "user", "content": question})
	return messages


def _figures_block(tables: list[dict], period: dict) -> str:
	lines = [f"# FIGURES (period {period.get('from_date', '')} to {period.get('to_date', '')})"]
	for table in tables:
		source = table.get("source", "CRM")
		lines.append(f"\n## {table.get('title', table.get('key', ''))} [{source}]")
		if table.get("note"):
			lines.append(table["note"])
		if table.get("error"):
			lines.append(f"UNAVAILABLE: this source could not be reached ({table['error']}).")
			continue
		rows = table.get("rows") or []
		if not rows:
			lines.append("(no rows in the period)")
			continue
		shown = rows[:FIGURES_ROW_CAP]
		lines.append(json.dumps(shown, default=str, ensure_ascii=False))
		if len(rows) > len(shown):
			lines.append(f"({len(rows) - len(shown)} more rows not shown)")
	return "\n".join(lines)


def _usable_history(history: list[dict] | None) -> list[dict]:
	turns = []
	for turn in history or []:
		if not isinstance(turn, dict):
			continue
		role = turn.get("role")
		content = turn.get("content")
		if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
			continue
		turns.append({"role": role, "content": content[:HISTORY_CHAR_CAP]})
	return turns[-HISTORY_TURN_LIMIT:]
