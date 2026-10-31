# Copyright (c) 2023, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

from unittest.mock import MagicMock, patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.fcrm.doctype.crm_call_log.crm_call_log import (
	create_lead_from_call_log,
	get_call_log,
	parse_call_log,
)
from crm.integrations.api import _get_recording_credentials


class TestCRMCallLog(IntegrationTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_call_log_creation_incoming(self):
		"""Test creating an incoming call log"""
		call = create_test_call_log(
			type="Incoming",
			status="Completed",
			caller=None,
			receiver="Administrator",
		)

		self.assertEqual(call.type, "Incoming")
		self.assertEqual(call.status, "Completed")
		self.assertEqual(call.receiver, "Administrator")

	def test_call_log_creation_outgoing(self):
		"""Test creating an outgoing call log"""
		call = create_test_call_log(
			type="Outgoing",
			status="Completed",
			caller="Administrator",
			receiver=None,
		)

		self.assertEqual(call.type, "Outgoing")
		self.assertEqual(call.status, "Completed")
		self.assertEqual(call.caller, "Administrator")

	def test_a_hand_logged_outgoing_call_names_the_session_user_as_caller(self):
		"""The manual quick entry leaves caller/receiver blank; the person logging the
		call is the one who made it, and the planner credits calls by these fields."""
		call = create_test_call_log(type="Outgoing", telephony_medium="Manual", caller=None, receiver=None)
		self.assertEqual(call.caller, frappe.session.user)
		self.assertFalse(call.receiver)

	def test_a_hand_logged_incoming_call_names_the_session_user_as_receiver(self):
		call = create_test_call_log(type="Incoming", telephony_medium="Manual", caller=None, receiver=None)
		self.assertEqual(call.receiver, frappe.session.user)
		self.assertFalse(call.caller)

	def test_a_telephony_log_is_not_attributed_to_whoever_inserted_it(self):
		"""Twilio and Exotel write the log as the integration user; the rep is set
		on caller/receiver by the handler, or not at all."""
		call = create_test_call_log(type="Outgoing", telephony_medium="Twilio", caller=None, receiver=None)
		self.assertFalse(call.caller)
		self.assertFalse(call.receiver)

	def test_call_log_with_duration(self):
		"""Test call log with duration field"""
		call = create_test_call_log(
			type="Incoming",
			status="Completed",
			duration=120,  # 2 minutes
		)

		self.assertEqual(call.duration, 120)

	def test_call_log_with_recording_url(self):
		"""Test call log with recording URL"""
		recording_url = "https://example.com/recording.mp3"
		call = create_test_call_log(
			type="Outgoing",
			status="Completed",
			recording_url=recording_url,
		)

		self.assertEqual(call.recording_url, recording_url)

	def test_external_recording_plays_through_proxy(self):
		call = create_test_call_log(recording_url="https://example.com/recording.wav")

		self.assertEqual(
			call.as_dict()["recording_url_path"],
			f"/api/method/crm.integrations.api.get_recording_url?call_log_name={call.name}",
		)

	def test_uploaded_file_recording_plays_directly(self):
		"""A recording uploaded to the site has no host for the proxy to fetch from."""
		for path in ("/files/4308.mp3", "/private/files/4308.wav"):
			with self.subTest(path=path):
				call = create_test_call_log(recording_url=path)
				self.assertEqual(call.as_dict()["recording_url_path"], path)

	def test_recording_paths_that_are_not_site_files_go_through_the_proxy(self):
		for url in (
			"//example.com/files/recording.mp3",
			"/files/../api/method/logout",
			"/private/files/..%2f..%2fapi",
			"/files/%2E%2E/api/method/logout",
		):
			with self.subTest(url=url):
				call = create_test_call_log(recording_url=url)
				self.assertIn("get_recording_url", call.as_dict()["recording_url_path"])

	def test_has_link_method(self):
		"""Test has_link method to check if document link exists"""
		# Create a lead for linking
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Test Lead",
				"lead_owner": "Administrator",
			}
		).insert()

		call = create_test_call_log()

		# Initially no link should exist
		self.assertFalse(call.has_link("CRM Lead", lead.name))

		# Add link
		call.link_with_reference_doc("CRM Lead", lead.name)

		# Now link should exist
		self.assertTrue(call.has_link("CRM Lead", lead.name))

	def test_link_with_reference_doc(self):
		"""Test linking call log with reference document"""
		# Create a deal for linking
		org = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Test Org for Call Log",
			}
		).insert()

		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org.name,
				"deal_owner": "Administrator",
			}
		).insert()

		call = create_test_call_log()

		# Link with deal
		call.link_with_reference_doc("CRM Deal", deal.name)
		call.save()

		# Verify link was created
		self.assertTrue(call.has_link("CRM Deal", deal.name))
		self.assertEqual(len(call.links), 1)
		self.assertEqual(call.links[0].link_doctype, "CRM Deal")
		self.assertEqual(call.links[0].link_name, deal.name)

	def test_link_with_reference_doc_duplicate_prevention(self):
		"""Test that linking same document twice doesn't create duplicate links"""
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Test Lead",
				"lead_owner": "Administrator",
			}
		).insert()

		call = create_test_call_log()

		# Link twice
		call.link_with_reference_doc("CRM Lead", lead.name)
		call.link_with_reference_doc("CRM Lead", lead.name)
		call.save()

		# Should only have one link
		self.assertEqual(len(call.links), 1)

	def test_default_list_data_returns_actual_logs(self):
		"""Test default_list_data returns actual call log data"""
		from crm.fcrm.doctype.crm_call_log.crm_call_log import CRMCallLog

		# Create test call logs with valid users
		create_test_call_log(
			type="Incoming",
			caller=None,
			receiver="Administrator",
			status="Completed",
		)
		create_test_call_log(
			type="Outgoing",
			caller="Administrator",
			receiver=None,
			status="Failed",
		)

		data = CRMCallLog.default_list_data()

		# Verify structure
		self.assertIn("columns", data)
		self.assertIn("rows", data)
		self.assertIsInstance(data["columns"], list)
		self.assertIsInstance(data["rows"], list)

		# Verify columns contain required fields
		self.assertTrue(len(data["columns"]) > 0)
		column_keys = [col["key"] for col in data["columns"]]
		self.assertIn("caller", column_keys)
		self.assertIn("receiver", column_keys)
		self.assertIn("type", column_keys)
		self.assertIn("status", column_keys)

		# Verify rows contain data fields
		self.assertIn("name", data["rows"])
		self.assertIn("caller", data["rows"])
		self.assertIn("receiver", data["rows"])
		self.assertIn("type", data["rows"])
		self.assertIn("status", data["rows"])

	def test_parse_call_log_incoming(self):
		"""Test parse_call_log function with incoming call"""
		# Create a user for testing
		if not frappe.db.exists("User", "test@example.com"):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": "test@example.com",
					"first_name": "Test",
				}
			).insert()

		call_data = {
			"type": "Incoming",
			"from": "+1234567890",
			"to": "+0987654321",
			"receiver": "test@example.com",
			"duration": 120,
		}

		parsed = parse_call_log(call_data)

		# Verify parsed data with actual values
		self.assertEqual(parsed["activity_type"], "incoming_call")
		self.assertEqual(parsed["_duration"], "2m")
		# _caller and _receiver are dicts with label and image
		self.assertIsInstance(parsed["_caller"], dict)
		self.assertIn("label", parsed["_caller"])
		self.assertEqual(parsed["_caller"]["label"], "Unknown")  # Phone number resolves to Unknown
		self.assertIsInstance(parsed["_receiver"], dict)
		self.assertIn("label", parsed["_receiver"])
		self.assertEqual(parsed["from"], "+1234567890")
		self.assertEqual(parsed["to"], "+0987654321")

	def test_parse_call_log_outgoing(self):
		"""Test parse_call_log function with outgoing call"""
		call_data = {
			"type": "Outgoing",
			"from": "+1234567890",
			"to": "+0987654321",
			"caller": "Administrator",
			"duration": 180,
		}

		parsed = parse_call_log(call_data)

		# Verify parsed data with actual values
		self.assertEqual(parsed["activity_type"], "outgoing_call")
		self.assertEqual(parsed["_duration"], "3m")
		# _caller and _receiver are dicts with label and image
		self.assertIsInstance(parsed["_caller"], dict)
		self.assertEqual(parsed["_caller"]["label"], "Administrator")
		self.assertIsInstance(parsed["_receiver"], dict)
		self.assertEqual(parsed["_receiver"]["label"], "Unknown")  # Phone number resolves to Unknown
		self.assertEqual(parsed["from"], "+1234567890")
		self.assertEqual(parsed["to"], "+0987654321")

	def test_get_call_log_api(self):
		"""Test get_call_log API function"""
		call = create_test_call_log(
			type="Outgoing",
			status="Completed",
			duration=60,
		)

		# Call the API
		result = get_call_log(call.name)

		# Verify result
		self.assertEqual(result["name"], call.name)
		self.assertEqual(result["type"], "Outgoing")
		self.assertEqual(result["status"], "Completed")
		self.assertIn("_duration", result)
		self.assertIn("_tasks", result)
		self.assertIn("_notes", result)

	def test_get_call_log_with_reference_lead(self):
		"""Test get_call_log API with reference to CRM Lead"""
		lead = frappe.get_doc(
			{
				"doctype": "CRM Lead",
				"first_name": "Test Lead",
				"lead_owner": "Administrator",
			}
		).insert()

		call = create_test_call_log(
			reference_doctype="CRM Lead",
			reference_docname=lead.name,
		)

		result = get_call_log(call.name)

		# Verify lead reference
		self.assertEqual(result.get("_lead"), lead.name)

	def test_get_call_log_with_reference_deal(self):
		"""Test get_call_log API with reference to CRM Deal"""
		org = frappe.get_doc(
			{
				"doctype": "CRM Organization",
				"organization_name": "Test Org for Call",
			}
		).insert()

		deal = frappe.get_doc(
			{
				"doctype": "CRM Deal",
				"organization": org.name,
				"deal_owner": "Administrator",
			}
		).insert()

		call = create_test_call_log(
			reference_doctype="CRM Deal",
			reference_docname=deal.name,
		)

		result = get_call_log(call.name)

		# Verify deal reference
		self.assertEqual(result.get("_deal"), deal.name)

	def test_call_log_shows_referenced_lead_when_number_is_shared(self):
		referenced = create_test_lead("Referenced Lead", "+919876500001")
		other = create_test_lead("Other Lead", "+919876500001")
		other.db_set("modified", frappe.utils.add_days(frappe.utils.now(), 1))

		call = create_test_call_log(
			type="Outgoing",
			caller="Administrator",
			to="+919876500001",
			reference_doctype="CRM Lead",
			reference_docname=referenced.name,
		)

		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Referenced Lead")

	def test_call_log_without_reference_falls_back_to_number(self):
		create_test_lead("Number Lead", "+919876500002")

		call = create_test_call_log(type="Outgoing", caller="Administrator", to="+919876500002")

		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Number Lead")

	def test_call_log_hides_referenced_lead_name_user_cannot_read(self):
		referenced = create_test_lead("Referenced Lead", "+919876500004")
		create_test_lead("Other Lead", "+919876500004")
		sales_user = create_sales_user()
		call = create_test_call_log(
			type="Outgoing",
			caller=sales_user,
			to="+919876500004",
			reference_doctype="CRM Lead",
			reference_docname=referenced.name,
		)

		frappe.set_user(sales_user)
		try:
			result = get_call_log(call.name)
		finally:
			frappe.set_user("Administrator")

		self.assertEqual(result["_receiver"]["label"], "Unknown")

	def test_call_log_with_a_dangling_reference_degrades_to_unknown(self):
		referenced = create_test_lead("Gone Lead", "+919876500006")
		# Shares the number: a fallback to the phone lookup would name this one.
		create_test_lead("Other Lead", "+919876500006")
		call = create_test_call_log(
			type="Outgoing",
			caller="Administrator",
			to="+919876500006",
			reference_doctype="CRM Lead",
			reference_docname=referenced.name,
		)
		frappe.delete_doc("CRM Lead", referenced.name, force=True, ignore_permissions=True)

		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Unknown")

	def test_call_log_names_deal_without_contacts_from_the_deal(self):
		org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Referenced Org"}).insert()
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "organization": org.name, "deal_owner": "Administrator"}
		).insert()
		create_test_lead("Other Lead", "+919876500005")
		call = create_test_call_log(
			type="Outgoing",
			caller="Administrator",
			to="+919876500005",
			reference_doctype="CRM Deal",
			reference_docname=deal.name,
		)

		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Referenced Org")

	def test_call_log_names_deal_from_typed_organization_name(self):
		deal = frappe.get_doc({"doctype": "CRM Deal", "deal_owner": "Administrator"}).insert()
		deal.db_set("organization_name", "Typed Org")
		call = create_test_call_log(reference_doctype="CRM Deal", reference_docname=deal.name)

		self.assertEqual(get_call_log(call.name)["_caller"]["label"], "Typed Org")

	def test_get_call_log_prefers_reference_over_linked_lead(self):
		referenced = create_test_lead("Referenced Lead", "+919876500003")
		other = create_test_lead("Other Lead", "+919876500003")

		call = create_test_call_log(reference_doctype="CRM Lead", reference_docname=referenced.name)
		call.link_with_reference_doc("CRM Lead", other.name)
		call.save()

		self.assertEqual(get_call_log(call.name)["_lead"], referenced.name)

	def test_get_call_log_with_linked_task(self):
		"""Test get_call_log API with linked CRM Task"""
		call = create_test_call_log()

		# Create and link a task
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Follow up call",
				"assigned_to": "Administrator",
			}
		).insert()

		call.link_with_reference_doc("CRM Task", task.name)
		call.save()

		result = get_call_log(call.name)

		# Verify task is in results
		self.assertEqual(len(result["_tasks"]), 1)
		self.assertEqual(result["_tasks"][0]["name"], task.name)

	def test_create_lead_from_call_log_basic(self):
		"""Test creating a lead from call log"""
		call = create_test_call_log(
			type="Incoming",
			from_number="+1234567890",
		)

		# Create lead from call log
		lead_name = create_lead_from_call_log(
			call_log=frappe.as_json({"name": call.name}),
			lead_details=frappe.as_json({"first_name": "John", "last_name": "Doe"}),
		)

		# Verify lead was created
		self.assertTrue(frappe.db.exists("CRM Lead", lead_name))
		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertEqual(lead.first_name, "John")
		self.assertEqual(lead.last_name, "Doe")
		self.assertEqual(lead.mobile_no, "+1234567890")

		# Verify call log was linked
		call.reload()
		self.assertTrue(call.has_link("CRM Lead", lead_name))

	def test_create_lead_from_call_log_with_owner(self):
		"""Test creating lead from call log with specific owner"""
		call = create_test_call_log(
			type="Outgoing",
			to="+9876543210",
		)

		lead_name = create_lead_from_call_log(
			call_log=frappe.as_json({"name": call.name}),
			lead_details=frappe.as_json({"first_name": "Jane", "lead_owner": "Administrator"}),
		)

		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertEqual(lead.lead_owner, "Administrator")

	def test_create_lead_from_call_log_no_details(self):
		"""Test creating lead from call log without lead details"""
		call = create_test_call_log(
			type="Incoming",
			from_number="+1112223333",
		)

		lead_name = create_lead_from_call_log(call_log=frappe.as_json({"name": call.name}))

		# Verify lead was created with default name
		lead = frappe.get_doc("CRM Lead", lead_name)
		self.assertTrue(lead.first_name.startswith("Lead from call"))
		self.assertEqual(lead.mobile_no, "+1112223333")

	def test_create_lead_from_an_outgoing_call_takes_the_number_dialled(self):
		"""On an outgoing call ``from`` is the rep's own line and the customer is ``to``,
		the same way round parse_call_log reads it."""
		call = create_test_call_log(type="Outgoing", from_number="+27115550100", to="+27821234567")

		lead = frappe.get_doc(
			"CRM Lead", create_lead_from_call_log(call_log=frappe.as_json({"name": call.name}))
		)

		self.assertEqual(lead.mobile_no, "+27821234567")
		self.assertEqual(lead.first_name, "Lead from call +27821234567")

	def test_create_lead_from_call_log_twice_returns_the_existing_lead(self):
		"""A second click must return the lead the call already has, not create another."""
		call = create_test_call_log(type="Incoming", from_number="+1231231234")

		first = create_lead_from_call_log(call_log=frappe.as_json({"name": call.name}))
		second = create_lead_from_call_log(
			call_log=frappe.as_json({"name": call.name}),
			lead_details=frappe.as_json({"first_name": "Duplicate"}),
		)

		self.assertEqual(first, second)
		self.assertEqual(frappe.db.count("CRM Lead", {"mobile_no": "+1231231234"}), 1)
		call.reload()
		self.assertEqual(len([link for link in call.links if link.link_doctype == "CRM Lead"]), 1)

	def test_create_lead_from_call_log_returns_the_reference_lead(self):
		"""A call already filed under a lead by reference does not get a second lead."""
		lead = frappe.get_doc({"doctype": "CRM Lead", "first_name": "Referenced"}).insert()
		call = create_test_call_log(reference_doctype="CRM Lead", reference_docname=lead.name)

		self.assertEqual(create_lead_from_call_log(call_log=frappe.as_json({"name": call.name})), lead.name)

	def test_create_lead_from_call_log_invalid_call_log(self):
		"""Test that invalid call log throws error"""
		with self.assertRaises(frappe.DoesNotExistError):
			create_lead_from_call_log(call_log=frappe.as_json({"name": "invalid_name"}))

	def test_create_lead_from_call_log_permission_check(self):
		"""Test that permission is checked when creating lead from call log"""
		create_test_call_log()

		# Verify that empty call log throws error
		with self.assertRaises(frappe.ValidationError):
			create_lead_from_call_log(call_log=frappe.as_json({}))

	def test_call_log_status_filtering(self):
		"""Test that call logs can be filtered by status"""
		# Create calls with different statuses
		completed_call = create_test_call_log(status="Completed", type="Incoming")
		failed_call = create_test_call_log(status="Failed", type="Outgoing")
		busy_call = create_test_call_log(status="Busy", type="Incoming")

		# Verify statuses are set correctly
		self.assertEqual(completed_call.status, "Completed")
		self.assertEqual(failed_call.status, "Failed")
		self.assertEqual(busy_call.status, "Busy")

		# Test filtering by status
		completed_logs = frappe.get_all("CRM Call Log", filters={"status": "Completed"})
		failed_logs = frappe.get_all("CRM Call Log", filters={"status": "Failed"})

		self.assertGreaterEqual(len(completed_logs), 1)
		self.assertGreaterEqual(len(failed_logs), 1)

		# Verify our specific calls are in the right filtered lists
		completed_names = [log.name for log in completed_logs]
		failed_names = [log.name for log in failed_logs]

		self.assertIn(completed_call.name, completed_names)
		self.assertIn(failed_call.name, failed_names)
		self.assertNotIn(busy_call.name, completed_names)
		self.assertNotIn(busy_call.name, failed_names)

	def test_call_log_with_telephony_medium(self):
		"""Test call log with different telephony mediums"""
		call = create_test_call_log(telephony_medium="Twilio")
		self.assertEqual(call.telephony_medium, "Twilio")

		call2 = create_test_call_log(telephony_medium="Exotel")
		self.assertEqual(call2.telephony_medium, "Exotel")

	def test_recording_credentials_manual_medium_needs_no_auth(self):
		"""A manually added recording is fetched as-is, with no provider auth."""
		self.assertIsNone(_get_recording_credentials("Manual"))

	def test_recording_credentials_unknown_medium_returns_none(self):
		"""An empty/unrecognized medium must not raise; it just skips auth."""
		self.assertIsNone(_get_recording_credentials(""))
		self.assertIsNone(_get_recording_credentials(None))

	def test_recording_credentials_twilio_unconfigured_returns_none(self):
		"""Twilio without a configured secret falls back to no auth instead of raising.

		Regression: get_password used to raise when the secret was unset, which made
		the recording proxy 500 and the UI show "Recording not available".
		"""
		settings = MagicMock()
		settings.api_key = "ACxxxxxxxx"
		settings.get_password.return_value = None
		with patch("crm.integrations.api.frappe.get_single", return_value=settings):
			self.assertIsNone(_get_recording_credentials("Twilio"))

	def test_recording_credentials_twilio_configured_returns_tuple(self):
		"""Twilio with both key and secret set yields the auth pair."""
		settings = MagicMock()
		settings.api_key = "ACxxxxxxxx"
		settings.get_password.return_value = "twilio_secret"
		with patch("crm.integrations.api.frappe.get_single", return_value=settings):
			self.assertEqual(_get_recording_credentials("Twilio"), ("ACxxxxxxxx", "twilio_secret"))

	def test_recording_credentials_exotel_configured_returns_tuple(self):
		"""Exotel with both key and token set yields the auth pair."""
		settings = MagicMock()
		settings.api_key = "exotel_key"
		settings.get_password.return_value = "exotel_token"
		with patch("crm.integrations.api.frappe.get_single", return_value=settings):
			self.assertEqual(_get_recording_credentials("Exotel"), ("exotel_key", "exotel_token"))


def create_sales_user():
	if not frappe.db.exists("User", "sales-user@example.com"):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": "sales-user@example.com",
				"first_name": "Sales",
				"roles": [{"role": "Sales User"}],
			}
		).insert(ignore_permissions=True)
	return "sales-user@example.com"


def create_test_lead(first_name, mobile_no):
	return frappe.get_doc(
		{
			"doctype": "CRM Lead",
			"first_name": first_name,
			"mobile_no": mobile_no,
			"lead_owner": "Administrator",
		}
	).insert()


HIDDEN_REP = "calllog-rep@crmtest.test"
HIDDEN_OWNER = "calllog-owner@crmtest.test"


class TestCallLogHidesUnreadableReferences(IntegrationTestCase):
	"""The caller or receiver of a call can read it even when the lead or deal it
	hangs off belongs to someone else (crm.permissions.linked_records). The call
	must not name that record on any read path, nor offer to create a lead over it."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		for email, name in ((HIDDEN_REP, "Calllog Rep"), (HIDDEN_OWNER, "Calllog Owner")):
			if not frappe.db.exists("User", email):
				frappe.get_doc(
					{"doctype": "User", "email": email, "first_name": name, "send_welcome_email": 0}
				).insert(ignore_permissions=True).add_roles("Sales User")

		self.lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Hidden", "lead_owner": HIDDEN_OWNER}
		).insert(ignore_permissions=True)
		deal = frappe.get_doc(
			{"doctype": "CRM Deal", "deal_owner": HIDDEN_OWNER, "organization": "Hidden Org"}
		)
		deal.flags.ignore_mandatory = True
		deal.flags.ignore_links = True
		self.deal = deal.insert(ignore_permissions=True)

		self.call = create_test_call_log(
			type="Outgoing",
			telephony_medium="Twilio",
			caller=HIDDEN_REP,
			reference_doctype="CRM Lead",
			reference_docname=self.lead.name,
		)
		self.call.link_with_reference_doc("CRM Deal", self.deal.name)
		self.call.save(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.db.rollback()

	def assertNamesNothingHidden(self, payload):
		serialized = frappe.as_json(payload)
		self.assertNotIn(self.lead.name, serialized)
		self.assertNotIn(self.deal.name, serialized)

	def test_get_call_log_does_not_name_a_hidden_lead_or_deal(self):
		frappe.set_user(HIDDEN_REP)
		result = get_call_log(self.call.name)

		self.assertNotIn("_lead", result)
		self.assertNotIn("_deal", result)
		self.assertFalse(result.get("reference_docname"))
		self.assertFalse(
			[link for link in result["links"] if link["link_doctype"] in ("CRM Lead", "CRM Deal")]
		)
		self.assertEqual(result.get("_has_hidden_reference"), 1)
		self.assertNamesNothingHidden(result)

	def test_frappe_client_get_does_not_name_a_hidden_lead_or_deal(self):
		frappe.set_user(HIDDEN_REP)
		result = frappe.client.get("CRM Call Log", self.call.name)

		self.assertFalse(result.get("reference_docname"))
		self.assertEqual(result.get("_has_hidden_reference"), 1)
		self.assertNamesNothingHidden(result)

	def test_the_resource_api_does_not_name_a_hidden_lead_or_deal(self):
		from frappe.api import v1, v2

		frappe.set_user(HIDDEN_REP)
		frappe.local.form_dict = frappe._dict()
		self.assertNamesNothingHidden(v1.read_doc("CRM Call Log", self.call.name).as_dict())
		self.assertNamesNothingHidden(v2.read_doc("CRM Call Log", self.call.name))

	def test_the_desk_form_load_does_not_name_a_hidden_lead_or_deal(self):
		from frappe.desk.form.load import getdoc

		frappe.set_user(HIDDEN_REP)
		frappe.local.response = frappe._dict({"docs": []})
		getdoc("CRM Call Log", self.call.name)
		self.assertNamesNothingHidden([doc.as_dict() for doc in frappe.response.docs])

	def test_the_call_log_list_does_not_name_a_hidden_lead_or_deal(self):
		from crm.api.doc import get_data

		frappe.set_user(HIDDEN_REP)
		result = get_data("CRM Call Log", filters={"name": self.call.name}, order_by="creation desc")

		self.assertEqual([row["name"] for row in result["data"]], [self.call.name])
		self.assertNamesNothingHidden(result["data"])

	def test_a_readable_records_timeline_does_not_name_a_hidden_deal_on_its_calls(self):
		from crm.api.activities import get_linked_calls

		own_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": HIDDEN_REP}
		).insert(ignore_permissions=True)
		call = create_test_call_log(caller=HIDDEN_REP, telephony_medium="Twilio")
		call.link_with_reference_doc("CRM Lead", own_lead.name)
		call.link_with_reference_doc("CRM Deal", self.deal.name)
		call.save(ignore_permissions=True)

		frappe.set_user(HIDDEN_REP)
		result = get_linked_calls(own_lead.name)

		self.assertIn(call.name, [row["name"] for row in result["calls"]])
		self.assertNamesNothingHidden(result)

	def test_create_lead_is_refused_without_naming_the_record(self):
		leads_before = frappe.db.count("CRM Lead")
		frappe.set_user(HIDDEN_REP)

		with self.assertRaises(frappe.PermissionError) as raised:
			create_lead_from_call_log(call_log=frappe.as_json({"name": self.call.name}))

		self.assertNotIn(self.lead.name, str(raised.exception))
		self.assertNotIn(self.lead.name, frappe.as_json(frappe.local.message_log))
		frappe.set_user("Administrator")
		self.assertEqual(frappe.db.count("CRM Lead"), leads_before)
		self.call.reload()
		self.assertEqual([link.link_doctype for link in self.call.links], ["CRM Deal"])

	def test_saving_what_the_rep_was_served_keeps_the_hidden_reference(self):
		frappe.set_user(HIDDEN_REP)
		doc = frappe.get_doc("CRM Call Log", self.call.name)
		doc.apply_fieldlevel_read_permissions()
		doc.status = "Busy"
		doc.save()

		frappe.set_user("Administrator")
		self.call.reload()
		self.assertEqual(self.call.status, "Busy")
		self.assertEqual(self.call.reference_docname, self.lead.name)
		self.assertTrue(self.call.has_link("CRM Deal", self.deal.name))

	def test_the_owner_still_sees_the_lead_and_deal(self):
		frappe.set_user(HIDDEN_OWNER)
		result = get_call_log(self.call.name)

		self.assertEqual(result.get("_lead"), self.lead.name)
		self.assertEqual(result.get("_deal"), self.deal.name)
		self.assertNotIn("_has_hidden_reference", result)
		self.assertEqual(
			frappe.client.get("CRM Call Log", self.call.name)["reference_docname"], self.lead.name
		)

	def test_the_administrator_still_sees_the_lead_and_deal(self):
		result = get_call_log(self.call.name)

		self.assertEqual(result.get("_lead"), self.lead.name)
		self.assertEqual(result.get("_deal"), self.deal.name)
		self.assertTrue(self.call.has_link("CRM Deal", self.deal.name))
		self.assertEqual(
			frappe.client.get("CRM Call Log", self.call.name)["reference_docname"], self.lead.name
		)

	def test_create_lead_returns_a_readable_lead_already_linked(self):
		frappe.set_user(HIDDEN_OWNER)
		call = create_test_call_log(
			caller=HIDDEN_OWNER, reference_doctype="CRM Lead", reference_docname=self.lead.name
		)
		self.assertEqual(
			create_lead_from_call_log(call_log=frappe.as_json({"name": call.name})), self.lead.name
		)

	def test_a_hidden_lead_is_not_named_by_matching_its_number_either(self):
		"""Blanking the reference must not hand the name back through the phone
		lookup the unreferenced path uses: the lead the rep can't read is the
		only record on this number."""
		from crm.api.doc import get_data

		self.lead.db_set("mobile_no", "+919876500099")
		call = create_test_call_log(
			type="Outgoing",
			telephony_medium="Twilio",
			caller=HIDDEN_REP,
			to="+919876500099",
			reference_doctype="CRM Lead",
			reference_docname=self.lead.name,
		)

		frappe.set_user(HIDDEN_REP)
		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Unknown")
		rows = get_data("CRM Call Log", filters={"name": call.name}, order_by="creation desc")["data"]
		self.assertEqual([row["_receiver"]["label"] for row in rows], ["Unknown"])
		self.assertNamesNothingHidden(rows)

	def test_a_readable_records_timeline_does_not_name_a_hidden_deal_the_call_references(self):
		from crm.api.activities import get_linked_calls

		own_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": HIDDEN_REP}
		).insert(ignore_permissions=True)
		call = create_test_call_log(
			caller=HIDDEN_REP,
			telephony_medium="Twilio",
			reference_doctype="CRM Deal",
			reference_docname=self.deal.name,
		)
		call.link_with_reference_doc("CRM Lead", own_lead.name)
		call.save(ignore_permissions=True)

		frappe.set_user(HIDDEN_REP)
		result = get_linked_calls(own_lead.name)

		rows = [row for row in result["calls"] if row["name"] == call.name]
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0].get("_has_hidden_reference"), 1)
		self.assertNamesNothingHidden(result)

	def test_the_save_response_does_not_name_the_hidden_reference(self):
		"""frappe.client.set_value returns the saved document without the read-path
		hook, and validate has just put the reference back on it."""
		frappe.set_user(HIDDEN_REP)
		response = frappe.client.set_value("CRM Call Log", self.call.name, "status", "Busy")

		self.assertFalse(response.get("reference_docname"))
		self.assertEqual(response.get("_has_hidden_reference"), 1)
		self.assertNamesNothingHidden(response)

		frappe.set_user("Administrator")
		self.call.reload()
		self.assertEqual(self.call.status, "Busy")
		self.assertEqual(self.call.reference_docname, self.lead.name)
		self.assertTrue(self.call.has_link("CRM Deal", self.deal.name))

	def test_a_list_row_asked_for_the_bare_reference_name_is_redacted(self):
		"""A custom column set can ask for reference_docname without
		reference_doctype; the name alone must still be recognised."""
		from crm.api.doc import get_data

		frappe.set_user(HIDDEN_REP)
		result = get_data(
			"CRM Call Log",
			filters={"name": self.call.name},
			order_by="creation desc",
			rows=["name", "reference_docname"],
		)

		self.assertEqual([row["name"] for row in result["data"]], [self.call.name])
		self.assertFalse(result["data"][0].get("reference_docname"))
		self.assertNamesNothingHidden(result["data"])

	def test_the_tasks_and_notes_served_with_the_call_do_not_name_it(self):
		"""The deal's owner adds a task from the call and assigns it to the rep; the
		task is the rep's to read, but its reference is not."""
		task = frappe.get_doc(
			{
				"doctype": "CRM Task",
				"title": "Call back",
				"assigned_to": HIDDEN_REP,
				"reference_doctype": "CRM Deal",
				"reference_docname": self.deal.name,
			}
		).insert(ignore_permissions=True)
		self.call.link_with_reference_doc("CRM Task", task.name)
		self.call.save(ignore_permissions=True)

		frappe.set_user(HIDDEN_REP)
		result = get_call_log(self.call.name)

		self.assertEqual([t["name"] for t in result["_tasks"]], [task.name])
		self.assertFalse(result["_tasks"][0].get("reference_docname"))
		self.assertNamesNothingHidden(result)

	def test_an_unreferenced_call_is_not_named_by_a_hidden_leads_number(self):
		"""A call that points at nothing is named by its number, from the records
		the viewer may read only."""
		self.lead.db_set("mobile_no", "+919876500098")
		call = create_test_call_log(
			type="Outgoing", telephony_medium="Twilio", caller=HIDDEN_REP, to="+919876500098"
		)

		frappe.set_user(HIDDEN_REP)
		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Unknown")

		frappe.set_user("Administrator")
		self.assertEqual(get_call_log(call.name)["_receiver"]["label"], "Hidden")

	def test_a_restored_link_keeps_its_place(self):
		"""The first lead link is the call's lead; a rep's save must not move a
		hidden one behind their own."""
		own_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": HIDDEN_REP}
		).insert(ignore_permissions=True)
		call = create_test_call_log(caller=HIDDEN_REP, telephony_medium="Twilio")
		call.link_with_reference_doc("CRM Lead", self.lead.name)
		call.link_with_reference_doc("CRM Lead", own_lead.name)
		call.save(ignore_permissions=True)

		frappe.set_user(HIDDEN_REP)
		doc = frappe.get_doc("CRM Call Log", call.name)
		doc.apply_fieldlevel_read_permissions()
		self.assertEqual([link.link_name for link in doc.links], [own_lead.name])
		doc.status = "Busy"
		doc.save()

		frappe.set_user("Administrator")
		call.reload()
		self.assertEqual([link.link_name for link in call.links], [self.lead.name, own_lead.name])
		self.assertEqual([link.idx for link in call.links], [1, 2])
		self.assertEqual(get_call_log(call.name)["_lead"], self.lead.name)

	def test_create_lead_returns_the_readable_lead_beside_a_hidden_deal(self):
		own_lead = frappe.get_doc(
			{"doctype": "CRM Lead", "first_name": "Own", "lead_owner": HIDDEN_REP}
		).insert(ignore_permissions=True)
		call = create_test_call_log(
			caller=HIDDEN_REP,
			telephony_medium="Twilio",
			reference_doctype="CRM Lead",
			reference_docname=own_lead.name,
		)
		call.link_with_reference_doc("CRM Deal", self.deal.name)
		call.save(ignore_permissions=True)

		frappe.set_user(HIDDEN_REP)
		self.assertEqual(
			create_lead_from_call_log(call_log=frappe.as_json({"name": call.name})), own_lead.name
		)

	def test_an_in_tree_manager_still_sees_the_reps_lead_and_deal(self):
		"""Row scoping, not a role check: a Sales Manager whose subtree holds the
		owner reads the records, so nothing is redacted for them."""
		from frappe.utils.nestedset import rebuild_tree

		from crm.permissions.test_org_hierarchy import make_hierarchy_node

		manager = "calllog-manager@crmtest.test"
		if not frappe.db.exists("User", manager):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": manager,
					"first_name": "Calllog Manager",
					"send_welcome_email": 0,
				}
			).insert(ignore_permissions=True).add_roles("Sales Manager")
		node = make_hierarchy_node(manager, is_group=1)
		make_hierarchy_node(HIDDEN_OWNER, reports_to=node.name)
		rebuild_tree("CRM Sales Hierarchy")
		saved = frappe.db.get_single_value("FCRM Settings", "enable_sales_hierarchy")
		frappe.db.set_single_value("FCRM Settings", "enable_sales_hierarchy", 1)
		self.addCleanup(frappe.db.set_single_value, "FCRM Settings", "enable_sales_hierarchy", saved or 0)

		frappe.set_user(manager)
		result = get_call_log(self.call.name)

		self.assertEqual(result.get("_lead"), self.lead.name)
		self.assertEqual(result.get("_deal"), self.deal.name)
		self.assertNotIn("_has_hidden_reference", result)
		self.assertEqual(
			frappe.client.get("CRM Call Log", self.call.name)["reference_docname"], self.lead.name
		)

	def test_create_lead_is_refused_for_a_call_on_a_deal(self):
		leads_before = frappe.db.count("CRM Lead")
		call = create_test_call_log(reference_doctype="CRM Deal", reference_docname=self.deal.name)

		with self.assertRaises(frappe.ValidationError):
			create_lead_from_call_log(call_log=frappe.as_json({"name": call.name}))
		self.assertEqual(frappe.db.count("CRM Lead"), leads_before)


class TestCallLogRowsResolveInBatches(IntegrationTestCase):
	"""The call-log list and a record's timeline label every call's caller and receiver.
	That used to cost a handful of queries per row (the record's existence, its
	permission, its contact, the user), so a page of a hundred calls ran several
	hundred. The cost must not grow with the number of calls."""

	def tearDown(self):
		frappe.db.rollback()

	def make_calls(self, per_kind, reference=None):
		"""``per_kind`` calls on distinct leads, on distinct deals and on no record at all."""
		org = frappe.get_doc({"doctype": "CRM Organization", "organization_name": "Batch Org"}).insert(
			ignore_if_duplicate=True
		)
		names = []
		for i in range(per_kind):
			lead = create_test_lead(f"Batch Lead {i}", None)
			contact = frappe.get_doc({"doctype": "Contact", "first_name": f"Batch Contact {i}"}).insert()
			deal = frappe.get_doc(
				{"doctype": "CRM Deal", "organization": org.name, "deal_owner": "Administrator"}
			)
			deal.append("contacts", {"contact": contact.name, "is_primary": 1})
			deal.insert()
			for doctype, docname in (("CRM Lead", lead.name), ("CRM Deal", deal.name)):
				call = create_test_call_log(
					type="Outgoing",
					caller="Administrator",
					to=f"+9198765{i:05d}",
					reference_doctype=doctype,
					reference_docname=docname,
				)
				if reference:
					call.link_with_reference_doc(*reference)
					call.save()
				names.append(call.name)
			call = create_test_call_log(
				type="Incoming", receiver="Administrator", from_number="+919876511111"
			)
			if reference:
				call.link_with_reference_doc(*reference)
				call.save()
			names.append(call.name)
		return names

	def list_rows(self, names):
		from crm.fcrm.doctype.crm_call_log.crm_call_log import CRMCallLog

		return frappe.get_all(
			"CRM Call Log",
			filters={"name": ("in", names)},
			fields=CRMCallLog.default_list_data()["rows"],
		)

	def count_queries(self, fn, *args):
		count = 0
		real_sql = frappe.db.sql

		def counting(*a, **k):
			nonlocal count
			count += 1
			return real_sql(*a, **k)

		with patch.object(frappe.db, "sql", side_effect=counting):
			fn(*args)
		return count

	def test_a_list_page_costs_the_same_queries_however_many_calls_it_holds(self):
		from crm.fcrm.doctype.crm_call_log.crm_call_log import CRMCallLog

		small, large = self.list_rows(self.make_calls(2)), self.list_rows(self.make_calls(8))
		# meta, roles and the phone lookup's first hit are cached after one pass
		CRMCallLog.parse_list_data(self.list_rows(self.make_calls(1)))

		self.assertEqual(
			self.count_queries(CRMCallLog.parse_list_data, large),
			self.count_queries(CRMCallLog.parse_list_data, small),
		)

	def test_a_records_timeline_costs_the_same_queries_however_many_calls_it_has(self):
		from crm.api.activities import get_linked_calls

		small_lead = create_test_lead("Few Calls", None)
		large_lead = create_test_lead("Many Calls", None)
		self.make_calls(2, reference=("CRM Lead", small_lead.name))
		self.make_calls(8, reference=("CRM Lead", large_lead.name))
		get_linked_calls(small_lead.name)

		self.assertEqual(
			self.count_queries(get_linked_calls, large_lead.name),
			self.count_queries(get_linked_calls, small_lead.name),
		)

	def test_every_row_is_still_labelled_from_its_own_record(self):
		from crm.fcrm.doctype.crm_call_log.crm_call_log import CRMCallLog

		create_test_lead("Number Lead", "+919876522222")
		names = self.make_calls(2)
		names.append(create_test_call_log(type="Incoming", from_number="+919876522222").name)
		dangling = create_test_lead("Gone Lead", None)
		names.append(
			create_test_call_log(
				type="Outgoing", reference_doctype="CRM Lead", reference_docname=dangling.name
			).name
		)
		frappe.delete_doc("CRM Lead", dangling.name, force=True, ignore_permissions=True)

		rows = CRMCallLog.parse_list_data(self.list_rows(names))
		admin = frappe.db.get_value("User", "Administrator", "full_name")
		# reference_doctype defaults to CRM Lead, so only the name says a call points at a record.
		labels = {
			(
				row.reference_doctype if row.reference_docname else "",
				row["from"] if row.type == "Incoming" else row.to,
			): (
				row._caller["label"],
				row._receiver["label"],
			)
			for row in rows
		}
		for i in range(2):
			self.assertEqual(labels[("CRM Lead", f"+9198765{i:05d}")], (admin, f"Batch Lead {i}"))
			self.assertEqual(labels[("CRM Deal", f"+9198765{i:05d}")], (admin, f"Batch Contact {i}"))
		self.assertEqual(labels[("", "+919876511111")], ("Unknown", admin))
		self.assertEqual(labels[("", "+919876522222")], ("Number Lead", admin))
		self.assertEqual(labels[("CRM Lead", "+1234567890")][1], "Unknown")


def create_test_call_log(**kwargs):
	"""Helper function to create a CRM Call Log for testing"""
	import uuid

	# Generate unique ID if not provided (required for autoname)
	unique_id = kwargs.pop("id", str(uuid.uuid4())[:10])

	# Handle special field name mapping
	if "from_number" in kwargs:
		kwargs["from"] = kwargs.pop("from_number")

	# Set defaults for required fields
	data = {
		"doctype": "CRM Call Log",
		"id": unique_id,
		"type": "Incoming",
		"status": "Completed",
		"to": "+1234567890",
		"from": "+0987654321",
	}

	# Update with all provided kwargs
	data.update(kwargs)

	call_log = frappe.get_doc(data)
	call_log.insert()
	return call_log
