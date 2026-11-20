# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""A list cannot borrow a parent it is not a child table of.

Replays the request against the real query builders: a rep who names a Single as
the parent of ``CRM Lead`` used to be handed every lead on the site. See
``crm.permissions.engine_guard``.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.client import get_count, get_list, get_value
from frappe.database.query import Engine
from frappe.desk.doctype.number_card.number_card import get_result
from frappe.desk.reportview import execute as reportview_execute
from frappe.model.db_query import DatabaseQuery as LegacyQuery
from frappe.tests import IntegrationTestCase

from crm import hooks
from crm.permissions import engine_guard

ALICE = "parentguard-alice@crmtest.test"
BOB = "parentguard-bob@crmtest.test"
SINGLE = "System Settings"
REFUSAL = "parent it does not belong to"


def ensure_rep(email: str) -> None:
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	frappe.get_doc("User", email).add_roles("Sales User")


class ListParentGuardTest(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		ensure_rep(ALICE)
		ensure_rep(BOB)
		lead = frappe.get_doc({"doctype": "CRM Lead", "lead_owner": BOB, "first_name": "Bobs Lead"})
		lead.flags.ignore_mandatory = True
		self.bobs_lead = lead.insert(ignore_permissions=True).name
		# a test process serves no request, so nothing has run before_request for it
		engine_guard.install()
		frappe.set_user(ALICE)

	def tearDown(self):
		frappe.set_user("Administrator")
		frappe.delete_doc("CRM Lead", self.bobs_lead, force=True, ignore_permissions=True)
		super().tearDown()

	def refused(self):
		return self.assertRaisesRegex(frappe.PermissionError, REFUSAL)

	# --- the wrap itself ----------------------------------------------------

	def test_both_builders_are_guarded_and_installing_again_changes_nothing(self):
		self.assertTrue(engine_guard.installed())
		select, read = Engine.check_select_permission, LegacyQuery.check_read_permission
		engine_guard.install()
		engine_guard.install(method="x", kwargs={}, transaction_type="job")
		self.assertIs(Engine.check_select_permission, select)
		self.assertIs(LegacyQuery.check_read_permission, read)
		engine_guard.ensure_installed()

	def test_it_is_installed_first_in_every_request_and_job_and_checked_at_migrate(self):
		self.assertEqual(hooks.before_request[0], "crm.permissions.engine_guard.install")
		self.assertEqual(hooks.before_job[0], "crm.permissions.engine_guard.install")
		self.assertIn("crm.permissions.engine_guard.ensure_installed", hooks.after_migrate)
		# and frappe resolves them, as a web worker and an RQ worker will
		self.assertIn("crm.permissions.engine_guard.install", frappe.get_hooks("before_request"))
		self.assertIn("crm.permissions.engine_guard.install", frappe.get_hooks("before_job"))
		self.assertIs(
			frappe.get_attr(frappe.get_hooks("before_request", app_name="crm")[0]), engine_guard.install
		)

	def test_a_frappe_that_renamed_a_method_fails_the_migrate(self):
		renamed = type("DatabaseQuery", (), {})
		with patch("frappe.model.db_query.DatabaseQuery", renamed):
			self.assertFalse(engine_guard.installed())
			with self.assertRaises(frappe.ValidationError):
				engine_guard.ensure_installed()
		self.assertTrue(engine_guard.installed())

	# --- what a rep sees without naming a parent ----------------------------

	def test_a_rep_does_not_list_another_reps_lead(self):
		self.assertNotIn(self.bobs_lead, frappe.get_list("CRM Lead", pluck="name", limit=0))

	# --- the borrowed parent, by every route that carries one -----------------

	def test_get_list_refuses_a_single_as_parent(self):
		with self.refused():
			frappe.get_list("CRM Lead", parent_doctype=SINGLE, pluck="name", limit=0)

	def test_the_client_api_refuses_it(self):
		with self.refused():
			get_list("CRM Lead", fields=["name", "lead_owner"], parent=SINGLE, limit_page_length=0)
		with self.refused():
			get_value("CRM Lead", "lead_owner", {"name": self.bobs_lead}, parent=SINGLE)
		# get_count has no such argument: the report view reads it from the request
		self.addCleanup(setattr, frappe.local, "form_dict", frappe.local.form_dict)
		frappe.local.form_dict = frappe._dict(parent_doctype=SINGLE)
		with self.refused():
			get_count("CRM Lead")

	def test_the_report_view_refuses_it(self):
		with self.refused():
			reportview_execute("CRM Lead", fields=["name"], parent_doctype=SINGLE, limit=0)

	def test_a_number_card_that_describes_one_is_refused(self):
		card = {"document_type": "CRM Lead", "parent_document_type": SINGLE, "function": "Count"}
		with self.refused():
			get_result(json.dumps(card), "[]")

	def test_the_older_builder_refuses_it_too(self):
		with self.refused():
			LegacyQuery("CRM Lead").execute(fields=["name"], parent_doctype=SINGLE, limit_page_length=0)

	def test_other_borrowed_parents_are_refused_as_well(self):
		for parent in ("CRM Deal", "No Such Doctype", "FCRM Settings"):
			with self.subTest(parent=parent), self.refused():
				frappe.get_list("CRM Lead", parent_doctype=parent, pluck="name")
		# a child table, under a parent that is not its own
		with self.refused():
			frappe.get_list("Event Participants", parent_doctype=SINGLE, pluck="name")

	def test_without_the_guard_the_borrowed_parent_lists_the_other_reps_lead(self):
		"""The reason the guard exists, kept as a test so it is known when it stops
		being one: when this fails, the frappe pin checks the parent itself and
		engine_guard can go."""
		guarded = Engine.check_select_permission
		self.addCleanup(setattr, Engine, "check_select_permission", guarded)
		Engine.check_select_permission = guarded.__wrapped__
		leaked = frappe.get_list("CRM Lead", parent_doctype=SINGLE, pluck="name", limit=0)
		self.assertIn(self.bobs_lead, leaked)

	# --- honest lists are untouched -------------------------------------------

	def test_a_child_table_still_lists_under_its_true_parent(self):
		# what the event panel asks for (frontend/src/composables/event.js)
		rows = get_list("Event Participants", fields=["name", "parent"], parent="Event")
		self.assertIsInstance(rows, list)

	def test_a_singles_own_child_table_still_lists(self):
		frappe.set_user("Administrator")
		tables = frappe.get_meta("FCRM Settings").get_table_fields()
		self.assertTrue(tables, "FCRM Settings no longer has a child table to test with")
		rows = frappe.get_list(tables[0].options, parent_doctype="FCRM Settings", pluck="name")
		self.assertIsInstance(rows, list)

	def test_a_doctype_named_as_its_own_parent_keeps_its_row_rules(self):
		names = frappe.get_list("CRM Lead", parent_doctype="CRM Lead", pluck="name", limit=0)
		self.assertNotIn(self.bobs_lead, names)

	def test_the_server_setting_permissions_aside_is_not_a_request(self):
		# frappe.get_all never asks the builders to check anything
		names = frappe.get_all("CRM Lead", parent_doctype=SINGLE, pluck="name", limit=0)
		self.assertIn(self.bobs_lead, names)
