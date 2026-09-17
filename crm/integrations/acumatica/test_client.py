import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, v, wrap


def _resp(status=200, json_body=None):
	m = MagicMock()
	m.status_code = status
	m.json.return_value = json_body if json_body is not None else {}
	m.text = str(json_body)
	return m


def _settings(branch=None):
	s = MagicMock()
	s.instance_url = "https://t.acumatica.com"
	s.endpoint_name = "Default"
	s.endpoint_version = "24.200.001"
	s.client_id = "cid"
	s.username = "api"
	s.request_pause = 0
	s.branch = branch
	s.get_password.return_value = "secret"
	return s


class TestValueHelpers(unittest.TestCase):
	def test_v_unwraps_value(self):
		self.assertEqual(v({"CustomerID": {"value": "ABC"}}, "CustomerID"), "ABC")

	def test_v_missing_returns_default(self):
		self.assertIsNone(v({}, "CustomerID"))
		self.assertEqual(v({"X": {}}, "X", "d"), "d")

	def test_wrap_wraps_leaves_and_lists(self):
		out = wrap({"CustomerName": "Acme", "Details": [{"InventoryID": "W1"}]})
		self.assertEqual(out["CustomerName"], {"value": "Acme"})
		self.assertEqual(out["Details"][0]["InventoryID"], {"value": "W1"})


class TestErrorDetail(unittest.TestCase):
	def test_finds_the_field_error_nested_in_an_echoed_entity(self):
		body = (
			'{"id": "x", "CustomerID": {"value": "ZZZ", "error": "Customer cannot be found."},'
			' "Details": [{"InventoryID": {"value": "V1", "error": "Item is inactive."}}],'
			' "padding": "' + "p" * 2000 + '"}'
		)
		detail = AcumaticaError("PUT -> 422", status_code=422, body=body).detail()
		self.assertIn("CustomerID: Customer cannot be found.", detail)
		self.assertIn("InventoryID: Item is inactive.", detail)

	def test_reads_the_exception_message_of_a_500(self):
		body = '{"message": "An error has occurred.", "exceptionMessage": "Branch is required."}'
		self.assertIn("Branch is required.", AcumaticaError("x", body=body).detail())

	def test_falls_back_to_raw_text_for_a_body_that_is_not_json(self):
		self.assertEqual(
			AcumaticaError("x", body="<html>Bad gateway</html>").detail(), "<html>Bad gateway</html>"
		)
		self.assertEqual(AcumaticaError("x").detail(), "")


class TestClient(FrappeTestCase):
	def setUp(self):
		frappe.cache().delete_value("acumatica_token::https://t.acumatica.com")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_get_page_authenticates_then_fetches(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(200, [{"CustomerID": {"value": "A"}}])
		c = AcumaticaClient(_settings())
		page = c.get_page("Customer", top=5)
		self.assertEqual(v(page[0], "CustomerID"), "A")
		token_url = rpost.call_args[0][0]
		self.assertEqual(token_url, "https://t.acumatica.com/identity/connect/token")
		get_url = rget.call_args[0][0]
		self.assertEqual(get_url, "https://t.acumatica.com/entity/Default/24.200.001/Customer")
		self.assertEqual(rget.call_args.kwargs["params"]["$top"], 5)
		self.assertEqual(rget.call_args.kwargs["params"]["$orderby"], "NoteID")
		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_get_page_orderby_is_overridable(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		AcumaticaClient(_settings()).get_page("SalesOrder", orderby="OrderNbr")
		self.assertEqual(rget.call_args.kwargs["params"]["$orderby"], "OrderNbr")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_null_expires_in_does_not_break_the_token_cache(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": None})
		rget.return_value = _resp(200, [])
		AcumaticaClient(_settings()).get_page("Customer")  # must not raise on int(None)

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_branch_is_sent_on_the_token_request_when_set(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		s = _settings(branch="MAIN")
		AcumaticaClient(s).get_page("Customer")
		self.assertEqual(rpost.call_args.kwargs["data"]["branch"], "MAIN")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_branch_is_not_sent_when_unset(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		s = _settings()
		AcumaticaClient(s).get_page("Customer")
		self.assertNotIn("branch", rpost.call_args.kwargs["data"])

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_branch_rides_on_every_request_as_a_header(self, rget, rpost):
		"""OAuth has no session to hold a branch; Acumatica reads PX-CbApiBranch per call."""
		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		AcumaticaClient(_settings(branch="MAIN")).get_page("Customer")
		self.assertEqual(rget.call_args.kwargs["headers"]["PX-CbApiBranch"], "MAIN")
		AcumaticaClient(_settings()).get_page("Customer")
		self.assertNotIn("PX-CbApiBranch", rget.call_args.kwargs["headers"])

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.put")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_a_write_is_given_longer_than_a_read(self, rget, rput, rpost):
		from crm.integrations.acumatica.client import TIMEOUT, WRITE_TIMEOUT

		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		rput.return_value = _resp(200, {})
		c = AcumaticaClient(_settings())
		c.get_page("Customer")
		c.put("SalesOrder", {"OrderType": "QT"})
		self.assertEqual(rget.call_args.kwargs["timeout"], TIMEOUT)
		self.assertEqual(rput.call_args.kwargs["timeout"], WRITE_TIMEOUT)
		self.assertGreater(WRITE_TIMEOUT, TIMEOUT)

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_get_by_id_fetches_the_record_url_and_treats_404_as_gone(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "t", "expires_in": 3600})
		rget.return_value = _resp(200, {"CustomerID": {"value": "A"}})
		c = AcumaticaClient(_settings())
		self.assertEqual(v(c.get_by_id("Customer", "g-1"), "CustomerID"), "A")
		self.assertEqual(
			rget.call_args[0][0], "https://t.acumatica.com/entity/Default/24.200.001/Customer/g-1"
		)
		rget.return_value = _resp(404, {})
		self.assertIsNone(c.get_by_id("Customer", "g-gone"))
		rget.return_value = _resp(500, {})
		with self.assertRaises(AcumaticaError):
			c.get_by_id("Customer", "g-1")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_401_reauthenticates_once_then_raises(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(401, {})
		c = AcumaticaClient(_settings())
		with self.assertRaises(AcumaticaError):
			c.get_page("Customer")
		self.assertEqual(rpost.call_count, 2)  # initial + one re-auth
		self.assertEqual(rget.call_count, 2)  # initial + one retry

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_iter_all_pages_until_empty_page(self, rget, rpost):
		"""A short page is not the end of the data: licence tiers cap the rows per
		response, so stopping there truncates the backfill."""
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		full = [{"CustomerID": {"value": f"C{i}"}} for i in range(2)]
		rget.side_effect = [_resp(200, full), _resp(200, full[:1]), _resp(200, [])]
		c = AcumaticaClient(_settings())
		got = list(c.iter_all("Customer", page_size=2))
		self.assertEqual(len(got), 3)
		self.assertEqual(rget.call_count, 3)
		self.assertEqual(rget.call_args_list[1].kwargs["params"]["$skip"], 2)
		# the short page moved the cursor by what arrived, not by $top
		self.assertEqual(rget.call_args_list[2].kwargs["params"]["$skip"], 3)

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_ping_fetches_one_customer(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(200, [{"CustomerID": {"value": "A"}}])
		c = AcumaticaClient(_settings())
		out = c.ping()
		self.assertEqual(out, {"ok": True, "sample": "A"})
		self.assertEqual(rget.call_args.kwargs["params"]["$top"], 1)
		self.assertEqual(rget.call_args.kwargs["params"]["$select"], "CustomerID")
		# the credentials check must not hinge on a query option a tenant may refuse
		self.assertNotIn("$orderby", rget.call_args.kwargs["params"])

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_ping_reports_no_sample_on_empty_page(self, rget, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		c = AcumaticaClient(_settings())
		self.assertEqual(c.ping(), {"ok": True, "sample": None})

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.put")
	def test_put_wraps_payload(self, rput, rpost):
		rpost.return_value = _resp(200, {"access_token": "tok", "expires_in": 3600})
		rput.return_value = _resp(200, {"NoteID": {"value": "guid-1"}})
		c = AcumaticaClient(_settings())
		out = c.put("Customer", {"CustomerName": "Acme"})
		self.assertEqual(v(out, "NoteID"), "guid-1")
		sent = rput.call_args.kwargs["json"]
		self.assertEqual(sent["CustomerName"], {"value": "Acme"})
