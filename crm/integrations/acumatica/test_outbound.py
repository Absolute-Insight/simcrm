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
	s.quote_order_type = "QT"
	s.save(ignore_permissions=True)
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _disable():
	"""Leave the site disabled DURABLY. _enable() saves the Single, whose on_update
	runs ensure_custom_fields(); the first run of that on a fresh site issues DDL,
	which implicitly commits the open transaction -- so `enabled=1` outlives the
	test's rollback and every later CRM Deal test record tries to reach Acumatica."""
	frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
	frappe.db.commit()
	frappe.clear_cache(doctype="CRM Acumatica Settings")


def _make_deal(status="Won"):
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": f"Out-{frappe.generate_hash(length=6)}"}
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
		outbound.create_customer_in_acumatica(deal, "on_update")
		ClientCls.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_puts_customer_and_stores_ids(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(CustomerID="NEW01", NoteID="g-new")
		org, deal = _make_deal(status="Won")
		outbound.create_customer_in_acumatica(deal, "on_update")
		entity, payload = client.put.call_args[0]
		self.assertEqual(entity, "Customer")
		self.assertEqual(payload["CustomerName"], org.organization_name)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "NEW01")
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_noteid"), "g-new")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_skips_when_org_already_linked(self, ClientCls):
		_enable()
		org, deal = _make_deal(status="Won")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_noteid", "g-existing")
		client = MagicMock()
		ClientCls.return_value = client
		outbound.create_customer_in_acumatica(deal, "on_update")
		client.put.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_failure_lands_in_sync_issues_not_exception(self, ClientCls):
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = AcumaticaError("boom", status_code=422)
		org, deal = _make_deal(status="Won")
		outbound.create_customer_in_acumatica(deal, "on_update")  # must not raise
		issues = frappe.get_doc("CRM Acumatica Settings").sync_issues
		self.assertTrue(any(i.kind == "Push Failed" for i in issues))


class TestHook(FrappeTestCase):
	def test_handler_registered_on_deal_update(self):
		from crm import hooks

		self.assertIn(
			"crm.integrations.acumatica.outbound.create_customer_in_acumatica",
			hooks.doc_events["CRM Deal"]["on_update"],
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

		outbound.create_customer_in_acumatica(deal, "on_update")  # must not raise

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

		outbound.create_customer_in_acumatica(deal, "on_update")  # must not raise

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
