import json
import re
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import importer, outcomes, quotes
from crm.integrations.acumatica.client import v
from crm.integrations.acumatica.install import ensure_custom_fields
from crm.integrations.acumatica.spreadsheet import OPEN_STATUS

SALESPERSON = "036-NEW"


def SQ(
	nbr, customer, *, status="Open", total=1000, quote_date="2026-10-02", salesperson=SALESPERSON, **extra
):
	"""A SalesOrder as the Default endpoint returns it with $expand=Commissions."""
	rec = {
		"OrderNbr": nbr,
		"OrderType": "QT",
		"Status": status,
		"CustomerID": customer,
		"OrderTotal": total,
		"Date": f"{quote_date}T00:00:00+02:00",
		"CreatedDate": f"{quote_date}T09:15:00+02:00",
		"LastModified": "2026-10-20T10:00:00+02:00",
		**extra,
	}
	out = {k: {"value": val} for k, val in rec.items()}
	if salesperson is not None:
		out["Commissions"] = {"DefaultSalesperson": {"value": salesperson}}
	return out


class NewQuotesTestCase(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_custom_fields()

	def setUp(self):
		super().setUp()
		self.suffix = frappe.generate_hash(length=6).upper()
		self.rep = f"quotes-rep-{self.suffix.lower()}@example.com"
		self._user(self.rep)
		self.customer = f"C-Q{self.suffix}"
		self.org = self._org(self.customer)
		self.base = frappe.db.get_single_value("FCRM Settings", "currency") or "USD"
		self.settings = frappe._dict(
			create_deals_from_quotes=1,
			create_deals_from_quotes_since="2026-09-06",
			salesperson_owners=json.dumps({SALESPERSON: self.rep}),
		)
		self.pending = {}

	def tearDown(self):
		frappe.db.rollback()

	def _user(self, email, role="Sales User", **fields):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Quotes", "send_welcome_email": 0, **fields}
		).insert(ignore_permissions=True)
		if role:
			user.add_roles(role)
		return email

	def _crm_deal(self, organization=None):
		return frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": organization or self.org,
				"status": OPEN_STATUS,
				"deal_value": 70,
				"expected_deal_value": 70,
				"expected_closure_date": date(2026, 12, 1),
			}
		).insert(ignore_permissions=True)

	def _org(self, customer_id):
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Quote Org {customer_id}"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", customer_id)
		return org.name

	def nbr(self, n):
		return f"QN{self.suffix}{n}"

	def quote(self, n, **kw):
		kw.setdefault("CurrencyID", self.base)
		return SQ(self.nbr(n), kw.pop("customer", self.customer), **kw)

	def client(self, rows):
		client = MagicMock()
		client.settings.request_pause = 0
		client.settings.quote_order_type = "QT"

		def get_page(entity, top=100, skip=0, filter=None, **kw):
			self.assertEqual(entity, "SalesOrder")
			match = re.search(r"OrderNbr eq '([^']+)'", filter or "")
			if match:
				return [r for r in rows if v(r, "OrderNbr") == match.group(1)]
			return rows[skip : skip + top]

		client.get_page.side_effect = get_page
		return client

	def pull(self, rows, since=None):
		return quotes.pull_new_quotes(self.client(rows), since, self.pending, self.settings)

	def deal(self, n, fields=("name",)):
		return frappe.db.get_value(
			"CRM Deal", {"acumatica_sales_quote": self.nbr(n)}, list(fields), as_dict=True
		)

	def deals_for(self, n):
		return frappe.db.count("CRM Deal", {"acumatica_sales_quote": self.nbr(n)})

	def issues(self, entity=quotes.QUEUE):
		return [
			(row.remote_id, row.kind)
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.entity == entity and self.suffix in (row.remote_id or "") + (row.detail or "")
		]


class NewQuoteBecomesADealTest(NewQuotesTestCase):
	"""A quote raised in Acumatica after the spreadsheet import never became a deal,
	so won revenue in the CRM stopped at the import."""

	def test_a_won_quote_becomes_a_won_deal_for_its_salesperson_and_customer(self):
		counts = self.pull([self.quote(1, status="Completed", total=12500.5)])

		self.assertEqual(counts["new_deals"], 1)
		deal = self.deal(
			1,
			(
				"status",
				"deal_owner",
				"organization",
				"deal_value",
				"expected_deal_value",
				"closed_date",
				"acumatica_customer",
				"currency",
				"creation",
			),
		)
		self.assertEqual(deal.status, "Won")
		self.assertEqual(deal.deal_owner, self.rep)
		self.assertEqual(deal.organization, self.org)
		self.assertEqual(deal.deal_value, 12500.5)
		self.assertEqual(deal.expected_deal_value, 12500.5)
		# won when Acumatica completed it, as the outcome pass dates a close
		self.assertEqual(deal.closed_date, date(2026, 10, 20))
		self.assertEqual(deal.acumatica_customer, self.customer)
		self.assertEqual(deal.currency, self.base)
		# created when the quote was, not on the night of the sync
		self.assertEqual(str(deal.creation)[:10], "2026-10-02")

	def test_an_open_quote_becomes_an_open_deal_good_for_its_validity(self):
		self.pull([self.quote(2, status="Open")])
		deal = self.deal(2, ("status", "closed_date", "expected_closure_date"))
		self.assertEqual(deal.status, OPEN_STATUS)
		self.assertIsNone(deal.closed_date)
		self.assertEqual(deal.expected_closure_date, date(2026, 10, 2) + timedelta(days=30))

	def test_a_canceled_or_rejected_quote_becomes_a_lost_deal_with_acumaticas_reason(self):
		self.pull([self.quote(3, status="Canceled"), self.quote(4, status="Rejected")])
		canceled = self.deal(3, ("status", "lost_reason"))
		self.assertEqual((canceled.status, canceled.lost_reason), ("Lost", outcomes.LOST_CANCELLED))
		self.assertEqual(self.deal(4, ("lost_reason",)).lost_reason, outcomes.LOST_REJECTED)

	def test_a_quote_a_deal_already_carries_is_left_alone(self):
		existing = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": self.org,
				"status": OPEN_STATUS,
				"deal_value": 50,
				"expected_deal_value": 50,
				"expected_closure_date": date(2026, 12, 1),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Deal", existing.name, "acumatica_sales_quote", self.nbr(5))

		counts = self.pull([self.quote(5, status="Open", total=999)])

		self.assertEqual(counts["new_deals"], 0)
		self.assertEqual(self.deals_for(5), 1)
		self.assertEqual(frappe.db.get_value("CRM Deal", existing.name, "deal_value"), 50)

	def test_a_zero_total_quote_is_skipped(self):
		counts = self.pull([self.quote(6, total=0)])
		self.assertEqual((counts["new_deals"], counts["quotes_skipped"]), (0, 1))
		self.assertEqual(self.deals_for(6), 0)

	def test_a_quote_dated_before_the_floor_is_skipped(self):
		"""A full backfill reads every quote the tenant ever had."""
		counts = self.pull([self.quote(7, quote_date="2026-08-30")])
		self.assertEqual(counts["new_deals"], 0)
		self.assertEqual(self.deals_for(7), 0)

	def test_a_rerun_creates_nothing_new(self):
		rows = [self.quote(8, status="Completed"), self.quote(9)]
		self.assertEqual(self.pull(rows)["new_deals"], 2)
		self.assertEqual(self.pull(rows)["new_deals"], 0)
		self.assertEqual((self.deals_for(8), self.deals_for(9)), (1, 1))

	def test_assignment_is_quiet(self):
		emails = frappe.db.count("Email Queue")
		notifications = frappe.db.count("Notification Log")

		self.pull([self.quote(10, status="Completed")])

		deal = self.deal(10)
		self.assertEqual(frappe.db.count("Email Queue"), emails)
		self.assertEqual(frappe.db.count("Notification Log"), notifications)
		# the ToDo is the assignment
		self.assertTrue(
			frappe.db.exists(
				"ToDo", {"reference_type": "CRM Deal", "reference_name": deal.name, "allocated_to": self.rep}
			)
		)
		self.assertFalse(frappe.flags.bulk_assign_quietly, "the flag is put back")

	def test_an_unmapped_salesperson_hands_the_deal_to_administrator_and_says_so_once(self):
		self.pull([self.quote(11, salesperson="099-XX"), self.quote(12, salesperson="099-XX")])
		self.assertEqual(self.deal(11, ("deal_owner",)).deal_owner, "Administrator")
		self.assertEqual(self.deal(12, ("deal_owner",)).deal_owner, "Administrator")
		rows = [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.entity == "Salesperson" and row.remote_id == "099-XX" and not row.dismissed
		]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].kind, "Mapping Conflict")

	def test_a_quote_with_no_salesperson_goes_to_administrator(self):
		self.pull([self.quote(13, salesperson=None)])
		self.assertEqual(self.deal(13, ("deal_owner",)).deal_owner, "Administrator")

	def test_a_quote_the_crm_made_is_linked_to_its_deal_not_duplicated(self):
		"""Create Sales Quote stores the number once Acumatica answers; a sweep that
		reads the quote before then must not make the same opportunity twice."""
		mine = self._crm_deal()

		counts = self.pull([self.quote(14, Description=f"Vectora deal {mine.name}")])

		self.assertEqual((counts["new_deals"], counts["linked_quotes"]), (0, 1))
		self.assertEqual(frappe.db.get_value("CRM Deal", mine.name, "acumatica_sales_quote"), self.nbr(14))
		self.assertEqual(self.deals_for(14), 1)

	def test_a_copy_of_a_crm_made_quote_becomes_a_deal_of_its_own(self):
		"""A rep copies QT0100 to QT0101 in Acumatica; the copy keeps the Description.
		Swallowed as "ours", its revenue never reached the CRM."""
		mine = self._crm_deal()
		frappe.db.set_value("CRM Deal", mine.name, "acumatica_sales_quote", self.nbr(16))

		counts = self.pull([self.quote(17, status="Completed", Description=f"Vectora deal {mine.name}")])

		self.assertEqual((counts["new_deals"], counts["linked_quotes"]), (1, 0))
		self.assertEqual(frappe.db.get_value("CRM Deal", mine.name, "acumatica_sales_quote"), self.nbr(16))
		self.assertEqual(self.deal(17, ("status",)).status, "Won")

	def test_a_description_naming_another_customers_deal_is_not_adopted(self):
		"""Matched as outbound._earlier_quote matches: Description and customer."""
		other = f"C-OTHER{self.suffix}"
		self._org(other)
		mine = self._crm_deal()

		counts = self.pull([self.quote(18, customer=other, Description=f"Vectora deal {mine.name}")])

		self.assertEqual((counts["new_deals"], counts["linked_quotes"]), (1, 0))
		self.assertFalse(frappe.db.get_value("CRM Deal", mine.name, "acumatica_sales_quote"))
		self.assertEqual(self.deals_for(18), 1)

	def test_a_quote_stored_by_create_sales_quote_mid_pass_is_left_alone(self):
		"""Create Sales Quote commits the number after the pass listed the known ones."""
		mine = self._crm_deal()
		row = self.quote(19, Description=f"Vectora deal {mine.name}", OrderTotal=999)
		client = self.client([row])
		fetch = client.get_page.side_effect

		def late_commit(*args, **kw):
			frappe.db.set_value("CRM Deal", mine.name, "acumatica_sales_quote", self.nbr(19))
			return fetch(*args, **kw)

		client.get_page.side_effect = late_commit
		counts = quotes.pull_new_quotes(client, None, self.pending, self.settings)

		self.assertEqual((counts["new_deals"], counts["linked_quotes"]), (0, 0))
		self.assertEqual(self.deals_for(19), 1)
		self.assertEqual(frappe.db.get_value("CRM Deal", mine.name, "deal_value"), 70)

	def test_a_deal_a_rep_deleted_does_not_come_back(self):
		self.pull([self.quote(15)])
		frappe.delete_doc("CRM Deal", self.deal(15).name, force=True, ignore_permissions=True)

		counts = self.pull([self.quote(15)])

		self.assertEqual(counts["new_deals"], 0)
		self.assertEqual(self.deals_for(15), 0)


class AQuoteThatCannotLandTest(NewQuotesTestCase):
	def test_an_unknown_customer_is_logged_and_the_run_goes_on(self):
		rows = [self.quote(20, customer=f"C-NONE{self.suffix}"), self.quote(21)]

		counts = self.pull(rows)

		self.assertEqual((counts["new_deals"], counts["quote_issues"]), (1, 1))
		self.assertEqual(self.deals_for(21), 1)
		self.assertEqual(self.issues(), [(self.nbr(20), "Import Failed")])
		self.assertEqual(self.pending, {quotes.QUEUE: {self.nbr(20): 1}})

	def test_it_is_fetched_again_by_number_and_lands_once_its_customer_does(self):
		"""The high-water mark moves past it, so the next sweep would never see it."""
		missing = f"C-LATE{self.suffix}"
		rows = [self.quote(22, customer=missing)]
		self.pull(rows)
		self.assertEqual(self.deals_for(22), 0)

		self._org(missing)
		client = self.client(rows)
		counts = quotes.pull_new_quotes(client, "2026-10-21T00:00:00", self.pending, self.settings)

		self.assertEqual(counts["new_deals"], 1)
		self.assertEqual(self.deals_for(22), 1)
		self.assertEqual(self.pending, {})
		filters = [c.kwargs.get("filter") for c in client.get_page.call_args_list]
		self.assertIn(f"OrderNbr eq '{self.nbr(22)}'", filters[0])

	def test_it_is_given_up_on_after_the_cap(self):
		rows = [self.quote(23, customer=f"C-NEVER{self.suffix}")]
		for _ in range(importer.MAX_RETRY_ATTEMPTS):
			self.pull(rows, since="2026-10-21T00:00:00")
		self.assertEqual(self.pending, {})
		self.assertIn((self.nbr(23), "Gave Up"), self.issues())


class OwnerMapTest(NewQuotesTestCase):
	def test_the_mapping_must_be_a_json_object_of_users(self):
		self.assertEqual(quotes.parse_owner_map(""), {})
		self.assertEqual(quotes.parse_owner_map('{" 007-TB ": "a@b.co"}'), {"007-TB": "a@b.co"})
		for bad in ("{", "[1]", '{"007": 5}', '{"007": ""}'):
			with self.assertRaises(ValueError, msg=bad):
				quotes.parse_owner_map(bad)

	def _settings(self, owners=None, **kw):
		return frappe._dict(
			create_deals_from_quotes=1,
			create_deals_from_quotes_since="2026-09-06",
			salesperson_owners=json.dumps(owners if owners is not None else {"007": self.rep}),
			**kw,
		)

	def test_settings_refuse_users_who_cannot_own_deals(self):
		s = self.suffix.lower()
		cannot = [
			"nobody-here@example.com",
			"Administrator",
			"Guest",
			self._user(f"norole-{s}@example.com", role=None),
			self._user(f"website-{s}@example.com", role=None, user_type="Website User"),
			self._user(f"disabled-{s}@example.com", enabled=0),
		]
		for user in cannot:
			with self.assertRaises(frappe.ValidationError, msg=user):
				quotes.validate_settings(self._settings({"007": user}), before=frappe._dict())
		manager = self._user(f"manager-{s}@example.com", role="Sales Manager")
		quotes.validate_settings(self._settings({"007": self.rep, "008": manager}), before=frappe._dict())

	def test_a_user_gone_since_does_not_block_an_unrelated_save_while_off(self):
		owners = json.dumps({"007": "gone-since@example.com"})
		before = frappe._dict(salesperson_owners=owners)
		quotes.validate_settings(frappe._dict(salesperson_owners=owners, request_pause=1), before=before)
		with self.assertRaises(frappe.ValidationError):
			quotes.validate_settings(
				frappe._dict(
					salesperson_owners=owners,
					create_deals_from_quotes=1,
					create_deals_from_quotes_since="2026-09-06",
				),
				before=before,
			)

	def test_the_switch_needs_its_floor(self):
		with self.assertRaises(frappe.ValidationError):
			quotes.validate_settings(frappe._dict(create_deals_from_quotes=1), before=frappe._dict())


class RereadOnEnableTest(NewQuotesTestCase):
	"""The high-water mark is past every quote raised before the switch was turned on,
	so without a re-read the September-October gap would never be read."""

	def setUp(self):
		super().setUp()
		frappe.defaults.clear_default(quotes.REREAD_ALL_NEW_QUOTES)
		self.addCleanup(frappe.defaults.clear_default, quotes.REREAD_ALL_NEW_QUOTES)

	def flagged(self):
		return bool(frappe.db.get_default(quotes.REREAD_ALL_NEW_QUOTES))

	def validate(self, before, **now):
		doc = frappe._dict(self.settings, **now)
		quotes.validate_settings(doc, before=frappe._dict(before))

	def test_turning_it_on_asks_for_a_reread(self):
		self.validate({"create_deals_from_quotes": 0})
		self.assertTrue(self.flagged())

	def test_moving_the_floor_earlier_asks_for_a_reread_and_later_does_not(self):
		on = {"create_deals_from_quotes": 1, "salesperson_owners": self.settings.salesperson_owners}
		self.validate({**on, "create_deals_from_quotes_since": "2026-09-01"})
		self.assertFalse(self.flagged())
		self.validate({**on, "create_deals_from_quotes_since": "2026-10-01"})
		self.assertTrue(self.flagged())

	def test_the_next_pass_reads_every_quote_and_then_clears_it(self):
		frappe.db.set_default(quotes.REREAD_ALL_NEW_QUOTES, 1)
		client = self.client([self.quote(30)])

		quotes.pull_new_quotes(client, "2026-10-21T00:00:00", self.pending, self.settings)

		self.assertNotIn("LastModified", client.get_page.call_args_list[0].kwargs["filter"])
		self.assertEqual(self.deals_for(30), 1)
		self.assertFalse(self.flagged())

	def test_a_pass_that_dies_keeps_it(self):
		frappe.db.set_default(quotes.REREAD_ALL_NEW_QUOTES, 1)
		client = self.client([])
		client.get_page.side_effect = RuntimeError("tenant down")

		with self.assertRaises(RuntimeError):
			quotes.pull_new_quotes(client, "2026-10-21T00:00:00", self.pending, self.settings)

		self.assertTrue(self.flagged())


class TheSweepTest(NewQuotesTestCase):
	"""The switch decides whether the sweep makes deals at all; existing sites keep it off."""

	def setUp(self):
		# not the base setUp: _import_all commits, and would keep its user and organization
		self.settings = frappe._dict(create_deals_from_quotes_since="2026-09-06")

	def tearDown(self):
		super().tearDown()
		# _import_all commits its high-water mark and clears the retry queue
		frappe.db.set_single_value("CRM Acumatica Settings", "pending_retries", "{}")
		frappe.db.set_single_value("CRM Acumatica Settings", "last_synced_at", self.last_synced_at)
		frappe.db.commit()  # nosemgrep: frappe-manual-commit

	def _sweep(self, switch):
		self.last_synced_at = frappe.db.get_single_value("CRM Acumatica Settings", "last_synced_at")
		settings = frappe._dict(self.settings, create_deals_from_quotes=switch, quote_expiry_grace_days=0)
		client = self.client([])
		client.iter_all.side_effect = lambda entity, **kw: iter([])
		with (
			patch.object(importer, "get_settings", return_value=settings),
			patch.object(importer, "AcumaticaClient", return_value=client),
			patch.object(quotes, "pull_new_quotes", return_value={"new_deals": 0}) as pull,
		):
			importer._import_all("2026-10-21T00:00:00")
		return pull

	def test_off_the_sweep_makes_no_deals(self):
		self.assertFalse(self._sweep(0).called)

	def test_on_the_sweep_reads_new_quotes_after_the_entities(self):
		pull = self._sweep(1)
		pull.assert_called_once()
		self.assertEqual(pull.call_args.args[1], "2026-10-21T00:00:00")
