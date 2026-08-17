# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Runs the golden set against a live endpoint and reports a confusion matrix.

No pass/fail gate, for the reason the injection evals give: a suite that fails on
every model gets switched off within a week. What this produces is five counts per
field, so two models can be compared and a regression is visible.

The reporting rule that matters more than any of the numbers: **a case that did
not run is never counted as a case that went well.** With no endpoint configured,
every field would be blank, every abstention case would "pass", and the report
would show a model abstaining perfectly while having done nothing at all. So an
errored case is its own outcome and suppresses the summary line.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import frappe

from crm.agent import client
from crm.agent.config import AgentConfig, get_config
from crm.agent.errors import AgentUnavailable, SchemaMismatch
from crm.agent.schemas import SiteFacts
from crm.domain_enrichment import model_fallback
from crm.domain_enrichment.evals.cases import CASES, INDUSTRIES, Case

SCORED_FIELDS = ("company_name", "description", "industry")

CORRECT = "correct"
MISSED = "missed"
WRONG = "wrong"
HALLUCINATED = "hallucinated"
ABSTAINED = "abstained"
# Harmful outcomes: a falsehood written onto a CRM record. Kept as a set rather
# than "everything except correct" because `missed` is a non-event, and lumping it
# in makes a cautious model look as bad as an inventive one.
HARMFUL = (WRONG, HALLUCINATED)


@dataclass
class CaseResult:
	case: Case
	outcomes: dict = field(default_factory=dict)  # field -> outcome
	got: dict = field(default_factory=dict)  # field -> raw model value
	error: str = ""

	@property
	def ran(self) -> bool:
		return not self.error

	@property
	def harmful(self) -> list[str]:
		return [name for name, outcome in self.outcomes.items() if outcome in HARMFUL]


def score_field(name: str, expected, got: str, must_mention: list[str]) -> str:
	"""One field's outcome. ``expected`` of ``""`` means blank is the right answer.

	``description`` is the exception, and it caught this function out once: a case
	expecting a description does not carry one in ``expected`` -- there is no single
	right sentence -- it carries ``description_must_mention`` instead. Reading the
	absent key as "expect blank" scored every *correct* description as an invention.
	So for description, a non-empty ``must_mention`` is what says a value is wanted.
	"""
	got = (got or "").strip()

	if name == "description":
		if not must_mention:
			return ABSTAINED if not got else HALLUCINATED
		if not got:
			return MISSED
		# Whether it is about the right thing at all. Weak on purpose: it catches a
		# description of some other company, and does not pretend to grade prose.
		lowered = got.lower()
		return CORRECT if any(term.lower() in lowered for term in must_mention) else WRONG

	want = (expected or "").strip()
	if not want:
		return ABSTAINED if not got else HALLUCINATED
	if not got:
		return MISSED
	return CORRECT if got.casefold() == want.casefold() else WRONG


def scored_fields(case: Case) -> list[str]:
	"""Which fields this case makes a claim about.

	A case that says nothing about a field is not scored on it -- see
	``login_wall_reveals_only_a_product_name``, where both a product name and a
	blank are defensible reads and a golden set should not punish either.
	"""
	names = []
	for name in SCORED_FIELDS:
		if name == "description":
			if case.description_must_mention or "description" in case.expected:
				names.append(name)
		elif name in case.expected:
			names.append(name)
	return names


def run_case(case: Case, cfg: AgentConfig) -> CaseResult:
	scored = scored_fields(case)
	messages = model_fallback.build_messages(list(SCORED_FIELDS), INDUSTRIES, case.text, case.website)
	try:
		facts = client.complete(cfg, SiteFacts, messages)
	except (AgentUnavailable, SchemaMismatch) as exc:
		return CaseResult(case=case, error=str(exc))
	except Exception as exc:  # a broken harness must not read as a model failure
		return CaseResult(case=case, error=f"{type(exc).__name__}: {exc}")

	result = CaseResult(case=case)
	for name in scored:
		got = getattr(facts, name, "") or ""
		result.got[name] = got
		result.outcomes[name] = score_field(
			name, case.expected.get(name, ""), got, case.description_must_mention
		)
	return result


def run(cases=None, cfg: AgentConfig = None) -> list[CaseResult]:
	cfg = cfg or get_config()
	return [run_case(case, cfg) for case in (cases or CASES)]


def tally(results) -> dict:
	counts = {outcome: 0 for outcome in (CORRECT, MISSED, WRONG, HALLUCINATED, ABSTAINED)}
	for result in results:
		for outcome in result.outcomes.values():
			counts[outcome] += 1
	return counts


def format_report(results, cfg: AgentConfig) -> str:
	"""A table meant to be pasted beside the previous run."""
	ran = [r for r in results if r.ran]
	errored = [r for r in results if not r.ran]
	counts = tally(ran)
	scored = sum(counts.values())

	lines = [
		f"Enrichment golden set — model: {cfg.model} @ {cfg.base_url}",
		"",
		f"{'case':38} {'name':>12} {'desc':>12} {'industry':>13}",
		"-" * 78,
	]
	for result in results:
		if not result.ran:
			lines.append(f"{result.case.name:38} {'DID NOT RUN — ' + result.error[:24]:>39}")
			continue
		cells = [f"{result.outcomes.get(name, '-'):>12}" for name in SCORED_FIELDS]
		lines.append(f"{result.case.name:38} {cells[0]} {cells[1]} {cells[2][:13]:>13}")

	lines.append("-" * 78)

	if errored:
		lines.append(
			f"{len(errored)}/{len(results)} cases DID NOT RUN — the endpoint did not answer. "
			"Nothing below is a measurement of the model."
		)
	if not scored:
		# The line this whole file is arranged around. With no endpoint every field
		# is blank, every abstention case "passes", and a hit-rate report would show
		# a model abstaining flawlessly while having done nothing whatsoever.
		lines.append("Nothing was measured.")
		return "\n".join(lines)

	harmful = counts[WRONG] + counts[HALLUCINATED]
	lines += [
		f"{scored} fields scored across {len(ran)} cases that ran.",
		f"  correct      {counts[CORRECT]:>3}",
		f"  abstained    {counts[ABSTAINED]:>3}   (correctly left blank)",
		f"  missed       {counts[MISSED]:>3}   (safe: the field stays as blank as the rules left it)",
		f"  wrong        {counts[WRONG]:>3}   HARMFUL",
		f"  hallucinated {counts[HALLUCINATED]:>3}   HARMFUL (invented where the page said nothing)",
		"",
		f"{harmful} harmful of {scored} scored. This is the number to watch, not the correct count:",
		"a model that answers everything scores well on 'correct' and writes fiction",
		"into a CRM. 'missed' is the failure this feature is allowed to have.",
	]
	offenders = [r for r in ran if r.harmful]
	if offenders:
		lines.append("")
		for result in offenders:
			for name in result.harmful:
				got = (result.got.get(name) or "")[:60]
				want = result.case.expected.get(name, "") or "(nothing)"
				lines.append(f"  {result.case.name}.{name}: wanted {want!r}, got {got!r}")
	return "\n".join(lines)


@frappe.whitelist()
def run_and_print():
	"""``bench --site <site> execute crm.domain_enrichment.evals.runner.run_and_print``"""
	cfg = get_config()
	if not cfg.enabled:
		print(
			"The agent tier is disabled, so no case can run. Nothing was measured.\n"
			"Enable it in CRM Agent Settings and point base_url at an endpoint first."
		)
		return
	print(format_report(run(cfg=cfg), cfg))
