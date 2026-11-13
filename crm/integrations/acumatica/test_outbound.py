import json
import re
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from crm.integrations.acumatica import outbound

_commit_patch = patch("crm.integrations.acumatica.outbound._commit")


def setUpModule():
	# The push commits once a customer is linked, so nothing later in the job can roll
	# the link back. Under test that would keep every organization, deal and user the
	# test made; the tests assert on the call instead.
	_commit_patch.start()


def tearDownModule():
	_commit_patch.stop()


def _names(fieldname):
	"""The field names a get_value call asked for, whether it passed one or a list."""
	return fieldname if isinstance(fieldname, list | tuple) else [fieldname]


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
	s.new_customer_class = overrides.get("new_customer_class", "COD")
	s.home_country = "South Africa"
	s.tax_zone_home = overrides.get("tax_zone_home", "01")
	s.tax_zone_abroad = overrides.get("tax_zone_abroad", "02")
	s.salesperson_owners = overrides.get("salesperson_owners")
	s.salesperson_branches = overrides.get("salesperson_branches")
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


def _forget_inflight():
	"""In-flight markers live in redis, which the test's rollback does not reach; and a
	rolled-back naming series hands the next test's deal the same name."""
	frappe.cache().delete_keys(outbound.INFLIGHT_PREFIX)


def _make_deal(status="Won", **kw):
	"""A deal on an organization that has everything a customer push needs.

	length=10 on the name, not the usual 6: the CustomerID-from-name test needs a name
	that still exceeds customer_id_max_length after the dash is stripped."""
	return _complete_deal(status=status, **kw)


def _complete_deal(
	status="Won",
	org_name=None,
	email="buyer@example.com",
	phone=None,
	first_name="Thandi",
	vat=None,
	country="South Africa",
	state="Gauteng",
	with_address=True,
	with_contact=True,
	owner=None,
):
	org_name = org_name or f"Out-{frappe.generate_hash(length=10)}"
	address = None
	if with_address:
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": org_name,
				"address_type": "Billing",
				"address_line1": "12 Industrial Road",
				"address_line2": "Unit 4",
				"city": "Germiston",
				"state": state,
				"pincode": "1401",
				"country": country,
			}
		).insert(ignore_permissions=True)
	org = frappe.get_doc(
		{
			"doctype": "CRM Organization",
			"organization_name": org_name,
			"website": "https://example.com",
			"address": address.name if address else None,
			"tax_registration_id": vat,
		}
	).insert(ignore_permissions=True)
	deal = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": status})
	if owner:
		deal.deal_owner = owner
	if with_contact:
		contact = frappe.get_doc(
			{
				"doctype": "Contact",
				"first_name": first_name,
				"last_name": "Mokoena",
				"designation": "Buyer",
				"company_name": org.name,
			}
		)
		if email:
			contact.append("email_ids", {"email_id": email, "is_primary": 1})
		if phone:
			contact.append("phone_nos", {"phone": phone, "is_primary_phone": 1})
		contact.insert(ignore_permissions=True)
		deal.append("contacts", {"contact": contact.name, "is_primary": 1})
	deal.insert(ignore_permissions=True)
	return org, deal


def _customer_puts(client):
	"""The PUTs that create a customer -- not the follow-up that sets its primary contact."""
	return [c for c in client.put.call_args_list if c.args[0] == "Customer" and "CustomerName" in c.args[1]]


def _pages(customers=(), contacts=(), by_id=None):
	"""A get_page stand-in answering by entity: ``customers`` for every Customer read
	(``by_id`` instead for a read filtered on CustomerID), ``contacts`` for Contact."""

	def get_page(entity, **kw):
		if entity == "Contact":
			return list(contacts)
		if by_id is not None and "CustomerID eq" in (kw.get("filter") or ""):
			return list(by_id)
		return list(customers)

	return get_page


class TestCreateCustomer(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()
		_forget_inflight()

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
	def test_an_organization_with_a_customer_id_but_no_noteid_is_already_linked(self, ClientCls):
		"""The spreadsheet import gives every organization its real CustomerID and no
		NoteID (the exports carry none). Testing NoteID alone would have PUT a
		duplicate customer into the client's live ERP the first time a rep won one
		of the 4,163 imported deals, then overwritten the real id with the duplicate's."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		# Insert open, then move to Won without hooks: inserting at Won runs the
		# push through the on_update hook before the import's identity is set.
		org, deal = _make_deal(status="Qualification")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", "C-PRO004")
		frappe.db.set_value("CRM Deal", deal.name, "status", "Won")

		outbound.push_customer_for_deal(deal.name)

		client.put.assert_not_called()
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "C-PRO004")
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-PRO004")
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_noteid"))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_customer_id_from_name_respects_the_segment_length(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		org, deal = _make_deal(status="Won")  # organization_name is longer than 10 chars
		client = MagicMock()
		ClientCls.return_value = client
		client.get_page.return_value = []  # the derived id is free in Acumatica
		client.put.return_value = _wrapped(NoteID="n", CustomerID="X")
		outbound.push_customer_for_deal(deal.name)
		self.assertLessEqual(len(_customer_puts(client)[0].args[1]["CustomerID"]), 10)


class TestDerivedCustomerIdCollisions(FrappeTestCase):
	"""'From Organization Name' truncates the name to the CUSTOMER ID segment, so two
	different organizations can derive one id -- and Acumatica's Customer PUT is an
	upsert keyed on it, which would rename the first customer and link both
	organizations to it. A taken id must be refused, not sent."""

	def tearDown(self):
		frappe.db.rollback()
		_disable()

	def _issues(self, org_name):
		return [
			row
			for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
			if row.remote_id == org_name and row.kind == "Push Failed"
		]

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_refuses_an_id_another_crm_organization_already_holds(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		client = MagicMock()
		ClientCls.return_value = client
		client.get_page.return_value = []
		org, deal = _make_deal(status="Won")
		derived = re.sub(r"[^A-Z0-9]", "", org.organization_name.upper())[:10]
		rival = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Rival-{frappe.generate_hash(length=8)}"}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", rival.name, "acumatica_id", derived)

		outbound.push_customer_for_deal(deal.name)

		client.put.assert_not_called()
		self.assertTrue(any(rival.name in row.detail for row in self._issues(org.name)))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_refuses_an_id_that_already_exists_in_acumatica(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		client = MagicMock()
		ClientCls.return_value = client
		client.get_page.return_value = [_wrapped(CustomerID="TAKEN")]
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)

		client.put.assert_not_called()
		self.assertTrue(any("already exists in Acumatica" in row.detail for row in self._issues(org.name)))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_failed_collision_check_refuses_rather_than_guessing_the_id_is_free(self, ClientCls):
		from crm.integrations.acumatica.client import AcumaticaError

		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		client = MagicMock()
		ClientCls.return_value = client
		client.get_page.side_effect = AcumaticaError("gateway timeout", status_code=504)
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)

		client.put.assert_not_called()
		self.assertTrue(any("could not check" in row.detail for row in self._issues(org.name)))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_free_id_is_still_pushed(self, ClientCls):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		client = MagicMock()
		ClientCls.return_value = client
		client.get_page.return_value = []
		client.put.return_value = _wrapped(NoteID="g-free", CustomerID="FREE01")
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)

		self.assertEqual(len(_customer_puts(client)), 1)
		self.assertEqual(self._issues(org.name), [])
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "FREE01")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_autonumbering_never_asks_acumatica_for_a_derived_id(self, ClientCls):
		"""Acumatica assigns the id in AutoNumber mode, so there is nothing to collide."""
		_enable(customer_numbering="AutoNumber")
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(NoteID="g-auto", CustomerID="AUTO01")
		org, deal = _make_deal(status="Won")

		client.get_page.side_effect = _pages()
		outbound.push_customer_for_deal(deal.name)

		filters = [c.kwargs.get("filter") or "" for c in client.get_page.call_args_list]
		self.assertFalse([f for f in filters if f.startswith("CustomerID eq")])
		self.assertEqual(client.put.call_args_list[0].args[0], "Customer")

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
			if doctype == "CRM Organization" and "acumatica_noteid" in _names(fieldname):
				calls.append(kwargs.get("for_update"))
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=spy):
			outbound.push_customer_for_deal(deal.name)

		self.assertIn(True, calls, "the pre-PUT re-check of acumatica_noteid must pass for_update=True")
		self.assertEqual(len(_customer_puts(client)), 1)

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
			if (
				doctype == "CRM Organization"
				and "acumatica_noteid" in _names(fieldname)
				and kwargs.get("for_update")
			):
				# the locked re-check reads both identity fields at once
				return frappe._dict(acumatica_noteid="g-won-the-race", acumatica_id="CUST-RACE")
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
		_forget_inflight()

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
	def test_a_push_after_an_unanswered_one_links_the_customer_it_made(self, ClientCls):
		"""AutoNumber: a Customer PUT that timed out may still have created the customer,
		and the next deal save sent another with no CustomerID to collide on -- a second
		customer in the client's ERP."""
		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ReadTimeout("read timed out")
		client.get_page.side_effect = _pages()
		org, deal = _make_deal(status="Won")

		outbound.push_customer_for_deal(deal.name)
		issue = [i for i in frappe.get_doc("CRM Acumatica Settings").sync_issues if i.remote_id == org.name]
		self.assertIn("may have created the customer", issue[-1].detail)

		# it did: the next push finds it by the name it was sent with
		client.get_page.reset_mock()
		client.get_page.side_effect = _pages(customers=[_wrapped(CustomerID="C000777", NoteID="guid-777")])
		client.put.side_effect = None
		client.put.return_value = _wrapped(ContactID=5)
		outbound.push_customer_for_deal(deal.name)

		self.assertEqual([c.args[0] for c in client.put.call_args_list].count("Customer"), 2)
		self.assertNotIn("CustomerName", client.put.call_args_list[-1].args[1])
		self.assertEqual(
			client.get_page.call_args_list[0].kwargs["filter"], f"CustomerName eq '{org.organization_name}'"
		)
		self.assertEqual(
			frappe.db.get_value("CRM Organization", org.name, ["acumatica_id", "acumatica_noteid"]),
			("C000777", "guid-777"),
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_customer"), "C000777")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_push_after_an_unanswered_one_that_made_nothing_sends_it_again(self, ClientCls):
		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ReadTimeout("read timed out")
		client.get_page.side_effect = _pages()
		org, deal = _make_deal(status="Won")
		outbound.push_customer_for_deal(deal.name)

		client.put.side_effect = None
		client.put.return_value = _wrapped(CustomerID="C000778", NoteID="guid-778")
		outbound.push_customer_for_deal(deal.name)

		self.assertEqual(client.put.call_args_list[1].args[0], "Customer")
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C000778")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_refused_push_is_sent_again_without_looking(self, ClientCls):
		"""A 4xx is Acumatica's answer: nothing was created, so there is nothing to find."""
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = AcumaticaError("Acumatica PUT Customer -> 422", status_code=422)
		client.get_page.side_effect = _pages()
		org, deal = _make_deal(status="Won")
		outbound.push_customer_for_deal(deal.name)
		outbound.push_customer_for_deal(deal.name)

		self.assertEqual(client.put.call_count, 2)
		# a refused PUT leaves no marker: each push reads by name once, for the
		# duplicate check, and no unanswered-push lookup ever runs
		by_name = [
			c
			for c in client.get_page.call_args_list
			if (c.kwargs.get("filter") or "").startswith("CustomerName eq")
		]
		self.assertEqual(len(by_name), 2)
		self.assertTrue(all(c.kwargs.get("select") for c in by_name))

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
		_forget_inflight()

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
	def test_a_refused_quote_tells_the_rep_why(self, ClientCls):
		"""The status line says "PUT ... -> 422"; the reason is nested in the body."""
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = AcumaticaError(
			"Acumatica PUT SalesOrder -> 422",
			status_code=422,
			body='{"CustomerID": {"value": "X", "error": "Customer is on credit hold."}}',
		)
		_org, deal = _mapped_deal()

		with self.assertRaises(frappe.ValidationError) as ctx:
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn("Customer is on credit hold.", str(ctx.exception))
		self.assertFalse(frappe.db.get_value("CRM Deal", deal.name, "acumatica_sales_quote"))
		# Acumatica answered: nothing was made, so the next click need not look for it
		self.assertIsNone(frappe.cache().get_value(outbound._inflight_key("SalesOrder", deal.name)))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_timed_out_quote_warns_that_it_may_exist(self, ClientCls):
		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ReadTimeout("read timed out")
		_org, deal = _mapped_deal()

		with self.assertRaises(frappe.ValidationError) as ctx:
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn("may still have been created", str(ctx.exception))

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
	def test_the_quote_is_booked_in_the_owners_branch(self, ClientCls):
		"""A multi-branch tenant books each rep's quotes in their own branch; without the
		branch every quote landed in the API user's default one."""
		rep = _rep()
		_enable(salesperson_owners=f'{{"007": "{rep}"}}', salesperson_branches='{"007": "BR-A"}')
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000130")
		org, deal = _mapped_deal()
		frappe.db.set_value("CRM Deal", deal.name, "deal_owner", rep)

		outbound.create_sales_quote_from_deal(deal.name)

		payload = client.put.call_args.args[1]
		self.assertEqual(payload["FinancialSettings"], {"Branch": {"value": "BR-A"}})

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_an_owner_without_a_branch_leaves_it_to_acumatica(self, ClientCls):
		rep = _rep()
		other = _rep()
		_enable(
			salesperson_owners=f'{{"007": "{rep}", "024": "{other}"}}', salesperson_branches='{"024": "BR-B"}'
		)
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000131")
		org, deal = _mapped_deal()
		frappe.db.set_value("CRM Deal", deal.name, "deal_owner", rep)

		outbound.create_sales_quote_from_deal(deal.name)

		self.assertNotIn("FinancialSettings", client.put.call_args.args[1])

	def test_a_branch_map_that_is_not_an_object_of_ids_is_refused(self):
		for raw in ('["BR-A"]', '{"007": ""}', "{not json"):
			with self.subTest(raw=raw), self.assertRaises(frappe.ValidationError):
				_enable(salesperson_branches=raw)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_rechecks_the_quote_with_a_row_lock_before_the_put(self, ClientCls):
		"""The first read of acumatica_sales_quote is unlocked, so two quick clicks are
		two requests that both pass it before either has an OrderNbr to store -- and
		SalesOrder is a PUT with no key in the body, so the second would create a
		second order in the client's ERP. The re-read right before the PUT must take
		a row lock: that is what makes the loser block until the winner commits."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000125")
		org, deal = _mapped_deal()

		real_get_value = frappe.db.get_value
		locked_reads = []

		def spy(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Deal" and "acumatica_sales_quote" in _names(fieldname):
				locked_reads.append(kwargs.get("for_update"))
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=spy):
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn(True, locked_reads, "the pre-PUT re-check of the quote must pass for_update=True")
		client.put.assert_called_once()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_quote_written_between_the_first_read_and_the_lock_stops_the_second_put(self, ClientCls):
		"""Simulates the double click without threads: the unlocked read sees no quote,
		the locked re-check -- standing in for the first click's commit landing in
		between -- does. The second request must refuse instead of PUTting again."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _mapped_deal()

		real_get_value = frappe.db.get_value

		def racing_winner(doctype, filters=None, fieldname="name", *args, **kwargs):
			if (
				doctype == "CRM Deal"
				and "acumatica_sales_quote" in _names(fieldname)
				and kwargs.get("for_update")
			):
				return "QT000126"
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=racing_winner):
			with self.assertRaises(frappe.ValidationError):
				outbound.create_sales_quote_from_deal(deal.name)

		client.put.assert_not_called()

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
	def test_a_line_with_no_quantity_refuses_the_quote_instead_of_sending_one_unit(self, ClientCls):
		"""Qty is a Float with no minimum, and `row.qty or 1` sent a line the rep had
		zeroed as one unit at the full price -- in a document that goes to a customer."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		_org, deal = _mapped_deal()
		for qty in (0, -2):
			with self.subTest(qty=qty):
				frappe.db.set_value("CRM Products", deal.products[0].name, "qty", qty)
				with self.assertRaises(frappe.ValidationError) as ctx:
					outbound.create_sales_quote_from_deal(deal.name)
				self.assertIn("Widget", str(ctx.exception))
				self.assertIn("quantity", str(ctx.exception))
		client.put.assert_not_called()
		self.assertIsNone(frappe.cache().get_value(outbound._inflight_key("SalesOrder", deal.name)))

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_the_put_gives_up_before_the_proxy_does(self, ClientCls):
		"""At WRITE_TIMEOUT (120s) behind nginx's 120s PROXY_READ_TIMEOUT the proxy
		answered first: the rep got a bare gateway error, never the warning that the
		quote may exist. The token fetch comes out of the same budget."""
		from crm.integrations.acumatica.client import TIMEOUT

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000131")
		_org, deal = _mapped_deal()

		outbound.create_sales_quote_from_deal(deal.name)

		self.assertLess(client.put.call_args.kwargs["timeout"] + TIMEOUT, 120)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_retry_adopts_the_order_an_unanswered_attempt_made(self, ClientCls):
		"""The request that never heard back is rolled back with no OrderNbr stored, so
		the rep's retry -- once the row lock let go -- PUT a second order."""
		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ReadTimeout("read timed out")
		_org, deal = _mapped_deal()
		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)

		# Acumatica finished it after all
		client.get_page.return_value = [_wrapped(OrderNbr="QT000777")]
		self.assertEqual(outbound.create_sales_quote_from_deal(deal.name), "QT000777")

		client.put.assert_called_once()
		self.assertIn(
			f"Description eq 'Vectora deal {deal.name}'", client.get_page.call_args.kwargs["filter"]
		)
		self.assertEqual(frappe.db.get_value("CRM Deal", deal.name, "acumatica_sales_quote"), "QT000777")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_retry_waits_out_acumatica_before_sending_another(self, ClientCls):
		import time

		import requests

		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.side_effect = requests.ReadTimeout("read timed out")
		_org, deal = _mapped_deal()
		with self.assertRaises(frappe.ValidationError):
			outbound.create_sales_quote_from_deal(deal.name)

		# nothing there yet proves nothing: Acumatica may still be writing it
		client.get_page.return_value = []
		with self.assertRaises(frappe.ValidationError) as ctx:
			outbound.create_sales_quote_from_deal(deal.name)
		self.assertIn("Try again in a few minutes", str(ctx.exception))
		client.put.assert_called_once()

		# once it has had time to finish, nothing there means nothing was made
		client.put.side_effect = None
		client.put.return_value = _wrapped(OrderNbr="QT000778")
		later = time.time() + outbound.QUOTE_SETTLE_SECONDS + 1
		with patch.object(outbound.time, "time", return_value=later):
			self.assertEqual(outbound.create_sales_quote_from_deal(deal.name), "QT000778")
		self.assertEqual(client.put.call_count, 2)

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_deal_priced_in_another_currency_than_its_customer_is_refused(self, ClientCls):
		"""Acumatica books a quote in its customer's currency and reads every UnitPrice
		in it: a ZAR-priced deal reached a USD customer as dollars, about 18x the price."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _mapped_deal()
		frappe.db.set_value("CRM Organization", org.name, "currency", "USD")
		frappe.db.set_value("CRM Deal", deal.name, "currency", "ZAR")

		with self.assertRaises(frappe.ValidationError) as ctx:
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn("billed in USD", str(ctx.exception))
		client.put.assert_not_called()

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_the_quote_says_which_currency_its_prices_are_in(self, ClientCls):
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		client.put.return_value = _wrapped(OrderNbr="QT000132")
		org, deal = _mapped_deal()
		frappe.db.set_value("CRM Organization", org.name, "currency", "USD")
		frappe.db.set_value("CRM Deal", deal.name, "currency", "USD")

		outbound.create_sales_quote_from_deal(deal.name)

		self.assertEqual(client.put.call_args[0][1]["CurrencyID"], "USD")

	@patch("crm.integrations.acumatica.outbound.AcumaticaClient")
	def test_a_free_text_line_is_refused_by_name_not_with_a_type_error(self, ClientCls):
		"""A line typed in by name has no product_code: its None went into the list of
		unlinked codes and ", ".join() raised a TypeError -- a generic error toast and
		an Error Log row instead of the refusal that says what to fix."""
		_enable()
		client = MagicMock()
		ClientCls.return_value = client
		org, deal = _mapped_deal()  # one linked product
		deal.append("products", {"product_name": "Custom bracket", "qty": 1, "rate": 5})
		deal.save(ignore_permissions=True)

		with self.assertRaises(frappe.ValidationError) as cm:
			outbound.create_sales_quote_from_deal(deal.name)

		self.assertIn("Custom bracket", str(cm.exception))
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


def _confirm_past(org, deal, past=()):
	facts = outbound._customer_facts(
		frappe.get_doc("CRM Deal", deal.name),
		frappe.get_doc("CRM Organization", org.name),
		frappe.get_cached_doc("CRM Acumatica Settings"),
	)
	frappe.db.set_value(
		"CRM Organization", org.name, "acumatica_confirmed_for", outbound.confirmation_value(facts, past)
	)


def _issues_for(remote_id, kind=None):
	return [
		row
		for row in frappe.get_doc("CRM Acumatica Settings").sync_issues
		if row.remote_id == remote_id and not row.dismissed and (kind is None or row.kind == kind)
	]


def _linked_org(name, customer_id, vat=None):
	"""A customer the sync already brought in."""
	org = frappe.get_doc(
		{"doctype": "CRM Organization", "organization_name": name, "tax_registration_id": vat}
	).insert(ignore_permissions=True)
	frappe.db.set_value("CRM Organization", org.name, "acumatica_id", customer_id)
	return org


def _rep():
	email = f"rep-{frappe.generate_hash(length=6)}@example.com"
	user = frappe.get_doc(
		{"doctype": "User", "email": email, "first_name": "Rep", "send_welcome_email": 0}
	).insert(ignore_permissions=True)
	user.add_roles("Sales User")
	return email


def _notes(user):
	"""The push's notes to ``user`` -- not the assignment note the deal itself sent."""
	return frappe.get_all(
		"CRM Notification",
		filters={"to_user": user, "notification_text": ("like", "%Acumatica%")},
		fields=["notification_text", "reference_name"],
	)


def _pushes(enqueue):
	"""The customer pushes among everything frappe.enqueue was handed."""
	return [
		c for c in enqueue.call_args_list if (c.kwargs.get("job_id") or "").startswith("acumatica_customer_")
	]


class CustomerPushCase(FrappeTestCase):
	def setUp(self):
		patcher = patch("crm.integrations.acumatica.outbound.AcumaticaClient")
		self.ClientCls = patcher.start()
		self.addCleanup(patcher.stop)
		self.client = MagicMock()
		self.ClientCls.return_value = self.client
		self.client.get_page.side_effect = _pages()
		self.client.put.return_value = _wrapped(CustomerID="C-A00411", NoteID="g-411")

	def tearDown(self):
		frappe.db.rollback()
		_disable()
		_forget_inflight()


class TestCustomerPayload(CustomerPushCase):
	def test_a_new_customer_carries_what_mbp_keeps_on_one(self):
		rep, other = _rep(), _rep()
		_enable(salesperson_owners=f'{{"017": "{other}", "003": "{rep}"}}')
		org, deal = _complete_deal(vat="4123456789", phone="+27 11 555 0100", owner=rep)
		frappe.db.set_value("CRM Organization", org.name, "currency", "ZAR")

		outbound.push_customer_for_deal(deal.name)

		payload = _customer_puts(self.client)[0].args[1]
		self.assertEqual(payload["CustomerName"], org.organization_name)
		self.assertEqual(payload["CustomerClass"], "COD")
		self.assertEqual(payload["CurrencyID"], "ZAR")
		self.assertEqual(payload["TaxZone"], "01")
		self.assertEqual(payload["TaxRegistrationID"], "4123456789")
		# the salesperson follows in a PUT of its own: a new customer has no MAIN
		# location yet to hang a Salespersons row on
		self.assertNotIn("Salespersons", payload)
		self.assertIn(
			(
				"Customer",
				{"CustomerID": "C-A00411", "Salespersons": [{"SalespersonID": "003", "Default": True}]},
			),
			[c.args for c in self.client.put.call_args_list],
		)
		main = payload["MainContact"]
		self.assertEqual(main["Email"], {"value": "buyer@example.com"})
		self.assertEqual(main["WebSite"], {"value": "https://example.com"})
		self.assertEqual(
			main["Address"],
			{
				"AddressLine1": {"value": "12 Industrial Road"},
				"AddressLine2": {"value": "Unit 4"},
				"City": {"value": "Germiston"},
				"State": {"value": "GP"},
				"PostalCode": {"value": "1401"},
				"Country": {"value": "ZA"},
			},
		)
		for decided_elsewhere in ("Terms", "CreditLimit", "Status", "StatementCycleID", "CustomerID"):
			self.assertNotIn(decided_elsewhere, payload)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-A00411")

	def test_the_wire_format_wraps_every_level(self):
		from crm.integrations.acumatica.client import wrap

		_enable()
		org, deal = _complete_deal()
		outbound.push_customer_for_deal(deal.name)
		wire = wrap(_customer_puts(self.client)[0].args[1])
		self.assertEqual(wire["CustomerName"], {"value": org.organization_name})
		self.assertEqual(wire["MainContact"]["Address"]["City"], {"value": "Germiston"})

	def test_a_foreign_customer_gets_the_abroad_zone_and_no_unknown_state(self):
		_enable()
		org, deal = _complete_deal(country="Mozambique", state="Maputo Province")
		outbound.push_customer_for_deal(deal.name)
		payload = _customer_puts(self.client)[0].args[1]
		self.assertEqual(payload["TaxZone"], "02")
		self.assertEqual(payload["MainContact"]["Address"]["Country"], {"value": "MZ"})
		self.assertNotIn("State", payload["MainContact"]["Address"])

	def test_blank_tax_zones_leave_it_to_the_class(self):
		_enable(tax_zone_home="", tax_zone_abroad="")
		org, deal = _complete_deal()
		outbound.push_customer_for_deal(deal.name)
		self.assertNotIn("TaxZone", _customer_puts(self.client)[0].args[1])

	def test_no_salesperson_when_two_codes_map_to_the_owner(self):
		rep = _rep()
		_enable(salesperson_owners=f'{{"003": "{rep}", "036": "{rep}"}}')
		org, deal = _complete_deal(owner=rep)
		outbound.push_customer_for_deal(deal.name)
		self.assertFalse([c for c in self.client.put.call_args_list if "Salespersons" in c.args[1]])

	def test_from_organization_name_still_derives_the_id(self):
		_enable(customer_numbering="From Organization Name", customer_id_max_length=10)
		org, deal = _complete_deal(org_name=f"Kappa Pumps {frappe.generate_hash(length=4)}")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_customer_puts(self.client)[0].args[1]["CustomerID"], "KAPPAPUMPS")


class TestCompletenessGate(CustomerPushCase):
	def test_an_organization_without_an_address_is_not_sent(self):
		rep = _rep()
		_enable()
		org, deal = _complete_deal(with_address=False, owner=rep)

		outbound.push_customer_for_deal(deal.name)

		self.ClientCls.assert_not_called()
		issue = _issues_for(org.name, "Push Blocked")
		self.assertEqual(len(issue), 1)
		self.assertIn("an address on the organization", issue[0].detail)
		notes = _notes(rep)
		self.assertEqual(len(notes), 1)
		self.assertEqual(notes[0].reference_name, deal.name)
		self.assertIn("address", notes[0].notification_text)

	def test_each_missing_piece_is_named(self):
		_enable()
		org, deal = _complete_deal(email=None, phone=None)
		address = frappe.db.get_value("CRM Organization", org.name, "address")
		frappe.db.set_value("Address", address, "city", "")
		outbound.push_customer_for_deal(deal.name)
		detail = _issues_for(org.name, "Push Blocked")[0].detail
		self.assertIn("the city", detail)
		self.assertIn("the primary contact's email or phone", detail)
		self.ClientCls.assert_not_called()

	def test_a_deal_without_a_primary_contact_is_not_sent(self):
		_enable()
		org, deal = _complete_deal(with_contact=False)
		outbound.push_customer_for_deal(deal.name)
		self.assertIn("a primary contact on the deal", _issues_for(org.name, "Push Blocked")[0].detail)
		self.ClientCls.assert_not_called()

	def test_a_phone_is_enough_without_an_email(self):
		_enable()
		org, deal = _complete_deal(email=None, phone="+27 11 555 0100")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_issues_for(org.name, "Push Blocked"), [])
		self.assertEqual(len(_customer_puts(self.client)), 1)

	def test_the_same_gap_is_reported_and_notified_once(self):
		rep = _rep()
		_enable()
		org, deal = _complete_deal(with_address=False, owner=rep)
		outbound.push_customer_for_deal(deal.name)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_issues_for(org.name, "Push Blocked")), 1)
		self.assertEqual(len(_notes(rep)), 1)

	def test_settings_refuse_the_switch_without_a_customer_class(self):
		with self.assertRaises(frappe.ValidationError):
			_enable(new_customer_class="  ")


class TestDuplicatePrevention(CustomerPushCase):
	def _blocked(self, org):
		self.assertEqual(_customer_puts(self.client), [])
		issues = _issues_for(org.name, "Possible Duplicate")
		self.assertEqual(len(issues), 1)
		return issues[0]

	def test_same_name_as_a_synced_customer(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Zeta Mining {suffix} (Pty) Ltd", f"C-Z{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Zeta Mining {suffix}")
		outbound.push_customer_for_deal(deal.name)
		issue = self._blocked(org)
		self.assertIn(f"C-Z{suffix}", issue.detail)
		candidates = json.loads(issue.candidates)
		self.assertEqual(candidates[0]["customer_id"], f"C-Z{suffix}")
		self.assertEqual(candidates[0]["reasons"], ["same name"])

	def test_a_similar_name_is_flagged(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"SBS Engineering - Merensky{suffix} (Pty) Ltd", f"C-S{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"SBS Engineerng Merensky{suffix}")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(json.loads(self._blocked(org).candidates)[0]["reasons"], ["similar name"])

	def test_same_vat_number_under_a_different_name(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Totally Other {suffix}", f"C-V{suffix}", vat="4123 456 789")
		_enable()
		org, deal = _complete_deal(org_name=f"Renamed Co {suffix}", vat="4123456789")
		outbound.push_customer_for_deal(deal.name)
		self.assertIn("same VAT number", json.loads(self._blocked(org).candidates)[0]["reasons"])

	def test_same_primary_contact_email_at_a_synced_customer(self):
		suffix = frappe.generate_hash(length=6)
		existing = _linked_org(f"Old Account {suffix}", f"C-E{suffix}")
		person = frappe.get_doc({"doctype": "Contact", "first_name": "Sipho", "company_name": existing.name})
		person.append("email_ids", {"email_id": f"sipho-{suffix}@example.com", "is_primary": 1})
		person.insert(ignore_permissions=True)
		_enable()
		org, deal = _complete_deal(org_name=f"New Account {suffix}", email=f"sipho-{suffix}@example.com")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(json.loads(self._blocked(org).candidates)[0]["reasons"], ["same contact email"])

	def test_a_customer_created_in_acumatica_since_the_last_sync(self):
		_enable()
		org, deal = _complete_deal()
		self.client.get_page.side_effect = _pages(
			customers=[_wrapped(CustomerID="C-A00412", CustomerName=org.organization_name)]
		)
		outbound.push_customer_for_deal(deal.name)
		issue = self._blocked(org)
		self.assertEqual(json.loads(issue.candidates)[0]["customer_id"], "C-A00412")
		self.assertIsNone(json.loads(issue.candidates)[0]["organization"])

	def test_the_remote_check_asks_by_name_and_by_vat(self):
		_enable()
		org, deal = _complete_deal(
			org_name=f"O'Brien Valves {frappe.generate_hash(length=4)}", vat="4999999999"
		)
		outbound.push_customer_for_deal(deal.name)
		filters = [c.kwargs.get("filter") for c in self.client.get_page.call_args_list]
		self.assertIn(f"CustomerName eq '{org.organization_name.replace(chr(39), chr(39) * 2)}'", filters)
		self.assertIn("TaxRegistrationID eq '4999999999'", filters)

	def test_a_remote_check_that_fails_sends_nothing(self):
		from crm.integrations.acumatica.client import AcumaticaError

		_enable()
		org, deal = _complete_deal()
		self.client.get_page.side_effect = AcumaticaError("gateway timeout", status_code=504)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_customer_puts(self.client), [])
		self.assertIn("could not check Acumatica", _issues_for(org.name, "Push Failed")[0].detail)

	def test_the_owner_is_told_a_manager_must_confirm(self):
		rep = _rep()
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Eta Holdings {suffix}", f"C-H{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Eta {suffix}", owner=rep)
		outbound.push_customer_for_deal(deal.name)
		outbound.push_customer_for_deal(deal.name)
		notes = _notes(rep)
		self.assertEqual(len(notes), 1)
		self.assertIn("sales manager", notes[0].notification_text)

	def _confirm(self, org, deal, past=()):
		_confirm_past(org, deal, past)

	def test_a_confirmed_organization_skips_every_duplicate_check(self):
		"""A VAT match too: MBP holds several accounts for one taxpayer (branches)."""
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Theta Pumps {suffix}", f"C-T{suffix}", vat="4777777777")
		_enable()
		org, deal = _complete_deal(org_name=f"Theta Pumps {suffix} Ltd", vat="4777777777")
		self._confirm(org, deal, past=(f"C-T{suffix}", "C-REMOTE"))
		self.client.get_page.side_effect = _pages(
			customers=[_wrapped(CustomerID="C-REMOTE", CustomerName=org.organization_name)]
		)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_customer_puts(self.client)), 1)
		self.assertEqual(_issues_for(org.name, "Possible Duplicate"), [])

	def test_a_candidate_the_manager_never_saw_still_blocks(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Mu Pumps {suffix}", f"C-M{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Mu Pumps {suffix} Ltd")
		self._confirm(org, deal, past=(f"C-M{suffix}",))
		# a customer by the same name keyed in at Acumatica after the confirmation
		self.client.get_page.side_effect = _pages(
			customers=[_wrapped(CustomerID="C-LATER", CustomerName=org.organization_name)]
		)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_customer_puts(self.client), [])
		issue = _issues_for(org.name, "Possible Duplicate")[0]
		self.assertEqual([c["customer_id"] for c in json.loads(issue.candidates)], ["C-LATER"])

	def test_a_confirmation_that_changes_before_the_put_stops_the_run(self):
		"""Decided unlocked, re-checked under the lock: a manager's action in between
		belongs to the job it queued."""
		_enable()
		org, deal = _complete_deal()
		real_get_value = frappe.db.get_value

		def confirmed_meanwhile(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Organization" and kwargs.get("for_update"):
				return frappe._dict(
					acumatica_noteid=None, acumatica_id=None, acumatica_confirmed_for='{"x": 1}'
				)
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch(
			"crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=confirmed_meanwhile
		):
			outbound.push_customer_for_deal(deal.name)
		self.client.put.assert_not_called()

	def test_a_push_another_job_sent_meanwhile_stops_this_one(self):
		"""Both jobs read no marker at the top; the first takes the lock, sends, gets
		no answer and leaves its marker. The second, holding the lock next, must not
		send a second customer."""
		_enable()
		org, deal = _complete_deal()
		real_get_value = frappe.db.get_value

		def first_job_sent(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Organization" and kwargs.get("for_update"):
				key = outbound._inflight_key("Customer", org.name)
				frappe.cache().set_value(
					key,
					{"sent_at": 1.0, "preexisting": [], "name": org.organization_name, "customer_id": None},
				)
				# another worker writes redis only: this process's local cache still holds
				# the None it read at the top, which a cached re-read would return
				frappe.local.cache[frappe.cache().make_key(key)] = None
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=first_job_sent):
			outbound.push_customer_for_deal(deal.name)
		self.client.put.assert_not_called()

	def test_the_remote_reads_run_before_the_row_lock(self):
		_enable()
		org, deal = _complete_deal()
		order = []
		# the Customer reads that decide; the contact follow-up after the PUT reads too
		self.client.get_page.side_effect = (
			lambda entity, **kw: (entity == "Customer" and order.append("read")) or []
		)
		real_get_value = frappe.db.get_value

		def spy(doctype, filters=None, fieldname="name", *args, **kwargs):
			if doctype == "CRM Organization" and kwargs.get("for_update"):
				order.append("lock")
			return real_get_value(doctype, filters, fieldname, *args, **kwargs)

		with patch("crm.integrations.acumatica.outbound.frappe.db.get_value", side_effect=spy):
			outbound.push_customer_for_deal(deal.name)
		self.assertIn("lock", order)
		self.assertNotIn("read", order[order.index("lock") :])

	def test_a_rename_after_the_confirmation_is_checked_again(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Iota Valves {suffix}", f"C-I{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Iota Pumps {suffix}")
		self._confirm(org, deal)
		# what the manager confirmed was "Iota Pumps"; the rep then renames it onto the
		# existing customer
		frappe.db.set_value(
			"CRM Organization", org.name, "organization_name", f"Iota Valves {suffix} (Pty) Ltd"
		)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_customer_puts(self.client), [])
		self.assertEqual(len(_issues_for(org.name, "Possible Duplicate")), 1)

	def test_a_confirmation_written_by_hand_is_not_one(self):
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Kappa Mining {suffix}", f"C-K{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Kappa Mining {suffix} Ltd")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_confirmed_for", "1")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_customer_puts(self.client), [])

	def test_the_remote_vat_check_asks_as_typed_and_as_digits(self):
		_enable()
		org, deal = _complete_deal(vat="4123 456 789")
		outbound.push_customer_for_deal(deal.name)
		filters = [c.kwargs.get("filter") for c in self.client.get_page.call_args_list]
		self.assertIn("TaxRegistrationID eq '4123 456 789'", filters)
		self.assertIn("TaxRegistrationID eq '4123456789'", filters)

	def test_moving_from_blocked_to_duplicate_clears_the_blocked_row(self):
		rep = _rep()
		suffix = frappe.generate_hash(length=6)
		_linked_org(f"Lambda Gears {suffix}", f"C-L{suffix}")
		_enable()
		org, deal = _complete_deal(org_name=f"Lambda Gears {suffix} CC", with_address=False, owner=rep)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_issues_for(org.name, "Push Blocked")), 1)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": org.name,
				"address_type": "Billing",
				"address_line1": "3 Smelter Road",
				"city": "Witbank",
				"country": "South Africa",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", org.name, "address", address.name)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(_issues_for(org.name, "Push Blocked"), [])
		self.assertEqual(len(_issues_for(org.name, "Possible Duplicate")), 1)
		# one note per kind; the duplicate one names no other customer
		notes = _notes(rep)
		self.assertEqual(len(notes), 2)
		self.assertFalse([n for n in notes if f"C-L{suffix}" in n.notification_text])

	def test_the_deal_leaving_the_status_clears_what_waited_on_it(self):
		_enable()
		org, deal = _complete_deal(with_address=False)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_issues_for(org.name, "Push Blocked")), 1)
		doc = frappe.get_doc("CRM Deal", deal.name)
		doc.status = "Qualification"
		doc.save(ignore_permissions=True)
		self.assertEqual(_issues_for(org.name, "Push Blocked"), [])

	def test_a_successful_push_clears_the_issues_that_held_it(self):
		_enable()
		org, deal = _complete_deal(with_address=False)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_issues_for(org.name, "Push Blocked")), 1)
		address = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": org.name,
				"address_type": "Billing",
				"address_line1": "1 Main Reef Road",
				"city": "Springs",
				"country": "South Africa",
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("CRM Organization", org.name, "address", address.name)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_customer_puts(self.client)), 1)
		self.assertEqual(_issues_for(org.name, "Push Blocked"), [])


class TestPrimaryContactFollowUp(CustomerPushCase):
	def _contact_of(self, deal):
		return frappe.get_doc("CRM Deal", deal.name).contacts[0].contact

	def test_the_contact_is_created_under_the_customer_and_made_primary(self):
		_enable()
		org, deal = _complete_deal(phone="+27 11 555 0100")
		self.client.put.side_effect = [
			_wrapped(CustomerID="C-A00411", NoteID="g-411"),
			_wrapped(ContactID=7781, NoteID="g-contact"),
			_wrapped(CustomerID="C-A00411"),
		]
		outbound.push_customer_for_deal(deal.name)

		calls = self.client.put.call_args_list
		self.assertEqual([c.args[0] for c in calls], ["Customer", "Contact", "Customer"])
		self.assertEqual(
			calls[1].args[1],
			{
				"FirstName": "Thandi",
				"LastName": "Mokoena",
				"Email": "buyer@example.com",
				"Phone1": "+27 11 555 0100",
				"JobTitle": "Buyer",
				"BusinessAccount": "C-A00411",
			},
		)
		self.assertEqual(calls[2].args[1], {"CustomerID": "C-A00411", "PrimaryContactID": 7781})
		contact = self._contact_of(deal)
		self.assertEqual(
			frappe.db.get_value("Contact", contact, ["acumatica_id", "acumatica_noteid"]),
			("7781", "g-contact"),
		)

	def test_a_failed_follow_up_keeps_the_customer_and_retries_without_a_second_contact(self):
		import requests

		_enable()
		org, deal = _complete_deal()
		self.client.put.side_effect = [
			_wrapped(CustomerID="C-A00411", NoteID="g-411"),
			requests.ReadTimeout("read timed out"),  # the Contact PUT: did it land?
		]
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-A00411")
		contact = self._contact_of(deal)
		self.assertTrue(_issues_for(contact, "Push Failed"))

		# it did land: the retry finds it under the customer by email, makes no second one
		self.client.put.reset_mock()
		self.client.put.side_effect = [_wrapped(CustomerID="C-A00411")]
		self.client.get_page.side_effect = _pages(contacts=[_wrapped(ContactID=7790, NoteID="g-c")])
		outbound.push_customer_for_deal(deal.name)

		self.assertEqual(
			[c.args for c in self.client.put.call_args_list],
			[("Customer", {"CustomerID": "C-A00411", "PrimaryContactID": 7790})],
		)
		lookup = next(c for c in self.client.get_page.call_args_list if c.args[0] == "Contact")
		self.assertEqual(
			lookup.kwargs["filter"], "BusinessAccount eq 'C-A00411' and Email eq 'buyer@example.com'"
		)
		self.assertEqual(frappe.db.get_value("Contact", contact, "acumatica_id"), "7790")

	def test_a_failed_primary_contact_put_retries_only_that(self):
		_enable()
		from crm.integrations.acumatica.client import AcumaticaError

		org, deal = _complete_deal()
		self.client.put.side_effect = [
			_wrapped(CustomerID="C-A00411", NoteID="g-411"),
			_wrapped(ContactID=7781, NoteID="g-contact"),
			AcumaticaError("refused", status_code=422),
		]
		outbound.push_customer_for_deal(deal.name)
		self.client.put.reset_mock()
		self.client.put.side_effect = [_wrapped(CustomerID="C-A00411")]
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(
			[c.args for c in self.client.put.call_args_list],
			[("Customer", {"CustomerID": "C-A00411", "PrimaryContactID": 7781})],
		)

	def test_an_imported_customer_gets_no_contact_pushed(self):
		"""The follow-up is for a customer this push made, not every linked one."""
		_enable()
		org, deal = _complete_deal(status="Qualification")
		frappe.db.set_value("CRM Organization", org.name, "acumatica_id", "C-PRO004")
		frappe.db.set_value("CRM Deal", deal.name, "status", "Won")
		outbound.push_customer_for_deal(deal.name)
		self.client.put.assert_not_called()


class TestRetryTriggers(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()
		_forget_inflight()

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_saving_an_organization_whose_push_is_waiting_queues_it(self, enqueue):
		_enable()
		org, deal = _complete_deal(with_address=False)
		outbound.push_customer_for_deal(deal.name)  # Push Blocked: no address
		enqueue.reset_mock()
		frappe.get_doc("CRM Organization", org.name).save(ignore_permissions=True)
		pushes = _pushes(enqueue)
		self.assertEqual(len(pushes), 1)
		self.assertEqual(pushes[0].kwargs["deal"], deal.name)
		self.assertEqual(pushes[0].kwargs["job_id"], f"acumatica_customer_{org.name}")
		self.assertTrue(pushes[0].kwargs["enqueue_after_commit"])

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_a_renamed_organization_keeps_its_waiting_push(self, enqueue):
		"""The issue rows name the organization in a Data field, which a rename does not
		follow: the push a rep renamed the organization to unblock was never re-queued,
		and the row for the vanished name stayed open on the manager's panel."""
		from frappe.model.rename_doc import rename_doc

		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import (
			open_sync_issues,
			record_sync_issue,
		)

		_enable()
		org, deal = _complete_deal(with_address=False)
		outbound.push_customer_for_deal(deal.name)  # Push Blocked: no address
		old = org.name
		record_sync_issue("Customer Salesperson", old, outbound.PUSH_FAILED, "salesperson 007 was not set")
		# the importer's rows carry an Acumatica CustomerID in the same column: not ours
		record_sync_issue("Customer", old, "Import Failed", "a customer whose ID reads like the name")

		new = rename_doc(
			"CRM Organization", old, f"{old} Renamed", force=True, ignore_permissions=True, show_alert=False
		)

		self.assertEqual(len(open_sync_issues("Customer", new, outbound.WAITING_KINDS)), 1)
		self.assertEqual(open_sync_issues("Customer", old, outbound.WAITING_KINDS), [])
		self.assertEqual(len(open_sync_issues("Customer Salesperson", new, (outbound.PUSH_FAILED,))), 1)
		self.assertEqual(len(open_sync_issues("Customer", old, ("Import Failed",))), 1)
		self.assertEqual(open_sync_issues("Customer", new, ("Import Failed",)), [])
		# and the cached Single the panel reads shows the row under the new name
		self.assertIn(
			(new, outbound.PUSH_BLOCKED),
			[(row.remote_id, row.kind) for row in outbound.get_settings().sync_issues],
		)

		enqueue.reset_mock()
		frappe.get_doc("CRM Organization", new).save(ignore_permissions=True)
		pushes = _pushes(enqueue)
		self.assertEqual(len(pushes), 1)
		self.assertEqual(pushes[0].kwargs["job_id"], f"acumatica_customer_{new}")

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_editing_an_organization_with_an_old_won_deal_and_nothing_waiting_queues_nothing(self, enqueue):
		"""The edit itself must not be what creates a live customer out of a deal won
		years ago."""
		_enable()
		org, deal = _complete_deal()
		enqueue.reset_mock()
		frappe.get_doc("CRM Organization", org.name).save(ignore_permissions=True)
		self.assertEqual(_pushes(enqueue), [])

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_a_linked_organization_or_one_without_a_won_deal_queues_nothing(self, enqueue):
		_enable()
		org, deal = _complete_deal(status="Qualification")
		enqueue.reset_mock()
		frappe.get_doc("CRM Organization", org.name).save(ignore_permissions=True)
		linked = _linked_org(f"Linked {frappe.generate_hash(length=6)}", "C-LNK1")
		frappe.get_doc("CRM Organization", linked.name).save(ignore_permissions=True)
		self.assertEqual(_pushes(enqueue), [])

	def test_handler_registered_on_organization_update(self):
		self.assertIn(
			"crm.integrations.acumatica.outbound.queue_customer_push_for_organization",
			frappe.get_hooks("doc_events")["CRM Organization"]["on_update"],
		)

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_sweep_queues_unlinked_organizations_with_a_recent_won_deal(self, enqueue):
		_enable()
		org, deal = _complete_deal()
		org2, deal2 = _complete_deal()
		frappe.db.set_value("CRM Deal", deal2.name, "acumatica_customer", "")
		frappe.db.set_value("CRM Organization", org2.name, "acumatica_id", "C-SWEPT")
		enqueue.reset_mock()

		count = outbound.queue_pending_customer_pushes(force=True)

		queued = {c.kwargs["job_id"] for c in _pushes(enqueue)}
		self.assertIn(f"acumatica_customer_{org.name}", queued)
		self.assertNotIn(f"acumatica_customer_{org2.name}", queued)
		self.assertGreaterEqual(count, 1)

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_sweep_leaves_old_deals_alone(self, enqueue):
		_enable()
		org, deal = _complete_deal()
		frappe.db.set_value(
			"CRM Deal",
			deal.name,
			"modified",
			frappe.utils.add_days(frappe.utils.now_datetime(), -45),
			update_modified=False,
		)
		enqueue.reset_mock()
		outbound.queue_pending_customer_pushes(force=True)
		queued = {c.kwargs["job_id"] for c in _pushes(enqueue)}
		self.assertNotIn(f"acumatica_customer_{org.name}", queued)

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_sweep_does_nothing_while_the_push_is_off(self, enqueue):
		_enable(create_customer_on_status_change=0)
		self.assertEqual(outbound.queue_pending_customer_pushes(force=True), 0)
		self.assertEqual(_pushes(enqueue), [])


class TestIdentityIsManagersOnly(FrappeTestCase):
	"""read_only and hidden are the form's; the server enforces permlevel. A rep who
	could write these could point their organization at another customer's code, or
	confirm it as new past the manager."""

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def test_a_sales_user_cannot_set_the_identity_or_the_confirmation(self):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
		rep = _rep()
		frappe.set_user(rep)
		org = frappe.get_doc(
			{"doctype": "CRM Organization", "organization_name": f"Mine-{frappe.generate_hash(length=8)}"}
		).insert()
		doc = frappe.get_doc("CRM Organization", org.name)
		doc.acumatica_id = "C-STOLEN"
		doc.acumatica_noteid = "g-stolen"
		doc.acumatica_confirmed_for = "anything"
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value(
				"CRM Organization", org.name, ["acumatica_id", "acumatica_noteid", "acumatica_confirmed_for"]
			),
			(None, None, None),
		)

	def test_the_fields_are_permlevel_one(self):
		meta = frappe.get_meta("CRM Organization")
		for field in ("acumatica_id", "acumatica_noteid", "acumatica_confirmed_for"):
			self.assertEqual(meta.get_field(field).permlevel, 1, field)
		self.assertEqual(meta.get_field("tax_registration_id").permlevel, 0)


class TestUnansweredPushRecovery(CustomerPushCase):
	"""AutoNumber has only the name to find an unanswered push's customer by, and a
	same-name customer may be somebody else's -- above all after a manager confirmed
	the organization as new beside an existing namesake."""

	def _time_out_first_push(self, org, deal, existing=()):
		import requests

		self.client.get_page.side_effect = _pages(customers=list(existing))
		self.client.put.side_effect = requests.ReadTimeout("read timed out")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(len(_customer_puts(self.client)), 1)
		self.client.put.reset_mock()
		self.client.put.side_effect = None
		self.client.put.return_value = _wrapped(ContactID=5)

	def _confirmed_deal(self):
		"""Confirmed new beside its existing namesake C-OLD1."""
		_enable()
		org, deal = _complete_deal()
		_confirm_past(org, deal, ("C-OLD1",))
		return org, deal

	def test_a_namesake_that_existed_before_the_push_is_never_adopted(self):
		org, deal = self._confirmed_deal()
		namesake = _wrapped(CustomerID="C-OLD1", CustomerName=org.organization_name, NoteID="g-old")
		self._time_out_first_push(org, deal, existing=[namesake])

		# the PUT made nothing: only the old namesake is there, so it is sent again
		self.client.get_page.side_effect = _pages(customers=[namesake])
		self.client.put.return_value = _wrapped(CustomerID="C-NEW1", NoteID="g-new")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-NEW1")
		self.assertEqual(len(_customer_puts(self.client)), 1)

	def test_the_one_new_namesake_is_the_pushs_own(self):
		org, deal = self._confirmed_deal()
		namesake = _wrapped(CustomerID="C-OLD1", CustomerName=org.organization_name)
		self._time_out_first_push(org, deal, existing=[namesake])
		made = _wrapped(CustomerID="C-MADE", CustomerName=org.organization_name, NoteID="g-made")
		self.client.get_page.side_effect = _pages(customers=[namesake, made])
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-MADE")
		self.assertEqual(_customer_puts(self.client), [])
		outbound._commit.assert_called()

	def test_two_new_namesakes_are_not_guessed_between(self):
		org, deal = self._confirmed_deal()
		self._time_out_first_push(org, deal)
		self.client.get_page.side_effect = _pages(
			customers=[
				_wrapped(CustomerID="C-NEWA", CustomerName=org.organization_name),
				_wrapped(CustomerID="C-NEWB", CustomerName=org.organization_name),
			]
		)
		outbound.push_customer_for_deal(deal.name)
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"))
		self.client.put.assert_not_called()
		self.assertIn("more than one new customer", _issues_for(org.name, "Push Failed")[0].detail)

	def test_a_customer_another_organization_holds_is_never_adopted(self):
		org, deal = self._confirmed_deal()
		_confirm_past(org, deal, ("C-OLD1", "C-HELD"))
		self._time_out_first_push(org, deal)
		_linked_org(f"Holder {frappe.generate_hash(length=6)}", "C-HELD")
		self.client.get_page.side_effect = _pages(
			customers=[_wrapped(CustomerID="C-HELD", CustomerName=org.organization_name)]
		)
		self.client.put.return_value = _wrapped(CustomerID="C-NEW2", NoteID="g-n2")
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-NEW2")

	def test_a_rename_after_an_unanswered_push_still_finds_what_it_made(self):
		"""Recovery looks for what was SENT, and the marker follows the rename."""
		from frappe.model.rename_doc import rename_doc

		org, deal = self._confirmed_deal()
		sent = org.organization_name
		self._time_out_first_push(org, deal)
		renamed = rename_doc(
			"CRM Organization",
			org.name,
			f"{sent} Renamed",
			force=True,
			ignore_permissions=True,
			show_alert=False,
		)
		self.assertTrue(frappe.cache().get_value(outbound._inflight_key("Customer", renamed)))
		self.assertFalse(frappe.cache().get_value(outbound._inflight_key("Customer", org.name)))

		made = _wrapped(CustomerID="C-MADE2", CustomerName=sent, NoteID="g-made2")
		self.client.get_page.side_effect = lambda entity, **kw: (
			[made] if kw.get("filter") == f"CustomerName eq '{sent}'" else []
		)
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", renamed, "acumatica_id"), "C-MADE2")
		self.assertEqual(_customer_puts(self.client), [])

	def test_a_marker_without_the_list_adopts_nothing(self):
		_enable()
		org, deal = _complete_deal()
		frappe.cache().set_value(outbound._inflight_key("Customer", org.name), 1700000000.0)
		self.client.get_page.side_effect = _pages(
			customers=[_wrapped(CustomerID="C-WHO", CustomerName=org.organization_name)]
		)
		outbound.push_customer_for_deal(deal.name)
		self.client.put.assert_not_called()
		self.assertFalse(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"))
		self.assertIn("link the right one by hand", _issues_for(org.name, "Push Failed")[0].detail)


class TestFollowUpsAndIssueRows(CustomerPushCase):
	def test_a_refused_salesperson_never_costs_the_customer(self):
		from crm.integrations.acumatica.client import AcumaticaError

		rep = _rep()
		_enable(salesperson_owners=f'{{"003": "{rep}"}}')
		org, deal = _complete_deal(owner=rep)
		self.client.put.side_effect = [
			_wrapped(CustomerID="C-A00411", NoteID="g-411"),
			AcumaticaError("LocationID is required", status_code=422),
			_wrapped(ContactID=7781, NoteID="g-contact"),
			_wrapped(CustomerID="C-A00411"),
		]
		outbound.push_customer_for_deal(deal.name)
		self.assertEqual(frappe.db.get_value("CRM Organization", org.name, "acumatica_id"), "C-A00411")
		issue = _issues_for(org.name, "Push Failed")
		self.assertEqual([i.entity for i in issue], ["Customer Salesperson"])
		self.assertIn("salesperson 003", issue[0].detail)

	def test_the_link_is_committed_before_the_follow_ups(self):
		_enable()
		org, deal = _complete_deal()
		order = []
		outbound._commit.side_effect = lambda: order.append("commit")
		self.client.put.side_effect = lambda entity, payload: (
			order.append(f"put {entity}") or _wrapped(CustomerID="C-A00411", NoteID="g", ContactID=3)
		)
		try:
			outbound.push_customer_for_deal(deal.name)
		finally:
			outbound._commit.side_effect = None
		self.assertEqual(order[:2], ["put Customer", "commit"])
		self.assertIn("put Contact", order[2:])

	def test_the_same_failure_keeps_one_row(self):
		import requests

		_enable()
		org, deal = _complete_deal()
		self.client.put.side_effect = requests.ConnectionError("dns is down")
		for _ in range(3):
			outbound.push_customer_for_deal(deal.name)
			frappe.cache().delete_value(outbound._inflight_key("Customer", org.name))
		self.assertEqual(len(_issues_for(org.name, "Push Failed")), 1)

	def test_recording_an_issue_never_saves_the_settings_document(self):
		from crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings import record_sync_issue

		before = frappe.db.get_single_value("CRM Acumatica Settings", "modified")
		with patch(
			"crm.fcrm.doctype.crm_acumatica_settings.crm_acumatica_settings.CRMAcumaticaSettings.save"
		) as save:
			record_sync_issue("Customer", "ROW-ONLY", "Push Failed", "boom")
			outbound.dismiss_sync_issues("Customer", "ROW-ONLY", ("Push Failed",))
		save.assert_not_called()
		self.assertEqual(frappe.db.get_single_value("CRM Acumatica Settings", "modified"), before)


class TestSweepThrottle(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()
		_disable()
		_forget_inflight()

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_the_pass_runs_once_a_day_however_often_the_sync_does(self, enqueue):
		_enable()
		org, deal = _complete_deal()
		enqueue.reset_mock()
		self.assertGreaterEqual(outbound.queue_pending_customer_pushes(), 1)
		self.assertEqual(outbound.queue_pending_customer_pushes(), 0)

	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_a_waiting_organization_is_skipped_until_something_changes(self, enqueue):
		_enable()
		org, deal = _complete_deal(with_address=False)
		with patch("crm.integrations.acumatica.outbound.AcumaticaClient"):
			outbound.push_customer_for_deal(deal.name)  # Push Blocked
		enqueue.reset_mock()
		outbound.queue_pending_customer_pushes(force=True)
		self.assertNotIn(f"acumatica_customer_{org.name}", {c.kwargs["job_id"] for c in _pushes(enqueue)})

		frappe.db.set_value(
			"CRM Organization",
			org.name,
			"modified",
			frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=5),
			update_modified=False,
		)
		enqueue.reset_mock()
		outbound.queue_pending_customer_pushes(force=True)
		self.assertIn(f"acumatica_customer_{org.name}", {c.kwargs["job_id"] for c in _pushes(enqueue)})

	@patch("crm.integrations.acumatica.outbound.SWEEP_LIMIT", 1)
	@patch("crm.integrations.acumatica.outbound.frappe.enqueue")
	def test_each_run_resumes_past_the_last(self, enqueue):
		_enable()
		a, _a = _complete_deal(org_name=f"Out-aaa{frappe.generate_hash(length=6)}")
		b, _b = _complete_deal(org_name=f"Out-aab{frappe.generate_hash(length=6)}")
		runs = []
		for _ in range(2):
			enqueue.reset_mock()
			outbound.queue_pending_customer_pushes(force=True)
			runs.append({c.kwargs["job_id"] for c in _pushes(enqueue)})
		self.assertEqual([len(r) for r in runs], [1, 1])
		self.assertNotEqual(runs[0], runs[1])


class TestRound3Guards(CustomerPushCase):
	def test_one_deal_leaving_the_status_keeps_the_rows_another_still_waits_on(self):
		_enable()
		org, deal = _complete_deal(with_address=False)
		other = frappe.get_doc({"doctype": "CRM Deal", "organization": org.name, "status": "Won"}).insert(
			ignore_permissions=True
		)
		outbound.push_customer_for_deal(deal.name)
		doc = frappe.get_doc("CRM Deal", deal.name)
		doc.status = "Qualification"
		doc.save(ignore_permissions=True)
		self.assertEqual(len(_issues_for(org.name, "Push Blocked")), 1)
		other = frappe.get_doc("CRM Deal", other.name)
		other.status = "Qualification"
		other.save(ignore_permissions=True)
		self.assertEqual(_issues_for(org.name, "Push Blocked"), [])

	def test_a_sales_user_cannot_set_a_deals_customer_code_or_quote_number(self):
		from crm.integrations.acumatica.install import ensure_custom_fields

		ensure_custom_fields()
		rep = _rep()
		frappe.set_user(rep)
		try:
			org = frappe.get_doc(
				{"doctype": "CRM Organization", "organization_name": f"Rep-{frappe.generate_hash(length=8)}"}
			).insert()
			deal = frappe.get_doc(
				{
					"doctype": "CRM Deal",
					"organization": org.name,
					"status": "Qualification",
					"deal_owner": rep,
				}
			).insert()
			deal.reload()
			deal.acumatica_customer = "C-OTHER"
			deal.acumatica_sales_quote = "QT000123"
			deal.save()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("CRM Deal", deal.name, ["acumatica_customer", "acumatica_sales_quote"]),
			(None, None),
		)
		meta = frappe.get_meta("CRM Deal")
		self.assertEqual(meta.get_field("acumatica_customer").permlevel, 1)
		self.assertEqual(meta.get_field("acumatica_sales_quote").permlevel, 1)

	def test_a_sales_user_reads_the_deals_customer_code(self):
		levels = [
			p.permlevel for p in frappe.get_meta("CRM Deal").permissions if p.role == "Sales User" and p.read
		]
		self.assertIn(1, levels)

	def test_a_sales_user_cannot_set_a_contacts_acumatica_identity(self):
		rep = _rep()
		frappe.set_user(rep)
		try:
			person = frappe.get_doc(
				{"doctype": "Contact", "first_name": "Fake", "acumatica_id": "999"}
			).insert()
			person.reload()
			person.acumatica_noteid = "g-fake"
			person.save()
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Contact", person.name, ["acumatica_id", "acumatica_noteid"]), (None, None)
		)
		# the sync still may
		person = frappe.get_doc("Contact", person.name)
		person.acumatica_id = "123"
		person.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("Contact", person.name, "acumatica_id"), "123")
