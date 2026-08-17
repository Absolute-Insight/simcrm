import json
from datetime import timedelta

import frappe
from frappe import _
from frappe.query_builder import Case, DocType
from frappe.query_builder.functions import Avg, Coalesce, Count, Date, DateFormat, IfNull, Sum
from frappe.rate_limiter import rate_limit
from frappe.utils import add_days, date_diff, flt, get_first_day, get_last_day, getdate, nowdate
from pypika.functions import Function

from crm.fcrm.doctype.crm_dashboard.crm_dashboard import create_default_manager_dashboard
from crm.utils import sales_user_only


# Custom function for TIMESTAMPDIFF (MySQL/MariaDB)
class TimestampDiff(Function):
	def __init__(self, unit, start, end, **kwargs):
		super().__init__("TIMESTAMPDIFF", unit, start, end, **kwargs)


def scope_deals(query):
	"""Narrow a deal aggregate to the deals the caller may actually read.

	Aggregates are hand-built queries, so the ``permission_query_conditions`` hook
	frappe applies to ``get_list`` never reaches them. Without this an in-hierarchy
	Sales Manager reads org-wide money out of a tile while the deal list beside it
	shows only their subtree — two numbers for the same question.
	"""
	return _scope(query, "CRM Deal")


def scope_leads(query):
	"""The lead-side counterpart of :func:`scope_deals`."""
	return _scope(query, "CRM Lead")


def _scope(query, doctype: str):
	# the private builder, not the public string wrapper: it returns a pypika
	# criterion that composes with a query builder query, and the public one
	# stringifies it for frappe's own SQL layer
	from crm.permissions.org_hierarchy import _permission_query_conditions

	cond = _permission_query_conditions(frappe.session.user, doctype)
	return query.where(cond) if cond else query


def belongs_to(table, user: str, doctype: str):
	"""The criterion for "this rep's records": owned by them, or assigned to them.

	The lead and deal lists have always meant it this way — ``org_hierarchy``'s
	permission condition is ``owner == user OR assigned by an open ToDo``. A tile
	filtered on the owner field alone therefore shows a rep fewer deals than the
	list immediately beside it, which is precisely the two-answers-to-one-question
	failure the one-source-of-numbers rule exists to prevent.
	"""
	return belongs_to_any(table, [user], doctype)


def belongs_to_any(table, users: list[str], doctype: str):
	""":func:`belongs_to` for a set of reps — "belongs to anyone in this team".

	Same definition of belonging, so a team total is exactly the union of its
	members' tiles and never a differently-shaped number. A deal owned by one
	member and assigned to another is counted once: this is a criterion on the
	deal row, not a sum over per-rep totals, which is why the team aggregate
	cannot be recovered by adding the rep ones up.
	"""
	owner_field = {"CRM Deal": "deal_owner", "CRM Lead": "lead_owner"}[doctype]
	Todo = frappe.qb.DocType("ToDo").as_("_belongs_todo")
	assigned = table.name.isin(
		frappe.qb.from_(Todo)
		.select(Todo.reference_name)
		.where(
			(Todo.reference_type == doctype) & (Todo.status != "Cancelled") & (Todo.allocated_to.isin(users))
		)
	)
	return (table[owner_field].isin(users)) | assigned


def pin_user(user: str | None) -> str | None:
	"""Resolve a caller-supplied ``user`` filter to one they are allowed to read.

	A plain Sales User is pinned to themselves, as before. The gap this closes is
	everyone else: the parameter was taken at face value for anyone holding
	Sales Manager, so an in-tree manager -- restricted to their own subtree for
	every deal aggregate on the page -- could name a rep from another team and
	read their figures, quota target included.

	Out-of-subtree requests raise rather than falling back to the caller's own
	numbers: silently answering a different question than the one asked is how
	a wrong number ends up in front of a client.
	"""
	roles = frappe.get_roles(frappe.session.user)
	is_manager = "Sales Manager" in roles or "System Manager" in roles

	if "Sales User" in roles and not is_manager:
		return frappe.session.user

	if not user:
		return None

	reps = visible_reps()
	if reps is not None and user not in reps:
		frappe.throw(_("You are not permitted to read {0}'s figures.").format(user), frappe.PermissionError)
	return user


def visible_reps() -> list[str] | None:
	"""Users whose plans and targets the caller may read, or ``None`` for everyone.

	Plan and quota aggregates are keyed on a user rather than on a deal, so they
	cannot go through :func:`scope_deals`; they get the same subtree from the
	hierarchy instead, so a manager's rep table and their deal tiles cover the
	same people.
	"""
	from crm.permissions.org_hierarchy import _in_hierarchy, _team_mem_query, hierarchy_enabled

	user = frappe.session.user
	if user == "Administrator":
		return None

	roles = frappe.get_roles(user)
	if "System Manager" in roles:
		return None

	if hierarchy_enabled() and _in_hierarchy(user):
		return [user, *(_team_mem_query(user).run(pluck=True) or [])]

	if "Sales Manager" in roles:
		return None

	return [user]


@frappe.whitelist()
def reset_to_default():
	frappe.only_for("System Manager", True)
	create_default_manager_dashboard(force=True)


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=60, seconds=60)
def get_dashboard(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get the dashboard data for the CRM dashboard.
	"""

	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	user = pin_user(user)

	dashboard = frappe.db.exists("CRM Dashboard", "Manager Dashboard")

	layout = []

	if not dashboard:
		layout = json.loads(create_default_manager_dashboard())
		frappe.db.commit()
	else:
		layout = json.loads(frappe.db.get_value("CRM Dashboard", "Manager Dashboard", "layout") or "[]")

	for l in layout:
		chart = CHARTS.get(l["name"])
		l["data"] = chart(from_date=from_date, to_date=to_date, user=user) if chart else None

	return layout


@frappe.whitelist()
@sales_user_only
@rate_limit(limit=60, seconds=60)
def get_chart(
	name: str, type: str, from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get number chart data for the dashboard.
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	user = pin_user(user)

	chart = CHARTS.get(name)
	if not chart:
		return {"error": _("Invalid chart name")}
	return chart(from_date=from_date, to_date=to_date, user=user)


def get_total_leads(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get lead count for the dashboard.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Lead = DocType("CRM Lead")

	# Build conditions for current period
	current_cond = (Lead.creation >= from_date) & (Lead.creation < to_date_plus_one)
	if user:
		current_cond = current_cond & belongs_to(Lead, user, "CRM Lead")

	# Build conditions for previous period
	prev_cond = (Lead.creation >= prev_from_date) & (Lead.creation < from_date)
	if user:
		prev_cond = prev_cond & belongs_to(Lead, user, "CRM Lead")

	# Build query with CASE expressions
	query = frappe.qb.from_(Lead).select(
		Count(Case().when(current_cond, Lead.name).else_(None)).as_("current_month_leads"),
		Count(Case().when(prev_cond, Lead.name).else_(None)).as_("prev_month_leads"),
	)

	query = scope_leads(query)

	result = query.run(as_dict=True)

	current_month_leads = result[0].current_month_leads or 0
	prev_month_leads = result[0].prev_month_leads or 0

	delta_in_percentage = (
		(current_month_leads - prev_month_leads) / prev_month_leads * 100 if prev_month_leads else 0
	)

	return {
		"title": _("Total leads"),
		"tooltip": _("Total number of leads"),
		"value": current_month_leads,
		"delta": delta_in_percentage,
		"deltaSuffix": "%",
	}


def get_ongoing_deals(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get ongoing deal count for the dashboard, and also calculate average deal value for ongoing deals.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build conditions for current period
	current_cond = (
		(Deal.creation >= from_date)
		& (Deal.creation < to_date_plus_one)
		& (Status.type.notin(["Won", "Lost"]))
	)
	if user:
		current_cond = current_cond & belongs_to(Deal, user, "CRM Deal")

	# Build conditions for previous period
	prev_cond = (
		(Deal.creation >= prev_from_date) & (Deal.creation < from_date) & (Status.type.notin(["Won", "Lost"]))
	)
	if user:
		prev_cond = prev_cond & belongs_to(Deal, user, "CRM Deal")

	# Build query with CASE expressions
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Count(Case().when(current_cond, Deal.name).else_(None)).as_("current_month_deals"),
			Count(Case().when(prev_cond, Deal.name).else_(None)).as_("prev_month_deals"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_month_deals = result[0].current_month_deals or 0
	prev_month_deals = result[0].prev_month_deals or 0

	delta_in_percentage = (
		(current_month_deals - prev_month_deals) / prev_month_deals * 100 if prev_month_deals else 0
	)

	return {
		"title": _("Ongoing deals"),
		"tooltip": _("Total number of non won/lost deals"),
		"value": current_month_deals,
		"delta": delta_in_percentage,
		"deltaSuffix": "%",
	}


def get_average_ongoing_deal_value(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get ongoing deal count for the dashboard, and also calculate average deal value for ongoing deals.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build conditions for current period
	current_cond = (
		(Deal.creation >= from_date)
		& (Deal.creation < to_date_plus_one)
		& (Status.type.notin(["Won", "Lost"]))
	)
	if user:
		current_cond = current_cond & belongs_to(Deal, user, "CRM Deal")

	# Build conditions for previous period
	prev_cond = (
		(Deal.creation >= prev_from_date) & (Deal.creation < from_date) & (Status.type.notin(["Won", "Lost"]))
	)
	if user:
		prev_cond = prev_cond & belongs_to(Deal, user, "CRM Deal")

	# Calculate deal value with exchange rate
	deal_value_expr = Deal.deal_value * IfNull(Deal.exchange_rate, 1)

	# Build query with CASE expressions
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Avg(Case().when(current_cond, deal_value_expr).else_(None)).as_("current_month_avg_value"),
			Avg(Case().when(prev_cond, deal_value_expr).else_(None)).as_("prev_month_avg_value"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_month_avg_value = result[0].current_month_avg_value or 0
	prev_month_avg_value = result[0].prev_month_avg_value or 0

	avg_value_delta = current_month_avg_value - prev_month_avg_value if prev_month_avg_value else 0

	return {
		"title": _("Avg. ongoing deal value"),
		"tooltip": _("Average deal value of non won/lost deals"),
		"value": current_month_avg_value,
		"delta": avg_value_delta,
		"prefix": get_base_currency_symbol(),
	}


def get_won_deals(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get won deal count for the dashboard, and also calculate average deal value for won deals.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build conditions for current period
	current_cond = (
		(Deal.closed_date >= from_date) & (Deal.closed_date < to_date_plus_one) & (Status.type == "Won")
	)
	if user:
		current_cond = current_cond & belongs_to(Deal, user, "CRM Deal")

	# Build conditions for previous period
	prev_cond = (Deal.closed_date >= prev_from_date) & (Deal.closed_date < from_date) & (Status.type == "Won")
	if user:
		prev_cond = prev_cond & belongs_to(Deal, user, "CRM Deal")

	# Build query with CASE expressions
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Count(Case().when(current_cond, Deal.name).else_(None)).as_("current_month_deals"),
			Count(Case().when(prev_cond, Deal.name).else_(None)).as_("prev_month_deals"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_month_deals = result[0].current_month_deals or 0
	prev_month_deals = result[0].prev_month_deals or 0

	delta_in_percentage = (
		(current_month_deals - prev_month_deals) / prev_month_deals * 100 if prev_month_deals else 0
	)

	return {
		"title": _("Won deals"),
		"tooltip": _("Total number of won deals based on its closure date"),
		"value": current_month_deals,
		"delta": delta_in_percentage,
		"deltaSuffix": "%",
	}


def get_average_won_deal_value(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get won deal count for the dashboard, and also calculate average deal value for won deals.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build conditions for current period
	current_cond = (
		(Deal.closed_date >= from_date) & (Deal.closed_date < to_date_plus_one) & (Status.type == "Won")
	)
	if user:
		current_cond = current_cond & belongs_to(Deal, user, "CRM Deal")

	# Build conditions for previous period
	prev_cond = (Deal.closed_date >= prev_from_date) & (Deal.closed_date < from_date) & (Status.type == "Won")
	if user:
		prev_cond = prev_cond & belongs_to(Deal, user, "CRM Deal")

	# Calculate deal value with exchange rate
	deal_value_expr = Deal.deal_value * IfNull(Deal.exchange_rate, 1)

	# Build query with CASE expressions
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Avg(Case().when(current_cond, deal_value_expr).else_(None)).as_("current_month_avg_value"),
			Avg(Case().when(prev_cond, deal_value_expr).else_(None)).as_("prev_month_avg_value"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_month_avg_value = result[0].current_month_avg_value or 0
	prev_month_avg_value = result[0].prev_month_avg_value or 0

	avg_value_delta = current_month_avg_value - prev_month_avg_value if prev_month_avg_value else 0

	return {
		"title": _("Avg. won deal value"),
		"tooltip": _("Average deal value of won deals"),
		"value": current_month_avg_value,
		"delta": avg_value_delta,
		"prefix": get_base_currency_symbol(),
	}


def get_average_deal_value(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get average deal value for the dashboard.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build conditions for current period
	current_cond = (Deal.creation >= from_date) & (Deal.creation < to_date_plus_one) & (Status.type != "Lost")
	if user:
		current_cond = current_cond & belongs_to(Deal, user, "CRM Deal")

	# Build conditions for previous period
	prev_cond = (Deal.creation >= prev_from_date) & (Deal.creation < from_date) & (Status.type != "Lost")
	if user:
		prev_cond = prev_cond & belongs_to(Deal, user, "CRM Deal")

	# Calculate deal value with exchange rate
	deal_value_expr = Deal.deal_value * IfNull(Deal.exchange_rate, 1)

	# Build query with CASE expressions
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Avg(Case().when(current_cond, deal_value_expr).else_(None)).as_("current_month_avg"),
			Avg(Case().when(prev_cond, deal_value_expr).else_(None)).as_("prev_month_avg"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_month_avg = result[0].current_month_avg or 0
	prev_month_avg = result[0].prev_month_avg or 0

	delta = current_month_avg - prev_month_avg if prev_month_avg else 0

	return {
		"title": _("Avg. deal value"),
		"tooltip": _("Average deal value of ongoing & won deals"),
		"value": current_month_avg,
		"prefix": get_base_currency_symbol(),
		"delta": delta,
	}


def get_average_time_to_close_a_lead(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get average time to close deals for the dashboard.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)
	prev_to_date = from_date

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")
	Lead = DocType("CRM Lead")

	# Base condition: closed_date is not null and status type is Won
	base_cond = (Deal.closed_date.isnotnull()) & (Status.type == "Won")
	if user:
		base_cond = base_cond & belongs_to(Deal, user, "CRM Deal")

	# Current period condition
	current_cond = (Deal.closed_date >= from_date) & (Deal.closed_date < to_date_plus_one)

	# Previous period condition
	prev_cond = (Deal.closed_date >= prev_from_date) & (Deal.closed_date < prev_to_date)

	# Calculate time difference from lead/deal creation to deal closure
	time_diff = TimestampDiff(
		frappe.qb.terms.LiteralValue("DAY"), Coalesce(Lead.creation, Deal.creation), Deal.closed_date
	)

	# Build query
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.left_join(Lead)
		.on(Deal.lead == Lead.name)
		.where(base_cond)
		.select(
			Avg(Case().when(current_cond, time_diff).else_(None)).as_("current_avg_lead"),
			Avg(Case().when(prev_cond, time_diff).else_(None)).as_("prev_avg_lead"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_avg_lead = result[0].current_avg_lead or 0
	prev_avg_lead = result[0].prev_avg_lead or 0
	delta_lead = current_avg_lead - prev_avg_lead if prev_avg_lead else 0

	return {
		"title": _("Avg. time to close a lead"),
		"tooltip": _("Average time taken from lead creation to deal closure"),
		"value": current_avg_lead,
		"suffix": " days",
		"delta": delta_lead,
		"deltaSuffix": " days",
		"negativeIsBetter": True,
	}


def get_average_time_to_close_a_deal(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get average time to close deals for the dashboard.
	"""
	diff = frappe.utils.date_diff(to_date, from_date)
	if diff == 0:
		diff = 1

	prev_from_date = frappe.utils.add_days(from_date, -diff)
	to_date_plus_one = frappe.utils.add_days(to_date, 1)
	prev_to_date = from_date

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")
	Lead = DocType("CRM Lead")

	# Base condition: closed_date is not null and status type is Won
	base_cond = (Deal.closed_date.isnotnull()) & (Status.type == "Won")
	if user:
		base_cond = base_cond & belongs_to(Deal, user, "CRM Deal")

	# Current period condition
	current_cond = (Deal.closed_date >= from_date) & (Deal.closed_date < to_date_plus_one)

	# Previous period condition
	prev_cond = (Deal.closed_date >= prev_from_date) & (Deal.closed_date < prev_to_date)

	# Calculate time difference from deal creation to deal closure
	time_diff = TimestampDiff(frappe.qb.terms.LiteralValue("DAY"), Deal.creation, Deal.closed_date)

	# Build query
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.left_join(Lead)
		.on(Deal.lead == Lead.name)
		.where(base_cond)
		.select(
			Avg(Case().when(current_cond, time_diff).else_(None)).as_("current_avg_deal"),
			Avg(Case().when(prev_cond, time_diff).else_(None)).as_("prev_avg_deal"),
		)
	)

	query = scope_deals(query)

	result = query.run(as_dict=True)

	current_avg_deal = result[0].current_avg_deal or 0
	prev_avg_deal = result[0].prev_avg_deal or 0
	delta_deal = current_avg_deal - prev_avg_deal if prev_avg_deal else 0

	return {
		"title": _("Avg. time to close a deal"),
		"tooltip": _("Average time taken from deal creation to deal closure"),
		"value": current_avg_deal,
		"suffix": " days",
		"delta": delta_deal,
		"deltaSuffix": " days",
		"negativeIsBetter": True,
	}


def get_sales_trend(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get sales trend data for the dashboard.
	[
		{ date: new Date('2024-05-01'), leads: 45, deals: 23, won_deals: 12 },
		{ date: new Date('2024-05-02'), leads: 50, deals: 30, won_deals: 15 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	Lead = DocType("CRM Lead")
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	# Build leads query
	leads_query = (
		frappe.qb.from_(Lead)
		.select(
			Date(Lead.creation).as_("date"),
			Count("*").as_("leads"),
			frappe.qb.terms.ValueWrapper(0).as_("deals"),
			frappe.qb.terms.ValueWrapper(0).as_("won_deals"),
		)
		.where(Date(Lead.creation).between(from_date, to_date))
	)

	if user:
		leads_query = leads_query.where(belongs_to(Lead, user, "CRM Lead"))

	leads_query = scope_leads(leads_query).groupby(Date(Lead.creation))

	# Build deals query
	deals_query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(
			Date(Deal.creation).as_("date"),
			frappe.qb.terms.ValueWrapper(0).as_("leads"),
			Count("*").as_("deals"),
			Sum(Case().when(Status.type == "Won", 1).else_(0)).as_("won_deals"),
		)
		.where(Date(Deal.creation).between(from_date, to_date))
	)

	if user:
		deals_query = deals_query.where(belongs_to(Deal, user, "CRM Deal"))

	deals_query = scope_deals(deals_query).groupby(Date(Deal.creation))

	# Combine with UNION ALL and aggregate by date
	union_query = leads_query.union_all(deals_query)

	# Wrap in outer query to aggregate by date
	daily = (
		frappe.qb.from_(union_query)
		.select(
			DateFormat(union_query.date, "%Y-%m-%d").as_("date"),
			Sum(union_query.leads).as_("leads"),
			Sum(union_query.deals).as_("deals"),
			Sum(union_query.won_deals).as_("won_deals"),
		)
		.groupby(union_query.date)
		.orderby(union_query.date)
	)

	result = daily.run(as_dict=True)

	sales_trend = [
		{
			"date": frappe.utils.get_datetime(row.date).strftime("%Y-%m-%d"),
			"leads": row.leads or 0,
			"deals": row.deals or 0,
			"won_deals": row.won_deals or 0,
		}
		for row in result
	]

	return {
		"data": sales_trend,
		"title": _("Sales trend"),
		"subtitle": _("Daily performance of leads, deals, and wins"),
		"xAxis": {
			"title": _("Date"),
			"key": "date",
			"type": "time",
			"timeGrain": "day",
		},
		"yAxis": {
			"title": _("Count"),
		},
		"series": [
			{"name": "leads", "type": "line", "showDataPoints": True},
			{"name": "deals", "type": "line", "showDataPoints": True},
			{"name": "won_deals", "type": "line", "showDataPoints": True},
		],
	}


def forecast_window(from_date: str | None, to_date: str | None) -> tuple[str, str]:
	"""The months a forecast covers: the caller's range, or a year either side of today.

	The default upper bound matters as much as the lower one — without it a deal
	someone dated 2032 lands on the chart and takes a snapshot row every week.
	"""
	from_date = str(from_date) if from_date else frappe.utils.add_months(nowdate(), -12)
	to_date = str(to_date) if to_date else frappe.utils.add_months(nowdate(), 12)
	return from_date, to_date


def forecast_by_month(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	users: list[str] | None = None,
):
	"""Probability-weighted open pipeline per month of expected closure.

	``users`` narrows to a team the way ``user`` narrows to a rep; it is what
	:func:`take_forecast_snapshot` uses to record a manager's subtree.

	Won and Lost deals are excluded: a Lost deal contributes nothing to a
	forecast, and a Won one is no longer a prediction — it shows up in
	:func:`actual_by_month` instead. Lost deals are excluded by status rather
	than trusted to carry probability 0, because a status changed outside the
	deal form leaves the old probability behind.
	"""
	from_date, to_date = forecast_window(from_date, to_date)
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	weighted = Deal.expected_deal_value * IfNull(Deal.probability, 0) / 100 * IfNull(Deal.exchange_rate, 1)
	month = DateFormat(Deal.expected_closure_date, "%Y-%m")

	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(month.as_("month"), Sum(weighted).as_("forecasted"))
		.where(
			(Deal.expected_closure_date >= from_date)
			& (Deal.expected_closure_date <= to_date)
			& (Status.type.notin(["Won", "Lost"]))
		)
		.groupby(month)
	)
	if user:
		query = query.where(belongs_to(Deal, user, "CRM Deal"))
	elif users is not None:
		query = query.where(belongs_to_any(Deal, users, "CRM Deal"))

	return {row["month"]: float(row["forecasted"] or 0) for row in scope_deals(query).run(as_dict=True)}


def actual_by_month(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	users: list[str] | None = None,
):
	"""Closed-won revenue per month it actually closed in.

	Grouped on ``closed_date``, never on the date the deal was once expected to
	close, so a deal that slipped two months lands on the month it really landed
	— and a Won deal that never carried an expected closure date is still counted.
	"""
	from_date, to_date = forecast_window(from_date, to_date)
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	month = DateFormat(Deal.closed_date, "%Y-%m")
	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(month.as_("month"), Sum(Deal.deal_value * IfNull(Deal.exchange_rate, 1)).as_("actual"))
		.where((Deal.closed_date >= from_date) & (Deal.closed_date <= to_date) & (Status.type == "Won"))
		.groupby(month)
	)
	if user:
		query = query.where(belongs_to(Deal, user, "CRM Deal"))
	elif users is not None:
		# `is not None`, not truthiness: an empty team must return nothing, not
		# fall through to the unscoped site total.
		query = query.where(belongs_to_any(Deal, users, "CRM Deal"))

	return {row["month"]: float(row["actual"] or 0) for row in scope_deals(query).run(as_dict=True)}


def get_forecasted_revenue(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	users: list[str] | None = None,
):
	"""
	Get forecasted revenue for the dashboard.
	[
		{ month: '2024-05-01', forecasted: 1200000, actual: 980000 },
		{ month: '2024-06-01', forecasted: 1350000, actual: 1120000 },
		{ month: '2024-07-01', forecasted: 1600000, actual: None },
		...
	]

	Forecast and actual are two different aggregates over two different dates —
	see :func:`forecast_by_month` and :func:`actual_by_month` — merged on the
	month key, so a deal forecast for May and won in July appears in both.
	``actual`` is ``None`` only for months still in the future; a settled month
	with nothing closed reports 0, which is a fact rather than a gap.
	"""
	forecast = forecast_by_month(from_date, to_date, user, users)
	actual = actual_by_month(from_date, to_date, user, users)

	this_month = str(get_first_day(nowdate()))[:7]
	result = []
	for month in sorted(set(forecast) | set(actual)):
		result.append(
			{
				"month": f"{month}-01",
				"forecasted": round(forecast.get(month, 0), 2),
				"actual": None if month > this_month else round(actual.get(month, 0), 2),
			}
		)

	payload = {
		"data": result,
		"title": _("Forecasted revenue"),
		"subtitle": _("Projected vs actual revenue based on deal probability"),
		"xAxis": {
			"title": _("Month"),
			"key": "month",
			"type": "time",
			"timeGrain": "month",
		},
		"yAxis": {
			"title": _("Revenue") + f" ({get_base_currency_symbol()})",
		},
		"series": [
			{"name": "forecasted", "type": "line", "showDataPoints": True},
			{"name": "actual", "type": "line", "showDataPoints": True},
		],
	}
	empty_state = forecast_empty_state()
	if empty_state:
		payload["emptyState"] = empty_state
	return payload


def forecast_empty_state() -> str | None:
	"""Why a forecast surface is blank, when it is blank for a reason we know.

	``expected_deal_value`` and ``expected_closure_date`` are only mandatory when
	FCRM Settings ``enable_forecasting`` is on, and it ships off. A blank chart
	beside tiles showing real money reads as a bug, so the surfaces say which
	setting is responsible instead of rendering nothing.
	"""
	if frappe.db.get_single_value("FCRM Settings", "enable_forecasting"):
		return None
	return _("Forecasting is off — turn it on in Settings and set expected value and close date on deals")


def get_funnel_conversion(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get funnel conversion data for the dashboard.
	[
		{ stage: 'Leads', count: 120 },
		{ stage: 'Qualification', count: 100 },
		{ stage: 'Negotiation', count: 80 },
		{ stage: 'Ready to Close', count: 60 },
		{ stage: 'Won', count: 30 },
		{ stage: 'Lost', count: 22 },
	]

	Every stage row counts the deals that ever reached it, and the terminal Lost
	row counts the deals that leaked out, so the rows add up to what happened
	rather than to what survived.
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	result = []

	# Get total leads using Query Builder
	CRMLead = DocType("CRM Lead")

	query = (
		frappe.qb.from_(CRMLead)
		.select(Count("*").as_("count"))
		.where(Date(CRMLead.creation).between(from_date, to_date))
	)

	if user:
		query = query.where(belongs_to(CRMLead, user, "CRM Lead"))

	total_leads = scope_leads(query).run(as_dict=True)
	total_leads_count = total_leads[0].count if total_leads else 0

	result.append({"stage": "Leads", "count": total_leads_count})

	result += get_deal_status_change_counts(from_date, to_date, user)
	result.append({"stage": _("Lost"), "count": lost_deal_count(from_date, to_date, user)})

	return {
		"data": result or [],
		"title": _("Funnel conversion"),
		"subtitle": _("Lead to deal conversion pipeline"),
		"xAxis": {
			"title": _("Stage"),
			"key": "stage",
			"type": "category",
		},
		"yAxis": {
			"title": _("Count"),
		},
		"swapXY": True,
		"series": [
			{
				"name": "count",
				"type": "bar",
				"echartOptions": {
					"colorBy": "data",
				},
			},
		],
	}


def pipeline_by_stage(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	status_types: tuple[str, ...] = ("Open", "Ongoing"),
	date_field: str | None = None,
):
	"""Deals, expected value and weighted expected value per stage — one aggregate.

	The single source for every by-stage number: the dashboard's stage chart and
	the pipeline report both call this, so they cannot drift apart. ``date_field``
	names the column a period applies to (``creation`` for "deals opened in the
	period"); left out, the answer is the pipeline as it stands right now, which
	is what a pipeline report means.

	Money is ``expected_deal_value``, the forward-looking basis — realised
	revenue lives in :func:`won_value_in_period` and is measured on
	``deal_value`` (SPEC: forward-looking vs realised money).
	"""
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")
	value = Deal.expected_deal_value * IfNull(Deal.exchange_rate, 1)

	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.where(Status.type.isin(list(status_types)))
		.select(
			Deal.status.as_("stage"),
			Status.type.as_("status_type"),
			Count(Deal.name).as_("deals"),
			Sum(value).as_("total_value"),
			Sum(value * IfNull(Deal.probability, 0) / 100).as_("weighted_value"),
			Status.position.as_("position"),
		)
		.groupby(Deal.status, Status.type, Status.position)
		.orderby(Status.position)
	)
	if date_field and from_date and to_date:
		query = query.where(Date(Deal[date_field]).between(from_date, to_date))
	if user:
		query = query.where(belongs_to(Deal, user, "CRM Deal"))

	rows = scope_deals(query).run(as_dict=True)
	for row in rows:
		row.pop("position", None)
		row["total_value"] = round(row["total_value"] or 0, 2)
		row["weighted_value"] = round(row["weighted_value"] or 0, 2)
	return rows


def get_deals_by_stage_axis(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get deal data by stage for the dashboard.
	[
		{ stage: 'Prospecting', count: 120 },
		{ stage: 'Negotiation', count: 45 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	rows = pipeline_by_stage(
		from_date,
		to_date,
		user,
		status_types=("Open", "Ongoing", "On Hold", "Won"),
		date_field="creation",
	)
	result = sorted(({**row, "count": row["deals"]} for row in rows), key=lambda r: r["count"], reverse=True)

	return {
		"data": result,
		"title": _("Deals by ongoing & won stage"),
		"xAxis": {
			"title": _("Stage"),
			"key": "stage",
			"type": "category",
		},
		"yAxis": {"title": _("Count")},
		"series": [
			{"name": "count", "type": "bar"},
		],
	}


def get_deals_by_stage_donut(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get deal data by stage for the dashboard.
	[
		{ stage: 'Prospecting', count: 120 },
		{ stage: 'Negotiation', count: 45 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder with JOIN
	CRMDeal = DocType("CRM Deal")
	CRMDealStatus = DocType("CRM Deal Status")

	query = (
		frappe.qb.from_(CRMDeal)
		.join(CRMDealStatus)
		.on(CRMDeal.status == CRMDealStatus.name)
		.select(CRMDeal.status.as_("stage"), Count("*").as_("count"), CRMDealStatus.type.as_("status_type"))
		.where(Date(CRMDeal.creation).between(from_date, to_date))
		.groupby(CRMDeal.status)
		.orderby(Count("*"), order=frappe.qb.desc)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	query = scope_deals(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Deals by stage"),
		"subtitle": _("Current pipeline distribution"),
		"categoryColumn": "stage",
		"valueColumn": "count",
	}


def get_lost_deal_reasons(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get lost deal reasons for the dashboard.
	[
		{ reason: 'Price too high', count: 20 },
		{ reason: 'Competitor won', count: 15 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder with JOIN
	CRMDeal = DocType("CRM Deal")
	CRMDealStatus = DocType("CRM Deal Status")

	query = (
		frappe.qb.from_(CRMDeal)
		.join(CRMDealStatus)
		.on(CRMDeal.status == CRMDealStatus.name)
		.select(CRMDeal.lost_reason.as_("reason"), Count("*").as_("count"))
		.where((Date(CRMDeal.creation).between(from_date, to_date)) & (CRMDealStatus.type == "Lost"))
		.groupby(CRMDeal.lost_reason)
		.having((CRMDeal.lost_reason.isnotnull()) & (CRMDeal.lost_reason != ""))
		.orderby(Count("*"), order=frappe.qb.desc)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	query = scope_deals(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Lost deal reasons"),
		"subtitle": _("Common reasons for losing deals"),
		"xAxis": {
			"title": _("Reason"),
			"key": "reason",
			"type": "category",
		},
		"yAxis": {
			"title": _("Count"),
		},
		"series": [
			{"name": "count", "type": "bar"},
		],
	}


def get_leads_by_source(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get lead data by source for the dashboard.
	[
		{ source: 'Website', count: 120 },
		{ source: 'Referral', count: 45 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder (safer, more maintainable)
	CRMLead = DocType("CRM Lead")

	query = (
		frappe.qb.from_(CRMLead)
		.select(IfNull(CRMLead.source, "Empty").as_("source"), Count("*").as_("count"))
		.where(Date(CRMLead.creation).between(from_date, to_date))
		.groupby(CRMLead.source)
		.orderby(Count("*"), order=frappe.qb.desc)
	)

	if user:
		query = query.where(belongs_to(CRMLead, user, "CRM Lead"))

	query = scope_leads(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Leads by source"),
		"subtitle": _("Lead generation channel analysis"),
		"categoryColumn": "source",
		"valueColumn": "count",
	}


def get_deals_by_source(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get deal data by source for the dashboard.
	[
		{ source: 'Website', count: 120 },
		{ source: 'Referral', count: 45 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder
	CRMDeal = DocType("CRM Deal")

	query = (
		frappe.qb.from_(CRMDeal)
		.select(IfNull(CRMDeal.source, "Empty").as_("source"), Count("*").as_("count"))
		.where(Date(CRMDeal.creation).between(from_date, to_date))
		.groupby(CRMDeal.source)
		.orderby(Count("*"), order=frappe.qb.desc)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	query = scope_deals(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Deals by source"),
		"subtitle": _("Deal generation channel analysis"),
		"categoryColumn": "source",
		"valueColumn": "count",
	}


def get_deals_by_territory(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Get deal data by territory for the dashboard.
	[
		{ territory: 'North America', deals: 45, value: 2300000 },
		{ territory: 'Europe', deals: 30, value: 1500000 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder with complex aggregations
	CRMDeal = DocType("CRM Deal")

	query = (
		frappe.qb.from_(CRMDeal)
		.select(
			IfNull(CRMDeal.territory, "Empty").as_("territory"),
			Count("*").as_("deals"),
			Sum(Coalesce(CRMDeal.deal_value, 0) * IfNull(CRMDeal.exchange_rate, 1)).as_("value"),
		)
		.where(Date(CRMDeal.creation).between(from_date, to_date))
		.groupby(CRMDeal.territory)
		.orderby(Count("*"), order=frappe.qb.desc)
		.orderby(
			Sum(Coalesce(CRMDeal.deal_value, 0) * IfNull(CRMDeal.exchange_rate, 1)), order=frappe.qb.desc
		)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	query = scope_deals(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Deals by territory"),
		"subtitle": _("Geographic distribution of deals and revenue"),
		"xAxis": {
			"title": _("Territory"),
			"key": "territory",
			"type": "category",
		},
		"yAxis": {
			"title": _("Number of deals"),
		},
		"y2Axis": {
			"title": _("Deal value") + f" ({get_base_currency_symbol()})",
		},
		"series": [
			{"name": "deals", "type": "bar"},
			{"name": "value", "type": "line", "showDataPoints": True, "axis": "y2"},
		],
	}


def get_deals_by_salesperson(
	from_date: str | None = None, to_date: str | None = None, user: str | None = None
):
	"""
	Get deal data by salesperson for the dashboard.
	[
		{ salesperson: 'John Smith', deals: 45, value: 2300000 },
		{ salesperson: 'Jane Doe', deals: 30, value: 1500000 },
		...
	]
	"""
	if not from_date or not to_date:
		from_date = frappe.utils.get_first_day(from_date or frappe.utils.nowdate())
		to_date = frappe.utils.get_last_day(to_date or frappe.utils.nowdate())

	# Using Frappe Query Builder with LEFT JOIN
	CRMDeal = DocType("CRM Deal")
	User = DocType("User")

	query = (
		frappe.qb.from_(CRMDeal)
		.left_join(User)
		.on(User.name == CRMDeal.deal_owner)
		.select(
			IfNull(User.full_name, CRMDeal.deal_owner).as_("salesperson"),
			Count("*").as_("deals"),
			Sum(Coalesce(CRMDeal.deal_value, 0) * IfNull(CRMDeal.exchange_rate, 1)).as_("value"),
		)
		.where(Date(CRMDeal.creation).between(from_date, to_date))
		.groupby(CRMDeal.deal_owner)
		.orderby(Count("*"), order=frappe.qb.desc)
		.orderby(
			Sum(Coalesce(CRMDeal.deal_value, 0) * IfNull(CRMDeal.exchange_rate, 1)), order=frappe.qb.desc
		)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	query = scope_deals(query)

	result = query.run(as_dict=True)

	return {
		"data": result or [],
		"title": _("Deals by salesperson"),
		"subtitle": _("Number of deals and total value per salesperson"),
		"xAxis": {
			"title": _("Salesperson"),
			"key": "salesperson",
			"type": "category",
		},
		"yAxis": {
			"title": _("Number of deals"),
		},
		"y2Axis": {
			"title": _("Deal value") + f" ({get_base_currency_symbol()})",
		},
		"series": [
			{"name": "deals", "type": "bar"},
			{"name": "value", "type": "line", "showDataPoints": True, "axis": "y2"},
		],
	}


def get_base_currency():
	"""
	The currency every monetary aggregate is expressed in. Deal values are
	multiplied by their stored exchange_rate to reach it, so nothing here ever
	sums two currencies together.
	"""
	return frappe.db.get_single_value("FCRM Settings", "currency") or "USD"


def get_base_currency_symbol():
	"""
	Get the base currency symbol from the system settings.
	"""
	return frappe.db.get_value("Currency", get_base_currency(), "symbol") or ""


def get_deal_status_change_counts(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
):
	"""
	Count the deals that ever reached each stage, ordered by stage position.

	A deal counts once per stage no matter how often it re-entered it, and a deal
	that was later lost still counts for every stage it passed through — dropping
	those would make the funnel a chart of survivors and inflate every conversion
	rate below the leak.

	Deals are attributed to a period by their own creation date, which is when the
	deal entered the funnel; the ``Leads`` row above it counts leads created in the
	same window.

	Returns:
	[
	  {"stage": "Qualification", "count": 120},
	  {"stage": "Negotiation", "count": 85},
	  ...
	]
	"""
	# Using Frappe Query Builder with multiple JOINs and table aliases
	CRMStatusChangeLog = DocType("CRM Status Change Log")
	CRMDeal = DocType("CRM Deal")
	TargetStatus = DocType("CRM Deal Status").as_("st")

	query = (
		frappe.qb.from_(CRMStatusChangeLog)
		.join(CRMDeal)
		.on(CRMStatusChangeLog.parent == CRMDeal.name)
		.join(TargetStatus)
		.on(CRMStatusChangeLog.to == TargetStatus.name)
		.select(
			CRMStatusChangeLog.to.as_("stage"),
			Count(CRMStatusChangeLog.parent).distinct().as_("count"),
		)
		.where(
			(CRMStatusChangeLog.to.isnotnull())
			& (CRMStatusChangeLog.to != "")
			& (Date(CRMDeal.creation).between(from_date, to_date))
		)
		.groupby(CRMStatusChangeLog.to, TargetStatus.position)
		.orderby(TargetStatus.position)
	)

	if user:
		query = query.where(belongs_to(CRMDeal, user, "CRM Deal"))

	return scope_deals(query).run(as_dict=True) or []


def lost_deal_count(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""Deals created in the period that are lost today — the funnel's terminal row."""
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(Count(Deal.name).as_("count"))
		.where((Date(Deal.creation).between(from_date, to_date)) & (Status.type == "Lost"))
	)
	if user:
		query = query.where(belongs_to(Deal, user, "CRM Deal"))

	rows = scope_deals(query).run(as_dict=True)
	return rows[0].count if rows else 0


def plan_adherence(
	from_date: str | None = None,
	to_date: str | None = None,
	user: str | None = None,
	group_by_user: bool = False,
):
	"""Planned activities that were due in the period, and what became of them.

	The single source for adherence: the dashboard tile and the by-rep report
	both call this. Only *settled* days count — fulfilment is written by the
	daily ``crm.rep_planning.match_actuals`` job, so today's items have not been
	matched yet and counting them would dock every rep a day's work.

	Returns one row per rep when ``group_by_user``, otherwise a single total row.
	"""
	cutoff = min(str(to_date), add_days(nowdate(), -1))

	PlanItem = DocType("CRM Rep Plan Item")
	Plan = DocType("CRM Rep Plan")
	done = Case().when(PlanItem.status == "Done", PlanItem.name).else_(None)
	missed = Case().when(PlanItem.status == "Missed", PlanItem.name).else_(None)

	query = (
		frappe.qb.from_(PlanItem)
		.join(Plan)
		.on(PlanItem.parent == Plan.name)
		.where((PlanItem.planned_date >= from_date) & (PlanItem.planned_date <= cutoff))
		.select(
			Count(PlanItem.name).as_("planned"),
			Count(done).as_("done"),
			Count(missed).as_("missed"),
		)
	)
	if group_by_user:
		query = query.select(Plan.user.as_("user")).groupby(Plan.user).orderby(Plan.user)
	if user:
		query = query.where(Plan.user == user)
	else:
		reps = visible_reps()
		if reps is not None:
			query = query.where(Plan.user.isin(reps))

	rows = query.run(as_dict=True)
	if not group_by_user and not rows:
		rows = [frappe._dict({"planned": 0, "done": 0, "missed": 0})]
	for row in rows:
		row["planned"] = row["planned"] or 0
		row["done"] = row["done"] or 0
		row["missed"] = row["missed"] or 0
		row["adherence"] = round(row["done"] / row["planned"] * 100) if row["planned"] else 0
	return rows


def get_plan_adherence(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Plan adherence: share of planned activities in the period that were done.

	Computed from CRM Rep Plan items whose planned date falls in the range and
	has settled — records, never self-reports. Items still in the future are not
	counted against anyone.
	"""
	current = plan_adherence(from_date, to_date, user)[0]

	diff = date_diff(to_date, from_date) or 1
	previous = plan_adherence(add_days(from_date, -diff), add_days(from_date, -1), user)[0]

	return {
		"title": _("Plan adherence"),
		"tooltip": _("Planned activities completed, out of those already due"),
		"value": current["adherence"],
		"suffix": "%",
		"delta": current["adherence"] - previous["adherence"],
		"deltaSuffix": "%",
	}


def _at_risk_deals(to_date: str | None = None, user: str | None = None) -> list[dict]:
	"""Every open deal owned by the caller's scope, scored, newest activity first.

	Uses ``get_list`` rather than ``get_all`` so the CRM Deal permission query
	condition applies, and bounds the scan by ``to_date`` so the dashboard's date
	picker means something here too.

	Feature extraction is batched but must stay feature-for-feature identical to
	``crm.agent.predict.get_deal_health``: a tile that omits a feature silently
	drops the factors that depend on it, so the same deal scores healthier here
	than on its own page. ``test_the_tile_and_the_deal_page_score_a_deal_alike``
	pins the two together.
	"""
	from crm.agent.predict import _stage_median_days, score_deal
	from crm.agent.signals import (
		CADENCE_WINDOW_DAYS,
		_activity_history,
		_deals_with_open_tasks,
		cadence_ratio,
	)

	statuses = frappe.get_all("CRM Deal Status", filters={"type": ("in", ("Open", "Ongoing"))}, pluck="name")
	if not statuses:
		return []

	filters = {"status": ("in", statuses)}
	if to_date:
		filters["creation"] = ("<=", f"{to_date} 23:59:59")
	if user:
		# own-or-assigned, resolved to names first: `belongs_to` is a criterion and
		# get_list's filters cannot express the ToDo subquery it contains
		Deal = DocType("CRM Deal")
		mine = (
			frappe.qb.from_(Deal).select(Deal.name).where(belongs_to(Deal, user, "CRM Deal")).run(pluck=True)
		)
		if not mine:
			return []
		filters["name"] = ("in", mine)

	deals = frappe.get_list(
		"CRM Deal",
		filters=filters,
		fields=["name", "creation", "expected_closure_date", "status"],
		limit_page_length=0,
	)
	names = [d.name for d in deals]

	now = frappe.utils.now_datetime()
	history_since = now - timedelta(days=CADENCE_WINDOW_DAYS)

	with_tasks: set = set()
	stage_since: dict = {}
	inbound: dict = {}
	history: dict = {}
	# IN lists are chunked: a site with tens of thousands of open deals would
	# otherwise build several multi-thousand-element predicates in one statement
	for batch in _chunks(names, 1000):
		with_tasks |= _deals_with_open_tasks(batch)
		stage_since.update(_latest_stage_change(batch))
		inbound.update(_inbound_ratio(batch))
		history.update(_activity_history(batch, history_since))

	# one lookup per distinct stage, not per deal
	stages = {d.status for d in deals if d.status}
	probabilities = (
		{
			row.name: flt(row.probability)
			for row in frappe.get_all(
				"CRM Deal Status", filters={"name": ("in", list(stages))}, fields=["name", "probability"]
			)
		}
		if stages
		else {}
	)
	medians = {stage: _stage_median_days(stage) for stage in stages}

	scored = []
	for deal in deals:
		touches = history.get(deal.name) or []
		last = max(touches) if touches else deal.creation
		entered_stage = stage_since.get(deal.name)
		# expected_closure_date, not closed_date: closed_date is only ever set on
		# a Won deal, and nothing scored here is won, so reading it meant the
		# overdue-close factor could never fire
		days_to_close = (
			date_diff(deal.expected_closure_date, now.date()) if deal.expected_closure_date else None
		)
		measured = cadence_ratio(touches, now)
		verdict = score_deal(
			{
				"idle_days": max(0, (now - last).days),
				"days_in_stage": max(0, (now - entered_stage).days) if entered_stage else None,
				"stage": deal.status,
				"stage_median_days": medians.get(deal.status),
				"stage_probability": probabilities.get(deal.status),
				"days_to_close": days_to_close,
				"cadence_ratio": measured[0] if measured else None,
				"has_open_task": deal.name in with_tasks,
				"inbound_ratio": inbound.get(deal.name),
			}
		)
		scored.append({"name": deal.name, "creation": deal.creation, **verdict})
	return scored


def _chunks(items: list, size: int):
	for start in range(0, len(items), size):
		yield items[start : start + size]


def _latest_stage_change(deal_names: list[str]) -> dict:
	"""When each deal last entered its current stage, in one query."""
	if not deal_names:
		return {}
	from frappe.query_builder.functions import Max

	Log = DocType("CRM Status Change Log")
	rows = (
		frappe.qb.from_(Log)
		.select(Log.parent.as_("deal"), Max(Log.to_date).as_("entered"))
		.where((Log.parenttype == "CRM Deal") & (Log.parent.isin(deal_names)))
		.groupby(Log.parent)
		.run(as_dict=True)
	)
	return {row["deal"]: row["entered"] for row in rows if row["entered"]}


def _inbound_ratio(deal_names: list[str]) -> dict:
	"""Share of each deal's conversation that came back from the other side."""
	if not deal_names:
		return {}
	Comm = DocType("Communication")
	rows = (
		frappe.qb.from_(Comm)
		.select(
			Comm.reference_name.as_("deal"),
			Count(Comm.name).as_("total"),
			Count(Case().when(Comm.sent_or_received == "Received", Comm.name).else_(None)).as_("inbound"),
		)
		.where((Comm.reference_doctype == "CRM Deal") & (Comm.reference_name.isin(deal_names)))
		.groupby(Comm.reference_name)
		.run(as_dict=True)
	)
	return {row["deal"]: row["inbound"] / row["total"] for row in rows if row["total"]}


def get_deals_at_risk(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Open deals whose health score is below 40 — scored by the same explainable
	heuristic the deal pages show (idle time, stage stagnation, missing next
	task, overdue close date, one-sided conversation).

	The delta counts the at-risk deals opened during the period: health is a
	property of now, so there is no honest way to re-score the pipeline as it
	stood a month ago, but "how many of these arrived this period" is a real
	period-over-period movement and a rising one is bad news.
	"""
	from crm.agent.predict import AT_RISK_BELOW

	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	def count(extra=None):
		query = (
			frappe.qb.from_(Deal)
			.join(Status)
			.on(Deal.status == Status.name)
			.select(Count(Deal.name))
			# gate on the timestamp, not the score: an unscored deal has
			# health_score = 0 (frappe Floats are NOT NULL DEFAULT 0), which would
			# otherwise read as the worst possible health and count every deal on a
			# site where the scorer has not run yet
			.where(
				Status.type.isin(["Open", "Ongoing"])
				& Deal.health_scored_on.isnotnull()
				& (Deal.health_score < AT_RISK_BELOW)
			)
		)
		if to_date:
			query = query.where(Deal.creation <= f"{to_date} 23:59:59")
		if user:
			query = query.where(belongs_to(Deal, user, "CRM Deal"))
		query = scope_deals(query)
		if extra is not None:
			query = query.where(extra)
		return query.run()[0][0] or 0

	at_risk = count()
	opened_in_period = count(Deal.creation >= str(from_date)) if from_date else 0

	# `health_score` is written by the hourly scorer, so say when it last ran —
	# a number that is quietly an hour old is fine, a number that is quietly two
	# days old because the scheduler is wedged is not.
	scored_on = frappe.db.sql("select max(health_scored_on) from `tabCRM Deal`")[0][0]
	freshness = (
		_("as of {0}").format(frappe.utils.format_datetime(scored_on, "medium"))
		if scored_on
		else _("not scored yet — the hourly scorer has not run")
	)

	return {
		"title": _("Deals at risk"),
		"tooltip": _("Open deals with a health score below {0} ({1})").format(AT_RISK_BELOW, freshness),
		"value": at_risk,
		"delta": opened_in_period,
		"negativeIsBetter": True,
	}


def forecast_snapshot_scopes() -> list[tuple[str, str, dict]]:
	"""Every (scope, user, filter kwargs) combination a snapshot run records.

	Three scopes, because each answers a question the others cannot:

	* ``Site`` — everyone, the number a company-wide manager reads.
	* ``Team`` — one manager's subtree, for every hierarchy node that has
	  descendants. Not derivable from the rep rows: a deal owned by one member
	  and assigned to another would be counted twice by summing them, and a
	  deal that changes hands moves between rep rows retroactively while the
	  team total stays put. Recording it is the only way to have it.
	* ``Rep`` — a single owner, for anyone who owns deals.

	A manager who owns deals themselves appears in both ``Team`` and ``Rep``,
	which is why ``scope`` exists rather than the user field alone carrying the
	meaning.
	"""
	from crm.permissions.org_hierarchy import _team_mem_query

	scopes: list[tuple[str, str, dict]] = [("Site", "", {})]

	# Nested set: a node with no descendants has rgt == lft + 1. Read in one
	# query rather than probing each user, so this stays flat as teams grow.
	nodes = frappe.get_all(
		"CRM Sales Hierarchy", filters={"user": ("is", "set")}, fields=["user", "lft", "rgt"]
	)
	for node in sorted(nodes, key=lambda n: n.user):
		if node.rgt - node.lft > 1:
			members = _team_mem_query(node.user).run(pluck=True) or []
			scopes.append(("Team", node.user, {"users": sorted({node.user, *members})}))

	owners = frappe.get_all(
		"CRM Deal", filters={"deal_owner": ("is", "set")}, pluck="deal_owner", distinct=True
	)
	scopes += [("Rep", rep, {"user": rep}) for rep in sorted(owners)]
	return scopes


def take_forecast_snapshot():
	"""
	Weekly scheduler entry: persist today's probability-weighted forecast per
	month, so forecast accuracy is measurable against what actually closed.

	One row per (snapshot day, month, scope, user) — see
	:func:`forecast_snapshot_scopes` for why all three scopes are written
	rather than derived. A rerun on the same day updates in place.
	"""
	today = nowdate()
	from_date, to_date = frappe.utils.add_months(today, -1), frappe.utils.add_months(today, 6)

	written = 0
	for scope, who, kwargs in forecast_snapshot_scopes():
		for row in get_forecasted_revenue(from_date, to_date, **kwargs)["data"]:
			month = row["month"][:7]
			values = {
				"forecasted": row["forecasted"] or 0,
				"actual_at_snapshot": row["actual"] or 0,
			}
			key = {"snapshot_date": today, "month": month, "scope": scope, "user": who}
			existing = frappe.db.exists("CRM Forecast Snapshot", key)
			if existing:
				frappe.db.set_value("CRM Forecast Snapshot", existing, values)
			else:
				frappe.get_doc({"doctype": "CRM Forecast Snapshot", **key, **values}).insert(
					ignore_permissions=True
				)
			written += 1
	return written


def quota_in_period(from_date: str, to_date: str, user: str | None = None) -> float:
	"""Quota covering ``[from_date, to_date]``, pro-rated by how much of each month it covers.

	Quota rows are monthly (see ``CRM Quota``). A dashboard range is arbitrary, so a
	whole month's target cannot be compared with a week of revenue and called
	attainment. Pro-rating by covered days makes every range honest: a full month
	returns exactly that month's quota, a quarter returns three, a week returns a
	week's worth.
	"""
	from_date, to_date = getdate(from_date), getdate(to_date)
	if to_date < from_date:
		return 0.0

	filters = {
		"period_start": ("between", [get_first_day(from_date), get_last_day(to_date)]),
	}
	if user:
		filters["user"] = user
	else:
		# frappe.get_all does not check permissions, and quota is keyed on a user
		# rather than a deal, so nothing else here would scope it. Unfiltered, an
		# in-tree manager divided their subtree's closed-won by the *company's*
		# quota and read back a third of their real attainment -- on the first
		# tile of the dashboard. visible_reps() is the same subtree the deal
		# aggregates beside it use.
		reps = visible_reps()
		if reps is not None:
			filters["user"] = ("in", reps)
	rows = frappe.get_all("CRM Quota", filters=filters, fields=["amount", "period_start"])

	total = 0.0
	for row in rows:
		month_start = getdate(row.period_start)
		month_end = get_last_day(month_start)
		covered_from = max(month_start, from_date)
		covered_to = min(month_end, to_date)
		if covered_to < covered_from:
			continue
		days_in_month = date_diff(month_end, month_start) + 1
		covered_days = date_diff(covered_to, covered_from) + 1
		total += (row.amount or 0) * covered_days / days_in_month
	return total


def won_value_in_period(from_date: str, to_date: str, user: str | None = None) -> float:
	"""Closed-won revenue in the period, normalised to the base currency."""
	Deal = DocType("CRM Deal")
	Status = DocType("CRM Deal Status")

	cond = (
		(Deal.closed_date >= from_date)
		& (Deal.closed_date < frappe.utils.add_days(to_date, 1))
		& (Status.type == "Won")
	)
	if user:
		cond = cond & belongs_to(Deal, user, "CRM Deal")

	query = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(Sum(Case().when(cond, Deal.deal_value * IfNull(Deal.exchange_rate, 1)).else_(0)))
	)
	return float(scope_deals(query).run()[0][0] or 0)


def get_quota_attainment(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Closed-won revenue against quota for the period.

	Both sides are in the base currency and both come from the same functions the
	reports use, so the dashboard tile and the quota report can never disagree.
	With no quota set the tile reports 0% and says so in its tooltip rather than
	dividing by zero or hiding.
	"""
	quota = quota_in_period(from_date, to_date, user)
	actual = won_value_in_period(from_date, to_date, user)
	attainment = round(actual / quota * 100) if quota else 0

	if quota:
		tooltip = _("{0} of {1} closed-won against quota").format(
			frappe.utils.fmt_money(actual, currency=get_base_currency()),
			frappe.utils.fmt_money(quota, currency=get_base_currency()),
		)
	else:
		tooltip = _("No quota set for this period")

	return {
		"title": _("Quota attainment"),
		"tooltip": tooltip,
		"value": attainment,
		"suffix": "%",
		"delta": 0,
	}


def forecast_accuracy_scope(user: str | None) -> tuple[str, str, list[str] | None]:
	"""Which snapshot series the caller is entitled to: ``(scope, user, members)``.

	``members`` is the rep list a Team row covers, so ``actual`` can be
	recomputed live over the same population; ``None`` means unrestricted.

	The gap this closes: the series was chosen by ``user`` alone, so a manager
	— who reaches here with ``user`` unset — read the row with an empty user,
	which is the *site* aggregate. For a manager over the whole company that is
	right. For an in-tree manager it is somebody else's revenue on their
	dashboard, and not the number they were asking for either.
	"""
	if user:
		return "Rep", user, [user]

	reps = visible_reps()
	if reps is None:
		return "Site", "", None
	return "Team", frappe.session.user, reps


def forecast_accuracy_rows(user: str | None = None) -> list[dict]:
	"""What each month was forecast to be, against what it turned out to be.

	``forecasted`` is the *last* snapshot taken before the month opened — the
	number the team committed to going in, not a half-formed one from weeks
	earlier. ``actual`` is queried live rather than read from the snapshot, so a
	month keeps converging on the truth after the snapshots for it stop;
	``actual_at_snapshot`` stays on the row as the record of what was known then.

	The series is picked by :func:`forecast_accuracy_scope`, never by ``user``
	alone.
	"""
	scope, who, members = forecast_accuracy_scope(user)
	snapshots = frappe.get_all(
		"CRM Forecast Snapshot",
		filters={"scope": scope, "user": who},
		fields=["snapshot_date", "month", "forecasted", "actual_at_snapshot"],
		order_by="month asc, snapshot_date asc",
	)

	by_month: dict[str, dict] = {}
	for snap in snapshots:
		entry = by_month.setdefault(
			snap.month, {"month": snap.month, "forecasted": None, "actual_at_snapshot": 0}
		)
		if str(snap.snapshot_date) < f"{snap.month}-01":
			entry["forecasted"] = snap.forecasted
		entry["actual_at_snapshot"] = snap.actual_at_snapshot

	rows = [e for e in by_month.values() if e["forecasted"] is not None]
	if not rows:
		return []

	months = sorted(e["month"] for e in rows)
	# Live actuals over the same population the snapshot covered -- a Team row
	# has to be re-measured across the subtree, not against one manager's own
	# deals, or forecast and actual would be two different questions.
	actual = actual_by_month(
		f"{months[0]}-01",
		str(get_last_day(f"{months[-1]}-01")),
		user=who if scope == "Rep" else None,
		users=members if scope == "Team" else None,
	)
	for entry in rows:
		entry["actual"] = round(actual.get(entry["month"], 0), 2)
	return sorted(rows, key=lambda e: e["month"])


def get_forecast_accuracy(from_date: str | None = None, to_date: str | None = None, user: str | None = None):
	"""
	Forecast vs what actually happened, per month, as an axis chart.

	Scoped by :func:`forecast_accuracy_scope`: a rep sees their own accuracy, a
	manager over the whole company sees the site series, and an in-tree manager
	sees their own team's — never the company's.
	"""
	scope, _who, _members = forecast_accuracy_scope(user)
	rows = forecast_accuracy_rows(user)

	payload = {
		"data": [
			{"month": f"{r['month']}-01", "forecasted": r["forecasted"], "actual": r["actual"]} for r in rows
		],
		"title": _("Forecast accuracy"),
		"subtitle": _("What each month was forecast to be, against what closed"),
		"xAxis": {
			"title": _("Month"),
			"key": "month",
			"type": "time",
			"timeGrain": "month",
		},
		"yAxis": {
			"title": _("Revenue") + f" ({get_base_currency_symbol()})",
		},
		"series": [
			{"name": "forecasted", "type": "line", "showDataPoints": True},
			{"name": "actual", "type": "line", "showDataPoints": True},
		],
	}
	if not rows:
		# Team series start empty on every existing site: snapshots were only
		# ever written per rep and site-wide, so there is no team history to
		# backfill -- a stored forecast is what was believed on a past date and
		# cannot be reconstructed afterwards. Say so, rather than showing the
		# generic "no snapshots yet" and leaving a manager to wonder whether
		# forecasting is broken.
		payload["emptyState"] = forecast_empty_state() or (
			_(
				"Your team's forecast accuracy starts building from the next weekly"
				" snapshot — the first month closes before this chart can compare anything"
			)
			if scope == "Team"
			else _("No forecast snapshots yet — accuracy appears once a month has been forecast and closed")
		)
	return payload


CHARTS = {
	"total_leads": get_total_leads,
	"ongoing_deals": get_ongoing_deals,
	"average_ongoing_deal_value": get_average_ongoing_deal_value,
	"won_deals": get_won_deals,
	"average_won_deal_value": get_average_won_deal_value,
	"average_deal_value": get_average_deal_value,
	"average_time_to_close_a_lead": get_average_time_to_close_a_lead,
	"average_time_to_close_a_deal": get_average_time_to_close_a_deal,
	"plan_adherence": get_plan_adherence,
	"deals_at_risk": get_deals_at_risk,
	"quota_attainment": get_quota_attainment,
	"sales_trend": get_sales_trend,
	"forecasted_revenue": get_forecasted_revenue,
	"forecast_accuracy": get_forecast_accuracy,
	"funnel_conversion": get_funnel_conversion,
	"deals_by_stage_axis": get_deals_by_stage_axis,
	"deals_by_stage_donut": get_deals_by_stage_donut,
	"lost_deal_reasons": get_lost_deal_reasons,
	"leads_by_source": get_leads_by_source,
	"deals_by_source": get_deals_by_source,
	"deals_by_territory": get_deals_by_territory,
	"deals_by_salesperson": get_deals_by_salesperson,
}
"""Charts the dashboard may render, by layout name.

An explicit registry rather than ``getattr(f"get_{name}")``: the old dispatch
made every module-level function reachable from a whitelisted endpoint and
called it positionally, which silently fed the caller's ``user`` into whatever
the third parameter happened to be. Everything here takes
``(from_date, to_date, user)`` and is called by keyword.
"""
