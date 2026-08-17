# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Compose a report from a dimension and a measure, inside the existing rails.

The five built-in reports each answer one fixed question. This answers the
combinations nobody wrote a report for -- won value by industry, average deal
size by rep, lost count by source -- without letting anyone ask a question the
metrics layer cannot answer honestly.

``reports.py`` states the rule this file has to live under: *nothing builds its
own aggregate*, because two aggregates over the same question drift and then the
dashboard and the report disagree in front of a client. A generic builder is, by
construction, a second query path -- so the rule is kept the only way it can be
here: :mod:`crm.tests.test_report_builder` asserts that for every
(dimension, measure) pair a chart or built-in report *also* computes, the two
produce identical numbers. Not a slogan; a failing test when it stops being true.

Everything else is the same rails as the dashboard, reused rather than
reimplemented:

* ``pin_user`` -- a plain Sales User is pinned to themselves and nobody may name
  a rep outside their own subtree, so the builder cannot become the one endpoint
  that reads another team's numbers;
* ``scope_deals`` -- hand-built aggregates never see frappe's
  ``permission_query_conditions``, so the caller's visibility is applied here;
* ``belongs_to`` / ``apply_territory`` -- the same definitions of "this rep's"
  and "this region's" the tiles use, so a builder row and a tile agree.

What it deliberately cannot do: name a doctype, name a column, or express a
filter. The dimensions and measures are closed registries. An admin who needs a
new one gets a registry entry and a conformance test, which is a code review --
not a query string that reaches the database.
"""

from __future__ import annotations

from dataclasses import dataclass

import frappe
from frappe import _
from frappe.query_builder import DocType
from frappe.query_builder.functions import Avg, Coalesce, Count, IfNull, Sum
from frappe.rate_limiter import rate_limit

from crm.api.dashboard import (
	apply_territory,
	belongs_to,
	company_size_bands,
	pin_user,
	scope_deals,
)
from crm.utils import sales_user_only

# Status scopes a caller may ask for. Named rather than free-form: "Open" and
# "Ongoing" together are what the product means by open pipeline, and letting a
# caller pick status types individually would let them build a "pipeline" that
# quietly excludes a stage.
STATUS_SCOPES = {
	"open": ("Open", "Ongoing"),
	"won": ("Won",),
	"lost": ("Lost",),
	"all": None,
}

UNSET_LABEL = "Unset"


@dataclass(frozen=True)
class Dimension:
	key: str
	label: str
	# Column on CRM Deal to group by. Kept as a name rather than a built column
	# so the registry stays data -- the query is assembled in one place below.
	column: str
	# When set, rows come back in this order rather than by measure descending.
	# Stage and company size are ordinal: sorting them by size would put
	# "1000+" between "11-50" and "201-500" and read as noise.
	ordered_values: str | None = None


@dataclass(frozen=True)
class Measure:
	key: str
	label: str
	# "number" | "currency" -- drives formatting, and the CSV/print path.
	type: str
	# Status types this measure is only meaningful for, or None for any scope.
	# won_value is realised revenue and means nothing over open deals.
	requires_scope: str | None = None
	description: str = ""


DIMENSIONS = {
	"stage": Dimension("stage", "Stage", "status", ordered_values="stage"),
	"source": Dimension("source", "Source", "source"),
	"industry": Dimension("industry", "Industry", "industry"),
	"company_size": Dimension(
		"company_size", "Company size", "no_of_employees", ordered_values="company_size"
	),
	"territory": Dimension("territory", "Territory", "territory"),
	"owner": Dimension("owner", "Rep", "deal_owner"),
	"lost_reason": Dimension("lost_reason", "Lost reason", "lost_reason"),
}

MEASURES = {
	"deals": Measure("deals", "Deals", "number", description="How many deals."),
	"expected_value": Measure(
		"expected_value",
		"Expected value",
		"currency",
		description="Sum of expected deal value, the forward-looking basis.",
	),
	"weighted_value": Measure(
		"weighted_value",
		"Weighted expected value",
		"currency",
		description="Expected value multiplied by each deal's probability.",
	),
	"won_value": Measure(
		"won_value",
		"Closed-won value",
		"currency",
		requires_scope="won",
		description="Realised revenue. Only meaningful over won deals.",
	),
	"avg_expected_value": Measure(
		"avg_expected_value",
		"Average expected value",
		"currency",
		description="Mean expected deal value, not the total.",
	),
}


def _ordered_values(kind: str) -> list[str]:
	if kind == "company_size":
		return company_size_bands()
	if kind == "stage":
		return frappe.get_all("CRM Deal Status", order_by="position asc", pluck="name")
	return []


def _measure_expression(measure_key: str, Deal):
	"""The aggregate for ``measure_key``.

	``expected_deal_value`` for anything forward-looking and ``deal_value`` for
	realised revenue -- the split SPEC.md draws, and the reason ``won_value`` is
	its own measure rather than ``expected_value`` filtered to Won.
	"""
	forward = Deal.expected_deal_value * IfNull(Deal.exchange_rate, 1)
	realised = Coalesce(Deal.deal_value, 0) * IfNull(Deal.exchange_rate, 1)
	return {
		"deals": Count(Deal.name),
		"expected_value": Sum(forward),
		"weighted_value": Sum(forward * IfNull(Deal.probability, 0) / 100),
		"won_value": Sum(realised),
		"avg_expected_value": Avg(forward),
	}[measure_key]


def build_rows(
	dimension: str,
	measure: str,
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	territory: str | None = None,
	status_scope: str = "open",
	date_field: str | None = None,
) -> list[dict]:
	"""Group deals by ``dimension`` and aggregate ``measure`` over them.

	``date_field`` names the column a period applies to. Left out, the answer is
	the pipeline as it stands now -- which is what "open pipeline by industry"
	means, and why applying a period to it by default would silently answer a
	different question.
	"""
	dim = DIMENSIONS[dimension]
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	column = Deal[dim.column]
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(column.as_("label"), _measure_expression(measure, Deal).as_("value"))
		.groupby(column)
	)

	status_types = STATUS_SCOPES[status_scope]
	if status_types:
		query = query.where(Status.type.isin(list(status_types)))
	if date_field and from_date and to_date:
		query = query.where(Deal[date_field].between(from_date, f"{to_date} 23:59:59"))
	if user:
		query = query.where(belongs_to(Deal, user, "CRM Deal"))
	query = apply_territory(query, Deal, territory)
	query = scope_deals(query)

	rows = [{"label": row[0], "value": row[1] or 0} for row in query.run()]
	return _label_and_order(rows, dim)


def _label_and_order(rows: list[dict], dim: Dimension) -> list[dict]:
	"""Name the unanswered bucket, and order ordinal dimensions by their order.

	``IfNull`` cannot see a stored empty string, and Frappe writes ``''`` rather
	than NULL for an untouched Data/Select field -- so relabelling happens here in
	Python rather than in SQL. Left to the database, a company-size chart reported
	every unanswered deal as the first band, which reads as a fact about the
	pipeline rather than a gap in it.
	"""
	for row in rows:
		if not (row["label"] or "").strip() if isinstance(row["label"], str) else not row["label"]:
			row["label"] = _(UNSET_LABEL)

	if dim.ordered_values:
		order = _ordered_values(dim.ordered_values)
		position = {name: index for index, name in enumerate(order)}
		# Anything not in the declared order (including Unset) sorts after it,
		# alphabetically, rather than being dropped -- a row the ordering does not
		# recognise is still a row of real deals.
		rows.sort(key=lambda r: (position.get(r["label"], len(order)), str(r["label"])))
	else:
		rows.sort(key=lambda r: (-(r["value"] or 0), str(r["label"])))
	return rows


def describe() -> dict:
	"""The registries, translated, for the builder UI to render."""
	return {
		"dimensions": [{"key": d.key, "label": _(d.label)} for d in DIMENSIONS.values()],
		"measures": [
			{
				"key": m.key,
				"label": _(m.label),
				"type": m.type,
				"requires_scope": m.requires_scope,
				"description": _(m.description) if m.description else "",
			}
			for m in MEASURES.values()
		],
		"status_scopes": [
			{"key": "open", "label": _("Open pipeline")},
			{"key": "won", "label": _("Closed won")},
			{"key": "lost", "label": _("Closed lost")},
			{"key": "all", "label": _("All deals")},
		],
	}


@frappe.whitelist()
@sales_user_only
def get_builder_options():
	return describe()


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=60, seconds=60)
def run(
	dimension: str,
	measure: str,
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	territory: str | None = None,
	status_scope: str = "open",
	date_field: str | None = None,
):
	"""Run one built report.

	Every argument is validated against a registry before it reaches a query.
	``dimension`` and ``measure`` become column names, so an unchecked value here
	would be the one place in the metrics layer a caller picks the SQL.
	"""
	if dimension not in DIMENSIONS:
		frappe.throw(_("Unknown dimension: {0}").format(dimension))
	if measure not in MEASURES:
		frappe.throw(_("Unknown measure: {0}").format(measure))
	if status_scope not in STATUS_SCOPES:
		frappe.throw(_("Unknown status scope: {0}").format(status_scope))
	# Only these two columns may carry a period. `date_field` is a column name;
	# anything else reaching the query builder is a caller choosing a column.
	if date_field and date_field not in ("creation", "closed_date"):
		frappe.throw(_("A period can only be applied to creation or closed date."))

	required = MEASURES[measure].requires_scope
	if required and status_scope != required:
		# Silently switching the scope would answer a different question than the
		# one asked; refusing says which question this measure can answer.
		frappe.throw(
			_("{0} is only meaningful over {1} deals.").format(_(MEASURES[measure].label), _(required))
		)

	user = pin_user(user)

	rows = build_rows(
		dimension=dimension,
		measure=measure,
		from_date=from_date,
		to_date=to_date,
		user=user,
		territory=territory,
		status_scope=status_scope,
		date_field=date_field,
	)
	dim, mea = DIMENSIONS[dimension], MEASURES[measure]
	return {
		"title": _("{0} by {1}").format(_(mea.label), _(dim.label).lower()),
		"columns": [
			{"key": "label", "label": _(dim.label), "type": "text"},
			{"key": "value", "label": _(mea.label), "type": mea.type},
		],
		"rows": rows,
		"dimension": dimension,
		"measure": measure,
		"status_scope": status_scope,
		"territory": territory or None,
		# Every dimension here is a column on CRM Deal, so a territory filter
		# reaches all of them -- unlike the built-in reports, two of which cannot
		# honour it and say so.
		"territory_filtered": bool(territory),
	}
