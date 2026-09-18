from datetime import date, timedelta
from unittest.mock import MagicMock

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import outcomes
from crm.integrations.acumatica.install import ensure_custom_fields


def Q(**kw):
	return {k: {"value": v} for k, v in kw.items()}


class OutcomesTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()

	def tearDown(self):
		frappe.db.rollback()

	def _deal(self, quote, status="Proposal/Quotation", closes_in=10, modified_days_ago=0):
		suffix = frappe.generate_hash(length=6)
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Outcome-{suffix}"}
		).insert(ignore_permissions=True)
		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org.name,
				"status": status,
				"expected_closure_date": date.today() + timedelta(days=closes_in),
				"deal_value": 1000,
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Deal", deal.name, "acumatica_sales_quote", quote, update_modified=False)
		if modified_days_ago:
			frappe.db.set_value(
				"CRM Deal",
				deal.name,
				"modified",
				frappe.utils.add_days(frappe.utils.now_datetime(), -modified_days_ago),
				update_modified=False,
			)
		return deal.name


class PullOutcomesTest(OutcomesTestCase):
	"""A quote that was accepted is copied into a sales order and the quote itself is
	Completed; one the customer declined is Canceled or Rejected. Until this, a deal
	stayed open in the CRM until a rep closed it by hand -- twice, once per system."""

	def _client(self, quotes):
		client = MagicMock()
		client.get_page.side_effect = lambda entity, top=100, skip=0, **kw: quotes[skip : skip + top]
		client.settings.request_pause = 0
		client.settings.quote_order_type = "QT"
		return client

	def test_a_completed_quote_wins_the_deal_on_the_date_it_completed(self):
		deal = self._deal("QT000001")
		client = self._client(
			[Q(OrderNbr="QT000001", Status="Completed", LastModified="2026-09-10T08:00:00+02:00")]
		)
		counts = outcomes.pull_quote_outcomes(client, None)
		self.assertEqual(counts, {"won": 1, "lost": 0, "unchanged": 0})
		self.assertEqual(
			frappe.db.get_value("CRM Deal", deal, ["status", "closed_date"]), ("Won", date(2026, 9, 10))
		)

	def test_a_canceled_or_rejected_quote_loses_the_deal_with_the_reason(self):
		a = self._deal("QT000002")
		b = self._deal("QT000003")
		client = self._client(
			[
				Q(OrderNbr="QT000002", Status="Canceled", LastModified="2026-09-11T08:00:00+02:00"),
				Q(OrderNbr="QT000003", Status="Rejected", LastModified="2026-09-11T08:00:00+02:00"),
			]
		)
		counts = outcomes.pull_quote_outcomes(client, None)
		self.assertEqual(counts["lost"], 2)
		self.assertEqual(
			frappe.db.get_value("CRM Deal", a, ["status", "lost_reason"]), ("Lost", outcomes.LOST_CANCELLED)
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", b, "lost_reason"), outcomes.LOST_REJECTED)

	def test_an_open_quote_and_an_unknown_quote_change_nothing(self):
		deal = self._deal("QT000004")
		client = self._client(
			[Q(OrderNbr="QT000004", Status="Open"), Q(OrderNbr="QT999999", Status="Completed")]
		)
		counts = outcomes.pull_quote_outcomes(client, None)
		self.assertEqual(counts["won"], 0)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal, "status"), "Proposal/Quotation")

	def test_a_deal_already_closed_by_a_rep_is_left_alone(self):
		"""The rep's word stands: a deal marked Lost in the CRM is not re-opened or
		re-won because Acumatica says Completed."""
		deal = self._deal("QT000005")
		frappe.db.set_value(
			"CRM Deal", deal, {"status": "Lost", "lost_reason": outcomes.LOST_EXPIRED}, update_modified=False
		)
		client = self._client(
			[Q(OrderNbr="QT000005", Status="Completed", LastModified="2026-09-10T08:00:00+02:00")]
		)
		outcomes.pull_quote_outcomes(client, None)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal, "status"), "Lost")

	def test_only_quotes_of_the_configured_type_changed_since_the_mark_are_read(self):
		self._deal("QT000006")
		client = self._client([])
		outcomes.pull_quote_outcomes(client, "2026-09-17 10:00:00")
		kw = client.get_page.call_args.kwargs
		self.assertIn("OrderType eq 'QT'", kw["filter"])
		self.assertIn("LastModified gt datetimeoffset'2026-09-17T10:00:00Z'", kw["filter"])
		self.assertIn("OrderNbr", kw["select"])


class ExpireStaleQuotesTest(OutcomesTestCase):
	"""MBP's quotes are valid for 30 days and Acumatica never expires them: 2,144 sat
	Open regardless of age. The CRM applies the rule, with a grace period so a deal a
	rep is still working is not cut off on day 31."""

	def test_a_quote_past_validity_plus_grace_is_lost_as_expired(self):
		stale = self._deal("QT000010", closes_in=-45, modified_days_ago=40)
		counts = outcomes.expire_stale_quotes(grace_days=30)
		self.assertEqual(counts["expired"], 1)
		self.assertEqual(
			frappe.db.get_value("CRM Deal", stale, ["status", "lost_reason"]), ("Lost", outcomes.LOST_EXPIRED)
		)

	def test_inside_the_grace_period_nothing_happens(self):
		fresh = self._deal("QT000011", closes_in=-10, modified_days_ago=5)
		outcomes.expire_stale_quotes(grace_days=30)
		self.assertEqual(frappe.db.get_value("CRM Deal", fresh, "status"), "Proposal/Quotation")

	def test_a_deal_touched_recently_is_not_expired(self):
		"""Past validity, but a rep edited it last week: somebody is working it."""
		worked = self._deal("QT000012", closes_in=-60, modified_days_ago=3)
		outcomes.expire_stale_quotes(grace_days=30)
		self.assertEqual(frappe.db.get_value("CRM Deal", worked, "status"), "Proposal/Quotation")

	def test_a_deal_without_a_quote_is_never_expired(self):
		"""Only quotes have a validity; a deal a rep created by hand is theirs to close."""
		manual = self._deal("", closes_in=-60, modified_days_ago=40)
		outcomes.expire_stale_quotes(grace_days=30)
		self.assertEqual(frappe.db.get_value("CRM Deal", manual, "status"), "Proposal/Quotation")

	def test_zero_grace_switches_expiry_off(self):
		stale = self._deal("QT000013", closes_in=-400, modified_days_ago=300)
		self.assertEqual(outcomes.expire_stale_quotes(grace_days=0), {"expired": 0})
		self.assertEqual(frappe.db.get_value("CRM Deal", stale, "status"), "Proposal/Quotation")
