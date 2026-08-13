# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Pure tests for the output contract.

The same pydantic model produces the JSON Schema sent to the model and validates what
comes back, so a drift between the two is impossible by construction.
"""

from __future__ import annotations

from frappe.tests import UnitTestCase

from crm.agent.errors import SchemaMismatch
from crm.agent.schemas import ThreadSummary, json_schema, parse_into

VALID = '{"summary": "Waiting on pricing sign-off.", "next_steps": ["Send quote"], "sentiment": "neutral"}'


class ThreadSummarySchemaTest(UnitTestCase):
	def test_schema_declares_required_fields_and_forbids_extras(self):
		schema = json_schema(ThreadSummary)
		self.assertIn("summary", schema["properties"])
		self.assertIn("summary", schema["required"])
		self.assertFalse(schema["additionalProperties"])

	def test_valid_payload_parses(self):
		result = parse_into(ThreadSummary, VALID)
		self.assertEqual(result.sentiment, "neutral")
		self.assertEqual(result.next_steps, ["Send quote"])

	def test_prose_instead_of_json_raises_schema_mismatch(self):
		with self.assertRaises(SchemaMismatch):
			parse_into(ThreadSummary, "Sure! Here is the summary you asked for.")

	def test_unknown_key_raises_schema_mismatch(self):
		payload = '{"summary": "x", "owner": "admin@example.com"}'
		with self.assertRaises(SchemaMismatch):
			parse_into(ThreadSummary, payload)

	def test_invalid_sentiment_raises_schema_mismatch(self):
		payload = '{"summary": "x", "sentiment": "furious"}'
		with self.assertRaises(SchemaMismatch):
			parse_into(ThreadSummary, payload)

	def test_mismatch_message_is_useful_enough_to_send_back_to_the_model(self):
		with self.assertRaises(SchemaMismatch) as ctx:
			parse_into(ThreadSummary, '{"summary": "x", "sentiment": "furious"}')
		self.assertIn("sentiment", str(ctx.exception))
