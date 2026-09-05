from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import outbound


def _wrapped(**kw):
	return {k: {"value": v} for k, v in kw.items()}


def _enable(**overrides):
	s = frappe.get_doc("CRM Acumatica Settings")
	s.enabled = 1
	s.instance_url = "https://t.acumatica.com"
	s.create_customer_on_status_change = overrides.get("create_customer_on_status_change", 1)
	s.deal_status = overrides.get("deal_status", "Won")
	s.customer_numbering = overrides.get("customer_numbering", "AutoNumber")
	s.customer_id_max_length = overrides.get("customer_id_max_length", 10)
	s.quote_order_type = "QT"
	s.save(ignore_permissions=True)
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _disable():
	"""Leave the site disabled DURABLY. _enable() saves the Single, whose on_update
	runs ensure_custom_fields(); the first run of that on a fresh site issues DDL,
	which implicitly commits the open transaction -- so `enabled=1` outlives the
	test's rollback and every later CRM Deal test record tries to reach Acumatica."""
	frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
	# Deliberate: the docstring above explains why this write must outlive rollback.
	frappe.db.commit()  # nosemgrep: frappe-manual-commit
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _make_deal(status="Won"):
	# length=10, not the usual 6: the CustomerID-from-name test needs a name that
	# still exceeds customer_id_max_length after the dash is stripped.
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": f"Out-{frappe.generate_hash(length=10)}"}
	).insert(ignore_permissions=True)
	deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": status}).insert(
		ignore_permissions=True
	)
	return org, deal


class TestCreateCustomer(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_noop_when_disabled(self, ClientCls):
		org, deal = _make_deal()
		outbound.push_customer_for_deal(deal.name)
		ClientCls.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_puts_customer_and_stores_ids(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(CustomerID="NEW01", NoteID="g-new")
		org, deal = _make_deal(status="Won")
		outbound.push_customer_for_deal(deal.name)
		entity, payload = client.put.call_args[0]
		self.assertEqual(entity, "Customer")
		self.assertEqual(payload["CustomerName"], org.organization_name)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "NEW01")
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_noteid"), "g-new")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_customer_id_from_name_respects_the_segment_length(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		org, deal = _make_deal(status="Won")  # organization_name is longer than 10 chars
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(NoteID="n", CustomerID="X")
		outbound.push_customer_for_deal(deal.name)
		self.assertLessEqual(len(client.put.call_args.args[1]["CustomerID"]), 10)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_skips_when_org_already_linked(self, ClientCls):
		_enable()
		org, deal = _make_deal(status="Won")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_noteid", "g-existing")
		client = MagicMock()
		ClientCls.return_value = client
		outbound.push_customer_for_deal(deal.name)
		client.put.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_rechecks_the_link_with_a_row_lock_before_the_put(self, ClientCls):
		"""enqueue_after_commit only defers the enqueue_call into frappe.db.after_commit,
		a plain deque with no de-duplication of its own -- two deals on the same
		organization saved in one request both pass the redis dedup check at hook time
		and both land a job at commit, so two workers can be here at once. The unlocked
		read earlier in the function can't see a concurrent winner's in-flight write, so
		the re-check right before the PUT must take a row lock (for_update=True) -- that
		is what makes the loser block until the winner commits instead of racing it."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(CustomerID="NEW01", NoteID="g-new")
		org, deal = _make_deal(status="Won")

		real_get_value = frappe.db.get_value
		calls = []

		def spy(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Organization" and fieldname == "acumatica_noteid":
				calls.append(kwargs.get("for_update"))
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=spy):
			outbound.push_customer_for_deal(deal.name)

		self.assertIn(True, calls, "the pre-PUT re-check of acumatica_noteid must pass for_update=True")
		client.put.assert_called_once()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_link_written_between_the_first_read_and_the_lock_stops_the_second_push(self, ClientCls):
		"""Simulates the race without threads: the doc-level read (the existing
		"already linked" fast path) sees no link yet, but the locked re-check --
		standing in for a concurrent worker's commit that landed in between -- does.
		The second job must find that and no-op rather than PUT a second customer."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _make_deal(status="Won")

		real_get_value = frappe.db.get_value

		def racing_winner(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Organization" and fieldname == "acumatica_noteid" and kwargs.get("for_update"):
				return "g-won-the-race"
			if doctype == "CRM Organization" and fieldname == "acumatica_id":
				return "CUST-RACE"
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=racing_winner):
			outbound.push_customer_for_deal(deal.name)

		client.put.assert_not_called()
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "CUST-RACE")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_failure_lands_in_sync_issues_not_exception(self, ClientCls):
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = AcumaticaError("boom", status_code=422)
		org, deal = _make_deal(status="Won")
		outbound.push_customer_for_deal(deal.name)  # must not raise
		issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertTrue(any(i.kind == "Push Failed" for i in issues))


class TestHook(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_deal_save_enqueues_the_push_instead_of_calling_the_erp(self, enqueue):
		_enable(create_customer_on_status_change=1, deal_status="Won")
		org, deal = _make_deal(status="Won")
		# _make_deal's insert() already ran the real on_update hook once (the
		# integration is enabled and the deal lands on the trigger status) --
		# isolate the explicit call below from that incidental firing.
		enqueue.reset_mock()
		outbound.queue_customer_push(deal, "on_update")
		enqueue.assert_called_once()
		self.assertEqual(
			enqueue.call_args.args[0], "crm.integrations.acumatica.outbound.push_customer_for_deal"
		)
		self.assertTrue(enqueue.call_args.kwargs["enqueue_after_commit"])
		self.assertEqual(enqueue.call_args.kwargs["job_id"], f"acumatica_customer_{org.name}")

	def test_handler_registered_on_deal_update(self):
		self.assertIn(
			"crm.integrations.acumatica.outbound.queue_customer_push",
			frappe.get_hooks("doc_events")["CRM Deal"]["on_update"],
		)


def _mapped_deal(with_products=True, mapped=True):
	"""A deal whose organization is already linked to an Acumatica customer.
	Status stays off the trigger status so the on_update push hook no-ops."""
	suffix = frappe.generate_hash(length=6)
	org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": f"Quote-{suffix}"}).insert(
		ignore_permissions=True
	)
	frappe.db.set_value("CRM Organization", org.name, "acumatica_id", f"CUST{suffix}")
	deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Qualification"})
	if with_products:
		product = frappe.get_doc(
			{"doctype": "CRM Product", "product_code": f"QP-{suffix}", "product_name": "Widget"}
		).insert(ignore_permissions=True)
		if mapped:
			frappe.db.set_value("CRM Product", product.name, "acumatica_id", "WIDGET")
		deal.append(
			"products",
			{
				"product_code": product.name,
				"product_name": product.product_name,
				"qty": 3,
				"rate": 100,
				"discount_percentage": 10,
			},
		)
	deal.insert(ignore_permissions=True)
	return org, deal


class TestTransportFailures(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_connection_error_lands_in_sync_issues_not_the_users_save(self, ClientCls):
		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ConnectionError("dns is down")
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)  # must not raise

		issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertTrue(any(i.kind == "Push Failed" and i.remote_id == org.name for i in issues))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_non_json_response_lands_in_sync_issues(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		# a proxy's HTML error page: resp.json() raises ValueError (JSONDecodeError)
		client.put.side_effect = ValueError("Expecting value: line 1 column 1")
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)  # must not raise

		issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertTrue(any(i.kind == "Push Failed" and i.remote_id == org.name for i in issues))


class TestCreateSalesQuote(FrappeTestCase):
	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()
		_disable()

	def test_rejects_a_user_without_write_permission(self):
		_enable()
		org, deal = _mapped_deal(with_products=False)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			outbound.create_sales_quote_from_deal(deal.name)

	def test_throws_when_the_integration_is_disabled(self):
		org, deal = _mapped_deal(with_products=False)
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")
		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_throws_when_the_organization_is_not_linked(self, ClientCls):
		_enable()
		org, deal = _mapped_deal(with_products=False)
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", "")
		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)
		ClientCls.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_sends_pricing_and_stores_the_order_number(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000123")
		org, deal = _mapped_deal()

		out = outbound.create_sales_quote_from_deal(deal.name)

		self.assertEqual(out, "QT000123")
		entity, payload = client.put.call_args[0]
		self.assertEqual(entity, "SalesOrder")
		self.assertEqual(payload["OrderType"], "QT")
		self.assertEqual(
			payload["CustomerID"], frappe.db.get_value("CRM Organization", org.name, "acumatica_id")
		)
		self.assertEqual(
			payload["Details"],
			[{"InventoryID": "WIDGET", "OrderQty": 3, "UnitPrice": 100, "DiscountPercent": 10}],
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_sales_quote"), "QT000123")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_second_call_refuses_to_create_a_duplicate_quote(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000124")
		org, deal = _mapped_deal()

		outbound.create_sales_quote_from_deal(deal.name)
		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertEqual(client.put.call_count, 1)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_throws_when_no_product_is_mapped_instead_of_sending_an_empty_quote(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _mapped_deal(mapped=False)

		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)

		client.put.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_refuses_when_any_product_is_unlinked_and_names_it(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _mapped_deal()  # one linked product
		unlinked = frappe.get_doc(
			{"doctype": "CRM Product", "product_code": "NO-ACU-1", "product_name": "Unlinked"}
		).insert(ignore_permissions=True)
		deal.append(
			"products",
			{"product_code": unlinked.name, "product_name": unlinked.product_name, "qty": 1, "rate": 5},
		)
		deal.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError) as cm:
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn("NO-ACU-1", str(cm.exception))
		client.put.assert_not_called()
