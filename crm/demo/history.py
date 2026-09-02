"""Two years of synthetic pipeline history behind the demo data.

The base demo (``crm/demo/leads.py`` and friends) is a dozen leads and seven
deals over eight weeks -- enough for a record page, not for a dashboard. Every
analytics surface reads a *window*: won revenue by month, forecast against
actual, quota attainment, funnel conversion, deals by territory and industry,
plan adherence. With eight weeks of data most of them draw one point.

This module writes the history those surfaces need, for the same three demo
reps, over the last twenty-four months plus the current one:

- organizations across the industries a valve supplier sells into, with a
  South African territory each;
- leads every month with a rising, seasonal count, and the statuses a real
  funnel leaves behind;
- a share of them converted into deals that were won (with a real
  ``closed_date`` and a status-change log that gives each stage a duration),
  lost (with a reason), or are still open in a stage;
- monthly targets per rep, forecast snapshots taken before each month began,
  and weekly plans with done and missed items;
- a few dated comments on the open deals so the cadence signals have a
  rhythm to read.

Deterministic: the same seed produces the same history, so a demo rehearsed
on one site looks the same on another. Everything created is tracked by name
and removed by :func:`delete_demo_history`, which ``clear_demo_data`` calls.

Amounts are in the site's base currency. The figures were sized for ZAR; on
a site in another currency they are divided by a fixed factor so a "large"
deal still reads as large rather than absurd.
"""

from __future__ import annotations

import math
import random
from datetime import date, datetime, timedelta

import frappe
from frappe.utils import get_first_day, getdate

from crm.demo.utils import backdate, build_full_names, insert_comment, resolve_owners

SEED = 20260902
MONTHS_BACK = 24
ZAR_TO_OTHER = 18.0

TERRITORIES = ["Gauteng", "North West", "KwaZulu-Natal", "Western Cape", "Mpumalanga", "Limpopo"]
INDUSTRIES = [
	"Mining",
	"Water & Sanitation",
	"Petrochemical",
	"Pulp & Paper",
	"Power Generation",
	"Food & Beverage",
	"Manufacturing",
	"Agriculture",
]
SOURCES = [
	"Website",
	"Reference",
	"Exhibition",
	"Cold Calling",
	"Existing Customer",
	"Campaign",
	"Walk In",
	"Email",
]
LOST_REASONS = [
	"Pricing",
	"Competition",
	"Budget Constraints",
	"Long Sales Cycle",
	"No Decision-Maker",
	"Unresponsive Prospect",
]
OPEN_STAGES = [
	("Qualification", 10),
	("Demo/Making", 25),
	("Proposal/Quotation", 50),
	("Negotiation", 70),
	("Ready to Close", 90),
]
EMPLOYEE_BANDS = ["11-50", "51-200", "201-500", "501-1000", "1000+"]

# (organization, industry, territory) -- the customer base of a valve and
# instrumentation supplier serving mines, utilities and process plants.
ORGANIZATIONS = [
	("Sishen Iron Ore Operations", "Mining", "North West"),
	("Rustenburg Platinum Smelter", "Mining", "North West"),
	("Marikana Concentrator", "Mining", "North West"),
	("Kathu Manganese Mine", "Mining", "North West"),
	("Ekurhuleni Water Services", "Water & Sanitation", "Gauteng"),
	("Rand Water Zuikerbosch", "Water & Sanitation", "Gauteng"),
	("Umgeni Water Board", "Water & Sanitation", "KwaZulu-Natal"),
	("eThekwini Wastewater Works", "Water & Sanitation", "KwaZulu-Natal"),
	("Cape Flats Treatment Works", "Water & Sanitation", "Western Cape"),
	("Secunda Synfuels", "Petrochemical", "Mpumalanga"),
	("Durban Refinery Terminals", "Petrochemical", "KwaZulu-Natal"),
	("Sasolburg Chemical Complex", "Petrochemical", "Gauteng"),
	("Richards Bay Pulp Mill", "Pulp & Paper", "KwaZulu-Natal"),
	("Ngodwana Paper Mill", "Pulp & Paper", "Mpumalanga"),
	("Kusile Power Station", "Power Generation", "Mpumalanga"),
	("Medupi Power Station", "Power Generation", "Limpopo"),
	("Lephalale Coal Handling", "Mining", "Limpopo"),
	("Boksburg Bottling Plant", "Food & Beverage", "Gauteng"),
	("Paarl Fruit Processing", "Food & Beverage", "Western Cape"),
	("Pietermaritzburg Dairy Co-op", "Food & Beverage", "KwaZulu-Natal"),
	("Germiston Steel Works", "Manufacturing", "Gauteng"),
	("Vanderbijlpark Rolling Mill", "Manufacturing", "Gauteng"),
	("Atlantis Foundry", "Manufacturing", "Western Cape"),
	("Tzaneen Citrus Estates", "Agriculture", "Limpopo"),
	("Ceres Irrigation Board", "Agriculture", "Western Cape"),
	("Nelspruit Sugar Mill", "Agriculture", "Mpumalanga"),
	("Klerksdorp Gold Plant", "Mining", "North West"),
	("Phalaborwa Copper Works", "Mining", "Limpopo"),
	("Mossel Bay Gas Plant", "Petrochemical", "Western Cape"),
	("Saldanha Ore Terminal", "Mining", "Western Cape"),
	("Tshwane Bulk Water", "Water & Sanitation", "Gauteng"),
	("Witbank Coal Washing", "Mining", "Mpumalanga"),
	("Newcastle Steel Coke Ovens", "Manufacturing", "KwaZulu-Natal"),
	("Polokwane Brewery", "Food & Beverage", "Limpopo"),
	("Soweto Reticulation Upgrade JV", "Water & Sanitation", "Gauteng"),
	("Hluhluwe Game Reserve Utilities", "Water & Sanitation", "KwaZulu-Natal"),
	("Matimba Ash Handling", "Power Generation", "Limpopo"),
	("Arnot Power Station", "Power Generation", "Mpumalanga"),
	("Springs Paper Recycling", "Pulp & Paper", "Gauteng"),
	("Stellenbosch Winery Group", "Food & Beverage", "Western Cape"),
]

FIRST_NAMES = [
	"Thabo",
	"Naledi",
	"Sipho",
	"Anele",
	"Pieter",
	"Annelize",
	"Johan",
	"Zanele",
	"Kagiso",
	"Lerato",
	"Riaan",
	"Nomvula",
	"Bongani",
	"Elsabe",
	"Mandla",
	"Precious",
	"Willem",
	"Thandeka",
	"Ravi",
	"Priya",
	"Ayanda",
	"Hendrik",
	"Lindiwe",
	"Deon",
]
LAST_NAMES = [
	"Mokoena",
	"van der Merwe",
	"Naidoo",
	"Dlamini",
	"Botha",
	"Khumalo",
	"Pillay",
	"Nkosi",
	"Steyn",
	"Mahlangu",
	"Coetzee",
	"Zulu",
	"Pretorius",
	"Sithole",
	"Govender",
	"Jacobs",
	"Molefe",
	"du Plessis",
	"Mthembu",
	"Venter",
]
JOB_TITLES = [
	"Plant Engineer",
	"Procurement Manager",
	"Maintenance Superintendent",
	"Reliability Engineer",
	"Projects Manager",
	"Buyer",
	"Instrumentation Lead",
	"Operations Manager",
]

# What a deal is about; shows up in the first comment on it.
DEAL_SUBJECTS = [
	"knife gate valves for the tailings line",
	"DN600 butterfly valves for the raw-water intake",
	"API 600 gate valves, Class 300, for the crude header",
	"actuated ball valves for the CIP skid",
	"magnetic flow meters for the reticulation upgrade",
	"pressure relief valves for the steam drum",
	"control valves with positioners for the digester",
	"resilient-seated gate valves for the pump station",
	"triple-offset butterfly valves for the ash slurry",
	"knife gate valve refurbishment programme",
]

COMMENTS = [
	"Site walk done. {org} confirmed {subject}; they want a technical submittal before the budget meeting.",
	"Sent the datasheets and the SANS 1123 flange drilling confirmation. Waiting on their engineer.",
	"Call with procurement: two competitors quoted. Ours is the only one with local seat spares.",
	"They asked for Class 300 instead of 150 on the header valves. Requoting.",
	"Delivery lead time is the sticking point; checking stock in Boksburg.",
]


def _dt(day: date, hour: int = 10) -> datetime:
	return datetime(day.year, day.month, day.day, hour, 15)


def _add_months(day: date, months: int) -> date:
	index = day.month - 1 + months
	year = day.year + index // 12
	month = index % 12 + 1
	return date(year, month, 1)


def _base_currency() -> tuple[str, float]:
	currency = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
	return currency, (1.0 if currency == "ZAR" else 1.0 / ZAR_TO_OTHER)


def _ensure_catalogue(doctype: str, field: str, values: list[str], created: list[str]) -> None:
	for value in values:
		if frappe.db.exists(doctype, value):
			continue
		frappe.get_doc({"doctype": doctype, field: value}).insert(ignore_permissions=True)
		created.append(value)


def create_demo_history(demo_users: list[str]) -> dict:
	"""Write the history and return the names of everything it created."""
	rng = random.Random(SEED)
	session_user, owner_1, owner_2, owner_3 = resolve_owners(demo_users)
	reps = []
	for user in (owner_1, owner_2, owner_3, session_user):
		if user not in reps:
			reps.append(user)
	reps = reps[:3]
	full_names = build_full_names(session_user)
	currency, scale = _base_currency()

	today = getdate()
	now = frappe.utils.now_datetime()
	created: dict[str, list] = {
		"territories": [],
		"industries": [],
		"organizations": [],
		"leads": [],
		"deals": [],
		"quotas": [],
		"snapshots": [],
		"plans": [],
		"comments": [],
	}

	_ensure_catalogue("CRM Territory", "territory_name", TERRITORIES, created["territories"])
	_ensure_catalogue("CRM Industry", "industry", INDUSTRIES, created["industries"])

	history_start = _add_months(get_first_day(today), -MONTHS_BACK)
	organizations = _create_organizations(rng, history_start, created)

	won_by_rep_month: dict[tuple[str, str], float] = {}
	open_deals: list[dict] = []

	for offset in range(MONTHS_BACK, -1, -1):
		month_start = _add_months(get_first_day(today), -offset)
		month_end = min(_add_months(month_start, 1) - timedelta(days=1), today)
		age_months = offset
		# A business growing ~2.5% a month, busier before the financial year
		# ends in February and quiet over December.
		growth = 1 + 0.025 * (MONTHS_BACK - offset)
		season = 1 + 0.15 * math.sin((month_start.month - 2) / 12 * 2 * math.pi)
		if month_start.month == 12:
			season *= 0.7
		leads_this_month = max(4, round(rng.uniform(6, 9) * growth * season))
		if offset == 0:
			leads_this_month = max(3, round(leads_this_month * (today.day / 30)))

		for _ in range(leads_this_month):
			lead_day = month_start + timedelta(days=rng.randint(0, max(0, (month_end - month_start).days)))
			rep = rng.choice(reps)
			org = rng.choice(organizations)
			lead_name = _create_lead(rng, org, rep, lead_day, created)

			converts = rng.random() < 0.45
			if not converts:
				_settle_lead(lead_name, rep, lead_day, age_months, rng, today)
				continue

			deal = _create_deal(
				rng, org, rep, lead_name, lead_day, age_months, today, scale, currency, created
			)
			if deal["status"] == "Won":
				key = (rep, deal["closed_date"].strftime("%Y-%m"))
				won_by_rep_month[key] = won_by_rep_month.get(key, 0.0) + deal["value"]
			elif deal["status"] not in ("Won", "Lost"):
				open_deals.append({**deal, "org": org, "rep": rep})
		frappe.db.commit()

	_create_quotas(rng, reps, today, won_by_rep_month, currency, created)
	_create_snapshots(rng, reps, today, won_by_rep_month, created)
	_create_plans(rng, reps, today, open_deals, created)
	_create_comments(rng, open_deals, full_names, now, created)
	frappe.db.commit()
	return created


def _create_organizations(rng, history_start: date, created: dict) -> list[dict]:
	organizations = []
	for name, industry, territory in ORGANIZATIONS:
		if frappe.db.exists("CRM Organization", name):
			organizations.append(
				{
					"name": name,
					"industry": industry,
					"territory": territory,
					"band": rng.choice(EMPLOYEE_BANDS),
				}
			)
			continue
		band = rng.choice(EMPLOYEE_BANDS)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": name,
				"industry": industry,
				"territory": territory,
				"no_of_employees": band,
				"annual_revenue": rng.choice([40, 120, 350, 900, 2400]) * 1_000_000,
			}
		).insert(ignore_permissions=True)
		ts = _dt(history_start + timedelta(days=rng.randint(0, 20)))
		backdate("CRM Organization", doc.name, frappe.session.user, ts)
		created["organizations"].append(doc.name)
		organizations.append({"name": doc.name, "industry": industry, "territory": territory, "band": band})
	return organizations


def _create_lead(rng, org: dict, rep: str, lead_day: date, created: dict) -> str:
	first = rng.choice(FIRST_NAMES)
	last = rng.choice(LAST_NAMES)
	slug = f"{first}.{last}".lower().replace(" ", "").replace("'", "")
	domain = org["name"].lower().replace(" ", "").replace("-", "")[:18]
	doc = frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": first,
			"last_name": last,
			"email": f"{slug}@{domain}.example.co.za",
			"mobile_no": f"+27 {rng.randint(60, 84)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
			"organization": org["name"],
			"industry": org["industry"],
			"territory": org["territory"],
			"job_title": rng.choice(JOB_TITLES),
			"status": "New",
			"source": rng.choice(SOURCES),
			"no_of_employees": org["band"],
			"lead_owner": rep,
		}
	).insert(ignore_permissions=True)
	backdate("CRM Lead", doc.name, rep, _dt(lead_day, rng.randint(8, 16)))
	created["leads"].append(doc.name)
	return doc.name


def _settle_lead(lead_name: str, rep: str, lead_day: date, age_months: int, rng, today: date) -> None:
	"""A lead that did not convert ends up somewhere honest for its age."""
	if age_months >= 3:
		status = rng.choices(["Nurture", "Unqualified", "Junk", "Contacted"], weights=[35, 35, 15, 15])[0]
	elif age_months >= 1:
		status = rng.choices(["Contacted", "Nurture", "Qualified", "Unqualified"], weights=[35, 30, 20, 15])[
			0
		]
	else:
		status = rng.choices(["New", "Contacted", "Qualified"], weights=[45, 40, 15])[0]
	touched = min(today, lead_day + timedelta(days=rng.randint(1, 20)))
	frappe.db.set_value("CRM Lead", lead_name, "status", status, update_modified=False)
	backdate("CRM Lead", lead_name, rep, _dt(touched, rng.randint(8, 17)), set_creation=False)


def _create_deal(rng, org, rep, lead_name, lead_day, age_months, today, scale, currency, created) -> dict:
	created_day = min(today, lead_day + timedelta(days=rng.randint(2, 14)))
	cycle_days = rng.randint(20, 110)
	value = round(
		rng.choice([45, 80, 120, 180, 260, 350, 480, 640, 900, 1400, 2400])
		* 1000
		* rng.uniform(0.85, 1.2)
		* scale,
		-2,
	)

	if age_months >= 4:
		outcome = rng.choices(["Won", "Lost", "open"], weights=[55, 37, 8])[0]
	elif age_months >= 2:
		outcome = rng.choices(["Won", "Lost", "open"], weights=[35, 20, 45])[0]
	else:
		outcome = rng.choices(["Won", "Lost", "open"], weights=[10, 5, 85])[0]

	closed_day = created_day + timedelta(days=cycle_days)
	if outcome in ("Won", "Lost") and closed_day > today:
		outcome = "open"

	if outcome == "open":
		stage_index = min(len(OPEN_STAGES) - 1, int((today - created_day).days / 25))
		stage_index = max(0, min(stage_index, rng.randint(0, len(OPEN_STAGES) - 1)))
		status, probability = OPEN_STAGES[stage_index]
	elif outcome == "Won":
		status, probability = "Won", 100
	else:
		status, probability = "Lost", 0

	deal = {
		"doctype": "CRM Deal",
		"organization": org["name"],
		"lead": lead_name,
		"deal_owner": rep,
		"status": status,
		"probability": probability,
		"currency": currency,
		"exchange_rate": 1,
		"deal_value": value,
		"expected_deal_value": value,
		"expected_closure_date": created_day + timedelta(days=rng.randint(30, 120)),
		"territory": org["territory"],
		"industry": org["industry"],
		"source": frappe.db.get_value("CRM Lead", lead_name, "source"),
		"no_of_employees": org["band"],
		"next_step": rng.choice(
			["Send revised quotation", "Site measurement", "Technical clarification call", "Await PO", ""]
		),
	}
	if status == "Lost":
		deal["lost_reason"] = rng.choice(LOST_REASONS)
	doc = frappe.get_doc(deal).insert(ignore_permissions=True)

	# Timestamps the hooks could not know about.
	created_ts = _dt(created_day, rng.randint(8, 16))
	last_touch = (
		closed_day
		if status in ("Won", "Lost")
		else min(today, created_day + timedelta(days=rng.randint(1, 40)))
	)
	backdate("CRM Deal", doc.name, rep, _dt(last_touch, rng.randint(8, 17)))
	frappe.db.set_value("CRM Deal", doc.name, "creation", created_ts, update_modified=False)
	if status == "Won":
		frappe.db.set_value("CRM Deal", doc.name, "closed_date", closed_day, update_modified=False)
	_write_stage_log(
		doc.name, rep, status, created_ts, closed_day if status in ("Won", "Lost") else None, rng
	)

	frappe.db.set_value("CRM Lead", lead_name, {"status": "Converted", "converted": 1}, update_modified=False)
	created["deals"].append(doc.name)
	return {
		"name": doc.name,
		"status": status,
		"value": value,
		"closed_date": closed_day,
		"created": created_day,
	}


def _write_stage_log(
	deal: str, rep: str, status: str, created_ts: datetime, closed_day: date | None, rng
) -> None:
	"""Replace the insert-time log with a journey that has real durations.

	The dashboard's stage-velocity factor and the Analyst's time-to-close read
	these rows; a single row stamped "now" would make every deal look brand new.
	"""
	frappe.db.delete("CRM Status Change Log", {"parent": deal, "parenttype": "CRM Deal"})
	final_index = len(OPEN_STAGES)
	if status in ("Won", "Lost"):
		path = [name for name, _p in OPEN_STAGES[: rng.randint(2, len(OPEN_STAGES))]] + [status]
		end = _dt(closed_day, rng.randint(9, 16))
	else:
		final_index = next(i for i, (name, _p) in enumerate(OPEN_STAGES) if name == status)
		path = [name for name, _p in OPEN_STAGES[: final_index + 1]]
		end = None
	span = ((end or frappe.utils.now_datetime()) - created_ts).total_seconds()
	cursor = created_ts
	for idx, stage in enumerate(path):
		is_last = idx == len(path) - 1
		if is_last and end is None:
			to_date = None
		else:
			step = max(3600, span / max(1, len(path)) * rng.uniform(0.6, 1.4))
			to_date = min(cursor + timedelta(seconds=step), end) if end else cursor + timedelta(seconds=step)
			if is_last:
				to_date = end
		row = frappe.get_doc(
			{
				"doctype": "CRM Status Change Log",
				"parent": deal,
				"parenttype": "CRM Deal",
				"parentfield": "status_change_log",
				"idx": idx + 1,
				"from": stage,
				"from_type": _status_type(stage),
				"from_date": cursor,
				"to": path[idx + 1] if not is_last else "",
				"to_type": _status_type(path[idx + 1]) if not is_last else "",
				"to_date": to_date,
				"duration": (to_date - cursor).total_seconds() if to_date else None,
				"log_owner": rep,
			}
		)
		row.insert(ignore_permissions=True)
		if to_date:
			cursor = to_date


_STATUS_TYPES: dict[str, str] = {}


def _status_type(status: str) -> str:
	if status not in _STATUS_TYPES:
		_STATUS_TYPES[status] = frappe.db.get_value("CRM Deal Status", status, "type") or ""
	return _STATUS_TYPES[status]


def _create_quotas(rng, reps, today, won_by_rep_month, currency, created) -> None:
	first = _add_months(get_first_day(today), -MONTHS_BACK)
	for rep in reps:
		history = [v for (user, _m), v in won_by_rep_month.items() if user == rep]
		typical = (sum(history) / max(1, len(history))) if history else 250_000
		for offset in range(0, MONTHS_BACK + 4):
			period = _add_months(first, offset)
			target = round(typical * rng.uniform(0.9, 1.25) * (1 + 0.01 * offset), -3)
			name = f"{rep}::{period.isoformat()}"
			if frappe.db.exists("CRM Quota", name):
				continue
			doc = frappe.get_doc(
				{
					"doctype": "CRM Quota",
					"user": rep,
					"period_start": period,
					"amount": target,
					"currency": currency,
				}
			).insert(ignore_permissions=True)
			created["quotas"].append(doc.name)


def _create_snapshots(rng, reps, today, won_by_rep_month, created) -> None:
	"""One snapshot per month, taken a week before it began, per rep and site-wide."""
	this_month = get_first_day(today)
	for offset in range(MONTHS_BACK, 0, -1):
		month = _add_months(this_month, -offset)
		snapshot_date = month - timedelta(days=7)
		site_total = 0.0
		for rep in reps:
			actual = won_by_rep_month.get((rep, month.strftime("%Y-%m")), 0.0)
			forecast = round(max(actual, 50_000) * rng.uniform(0.7, 1.35), -2)
			site_total += forecast
			doc = frappe.get_doc(
				{
					"doctype": "CRM Forecast Snapshot",
					"snapshot_date": snapshot_date,
					"month": month.strftime("%Y-%m"),
					"scope": "Rep",
					"user": rep,
					"forecasted": forecast,
					"actual_at_snapshot": 0,
				}
			).insert(ignore_permissions=True)
			created["snapshots"].append(doc.name)
		doc = frappe.get_doc(
			{
				"doctype": "CRM Forecast Snapshot",
				"snapshot_date": snapshot_date,
				"month": month.strftime("%Y-%m"),
				"scope": "Site",
				"user": "",
				"forecasted": round(site_total, -2),
				"actual_at_snapshot": 0,
			}
		).insert(ignore_permissions=True)
		created["snapshots"].append(doc.name)


def _create_plans(rng, reps, today, open_deals, created) -> None:
	"""Eight past weeks and the current one, with done and missed items behind today."""
	monday = today - timedelta(days=today.weekday())
	activity_types = ["Call", "Meeting", "Task", "Email"]
	for rep in reps:
		mine = [d for d in open_deals if d["rep"] == rep] or open_deals
		for weeks_ago in range(8, -1, -1):
			week_start = monday - timedelta(weeks=weeks_ago)
			if frappe.db.exists("CRM Rep Plan", {"user": rep, "week_start": week_start}):
				continue
			items = []
			for _ in range(rng.randint(5, 8)):
				planned = week_start + timedelta(days=rng.randint(0, 4))
				deal = rng.choice(mine) if mine else None
				if planned < today:
					status = rng.choices(["Done", "Missed"], weights=[72, 28])[0]
				else:
					status = "Planned"
				items.append(
					{
						"activity_type": rng.choice(activity_types),
						"planned_date": planned,
						"note": rng.choice(
							[
								"Follow up on quotation",
								"Site visit",
								"Confirm delivery slot",
								"Technical call",
								"Send datasheets",
							]
						),
						"reference_doctype": "CRM Deal" if deal else None,
						"reference_docname": deal["name"] if deal else None,
						"status": status,
						"manual_override": 1 if status != "Planned" else 0,
					}
				)
			doc = frappe.get_doc(
				{"doctype": "CRM Rep Plan", "user": rep, "week_start": week_start, "items": items}
			).insert(ignore_permissions=True)
			created["plans"].append(doc.name)


def _create_comments(rng, open_deals, full_names, now, created) -> None:
	"""A dated rhythm of notes on the open deals, so cadence and idle signals have something to read."""
	for deal in open_deals:
		count = rng.randint(1, 4)
		days_open = max(1, (now.date() - deal["created"]).days)
		for i in range(count):
			days_ago = int(days_open * (1 - (i + 1) / (count + 1)))
			if i == 0 and rng.random() < 0.35:
				days_ago = rng.randint(0, 3)
			ts = now - timedelta(days=days_ago, hours=rng.randint(0, 8))
			text = rng.choice(COMMENTS).format(org=deal["org"]["name"], subject=rng.choice(DEAL_SUBJECTS))
			name = insert_comment("CRM Deal", deal["name"], deal["rep"], f"<p>{text}</p>", full_names, ts)
			created["comments"].append(name)


def delete_demo_history(created: dict) -> None:
	"""Remove everything :func:`create_demo_history` wrote, dependents first."""
	if not created:
		return
	if created.get("comments"):
		frappe.db.delete("Comment", {"name": ["in", created["comments"]]})
	for name in created.get("plans", []):
		if frappe.db.exists("CRM Rep Plan", name):
			frappe.delete_doc("CRM Rep Plan", name, ignore_permissions=True, force=True)
	if created.get("snapshots"):
		frappe.db.delete("CRM Forecast Snapshot", {"name": ["in", created["snapshots"]]})
	if created.get("quotas"):
		frappe.db.delete("CRM Quota", {"name": ["in", created["quotas"]]})
	for name in created.get("deals", []):
		if frappe.db.exists("CRM Deal", name):
			frappe.delete_doc("CRM Deal", name, ignore_permissions=True, force=True)
	for name in created.get("leads", []):
		if frappe.db.exists("CRM Lead", name):
			frappe.delete_doc("CRM Lead", name, ignore_permissions=True, force=True)
	for name in created.get("organizations", []):
		if frappe.db.exists("CRM Organization", name):
			frappe.delete_doc("CRM Organization", name, ignore_permissions=True, force=True)
	for doctype, key in (("CRM Territory", "territories"), ("CRM Industry", "industries")):
		for name in created.get(key, []):
			if frappe.db.exists(doctype, name):
				try:
					frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
				except frappe.LinkExistsError:
					# a real record adopted the value meanwhile; it is theirs now
					pass
	frappe.db.commit()
