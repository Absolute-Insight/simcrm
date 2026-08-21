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
	MAX_OPEN_PER_USER,
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
				"max_open_per_user": MAX_OPEN_PER_USER,
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
		badge on the record. Same boundary, so it must move on both sides at once."""
		self.assertEqual(js_const("HEALTH_AT_RISK"), float(AT_RISK_BELOW))


class BandVocabularyTest(UnitTestCase):
	"""The tile and the badge have to mean the same thing by the same word.

	They did not. The tile counted ``score < 40`` and called it "Deals at risk",
	while the badge calls 40-69 "At risk" and reserves "Critical" for ``< 40`` --
	so the tile's population was exactly the badge's *Critical* set, and a manager
	reading "8 deals at risk" beside thirty "At risk" badges was told two
	different things by one word. The tile is now "Critical deals". The number it
	shows never changed; only the label was wrong.
	"""

	def test_the_tile_uses_the_badge_word_for_the_band_it_counts(self):
		from crm.api.dashboard import get_deals_at_risk

		title = get_deals_at_risk()["title"]
		self.assertIn("Critical", title)
		self.assertNotIn("at risk", title.casefold())

	def test_the_badge_still_reserves_critical_for_the_band_the_tile_counts(self):
		"""The other half. If the JS ever renamed its ``< 40`` band, the tile's
		title would be borrowing a word that no longer means that."""
		source = SUGGESTIONS_JS.read_text()
		critical = re.search(r"key: 'critical',\s*\n\s*label: __\('([^']+)'\)", source)
		self.assertIsNotNone(critical, "the critical band is no longer shaped as expected")
		self.assertEqual(critical.group(1), "Critical")

	def test_the_middle_band_is_the_one_called_at_risk(self):
		source = SUGGESTIONS_JS.read_text()
		at_risk = re.search(r"key: 'at_risk',\s*\n\s*label: __\('([^']+)'\)", source)
		self.assertIsNotNone(at_risk, "the at-risk band is no longer shaped as expected")
		self.assertEqual(at_risk.group(1), "At risk")

	def test_the_parser_finds_a_constant_that_is_really_there(self):
		"""The guard above passes vacuously if the regex silently matches nothing,
		so prove the parser reads a known-present value correctly."""
		self.assertEqual(js_const("HEALTH_HEALTHY"), 70.0)

	def test_the_parser_refuses_a_constant_that_is_not_there(self):
		with self.assertRaises(AssertionError):
			js_const("NO_SUCH_THRESHOLD")
