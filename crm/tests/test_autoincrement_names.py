"""Whitelisted endpoints must take back the int names autoincremented doctypes give out.

CRM Task autoincrements, so the browser holds its name as a number and posts it as a
JSON number. Frappe validates whitelisted arguments against their annotations -- in
request and in test context alike -- so a bare ``str`` answers 417 to every real call.
"""

import frappe
from frappe.tests import IntegrationTestCase

from crm.api.doc import _unlink_linked_docs, get_linked_docs_of_document


class LinkedDocsOfAnAutoincrementedRecordTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.task = frappe.get_doc({"doctype": "CRM Task", "title": "Autoincrement probe"}).insert(
			ignore_permissions=True
		)
		self.assertIsInstance(self.task.name, int)

	def tearDown(self):
		frappe.db.rollback()
		super().tearDown()

	def test_the_delete_modal_can_list_a_tasks_linked_documents(self):
		"""DeleteLinkedDocModal asks for these with the int name; the 417 left it
		offering a plain Delete with no idea what the task was linked to."""
		self.assertEqual(get_linked_docs_of_document("CRM Task", self.task.name), [])

	def test_bulk_delete_unlinks_tasks_without_an_error_log_per_task(self):
		"""delete_bulk_docs hands the ints it was posted to _unlink_linked_docs, which
		calls the endpoint in-process -- and the annotation is checked there too."""
		before = frappe.db.count("Error Log")

		_unlink_linked_docs("CRM Task", [self.task.name])

		self.assertEqual(frappe.db.count("Error Log"), before, "one Bulk Delete Error per task")
