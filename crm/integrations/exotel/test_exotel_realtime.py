# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The incoming-call webhook used to broadcast Exotel's raw payload site-wide.

`publish_realtime` with no room reaches `get_site_room()` -- every logged-in
session -- and the payload is Exotel's passthru, including `CallFrom`: the
customer's phone number. `ExotelCallUI` does filter on `AgentEmail` before it
shows the popup, but that decision happens after the data has crossed the wire
to every rep's browser.

There is no Exotel account to test against here, so these exercise the
addressing decision directly with representative payloads.
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from crm.integrations.exotel.handler import _call_agent, _publish_call_to_agent

AGENT = "exotel-agent@crmtest.test"
CUSTOMER_NUMBER = "+15550001111"


class ExotelRealtimeScopeTest(IntegrationTestCase):
	def published(self, payload, call_log=None):
		"""Only this handler's own publishes.

		`log_error` writes an Error Log, and inserting one makes frappe publish
		its own `list_update` — which the patch intercepts before frappe fills
		in the room it would have set. Asserting over every captured call would
		be testing the framework, and failing on it.
		"""
		with patch.object(frappe, "publish_realtime") as publish:
			_publish_call_to_agent(payload, call_log)
		return [call for call in publish.call_args_list if call.args[:1] == ("exotel_call",)]

	def test_an_incoming_call_reaches_only_its_agent(self):
		calls = self.published({"CallSid": "abc", "CallFrom": CUSTOMER_NUMBER, "AgentEmail": AGENT})
		self.assertEqual(len(calls), 1)
		self.assertEqual(calls[0].kwargs["user"], AGENT)

	def test_the_customer_number_is_never_sent_unaddressed(self):
		"""The property that matters: whatever the payload, no publish may go
		out without a recipient."""
		payloads = [
			{"CallSid": "a", "CallFrom": CUSTOMER_NUMBER, "AgentEmail": AGENT},
			{"CallSid": "b", "CallFrom": CUSTOMER_NUMBER},
			{"CallSid": "c"},
		]
		for payload in payloads:
			with self.subTest(payload=payload):
				for call in self.published(payload):
					self.assertTrue(
						call.kwargs.get("user") or call.kwargs.get("room") or call.kwargs.get("doctype"),
						f"unaddressed publish carrying {call.args}",
					)

	def test_nothing_is_published_when_the_agent_is_unknown(self):
		"""Silence beats broadcasting a customer's number to the company. The
		handler logs it, so the case is visible rather than merely absent."""
		with patch.object(frappe, "log_error") as log_error:
			calls = self.published({"CallSid": "c", "CallFrom": CUSTOMER_NUMBER})
		self.assertEqual(calls, [])
		self.assertTrue(log_error.called)

	def test_an_existing_call_log_supplies_the_agent(self):
		"""Status callbacks for a call already logged carry no AgentEmail; the
		log knows who it belongs to."""
		log = frappe._dict({"receiver": AGENT, "caller": None})
		self.assertEqual(_call_agent({"CallSid": "d"}, log), AGENT)

	def test_an_outgoing_call_log_supplies_the_caller(self):
		log = frappe._dict({"receiver": None, "caller": AGENT})
		self.assertEqual(_call_agent({"CallSid": "e"}, log), AGENT)

	def test_the_payload_still_arrives_intact(self):
		payload = {"CallSid": "f", "CallFrom": CUSTOMER_NUMBER, "AgentEmail": AGENT}
		calls = self.published(payload)
		self.assertEqual(calls[0].args[0], "exotel_call")
		self.assertEqual(calls[0].args[1], payload)
