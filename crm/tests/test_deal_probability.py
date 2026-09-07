# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A deal's probability follows its stage until someone sets it by hand.

Every probability-weighted number reads ``CRM Deal.probability``; it used to be
written once at creation from the first stage's default and never again, so the
forecast did not move as deals advanced. ``closed_date`` likewise used to be
re-stamped with today on every save that entered Won, even with a date supplied.
"""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase


def stage(type_: str, exclude=()) -> tuple[str, float]:
	filters = {"type": type_}
	if exclude:
		filters["name"] = ("not in", list(exclude))
	rows = frappe.get_all(
		"CRM Deal Status", filters=filters, fields=["name", "probability"], order_by="position asc"
	)
	assert rows, f"no CRM Deal Status of type {type_}: {frappe.get_all('CRM Deal Status', fields=['name', 'type'])}"
	return rows[0].name, float(rows[0].probability or 0)


class DealProbabilityFollowsStageTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		# the shipped statuses: one Open stage (Qualification), then Ongoing ones
		self.first, self.first_p = stage("Open")
		self.second, self.second_p = stage("Ongoing")
		self.won, _ = stage("Won")
		self.org = (
			frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Probability Org"})
			.insert(ignore_if_duplicate=True)
			.name
		)
		self.deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": self.org, "status": self.first}
		).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Deal", self.deal.name, force=True, ignore_permissions=True)
		super().tearDown()

	def test_a_new_deal_starts_at_its_stages_default(self):
		self.assertEqual(float(self.deal.probability), self.first_p)

	def test_moving_stage_moves_a_default_probability(self):
		self.deal.status = self.second
		self.deal.save(ignore_permissions=True)
		self.assertEqual(float(self.deal.probability), self.second_p)

	def test_a_hand_set_probability_survives_a_stage_change(self):
		hand_set = 33.0
		self.assertNotEqual(hand_set, self.second_p)
		self.deal.probability = hand_set
		self.deal.save(ignore_permissions=True)
		self.deal.status = self.second
		self.deal.save(ignore_permissions=True)
		self.assertEqual(float(self.deal.probability), hand_set)

	def test_a_supplied_closed_date_is_not_overwritten_on_the_way_into_won(self):
		self.deal.status = self.won
		self.deal.closed_date = "2026-03-15"
		self.deal.save(ignore_permissions=True)
		self.assertEqual(str(self.deal.closed_date), "2026-03-15")
		# and a later save while Won leaves it alone as well
		self.deal.expected_deal_value = (self.deal.expected_deal_value or 0) + 1
		self.deal.save(ignore_permissions=True)
		self.assertEqual(str(self.deal.closed_date), "2026-03-15")

	def test_entering_won_without_a_date_stamps_today(self):
		self.deal.status = self.won
		self.deal.save(ignore_permissions=True)
		self.assertEqual(str(self.deal.closed_date), frappe.utils.nowdate())
