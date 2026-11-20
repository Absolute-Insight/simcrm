# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""What a request can no longer ask of a list. See ``crm.permissions.engine_guard``.

Each part is replayed against the real query builder as a rep, and each has a
test that takes the guard away and shows the leak, so the day frappe closes one
itself is the day that test fails.
"""

from __future__ import annotations

import json
import sys
import types
from unittest.mock import patch

import frappe
from frappe.client import get_count, get_list, get_value
from frappe.database.query import Engine
from frappe.desk.doctype.number_card.number_card import get_result
from frappe.desk.reportview import execute as reportview_execute
from frappe.desk.reportview import get_list as reportview_get_list
from frappe.tests import IntegrationTestCase

from crm import hooks
from crm.permissions import document_guard, engine_guard

try:
	from frappe.model.db_query import DatabaseQuery as LegacyQuery
except ImportError:  # frappe has dropped the older builder; nothing of it to test
	LegacyQuery = None

ALICE = "parentguard-alice@crmtest.test"
BOB = "parentguard-bob@crmtest.test"
SINGLE = "System Settings"
SHARED_CHILD = "Event Notifications"  # a table of FCRM Settings and of Event
REPORT_VIEW = "/api/method/frappe.desk.reportview.get"
LINK_SEARCH = "frappe.desk.search.search_link"
LINK_VALIDATION = "frappe.client.validate_link_and_fetch"
REFUSAL = "parent it does not belong to"
ENGINE_METHODS = ("check_select_permission", "add_permission_conditions")


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

	def without(self, owner, name):
		"""Take one wrap away for the rest of the test."""
		guarded = getattr(owner, name)
		self.addCleanup(setattr, owner, name, guarded)
		setattr(owner, name, guarded.__wrapped__)

	def request(self, path="/", **form):
		"""Make this look like a request for ``path`` carrying ``form``."""
		for attr in ("form_dict", "request"):
			if hasattr(frappe.local, attr):
				self.addCleanup(setattr, frappe.local, attr, getattr(frappe.local, attr))
			else:
				self.addCleanup(delattr, frappe.local, attr)
		frappe.local.request = types.SimpleNamespace(path=path)
		frappe.local.form_dict = frappe._dict(form)

	# --- the wrap itself ----------------------------------------------------

	def test_both_builders_are_guarded_and_installing_again_changes_nothing(self):
		self.assertTrue(engine_guard.installed())
		select, conditions = Engine.check_select_permission, Engine.add_permission_conditions
		engine_guard.install()
		engine_guard.install(method="x", kwargs={}, transaction_type="job")
		self.assertIs(Engine.check_select_permission, select)
		self.assertIs(Engine.add_permission_conditions, conditions)
		self.assertTrue(hasattr(select, "__wrapped__") and hasattr(conditions, "__wrapped__"))
		if LegacyQuery:
			self.assertTrue(hasattr(LegacyQuery.check_read_permission, "__wrapped__"))
		engine_guard.ensure_installed()

	def test_it_is_installed_first_in_every_request_and_job_and_checked_at_migrate(self):
		self.assertEqual(hooks.before_request[0], "crm.permissions.engine_guard.guard_request")
		self.assertEqual(hooks.before_job[0], "crm.permissions.engine_guard.install")
		self.assertIn("crm.permissions.engine_guard.ensure_installed", hooks.after_migrate)
		# and frappe resolves them, as a web worker and an RQ worker will
		self.assertIn("crm.permissions.engine_guard.guard_request", frappe.get_hooks("before_request"))
		self.assertIn("crm.permissions.engine_guard.install", frappe.get_hooks("before_job"))
		self.assertIs(
			frappe.get_attr(frappe.get_hooks("before_request", app_name="crm")[0]),
			engine_guard.guard_request,
		)

	def test_a_worker_still_on_the_old_hook_lists_is_guarded_too(self):
		"""Hooks are cached past a restart; the old lists name reserve_action."""
		self.without(Engine, "check_select_permission")
		self.without(Engine, "add_permission_conditions")
		self.assertFalse(engine_guard.installed())
		self.request(REPORT_VIEW, doctype="CRM Lead", ignore_user_permissions="1")
		document_guard.reserve_action()
		self.assertTrue(engine_guard.installed())
		self.assertNotIn("ignore_user_permissions", frappe.form_dict)

	def test_a_frappe_that_renamed_an_engine_method_fails_the_migrate(self):
		for gone in ("check_select_permission", "add_permission_conditions"):
			kept = {name: getattr(Engine, name) for name in ENGINE_METHODS if name != gone}
			with self.subTest(gone=gone), patch("frappe.database.query.Engine", type("Engine", (), kept)):
				self.assertFalse(engine_guard.installed())
				with self.assertRaises(frappe.ValidationError):
					engine_guard.ensure_installed()
				with self.assertRaises(AttributeError):
					engine_guard.install()
		self.assertTrue(engine_guard.installed())

	def test_a_frappe_without_the_older_builder_is_still_guarded(self):
		"""Nothing calls it any more; its removal must not fail a migrate or a request."""
		without_class = types.ModuleType("frappe.model.db_query")
		with patch.dict(sys.modules, {"frappe.model.db_query": without_class}):
			engine_guard.install()
			engine_guard.ensure_installed()
			self.assertTrue(engine_guard.installed())
		without_method = type("DatabaseQuery", (), {})
		with patch.dict(sys.modules, {"frappe.model.db_query": without_class}):
			without_class.DatabaseQuery = without_method
			engine_guard.guard_request()
			engine_guard.ensure_installed()
			self.assertTrue(engine_guard.installed())
		self.assertFalse(hasattr(without_method, "check_read_permission"))

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
		if not LegacyQuery:
			self.skipTest("this frappe has no older builder")
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
		self.without(Engine, "check_select_permission")
		# the second wrap alone would stop this too, on a column a lead does not have
		self.without(Engine, "add_permission_conditions")
		leaked = frappe.get_list("CRM Lead", parent_doctype=SINGLE, pluck="name", limit=0)
		self.assertIn(self.bobs_lead, leaked)

	# --- a doctype by another spelling ------------------------------------------

	def test_a_doctype_is_listed_only_by_its_own_name(self):
		"""The row rules in hooks.py are keyed on the exact name; the database is not."""
		self.assertIn("CRM Lead", frappe.get_hooks("permission_query_conditions"))
		spelling = self.assertRaisesRegex(frappe.PermissionError, "another spelling")
		for variant in ("crm lead", "CRM lead", "Crm Lead"):
			with self.subTest(variant=variant):
				self.assertEqual(frappe.get_meta(variant).name, "CRM Lead")
				self.assertFalse(engine_guard.spelled_as_named(variant))
				# the builder itself, which is as far as a database that folds
				# table names would let the request get
				with spelling:
					frappe.qb.get_query(variant, fields=["name"], ignore_permissions=False)
				with spelling:
					frappe.qb.get_query(
						"CRM Products", fields=["name"], ignore_permissions=False, parent_doctype=variant
					)
				# by the routes, this database (case-sensitive tables) stops it
				# sooner; either way it is an error and never a list
				for route in (
					lambda: frappe.get_list(variant, pluck="name", limit=0),
					lambda: get_list(variant, fields=["name"], limit_page_length=0),
					lambda: reportview_execute(variant, fields=["name"], limit=0),
				):
					with self.assertRaises((frappe.PermissionError, frappe.db.TableMissingError)):
						route()
		# a parent is not looked up as a table first, so the routes reach the guard
		for parent in ("event", "EVENT"):
			with self.subTest(parent=parent), spelling:
				get_list(SHARED_CHILD, fields=["name"], parent=parent)
		with spelling:
			get_list(SHARED_CHILD, fields=["name"], parent="fcrm settings")
		with spelling:
			frappe.get_list("CRM Lead", parent_doctype="crm lead", pluck="name")

	def test_the_true_names_still_list(self):
		self.assertNotIn(self.bobs_lead, frappe.get_list("CRM Lead", pluck="name", limit=0))
		self.assertIsInstance(get_list(SHARED_CHILD, fields=["name"], parent="Event"), list)
		self.assertTrue(engine_guard.spelled_as_named("CRM Lead"))
		self.assertTrue(engine_guard.spelled_as_named(None))
		# not a doctype at all: left for frappe's own check to refuse
		self.assertTrue(engine_guard.spelled_as_named("No Such Doctype"))
		with self.assertRaises(Exception):
			frappe.get_list("No Such Doctype", pluck="name")

	# --- honest lists are untouched -------------------------------------------

	def test_a_child_table_still_lists_under_its_true_parent(self):
		# what the event panel asks for (frontend/src/composables/event.js)
		rows = get_list("Event Participants", fields=["name", "parent"], parent="Event")
		self.assertIsInstance(rows, list)

	# --- a child table a Single shares with another doctype ---------------------

	def bobs_event_reminder(self) -> str:
		"""A reminder row on an event of Bob's that Alice has no part in."""
		frappe.set_user(BOB)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Bobs private event",
				"event_type": "Private",
				"starts_on": frappe.utils.now_datetime(),
				"notifications": [{"type": "Notification", "before": 7, "interval": "minutes"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, "Event", event.name, force=True, ignore_permissions=True)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(ALICE)
		return event.notifications[0].name

	def settings_reminder(self) -> str:
		"""A row of the Single's own, written as the settings form would store it."""
		row = frappe.get_doc(
			{
				"doctype": SHARED_CHILD,
				"parent": "FCRM Settings",
				"parenttype": "FCRM Settings",
				"parentfield": "event_notifications",
				"type": "Notification",
				"before": 9,
				"interval": "minutes",
			}
		)
		row.db_insert()
		self.addCleanup(frappe.db.delete, SHARED_CHILD, {"name": row.name})
		return row.name

	def shared_child_fields(self):
		tables = frappe.get_meta("FCRM Settings").get_table_fields()
		self.assertIn(
			SHARED_CHILD, [df.options for df in tables], "FCRM Settings no longer shares this table"
		)
		self.assertIn(SHARED_CHILD, [df.options for df in frappe.get_meta("Event").get_table_fields()])

	def test_under_a_single_only_the_singles_own_rows_are_listed(self):
		self.shared_child_fields()
		theirs, own = self.bobs_event_reminder(), self.settings_reminder()
		rows = get_list(
			SHARED_CHILD, fields=["name", "parent", "parenttype"], parent="FCRM Settings", limit_page_length=0
		)
		names = [row.name for row in rows]
		self.assertIn(own, names)
		self.assertNotIn(theirs, names)
		self.assertEqual({row.parenttype for row in rows}, {"FCRM Settings"})
		# and by the routes that count and aggregate
		self.assertNotIn(
			theirs, reportview_execute(SHARED_CHILD, parent_doctype="FCRM Settings", pluck="name", limit=0)
		)
		everything = frappe.get_all(SHARED_CHILD, filters={"parenttype": "FCRM Settings"}, pluck="name")
		card = {"document_type": SHARED_CHILD, "parent_document_type": "FCRM Settings", "function": "Count"}
		self.assertEqual(get_result(json.dumps(card), "[]"), len(everything))

	def test_without_the_guard_a_single_parent_lists_another_reps_event_rows(self):
		"""Why the second wrap exists; when this fails frappe filters parenttype itself."""
		self.shared_child_fields()
		theirs = self.bobs_event_reminder()
		self.without(Engine, "add_permission_conditions")
		leaked = frappe.get_list(SHARED_CHILD, parent_doctype="FCRM Settings", pluck="name", limit=0)
		self.assertIn(theirs, leaked)

	def same_named_row_of_another_parent(self) -> tuple[str, str]:
		"""An event of Alice's, and a row of this table kept under another doctype's
		document that happens to carry the event's name."""
		frappe.set_user(ALICE)
		event = frappe.get_doc(
			{
				"doctype": "Event",
				"subject": "Alices event",
				"event_type": "Private",
				"starts_on": frappe.utils.now_datetime(),
				"notifications": [{"type": "Notification", "before": 5, "interval": "minutes"}],
			}
		).insert(ignore_permissions=True)
		frappe.set_user("Administrator")
		self.addCleanup(frappe.delete_doc, "Event", event.name, force=True, ignore_permissions=True)
		other = frappe.get_doc(
			{
				"doctype": SHARED_CHILD,
				"parent": event.name,
				"parenttype": "CRM Deal",
				"parentfield": "notifications",
				"type": "Email",
				"before": 3,
				"interval": "hours",
			}
		)
		other.db_insert()
		self.addCleanup(frappe.db.delete, SHARED_CHILD, {"name": other.name})
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(ALICE)
		return event.notifications[0].name, other.name

	def test_under_an_ordinary_parent_only_that_doctypes_rows_are_listed(self):
		own, other = self.same_named_row_of_another_parent()
		rows = get_list(SHARED_CHILD, fields=["name", "parenttype"], parent="Event", limit_page_length=0)
		names = [row.name for row in rows]
		self.assertIn(own, names)
		self.assertNotIn(other, names)
		self.assertEqual({row.parenttype for row in rows}, {"Event"})
		self.assertNotIn(
			other, reportview_execute(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0)
		)

	def test_without_the_guard_a_same_named_parent_of_another_doctype_leaks(self):
		"""Why the wrap is not kept to Singles; when this fails frappe joins on parenttype."""
		own, other = self.same_named_row_of_another_parent()
		self.without(Engine, "add_permission_conditions")
		leaked = frappe.get_list(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0)
		self.assertIn(own, leaked)
		self.assertIn(other, leaked)

	def test_the_parenttype_condition_costs_an_honest_list_nothing(self):
		"""Each table under its parent, with the wrap and without it: the same rows."""
		reminder = self.bobs_event_reminder()
		frappe.set_user("Administrator")
		guarded = Engine.add_permission_conditions
		compared = 0
		for parent in ("Event", "CRM Deal", "CRM Lead", "Contact", "Address", "CRM Rep Plan"):
			for df in frappe.get_meta(parent).get_table_fields():
				with self.subTest(parent=parent, table=df.options):
					with_it = frappe.get_list(df.options, parent_doctype=parent, pluck="name", limit=0)
					with patch.object(Engine, "add_permission_conditions", guarded.__wrapped__):
						without_it = frappe.get_list(df.options, parent_doctype=parent, pluck="name", limit=0)
					self.assertCountEqual(with_it, without_it)
					compared += len(with_it)
		self.assertTrue(compared, "nothing was listed, so nothing was compared")
		# a private event's rows are its owner's to list, whoever else is asking
		frappe.set_user(BOB)
		with_it = frappe.get_list(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0)
		with patch.object(Engine, "add_permission_conditions", guarded.__wrapped__):
			without_it = frappe.get_list(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0)
		self.assertIn(reminder, with_it)
		self.assertCountEqual(with_it, without_it)

	def test_an_ordinary_parent_keeps_its_own_row_rules(self):
		theirs = self.bobs_event_reminder()
		self.assertNotIn(theirs, frappe.get_list(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0))
		frappe.set_user(BOB)
		self.assertIn(theirs, frappe.get_list(SHARED_CHILD, parent_doctype="Event", pluck="name", limit=0))

	def test_a_singles_own_child_table_still_lists(self):
		frappe.set_user("Administrator")
		for df in frappe.get_meta("FCRM Settings").get_table_fields():
			with self.subTest(table=df.options):
				rows = frappe.get_list(df.options, parent_doctype="FCRM Settings", pluck="name", limit=0)
				stored = frappe.get_all(df.options, filters={"parenttype": "FCRM Settings"}, pluck="name")
				self.assertCountEqual(rows, stored)

	# --- ignore_user_permissions from the request -----------------------------

	def restricted_to_one_lead(self) -> tuple[str, str]:
		"""Two leads of Alice's, and a User Permission that leaves her one."""
		frappe.set_user("Administrator")
		names = []
		for first_name in ("Alice allowed", "Alice withheld"):
			lead = frappe.get_doc({"doctype": "CRM Lead", "lead_owner": ALICE, "first_name": first_name})
			lead.flags.ignore_mandatory = True
			names.append(lead.insert(ignore_permissions=True).name)
			self.addCleanup(frappe.delete_doc, "CRM Lead", names[-1], force=True, ignore_permissions=True)
		# a lead is shared with its owner, and a share outranks a User Permission
		frappe.db.delete("DocShare", {"share_doctype": "CRM Lead", "share_name": ("in", names)})
		permission = frappe.get_doc(
			{"doctype": "User Permission", "user": ALICE, "allow": "CRM Lead", "for_value": names[0]}
		).insert(ignore_permissions=True)
		self.addCleanup(
			frappe.delete_doc, "User Permission", permission.name, force=True, ignore_permissions=True
		)
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(ALICE)
		return names[0], names[1]

	def listed_by_the_report_view(self) -> list[str]:
		return [row["name"] for row in reportview_get_list()]

	def test_a_request_cannot_set_user_permissions_aside(self):
		allowed, withheld = self.restricted_to_one_lead()
		self.request(REPORT_VIEW, doctype="CRM Lead", fields='["name"]', ignore_user_permissions="1")
		engine_guard.guard_request()
		self.assertNotIn("ignore_user_permissions", frappe.form_dict)
		self.assertEqual(frappe.form_dict.doctype, "CRM Lead")
		names = self.listed_by_the_report_view()
		self.assertIn(allowed, names)
		self.assertNotIn(withheld, names)

	def test_without_the_guard_the_request_flag_lists_what_was_withheld(self):
		"""Why the flag is dropped; when this fails the report view strips it itself."""
		from frappe.desk import reportview

		_allowed, withheld = self.restricted_to_one_lead()
		self.request(REPORT_VIEW, doctype="CRM Lead", fields='["name"]')
		self.assertNotIn(withheld, self.listed_by_the_report_view())
		frappe.form_dict.ignore_user_permissions = "1"
		# as frappe ships it, without the key install() adds
		shipped = tuple(p for p in reportview.DISALLOWED_PARAMS if p != "ignore_user_permissions")
		with patch.object(reportview, "DISALLOWED_PARAMS", shipped):
			self.assertIn(withheld, self.listed_by_the_report_view())

	def test_the_report_view_drops_the_flag_however_it_got_there(self):
		"""An endpoint that sets a call's arguments after before_request, as frappe's
		MCP does, is past drop_request_flag; the report view strips the key itself."""
		from frappe.desk import reportview
		from frappe.desk.doctype.kanban_board.kanban_board import get_kanban_reportview_args

		self.assertIn("ignore_user_permissions", reportview.DISALLOWED_PARAMS)
		allowed, withheld = self.restricted_to_one_lead()
		self.request(REPORT_VIEW, doctype="CRM Lead", fields='["name"]')
		engine_guard.guard_request()
		frappe.form_dict.ignore_user_permissions = "1"
		names = self.listed_by_the_report_view()
		self.assertIn(allowed, names)
		self.assertNotIn(withheld, names)
		self.assertNotIn("ignore_user_permissions", reportview.get_form_params())
		frappe.form_dict.board_name = "a board"
		self.assertNotIn("ignore_user_permissions", get_kanban_reportview_args()[-1])
		# and what frappe stripped before is still stripped
		for param in ("cmd", "data", "ignore_permissions", "view", "user", "csrf_token", "join"):
			self.assertIn(param, reportview.DISALLOWED_PARAMS)

	def test_the_flag_is_added_to_the_report_view_once_and_its_absence_is_reported(self):
		from frappe.desk import reportview

		before = reportview.DISALLOWED_PARAMS
		engine_guard.install()
		self.assertIs(reportview.DISALLOWED_PARAMS, before)
		self.assertEqual(before.count("ignore_user_permissions"), 1)
		shipped = tuple(p for p in before if p != "ignore_user_permissions")
		with patch.object(reportview, "DISALLOWED_PARAMS", shipped):
			self.assertFalse(engine_guard.installed())
			engine_guard.install()
			self.assertTrue(engine_guard.installed())
			self.assertEqual(reportview.DISALLOWED_PARAMS, (*shipped, "ignore_user_permissions"))
		# a frappe that no longer keeps the list: requests go on, the migrate does not
		gone = types.ModuleType("frappe.desk.reportview")
		with patch.dict(sys.modules, {"frappe.desk.reportview": gone}), patch("frappe.desk.reportview", gone):
			engine_guard.guard_request()
			self.assertFalse(engine_guard.installed())
			with self.assertRaises(frappe.ValidationError):
				engine_guard.ensure_installed()
		self.assertTrue(engine_guard.installed())

	def test_the_flag_is_dropped_however_the_method_is_named(self):
		dropped = [
			(REPORT_VIEW, {}),
			("/api/method/frappe.desk.reportview.get_count", {}),
			("/api/method/frappe.desk.reportview.export_query", {}),
			("/api/method/frappe.desk.doctype.kanban_board.kanban_board.get_kanban_board_data", {}),
			("/api/v2/method/frappe.desk.reportview.get", {}),
			("/api/resource/CRM Lead", {}),
			("/", {"cmd": "frappe.desk.reportview.get"}),
			# frappe.app runs cmd before it looks at the path
			(f"/api/method/{LINK_SEARCH}", {"cmd": "frappe.desk.reportview.get"}),
			(f"/api/method/{LINK_SEARCH}", {"cmd": ["frappe.desk.search.search_link"]}),
			# v2 reads two segments as a doctype and its controller's method
			(f"/api/v2/method/{LINK_SEARCH}/get", {}),
			("/api/method/frappe.desk.searchx", {}),
			# only the one method of frappe.client, by its whole name
			("/api/method/frappe.client.get_list", {}),
			("/api/method/frappe.client.get_count", {}),
			(f"/api/method/{LINK_VALIDATION}x", {}),
			(f"/api/method/{LINK_VALIDATION}", {"cmd": "frappe.desk.reportview.get"}),
			(f"/app/{LINK_SEARCH}", {}),
		]
		for path, form in dropped:
			with self.subTest(path=path, form=form):
				self.request(path, ignore_user_permissions="1", doctype="CRM Lead", **form)
				engine_guard.guard_request()
				self.assertNotIn("ignore_user_permissions", frappe.form_dict)
				self.assertEqual(frappe.form_dict.doctype, "CRM Lead")

	def test_a_link_search_keeps_the_flag_for_frappe_to_validate(self):
		kept = [
			(f"/api/method/{LINK_SEARCH}", {}),
			("/api/method/frappe.desk.search.search_widget", {}),
			(f"/api/v1/method/{LINK_SEARCH}", {}),
			(f"/api/v2/method/{LINK_SEARCH}", {}),
			("/", {"cmd": LINK_SEARCH}),
			# the link control's second call, with the same arguments
			(f"/api/method/{LINK_VALIDATION}", {}),
			(f"/api/v2/method/{LINK_VALIDATION}", {}),
			("/", {"cmd": LINK_VALIDATION}),
		]
		for path, form in kept:
			with self.subTest(path=path, form=form):
				self.request(path, ignore_user_permissions="1", **form)
				engine_guard.guard_request()
				self.assertEqual(frappe.form_dict.ignore_user_permissions, "1")

	def test_link_validation_hands_the_flag_to_the_search_and_nowhere_else(self):
		"""What makes it safe to keep: the day frappe uses it for more, this fails."""
		import inspect

		from frappe import client

		source = inspect.getsource(client.validate_link_and_fetch)
		self.assertNotIn("ignore_user_permissions", source)
		self.assertIn("search_widget", source)
		self.assertIn("**search_args", source)
		self.assertNotIn("search_args", source.split("search_widget,", 1)[1].split(")", 1)[1])
		from frappe.desk.search import search_widget

		self.assertIn("validate_ignore_user_permissions", inspect.getsource(search_widget))

	def test_a_link_field_that_ignores_user_permissions_validates_what_it_offered(self):
		"""The desk searches, then validates, with one set of arguments. Dropping the
		flag from the second cleared a value the first had just offered."""
		from frappe.client import validate_link_and_fetch
		from frappe.desk.search import search_link

		allowed, withheld = self.restricted_to_one_lead()
		field = frappe.get_meta("CRM Deal").get_field("lead")
		self.assertEqual(field.options, "CRM Lead")
		self.addCleanup(setattr, field, "ignore_user_permissions", field.ignore_user_permissions)
		field.ignore_user_permissions = 1
		args = {"reference_doctype": "CRM Deal", "link_fieldname": "lead", "ignore_user_permissions": "1"}

		self.request(f"/api/method/{LINK_SEARCH}", doctype="CRM Lead", txt=withheld, **args)
		frappe.local.request.method = "POST"
		engine_guard.guard_request()
		offered = [row["value"] for row in search_link(**frappe.form_dict)]
		self.assertIn(withheld, offered)

		self.request(f"/api/method/{LINK_VALIDATION}", doctype="CRM Lead", docname=withheld, **args)
		frappe.local.request.method = "POST"
		engine_guard.guard_request()
		self.assertEqual(validate_link_and_fetch(**frappe.form_dict).get("name"), withheld)

		# a field without the option gets no such favour, flag or not
		field.ignore_user_permissions = 0
		self.request(f"/api/method/{LINK_VALIDATION}", doctype="CRM Lead", docname=withheld, **args)
		frappe.local.request.method = "POST"
		engine_guard.guard_request()
		self.assertEqual(frappe.form_dict.ignore_user_permissions, "1")
		with self.assertRaises((frappe.ValidationError, frappe.PermissionError)):
			validate_link_and_fetch(**frappe.form_dict)
		frappe.form_dict.pop("ignore_user_permissions")
		self.assertFalse(validate_link_and_fetch(**frappe.form_dict))
		self.assertTrue(validate_link_and_fetch(doctype="CRM Lead", docname=allowed).get("name"))

	# --- frappe's MCP endpoint ---------------------------------------------------

	def test_the_mcp_endpoint_is_refused(self):
		for path in ("/api/v2/mcp", "/api/v2/mcp/", "/api/v2/mcp/anything", "/api/mcp", "/api/V2/MCP"):
			with self.subTest(path=path):
				self.request(path, ignore_user_permissions="1")
				with self.assertRaisesRegex(frappe.PermissionError, "not available"):
					engine_guard.guard_request()
				with self.assertRaisesRegex(frappe.PermissionError, "not available"):
					document_guard.reserve_action()
		for path in ("/api/v2/method/ping", "/api/v2/mcpx", "/api/method/mcp", "/app/mcp", "/mcp"):
			with self.subTest(path=path):
				self.request(path)
				engine_guard.guard_request()

	def test_this_frappe_has_no_mcp_endpoint_to_lose(self):
		"""Refusing the path costs nothing while this holds. When it fails, frappe has
		grown the endpoint: read engine_guard's note on it before allowing it."""
		import importlib.util

		self.assertIsNone(importlib.util.find_spec("frappe.mcp"))
		self.assertNotIn("enable_mcp", [df.fieldname for df in frappe.get_meta("System Settings").fields])

	def test_a_job_has_no_request_to_clean(self):
		for attr in ("form_dict", "request"):
			if hasattr(frappe.local, attr):
				self.addCleanup(setattr, frappe.local, attr, getattr(frappe.local, attr))
				delattr(frappe.local, attr)
		engine_guard.guard_request()
		document_guard.reserve_action()

	def test_a_doctype_named_as_its_own_parent_keeps_its_row_rules(self):
		names = frappe.get_list("CRM Lead", parent_doctype="CRM Lead", pluck="name", limit=0)
		self.assertNotIn(self.bobs_lead, names)

	def test_the_server_setting_permissions_aside_is_not_a_request(self):
		# frappe.get_all never asks the builders to check anything
		names = frappe.get_all("CRM Lead", parent_doctype=SINGLE, pluck="name", limit=0)
		self.assertIn(self.bobs_lead, names)
