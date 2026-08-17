# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""One number, one definition — across modules and across languages.

Thresholds here are read by more than one thing: a module constant is the
default a pure finder falls back to, ``SIGNAL_DEFAULTS`` is what an admin sees
in Settings, and a few are also written in JavaScript because a badge has to
band a score without a round trip. Nothing in the language stops those copies
parting, and when they part nothing fails — the tile counts one population and
the badges describe another, both looking authoritative.

So the copies are asserted equal here. These tests are cheap and slightly dull,
which is the point: the failure they prevent is silent.
"""

from __future__ import annotations

import re
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from crm.agent.config import SIGNAL_DEFAULTS
from crm.agent.predict import AT_RISK_BELOW
from crm.agent.signals import (
	CLOSE_HORIZON_DAYS,
	DISMISS_COOLDOWN_DAYS,
	IDLE_DEAL_DAYS,
	SUGGESTION_TTL_DAYS,
)

SUGGESTIONS_JS = Path(frappe.get_app_path("crm", "..", "frontend", "src", "utils", "suggestions.js"))


def js_const(name: str) -> float:
	"""The numeric literal exported as ``name`` from suggestions.js.

	Parsed rather than duplicated: a copy of the value in this file would be the
	very thing being guarded against.
	"""
	match = re.search(rf"^export const {name} = (-?[\d.]+)$", SUGGESTIONS_JS.read_text(), re.MULTILINE)
	if not match:
		raise AssertionError(
			f"{name} is no longer an exported numeric constant in {SUGGESTIONS_JS.name}. "
			"If it moved, this guard has to move with it -- do not delete it."
		)
	return float(match.group(1))


class SignalDefaultsTest(UnitTestCase):
	"""The module constants are the admin's defaults, not a second opinion."""

	def test_the_finder_defaults_are_the_settings_defaults(self):
		self.assertEqual(
			{
				"idle_deal_days": IDLE_DEAL_DAYS,
				"dismiss_cooldown_days": DISMISS_COOLDOWN_DAYS,
				"suggestion_ttl_days": SUGGESTION_TTL_DAYS,
				"close_horizon_days": CLOSE_HORIZON_DAYS,
			},
			{key: SIGNAL_DEFAULTS[key] for key in SIGNAL_DEFAULTS if key != "signals_enabled"},
		)

	def test_predict_and_signals_agree_on_the_close_horizon(self):
		"""They were two independent 14s until the import replaced one of them."""
		from crm.agent import predict, signals

		self.assertIs(predict.CLOSE_HORIZON_DAYS, signals.CLOSE_HORIZON_DAYS)


class CrossLanguageThresholdTest(UnitTestCase):
	"""The numbers that exist in both Python and JavaScript."""

	def test_the_at_risk_boundary_is_the_same_number_on_both_sides(self):
		"""``AT_RISK_BELOW`` gates the dashboard tile; ``HEALTH_AT_RISK`` gates the
		badge on the record. Same boundary, so it must move on both sides at once.

		This pins the *boundary* only, and deliberately does not bless what either
		side calls the bands it divides -- they do not currently agree. The tile
		counts ``score < 40`` and calls that "Deals at risk"; the badge calls
		40-69 "At risk" and reserves "Critical" for ``< 40``. So the tile's
		population is exactly the badge's *Critical* set, and a deal the record
		page badges "At risk" is not in the tile at all. Reconciling the two
		changes either a label or a number a manager reads, so it is written up
		in docs/PILOT-READINESS.md rather than decided here.
		"""
		self.assertEqual(js_const("HEALTH_AT_RISK"), float(AT_RISK_BELOW))

	def test_the_parser_finds_a_constant_that_is_really_there(self):
		"""The guard above passes vacuously if the regex silently matches nothing,
		so prove the parser reads a known-present value correctly."""
		self.assertEqual(js_const("HEALTH_HEALTHY"), 70.0)

	def test_the_parser_refuses_a_constant_that_is_not_there(self):
		with self.assertRaises(AssertionError):
			js_const("NO_SUCH_THRESHOLD")
