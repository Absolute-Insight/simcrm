# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

"""The columns every scoped query filters on have to be indexed.

Frappe does not index a Link field on its own, so an index only exists if the
doctype JSON asks for one (``search_index``) or a doctype's
``on_doctype_update`` adds it. These are the ones the hierarchy filter, the
kanban, the snapshot job and every Won aggregate range-scan, and they were all
unindexed: at MBP scale each scoped list page was a full table scan per rep per
request.

This reads the shipped JSON rather than ``frappe.get_meta`` or
``frappe.db.has_index`` deliberately. Both of those answer a question about the
*site the test happens to run on* -- whether someone has migrated it with this
branch checked out -- rather than about what the app ships, so on a shared bench
they go red for reasons that have nothing to do with the code. What migrate then
does with the flag is Frappe's job and is covered by Frappe's own schema tests.
"""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

DOCTYPE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "fcrm", "doctype")

# fieldname -> why it is hot
INDEXED_FIELDS = {
	"crm_deal": {
		"deal_owner": "every non-admin list, count and kanban query filters on it",
		"closed_date": "every Won aggregate range-scans it",
		"expected_closure_date": "the forecast reads open deals by expected close month",
	},
	"crm_lead": {
		"lead_owner": "the hierarchy filter scopes leads by owner",
	},
	"crm_notification": {
		"to_user": "the inbox, its unread count and mark-as-read all filter on the recipient",
	},
}


class HotColumnIndexTest(UnitTestCase):
	def load(self, doctype_dir: str) -> dict:
		path = os.path.join(DOCTYPE_DIR, doctype_dir, f"{doctype_dir}.json")
		with open(path) as f:
			return json.load(f)

	def test_the_scoped_query_columns_declare_an_index(self):
		for doctype_dir, fields in INDEXED_FIELDS.items():
			meta = self.load(doctype_dir)
			by_name = {field["fieldname"]: field for field in meta["fields"]}
			for fieldname, why in fields.items():
				with self.subTest(doctype=meta["name"], fieldname=fieldname):
					self.assertIn(fieldname, by_name)
					self.assertEqual(
						by_name[fieldname].get("search_index"),
						1,
						f"{meta['name']}.{fieldname} needs an index: {why}",
					)


class ToDoScopeIndexTest(UnitTestCase):
	"""ToDo is frappe's table, so its index is added after migrate rather than
	declared. Asked of the app, not of the site, for the reason given above."""

	def test_migrate_adds_the_assignee_index(self):
		from crm import hooks

		self.assertIn("crm.permissions.org_hierarchy.ensure_todo_index", hooks.after_migrate)

	def test_install_adds_it_too(self):
		"""A new site has no migrate until its first upgrade."""
		import inspect

		from crm import install

		self.assertIn("ensure_todo_index()", inspect.getsource(install.after_install))

	def test_the_index_is_on_the_table_and_covers_the_filter(self):
		"""Asked of the database: ``add_index`` is idempotent, so calling it here
		creates the index on a site that has not migrated since and is a no-op on
		one that has. ``allocated_to`` leads -- it is the one column that narrows
		to a rep's own rows -- and the rest is the sub-select's WHERE."""
		from crm.permissions.org_hierarchy import (
			TODO_SCOPE_INDEX,
			_permission_query_conditions,
			ensure_todo_index,
		)

		ensure_todo_index()
		indexes: dict[str, list[str]] = {}
		for row in frappe.db.sql("show index from `tabToDo`", as_dict=True):
			indexes.setdefault(row.Key_name, []).append((row.Seq_in_index, row.Column_name))
		columns = [[name for _seq, name in sorted(parts)] for parts in indexes.values()]
		self.assertIn(TODO_SCOPE_INDEX, columns)
		self.assertEqual(TODO_SCOPE_INDEX[0], "allocated_to")

		with (
			patch("crm.permissions.org_hierarchy.sees_everything", return_value=False),
			patch("crm.permissions.org_hierarchy.hierarchy_enabled", return_value=False),
		):
			sql = _permission_query_conditions("index-rep@crmtest.test", "CRM Deal").get_sql(quote_char="`")
		assigned = sql[sql.index("FROM `tabToDo`") :]
		for column in TODO_SCOPE_INDEX:
			with self.subTest(column=column):
				self.assertIn(f"`{column}`", assigned)
