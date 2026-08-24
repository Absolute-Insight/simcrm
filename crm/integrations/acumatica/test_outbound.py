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
		frappe.db.set_single_value("CRM Acumatica Settings", "enabled", 0)
		frappe.clear_cache(doctype="CRM Acumatica Settings")

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
