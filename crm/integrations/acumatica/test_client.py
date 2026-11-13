import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica.client import AcumaticaClient, AcumaticaError, token_cache_key, v, wrap


def _resp(status=200, json_body=None):
	m = MagicMock()
	m.status_code = status
	m.json.return_value = json_body if json_body is not None else {}
	m.text = str(json_body)
	return m


KEY = token_cache_key("https://t.acumatica.com", "cid", "api")


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
		frappe.cache().delete_value(KEY)

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
	def test_logout_ends_the_api_session_and_forgets_the_token(self, rget, rpost):
		"""Every token holds one of the user's concurrent API logins for an hour.
		Test connection minted one per click and never let go; the tenant's limit
		was reached on the first day."""
		rpost.side_effect = [_resp(200, {"access_token": "tok", "expires_in": 3600}), _resp(204)]
		rget.return_value = _resp(200, [])
		c = AcumaticaClient(_settings())
		c.get_page("Customer")
		c.logout()
		self.assertEqual(rpost.call_args[0][0], "https://t.acumatica.com/entity/auth/logout")
		self.assertEqual(rpost.call_args.kwargs["headers"]["Authorization"], "Bearer tok")
		self.assertIsNone(frappe.cache().get_value(KEY))

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_a_new_login_on_the_same_instance_does_not_reuse_the_old_token(self, rget, rpost):
		"""MBP's Sandbox and live companies share one URL; the client ID's @Tenant picks
		the company. Saving the live login must not leave the sync on the Sandbox's token."""
		rpost.return_value = _resp(200, {"access_token": "live", "expires_in": 3600})
		rget.return_value = _resp(200, [])
		frappe.cache().set_value(KEY, "sandbox")
		live = _settings()
		live.client_id = "other@MBP"
		live_key = token_cache_key(live.instance_url, live.client_id, live.username)
		self.addCleanup(frappe.cache().delete_value, live_key)

		AcumaticaClient(live).get_page("Customer")

		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer live")
		self.assertEqual(frappe.cache().get_value(live_key), "live")
		self.assertNotIn("other@MBP", live_key)

	@patch("crm.integrations.acumatica.client.requests.post")
	def test_logout_without_a_session_does_nothing(self, rpost):
		AcumaticaClient(_settings()).logout()
		rpost.assert_not_called()

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_logout_never_raises(self, rget, rpost):
		"""It runs in finally blocks; a logout that fails must not turn a finished
		sync or a successful ping into an error."""
		rpost.side_effect = [_resp(200, {"access_token": "tok", "expires_in": 3600}), RuntimeError("dns")]
		rget.return_value = _resp(200, [])
		c = AcumaticaClient(_settings())
		c.get_page("Customer")
		c.logout()  # must not raise
		self.assertIsNone(frappe.cache().get_value(KEY))

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_a_session_of_its_own_never_touches_the_shared_token(self, rget, rpost):
		"""Test connection runs beside the sync and must neither use nor drop its login."""
		key = KEY
		frappe.cache().set_value(key, "shared")
		self.addCleanup(frappe.cache().delete_value, key)
		rpost.return_value = _resp(200, {"access_token": "own", "expires_in": 3600})
		rget.return_value = _resp(200, [])

		c = AcumaticaClient(_settings(), shared_session=False)
		c.get_page("Customer")
		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer own")
		self.assertEqual(frappe.cache().get_value(key), "shared")

		c.logout()
		self.assertEqual(rpost.call_args.kwargs["headers"]["Authorization"], "Bearer own")
		self.assertEqual(frappe.cache().get_value(key), "shared")

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


class TestSharedLogin(FrappeTestCase):
	"""The API user has three concurrent logins; the workers share one token."""

	def setUp(self):
		frappe.cache().delete_value(KEY)
		self.addCleanup(frappe.cache().delete_value, KEY)

	def test_concurrent_callers_with_an_empty_cache_make_one_login(self):
		"""The sweep logs out as it ends, with the pushes it queued about to start:
		each worker found the cache empty and opened a login of its own."""
		conf = frappe.local.conf
		logins, tokens, errors = [], [], []
		barrier = threading.Barrier(4)

		def slow_login(*args, **kwargs):
			logins.append(1)
			time.sleep(0.3)  # the window the other callers arrive in
			return _resp(200, {"access_token": f"tok{len(logins)}", "expires_in": 3600})

		def caller():
			# what a worker process has of its own: the site's config and an empty local cache
			frappe.local.conf = conf
			frappe.local.cache = {}
			try:
				barrier.wait(5)
				tokens.append(AcumaticaClient(_settings())._token())
			except Exception as e:  # reported by the assertion below, in the test's thread
				errors.append(e)

		with patch("crm.integrations.acumatica.client.requests.post", side_effect=slow_login):
			threads = [threading.Thread(target=caller) for _ in range(4)]
			for t in threads:
				t.start()
			for t in threads:
				t.join(30)

		self.assertEqual(errors, [])
		self.assertEqual(len(logins), 1, f"{len(logins)} API logins opened for 4 concurrent callers")
		self.assertEqual(tokens, ["tok1"] * 4)

	@patch("crm.integrations.acumatica.client.requests.post")
	def test_the_login_lock_is_held_for_the_token_request_and_released_after(self, rpost):
		def lock():
			return frappe.cache().lock(frappe.cache().make_key(f"{KEY}::login"), timeout=5)

		held_during = []

		def login(*args, **kwargs):
			held_during.append(not lock().acquire(blocking=False))
			return _resp(200, {"access_token": "tok", "expires_in": 3600})

		rpost.side_effect = login
		self.assertEqual(AcumaticaClient(_settings())._token(), "tok")
		self.assertEqual(held_during, [True])
		mine = lock()
		self.assertTrue(mine.acquire(blocking=False), "the lock outlived the login")
		mine.release()

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_a_401_uses_the_login_another_worker_has_already_made(self, rget, rpost):
		"""Every worker holding the logged-out token gets a 401 at once. The first logs
		in again; the rest used to drop that fresh token and open a login each."""
		frappe.cache().set_value(KEY, "logged-out")

		def answer(url, headers=None, **kwargs):
			if headers["Authorization"] == "Bearer logged-out":
				# another worker got its 401 first and has logged in again by now
				frappe.cache().set_value(KEY, "fresh")
				return _resp(401, {})
			return _resp(200, [])

		rget.side_effect = answer
		AcumaticaClient(_settings()).get_page("Customer")

		self.assertEqual(rget.call_args.kwargs["headers"]["Authorization"], "Bearer fresh")
		rpost.assert_not_called()
		self.assertEqual(frappe.cache().get_value(KEY, use_local_cache=False), "fresh")

	@patch("crm.integrations.acumatica.client.requests.post")
	@patch("crm.integrations.acumatica.client.requests.get")
	def test_a_refused_token_is_dropped_even_when_the_new_login_fails(self, rget, rpost):
		from crm.integrations.acumatica.client import AcumaticaAuthError

		frappe.cache().set_value(KEY, "stale")
		rget.return_value = _resp(401, {})
		rpost.return_value = _resp(500, {})
		with self.assertRaises(AcumaticaAuthError):
			AcumaticaClient(_settings()).get_page("Customer")
		self.assertIsNone(frappe.cache().get_value(KEY, use_local_cache=False))

	@patch("crm.integrations.acumatica.client.requests.post")
	def test_logout_drops_only_the_token_it_ended(self, rpost):
		"""A logout that raced a new login must not empty the cache under it."""
		frappe.cache().set_value(KEY, "newer")
		c = AcumaticaClient(_settings())
		c._forget_token("ended")
		self.assertEqual(frappe.cache().get_value(KEY, use_local_cache=False), "newer")
		c._forget_token("newer")
		self.assertIsNone(frappe.cache().get_value(KEY, use_local_cache=False))

	def _hold_the_login_lock(self):
		theirs = frappe.cache().lock(frappe.cache().make_key(f"{KEY}::login"), timeout=30)
		self.assertTrue(theirs.acquire(blocking=False))
		self.addCleanup(theirs.release)

	@patch("crm.integrations.acumatica.client.LOGIN_WAIT_IN_JOB", 0.3)
	@patch("crm.integrations.acumatica.client.requests.post")
	def test_a_caller_whose_wait_runs_out_does_not_log_in_beside_the_holder(self, rpost):
		"""The token endpoint is hanging and one worker holds the lock on it. The ones
		whose wait ran out used to log in for themselves -- concurrent logins again,
		against the cap of three -- instead of failing and being retried."""
		from crm.integrations.acumatica.client import AcumaticaAuthError

		self._hold_the_login_lock()
		with self.assertRaises(AcumaticaAuthError) as ctx:
			AcumaticaClient(_settings())._token()
		rpost.assert_not_called()
		self.assertIn("still logging in", ctx.exception.detail())

	@patch("crm.integrations.acumatica.client.LOGIN_WAIT_IN_JOB", 0.3)
	@patch("crm.integrations.acumatica.client.requests.post")
	def test_a_caller_whose_wait_runs_out_still_uses_a_login_that_landed(self, rpost):
		self._hold_the_login_lock()
		c = AcumaticaClient(_settings())
		with patch.object(c, "_cached_token", side_effect=[None, "theirs"]):
			self.assertEqual(c._token(), "theirs")
		rpost.assert_not_called()

	def test_a_request_waits_less_for_a_login_than_a_job(self):
		"""A request is behind a proxy with a deadline; a job is not."""
		from crm.integrations.acumatica import client

		self.assertIsNone(getattr(frappe.local, "request", None))
		self.assertEqual(AcumaticaClient._login_wait(), client.LOGIN_WAIT_IN_JOB)
		frappe.local.request = MagicMock()
		self.addCleanup(delattr, frappe.local, "request")
		self.assertEqual(AcumaticaClient._login_wait(), client.LOGIN_WAIT_IN_REQUEST)

	def test_the_lock_outlasts_the_slowest_login_and_a_request_stays_inside_its_token_budget(self):
		from crm.integrations.acumatica import client

		# requests applies TIMEOUT to the connect and to the read separately
		self.assertGreater(client.LOGIN_LOCK_SECONDS, 2 * client.TIMEOUT)
		# what outbound._quote_write_timeout keeps back for the token: TIMEOUT + 15
		self.assertLessEqual(client.LOGIN_WAIT_IN_REQUEST + client.TIMEOUT, client.TIMEOUT + 15)
