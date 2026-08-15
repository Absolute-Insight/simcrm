# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Deal-health scoring — explainable by construction.

``score_deal`` is a transparent heuristic over structured features only
(PLAN.md Phase 8, constraint 2: never message text). It starts at 100 and
subtracts named, weighted factors; the factors list always accounts exactly
for the deduction, so the UI can show *why* a deal scores what it does.
The model tier, when enabled, may re-rank or annotate — it never replaces
this number silently.

Three of the factors are forward-looking rather than post-mortem. Elapsed
time (idle, stage age, an overdue close date) says what already happened;
*stage velocity* against the historical median for that same stage, *slip
risk* against a close date still in the future, and a *decaying cadence*
against the deal's own rhythm say what is about to. Both kinds are here
because a health score that only counts elapsed days ranks a dead deal above
a fast-decaying live one.

Every weight is a named constant rather than a literal inside a factor dict:
the numbers are the tuning surface, and a tuning surface nobody can find is
not one.

Model-free like ``signals``: this module must not import ``crm.agent.client``.
"""

from __future__ import annotations

from datetime import timedelta

import frappe

from crm.agent.signals import EARLY_STAGE_PROBABILITY, cadence_ratio

IDLE_GRACE_DAYS = 3
STAGE_GRACE_DAYS = 21
CLOSE_HORIZON_DAYS = 14
# Below this multiple of the stage's historical median, a deal is moving normally.
SLOW_STAGE_RATIO = 1.5
# Below this multiple of the deal's own median contact gap, so is its cadence.
COOLING_RATIO = 2.0

# A deal below this is "at risk". One definition, read by the stored-score job
# and by the dashboard tile that counts what it wrote.
AT_RISK_BELOW = 40

IDLE_WEIGHT_PER_DAY = 4
IDLE_WEIGHT_CAP = 50
STAGE_STAGNATION_WEIGHT_CAP = 20
SLOW_STAGE_WEIGHT_PER_MULTIPLE = 8
SLOW_STAGE_WEIGHT_CAP = 20
CLOSE_OVERDUE_BASE_WEIGHT = 10
CLOSE_OVERDUE_WEIGHT_CAP = 30
SLIP_RISK_WEIGHT = 25
COOLING_WEIGHT_PER_MULTIPLE = 6
COOLING_WEIGHT_CAP = 20
NO_OPEN_TASK_WEIGHT = 15
NO_INBOUND_WEIGHT = 10

# Sample size below which a stage median is one team member's habit, not a norm.
MIN_STAGE_SAMPLES = 5
STAGE_SAMPLE_LIMIT = 500


def score_deal(features: dict) -> dict:
	"""Score 0-100 with factor attribution.

	Expected feature keys (missing/None values are treated as unknown and
	never punished): ``idle_days``, ``days_in_stage``, ``stage``,
	``stage_median_days``, ``stage_probability``, ``days_to_close`` (negative =
	past due), ``cadence_ratio``, ``has_open_task``, ``inbound_ratio``.
	"""
	factors = []

	idle_days = features.get("idle_days")
	if idle_days is not None and idle_days > IDLE_GRACE_DAYS:
		factors.append(
			{
				"key": "idle",
				"label": f"No activity for {idle_days} days",
				"weight": min(IDLE_WEIGHT_CAP, (idle_days - IDLE_GRACE_DAYS) * IDLE_WEIGHT_PER_DAY),
			}
		)

	days_in_stage = features.get("days_in_stage")
	if days_in_stage is not None and days_in_stage > STAGE_GRACE_DAYS:
		factors.append(
			{
				"key": "stage_stagnation",
				"label": f"In the same stage for {days_in_stage} days",
				"weight": min(STAGE_STAGNATION_WEIGHT_CAP, days_in_stage - STAGE_GRACE_DAYS),
			}
		)

	stage_median = features.get("stage_median_days")
	if days_in_stage is not None and stage_median:
		ratio = days_in_stage / stage_median
		if ratio >= SLOW_STAGE_RATIO:
			stage = features.get("stage") or "this stage"
			factors.append(
				{
					"key": "slow_stage",
					"label": (
						f"{ratio:.1f}x slower through {stage} than the usual " f"{stage_median:.0f} days"
					),
					"weight": min(
						SLOW_STAGE_WEIGHT_CAP,
						round((ratio - 1) * SLOW_STAGE_WEIGHT_PER_MULTIPLE),
					),
				}
			)

	days_to_close = features.get("days_to_close")
	if days_to_close is not None and days_to_close < 0:
		overdue = -days_to_close
		factors.append(
			{
				"key": "close_overdue",
				"label": f"Expected close date passed {overdue} days ago",
				"weight": min(CLOSE_OVERDUE_WEIGHT_CAP, CLOSE_OVERDUE_BASE_WEIGHT + overdue),
			}
		)

	stage_probability = features.get("stage_probability")
	if (
		days_to_close is not None
		and 0 <= days_to_close <= CLOSE_HORIZON_DAYS
		and stage_probability is not None
		and stage_probability < EARLY_STAGE_PROBABILITY
	):
		# fires while the date is still ahead — the only point at which the rep
		# can do anything about it
		factors.append(
			{
				"key": "slip_risk",
				"label": (
					f"Due to close in {days_to_close} days from a stage that closes "
					f"{stage_probability:g}% of the time"
				),
				"weight": SLIP_RISK_WEIGHT,
			}
		)

	ratio = features.get("cadence_ratio")
	if ratio is not None and ratio >= COOLING_RATIO:
		factors.append(
			{
				"key": "cadence_slowing",
				"label": f"Contact has slowed to {ratio:.1f}x this deal's own gap",
				"weight": min(COOLING_WEIGHT_CAP, round((ratio - 1) * COOLING_WEIGHT_PER_MULTIPLE)),
			}
		)

	if features.get("has_open_task") is False:
		factors.append(
			{
				"key": "no_open_task",
				"label": "No open task scheduled",
				"weight": NO_OPEN_TASK_WEIGHT,
			}
		)

	inbound_ratio = features.get("inbound_ratio")
	if inbound_ratio is not None and inbound_ratio <= 0.05:
		factors.append(
			{
				"key": "no_inbound",
				"label": "Conversation is one-sided — no inbound responses",
				"weight": NO_INBOUND_WEIGHT,
			}
		)

	score = max(0, 100 - sum(f["weight"] for f in factors))
	return {"score": score, "factors": factors}


def _stage_median_days(status: str) -> float | None:
	"""Median days deals historically spent in ``status`` before leaving it.

	Read from the status change log's own duration column, so the baseline is
	this site's history rather than a number somebody guessed. Returns None
	below MIN_STAGE_SAMPLES: comparing a deal against two other deals produces
	a confident-looking factor backed by nothing.
	"""
	log = frappe.qb.DocType("CRM Status Change Log")
	rows = (
		frappe.qb.from_(log)
		.select(log.duration)
		.where(log.parenttype == "CRM Deal")
		.where(log["from"] == status)
		.where(log.duration > 0)
		.limit(STAGE_SAMPLE_LIMIT)
		.run()
	)
	durations = sorted(row[0] / 86400.0 for row in rows if row[0])
	if len(durations) < MIN_STAGE_SAMPLES:
		return None
	middle = len(durations) // 2
	if len(durations) % 2:
		return durations[middle]
	return (durations[middle - 1] + durations[middle]) / 2


@frappe.whitelist()
def get_deal_health(name: str) -> dict:
	"""Feature extraction + scoring for one deal, permission-checked."""
	from crm.agent.signals import CADENCE_WINDOW_DAYS, _activity_history, _latest_activity

	deal = frappe.get_doc("CRM Deal", name)
	deal.check_permission("read")
	now = frappe.utils.now_datetime()

	last = _latest_activity([name]).get(name) or deal.creation
	idle_days = max(0, (now - last).days)

	days_in_stage = None
	if deal.status_change_log and deal.status_change_log[-1].to_date:
		days_in_stage = max(0, (now - deal.status_change_log[-1].to_date).days)

	# expected_closure_date, not closed_date: the latter is only written when a
	# deal is Won, so a risk factor keyed on it can never fire on a live deal
	days_to_close = None
	if deal.expected_closure_date:
		days_to_close = (deal.expected_closure_date - now.date()).days

	history = _activity_history([name], now - timedelta(days=CADENCE_WINDOW_DAYS))
	measured = cadence_ratio(history.get(name) or [], now)

	has_open_task = bool(
		frappe.get_all(
			"CRM Task",
			filters={
				"reference_doctype": "CRM Deal",
				"reference_docname": name,
				"status": ("not in", ("Done", "Canceled")),
			},
			limit=1,
		)
	)

	comms = frappe.get_all(
		"Communication",
		filters={"reference_doctype": "CRM Deal", "reference_name": name},
		fields=["sent_or_received"],
		limit_page_length=200,
	)
	inbound_ratio = None
	if comms:
		inbound = sum(1 for c in comms if c.sent_or_received == "Received")
		inbound_ratio = inbound / len(comms)

	return score_deal(
		{
			"idle_days": idle_days,
			"days_in_stage": days_in_stage,
			"stage": deal.status,
			"stage_median_days": _stage_median_days(deal.status),
			"stage_probability": frappe.utils.flt(
				frappe.db.get_value("CRM Deal Status", deal.status, "probability")
			),
			"days_to_close": days_to_close,
			"cadence_ratio": measured[0] if measured else None,
			"has_open_task": has_open_task,
			"inbound_ratio": inbound_ratio,
		}
	)


def score_open_deals(batch_size: int = 1000) -> int:
	"""Hourly: write every open deal's health score onto the deal.

	The dashboard used to score the whole open pipeline on every page load, which
	is 8 seconds of work at 100k deals for a single number, repeated per viewer.
	Scoring is the same for everyone and changes on the hour at most, so it is
	computed once here and the tile becomes a COUNT.

	Feature extraction is shared with :func:`crm.api.dashboard._at_risk_deals`
	(and therefore with :func:`get_deal_health`) so a deal cannot score one way
	in the tile and another on its own page.
	"""
	from crm.api.dashboard import _at_risk_deals

	scored = _at_risk_deals()
	if not scored:
		return 0

	now = frappe.utils.now_datetime()
	Deal = frappe.qb.DocType("CRM Deal")
	for start in range(0, len(scored), batch_size):
		chunk = scored[start : start + batch_size]
		# one UPDATE per batch with a CASE, rather than a write per deal: at 100k
		# deals the per-row version is 100k round trips
		case = frappe.qb.terms.Case()
		for deal in chunk:
			case = case.when(Deal.name == deal["name"], deal["score"])
		(
			frappe.qb.update(Deal)
			.set(Deal.health_score, case.else_(Deal.health_score))
			.set(Deal.health_scored_on, now)
			.where(Deal.name.isin([deal["name"] for deal in chunk]))
			.run()
		)
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: a batch job over the whole pipeline cannot hold one transaction

	# a deal that closed since the last run keeps a stale score, and the tile
	# filters on open status anyway — but clear it so nothing downstream reads a
	# score that no longer describes anything
	Status = frappe.qb.DocType("CRM Deal Status")
	closed = (
		frappe.qb.from_(Deal)
		.join(Status)
		.on(Deal.status == Status.name)
		.select(Deal.name)
		.where(Status.type.isin(["Won", "Lost"]) & Deal.health_scored_on.isnotnull())
		.run(pluck=True)
	)
	if closed:
		# clearing `health_scored_on` is what un-scores a deal: frappe Float columns
		# are NOT NULL DEFAULT 0, so a zeroed score is indistinguishable from the
		# worst possible health, and every reader must gate on the timestamp
		(
			frappe.qb.update(Deal)
			.set(Deal.health_score, 0)
			.set(Deal.health_scored_on, None)
			.where(Deal.name.isin(closed))
			.run()
		)
		if not frappe.flags.in_test:
			frappe.db.commit()  # nosemgrep: a batch job over the whole pipeline cannot hold one transaction

	return len(scored)
