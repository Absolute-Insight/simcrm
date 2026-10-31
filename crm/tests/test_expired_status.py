"""Expired: a quote that ran out, not a lost deal.

The sweep used to close such deals as Lost ("Quote expired"). Expired is its own
status, of type On Hold, so the deal can still go on to Won or Lost -- by a rep,
or by its quote's outcome in Acumatica.
"""

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

	def test_the_patch_reopens_the_sweeps_lost_quotes_as_expired(self):
		if not frappe.db.exists("CRM Lost Reason", LOST_EXPIRED):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": LOST_EXPIRED}).insert()
		if not frappe.db.exists("CRM Lost Reason", "Price"):
			frappe.get_doc({"doctype": "CRM Lost Reason", "lost_reason": "Price"}).insert()
		swept = self._deal("Lost", LOST_EXPIRED)
		by_hand = self._deal("Lost", "Price")
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
