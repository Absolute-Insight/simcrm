# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The tile row's fan-out, and the rate limit that has to allow for it.

One dashboard view is one ``get_dashboard`` -- its panels are all computed
server-side inside it -- plus one ``get_chart`` *per tile in the tile row*. Both
endpoints were capped at 60 a minute, which reads as generous and is not: it
allowed twelve views of the tile row, and a manager clicking period → territory
→ rep → period in a demo reaches that in seconds.

The failure is worse than an error. The 429 lands on the tiles only, so the
panels below keep updating while the numbers above them freeze: the page still
looks like it is working, and the two halves quietly disagree.

The tile count lives in ``Dashboard.vue`` and the limit lives in Python, so
nothing in either language can notice them parting. This reads the catalogue out
of the component -- the same approach the threshold guard takes with
``suggestions.js`` -- so adding a sixth tile without raising the limit fails
here instead of shipping a quieter dashboard.
"""

from __future__ import annotations

import re
from pathlib import Path

import frappe
from frappe.tests import UnitTestCase

from crm.api.dashboard import (
	CHART_CALLS_PER_MINUTE,
	DASHBOARD_TILE_COUNT,
	DASHBOARD_VIEWS_PER_MINUTE,
)

# The filename is joined on rather than passed to get_app_path: that helper
# lowercases the segments it is given, so "Dashboard.vue" arrives as
# "dashboard.vue" and the read fails on a case-sensitive filesystem. The other
# guard in this codebase reads suggestions.js and never noticed, because that
# name is already lowercase.
DASHBOARD_VUE = Path(frappe.get_app_path("crm", "..", "frontend", "src", "pages")) / "Dashboard.vue"


def tiles_in_catalogue() -> list[str]:
	"""The tile names ``Dashboard.vue`` fires a ``get_chart`` for.

	Parsed rather than restated: a copy of the number in this file would be the
	very thing being guarded against.
	"""
	source = DASHBOARD_VUE.read_text()
	block = re.search(r"const TILE_CATALOGUE = \[(.*?)\n\]", source, re.S)
	if not block:
		raise AssertionError(
			"TILE_CATALOGUE is no longer shaped as expected in Dashboard.vue. "
			"If the tile row moved, this guard has to move with it -- do not delete it."
		)
	return re.findall(r"name:\s*'([^']+)'", block.group(1))


class TileFanOutTest(UnitTestCase):
	def test_the_python_tile_count_matches_the_component(self):
		self.assertEqual(len(tiles_in_catalogue()), DASHBOARD_TILE_COUNT)

	def test_the_chart_limit_allows_a_full_view_for_every_dashboard_view(self):
		"""The relationship that was wrong: the tile row must not run out of
		budget before the endpoint that renders the rest of the page does."""
		self.assertGreaterEqual(
			CHART_CALLS_PER_MINUTE,
			DASHBOARD_VIEWS_PER_MINUTE * DASHBOARD_TILE_COUNT,
		)

	def test_the_endpoints_carry_those_limits(self):
		"""Guards against the constants being defined and then not used, which
		is what a rename or a merge conflict leaves behind."""
		source = Path(frappe.get_app_path("crm", "api", "dashboard.py")).read_text()
		self.assertIn("@rate_limit(limit=DASHBOARD_VIEWS_PER_MINUTE, seconds=60)", source)
		self.assertIn("@rate_limit(limit=CHART_CALLS_PER_MINUTE, seconds=60)", source)

	def test_the_parser_finds_real_tile_names(self):
		"""The guard above passes vacuously if the regex matches an empty list."""
		names = tiles_in_catalogue()
		self.assertIn("ongoing_deals", names)
		self.assertTrue(all(names))

	def test_the_parser_raises_rather_than_returning_nothing(self):
		"""A regex guard that silently matches nothing passes forever."""
		from unittest import mock

		with mock.patch.object(Path, "read_text", return_value="no catalogue here"):
			with self.assertRaises(AssertionError):
				tiles_in_catalogue()


class UserRateLimitTest(UnitTestCase):
	def test_a_user_over_budget_gets_the_same_error_as_the_ip_limiter(self):
		from unittest import mock

		from crm.api import dashboard

		with mock.patch.object(dashboard, "user_rate_limited", return_value=True):
			with self.assertRaises(frappe.TooManyRequestsError):
				dashboard.check_user_rate("dashboard", 1)
		with mock.patch.object(dashboard, "user_rate_limited", return_value=False):
			dashboard.check_user_rate("dashboard", 1)

	def test_the_user_budget_keeps_the_tile_fan_out_relationship(self):
		from crm.api.dashboard import USER_CHART_CALLS_PER_MINUTE, USER_DASHBOARD_VIEWS_PER_MINUTE

		self.assertGreaterEqual(
			USER_CHART_CALLS_PER_MINUTE, USER_DASHBOARD_VIEWS_PER_MINUTE * DASHBOARD_TILE_COUNT
		)
		self.assertGreaterEqual(USER_DASHBOARD_VIEWS_PER_MINUTE, DASHBOARD_VIEWS_PER_MINUTE)
