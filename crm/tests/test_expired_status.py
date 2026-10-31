"""Expired: a quote that ran out, not a lost deal.

The sweep used to close such deals as Lost ("Quote expired"). Expired is its own
status, of type On Hold, so the deal can still go on to Won or Lost -- by a rep,
or by its quote's outcome in Acumatica.
"""

import json

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_deal_status.crm_deal_status import EXPIRED, ensure_expired_status
from crm.integrations.acumatica.outcomes import LOST_EXPIRED
from crm.patches.v1_0.add_expired_deal_status import execute as convert_expired


class ExpiredStatusTest(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def _drop_expired(self):
		"""Start from a site that has never had the status."""
		frappe.db.delete("CRM Deal Status", EXPIRED)

	def _deal(self, status, lost_reason=None):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Expired-{frappe.generate_hash(length=6)}"}
		).insert(ignore_permissions=True)
		doc = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Qualification"})
		doc.insert(ignore_permissions=True)
		if status != "Qualification":
			doc.status = status
			doc.lost_reason = lost_reason
			doc.save(ignore_permissions=True)
		return doc.name

	def test_the_status_is_on_hold_and_sits_just_before_won(self):
		self._drop_expired()
		won_before = frappe.db.get_value("CRM Deal Status", "Won", "position")
		ensure_expired_status()
		status = frappe.get_doc("CRM Deal Status", EXPIRED)
		self.assertEqual(status.type, "On Hold")
		self.assertEqual(status.position, won_before)
		self.assertEqual(frappe.db.get_value("CRM Deal Status", "Won", "position"), won_before + 1)

	def test_ensuring_it_twice_changes_nothing(self):
		ensure_expired_status()
		positions = dict(frappe.get_all("CRM Deal Status", fields=["name", "position"], as_list=True))
		ensure_expired_status()
		self.assertEqual(
			dict(frappe.get_all("CRM Deal Status", fields=["name", "position"], as_list=True)), positions
		)

	def test_an_expired_deal_can_still_be_won_or_lost(self):
		ensure_expired_status()
		for outcome, reason in (("Won", None), ("Lost", "Other")):
			with self.subTest(outcome=outcome):
				name = self._deal(EXPIRED)
				doc = frappe.get_doc("CRM Deal", name)
				doc.status = outcome
				doc.lost_reason = reason
				doc.lost_notes = "price" if reason else None
				doc.save(ignore_permissions=True)
				self.assertEqual(frappe.db.get_value("CRM Deal", name, "status"), outcome)

	def _lost_by(self, user, reason, notes=None):
		"""A deal taken to Lost by ``user``, with the status log saying so."""
		name = self._deal("Qualification")
		frappe.set_user(user)
		try:
			doc = frappe.get_doc("CRM Deal", name)
			doc.status = "Lost"
			doc.lost_reason = reason
			doc.lost_notes = notes
			doc.flags.ignore_permissions = True
			doc.save()
		finally:
			frappe.set_user("Administrator")
		return name

	def _reason(self, reason):
		if not frappe.db.exists("CRM Lost Reason", reason):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": reason}).insert()

	def test_a_rep_who_chose_the_reason_keeps_their_decision(self):
		""" "Quote expired" is a reason anyone can pick; only the sweep's closes move."""
		self._reason(LOST_EXPIRED)
		rep = "expired-rep@crmtest.test"
		if not frappe.db.exists("User", rep):
			user = frappe.get_doc(
				{"doctype": "User", "email": rep, "first_name": "Expired Rep", "send_welcome_email": 0}
			).insert(ignore_permissions=True)
			user.add_roles("Sales User")
		chosen = self._lost_by(rep, LOST_EXPIRED)
		self._drop_expired()

		convert_expired()

		self.assertEqual(frappe.db.get_value("CRM Deal", chosen, "status"), "Lost")

	def test_a_deal_with_lost_notes_is_left_alone(self):
		self._reason(LOST_EXPIRED)
		noted = self._lost_by("Administrator", LOST_EXPIRED, "customer went to a competitor")
		self._drop_expired()

		convert_expired()

		status, notes = frappe.db.get_value("CRM Deal", noted, ["status", "lost_notes"])
		self.assertEqual(status, "Lost")
		self.assertEqual(notes, "customer went to a competitor")

	def test_the_patch_keeps_who_last_touched_the_deal(self):
		self._reason(LOST_EXPIRED)
		swept = self._lost_by("Administrator", LOST_EXPIRED)
		stamp = "2026-01-05 09:00:00.000000"
		frappe.db.set_value(
			"CRM Deal", swept, {"modified": stamp, "modified_by": "rep@x.test"}, update_modified=False
		)
		self._drop_expired()

		convert_expired()

		modified, by = frappe.db.get_value("CRM Deal", swept, ["modified", "modified_by"])
		self.assertEqual(str(modified), "2026-01-05 09:00:00")
		self.assertEqual(by, "rep@x.test")

	def test_a_deal_that_cannot_validate_still_moves_and_is_logged(self):
		from unittest.mock import patch

		self._reason(LOST_EXPIRED)
		swept = self._lost_by("Administrator", LOST_EXPIRED)
		self._drop_expired()

		with patch("frappe.model.document.Document.save", side_effect=frappe.ValidationError("no value")):
			convert_expired()

		self.assertEqual(frappe.db.get_value("CRM Deal", swept, "status"), EXPIRED)
		log = frappe.get_doc("CRM Deal", swept).status_change_log
		self.assertEqual(log[-1].get("from"), EXPIRED)
		self.assertEqual(log[-2].get("to"), EXPIRED)

	def test_the_next_pull_rereads_every_quote(self):
		from crm.integrations.acumatica.outcomes import REREAD_ALL_QUOTES

		self._reason(LOST_EXPIRED)
		self._lost_by("Administrator", LOST_EXPIRED)
		self._drop_expired()
		frappe.defaults.clear_default(REREAD_ALL_QUOTES)

		convert_expired()

		self.assertTrue(frappe.db.get_default(REREAD_ALL_QUOTES))
		frappe.defaults.clear_default(REREAD_ALL_QUOTES)

	def test_a_saved_board_gains_the_column_before_won(self):
		view = frappe.get_doc(
			{
				"doctype": "CRM View Settings",
				"dt": "CRM Deal",
				"type": "kanban",
				"column_field": "status",
				"label": "Board",
				"user": "Administrator",
				"kanban_columns": '[{"name": "Negotiation"}, {"name": "Won"}, {"name": "Lost"}]',
			}
		).insert(ignore_permissions=True)
		self._drop_expired()

		convert_expired()
		convert_expired()

		columns = json.loads(frappe.db.get_value("CRM View Settings", view.name, "kanban_columns"))
		self.assertEqual([c["name"] for c in columns], ["Negotiation", EXPIRED, "Won", "Lost"])

	def test_a_malformed_saved_board_does_not_stop_the_migrate(self):
		view = frappe.get_doc(
			{
				"doctype": "CRM View Settings",
				"dt": "CRM Deal",
				"type": "kanban",
				"column_field": "status",
				"label": "Bad",
				"user": "Administrator",
				"kanban_columns": '["x"]',
			}
		).insert(ignore_permissions=True)
		self._drop_expired()

		convert_expired()

		self.assertEqual(frappe.db.get_value("CRM View Settings", view.name, "kanban_columns"), '["x"]')

	def test_a_site_whose_expired_status_closes_deals_is_not_touched(self):
		self._reason(LOST_EXPIRED)
		swept = self._lost_by("Administrator", LOST_EXPIRED)
		self._drop_expired()
		frappe.get_doc(
			{
				"doctype": "CRM Deal Status",
				"deal_status": EXPIRED,
				"type": "Lost",
				"color": "red",
				"position": 20,
			}
		).insert()

		convert_expired()

		self.assertEqual(frappe.db.get_value("CRM Deal", swept, "status"), "Lost")

	def test_expired_deals_are_out_of_the_open_tiles_and_the_forecast(self):
		from crm.api.dashboard import forecast_by_month, get_ongoing_deals

		ensure_expired_status()
		today = frappe.utils.nowdate()
		name = self._deal("Qualification")
		frappe.db.set_value(
			"CRM Deal",
			name,
			{"expected_closure_date": today, "expected_deal_value": 7_777_777, "probability": 100},
		)

		def forecast():
			return sum(forecast_by_month(today, today).values())

		open_tile, open_forecast = get_ongoing_deals(today, today)["value"], forecast()

		frappe.db.set_value("CRM Deal", name, "status", EXPIRED)

		self.assertEqual(get_ongoing_deals(today, today)["value"], open_tile - 1)
		self.assertLess(forecast(), open_forecast)

	def test_the_patch_reopens_the_sweeps_lost_quotes_as_expired(self):
		if not frappe.db.exists("CRM Lost Reason", LOST_EXPIRED):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": LOST_EXPIRED}).insert()
		if not frappe.db.exists("CRM Lost Reason", "Price"):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Price"}).insert()
		swept = self._lost_by("Administrator", LOST_EXPIRED)
		by_hand = self._lost_by("Administrator", "Price")
		self._drop_expired()

		convert_expired()

		status, reason = frappe.db.get_value("CRM Deal", swept, ["status", "lost_reason"])
		self.assertEqual(status, EXPIRED)
		self.assertFalse(reason)
		log = frappe.get_doc("CRM Deal", swept).status_change_log
		self.assertEqual(log[-1].get("from"), EXPIRED, "the move is in the status log")
		self.assertEqual(
			frappe.db.get_value("CRM Deal", by_hand, ["status", "lost_reason"]),
			("Lost", "Price"),
			"a deal a person lost for a reason of their own stays lost",
		)
