# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""Settings -> Knowledge endpoints: who may write, and that the sample import
is idempotent by title."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from crm.api import knowledge as api
from crm.knowledge import load_samples

REP = "knowledge-rep@crmtest.test"


def make_sales_user(email: str) -> None:
	if not frappe.db.exists("User", email):
		user = frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": "Knowledge Rep", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
		user.add_roles("Sales User")


class KnowledgeApiTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.db.savepoint("knowledge_api")
		self.addCleanup(frappe.db.rollback, save_point="knowledge_api")
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.db.delete("CRM Knowledge Article")
		make_sales_user(REP)

	def test_import_samples_is_idempotent_by_title(self):
		first = api.import_samples()
		self.assertEqual(first["imported"], len(load_samples()))
		self.assertEqual(first["skipped"], 0)

		second = api.import_samples()
		self.assertEqual(second["imported"], 0)
		self.assertEqual(second["skipped"], len(load_samples()))
		self.assertEqual(frappe.db.count("CRM Knowledge Article"), len(load_samples()))

	def test_save_and_delete_round_trip_and_tags_are_normalised(self):
		saved = api.save_article(
			{"title": " Gate valves ", "category": "Valves", "tags": "gate ,  isolation,", "body": "x"}
		)
		self.assertEqual(saved["title"], "Gate valves")
		self.assertEqual(saved["tags"], "gate, isolation")
		self.assertEqual(saved["available_to_assistant"], 1)

		updated = api.save_article({"name": saved["name"], "available_to_assistant": 0, "owner": "hacker"})
		self.assertEqual(updated["available_to_assistant"], 0)
		self.assertEqual(
			frappe.db.get_value("CRM Knowledge Article", saved["name"], "owner"), frappe.session.user
		)

		api.delete_article(saved["name"])
		self.assertFalse(frappe.db.exists("CRM Knowledge Article", saved["name"]))

	def test_a_sales_user_may_read_but_not_write(self):
		api.save_article({"title": "Readable", "category": "Valves", "body": "x"})
		frappe.set_user(REP)
		self.assertEqual(len(api.list_articles()["articles"]), 1)
		with self.assertRaises(frappe.PermissionError):
			api.save_article({"title": "Nope", "category": "Valves", "body": "x"})
		with self.assertRaises(frappe.PermissionError):
			api.import_samples()
		with self.assertRaises(frappe.PermissionError):
			api.delete_article("KB-00001")
